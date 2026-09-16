#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tests/test_shared_primitives.py

E-03 Phase 2 Wave 1A: Canonical tests for shared pure primitives
- shared/dlpSanitizer.js
- shared/atomicFs.js
"""

import json
import os
import subprocess
import sys
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def eval_in_node(script: str) -> str:
    """Execute javascript in node with REPO_ROOT as cwd and return trimmed stdout."""
    res = subprocess.run(
        ["node", "-e", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True
    )
    if res.returncode != 0:
        raise RuntimeError(f"Node execution failed (code {res.returncode}):\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
    return res.stdout.strip()


# ==============================================================================
# DLP Sanitizer Tests (Primitive 1)
# ==============================================================================

def test_dlp_loads_without_third_party_deps():
    """Requirement 13: Module loads cleanly with zero third-party packages."""
    out = eval_in_node("const dlp = require('./shared/dlpSanitizer.js'); console.log(typeof dlp.sanitizeDlp);")
    assert out == "function"


def test_dlp_ordinary_text_unchanged():
    """Requirement 1: Ordinary text remains unchanged."""
    text = "Hello world! This is a completely standard text without secrets."
    cmd = f"""
    const {{ sanitizeDlp }} = require('./shared/dlpSanitizer.js');
    console.log(sanitizeDlp({json.dumps(text)}));
    """
    assert eval_in_node(cmd) == text


def test_dlp_git_sha_unchanged():
    """Requirement 2: 40-character Git SHA is excluded from token redaction."""
    sha = "c73dd28ce25c74caf46b9477410d7e405f0d7a46"
    cmd = f"""
    const {{ sanitizeDlp }} = require('./shared/dlpSanitizer.js');
    console.log(sanitizeDlp({json.dumps(sha)}));
    """
    assert eval_in_node(cmd) == sha


def test_dlp_uuid_unchanged():
    """Requirement 3: UUID format is excluded from token redaction."""
    uuid_str = "1d97dad0-4d98-436a-b467-9d47535ad9a7"
    cmd = f"""
    const {{ sanitizeDlp }} = require('./shared/dlpSanitizer.js');
    console.log(sanitizeDlp({json.dumps(uuid_str)}));
    """
    assert eval_in_node(cmd) == uuid_str


def test_dlp_pure_numeric_unchanged():
    """Requirement 4: Pure numeric string is excluded from token redaction."""
    num_str = "1234567890123456789012345678901234567890"
    cmd = f"""
    const {{ sanitizeDlp }} = require('./shared/dlpSanitizer.js');
    console.log(sanitizeDlp({json.dumps(num_str)}));
    """
    assert eval_in_node(cmd) == num_str


def test_dlp_gemini_key_redacted():
    """Requirement 5: Representative Gemini-like key is redacted."""
    dummy_key = "AIzaSy" + "A" * 33
    cmd = f"""
    const {{ sanitizeDlp }} = require('./shared/dlpSanitizer.js');
    console.log(sanitizeDlp('Key: ' + {json.dumps(dummy_key)}));
    """
    assert eval_in_node(cmd) == "Key: [DLP_GEMINI_KEY]"


def test_dlp_telegram_token_redacted():
    """Requirement 6: Representative Telegram-like bot token is redacted."""
    dummy_token = "123456789:" + "A" * 35
    cmd = f"""
    const {{ sanitizeDlp }} = require('./shared/dlpSanitizer.js');
    console.log(sanitizeDlp('Bot token: ' + {json.dumps(dummy_token)}));
    """
    assert eval_in_node(cmd) == "Bot token: [DLP_TELEGRAM_TOKEN]"


def test_dlp_postgres_password_redacted():
    """Requirement 7: Postgres password component is redacted."""
    conn_str = "postgres://app_user:SuperSecretPassword123@db.example.internal:5432/maindb"
    cmd = f"""
    const {{ sanitizeDlp }} = require('./shared/dlpSanitizer.js');
    console.log(sanitizeDlp({json.dumps(conn_str)}));
    """
    assert eval_in_node(cmd) == "postgres://app_user:[DLP_DB_PWD]@db.example.internal:5432/maindb"


def test_dlp_high_entropy_token_redacted():
    """Requirement 8: High-entropy 40+ token is redacted."""
    high_entropy = "Token_abc123_XYZ_789_abcdefg_HIJKLMNOP_12345_6789"
    cmd = f"""
    const {{ sanitizeDlp }} = require('./shared/dlpSanitizer.js');
    console.log(sanitizeDlp('Auth ' + {json.dumps(high_entropy)}));
    """
    assert eval_in_node(cmd) == "Auth [DLP_LONG_TOKEN]"


def test_dlp_path_false_positive_protection():
    """Windows and Unix paths are protected from false-positive long-token redaction."""
    win_path = r"C:\Users\HH.AI_260806\Desktop\HH.AI_v2\skills\execution\playwright-automation\lib\helpers.js"
    unix_path = "/var/log/application/services/deployment/production/frontend/access.log"
    cmd = f"""
    const {{ sanitizeDlp }} = require('./shared/dlpSanitizer.js');
    console.log(sanitizeDlp({json.dumps(win_path)}));
    console.log(sanitizeDlp({json.dumps(unix_path)}));
    """
    out = eval_in_node(cmd).splitlines()
    assert out[0] == win_path
    assert out[1] == unix_path


def test_dlp_falsy_and_object_handling():
    """Falsy values return as-is; objects are stringified and sanitized."""
    cmd = """
    const { sanitizeDlp } = require('./shared/dlpSanitizer.js');
    console.log(sanitizeDlp(null) === null);
    console.log(sanitizeDlp('') === '');
    const obj = { key: 'AIzaSy' + 'A'.repeat(33) };
    console.log(sanitizeDlp(obj));
    """
    out = eval_in_node(cmd).splitlines()
    assert out[0] == "true"
    assert out[1] == "true"
    assert json.loads(out[2]) == {"key": "[DLP_GEMINI_KEY]"}


# ==============================================================================
# AtomicFS Tests (Primitive 2)
# ==============================================================================

def test_atomic_fs_loads_without_third_party_deps():
    """Requirement 13: Module loads cleanly without third-party dependencies."""
    out = eval_in_node("const afs = require('./shared/atomicFs.js'); console.log(typeof afs.writeStateAtomic);")
    assert out == "function"


def test_atomic_fs_new_file_write_success(tmp_path):
    """Requirement 9: New file write returns true and creates the file."""
    target_file = tmp_path / "state_new.json"
    target_str = str(target_file).replace("\\", "/")
    content = '{"status": "OK", "agent": "Antigravity"}'

    cmd = f"""
    const {{ writeStateAtomic }} = require('./shared/atomicFs.js');
    const res = writeStateAtomic({json.dumps(target_str)}, {json.dumps(content)});
    console.log(res);
    """
    assert eval_in_node(cmd) == "true"
    assert target_file.exists()


def test_atomic_fs_contents_exact_utf8(tmp_path):
    """Requirement 10: Written contents are exact UTF-8."""
    target_file = tmp_path / "utf8_test.txt"
    target_str = str(target_file).replace("\\", "/")
    utf8_content = "測試繁體中文 UTF-8 寫入 🚀 [Antigravity] 狀態持久化: 100% 成功。"

    cmd = f"""
    const {{ writeStateAtomic }} = require('./shared/atomicFs.js');
    writeStateAtomic({json.dumps(target_str)}, {json.dumps(utf8_content)});
    """
    eval_in_node(cmd)

    read_back = target_file.read_text(encoding="utf-8")
    assert read_back == utf8_content


def test_atomic_fs_replacement_consistency(tmp_path):
    """Requirement 11: Second write / replacement behavior is consistent and atomic."""
    target_file = tmp_path / "replace_test.json"
    target_str = str(target_file).replace("\\", "/")

    cmd = f"""
    const {{ writeStateAtomic }} = require('./shared/atomicFs.js');
    const r1 = writeStateAtomic({json.dumps(target_str)}, 'VERSION_1');
    const r2 = writeStateAtomic({json.dumps(target_str)}, 'VERSION_2');
    console.log(r1 + ',' + r2);
    """
    assert eval_in_node(cmd) == "true,true"
    assert target_file.read_text(encoding="utf-8") == "VERSION_2"


def test_atomic_fs_temp_file_cleaned_up(tmp_path):
    """Requirement 12: Temporary file does not remain after successful write."""
    target_file = tmp_path / "cleanup_test.json"
    target_str = str(target_file).replace("\\", "/")

    cmd = f"""
    const {{ writeStateAtomic }} = require('./shared/atomicFs.js');
    writeStateAtomic({json.dumps(target_str)}, 'DATA');
    """
    eval_in_node(cmd)

    files_in_dir = list(tmp_path.iterdir())
    assert len(files_in_dir) == 1
    assert files_in_dir[0].name == "cleanup_test.json"
    assert not any(f.name.endswith(".tmp") for f in files_in_dir)
