# -*- coding: utf-8 -*-
"""Synthetic real-Git C9 R2 off-HEAD S1 preservation negative controls."""
import os
import subprocess
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import c9_local_history_guard as inv
from test_c9_base_guard import fixture, git, snapshot


def test_clean_base_on_old_branch_with_no_unique_other_heads_ready(tmp_path):
    origin, work, base = fixture(tmp_path)
    git(work, 'switch', '-qc', 'batch/old-at-base')
    before = snapshot(work, origin)
    result = inv.inventory(work, base)
    assert result['status'] == 'READY' and result['reason'] == 'NO_OFF_HEAD_UNMERGED_HISTORY'
    assert result['authorization'] == 'NONE' and result['snapshot_only'] is True
    assert snapshot(work, origin) == before


def test_off_head_unpublished_s1_commit_holds_even_when_checked_out_base_is_clean(tmp_path):
    origin, work, base = fixture(tmp_path)
    git(work, 'switch', '-qc', 'batch/unpublished-s1')
    (work/'s1.txt').write_text('keep original S1\n')
    git(work, 'add', 's1.txt'); git(work, 'commit', '-qm', 'unpublished local S1')
    s1_tip = git(work, 'rev-parse', 'HEAD')
    git(work, 'switch', '-q', '-c', 'batch/old-u04', base)
    assert git(work, 'status', '--porcelain=v1', '--untracked-files=all') == ''
    before = snapshot(work, origin)
    result = inv.inventory(work, base)
    assert result == {'status':'HOLD','reason':'OFF_HEAD_HISTORY_PRESERVE'}
    assert snapshot(work, origin) == before
    assert git(work, 'rev-parse', 'refs/heads/batch/unpublished-s1') == s1_tip
    assert git(work, 'show', 'batch/unpublished-s1:s1.txt') == 'keep original S1'


def test_off_head_diverged_branch_holds_even_if_another_branch_is_clean(tmp_path):
    origin, work, base = fixture(tmp_path)
    git(work, 'switch','-qc','batch/diverged')
    (work/'x.txt').write_text('divergent\n')
    git(work,'add','x.txt'); git(work,'commit','-qm','diverged')
    git(work,'switch','-q','main')
    assert inv.inventory(work,base)['reason']=='OFF_HEAD_HISTORY_PRESERVE'


def test_already_merged_old_tip_allowed(tmp_path):
    origin, work, base = fixture(tmp_path)
    git(work,'switch','-qc','batch/old')
    git(work,'switch','-q','main')
    assert inv.inventory(work,base)['status']=='READY'


def test_local_dirty_holds_without_exposing_name(tmp_path,capsys):
    origin, work, base = fixture(tmp_path)
    (work/'confidential-temp.txt').write_text('secret contents')
    assert inv.main(['--repo',str(work),'--base-oid',base])==1
    output=capsys.readouterr().out
    assert 'confidential-temp' not in output and 'secret contents' not in output
    assert 'BASE_GUARD_DIRTY_PRESERVE' in output


def test_stale_live_main_stops(tmp_path):
    origin, work, base = fixture(tmp_path)
    other=tmp_path/'other'
    subprocess.run(['git','clone','-q',str(origin),str(other)],check=True)
    git(other,'config','user.name','Test'); git(other,'config','user.email','test@example.invalid')
    (other/'another.txt').write_text('new')
    git(other,'add','another.txt');git(other,'commit','-qm','move main');git(other,'push','-q','origin','main')
    assert inv.inventory(work,base)['reason']=='BASE_GUARD_MAIN_DRIFT'


def test_unbounded_ref_set_and_invalid_ref_output_fail_closed(tmp_path,monkeypatch):
    origin, work, base = fixture(tmp_path)
    real = inv._git
    def inject(repo,*args):
        if args[0]=='for-each-ref':return '\n'.join(['a'*40]*(inv.MAX_LOCAL_HEADS+1))
        return real(repo,*args)
    monkeypatch.setattr(inv,'_git',inject)
    assert inv.inventory(work,base)['reason']=='LOCAL_HEAD_SET_UNBOUNDED'
    def invalid(repo,*args):
        if args[0]=='for-each-ref':return 'not-a-commit-id'
        return real(repo,*args)
    monkeypatch.setattr(inv,'_git',invalid)
    assert inv.inventory(work,base)['reason']=='LOCAL_HEAD_OID_INVALID'


def test_rev_list_corruption_refused(tmp_path,monkeypatch):
    origin,work,base=fixture(tmp_path)
    git(work,'switch','-qc','batch/local')
    (work/'foo').write_text('new')
    git(work,'add','foo');git(work,'commit','-qm','new')
    git(work,'switch','-q','main')
    real=inv._git
    monkeypatch.setattr(inv,'_git',lambda repo,*a: 'unexpected' if a[0]=='rev-list' else real(repo,*a))
    assert inv.inventory(work,base)['reason']=='LOCAL_HISTORY_COUNT_INVALID'


def test_failed_git_query_stops(tmp_path,monkeypatch):
    _,work,base=fixture(tmp_path)
    real=inv._git
    def fail(repo,*a):
        if a[0]=='for-each-ref':raise RuntimeError('GIT_QUERY_FAILED')
        return real(repo,*a)
    monkeypatch.setattr(inv,'_git',fail)
    assert inv.main(['--repo',str(work),'--base-oid',base])==1


def test_git_index_byte_and_mtime_unchanged(tmp_path):
    origin,work,base=fixture(tmp_path)
    index=work/'.git'/'index'
    before=snapshot(work,origin)
    bs=index.read_bytes();stamp=index.stat().st_mtime_ns
    assert inv.inventory(work,base)['status']=='READY'
    assert index.read_bytes()==bs and index.stat().st_mtime_ns==stamp
    assert before==snapshot(work,origin)


# B-119 G1 capacity (no file writes beyond the shared fixture; refs only via update-ref).
def _many_heads_at(work, oid, n):
    for i in range(n):
        git(work, 'update-ref', 'refs/heads/cap/h%03d' % i, oid)


def test_more_than_64_branches_all_at_base_ready(tmp_path):
    origin, work, base = fixture(tmp_path)
    _many_heads_at(work, base, 70)
    before = snapshot(work, origin)
    result = inv.inventory(work, base)
    assert result['status'] == 'READY' and result['reason'] == 'NO_OFF_HEAD_UNMERGED_HISTORY'
    assert result['local_head_count'] == 71
    assert snapshot(work, origin) == before


def test_more_than_64_branches_with_pushed_unmerged_tip_still_holds(tmp_path):
    origin, work, base = fixture(tmp_path)
    _many_heads_at(work, base, 70)
    git(work, 'switch', '-qc', 'batch/pushed-unmerged')
    (work/'p.txt').write_bytes(b'pushed but not in Base\n')
    git(work, 'add', 'p.txt'); git(work, 'commit', '-qm', 'pushed unmerged')
    tip = git(work, 'rev-parse', 'HEAD')
    git(work, 'push', '-q', 'origin', 'batch/pushed-unmerged')
    assert git(origin, 'rev-parse', 'refs/heads/batch/pushed-unmerged') == tip
    git(work, 'switch', '-q', 'main')
    before = snapshot(work, origin)
    assert inv.inventory(work, base) == {'status': 'HOLD', 'reason': 'OFF_HEAD_HISTORY_PRESERVE'}
    assert snapshot(work, origin) == before
    assert git(work, 'rev-parse', 'refs/heads/batch/pushed-unmerged') == tip


def test_limit_boundary_exact_and_over(tmp_path, monkeypatch):
    origin, work, base = fixture(tmp_path)
    real = inv._git
    for n, want in ((inv.MAX_LOCAL_HEADS, 'NO_OFF_HEAD_UNMERGED_HISTORY'),
                    (inv.MAX_LOCAL_HEADS + 1, 'LOCAL_HEAD_SET_UNBOUNDED')):
        def inject(repo, *args, n=n):
            if args[0] == 'for-each-ref':
                return '\n'.join([base] * n)
            return real(repo, *args)
        monkeypatch.setattr(inv, '_git', inject)
        assert inv.inventory(work, base)['reason'] == want


def test_duplicate_merged_tips_counted_once_and_ready(tmp_path, monkeypatch):
    origin, work, old = fixture(tmp_path)
    (work/'y.txt').write_bytes(b'second\n')
    git(work, 'add', 'y.txt'); git(work, 'commit', '-qm', 'second')
    base = git(work, 'rev-parse', 'HEAD')
    git(work, 'push', '-q', 'origin', 'main'); git(work, 'fetch', '-q', 'origin', 'main')
    real = inv._git
    calls = []
    def inject(repo, *args):
        if args[0] == 'for-each-ref':
            return '\n'.join([old] * 40 + [base])
        if args[0] == 'rev-list':
            calls.append(args[-1])
        return real(repo, *args)
    monkeypatch.setattr(inv, '_git', inject)
    assert inv.inventory(work, base)['status'] == 'READY'
    assert calls == [base + '..' + old]


def test_each_distinct_tip_counted_once_and_any_ahead_tip_holds(tmp_path, monkeypatch):
    origin, work, base = fixture(tmp_path)
    git(work, 'switch', '-qc', 'batch/ahead')
    (work/'a.txt').write_bytes(b'ahead\n')
    git(work, 'add', 'a.txt'); git(work, 'commit', '-qm', 'ahead')
    ahead = git(work, 'rev-parse', 'HEAD')
    git(work, 'switch', '-q', 'main')
    real = inv._git
    calls = []
    def inject(repo, *args):
        if args[0] == 'for-each-ref':
            return '\n'.join([base] * 40 + [ahead] * 40)
        if args[0] == 'rev-list':
            calls.append(args[-1])
        return real(repo, *args)
    monkeypatch.setattr(inv, '_git', inject)
    assert inv.inventory(work, base) == {'status': 'HOLD', 'reason': 'OFF_HEAD_HISTORY_PRESERVE'}
    assert calls == [base + '..' + ahead]
