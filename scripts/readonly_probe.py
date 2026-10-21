#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fixed, fail-closed C9 read-only probe dispatcher. NEVER authorizes recovery.

There is no generic shell, external command, eval, script or path argument.
A delivered prompt may only select the one reviewed, constant C9 probe.
For defense in depth, verify the installed dispatcher, referenced guards, and
prompt against the bound local Git commit before invoking any probes.
"""
import argparse
import hashlib
import json
import os
import pathlib
import stat
import subprocess
import sys

PROBE_ID = 'C9_RECOVERY_PREFLIGHT_V1'
S1_TASK = 'B119-N7N8-POSTMAIN-STATE-R1-261018'
S1_BASE = 'fdd59488a0632d0654fc6a1251bba004502cef51'
CODE_PATHS = ('scripts/readonly_probe.py', 'scripts/prompt_builder.py',
              'scripts/batch_runner.py', 'scripts/c9_base_guard.py',
              'scripts/c9_local_history_guard.py', 'scripts/c9_s1_capture_guard.py',
              'scripts/s1_evidence.py', 'scripts/s1_full_capture.py')


def _fail(code):
    print('C9_READONLY_JSON=' + json.dumps({'status': 'HOLD', 'reason': code,
          'authorization': 'NONE'}, sort_keys=True, separators=(',', ':')))
    return 1


def _git(repo, *args):
    try:
        cp = subprocess.run(['git', '--no-optional-locks', '-C', str(repo), *args],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=20,
                            env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0',
                                 'GIT_TERMINAL_PROMPT': '0'})
        if cp.returncode:
            raise ValueError('GIT_INSPECT_FAILED')
        return cp.stdout
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('GIT_INSPECT_FAILED') from None


def _identity(repo, base):
    if _git(repo, 'rev-parse', '--is-shallow-repository').strip() != b'false':
        raise ValueError('SHALLOW_REPO')
    if _git(repo, 'rev-parse', '--verify', 'HEAD^{commit}').strip().decode('ascii') != base:
        raise ValueError('HEAD_DRIFT')
    if _git(repo, 'rev-parse', '--verify', 'refs/remotes/origin/main').strip().decode('ascii') != base:
        raise ValueError('ORIGIN_MAIN_DRIFT')
    for rel in CODE_PATHS:
        path = repo / rel
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise ValueError('PROBE_CODE_UNSAFE')
        actual = path.read_bytes()
        expected = _git(repo, 'show', base + ':' + rel)
        if hashlib.sha256(actual).digest() != hashlib.sha256(expected).digest():
            raise ValueError('PROBE_CODE_DRIFT')


def execute(repo, spec):
    """All inputs already validated by batch_runner.load_spec, rechecked here."""
    if (spec.get('probe_id') != PROBE_ID or spec.get('s1_task_id') != S1_TASK
            or spec.get('s1_base_oid') != S1_BASE):
        raise ValueError('PROBE_ARGS_INVALID')
    # Import only after checking on-disk byte identity to the bound Base.
    from c9_base_guard import classify
    from c9_local_history_guard import inventory
    from c9_s1_capture_guard import validate_capture, CaptureGuardError
    base = spec['base_oid']
    base_result = classify(repo, base)
    history_result = inventory(repo, base)
    try:
        capture = validate_capture(repo, S1_TASK, S1_BASE)
        credential = {'status': 'SNAPSHOT_VERIFIED_ONLY', 'reason': 'CREDENTIAL_NOT_RECOVERY_PERMIT'}
    except CaptureGuardError as exc:
        credential = {'status': 'HOLD', 'reason': str(exc)}
    except Exception:
        credential = {'status': 'HOLD', 'reason': 'CAPTURE_QUERY_FAILED'}
    combined = 'SNAPSHOT_VERIFIED_ONLY' if all((
        base_result.get('status') == 'READY',
        history_result.get('status') == 'READY',
        credential['status'] == 'SNAPSHOT_VERIFIED_ONLY')) else 'HOLD'
    result = {'status': combined, 'authorization': 'NONE',
              'restoration_authorized': False, 'deletion_authorized': False,
              'base': {'status': base_result.get('status'), 'reason': base_result.get('reason')},
              'history': {'status': history_result.get('status'), 'reason': history_result.get('reason')},
              'credential': credential}
    print('C9_READONLY_JSON=' + json.dumps(result, sort_keys=True, separators=(',', ':')))
    # Never return 0 as recovery permitted, including snapshot verified.
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--task-id', required=True)
    ap.add_argument('--prompt-file', required=True)
    args = ap.parse_args(argv)
    repo = pathlib.Path(__file__).resolve().parent.parent
    if args.prompt_file != '.git/' + args.task_id + '-prompt.txt':
        return _fail('PROMPT_PATH_INVALID')
    try:
        import re
        file = repo / args.prompt_file
        if file.is_symlink() or not file.is_file() or file.stat().st_size > 160000:
            raise ValueError('PROMPT_FILE_INVALID')
        raw = file.read_bytes()
        if len(raw) > 160000 or b'\r' in raw or b'\0' in raw:
            raise ValueError('PROMPT_BYTES_INVALID')
        # Bootstrap identity using only Python stdlib; do not import replaceable
        # project helpers before verifying exact Git-tracked tool bytes.
        marker = re.search(rb'(?m)^<<<BEGIN BATCH_SPEC_JSON>>>\n([^<]{1,10000})\n<<<END BATCH_SPEC_JSON>>>$', raw)
        if marker is None:
            raise ValueError('SPEC_MISSING')
        bootstrap = json.loads(marker.group(1).decode('utf-8', 'strict'))
        base = bootstrap.get('base_oid')
        if (not isinstance(base, str) or re.fullmatch('[0-9a-f]{40}', base) is None
                or bootstrap.get('task_id') != args.task_id or bootstrap.get('kind') != 'readonly'):
            raise ValueError('SPEC_BOOTSTRAP_INVALID')
        _identity(repo, base)
        import batch_runner
        import prompt_builder
        lines = batch_runner.prompt_lines(raw)
        spec = batch_runner.load_spec(lines, args.task_id)
        if spec.get('kind') != 'readonly' or spec['base_oid'] != base:
            raise ValueError('SPEC_KIND_INVALID')
        # Full canonical check re-verifies must-read, contract, and governance
        # on these exact prompt bytes before dispatching any C9 query.
        prompt_builder.check(str(repo), str(file))
        return execute(repo, spec)
    except Exception:
        return _fail('PROBE_PREFLIGHT_FAILED')


if __name__ == '__main__':
    raise SystemExit(main())
