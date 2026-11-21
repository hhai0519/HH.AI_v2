#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/gate4_groups.py

Grouped concurrent execution of the unit-test gate (gate 4 of scripts/verify_all.py) for the LOCAL runner gate
(D9 batch 1; USER decision 2026-11-21: shorten gate 4, never relax acceptance).

The sequential gate 4 runs every test of scripts/tests in one pytest process (about 30 minutes on the USER's
Windows laptop, limit 3600 seconds). This module splits the same tests into groups that run at the same time:

  phase 1  the "crowd-sensitive" test files (real timeouts, process-tree kills, Node child processes) run
           alone, one pytest process, so nothing competes with them;
  phase 2  every other test file is split into N = min(4, cpu_count // 2) groups (at least 1; with fewer than
           2 groups nothing changes and the sequential command runs) and the groups run concurrently.

Contract (every item has a test in scripts/tests/test_gate4_groups.py):
1. Only the local runner gate enables it: scripts/verify_all.py asks `requested(env, cmd)`, which needs the
   runner-only variable HHAI_GATE_DURATIONS_PREFIX (the local gate runner sets it; CI and a direct run of
   verify_all never do) and the canonical full gate 4 command. CI therefore stays sequential.
2. The grouping is deterministic: files come from `pytest --collect-only -q` of the same target, weights come
   from scripts/gate4_timings.json (seconds per test file; a file missing from it, or an unusable table, gets the
   median weight, or 1.0), and files are assigned by LPT (heaviest first, to the least loaded group, ties to
   the lowest group index).
3. Each pytest process has its own --basetemp, no cache provider and its own JUnit XML file; the per-session
   duration plugin of the runner (scripts/gate_durations.py) names its record by the session's own arguments, so
   the processes never overwrite each other.
4. The gate passes only if every process exited 0 without timeout or launch error, every JUnit file is readable
   with zero failures and errors, and the number of test cases counted over all processes equals the number
   of tests collected (a missing or extra test is a FAIL). Nothing is skipped or downgraded.
5. The whole gate has an internal deadline (3300 seconds) below the runner's limit (3600 seconds) so that a
   too-slow run fails cleanly with per-group progress in the raw output instead of being killed by the runner.
6. Output order is fixed: plan lines, a progress line every two minutes while groups run, then phase 1 and the
   groups in index order, each with a header line and its complete pytest output, then one result line.

  python scripts/gate4_groups.py calibrate TSV [TSV ...]   print a timing table from runner duration records
"""

import argparse
import json
import math
import os
import re
import shutil
import statistics
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bounded_process import run_bounded  # noqa: E402

TIMINGS_FILE = os.path.join(REPO_ROOT, 'scripts', 'gate4_timings.json')
LOCAL_GATE_ENV = 'HHAI_GATE_DURATIONS_PREFIX'
MAX_GROUPS = 4
DEADLINE_SEC = 3300
COLLECT_TIMEOUT_SEC = 900
HEARTBEAT_SEC = 120
DEFAULT_WEIGHT = 1.0
# Test files whose tests depend on real time limits, process-tree kills or Node child processes: they run alone.
SEQUENTIAL_FILES = (
    'scripts/tests/test_batch_runner.py',
    'scripts/tests/test_batch_sim.py',
    'scripts/tests/test_bounded_process.py',
    'scripts/tests/test_c9_s1_capture_guard.py',
    'scripts/tests/test_channel_gateway_core.py',
    'scripts/tests/test_gate_runner.py',
    'scripts/tests/test_s1_full_capture.py',
)
NODEID = re.compile(r'^(?P<file>[^\s:][^\r\n]*?\.py)::')
COLLECTED = re.compile(r'^(\d+) tests? collected')
PROGRESS = re.compile(r'\[\s*(\d+)%\]')


def group_count(cpu_count):
    """N = min(4, cpu_count // 2), at least 1."""
    try:
        n = int(cpu_count)
    except (TypeError, ValueError):
        return 1
    return max(1, min(MAX_GROUPS, n // 2))


def canonical_cmd(cmd):
    """The full gate 4 command only: python -m pytest <target> ..., never a collect-only variant."""
    return (isinstance(cmd, (list, tuple)) and len(cmd) >= 4 and list(cmd[1:3]) == ['-m', 'pytest']
            and not any(str(a).startswith('--collect-only') for a in cmd))


def requested(env, cmd):
    return bool((env or {}).get(LOCAL_GATE_ENV)) and canonical_cmd(cmd)


def load_timings(path=TIMINGS_FILE):
    """({file: seconds}, note). Any problem returns ({}, reason): the plan then uses default weights."""
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            doc = json.load(handle)
        files = doc['files']
        if doc.get('schema_version') != 1 or not isinstance(files, dict):
            raise ValueError('SCHEMA')
        table = {}
        for name, seconds in files.items():
            if (not isinstance(name, str) or isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                    or not math.isfinite(seconds) or seconds < 0):
                raise ValueError('VALUE')
            table[name] = float(seconds)
        return table, 'OK'
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {}, 'UNAVAILABLE:' + type(exc).__name__


def parse_collect(text):
    """(node ids in order, declared count or None) from `pytest --collect-only -q` output."""
    ids, declared = [], None
    for raw in text.replace('\r\n', '\n').split('\n'):
        line = raw.strip()
        if NODEID.match(line):
            ids.append(line.replace('\\', '/'))
            continue
        m = COLLECTED.match(line)
        if m:
            declared = int(m.group(1))
    return ids, declared


def files_of(nodeids):
    seen, files = set(), []
    for nid in nodeids:
        name = NODEID.match(nid).group('file')
        if name not in seen:
            seen.add(name)
            files.append(name)
    return files


def plan_groups(files, timings, n_groups, sequential=SEQUENTIAL_FILES):
    """Deterministic plan: (phase 1 files, [group files ...], [group estimates])."""
    phase1 = sorted(f for f in files if f in set(sequential))
    rest = [f for f in files if f not in set(sequential)]
    known = sorted(v for k, v in timings.items())
    default = statistics.median(known) if known else DEFAULT_WEIGHT
    weight = {f: timings.get(f, default) for f in rest}
    n = max(1, min(n_groups, len(rest))) if rest else 0
    groups = [[] for _ in range(n)]
    loads = [0.0] * n
    for f in sorted(rest, key=lambda x: (-weight[x], x)):
        i = min(range(n), key=lambda k: (loads[k], k))
        groups[i].append(f)
        loads[i] += weight[f]
    return phase1, [sorted(g) for g in groups], [round(x, 1) for x in loads]


def build_cmd(prefix, extra, files, basetemp, junit):
    return (list(prefix) + ['-p', 'no:cacheprovider', '--basetemp', basetemp, '--junitxml', junit,
                            '-o', 'junit_family=xunit2'] + list(extra) + list(files))


def read_junit(path):
    """(tests, failures, errors, skipped) summed over the suites of one JUnit file; ValueError if unusable."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError('JUNIT_UNREADABLE') from exc
    suites = [root] if root.tag == 'testsuite' else list(root.iter('testsuite'))
    if not suites:
        raise ValueError('JUNIT_NO_SUITE')
    total = [0, 0, 0, 0]
    for suite in suites:
        try:
            for i, key in enumerate(('tests', 'failures', 'errors', 'skipped')):
                total[i] += int(suite.attrib[key])
        except (KeyError, ValueError) as exc:
            raise ValueError('JUNIT_ATTRIBUTE') from exc
    return tuple(total)


def _tail_progress(path):
    try:
        with open(path, 'rb') as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 4096))
            hits = PROGRESS.findall(handle.read().decode('utf-8', 'replace'))
        return (hits[-1] + '%') if hits else 'start'
    except OSError:
        return 'n/a'


def _decode(data):
    return (data or b'').decode('utf-8', 'replace').replace('\r\n', '\n').rstrip('\n')


def run_grouped(cmd, env, cwd, *, cpu_count=None, timings_path=TIMINGS_FILE, sequential=SEQUENTIAL_FILES,
                runner=run_bounded, deadline_sec=DEADLINE_SEC, heartbeat_sec=HEARTBEAT_SEC, collect_timeout=COLLECT_TIMEOUT_SEC,
                clock=time.monotonic, out=None, tmp_parent=None):
    """Return None when grouping does not apply (the caller runs the sequential command), else 0 or 1."""
    out = out or (lambda text: print(text, flush=True))
    n = group_count(os.cpu_count() if cpu_count is None else cpu_count)
    if n < 2:
        out('GATE4_GROUPS mode=SEQUENTIAL reason=GROUP_COUNT_BELOW_2 groups=%d' % n)
        return None
    started = clock()
    prefix, target, extra = list(cmd[:3]), cmd[3], list(cmd[4:])
    root = tempfile.mkdtemp(prefix='hhai-gate4-', dir=tmp_parent)
    try:
        return _run(prefix, target, extra, env, cwd, n, started, root, timings_path, sequential, runner,
                    deadline_sec, heartbeat_sec, collect_timeout, clock, out)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _run(prefix, target, extra, env, cwd, n, started, root, timings_path, sequential, runner, deadline_sec,
         heartbeat_sec, collect_timeout, clock, out):
    def remaining():
        return deadline_sec - (clock() - started)

    cres = runner(prefix + [target, '--collect-only', '-q', '-p', 'no:cacheprovider'], cwd,
                  max(1, min(collect_timeout, remaining())), env=env, merge_stderr=True,
                  capture_path=os.path.join(root, 'collect.out'))
    ctext = _decode(cres.stdout)
    if cres.launch_error or cres.timed_out or cres.returncode != 0:
        out('GATE4_GROUPS_RESULT status=FAIL reasons=COLLECT_FAILED rc=%s timed_out=%s launch_error=%s'
            % (cres.returncode, cres.timed_out, cres.launch_error))
        out(ctext)
        return 1
    nodeids, declared = parse_collect(ctext)
    if not nodeids or (declared is not None and declared != len(nodeids)):
        out('GATE4_GROUPS_RESULT status=FAIL reasons=COLLECT_COUNT_MISMATCH listed=%d declared=%s'
            % (len(nodeids), declared))
        return 1
    collected = len(nodeids)
    files = files_of(nodeids)
    timings, note = load_timings(timings_path)
    phase1, groups, loads = plan_groups(files, timings, n, sequential)
    out('GATE4_GROUPS mode=GROUPED groups=%d cpu_groups=%d collected=%d files=%d sequential_files=%d timings=%d(%s)'
        % (len(groups), n, collected, len(files), len(phase1), len(timings), note))
    if phase1:
        out('GATE4_PLAN phase=1 files=%d: %s' % (len(phase1), ' '.join(phase1)))
    for i, (g, est) in enumerate(zip(groups, loads), 1):
        out('GATE4_PLAN group=g%d files=%d est_sec=%s: %s' % (i, len(g), est, ' '.join(g)))

    jobs = ([('seq', phase1)] if phase1 else [])
    group_jobs = [('g%d' % i, g) for i, g in enumerate(groups, 1)]
    results = {}

    def launch(name, fl):
        t0 = clock()
        left = remaining()
        if left <= 0:
            results[name] = dict(rc=None, timed_out=True, launch_error=None, stdout=b'', sec=0.0, files=fl,
                                 skipped_by_deadline=True)
            return
        res = runner(build_cmd(prefix, extra, fl, os.path.join(root, 'bt-' + name), os.path.join(root, name + '.xml')),
                     cwd, max(1, left), env=env, merge_stderr=True, capture_path=os.path.join(root, name + '.out'))
        results[name] = dict(rc=res.returncode, timed_out=res.timed_out, launch_error=res.launch_error,
                             stdout=res.stdout, sec=clock() - t0, files=fl)

    p1_start = clock()
    for name, fl in jobs:
        launch(name, fl)
    p1_sec = clock() - p1_start
    p2_start = clock()
    all_done = threading.Event()
    pending = [len(group_jobs)]
    lock = threading.Lock()

    def launch_and_count(name, fl):
        try:
            launch(name, fl)
        finally:
            with lock:
                pending[0] -= 1
                if pending[0] == 0:
                    all_done.set()

    if not group_jobs:
        all_done.set()
    threads = [threading.Thread(target=launch_and_count, args=(name, fl), daemon=True) for name, fl in group_jobs]
    for t in threads:
        t.start()
    while not all_done.wait(timeout=heartbeat_sec or None):
        out('GATE4_PROGRESS elapsed_sec=%.0f %s' % (clock() - started, ' '.join(
            '%s=%s' % (name, ('done' if name in results else _tail_progress(os.path.join(root, name + '.out'))))
            for name, _ in group_jobs)))
    for t in threads:
        t.join()
    p2_sec = clock() - p2_start

    reasons, tests_sum, failures_sum, errors_sum, skipped_sum = [], 0, 0, 0, 0
    for name, fl in jobs + group_jobs:
        r = results.get(name)
        if r is None:
            reasons.append(name + ':NO_RESULT')
            continue
        counts = None
        try:
            counts = read_junit(os.path.join(root, name + '.xml'))
        except ValueError as exc:
            reasons.append('%s:%s' % (name, exc))
        if r['launch_error']:
            reasons.append('%s:LAUNCH_ERROR' % name)
        if r['timed_out']:
            reasons.append('%s:TIMEOUT' % name)
        elif r['rc'] != 0 and not r['launch_error']:
            reasons.append('%s:EXIT_%s' % (name, r['rc']))
        if counts:
            tests_sum += counts[0]
            failures_sum += counts[1]
            errors_sum += counts[2]
            skipped_sum += counts[3]
            if counts[1] or counts[2]:
                reasons.append('%s:FAILED_TESTS' % name)
        out('GATE4_GROUP name=%s rc=%s sec=%.1f files=%d tests=%s' % (
            name, r['rc'], r['sec'], len(fl), counts[0] if counts else 'n/a'))
        text = _decode(r['stdout'])
        if text:
            out(text)
    if tests_sum != collected:
        reasons.append('COUNT_MISMATCH')
    status = 'PASS' if not reasons else 'FAIL'
    out('GATE4_GROUPS_RESULT status=%s collected=%d counted=%d passed=%d skipped=%d failures=%d errors=%d '
        'phase1_sec=%.1f groups_sec=%.1f total_sec=%.1f reasons=%s' % (
            status, collected, tests_sum, tests_sum - failures_sum - errors_sum - skipped_sum, skipped_sum,
            failures_sum, errors_sum, p1_sec, p2_sec, clock() - started, ','.join(reasons) if reasons else 'NONE'))
    return 0 if status == 'PASS' else 1


def calibrate(paths):
    """Timing table (JSON text) from runner duration records; ValueError when a record has no usable row."""
    totals = {}
    for path in paths:
        with open(path, 'r', encoding='utf-8') as handle:
            lines = [l.rstrip('\r\n') for l in handle if l.strip() and not l.startswith('#')]
        if not lines or lines[0].split('\t')[:5] != ['nodeid', 'setup', 'call', 'teardown', 'total']:
            raise ValueError('DURATIONS_HEADER:' + os.path.basename(path))
        for line in lines[1:]:
            cells = line.split('\t')
            name = NODEID.match(cells[0])
            if len(cells) < 6 or not name:
                raise ValueError('DURATIONS_ROW:' + os.path.basename(path))
            totals[name.group('file')] = totals.get(name.group('file'), 0.0) + float(cells[4])
    if not totals:
        raise ValueError('DURATIONS_EMPTY')
    doc = {'schema_version': 1, 'unit': 'seconds', 'files': {k: round(v, 1) for k, v in sorted(totals.items())}}
    return json.dumps(doc, ensure_ascii=True, indent=1, sort_keys=True) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Gate 4 grouping helpers (D9 batch 1).')
    sub = parser.add_subparsers(dest='cmd', required=True)
    cal = sub.add_parser('calibrate', help='print a timing table from runner duration records (.tsv)')
    cal.add_argument('tsv', nargs='+')
    args = parser.parse_args(argv)
    try:
        sys.stdout.write(calibrate(args.tsv))
    except (OSError, ValueError) as exc:
        print('GATE4_CALIBRATE FAIL %s' % exc)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
