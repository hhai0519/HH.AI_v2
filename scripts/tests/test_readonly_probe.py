# -*- coding: utf-8 -*-
"""B115/B119 C9: registered fixed probe; deny all write and recovery semantics."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(DIR))
import readonly_probe as rp

BASE = 'b86ff4c5a651ffd5938dc5d65ea5f3c198b3d9d1'
SPEC = {'probe_id':rp.PROBE_ID, 's1_task_id':rp.S1_TASK,
        's1_base_oid':rp.S1_BASE, 'base_oid':BASE}


def test_probe_ids_are_fixed_and_no_shell_surface():
    for key, val in [('probe_id','PUSH'), ('s1_task_id','arbitrary'), ('s1_base_oid','a'*40)]:
        with pytest.raises(ValueError, match='PROBE_ARGS_INVALID'):
            rp.execute('/fake', dict(SPEC, **{key:val}))


def test_probe_main_rejects_noncanonical_path_before_any_reads(monkeypatch,capsys):
    monkeypatch.setattr(rp, '_identity', lambda *a: (_ for _ in ()).throw(AssertionError('never')))
    assert rp.main(['--task-id','TEST-READONLY-261021','--prompt-file','../../bad']) == 1
    assert 'PROMPT_PATH_INVALID' in capsys.readouterr().out


def test_capture_hold_is_never_authorized(monkeypatch,capsys):
    import c9_base_guard
    import c9_local_history_guard
    import c9_s1_capture_guard
    monkeypatch.setattr(c9_base_guard,'classify',lambda *a:{'status':'READY','reason':'AT_BASE_NO_SWITCH_NEEDED'})
    monkeypatch.setattr(c9_local_history_guard,'inventory',lambda *a:{'status':'READY','reason':'NO_LOCAL_DELTA'})
    def missing(*a): raise c9_s1_capture_guard.CaptureGuardError('CAPTURE_MISSING')
    monkeypatch.setattr(c9_s1_capture_guard,'validate_capture',missing)
    assert rp.execute('/fake',dict(SPEC)) == 1
    obj=json.loads(capsys.readouterr().out.split('=',1)[1]);assert obj['status']=='HOLD'
    assert obj['authorization']=='NONE' and obj['credential']['reason']=='CAPTURE_MISSING'
    assert obj['restoration_authorized'] is False


def test_snapshot_verified_is_nonzero_not_restore(monkeypatch,capsys):
    import c9_base_guard
    import c9_local_history_guard
    import c9_s1_capture_guard
    monkeypatch.setattr(c9_base_guard,'classify',lambda *a:{'status':'READY','reason':'AT_BASE_NO_SWITCH_NEEDED'})
    monkeypatch.setattr(c9_local_history_guard,'inventory',lambda *a:{'status':'READY','reason':'NO_LOCAL_DELTA'})
    monkeypatch.setattr(c9_s1_capture_guard,'validate_capture',lambda *a:{'status':'SNAPSHOT_VERIFIED_ONLY'})
    assert rp.execute('/fake',dict(SPEC)) == 1
    obj=json.loads(capsys.readouterr().out.split('=',1)[1])
    assert obj['status']=='SNAPSHOT_VERIFIED_ONLY' and obj['authorization']=='NONE'
    assert obj['deletion_authorized'] is False and obj['restoration_authorized'] is False


def test_code_identity_fails_closed_on_modified_copy(monkeypatch,tmp_path):
    root=tmp_path/'repo';root.mkdir();(root/'scripts').mkdir();
    for rel in rp.CODE_PATHS:
        p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'original')
    def fake_git(repo,*args):
        if args[-1]=='--is-shallow-repository':return b'false\n'
        if args[-1]=='HEAD^{commit}':return (BASE+'\n').encode()
        if args[-1]=='refs/remotes/origin/main':return (BASE+'\n').encode()
        return b'original'
    monkeypatch.setattr(rp,'_git',fake_git)
    rp._identity(root,BASE)
    (root/'scripts/readonly_probe.py').write_bytes(b'altered')
    with pytest.raises(ValueError,match='PROBE_CODE_DRIFT'):
        rp._identity(root,BASE)


def _setup_identity_case(monkeypatch, tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    (root / 'scripts').mkdir()
    for rel in rp.CODE_PATHS:
        file = root / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b'original')

    def fake_git(repo, *args):
        if args[-1] == '--is-shallow-repository':
            return b'false\n'
        if args[-1] == 'HEAD^{commit}':
            return (BASE + '\n').encode()
        if args[-1] == 'refs/remotes/origin/main':
            return (BASE + '\n').encode()
        return b'original'

    monkeypatch.setattr(rp, '_git', fake_git)
    return root


def _symlink_or_capability_skip(path, target):
    try:
        path.symlink_to(target)
    except OSError as exc:
        # Only the exact Windows permission failure is a capability skip.
        if getattr(exc, 'winerror', None) == 1314:
            pytest.skip('WIN_SYMLINK_PRIVILEGE_UNAVAILABLE')
        raise


def test_unsafe_identity_path_rejected(monkeypatch, tmp_path):
    # Mandatory type rejection: does not depend on symlink privileges.
    root = _setup_identity_case(monkeypatch, tmp_path)
    path = root / 'scripts/readonly_probe.py'
    path.unlink()
    path.mkdir()
    with pytest.raises(ValueError, match='PROBE_CODE_UNSAFE'):
        rp._identity(root, BASE)


def test_unsafe_identity_symlink_rejected(monkeypatch, tmp_path):
    root = _setup_identity_case(monkeypatch, tmp_path)
    path = root / 'scripts/readonly_probe.py'
    path.unlink()
    _symlink_or_capability_skip(path, 'batch_runner.py')
    with pytest.raises(ValueError, match='PROBE_CODE_UNSAFE'):
        rp._identity(root, BASE)


def test_windows_symlink_privilege_1314_is_bounded_skip(monkeypatch, tmp_path):
    err = OSError('synthetic Windows symbolic link privilege failure')
    err.winerror = 1314

    def fail_link(self, target):
        raise err

    monkeypatch.setattr(Path, 'symlink_to', fail_link)
    with pytest.raises(pytest.skip.Exception, match='WIN_SYMLINK_PRIVILEGE_UNAVAILABLE'):
        _symlink_or_capability_skip(tmp_path / 'synthetic', 'target')


def test_unexpected_symlink_oserror_is_not_skipped(monkeypatch, tmp_path):
    err = OSError('synthetic unexpected I/O failure')
    err.winerror = 5

    def fail_link(self, target):
        raise err

    monkeypatch.setattr(Path, 'symlink_to', fail_link)
    with pytest.raises(OSError, match='unexpected I/O failure'):
        _symlink_or_capability_skip(tmp_path / 'synthetic', 'target')
