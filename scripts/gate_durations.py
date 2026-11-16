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
"""
import hashlib
import json
import os
import sys
from pathlib import Path

PREFIX_ENV = 'HHAI_GATE_DURATIONS_PREFIX'
ADDOPT = '-p scripts.gate_durations'
PHASES = ('setup', 'call', 'teardown')

_prefix = None
_rows = {}


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


def pytest_configure(config):
    global _prefix
    _prefix = _scrub_environment() or None
    _rows.clear()


def pytest_runtest_logreport(report):
    row = _rows.setdefault(report.nodeid, {'setup': 0.0, 'call': 0.0, 'teardown': 0.0, 'outcome': None})
    if report.when in PHASES:
        row[report.when] = float(report.duration)
    if report.when == 'call' or (report.when == 'setup' and report.outcome != 'passed'):
        row['outcome'] = report.outcome
    elif report.outcome == 'failed':
        row['outcome'] = 'error'


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
