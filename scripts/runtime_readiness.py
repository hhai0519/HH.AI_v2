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
import stat
import tomllib
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


# F-UV-A1: production admission must run before the runner creates any control
# artifact.  Never use `uv run` as an admission probe: it can create `.venv` or
# synchronize it even with --offline, --locked, and --no-sync combinations.
_PIN_LINE = re.compile(r'^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9._+!-]*)$')
# Real `uv --version` output carries a parenthesised build/target suffix,
# e.g. 'uv 0.11.32 (3010295ae 2026-07-23 x86_64-pc-windows-msvc)' on Windows and
# 'uv 0.11.32 (x86_64-unknown-linux-gnu)' on Linux; accept exactly one such group.
_UV_VER = re.compile(r'^uv (\d+\.\d+\.\d+)(?:\+[^\s]+)?(?: \([^()\r\n]{1,80}\))?$')


def _pin_set(text):
    result = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        parts = re.split(r'\s*;\s*', line, maxsplit=1)
        m = _PIN_LINE.fullmatch(parts[0].strip())
        if not m or len(parts) > 2:
            raise RuntimeMismatch('UV_EXPORT_PIN_INVALID')
        package = re.sub(r'[-_.]+', '-', m.group(1).lower())
        value = package + '==' + m.group(2)
        if len(parts) == 2:
            marker = re.sub(r'\s+', ' ', parts[1].replace('"', "'").strip())
            if marker != "sys_platform == 'win32'":
                raise RuntimeMismatch('UV_EXPORT_MARKER_UNSUPPORTED')
            value += ';' + marker
        if any(x.startswith(package + '==') for x in result):
            raise RuntimeMismatch('UV_EXPORT_DUPLICATE_PIN')
        result.add(value)
    if not result:
        raise RuntimeMismatch('UV_EXPORT_EMPTY')
    return result


def _uv_call(uv, args, root, *, output_limit=8192):
    # Admission must remain read-only even if the caller supplies a simulation
    # cache override. Simulation cache belongs to batch_sim setup, never to
    # production runtime admission. uv's own cache is disabled altogether.
    env = {k: v for k, v in os.environ.items() if not k.startswith('UV_')
           and k not in ('VIRTUAL_ENV', 'PYTHONHOME', 'HHAI_SIM_UV_CACHE_DIR')}
    env['UV_NO_CACHE'] = '1'
    env['UV_OFFLINE'] = '1'
    env['UV_NO_PROGRESS'] = '1'
    env['UV_PYTHON_DOWNLOADS'] = 'never'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    try:
        result = subprocess.run([uv, '--no-config', *args], cwd=str(root), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                check=False, env=env, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeMismatch('UV_UNAVAILABLE') from None
    if result.returncode != 0:
        raise RuntimeMismatch('UV_COMMAND_NONZERO')
    if len(result.stdout) > output_limit or len(result.stderr) > 4096:
        raise RuntimeMismatch('UV_OUTPUT_TOO_LARGE')
    try:
        return result.stdout.decode('utf-8').strip()
    except UnicodeDecodeError:
        raise RuntimeMismatch('UV_OUTPUT_INVALID') from None


def _no_reparse(path):
    """Reject all link/junction components (including the executable) before accepting uv.

    On Windows lstat returns FILE_ATTRIBUTE_REPARSE_POINT for junctions/reparse
    points even when Path.is_symlink() misses them. Avoid chasing anything before
    checking the user-controlled .venv path.
    """
    try:
        info = os.lstat(path)
    except OSError:
        raise RuntimeMismatch('VENV_MISSING') from None
    if stat.S_ISLNK(info.st_mode) or (getattr(info, 'st_file_attributes', 0) & 0x400):
        raise RuntimeMismatch('VENV_REPARSE_FORBIDDEN')
    return info


def uv_admission(root):
    root = Path(root).absolute()
    lock = root / 'uv.lock'
    if lock.is_symlink() or not lock.is_file():
        raise RuntimeMismatch('UV_LOCK_INVALID')
    envdir = root / '.venv'
    pyrel = Path('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    desired = envdir / pyrel
    if not envdir.is_dir() or not desired.is_file():
        raise RuntimeMismatch('VENV_MISSING')
    # Validate the venv container without following any junction/reparse.
    # POSIX uv-managed venvs commonly symlink bin/python -> the base Python,
    # and CPython exposes sys.executable as bin/python3. Both are legitimate.
    for path in (root, envdir, envdir / pyrel.parent):
        _no_reparse(path)
    if os.name == 'nt':
        _no_reparse(desired)   # Windows executable reparse is never allowed
    actual_prefix = os.path.normcase(os.path.realpath(sys.prefix))
    wanted_prefix = os.path.normcase(os.path.realpath(str(envdir)))
    if (actual_prefix != wanted_prefix or
            os.path.normcase(os.path.realpath(sys.prefix)) ==
            os.path.normcase(os.path.realpath(sys.base_prefix))):
        raise RuntimeMismatch('VENV_PYTHON_MISMATCH')
    actual = Path(sys.executable).absolute() if sys.executable else None
    if (actual is None or
            os.path.normcase(os.path.abspath(str(actual.parent))) !=
            os.path.normcase(os.path.abspath(str(envdir / pyrel.parent)))):
        raise RuntimeMismatch('VENV_PYTHON_MISMATCH')
    selected = shutil.which('python')
    if (not selected or os.path.normcase(os.path.abspath(os.path.dirname(selected))) !=
            os.path.normcase(os.path.abspath(str(envdir / pyrel.parent)))):
        raise RuntimeMismatch('PATH_PYTHON_MISMATCH')
    try:
        pyproject = tomllib.loads(_read(root, 'pyproject.toml'))
        uv_required = pyproject['tool']['uv']['required-version']
    except (KeyError, TypeError, ValueError, tomllib.TOMLDecodeError):
        raise RuntimeMismatch('UV_PROJECT_INVALID') from None
    if not isinstance(uv_required, str) or not re.fullmatch(r'==\d+\.\d+\.\d+', uv_required):
        raise RuntimeMismatch('UV_VERSION_SOURCE_INVALID')
    uv = shutil.which('uv')
    if not uv or 'windowsapps' in uv.replace('\\', '/').lower().split('/'):
        raise RuntimeMismatch('UV_UNAVAILABLE')
    version = _uv_call(uv, ['--version'], root, output_limit=150)
    match = _UV_VER.fullmatch(version)
    if match is None or '==' + match.group(1) != uv_required:
        raise RuntimeMismatch('UV_VERSION_MISMATCH')
    # Both commands are offline, read-only with respect to project source, and
    # do not run `uv run` or `uv sync`. Never permit a stale lock or altered pip pin.
    _uv_call(uv, ['lock', '--check', '--offline', '--no-python-downloads'], root)
    export = _uv_call(uv, ['export', '--locked', '--offline', '--no-python-downloads',
                           '--no-hashes', '--no-header', '--no-annotate',
                           '--no-emit-project'], root)
    if _pin_set(_read(root, 'requirements.txt')) != _pin_set(export):
        raise RuntimeMismatch('UV_EXPORT_REQUIREMENTS_MISMATCH')
    pinned_py = _read(root, '.python-version').strip()
    if not re.fullmatch(r'\d+\.\d+', pinned_py):
        raise RuntimeMismatch('UV_PYTHON_VERSION_INVALID')
    if '.'.join(map(str, sys.version_info[:2])) != pinned_py:
        raise RuntimeMismatch('UV_PYTHON_VERSION_MISMATCH')


def check(root):
    # No uv sources in old synthetic fixtures or pre-migration main: legacy G5 tests stay valid.
    # After the uv cutover all production tasks must arrive via the managed .venv.
    if any((Path(root) / name).exists() or (Path(root) / name).is_symlink()
           for name in ('pyproject.toml', 'uv.lock', '.python-version')):
        uv_admission(root)
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
