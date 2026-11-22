#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G5-a: runner-only pytest plugin that records every test's duration as local gate evidence.

gate_runner.run_stage loads it for one gate process only, through PYTEST_ADDOPTS
("-p scripts.gate_durations") plus HHAI_GATE_DURATIONS_PREFIX (the gate's raw sidecar path).
CI and verify_all never set either variable, so CI behaviour is unchanged.

The plugin only observes test reports: it never changes an outcome, a collection or the exit status.
Each pytest session writes "<prefix>.durations-<tag>.tsv", where <tag> is derived from the session's
own arguments, so the two pytest gates inside verify_all never overwrite each other. A record that
cannot be written is reported as one "GATE_DURATIONS_UNAVAILABLE <reason>" line; it is diagnostic
data, never acceptance evidence. Both variables are removed from os.environ at configure time so that
pytest processes started by the tests themselves never inherit the plugin.

TD-100: each session also keeps "<prefix>.progress-<tag>.json" up to date while it runs (completed test count, the
test running now and the last finished one), so a gate that is killed on timeout still says how far it got. The
record is one small file held open and rewritten in place at every test start (no per-test open or rename).
scripts/gate_report.py turns it into the fixed GATE_PROGRESS lines.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

PREFIX_ENV = 'HHAI_GATE_DURATIONS_PREFIX'
ADDOPT = '-p scripts.gate_durations'
PHASES = ('setup', 'call', 'teardown')

PROGRESS_INFIX = '.progress-'
PROGRESS_WIDTH = 1024
PROGRESS_MAX_NODEID = 300

_prefix = None
_rows = {}
_progress = {'handle': None, 'completed': 0, 'running': None, 'last': None}


def _scrub_environment():
    """Remove the runner-only settings so that nested pytest processes start clean."""
    prefix = os.environ.pop(PREFIX_ENV, None)
    addopts = os.environ.get('PYTEST_ADDOPTS')
    if addopts is not None:
        rest = ' '.join(addopts.replace(ADDOPT, ' ').split())
        if rest:
            os.environ['PYTEST_ADDOPTS'] = rest
        else:
            del os.environ['PYTEST_ADDOPTS']
    return prefix


def _short(nodeid):
    return nodeid if isinstance(nodeid, str) and len(nodeid) <= PROGRESS_MAX_NODEID else None


def _write_progress():
    """Rewrite the progress record in place; diagnostic data, so a write problem is ignored."""
    handle = _progress['handle']
    if handle is None:
        return
    text = json.dumps({'schema_version': 1, 'completed': _progress['completed'], 'running': _progress['running'],
                       'last': _progress['last']}, ensure_ascii=True)
    try:
        handle.seek(0)
        handle.write(text.ljust(PROGRESS_WIDTH))
        handle.truncate()  # also flushes, so a killed run still leaves the record; it cuts any tail of an older, longer write
    except (OSError, ValueError):
        _progress['handle'] = None


def _close_progress():
    handle = _progress['handle']
    _progress['handle'] = None
    if handle is not None:
        try:
            handle.close()
        except OSError:
            pass


def pytest_configure(config):
    global _prefix
    _prefix = _scrub_environment() or None
    _rows.clear()
    _close_progress()
    _progress.update(completed=0, running=None, last=None)
    if _prefix:
        path = _prefix + PROGRESS_INFIX + session_tag(config.invocation_params.args) + '.json'
        try:
            _progress['handle'] = open(path, 'w', encoding='utf-8', newline='')
            _write_progress()
        except OSError:
            _progress['handle'] = None


def pytest_runtest_logstart(nodeid, location):
    _progress['running'] = _short(nodeid)
    _write_progress()


def pytest_runtest_logreport(report):
    row = _rows.setdefault(report.nodeid, {'setup': 0.0, 'call': 0.0, 'teardown': 0.0, 'outcome': None})
    if report.when in PHASES:
        row[report.when] = float(report.duration)
    if report.when == 'call' or (report.when == 'setup' and report.outcome != 'passed'):
        row['outcome'] = report.outcome
    elif report.outcome == 'failed':
        row['outcome'] = 'error'
    if report.when == 'teardown':
        _progress['completed'] += 1
        _progress['last'] = _short(report.nodeid)
        _progress['running'] = None


def session_tag(args):
    return hashlib.sha256(json.dumps(list(args), ensure_ascii=True).encode('utf-8')).hexdigest()[:12]


def render(args, rows):
    lines = ['# args=' + json.dumps(list(args), ensure_ascii=True),
             'nodeid\tsetup\tcall\tteardown\ttotal\toutcome']
    for nodeid in sorted(rows):
        r = rows[nodeid]
        total = r['setup'] + r['call'] + r['teardown']
        lines.append('\t'.join([nodeid] + ['%.3f' % r[p] for p in PHASES] + ['%.3f' % total, str(r['outcome'])]))
    return '\n'.join(lines) + '\n'


def pytest_sessionfinish(session, exitstatus):
    _write_progress()
    _close_progress()
    if not _prefix:
        return
    args = session.config.invocation_params.args
    path = Path(_prefix + '.durations-' + session_tag(args) + '.tsv')
    tmp = path.with_name(path.name + '.tmp')
    try:
        with open(tmp, 'x', encoding='utf-8', newline='\n') as f:
            f.write(render(args, _rows))
        os.replace(tmp, path)
    except OSError as exc:
        sys.stderr.write('GATE_DURATIONS_UNAVAILABLE ' + type(exc).__name__ + '\n')
        sys.stderr.flush()
