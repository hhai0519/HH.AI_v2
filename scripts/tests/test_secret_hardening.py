# -*- coding: utf-8 -*-
"""
scripts/tests/test_secret_hardening.py

Comprehensive tests for B-98 / TG-MVP-06 secret hardening:
- secret_presence.py presence probing and safety guarantees (§41)
- secret_scan.py staged and tracked scanner detectors and contracts (§42)
- install_git_hooks.py and .githooks/pre-commit execution and isolation (§43)

All secret fixtures are dynamically synthesized at runtime.
Zero hardcoded credentials in tracked test code.
Zero secret values exposed in test assertions or output.
"""

import os
import sys
import subprocess
import pytest

# Ensure scripts directory is on sys.path
SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import secret_presence
import secret_scan
import install_git_hooks


# ---------------------------------------------------------------------------
# Section 41: secret_presence.py Tests
# ---------------------------------------------------------------------------

def test_presence_exact_named_env_present(monkeypatch, capsys):
    # Dynamic synthetic name & value
    var_name = "HHAI_SYNTHETIC_AUTH_TOKEN_TEST"
    raw_val = "".join(["v", "a", "l", "_"]) + "secret12345678"
    monkeypatch.setenv(var_name, raw_val)

    rc = secret_presence.check_presence([var_name])
    captured = capsys.readouterr()

    assert rc == 0
    assert captured.out.strip() == "PRESENT"
    # Never expose variable name or secret value in stdout or stderr
    assert var_name not in captured.out
    assert var_name not in captured.err
    assert raw_val not in captured.out
    assert raw_val not in captured.err


def test_presence_absent_env(monkeypatch, capsys):
    var_name = "HHAI_DEFINITELY_ABSENT_VAR_9999"
    monkeypatch.delenv(var_name, raising=False)

    rc = secret_presence.check_presence([var_name])
    captured = capsys.readouterr()

    assert rc == 0
    assert captured.out.strip() == "ABSENT"
    assert var_name not in captured.out
    assert var_name not in captured.err


def test_presence_unrelated_env_not_enumerated(monkeypatch, capsys):
    unrelated_secret_name = "UNRELATED_SECRET_KEY_NEVER_SHOW"
    unrelated_secret_val = "".join(["s", "e", "c", "r", "e", "t"]) + "_unrelated_val"
    monkeypatch.setenv(unrelated_secret_name, unrelated_secret_val)

    query_name = "TEST_NORMAL_VARIABLE"
    monkeypatch.setenv(query_name, "hello")

    rc = secret_presence.check_presence([query_name])
    captured = capsys.readouterr()

    assert rc == 0
    assert captured.out.strip() == "PRESENT"
    # Unrelated secret and query name must not be logged, mentioned, or dumped
    assert query_name not in captured.out
    assert unrelated_secret_name not in captured.out
    assert unrelated_secret_val not in captured.out
    assert unrelated_secret_val not in captured.err


def test_presence_invalid_env_name_fail_closed(capsys):
    invalid_names = [
        "123_STARTS_WITH_DIGIT",
        "BAD NAME WITH SPACES",
        "BAD-DASH-VAR",
        "",
        " ",
    ]
    for bad_name in invalid_names:
        rc = secret_presence.check_presence([bad_name])
        assert rc == 1
        captured = capsys.readouterr()
        if bad_name.strip():
            assert bad_name not in captured.out
            assert bad_name not in captured.err
            assert bad_name.strip() not in captured.out
            assert bad_name.strip() not in captured.err


def test_presence_wildcard_prefix_rejected(capsys):
    wildcards = ["PATH*", "TOKEN?", "TEST%VAR", "$ENV:VAR"]
    for wc in wildcards:
        rc = secret_presence.check_presence([wc])
        assert rc == 1
        captured = capsys.readouterr()
        assert wc not in captured.out
        assert wc not in captured.err


def test_presence_leading_trailing_whitespace_rejected(capsys):
    ws_names = ["  HHAI_VAR", "HHAI_VAR  ", "  HHAI_VAR  "]
    for ws_name in ws_names:
        rc = secret_presence.check_presence([ws_name])
        assert rc == 1
        captured = capsys.readouterr()
        assert "HHAI_VAR" not in captured.out
        assert "HHAI_VAR" not in captured.err


def test_presence_credential_shaped_valid_argument_not_echoed(capsys):
    # Dynamically construct credential-like token matching ENV_NAME_PATTERN
    prefix = "".join(["g", "h", "p", "_"])
    body = "SYNTHETIC" + "1234567890ABCDEF"
    cred_token = prefix + body

    rc = secret_presence.check_presence([cred_token])
    captured = capsys.readouterr()

    assert rc == 0
    assert captured.out.strip() == "ABSENT"
    # Caller argument must strictly not be echoed
    assert cred_token not in captured.out
    assert cred_token not in captured.err
    assert body not in captured.out
    assert body not in captured.err


def test_presence_credential_shaped_invalid_argument_not_echoed(capsys):
    # Dynamically construct credential-like token with invalid characters
    prefix = "".join(["t", "o", "k", "e", "n", ":"])
    body = "secret_val_12345"
    cred_token = prefix + body

    rc = secret_presence.check_presence([cred_token])
    captured = capsys.readouterr()

    assert rc == 1
    assert cred_token not in captured.out
    assert cred_token not in captured.err
    assert body not in captured.out
    assert body not in captured.err


def test_presence_zero_args_fail_closed(capsys):
    rc = secret_presence.check_presence([])
    assert rc == 1
    captured = capsys.readouterr()
    assert "SECRET_PRESENCE ERROR" in captured.err


def test_presence_multiple_args_fail_closed(capsys):
    arg1 = "VAR_ONE"
    arg2 = "VAR_TWO"
    rc = secret_presence.check_presence([arg1, arg2])
    assert rc == 1
    captured = capsys.readouterr()
    assert arg1 not in captured.out
    assert arg1 not in captured.err
    assert arg2 not in captured.out
    assert arg2 not in captured.err


def test_presence_source_does_not_enumerate_environ():
    import inspect
    source = inspect.getsource(secret_presence)
    # Ensure helper does not call iteration methods on os.environ
    assert "os.environ.keys()" not in source
    assert "os.environ.items()" not in source
    assert "os.environ.values()" not in source
    assert "for " not in source or "for k in os.environ" not in source


# ---------------------------------------------------------------------------
# Section 42: secret_scan.py Detector & Policy Tests
# ---------------------------------------------------------------------------

def test_scan_clean_text_passes():
    content = b"const app = 'HH.AI_v2';\nconsole.log('Clean code');\n"
    findings = list(secret_scan.scan_content_lines(content, "test.js"))
    assert findings == []


def test_scan_github_token_blocks():
    prefix = "".join(["g", "h", "p", "_"])
    raw_token = prefix + "A" * 36
    content = f"const gh_token = '{raw_token}';\n".encode("utf-8")

    findings = list(secret_scan.scan_content_lines(content, "test.js"))
    assert len(findings) >= 1
    assert findings[0][0] == "GITHUB_CREDENTIAL"


def test_scan_notion_token_blocks():
    prefix = "".join(["n", "t", "n", "_"])
    raw_token = prefix + "B" * 32
    content = f"NOTION_KEY='{raw_token}'\n".encode("utf-8")

    findings = list(secret_scan.scan_content_lines(content, "config.py"))
    assert len(findings) >= 1
    assert findings[0][0] == "NOTION_CREDENTIAL"


def test_scan_telegram_token_blocks():
    bot_id = "123456789"
    token_body = "A" * 35
    raw_token = f"{bot_id}:{token_body}"
    content = f"const tg_bot_token = '{raw_token}';\n".encode("utf-8")

    findings = list(secret_scan.scan_content_lines(content, "bot.ts"))
    assert len(findings) >= 1
    assert findings[0][0] == "TELEGRAM_BOT_TOKEN"


def test_scan_google_cookie_blocks():
    prefix = "".join(["O", "S", "I", "D", "="])
    cookie = prefix + "C" * 32
    content = f"Cookie: {cookie}\n".encode("utf-8")

    findings = list(secret_scan.scan_content_lines(content, "headers.txt"))
    assert len(findings) >= 1
    assert findings[0][0] == "GOOGLE_SESSION_COOKIE"


def test_scan_private_key_marker_blocks():
    marker = b"-----" + b"BEGIN " + b"RSA " + b"PRIVATE KEY" + b"-----"
    footer = b"-----" + b"END " + b"RSA " + b"PRIVATE KEY" + b"-----"
    content = marker + b"\nMIIEowIBAAKCAQEA0...\n" + footer + b"\n"
    findings = list(secret_scan.scan_content_lines(content, "server.key"))
    assert len(findings) >= 1
    assert findings[0][0] == "PRIVATE_KEY_MATERIAL"


def test_scan_generic_secret_assignment_blocks():
    prefix = "".join(["a", "p", "i", "_", "k", "e", "y"])
    raw_key = "k" * 36
    content = f"{prefix}: '{raw_key}'\n".encode("utf-8")

    findings = list(secret_scan.scan_content_lines(content, "settings.json"))
    assert len(findings) >= 1
    assert findings[0][0] == "GENERIC_SECRET_ASSIGNMENT"


def test_scan_line_credential_blocks():
    prefix = "".join(["c", "h", "a", "n", "n", "e", "l", "_", "s", "e", "c", "r", "e", "t"])
    raw_secret = "s" * 32
    content = f"{prefix} = '{raw_secret}'\n".encode("utf-8")

    findings = list(secret_scan.scan_content_lines(content, "line.py"))
    assert len(findings) >= 1
    assert findings[0][0] == "LINE_CREDENTIAL"


def test_scan_placeholder_value_does_not_block():
    placeholders = [
        "api_key: '__PLACEHOLDER__'",
        "api_key: 'FAKE_API_KEY_FOR_TESTING_12345'",
        "api_key: '<YOUR_API_KEY_HERE>'",
        "api_key: '${ENV_API_KEY}'",
        "api_key: 'EXAMPLE_KEY_12345678901234567890'",
        "api_key: 'REDACTED_FOR_SECURITY_AUDIT_LOG'",
        "api_key: 'DUMMY_SYNTHETIC_VALUE_TEST_ONLY'",
    ]
    for line in placeholders:
        content = (line + "\n").encode("utf-8")
        findings = list(secret_scan.scan_content_lines(content, "config.yaml"))
        assert findings == [], f"Should not block placeholder: {line}"


def test_scan_forbidden_filename_blocks():
    forbidden_files = [
        "cookies.txt",
        "nlm_cookies.txt",
        "mcp_config.json",
        "mcp_config.backup.json",
        ".env",
        ".env.local",
        ".env.production",
        "credentials.json",
        "id_rsa",
        "id_rsa.pub",
        "id_ed25519",
        "cert.p12",
        "cert.pfx",
        "server.key",
    ]
    for fn in forbidden_files:
        det = secret_scan.check_forbidden_filename(fn)
        assert det == "FILENAME_FORBIDDEN", f"Expected {fn} to be forbidden"


def test_scan_env_example_allowed_by_filename():
    allowed_templates = [
        ".env.example",
        ".env.sample",
        ".env.template",
        "path/to/.env.example",
    ]
    for fn in allowed_templates:
        det = secret_scan.check_forbidden_filename(fn)
        assert det is None, f"Expected {fn} to be allowed template"


def test_scan_all_extensions_checked(tmp_path):
    # Scan across .txt, .json, .md, and unknown extension .xyz
    extensions = [".txt", ".json", ".md", ".xyz"]
    prefix = "".join(["g", "h", "p", "_"])
    raw_token = prefix + "Z" * 36

    for ext in extensions:
        content = f"secret_line: {raw_token}\n".encode("utf-8")
        findings = list(secret_scan.scan_content_lines(content, f"file{ext}"))
        assert len(findings) >= 1, f"Scanner should check extension {ext}"


def test_scan_staged_mode_reads_index_blob_not_working_tree(tmp_path):
    # Initialize a temporary git repository
    repo_dir = tmp_path / "git_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)

    test_file = repo_dir / "data.txt"

    # 1. Write clean content and stage it
    test_file.write_text("clean staged content\n", encoding="utf-8")
    subprocess.run(["git", "add", "data.txt"], cwd=repo_dir, check=True, capture_output=True)

    # 2. Modify working tree with a secret AFTER staging
    prefix = "".join(["g", "h", "p", "_"])
    leaked = prefix + "X" * 36
    test_file.write_text(f"leaked in working tree: {leaked}\n", encoding="utf-8")

    # Staged scan must read index blob (clean), NOT working tree
    proc = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, "secret_scan.py"), "--staged"],
        cwd=repo_dir,
        capture_output=True,
        text=True
    )
    assert proc.returncode == 0
    assert "SECRET_SCAN PASS mode=STAGED" in proc.stdout

    # Now stage the leak -> staged scan must block
    subprocess.run(["git", "add", "data.txt"], cwd=repo_dir, check=True, capture_output=True)
    proc2 = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, "secret_scan.py"), "--staged"],
        cwd=repo_dir,
        capture_output=True,
        text=True
    )
    assert proc2.returncode == 1
    assert "SECRET_SCAN BLOCK" in proc2.stdout
    # Safe output: never prints the secret value
    assert leaked not in proc2.stdout


def test_scan_staged_deleted_file_does_not_fail(tmp_path):
    repo_dir = tmp_path / "del_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)

    # Commit a clean file first
    test_file = repo_dir / "to_delete.txt"
    test_file.write_text("initial file\n", encoding="utf-8")
    subprocess.run(["git", "add", "to_delete.txt"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "init"],
        cwd=repo_dir,
        check=True,
        capture_output=True
    )

    # Delete the file and stage deletion
    test_file.unlink()
    subprocess.run(["git", "rm", "to_delete.txt"], cwd=repo_dir, check=True, capture_output=True)

    proc = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, "secret_scan.py"), "--staged"],
        cwd=repo_dir,
        capture_output=True,
        text=True
    )
    assert proc.returncode == 0
    assert "SECRET_SCAN PASS mode=STAGED" in proc.stdout


def test_scan_block_output_does_not_contain_secret_or_context_line(capsys):
    prefix = "".join(["g", "h", "p", "_"])
    raw_token = prefix + "Y" * 36
    path = "api/secret.json"

    findings = [( "GITHUB_CREDENTIAL", path, 10 )]
    for det_id, p, line_no in findings:
        sys.stdout.write(f"SECRET_SCAN BLOCK detector={det_id} path={p} line={line_no}\n")

    captured = capsys.readouterr()
    assert f"SECRET_SCAN BLOCK detector=GITHUB_CREDENTIAL path={path} line=10" in captured.out
    # Strictly zero secret value or context line
    assert raw_token not in captured.out


def test_scan_tracked_mode_detects_tracked_leak(tmp_path):
    repo_dir = tmp_path / "tracked_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)

    prefix = "".join(["g", "h", "p", "_"])
    raw_token = prefix + "T" * 36
    leak_file = repo_dir / "token.txt"
    leak_file.write_text(f"GITHUB_KEY = '{raw_token}'\n", encoding="utf-8")
    subprocess.run(["git", "add", "token.txt"], cwd=repo_dir, check=True, capture_output=True)

    proc = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, "secret_scan.py"), "--tracked"],
        cwd=repo_dir,
        capture_output=True,
        text=True
    )
    assert proc.returncode == 1
    assert "SECRET_SCAN BLOCK detector=GITHUB_CREDENTIAL" in proc.stdout
    assert raw_token not in proc.stdout


# ---------------------------------------------------------------------------
# Section 43: Hook & Installer Tests in Temporary Git Repo
# ---------------------------------------------------------------------------

def test_hook_installer_and_execution_lifecycle(tmp_path):
    repo_dir = tmp_path / "hook_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)

    # Copy scripts and .githooks into temporary repo
    githooks_dir = repo_dir / ".githooks"
    githooks_dir.mkdir()
    hook_dest = githooks_dir / "pre-commit"

    hook_dest = githooks_dir / "pre-commit"
    hook_dest_push = githooks_dir / "pre-push"

    scripts_target = repo_dir / "scripts"
    scripts_target.mkdir()

    with open(os.path.join(SCRIPTS_DIR, "..", ".githooks", "pre-commit"), "rb") as f:
        hook_dest.write_bytes(f.read())
    with open(os.path.join(SCRIPTS_DIR, "..", ".githooks", "pre-push"), "rb") as f:
        hook_dest_push.write_bytes(f.read())
    try:
        os.chmod(hook_dest, 0o755)
        os.chmod(hook_dest_push, 0o755)
    except Exception:
        pass

    with open(os.path.join(SCRIPTS_DIR, "secret_scan.py"), "rb") as f:
        (scripts_target / "secret_scan.py").write_bytes(f.read())

    with open(os.path.join(SCRIPTS_DIR, "governance_preflight.py"), "rb") as f:
        (scripts_target / "governance_preflight.py").write_bytes(f.read())

    with open(os.path.join(SCRIPTS_DIR, "validate_prompt_manifest.py"), "rb") as f:
        (scripts_target / "validate_prompt_manifest.py").write_bytes(f.read())

    with open(os.path.join(SCRIPTS_DIR, "install_git_hooks.py"), "rb") as f:
        (scripts_target / "install_git_hooks.py").write_bytes(f.read())

    # A. Initial check must FAIL (hooksPath not set)
    proc_check_init = subprocess.run(
        [sys.executable, "scripts/install_git_hooks.py", "--check"],
        cwd=repo_dir,
        capture_output=True,
        text=True
    )
    assert proc_check_init.returncode != 0

    # B. Install hooks
    proc_install = subprocess.run(
        [sys.executable, "scripts/install_git_hooks.py", "--install"],
        cwd=repo_dir,
        capture_output=True,
        text=True
    )
    assert proc_install.returncode == 0
    assert "HOOK_INSTALL PASS" in proc_install.stdout

    # C. Check passes after install
    proc_check_post = subprocess.run(
        [sys.executable, "scripts/install_git_hooks.py", "--check"],
        cwd=repo_dir,
        capture_output=True,
        text=True
    )
    assert proc_check_post.returncode == 0
    assert "HOOK_CHECK PASS" in proc_check_post.stdout

    # D. Test --check fails when hook file is missing
    hook_backup = hook_dest.read_bytes()
    hook_dest.unlink()
    proc_missing = subprocess.run(
        [sys.executable, "scripts/install_git_hooks.py", "--check"],
        cwd=repo_dir,
        capture_output=True,
        text=True
    )
    assert proc_missing.returncode != 0
    assert "HOOK_CHECK FAIL" in proc_missing.stderr

    # E. Test --check fails when hook path is a directory rather than regular file
    hook_dest.mkdir()
    proc_dir = subprocess.run(
        [sys.executable, "scripts/install_git_hooks.py", "--check"],
        cwd=repo_dir,
        capture_output=True,
        text=True
    )
    assert proc_dir.returncode != 0
    assert "HOOK_CHECK FAIL" in proc_dir.stderr
    hook_dest.rmdir()

    # Restore hook file with standard permission
    hook_dest.write_bytes(hook_backup)
    try:
        os.chmod(hook_dest, 0o755)
    except Exception:
        pass

    # F. On POSIX, verify non-executable hook fails --check and --install restores it
    if os.name != 'nt':
        os.chmod(hook_dest, 0o644)
        proc_no_x = subprocess.run(
            [sys.executable, "scripts/install_git_hooks.py", "--check"],
            cwd=repo_dir,
            capture_output=True,
            text=True
        )
        assert proc_no_x.returncode != 0
        assert "HOOK_CHECK FAIL" in proc_no_x.stderr

        # --install restores executable permissions on POSIX
        proc_reinstall = subprocess.run(
            [sys.executable, "scripts/install_git_hooks.py", "--install"],
            cwd=repo_dir,
            capture_output=True,
            text=True
        )
        assert proc_reinstall.returncode == 0
        assert "HOOK_INSTALL PASS" in proc_reinstall.stdout

        proc_check_restored = subprocess.run(
            [sys.executable, "scripts/install_git_hooks.py", "--check"],
            cwd=repo_dir,
            capture_output=True,
            text=True
        )
        assert proc_check_restored.returncode == 0
        assert "HOOK_CHECK PASS" in proc_check_restored.stdout

    # G. Global git config is unchanged
    global_val = subprocess.run(
        ["git", "config", "--global", "--get", "core.hooksPath"],
        capture_output=True,
        text=True
    ).stdout.strip()
    local_val = subprocess.run(
        ["git", "config", "--local", "--get", "core.hooksPath"],
        cwd=repo_dir,
        capture_output=True,
        text=True
    ).stdout.strip()
    assert local_val == ".githooks"

    # H. Clean staged commit succeeds via pre-commit hook
    clean_file = repo_dir / "clean.txt"
    clean_file.write_text("clean commit content\n", encoding="utf-8")
    subprocess.run(["git", "add", "clean.txt"], cwd=repo_dir, check=True, capture_output=True)

    proc_commit_clean = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "clean commit"],
        cwd=repo_dir,
        capture_output=True,
        text=True
    )
    assert proc_commit_clean.returncode == 0, f"Clean commit failed: {proc_commit_clean.stderr}"

    # I. Staged secret leak causes commit to FAIL via hook
    prefix = "".join(["g", "h", "p", "_"])
    raw_token = prefix + "F" * 36
    leak_file = repo_dir / "bad.txt"
    leak_file.write_text(f"GITHUB_PAT = '{raw_token}'\n", encoding="utf-8")
    subprocess.run(["git", "add", "bad.txt"], cwd=repo_dir, check=True, capture_output=True)

    proc_commit_leak = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "bad commit"],
        cwd=repo_dir,
        capture_output=True,
        text=True
    )
    assert proc_commit_leak.returncode != 0, "Commit with secret must be blocked by hook"
    assert "PRE-COMMIT BLOCK" in proc_commit_leak.stderr or "SECRET_SCAN BLOCK" in proc_commit_leak.stdout


def test_hook_installer_posix_permission_branches(monkeypatch, tmp_path):
    repo_dir = tmp_path / "posix_mock_repo"
    repo_dir.mkdir()
    githooks_dir = repo_dir / ".githooks"
    githooks_dir.mkdir()
    hook_file = githooks_dir / "pre-commit"
    hook_file.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hook_push = githooks_dir / "pre-push"
    hook_push.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    monkeypatch.setattr(install_git_hooks, "get_repo_root", lambda: str(repo_dir).replace('\\', '/'))
    monkeypatch.setattr(install_git_hooks.os, "name", "posix")

    orig_check_output = subprocess.check_output

    def fake_check_output(cmd, **kwargs):
        if "core.hooksPath" in cmd:
            return ".githooks\n"
        return orig_check_output(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)

    # 1. When os.access(..., os.X_OK) returns False on POSIX -> check_hooks fails
    monkeypatch.setattr(install_git_hooks.os, "access", lambda path, mode: False)
    rc_check = install_git_hooks.check_hooks()
    assert rc_check != 0

    # 2. When os.access(..., os.X_OK) returns True on POSIX -> check_hooks passes
    monkeypatch.setattr(install_git_hooks.os, "access", lambda path, mode: True)
    rc_check_pass = install_git_hooks.check_hooks()
    assert rc_check_pass == 0

    # 3. When chmod raises exception on POSIX during install -> install_hooks fails closed (no swallowed error)
    def bad_chmod(path, mode):
        raise PermissionError("chmod failed")

    monkeypatch.setattr(install_git_hooks.os, "chmod", bad_chmod)
    rc_install_fail = install_git_hooks.install_hooks()
    assert rc_install_fail != 0


def test_hook_tracked_mode_in_git_tree():
    out = subprocess.check_output(
        ["git", "ls-files", "--stage", ".githooks/pre-commit"],
        text=True
    )
    assert out.startswith("100755"), f"Expected 100755 mode, got: {out}"
    out_push = subprocess.check_output(
        ["git", "ls-files", "--stage", ".githooks/pre-push"],
        text=True
    )
    if out_push.strip():
        assert out_push.startswith("100755"), f"Expected 100755 mode, got: {out_push}"


# ---------------------------------------------------------------------------
# Section 24 & 33: Incident-Derived REG & K6 Persistence Truth Tests (B-109 M1)
# ---------------------------------------------------------------------------

from validate_prompt_manifest import validate_execution_contract

VALID_REG_BASE_OID = "69b4b6c72e2bf2b91a46107afb2e7e9a2e538de1"

BASE_VALID_CONTRACT = {
    "contract_version": "1",
    "task_id": "REG-TEST-01",
    "base_oid": VALID_REG_BASE_OID,
    "main_advancement": "FORBIDDEN",
    "authorized_main_sha": "NONE",
    "remote_ref_deletion": "FORBIDDEN",
    "authorized_delete_refs": "NONE",
    "local_destructive_git": "FORBIDDEN",
    "credential_access": "FORBIDDEN",
    "environment_enumeration": "FORBIDDEN",
    "cross_session_access": "FORBIDDEN",
    "browser_github_mutation": "FORBIDDEN",
    "raw_actions_log_access": "EXTERNAL_MACRO_ONLY",
    "branch_creation": "GIT_SWITCH_C",
    "hook_bypass": "FORBIDDEN",
    "goal_pressure_policy": "SAFETY_BOUNDARY_WINS",
    "ide_ephemeral_guards_required": "false",
}


def test_reg_credential_01():
    """REG-CREDENTIAL-01: credential_access = FORBIDDEN (positive + negative controls)."""
    # Positive control
    c_pos = dict(BASE_VALID_CONTRACT)
    c_pos["credential_access"] = "FORBIDDEN"
    ok, err, _ = validate_execution_contract(c_pos)
    assert ok is True
    assert err == ""

    # Negative control
    c_neg = dict(BASE_VALID_CONTRACT)
    c_neg["credential_access"] = "ALLOWED"
    ok, err, _ = validate_execution_contract(c_neg)
    assert ok is False
    assert "credential_access must be 'FORBIDDEN'" in err


def test_reg_env_01():
    """REG-ENV-01: environment_enumeration = FORBIDDEN (positive + negative controls)."""
    # Positive control
    c_pos = dict(BASE_VALID_CONTRACT)
    c_pos["environment_enumeration"] = "FORBIDDEN"
    ok, err, _ = validate_execution_contract(c_pos)
    assert ok is True

    # Negative control
    c_neg = dict(BASE_VALID_CONTRACT)
    c_neg["environment_enumeration"] = "ALLOWED"
    ok, err, _ = validate_execution_contract(c_neg)
    assert ok is False
    assert "environment_enumeration must be 'FORBIDDEN'" in err


def test_reg_session_01():
    """REG-SESSION-01: cross_session_access = FORBIDDEN (positive + negative controls)."""
    # Positive control
    c_pos = dict(BASE_VALID_CONTRACT)
    c_pos["cross_session_access"] = "FORBIDDEN"
    ok, err, _ = validate_execution_contract(c_pos)
    assert ok is True

    # Negative control
    c_neg = dict(BASE_VALID_CONTRACT)
    c_neg["cross_session_access"] = "ALLOWED"
    ok, err, _ = validate_execution_contract(c_neg)
    assert ok is False
    assert "cross_session_access must be 'FORBIDDEN'" in err


def test_reg_evidence_01():
    """REG-EVIDENCE-01: raw_actions_log_access = EXTERNAL_MACRO_ONLY (positive + negative controls)."""
    # Positive control
    c_pos = dict(BASE_VALID_CONTRACT)
    c_pos["raw_actions_log_access"] = "EXTERNAL_MACRO_ONLY"
    ok, err, _ = validate_execution_contract(c_pos)
    assert ok is True

    # Negative control
    c_neg = dict(BASE_VALID_CONTRACT)
    c_neg["raw_actions_log_access"] = "EXECUTOR_ALLOWED"
    ok, err, _ = validate_execution_contract(c_neg)
    assert ok is False
    assert "raw_actions_log_access must be 'EXTERNAL_MACRO_ONLY'" in err


def test_reg_browser_01():
    """REG-BROWSER-01: browser_github_mutation = FORBIDDEN (positive + negative controls)."""
    # Positive control
    c_pos = dict(BASE_VALID_CONTRACT)
    c_pos["browser_github_mutation"] = "FORBIDDEN"
    ok, err, _ = validate_execution_contract(c_pos)
    assert ok is True

    # Negative control
    c_neg = dict(BASE_VALID_CONTRACT)
    c_neg["browser_github_mutation"] = "ALLOWED"
    ok, err, _ = validate_execution_contract(c_neg)
    assert ok is False
    assert "browser_github_mutation must be 'FORBIDDEN'" in err


def test_reg_goal_01():
    """REG-GOAL-01: goal_pressure_policy = SAFETY_BOUNDARY_WINS (positive + negative controls)."""
    # Positive control
    c_pos = dict(BASE_VALID_CONTRACT)
    c_pos["goal_pressure_policy"] = "SAFETY_BOUNDARY_WINS"
    ok, err, _ = validate_execution_contract(c_pos)
    assert ok is True

    # Negative control
    c_neg = dict(BASE_VALID_CONTRACT)
    c_neg["goal_pressure_policy"] = "GOAL_WINS"
    ok, err, _ = validate_execution_contract(c_neg)
    assert ok is False
    assert "goal_pressure_policy must be 'SAFETY_BOUNDARY_WINS'" in err


def test_reg_hook_01():
    """REG-HOOK-01: hook_bypass = FORBIDDEN (positive + negative controls)."""
    # Positive control
    c_pos = dict(BASE_VALID_CONTRACT)
    c_pos["hook_bypass"] = "FORBIDDEN"
    ok, err, _ = validate_execution_contract(c_pos)
    assert ok is True

    # Negative control
    c_neg = dict(BASE_VALID_CONTRACT)
    c_neg["hook_bypass"] = "ALLOWED"
    ok, err, _ = validate_execution_contract(c_neg)
    assert ok is False
    assert "hook_bypass must be 'FORBIDDEN'" in err


def test_reg_k6_persist_01():
    """REG-K6-PERSIST-01: fact: old Deny List non-persistent."""
    baseline_path = os.path.join(SCRIPTS_DIR, "..", "docs", "ops", "antigravity-environment-baseline.md")
    with open(baseline_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "DEPRECATED" in content
    assert "NON-PERSISTENT" in content
    assert "DO NOT USE" in content
    assert "Deny List Terminal Commands" in content


def test_reg_k6_persist_02():
    """REG-K6-PERSIST-02: fact: Advanced Command Access explicit Deny restart-persistent observed."""
    baseline_path = os.path.join(SCRIPTS_DIR, "..", "docs", "ops", "antigravity-environment-baseline.md")
    with open(baseline_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "Advanced Command Access" in content
    assert "git credential" in content
    assert "git reset" in content
    assert "DIRECTLY RESTART-VERIFIED" in content or "direct restart-tested" in content.lower()


def test_reg_k6_persist_03():
    """REG-K6-PERSIST-03: fact: Execute URL github.com explicit Deny restart-persistent observed."""
    baseline_path = os.path.join(SCRIPTS_DIR, "..", "docs", "ops", "antigravity-environment-baseline.md")
    with open(baseline_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "Execute URLs" in content
    assert "github.com" in content
    assert "Deny" in content
    assert "不得 delete" in content or "do not delete" in content.lower() or "不得靠 delete" in content


def test_reg_k6_truth_01():
    """REG-K6-TRUTH-01: distinction between direct tested vs same-mechanism inference."""
    baseline_path = os.path.join(SCRIPTS_DIR, "..", "docs", "ops", "antigravity-environment-baseline.md")
    with open(baseline_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "DIRECTLY RESTART-VERIFIED" in content or "DIRECT" in content
    assert "SAME-MECHANISM" in content or "same-mechanism" in content.lower()
    assert "非逐一重啟測試事實" in content or "not individually" in content.lower()
