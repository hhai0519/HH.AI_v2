# -*- coding: utf-8 -*-
"""
scripts/tests/test_secret_scan_fail_closed.py

B-113 negative and positive controls for scripts/secret_scan.py:
- placeholder exemption only for delimited keyword segments (no substring exemption);
- tracked and staged modes fail closed (SCAN_READ_ERROR) on unreadable content;
- legitimate skips stay narrow (worktree-deleted file, gitlink, staged deletion).
Synthetic tokens are assembled at runtime so this file itself carries no token literal.
"""

import os
import subprocess
import sys

import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import secret_scan  # noqa: E402

ALNUM = "Ab3Kq9Zx7Lm2Np5Rt8Vw1Yc4Hd6Jf0GsBn7Mc2Xe5Wr8Ty1Ui4Op6As3Df9Gh0Jk"
assert len(ALNUM) == 64


def gh_token(body):
    return "".join(["g", "h", "p", "_"]) + body


def google_key(body):
    return "".join(["A", "I", "z", "a"]) + body


def scan_line(line, path="sample.txt"):
    return list(secret_scan.scan_content_lines((line + "\n").encode("utf-8"), path))


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.invalid")
    git(tmp_path, "config", "user.name", "t")
    return tmp_path


# ---------------------------------------------------------------- placeholder semantics

@pytest.mark.parametrize("inner", ["TEST", "test", "Fake", "DUMMY", "Example"])
def test_keyword_inside_token_body_is_reported(inner):
    body = (ALNUM[:10] + inner + ALNUM)[:36]
    assert len(body) == 36
    findings = scan_line(f"token = {gh_token(body)}")
    assert ("GITHUB_CREDENTIAL", 1) in findings


def test_keyword_inside_google_key_is_reported():
    body = (ALNUM[:12] + "Fake" + ALNUM)[:35]
    findings = scan_line(f"key: {google_key(body)}")
    assert ("GOOGLE_API_KEY", 1) in findings


def test_marker_elsewhere_on_line_does_not_exempt_token():
    body = (ALNUM[:8] + "test" + ALNUM)[:36]
    findings = scan_line(f"# EXAMPLE only: {gh_token(body)}")
    assert ("GITHUB_CREDENTIAL", 1) in findings


@pytest.mark.parametrize("value", [
    "FAKE_API_KEY_FOR_TESTING_12345",
    "EXAMPLE_KEY_12345678901234567890",
    "REDACTED_FOR_SECURITY_AUDIT_LOG",
    "DUMMY_SYNTHETIC_VALUE_TEST_ONLY",
    "abcdefghijklmnopqrstuvwxyz-TEST-0123",
])
def test_delimited_keyword_value_is_exempt(value):
    assert scan_line(f"api_key: '{value}'") == []


def test_keyword_glued_into_assignment_value_is_reported():
    value = "abcdefghijTESTklmnopqrstuvwxyz0123456789"
    assert ("GENERIC_SECRET_ASSIGNMENT", 1) in scan_line(f"api_key: '{value}'")


def test_delimited_keyword_token_is_exempt():
    # '-' is inside the Google key charset, so a keyword bounded by '-' is a delimited segment
    key = google_key(("x-TEST-" + ALNUM)[:35])
    assert scan_line(f"key: {key}") == []


def test_keyword_glued_to_token_prefix_is_reported():
    key = google_key(("TEST" + ALNUM)[:35])
    assert ("GOOGLE_API_KEY", 1) in scan_line(f"key: {key}")


# ---------------------------------------------------------------- tracked mode

def test_tracked_unreadable_file_fails_closed(repo, monkeypatch):
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    git(repo, "add", "a.txt")
    real_open = open

    def failing_open(path, *args, **kwargs):
        if os.path.basename(str(path)) == "a.txt":
            raise PermissionError("denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", failing_open)
    findings = secret_scan.run_tracked_scan(str(repo))
    assert (secret_scan.SCAN_READ_ERROR, "a.txt", 0) in findings


def test_tracked_worktree_deleted_file_is_skipped(repo):
    (repo / "gone.txt").write_text("hello\n", encoding="utf-8")
    git(repo, "add", "gone.txt")
    (repo / "gone.txt").unlink()
    assert secret_scan.run_tracked_scan(str(repo)) == []


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unsupported")
def test_tracked_symlink_scans_link_text_not_target(repo):
    target = repo / "target.txt"
    target.write_text(f"token = {gh_token(ALNUM[:36])}\n", encoding="utf-8")
    try:
        os.symlink("target.txt", repo / "link.txt")
    except OSError:
        pytest.skip("symlink not permitted")
    git(repo, "add", "link.txt")
    assert secret_scan.run_tracked_scan(str(repo)) == []


def test_tracked_clean_file_passes(repo):
    (repo / "ok.txt").write_text("nothing here\n", encoding="utf-8")
    git(repo, "add", "ok.txt")
    assert secret_scan.run_tracked_scan(str(repo)) == []


# ---------------------------------------------------------------- staged mode

def test_staged_blob_read_failure_fails_closed(repo, monkeypatch):
    (repo / "b.txt").write_text("hello\n", encoding="utf-8")
    git(repo, "add", "b.txt")

    def boom(repo_root, blob_sha):
        raise subprocess.CalledProcessError(128, ["git", "cat-file"])

    monkeypatch.setattr(secret_scan, "read_index_blob", boom)
    findings = secret_scan.run_staged_scan(str(repo))
    assert findings == [(secret_scan.SCAN_READ_ERROR, "b.txt", 0)]


def test_staged_missing_index_entry_fails_closed(repo, monkeypatch):
    (repo / "c.txt").write_text("hello\n", encoding="utf-8")
    git(repo, "add", "c.txt")
    monkeypatch.setattr(secret_scan, "read_index_entries", lambda root: {})
    findings = secret_scan.run_staged_scan(str(repo))
    assert findings == [(secret_scan.SCAN_READ_ERROR, "c.txt", 0)]


def test_staged_unmerged_entry_fails_closed(repo, monkeypatch):
    (repo / "d.txt").write_text("hello\n", encoding="utf-8")
    git(repo, "add", "d.txt")
    entries = secret_scan.read_index_entries(str(repo))
    mode, sha, _ = entries["d.txt"]
    monkeypatch.setattr(secret_scan, "read_index_entries", lambda root: {"d.txt": (mode, sha, "2")})
    findings = secret_scan.run_staged_scan(str(repo))
    assert findings == [(secret_scan.SCAN_READ_ERROR, "d.txt", 0)]


def test_staged_gitlink_is_skipped(repo):
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(repo, "add", "seed.txt")
    git(repo, "commit", "-q", "-m", "seed")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{head},sub")
    assert secret_scan.run_staged_scan(str(repo)) == []


def test_staged_reads_index_blob_and_detects(repo):
    (repo / "e.txt").write_text(f"token = {gh_token(ALNUM[:36])}\n", encoding="utf-8")
    git(repo, "add", "e.txt")
    (repo / "e.txt").write_text("clean now\n", encoding="utf-8")
    assert ("GITHUB_CREDENTIAL", "e.txt", 1) in secret_scan.run_staged_scan(str(repo))


def test_staged_deletion_is_not_an_error(repo):
    (repo / "f.txt").write_text("hello\n", encoding="utf-8")
    git(repo, "add", "f.txt")
    git(repo, "commit", "-q", "-m", "f")
    git(repo, "rm", "-q", "f.txt")
    assert secret_scan.run_staged_scan(str(repo)) == []


def test_cli_read_error_blocks_without_content(repo):
    (repo / "g.txt").write_text("hello\n", encoding="utf-8")
    git(repo, "add", "g.txt")
    os.chmod(repo / "g.txt", 0)
    try:
        with open(repo / "g.txt", "rb"):
            pytest.skip("file still readable (privileged user)")
    except PermissionError:
        pass
    try:
        proc = subprocess.run([sys.executable, os.path.join(SCRIPTS_DIR, "secret_scan.py"), "--tracked"],
                              cwd=repo, capture_output=True, text=True)
    finally:
        os.chmod(repo / "g.txt", 0o644)
    assert proc.returncode == 1
    assert "SECRET_SCAN BLOCK detector=SCAN_READ_ERROR path=g.txt line=0" in proc.stdout
    assert "hello" not in proc.stdout
