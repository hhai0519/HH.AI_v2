#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/gate_report.py

Fixed-shape diagnostic lines for an Executor reply (alpha batch 1: D2, TD-100, TD-104, TD-112).

The runner prints only a fixed vocabulary into a reply (scripts/batch_runner.py bounded_summary): raw gate output
stays in the task-local .raw sidecars. This module reads those sidecars and the structured records the local gate
leaves beside them, and returns lines whose every token is validated; nothing is echoed unchecked.

  S1 failed list (D2)            S1_FAILED_LIST kind=GATE_FAILED count=<rows> shown=<n> [unsafe=<n>]
                                 S1_FAILED_LIST kind=CI_FAILED count=<n> shown=<n>
                                 S1_FAILED_LIST kind=FAILED_LIST_UNAVAILABLE reason=<fixed reason>
                                 S1_FAILED_ITEM <test id>  |  S1_FAILED_ITEM job=<job> conclusion=<conclusion>
  timeout progress (TD-100)      GATE_PROGRESS stage=... run=... gate=... procs=... completed=...
                                 GATE_PROGRESS_PROC idx=... completed=... running=<name|none|withheld> last=<same>

Test names (alpha 1 D-SO B1): count is the number of FAILED/ERROR rows, whatever their names look like. A name that is
a safe node id is shown as it is; a parametrized id that is not safe (spaces, escapes, <>, ...) is shown reduced to the
part before its first "[" plus the fixed mark "[*]" (once per reduced name); a row whose name cannot be shown at all is
counted in unsafe. shown is the number of listed names, so shown + unsafe <= count. Progress names use the same reduced
form, and the fixed word "withheld" when nothing can be shown; a progress record is never dropped for its names.
  grouped gate 4 result (TD-112) GATE4_GROUPS_RESULT status=... collected=... (one line)
                                 GATE4_GROUP name=<seq|gN> rc=... sec=... files=... tests=...

Sources and trust:
  * failed test names come from the lines of pytest's "short test summary info" sections in the raw sidecar of the
    failing stage (several sections when gate 4 ran in groups). They are diagnostics, never acceptance evidence:
    a test that prints such a line itself could add a name, so a name is only listed, never counted as proof.
  * the grouped result and the timeout progress come from JSON records written by the gate itself
    (scripts/gate4_groups.py -> <raw>.gate4-groups.json, scripts/gate_durations.py -> <raw>.progress-<tag>.json),
    checked for exact schema and types before any line is built.
Every function returns lines and never raises for bad input: unreadable, missing or malformed sources produce the
fixed "unavailable" form or no line.
"""

import glob
import json
import os
import re

KIND_GATE = 'GATE_FAILED'
KIND_CI = 'CI_FAILED'
KIND_NONE = 'FAILED_LIST_UNAVAILABLE'
KINDS = (KIND_GATE, KIND_CI, KIND_NONE)
REASONS = ('NOT_A_TEST_STEP', 'NO_RAW_OUTPUT', 'NO_NAMES_FOUND', 'LIST_ERROR')
MAX_ITEMS = 20
MAX_PROCS = 8
MAX_NODEID = 300
MAX_SOURCE_BYTES = 64 * 1024 * 1024
# Steps whose child output can name failed tests, and the S1 codes that mean "CI did not pass".
TEST_STEPS = ('focused', 'precommit', 'postcommit')
CI_CODES = frozenset({'CANDIDATE_CI_NOT_PASS', 'CANDIDATE_CI_NOT_PROVEN', 'POST_MAIN_CI_NOT_PASS',
                      'CI_STATUS_NOT_PASS', 'CI_STATUS_JOBS_NOT_PASS'})
CI_JOBS = ('verify', 'gateway-windows')
CI_CONCLUSIONS = ('failure', 'cancelled', 'timed_out', 'skipped', 'action_required', 'neutral', 'stale',
                  'startup_failure', 'in_progress', 'queued', 'none')
STAGE_NAMES = ('PRECOMMIT', 'STAGED', 'POSTCOMMIT')
GROUP_NAMES = ('seq', 'g1', 'g2', 'g3', 'g4')
RESULT_FIELDS = ('collected', 'counted', 'passed', 'skipped', 'failures', 'errors')
SECONDS_FIELDS = ('phase1_sec', 'groups_sec', 'total_sec')
GROUPS_SUFFIX = '.gate4-groups.json'
PROGRESS_INFIX = '.progress-'

NODE_TOKEN = re.compile(r'^[A-Za-z0-9_./-]{1,200}\.py(?:::[A-Za-z0-9_.:\[\]/,=+@*-]{1,200})?$')
SECTION_START = re.compile(r'^=+ short test summary info =+$')
SECTION_ROW = re.compile(r'^(?:FAILED|ERROR|SKIPPED|XFAIL|XPASS) ')
REASON_TOKEN = re.compile(r'^[A-Za-z0-9_:]+(?:,[A-Za-z0-9_:]+)*$')
SEC_TEXT = re.compile(r'^[0-9]{1,7}\.[0-9]$')
RAW_NAME = re.compile(r'^(?P<task>[A-Za-z0-9_-]+)-local-gates\.txt\.(?P<stage>[a-z]+)-run(?P<run>[0-9]+)-gate(?P<gate>[0-9]+)\.raw$')


WITHHELD = 'withheld'
PARAM_MARK = '[*]'
SUMMARY_ROW = re.compile(r'^(?:FAILED|ERROR) (?P<rest>.*)$')


def node_ok(token):
    """A pytest node id (or a bare test file) made of safe characters only, with balanced brackets."""
    return (isinstance(token, str) and len(token) <= MAX_NODEID and NODE_TOKEN.fullmatch(token) is not None
            and token.count('[') == token.count(']'))


def display_id(text):
    """The listable form of a test name: the name itself when it is a safe node id, else (a parametrized id with
    spaces, escapes or other unsafe characters) its part before the first "[" plus the fixed mark "[*]" when that
    part is a safe node id; None when nothing safe can be shown."""
    if not isinstance(text, str):
        return None
    if node_ok(text):
        return text
    cut = text.find('[')
    if cut <= 0:
        return None
    head = text[:cut]
    shown = head + PARAM_MARK
    return shown if node_ok(head) and node_ok(shown) else None


def summary_name(name):
    """The name of a short-summary row with Windows path separators in its file part turned into "/".

    pytest prints a row's file part relative to the invocation directory (config.cwd_relative_nodeid, bestrelpath);
    when that differs from the rootdir on Windows the part uses "\\". Only the part before the first "::" changes;
    a parameter id keeps its characters (it is listed in its reduced form when unsafe)."""
    head, sep, tail = name.partition('::')
    return head.replace('\\', '/') + sep + tail


def parse_failed_rows(text):
    """(items, unsafe, rows) from pytest "short test summary info" sections.

    rows is the number of FAILED/ERROR rows (every one is counted, whatever its name looks like); items are the
    distinct listable names in first-appearance order (display_id of each row's name: the text before the first
    " - " message separator); unsafe is the number of rows whose name cannot be shown at all.
    A section starts at the "=== short test summary info ===" header and lasts while lines start with a pytest
    result word; anything else ends it. Grouped gate output holds several sections.
    """
    items, seen = [], set()
    unsafe = rows = 0
    in_section = False
    for raw in (text or '').replace('\r\n', '\n').split('\n'):
        line = raw.rstrip()
        if SECTION_START.fullmatch(line):
            in_section = True
            continue
        if not in_section:
            continue
        if not SECTION_ROW.match(line):
            in_section = False
            continue
        m = SUMMARY_ROW.match(line)
        if not m:
            continue
        rows += 1
        name = summary_name(m.group('rest').split(' - ', 1)[0].strip())
        shown = display_id(name)
        if shown is None:
            unsafe += 1
        elif shown not in seen:
            seen.add(shown)
            items.append(shown)
    return items, unsafe, rows


def parse_failed_ids(text):
    """(items, unsafe): the listable names and the number of rows whose name cannot be shown (see parse_failed_rows)."""
    items, unsafe, _rows = parse_failed_rows(text)
    return items, unsafe


def _read_text(path):
    try:
        if os.path.getsize(path) > MAX_SOURCE_BYTES:
            return None
        with open(path, 'rb') as handle:
            return handle.read().decode('utf-8', 'replace')
    except OSError:
        return None


def raw_sidecars(root, task_id, stage):
    """{gate index: raw sidecar path} of the highest run of this task's stage under .git/ (empty when none)."""
    pattern = os.path.join(root, '.git', task_id + '-local-gates.txt.' + stage.lower() + '-run*-gate*.raw')
    best_run, found = 0, {}
    for path in glob.glob(pattern):
        m = RAW_NAME.fullmatch(os.path.basename(path))
        if not m or m.group('task') != task_id or m.group('stage') != stage.lower():
            continue
        run, gate = int(m.group('run')), int(m.group('gate'))
        if run > best_run:
            best_run, found = run, {}
        if run == best_run:
            found[gate] = path
    return {'run': best_run, 'paths': found}


def failed_sources(root, task_id, step):
    """Raw texts that may name failed tests for a step: the focused bounded record or the stage's raw sidecars."""
    if step == 'focused':
        path = os.path.join(root, '.git', task_id + '-bounded-focused.txt')
        text = _read_text(path)
        return [] if text is None else [text]
    stage = {'precommit': 'PRECOMMIT', 'postcommit': 'POSTCOMMIT'}.get(step)
    if stage is None:
        return []
    texts = []
    for gate, path in sorted(raw_sidecars(root, task_id, stage)['paths'].items()):
        text = _read_text(path)
        if text is not None:
            texts.append(text)
    return texts


def _list_lines(kind, items, total, reason=None, unsafe=0):
    if kind == KIND_NONE:
        return ['S1_FAILED_LIST kind=' + KIND_NONE + ' reason=' + reason]
    shown = items[:MAX_ITEMS]
    extra = ' unsafe=%d' % unsafe if unsafe else ''
    return (['S1_FAILED_LIST kind=' + kind + ' count=' + str(total) + ' shown=' + str(len(shown)) + extra]
            + ['S1_FAILED_ITEM ' + item for item in shown])


def ci_items(jobs):
    """Failed-job items from a ci-status jobs object; only fixed job names and conclusions are accepted."""
    items = []
    if not isinstance(jobs, dict):
        return items
    for name in CI_JOBS:
        info = jobs.get(name)
        if info is None:
            conclusion = 'none'
        elif isinstance(info, dict) and info.get('status') == 'completed' and info.get('conclusion') == 'success':
            continue
        elif isinstance(info, dict):
            conclusion = info.get('conclusion') if info.get('conclusion') in CI_CONCLUSIONS else (
                'in_progress' if info.get('status') == 'in_progress' else 'queued' if info.get('status') == 'queued' else 'none')
        else:
            conclusion = 'none'
        items.append('job=' + name + ' conclusion=' + conclusion)
    return items


def failed_list_lines(root, task_id, step, code, ci_jobs=None):
    """The one S1 failed list of a persisted S1 inside a step (D2): GATE_FAILED, CI_FAILED or FAILED_LIST_UNAVAILABLE."""
    try:
        if code in CI_CODES:
            items = ci_items(ci_jobs)
            if items:
                return _list_lines(KIND_CI, items, len(items))
            return _list_lines(KIND_NONE, [], 0, 'NO_NAMES_FOUND')
        if step not in TEST_STEPS:
            return _list_lines(KIND_NONE, [], 0, 'NOT_A_TEST_STEP')
        texts = failed_sources(root, task_id, step)
        if not texts:
            return _list_lines(KIND_NONE, [], 0, 'NO_RAW_OUTPUT')
        ids, seen = [], set()
        rows = unsafe = 0
        for text in texts:
            found, bad, count = parse_failed_rows(text)
            rows += count
            unsafe += bad
            for token in found:
                if token not in seen:
                    seen.add(token)
                    ids.append(token)
        if not rows:
            return _list_lines(KIND_NONE, [], 0, 'NO_NAMES_FOUND')
        return _list_lines(KIND_GATE, ids, rows, unsafe=unsafe)
    except Exception:  # noqa: BLE001 - diagnostics never replace the S1 they describe
        return _list_lines(KIND_NONE, [], 0, 'LIST_ERROR')


def _load_json(path):
    try:
        if os.path.getsize(path) > 1024 * 1024:
            return None
        with open(path, 'rb') as handle:
            return json.loads(handle.read().decode('utf-8'))
    except (OSError, ValueError):
        return None


def _int(value):
    return type(value) is int and 0 <= value <= 10 ** 9


def _sec(value):
    return type(value) in (int, float) and not isinstance(value, bool) and 0 <= value < 10 ** 7 and value == value


def groups_lines(root, task_id, stage):
    """TD-112: the grouped gate 4 result as one GATE4_GROUPS_RESULT line and up to five GATE4_GROUP lines.

    Only PRECOMMIT has gate 4. No record (CI, sequential run, old gate) or an invalid record gives no line.
    """
    try:
        if stage != 'PRECOMMIT':
            return []
        info = raw_sidecars(root, task_id, stage)
        raw = info['paths'].get(4)
        if raw is None:
            return []
        doc = _load_json(raw + GROUPS_SUFFIX)
        return render_groups(doc)
    except Exception:  # noqa: BLE001
        return []


def render_groups(doc):
    """Lines for one validated record of scripts/gate4_groups.py (schema_version 1), else []."""
    if not isinstance(doc, dict) or doc.get('schema_version') != 1 or doc.get('status') not in ('PASS', 'FAIL'):
        return []
    if any(not _int(doc.get(k)) for k in RESULT_FIELDS) or any(not _sec(doc.get(k)) for k in SECONDS_FIELDS):
        return []
    reasons = doc.get('reasons')
    if not isinstance(reasons, list) or not all(isinstance(r, str) and REASON_TOKEN.fullmatch(r) for r in reasons):
        return []
    groups = doc.get('groups')
    if not isinstance(groups, list) or len(groups) > len(GROUP_NAMES):
        return []
    lines = []
    names = set()
    for g in groups:
        if (not isinstance(g, dict) or g.get('name') not in GROUP_NAMES or g['name'] in names or not _sec(g.get('sec'))
                or not _int(g.get('files')) or not (g.get('tests') is None or _int(g.get('tests')))
                or not (g.get('rc') is None or (type(g.get('rc')) is int and -1000 <= g['rc'] <= 1000))):
            return []
        names.add(g['name'])
        lines.append('GATE4_GROUP name=%s rc=%s sec=%.1f files=%d tests=%s' % (
            g['name'], 'None' if g['rc'] is None else g['rc'], g['sec'], g['files'],
            'n/a' if g['tests'] is None else g['tests']))
    result = ('GATE4_GROUPS_RESULT status=%s collected=%d counted=%d passed=%d skipped=%d failures=%d errors=%d '
              'phase1_sec=%.1f groups_sec=%.1f total_sec=%.1f reasons=%s' % (
                  doc['status'], doc['collected'], doc['counted'], doc['passed'], doc['skipped'], doc['failures'],
                  doc['errors'], doc['phase1_sec'], doc['groups_sec'], doc['total_sec'],
                  ','.join(reasons) if reasons else 'NONE'))
    return [result] + lines


def _progress_name(name):
    """A test name of a progress record as shown: none, the safe display form, or the fixed word withheld."""
    if name is None or name == '':
        return 'none'
    return display_id(name) or WITHHELD


def progress_lines(root, task_id, stage):
    """TD-100: completed test count and the last/running test names of a gate that timed out.

    Reads every <raw>.progress-<tag>.json of the highest-numbered gate of the stage that has any. One
    GATE_PROGRESS line (total) and up to eight GATE_PROGRESS_PROC lines (one per pytest process).
    """
    try:
        if stage not in STAGE_NAMES:
            return []
        info = raw_sidecars(root, task_id, stage)
        chosen = None
        for gate in sorted(info['paths'], reverse=True):
            files = sorted(glob.glob(glob.escape(info['paths'][gate]) + PROGRESS_INFIX + '*.json'))
            if files:
                chosen = (gate, files)
                break
        if chosen is None:
            return []
        gate, files = chosen
        procs = []
        for path in files[:MAX_PROCS + 1]:
            doc = _load_json(path)
            if (not isinstance(doc, dict) or doc.get('schema_version') != 1 or not _int(doc.get('completed'))
                    or not all(doc.get(k) is None or isinstance(doc.get(k), str) for k in ('running', 'last'))):
                return []
            procs.append(doc)
        if len(procs) > MAX_PROCS:
            return []
        total = sum(p['completed'] for p in procs)
        lines = ['GATE_PROGRESS stage=%s run=%d gate=%d procs=%d completed=%d' % (stage, info['run'], gate, len(procs), total)]
        for i, p in enumerate(procs, 1):
            lines.append('GATE_PROGRESS_PROC idx=%d completed=%d running=%s last=%s' % (
                i, p['completed'], _progress_name(p['running']), _progress_name(p['last'])))
        return lines
    except Exception:  # noqa: BLE001
        return []


def gate_lines(root, task_id, stage, timed_out):
    """Lines printed by Batch.bounded after a gate stage: grouped result (PRECOMMIT) and timeout progress."""
    lines = groups_lines(root, task_id, stage)
    if timed_out:
        lines += progress_lines(root, task_id, stage)
    return lines
