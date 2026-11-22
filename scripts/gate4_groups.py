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
   The deadline counts from the start of scripts/verify_all.py (the process the runner limits), not from the start of
   the grouped run (alpha batch 1, TD-104).
6. Output order is fixed: plan lines, a progress line every two minutes while phase 1 and then the groups run (phase 1
   prints one too; alpha batch 1, TD-104), then phase 1 and the groups in index order, each with a header line and
   its complete pytest output, then one result line.
7. The test count is checked per test file as well as in total: the JUnit test cases of every process are mapped to
   their test file and compared with the collected count of each file (alpha batch 1, TD-104). A mismatch adds the
   reason FILE_COUNT_MISMATCH and one GATE4_FILE_MISMATCH line per file (raw output only).
8. Beside the raw output the gate writes one JSON record (<raw>.gate4-groups.json, schema_version 1) with the result
   fields and the per-group lines; scripts/gate_report.py turns it into the fixed GATE4_GROUPS_RESULT and GATE4_GROUP
   lines of an Executor reply (alpha batch 1, TD-112). The record is diagnostic data, never acceptance evidence.

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
RECORD_SUFFIX = '.gate4-groups.json'
MAX_FILE_MISMATCH_LINES = 20
HEARTBEAT_SEC = 120
DEFAULT_WEIGHT = 1.0
# Test files whose tests depend on real time limits, process-tree kills or Node child processes: they run alone.
SEQUENTIAL_FILES = (
    'scripts/tests/test_batch_runner.py',
    'scripts/tests/test_batch_sim.py',
    'scripts/tests/test_bounded_process.py',
    'scripts/tests/test_c9_s1_capture_guard.py',
    'scripts/tests/test_channel_gateway_core.py',
    'scripts/tests/test_gate_report.py',
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


def classname_file(classname, files):
    """The test file a JUnit classname belongs to (module path with dots, optional class parts), or None."""
    for name in files:
        stem = name[:-3].replace('/', '.') if name.endswith('.py') else name.replace('/', '.')
        if classname == stem or classname.startswith(stem + '.'):
            return name
    return None


def read_junit_files(path, files):
    """({file: test case count}, unmapped test case count) over the JUnit file of one process."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError('JUNIT_UNREADABLE') from exc
    counts, unmapped = {}, 0
    for case in root.iter('testcase'):
        name = classname_file(case.attrib.get('classname', ''), files)
        if name is None:
            unmapped += 1
        else:
            counts[name] = counts.get(name, 0) + 1
    return counts, unmapped


def write_record(path, record):
    """Write the JSON record beside the raw output (temp file, then replace); True when written."""
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + '\n')
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


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
                clock=time.monotonic, out=None, tmp_parent=None, started=None):
    """Return None when grouping does not apply (the caller runs the sequential command), else 0 or 1.

    started is the clock value the deadline counts from (the start of verify_all, TD-104); None means now.
    """
    out = out or (lambda text: print(text, flush=True))
    n = group_count(os.cpu_count() if cpu_count is None else cpu_count)
    if n < 2:
        out('GATE4_GROUPS mode=SEQUENTIAL reason=GROUP_COUNT_BELOW_2 groups=%d' % n)
        return None
    started = clock() if started is None else started
    prefix, target, extra = list(cmd[:3]), cmd[3], list(cmd[4:])
    root = tempfile.mkdtemp(prefix='hhai-gate4-', dir=tmp_parent)
    try:
        return _run(prefix, target, extra, env, cwd, n, started, root, timings_path, sequential, runner,
                    deadline_sec, heartbeat_sec, collect_timeout, clock, out)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _record_path(env):
    prefix = (env or {}).get(LOCAL_GATE_ENV)
    return (prefix + RECORD_SUFFIX) if prefix else None


def _save_record(record_path, record, out):
    if record_path is None:
        return
    if not write_record(record_path, record):
        out('GATE4_GROUPS_RECORD_UNAVAILABLE')


def _early_record(status_reason):
    return {'schema_version': 1, 'status': 'FAIL', 'collected': 0, 'counted': 0, 'passed': 0, 'skipped': 0,
            'failures': 0, 'errors': 0, 'phase1_sec': 0.0, 'groups_sec': 0.0, 'total_sec': 0.0,
            'reasons': [status_reason], 'groups': []}


def _run(prefix, target, extra, env, cwd, n, started, root, timings_path, sequential, runner, deadline_sec,
         heartbeat_sec, collect_timeout, clock, out):
    record_path = _record_path(env)

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
        _save_record(record_path, _early_record('COLLECT_FAILED'), out)
        return 1
    nodeids, declared = parse_collect(ctext)
    if not nodeids or (declared is not None and declared != len(nodeids)):
        out('GATE4_GROUPS_RESULT status=FAIL reasons=COLLECT_COUNT_MISMATCH listed=%d declared=%s'
            % (len(nodeids), declared))
        _save_record(record_path, _early_record('COLLECT_COUNT_MISMATCH'), out)
        return 1
    collected = len(nodeids)
    files = files_of(nodeids)
    expected = {}
    for nid in nodeids:
        name = NODEID.match(nid).group('file')
        expected[name] = expected.get(name, 0) + 1
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

    def run_phase(phase_jobs):
        """Run the jobs of one phase at the same time; print a progress line every heartbeat while they run."""
        if not phase_jobs:
            return
        all_done = threading.Event()
        pending = [len(phase_jobs)]
        lock = threading.Lock()

        def launch_and_count(name, fl):
            try:
                launch(name, fl)
            finally:
                with lock:
                    pending[0] -= 1
                    if pending[0] == 0:
                        all_done.set()

        threads = [threading.Thread(target=launch_and_count, args=(name, fl), daemon=True) for name, fl in phase_jobs]
        for thread in threads:
            thread.start()
        while not all_done.wait(timeout=heartbeat_sec or None):
            out('GATE4_PROGRESS elapsed_sec=%.0f %s' % (clock() - started, ' '.join(
                '%s=%s' % (name, ('done' if name in results else _tail_progress(os.path.join(root, name + '.out'))))
                for name, _ in phase_jobs)))
        for thread in threads:
            thread.join()

    p1_start = clock()
    run_phase(jobs)
    p1_sec = clock() - p1_start
    p2_start = clock()
    run_phase(group_jobs)
    p2_sec = clock() - p2_start

    reasons, tests_sum, failures_sum, errors_sum, skipped_sum = [], 0, 0, 0, 0
    counted_files, unmapped_total = {}, 0
    record_groups = []
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
        try:
            by_file, unmapped = read_junit_files(os.path.join(root, name + '.xml'), fl)
            for fname, number in by_file.items():
                counted_files[fname] = counted_files.get(fname, 0) + number
            unmapped_total += unmapped
        except ValueError:
            pass  # the unreadable record already added its reason above
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
        record_groups.append({'name': name, 'rc': r['rc'] if type(r['rc']) is int else None, 'sec': round(r['sec'], 1),
                              'files': len(fl), 'tests': counts[0] if counts else None})
        text = _decode(r['stdout'])
        if text:
            out(text)
    if tests_sum != collected:
        reasons.append('COUNT_MISMATCH')
    # Per-file check (TD-104): only when every process produced a readable record, so an unreadable or missing
    # process is reported by its own reason and not by a second, derived one.
    if not any(r_.endswith(('JUNIT_UNREADABLE', 'JUNIT_NO_SUITE', 'JUNIT_ATTRIBUTE', 'NO_RESULT')) for r_ in reasons):
        mismatched = sorted(f for f in set(expected) | set(counted_files) if expected.get(f, 0) != counted_files.get(f, 0))
        if mismatched or unmapped_total:
            reasons.append('FILE_COUNT_MISMATCH')
            for fname in mismatched[:MAX_FILE_MISMATCH_LINES]:
                out('GATE4_FILE_MISMATCH file=%s expected=%d counted=%d' % (fname, expected.get(fname, 0), counted_files.get(fname, 0)))
            if unmapped_total:
                out('GATE4_FILE_MISMATCH file=UNMAPPED expected=0 counted=%d' % unmapped_total)
    status = 'PASS' if not reasons else 'FAIL'
    total_sec = clock() - started
    out('GATE4_GROUPS_RESULT status=%s collected=%d counted=%d passed=%d skipped=%d failures=%d errors=%d '
        'phase1_sec=%.1f groups_sec=%.1f total_sec=%.1f reasons=%s' % (
            status, collected, tests_sum, tests_sum - failures_sum - errors_sum - skipped_sum, skipped_sum,
            failures_sum, errors_sum, p1_sec, p2_sec, total_sec, ','.join(reasons) if reasons else 'NONE'))
    _save_record(record_path, {
        'schema_version': 1, 'status': status, 'collected': collected, 'counted': tests_sum,
        'passed': tests_sum - failures_sum - errors_sum - skipped_sum, 'skipped': skipped_sum,
        'failures': failures_sum, 'errors': errors_sum, 'phase1_sec': round(p1_sec, 1), 'groups_sec': round(p2_sec, 1),
        'total_sec': round(total_sec, 1), 'reasons': reasons, 'groups': record_groups}, out)
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
