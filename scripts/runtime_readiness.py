#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G5 admission guard: verify the *running* Python and PATH-selected Node before mutation.

This program is invoked by batch_runner's production-only precontrol admission,
before a task control artifact exists. It uses only Python's standard library and
reads current repository version sources; it does not install or mutate anything.
Unsupported version expressions fail closed until a separately reviewed upgrade.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


class RuntimeMismatch(Exception):
    pass


_VERSION = re.compile(r'^(\d+)\.(\d+)\.(\d+)$')
_NODE_OUT = re.compile(r'^v(\d+)\.(\d+)\.(\d+)$')
_PYTEST_OUT = re.compile(r'^pytest (\d+(?:\.\d+){1,3})$')
_CLAUSE = re.compile(r'^(>=|<=|>|<|=)(\d+)(?:\.(\d+))?(?:\.(\d+))?$')
_PYTEST_PIN = re.compile(r'^pytest==([0-9]+(?:\.[0-9]+){1,3})$')


def _read(root, relative):
    p = Path(root) / relative
    try:
        if p.is_symlink() or not p.is_file() or p.stat().st_size > 32768:
            raise RuntimeMismatch('SOURCE_INVALID')
        return p.read_text(encoding='utf-8')
    except (OSError, UnicodeError, ValueError):
        raise RuntimeMismatch('SOURCE_UNREADABLE') from None


def _pins(root):
    lines = [s.strip() for s in _read(root, 'requirements.txt').splitlines()]
    pins = [m.group(1) for x in lines if (m := _PYTEST_PIN.fullmatch(x))]
    # Other packages whose name starts with pytest (for example pytest-cov) are
    # not the pytest interpreter package; only reject competing pytest pins.
    is_pytest = re.compile(r'^pytest(?=[=<>!~;\s]|$)', re.I)
    if len(pins) != 1 or any(is_pytest.match(x) and not _PYTEST_PIN.fullmatch(x)
                               for x in lines if x and not x.startswith('#')):
        raise RuntimeMismatch('PYTEST_PIN_INVALID')
    baseline = _read(root, '.nvmrc').strip()
    match = _VERSION.fullmatch(baseline)
    if not match:
        raise RuntimeMismatch('NVMRC_INVALID')
    try:
        pkg = json.loads(_read(root, 'runtime/channel-gateway/package.json'))
        clause_text = pkg['engines']['node']
    except (KeyError, TypeError, ValueError):
        raise RuntimeMismatch('ENGINES_INVALID') from None
    if not isinstance(clause_text, str):
        raise RuntimeMismatch('ENGINES_INVALID')
    clauses = []
    for token in clause_text.split():
        m = _CLAUSE.fullmatch(token)
        if not m:
            raise RuntimeMismatch('ENGINES_UNSUPPORTED')
        clauses.append((m.group(1), tuple(int(v or 0) for v in m.groups()[1:])))
    if not clauses:
        raise RuntimeMismatch('ENGINES_UNSUPPORTED')
    return pins[0], tuple(map(int, match.groups())), clauses


def _allowed(version, comparator, bound):
    return {'>=': version >= bound, '>': version > bound,
            '<=': version <= bound, '<': version < bound, '=': version == bound}[comparator]


def _invoke(argv, *, pytest_probe=False):
    try:
        # Keep the admission probe read-only even when the host has pytest
        # plugins or module bytecode generation configured implicitly.
        env = dict(os.environ)
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
        run = subprocess.run(argv, input=b'', stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             timeout=18, check=False, env=env)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeMismatch('PROCESS_UNAVAILABLE') from None
    if run.returncode != 0 or len(run.stdout) > 512:
        # Classify only Python's known missing-module diagnostic; never echo stderr.
        if pytest_probe and run.returncode != 0 and b'No module named pytest' in run.stderr:
            raise RuntimeMismatch('PYTEST_UNAVAILABLE')
        raise RuntimeMismatch('PROCESS_NONZERO')
    try:
        return run.stdout.decode('ascii').strip()
    except UnicodeDecodeError:
        raise RuntimeMismatch('PROCESS_OUTPUT_INVALID') from None


def check(root):
    pytest_pin, baseline, clauses = _pins(root)
    python = sys.executable
    if not python or 'windowsapps' in python.replace('\\', '/').lower().split('/'):
        raise RuntimeMismatch('PYTHON_ALIAS_FORBIDDEN')
    # Calling -m with *this* executable validates importability, not merely metadata
    # belonging to another Python installation or the first `python` in PATH.
    pytest_output = _invoke([python, '-m', 'pytest', '--version'], pytest_probe=True)
    p = _PYTEST_OUT.fullmatch(pytest_output)
    if not p or p.group(1) != pytest_pin:
        raise RuntimeMismatch('PYTEST_MISMATCH')
    node = shutil.which('node')
    if not node:
        raise RuntimeMismatch('NODE_MISSING')
    if 'windowsapps' in node.replace('\\', '/').lower().split('/'):
        raise RuntimeMismatch('NODE_ALIAS_FORBIDDEN')
    node_output = _invoke([node, '--version'])
    n = _NODE_OUT.fullmatch(node_output)
    if not n:
        raise RuntimeMismatch('NODE_VERSION_INVALID')
    version = tuple(map(int, n.groups()))
    # .nvmrc is the reviewed baseline, not an exact patch-version equality gate.
    # The channel-gateway engines expression is authoritative for all range limits.
    if version < baseline or not all(_allowed(version, op, bound) for op, bound in clauses):
        raise RuntimeMismatch('NODE_RANGE_MISMATCH')
    return {'python': python, 'pytest': p.group(1), 'node': node_output,
            'nvmrc': '.'.join(map(str, baseline))}


def main():
    try:
        value = check(Path(__file__).resolve().parent.parent)
    except RuntimeMismatch as exc:
        print('RUNTIME_MISMATCH ' + str(exc))
        return 1
    print('RUNTIME_READY pytest=' + value['pytest'] + ' node=' + value['node']
          + ' python=' + value['python'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
