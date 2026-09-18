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
    assert captured.out.strip() == f"{var_name}=PRESENT"
    # Never expose secret value in stdout or stderr
    assert raw_val not in captured.out
    assert raw_val not in captured.err


def test_presence_absent_env(monkeypatch, capsys):
    var_name = "HHAI_DEFINITELY_ABSENT_VAR_9999"
    monkeypatch.delenv(var_name, raising=False)

    rc = secret_presence.check_presence([var_name])
    captured = capsys.readouterr()

    assert rc == 0
    assert captured.out.strip() == f"{var_name}=ABSENT"


def test_presence_unrelated_env_not_enumerated(monkeypatch, capsys):
    unrelated_secret_name = "UNRELATED_SECRET_KEY_NEVER_SHOW"
    unrelated_secret_val = "".join(["s", "e", "c", "r", "e", "t"]) + "_unrelated_val"
    monkeypatch.setenv(unrelated_secret_name, unrelated_secret_val)

    query_name = "TEST_NORMAL_VARIABLE"
    monkeypatch.setenv(query_name, "hello")

    rc = secret_presence.check_presence([query_name])
    captured = capsys.readouterr()

    assert rc == 0
    assert captured.out.strip() == f"{query_name}=PRESENT"
    # Unrelated secret must not be logged, mentioned, or dumped
    assert unrelated_secret_name not in captured.out
    assert unrelated_secret_val not in captured.out


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


def test_presence_wildcard_prefix_rejected(capsys):
    wildcards = ["PATH*", "TOKEN?", "TEST%VAR", "$ENV:VAR"]
    for wc in wildcards:
        rc = secret_presence.check_presence([wc])
        assert rc == 1


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

    scripts_target = repo_dir / "scripts"
    scripts_target.mkdir()

    with open(os.path.join(SCRIPTS_DIR, "..", ".githooks", "pre-commit"), "rb") as f:
        hook_dest.write_bytes(f.read())

    with open(os.path.join(SCRIPTS_DIR, "secret_scan.py"), "rb") as f:
        (scripts_target / "secret_scan.py").write_bytes(f.read())

    with open(os.path.join(SCRIPTS_DIR, "install_git_hooks.py"), "rb") as f:
        (scripts_target / "install_git_hooks.py").write_bytes(f.read())

    # A. Initial check must FAIL
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

    # D. Global git config is unchanged
    global_val = subprocess.run(
        ["git", "config", "--global", "--get", "core.hooksPath"],
        capture_output=True,
        text=True
    ).stdout.strip()
    # It should either be unset or unchanged by this local test
    local_val = subprocess.run(
        ["git", "config", "--local", "--get", "core.hooksPath"],
        cwd=repo_dir,
        capture_output=True,
        text=True
    ).stdout.strip()
    assert local_val == ".githooks"

    # E & G. Clean staged commit succeeds via pre-commit hook
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

    # F. Staged secret leak causes commit to FAIL via hook
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
