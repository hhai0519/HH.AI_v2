# -*- coding: utf-8 -*-
"""B-118: ref whitelist, no-overwrite, failure truth, and runner ordering controls."""
import os
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bundle_after_push as bund
import batch_runner as br


def g(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL).decode().strip()


@pytest.fixture
def small_repo(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    g(repo, 'init', '-q')
    g(repo, 'config', 'user.email', 'test@example.invalid')
    g(repo, 'config', 'user.name', 'Tester')
    (repo / 'a').write_text('a\n')
    g(repo, 'add', 'a')
    g(repo, 'commit', '-q', '-m', 'base')
    base = g(repo, 'rev-parse', 'HEAD')
    g(repo, 'update-ref', 'refs/remotes/origin/main', base)
    g(repo, 'switch', '-q', '-c', 'batch/b118-test')
    (repo / 'a').write_text('b\n')
    g(repo, 'commit', '-qam', 'candidate')
    head = g(repo, 'rev-parse', 'HEAD')
    g(repo, 'update-ref', 'refs/remotes/origin/batch/b118-test', head)
    dl = tmp_path / 'Downloads'
    dl.mkdir()
    return repo, dl, base, head


def test_bundle_exact_refs_non_stash_and_timezone(small_repo):
    root, dl, base, head = small_repo
    g(root, 'update-ref', 'refs/stash', head)
    clock = datetime(2026, 10, 14, 15, 35, 9, tzinfo=timezone(timedelta(hours=8)))
    target = bund.create_bundle(root, 'batch/b118-test', base, head, dl, clock, 'B118-TEST')
    assert Path(target).name == 'HH.AI_v2-20261014-153509-' + base[:7] + '.bundle'
    assert 'complete history' in g(root, 'bundle', 'verify', target)
    heads = g(root, 'bundle', 'list-heads', target)
    assert base + ' refs/remotes/origin/main' in heads
    assert head + ' refs/remotes/origin/batch/b118-test' in heads
    assert 'refs/stash' not in heads
    assert (root / '.git/B118-TEST-bundle.tmp').is_file()


def test_bundle_collision_is_non_destructive(small_repo):
    root, dl, base, head = small_repo
    clock = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)
    name = 'HH.AI_v2-20261014-230000-' + base[:7] + '.bundle'
    (dl / name).write_bytes(b'preserve')
    with pytest.raises(bund.BundleFailure, match='BUNDLE_EXISTS'):
        bund.create_bundle(root, 'batch/b118-test', base, head, dl, clock, 'B118-TEST')
    assert (dl / name).read_bytes() == b'preserve'


def test_untrusted_path_fails_closed(small_repo, tmp_path):
    root, dl, base, head = small_repo
    link = tmp_path / 'link'
    try:
        link.symlink_to(dl, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('symlink creation unavailable')
    with pytest.raises(bund.BundleFailure, match='DOWNLOADS_UNSAFE'):
        bund.create_bundle(root, 'batch/b118-test', base, head, link, task_id='B118-TEST')


def test_ref_mismatch_and_invalid_branch_rejected(small_repo):
    root, dl, base, head = small_repo
    with pytest.raises(bund.BundleFailure, match='ARGUMENT_INVALID'):
        bund.create_bundle(root, 'refs/stash', base, head, dl, task_id='B118-TEST')
    g(root, 'update-ref', 'refs/remotes/origin/main', head)
    with pytest.raises(bund.BundleFailure, match='TRACKING_MAIN_DRIFT'):
        bund.create_bundle(root, 'batch/b118-test', base, head, dl, task_id='B118-TEST')


def test_missing_tracking_candidate_bounded_materialization(small_repo):
    root, dl, base, head = small_repo
    g(root, 'update-ref', '-d', 'refs/remotes/origin/batch/b118-test')
    refs = bund.allowed_refs(str(root), 'batch/b118-test', base, head)
    assert refs['refs/remotes/origin/batch/b118-test'] == head
    assert g(root, 'rev-parse', 'refs/remotes/origin/batch/b118-test') == head


def test_step_order_legacy_runner_update_and_new_production():
    legacy = {'kind': 'production', 'e24': False, 'focused': None, 'runner_update': True}
    assert br.derive_steps(legacy)[-1] == 'push'
    enabled = dict(legacy, bundle_output=True)
    assert br.derive_steps(enabled)[-2:] == ['push', 'bundle']
    assert br.derive_steps({'kind': 'promotion'}) == ['preflight', 'verify', 'promote', 'postmain']
    c = {'task_id': 'T', 'prompt_sha256': 'p', 'runner_sha256': 'r',
         'done': br.derive_steps(enabled)[:-1], 'halted': None}
    assert br.check_control(c, 'T', 'p', 'r', br.derive_steps(enabled), 'bundle') == 'OK'
    with pytest.raises(br.Halt, match='STEP_ORDER_VIOLATION'):
        br.check_control(c, 'T', 'p', 'r', br.derive_steps(enabled), 'push')


def test_bundle_error_after_push_is_non_halting(monkeypatch, small_repo, capsys):
    root, dl, base, head = small_repo
    b = br.Batch.__new__(br.Batch)
    b.root = str(root)
    b.task_id = 'B118-TEST'
    b.spec = {'kind': 'production', 'base_oid': base, 'branch': 'batch/b118-test'}
    monkeypatch.setattr(br, 'status_lines', lambda *_: [])
    monkeypatch.setattr(b, 'remote_sha', lambda ref: base if ref.endswith('/main') else head)
    monkeypatch.setattr(br, 'create_bundle', lambda *a, **k: (_ for _ in ()).throw(bund.BundleFailure('BUNDLE_EXISTS')))
    # Must not call step_push or CI again after a bundle error.
    monkeypatch.setattr(b, 'step_push', lambda: (_ for _ in ()).throw(AssertionError('re-push')))
    assert b.step_bundle() == 'FAILED_BUNDLE_EXISTS'
    assert 'BUNDLE FAILED BUNDLE_EXISTS' in capsys.readouterr().out


def test_symbolic_origin_head_not_exported(small_repo):
    root, dl, base, head = small_repo
    g(root, 'symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/main')
    refs = bund.allowed_refs(str(root), 'batch/b118-test', base, head)
    assert 'refs/remotes/origin/HEAD' not in refs
    assert refs['refs/remotes/origin/main'] == base


def test_git_command_nonzero_never_leaks_raw_output(monkeypatch, small_repo):
    root, dl, base, head = small_repo
    class R:
        returncode = 128
        stdout = b'secret-invalid-output'
        stderr = b'credential value must not be logged'
    monkeypatch.setattr(bund.subprocess, 'run', lambda *args, **kwargs: R())
    with pytest.raises(bund.BundleFailure, match='GIT_NONZERO'):
        bund.git(str(root), 'for-each-ref', 'refs/remotes/origin')
