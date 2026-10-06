# -*- coding: utf-8 -*-
"""
scripts/tests/test_prompt_intake.py

Negative and positive controls for scripts/prompt_intake.py (B-107 canonical tooling).
"""

import hashlib
import os
import subprocess
import sys

import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TOOL = os.path.join(SCRIPTS_DIR, "prompt_intake.py")
TASK = "TEST-INTAKE-001"
CONTENT = "prompt body\n第二行\n".encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def env(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    source = downloads / "prompt.txt"
    source.write_bytes(CONTENT)
    return repo, source


def run(repo, source, digest, task=TASK):
    proc = subprocess.run(
        [sys.executable, TOOL, "--task-id", task, "--source", str(source), "--sha256", digest, "--repo-root", str(repo)],
        capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout


def target_of(repo, task=TASK):
    return repo / ".git" / f"{task}-prompt.txt"


def test_pass_copies_exact_bytes(env):
    repo, source = env
    code, out = run(repo, source, sha(CONTENT))
    assert code == 0, out
    assert "PROMPT_INTAKE PASS" in out
    assert target_of(repo).read_bytes() == CONTENT


def test_uppercase_hash_accepted(env):
    repo, source = env
    code, _ = run(repo, source, sha(CONTENT).upper())
    assert code == 0


def test_hash_mismatch_creates_nothing(env):
    repo, source = env
    code, out = run(repo, source, sha(b"other"))
    assert code == 5 and "SOURCE_HASH_MISMATCH" in out
    assert not target_of(repo).exists()


def test_source_missing(env):
    repo, source = env
    code, out = run(repo, source.parent / "absent.txt", sha(CONTENT))
    assert code == 3 and "SOURCE_MISSING" in out


def test_target_exists_is_not_overwritten(env):
    repo, source = env
    target_of(repo).write_bytes(b"old")
    code, out = run(repo, source, sha(CONTENT))
    assert code == 6 and "TARGET_EXISTS" in out
    assert target_of(repo).read_bytes() == b"old"


def test_target_exists_even_with_same_content(env):
    repo, source = env
    target_of(repo).write_bytes(CONTENT)
    code, _ = run(repo, source, sha(CONTENT))
    assert code == 6


def test_empty_and_oversize_source_rejected(env):
    repo, source = env
    source.write_bytes(b"")
    assert run(repo, source, sha(b""))[0] == 4
    big = b"a" * (1024 * 1024 + 1)
    source.write_bytes(big)
    assert run(repo, source, sha(big))[0] == 4
    assert not target_of(repo).exists()


def test_directory_source_rejected(env):
    repo, source = env
    code, _ = run(repo, source.parent, sha(CONTENT))
    assert code == 4


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unsupported")
def test_symlink_source_rejected(env, tmp_path):
    repo, source = env
    link = source.parent / "link.txt"
    try:
        os.symlink(source, link)
    except OSError:
        pytest.skip("symlink not permitted")
    code, _ = run(repo, link, sha(CONTENT))
    assert code == 4
    assert not target_of(repo).exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unsupported")
def test_symlinked_ancestor_directory_rejected(env, tmp_path):
    repo, source = env
    link_dir = tmp_path / "linked"
    try:
        os.symlink(source.parent, link_dir, target_is_directory=True)
    except OSError:
        pytest.skip("symlink not permitted")
    code, out = run(repo, link_dir / "prompt.txt", sha(CONTENT))
    assert code == 7 and "PATH_NOT_SAFE" in out
    assert not target_of(repo).exists()


def test_git_file_instead_of_directory_rejected(tmp_path):
    repo = tmp_path / "wt"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    source = tmp_path / "prompt.txt"
    source.write_bytes(CONTENT)
    code, _ = run(repo, source, sha(CONTENT))
    assert code == 7


@pytest.mark.parametrize("task", ["", "bad id", "../x", "a/b"])
def test_invalid_task_id_rejected(env, task):
    repo, source = env
    code, _ = run(repo, source, sha(CONTENT), task=task)
    assert code == 2


@pytest.mark.parametrize("digest", ["", "abc", "g" * 64])
def test_invalid_digest_rejected(env, digest):
    repo, source = env
    code, _ = run(repo, source, digest)
    assert code == 2


def test_relative_source_rejected(env):
    repo, _ = env
    code, _ = run(repo, "prompt.txt", sha(CONTENT))
    assert code == 2


def test_no_content_echo(env):
    repo, source = env
    secret_like = b"TOKEN_VALUE_SHOULD_NOT_ECHO\n"
    source.write_bytes(secret_like)
    code, out = run(repo, source, sha(b"different"))
    assert code == 5
    assert "TOKEN_VALUE_SHOULD_NOT_ECHO" not in out
