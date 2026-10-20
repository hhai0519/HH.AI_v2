# -*- coding: utf-8 -*-
"""Synthetic Git fixtures for C9 safe return Base guard; no real refs written."""
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import c9_base_guard as guard


def git(repo, *args):
    p = subprocess.run(['git', '-C', str(repo), *args], check=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=15)
    return p.stdout.decode('utf-8').strip()


def fixture(tmp_path):
    origin = tmp_path/'origin.git'; work = tmp_path/'work'
    subprocess.run(['git', 'init', '-q', '--bare', str(origin)], check=True)
    subprocess.run(['git', 'init', '-q', str(work)], check=True)
    git(work, 'config', 'user.name', 'Test')
    git(work, 'config', 'user.email', 'test@example.invalid')
    (work/'x.txt').write_text('initial\n')
    git(work, 'add', 'x.txt'); git(work, 'commit', '-qm', 'base')
    base = git(work, 'rev-parse', 'HEAD')
    git(work, 'branch', '-M', 'main')
    git(work, 'remote', 'add', 'origin', str(origin))
    git(work, 'push', '-q', 'origin', 'main')
    git(origin, 'symbolic-ref', 'HEAD', 'refs/heads/main')
    git(work, 'fetch', '-q', 'origin', 'main')
    return origin, work, base


def snapshot(work, origin):
    return (git(work, 'show-ref'), git(work, 'status', '--porcelain=v1', '--untracked-files=all'),
            git(work, 'rev-parse', 'HEAD'), git(origin, 'show-ref'))


def test_at_base_clean_old_branch_no_detach(tmp_path):
    origin, work, base = fixture(tmp_path)
    git(work, 'switch', '-qc', 'batch/old-u04')
    before = snapshot(work, origin)
    assert guard.classify(work, base) == {'status':'READY','reason':'AT_BASE_NO_SWITCH_NEEDED',
            'head':base,'branch':'batch/old-u04','remote_main':base}
    assert snapshot(work, origin) == before


def test_unpushed_s1_commit_holds_and_keeps_branch_and_bytes(tmp_path):
    origin, work, base = fixture(tmp_path)
    git(work,'switch','-qc','batch/s1-halted')
    (work/'x.txt').write_text('historical S1 evidence remains\n')
    git(work,'add','x.txt'); git(work,'commit','-qm','unpublished S1')
    before=snapshot(work,origin)
    result=guard.classify(work,base)
    assert result['status']=='HOLD' and result['reason']=='LOCAL_COMMIT_PRESERVE'
    assert snapshot(work,origin)==before
    assert (work/'x.txt').read_text()=='historical S1 evidence remains\n'


def test_untracked_and_tracked_dirty_both_halt(tmp_path):
    origin,work,base=fixture(tmp_path)
    (work/'dont-delete.tmp').write_text('S1 evidence')
    assert guard.classify(work,base)['reason']=='DIRTY_PRESERVE'
    assert (work/'dont-delete.tmp').exists()
    (work/'dont-delete.tmp').unlink()
    (work/'x.txt').write_text('dirty')
    assert guard.classify(work,base)['reason']=='DIRTY_PRESERVE'


def test_main_drift_halts_without_fetch(tmp_path):
    origin,work,base=fixture(tmp_path)
    (origin/'dummy').write_text('x')
    other=tmp_path/'other'
    subprocess.run(['git','clone','-q',str(origin),str(other)],check=True)
    git(other,'checkout','-q','main')
    git(other,'config','user.name','Test');git(other,'config','user.email','test@example.invalid')
    (other/'y').write_text('changed');git(other,'add','y');git(other,'commit','-qm','remote advanced')
    git(other,'push','-q','origin','main')
    assert guard.classify(work,base)['reason']=='MAIN_DRIFT'
    assert git(work,'rev-parse','HEAD')==base


def test_detached_non_base_holds(tmp_path):
    origin,work,base=fixture(tmp_path)
    git(work,'switch','-qc','batch/s1-local')
    (work/'x.txt').write_text('new\n');git(work,'add','x.txt');git(work,'commit','-qm','local')
    git(work,'switch','-q','--detach','HEAD')
    result=guard.classify(work,base)
    assert result['status']=='HOLD' and result['reason']=='HEAD_NOT_BASE_PRESERVE'


def test_invalid_oid_and_shallow_fail_closed(tmp_path):
    origin,work,base=fixture(tmp_path)
    try:guard.classify(work,'f5e1')
    except RuntimeError as exc:assert str(exc)=='BASE_OID_INVALID'
    else:raise AssertionError('invalid oid accepted')
    shallow=tmp_path/'shallow'
    subprocess.run(['git','clone','--depth=1','-q',origin.resolve().as_uri(),str(shallow)],check=True)
    assert git(shallow,'rev-parse','--is-shallow-repository')=='true'
    try:guard.classify(shallow,base)
    except RuntimeError as exc:assert str(exc)=='SHALLOW_REPO'
    else:raise AssertionError('shallow accepted')


def test_cli_stop_is_single_machine_card(tmp_path,capsys):
    _,work,base=fixture(tmp_path)
    (work/'hidden-name.txt').write_text('secret')
    assert guard.main(['--repo',str(work),'--base-oid',base])==1
    output=capsys.readouterr().out
    assert output.startswith('C9_BASE_GUARD_JSON=')
    assert 'hidden-name.txt' not in output and 'secret' not in output


def test_git_status_does_not_refresh_index_and_optional_locks_disabled(tmp_path, monkeypatch):
    origin, work, base = fixture(tmp_path)
    git(work, 'switch', '-qc', 'batch/old-u04')
    index = work / '.git' / 'index'
    original_index = index.read_bytes()
    original_mtime_ns = index.stat().st_mtime_ns
    original = guard.subprocess.run
    calls = []
    def track(*args, **kwargs):
        cmd = args[0]
        if isinstance(cmd, list) and '--no-optional-locks' in cmd:
            assert cmd[:2] == ['git', '--no-optional-locks']
            assert kwargs['env'].get('GIT_OPTIONAL_LOCKS') == '0'
            calls.append(cmd)
        return original(*args, **kwargs)
    monkeypatch.setattr(guard.subprocess, 'run', track)
    result = guard.classify(work, base)
    assert result['reason'] == 'AT_BASE_NO_SWITCH_NEEDED'
    assert len(calls) >= 5 and any('status' in x for x in calls)
    assert index.read_bytes() == original_index
    assert index.stat().st_mtime_ns == original_mtime_ns
