"""Unit tests for verification_primitives.py (Pilot INC-A, B-69).

All tests execute the production tool via subprocess using sys.executable.
No parallel comparison logic replaces the production tool.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL_PATH = Path(__file__).resolve().parent.parent / "verification_primitives.py"


def run_tool(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    cmd = [sys.executable, str(TOOL_PATH), *args]
    return subprocess.run(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_t1_count_match(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    needle = tmp_path / "needle.txt"
    target.write_bytes(b"apple\nbanana\napple\ncherry\n")
    needle.write_bytes(b"apple\n")

    res = run_tool("count", "--target", str(target), "--needle-file", str(needle), "--expect", "2")
    assert res.returncode == 0
    data = json.loads(res.stdout.decode("ascii"))
    assert data["tool"] == "verification_primitives"
    assert data["version"] == 1
    assert data["command"] == "count"
    assert data["status"] == "PASS"
    assert data["count"] == 2
    assert data["expect"] == 2
    assert data["target_sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()


def test_t2_count_mismatch(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    needle = tmp_path / "needle.txt"
    target.write_bytes(b"apple\nbanana\napple\n")
    needle.write_bytes(b"apple\n")

    res = run_tool("count", "--target", str(target), "--needle-file", str(needle), "--expect", "1")
    assert res.returncode == 1
    data = json.loads(res.stdout.decode("ascii"))
    assert data["command"] == "count"
    assert data["status"] == "CANDIDATE_INVALID"
    assert data["count"] == 2
    assert data["expect"] == 1


def test_t3_count_no_expect(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    needle = tmp_path / "needle.txt"
    target.write_bytes(b"apple\nbanana\napple\n")
    needle.write_bytes(b"apple\n")

    res = run_tool("count", "--target", str(target), "--needle-file", str(needle))
    assert res.returncode == 0
    data = json.loads(res.stdout.decode("ascii"))
    assert data["command"] == "count"
    assert data["status"] == "REPORT"
    assert data["count"] == 2
    assert data["expect"] is None


def test_t4_count_crlf_target_and_lf_target(tmp_path: Path) -> None:
    target_crlf = tmp_path / "target_crlf.txt"
    target_lf = tmp_path / "target_lf.txt"
    needle_lf = tmp_path / "needle_lf.txt"

    target_crlf.write_bytes(b"item1\r\nitem2\r\nitem1\r\n")
    target_lf.write_bytes(b"item1\nitem2\nitem1\n")
    needle_lf.write_bytes(b"item1\n")

    res_crlf = run_tool("count", "--target", str(target_crlf), "--needle-file", str(needle_lf))
    res_lf = run_tool("count", "--target", str(target_lf), "--needle-file", str(needle_lf))

    assert res_crlf.returncode == 0
    assert res_lf.returncode == 0
    data_crlf = json.loads(res_crlf.stdout.decode("ascii"))
    data_lf = json.loads(res_lf.stdout.decode("ascii"))

    assert data_crlf["count"] == 2
    assert data_lf["count"] == 2
    assert data_crlf["count"] == data_lf["count"]


def test_t5_needle_trailing_newline_strip(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    needle_single = tmp_path / "needle_single.txt"
    needle_double = tmp_path / "needle_double.txt"

    # target has "token other" without trailing newline after token
    target.write_bytes(b"token other\n")
    needle_single.write_bytes(b"token\n")
    needle_double.write_bytes(b"token\n\n")

    res_single = run_tool("count", "--target", str(target), "--needle-file", str(needle_single))
    res_double = run_tool("count", "--target", str(target), "--needle-file", str(needle_double))

    assert res_single.returncode == 0
    assert res_double.returncode == 0
    data_single = json.loads(res_single.stdout.decode("ascii"))
    data_double = json.loads(res_double.stdout.decode("ascii"))

    # Single trailing newline stripped: "token" matches 1
    assert data_single["count"] == 1
    # Double trailing newline only stripped one: "token\n" matches 0
    assert data_double["count"] == 0


def test_t6_needle_has_bom_and_target_has_bom(tmp_path: Path) -> None:
    needle_bom = tmp_path / "needle_bom.txt"
    needle_bom.write_bytes(b"\xef\xbb\xbfpattern\n")
    target_clean = tmp_path / "target_clean.txt"
    target_clean.write_bytes(b"pattern exists here\n")

    res_bom = run_tool("count", "--target", str(target_clean), "--needle-file", str(needle_bom))
    assert res_bom.returncode == 2
    data_bom = json.loads(res_bom.stdout.decode("ascii"))
    assert data_bom["status"] == "VERIFICATION_TOOL_UNABLE_TO_COMPLETE"
    assert data_bom["reason"] == "NEEDLE_HAS_BOM"

    target_bom = tmp_path / "target_bom.txt"
    target_bom.write_bytes(b"\xef\xbb\xbfpattern exists here\n")
    needle_clean = tmp_path / "needle_clean.txt"
    needle_clean.write_bytes(b"pattern\n")

    res_tb = run_tool("count", "--target", str(target_bom), "--needle-file", str(needle_clean))
    assert res_tb.returncode == 0
    data_tb = json.loads(res_tb.stdout.decode("ascii"))
    assert data_tb["count"] == 1


def test_t7_count_error_conditions(tmp_path: Path) -> None:
    # 1. UTF8_DECODE_ERROR
    bad_target = tmp_path / "bad_target.bin"
    bad_target.write_bytes(b"\xff\xfe\xfa")
    good_needle = tmp_path / "good_needle.txt"
    good_needle.write_bytes(b"test\n")

    res_utf8 = run_tool("count", "--target", str(bad_target), "--needle-file", str(good_needle))
    assert res_utf8.returncode == 2
    assert json.loads(res_utf8.stdout.decode("ascii"))["reason"] == "UTF8_DECODE_ERROR"

    # 2. FILE_READ_ERROR
    missing_target = tmp_path / "non_existent.txt"
    res_fnf = run_tool("count", "--target", str(missing_target), "--needle-file", str(good_needle))
    assert res_fnf.returncode == 2
    assert json.loads(res_fnf.stdout.decode("ascii"))["reason"] == "FILE_READ_ERROR"

    # 3. EMPTY_NEEDLE (empty file, only LF, or only CRLF)
    empty_needle = tmp_path / "empty_needle.txt"
    empty_needle.write_bytes(b"")
    good_target = tmp_path / "good_target.txt"
    good_target.write_bytes(b"some content\n")

    res_empty = run_tool("count", "--target", str(good_target), "--needle-file", str(empty_needle))
    assert res_empty.returncode == 2
    assert json.loads(res_empty.stdout.decode("ascii"))["reason"] == "EMPTY_NEEDLE"

    lf_only_needle = tmp_path / "lf_only.txt"
    lf_only_needle.write_bytes(b"\n")
    res_lf_only = run_tool("count", "--target", str(good_target), "--needle-file", str(lf_only_needle))
    assert res_lf_only.returncode == 2
    assert json.loads(res_lf_only.stdout.decode("ascii"))["reason"] == "EMPTY_NEEDLE"

    crlf_only_needle = tmp_path / "crlf_only.txt"
    crlf_only_needle.write_bytes(b"\r\n")
    res_crlf_only = run_tool("count", "--target", str(good_target), "--needle-file", str(crlf_only_needle))
    assert res_crlf_only.returncode == 2
    assert json.loads(res_crlf_only.stdout.decode("ascii"))["reason"] == "EMPTY_NEEDLE"


def test_t8_near_production_encoding_cp950(tmp_path: Path) -> None:
    test_char = "✓"
    non_bmp_char = "🚀"

    with pytest.raises(UnicodeEncodeError):
        test_char.encode("cp950")
    assert ord(non_bmp_char) > 0xFFFF

    target = tmp_path / "target_cp950.txt"
    needle = tmp_path / "needle_cp950.txt"
    target.write_text(f"prefix {test_char} {non_bmp_char} suffix\n", encoding="utf-8")
    needle.write_text(f"{test_char} {non_bmp_char}\n", encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp950"
    env["PYTHONUTF8"] = "0"

    res = run_tool("count", "--target", str(target), "--needle-file", str(needle), "--expect", "1", env=env)
    assert res.returncode == 0
    assert all(b < 128 for b in res.stdout)
    data = json.loads(res.stdout.decode("ascii"))
    assert data["status"] == "PASS"
    assert data["count"] == 1


def test_t9_sha256_behaviors(tmp_path: Path) -> None:
    crlf_file = tmp_path / "crlf.txt"
    crlf_bytes = b"first line\r\nsecond line\r\n"
    crlf_file.write_bytes(crlf_bytes)

    lf_file = tmp_path / "lf.txt"
    lf_bytes = b"first line\nsecond line\n"
    lf_file.write_bytes(lf_bytes)

    # CRLF file: raw and lf sha256 differ
    res_crlf = run_tool("sha256", "--file", str(crlf_file))
    assert res_crlf.returncode == 0
    data_crlf = json.loads(res_crlf.stdout.decode("ascii"))
    assert data_crlf["sha256_raw"] != data_crlf["sha256_lf"]
    assert data_crlf["sha256_raw"] == hashlib.sha256(crlf_bytes).hexdigest()
    assert data_crlf["sha256_lf"] == hashlib.sha256(lf_bytes).hexdigest()

    # LF file: raw and lf sha256 are identical
    res_lf = run_tool("sha256", "--file", str(lf_file))
    assert res_lf.returncode == 0
    data_lf = json.loads(res_lf.stdout.decode("ascii"))
    assert data_lf["sha256_raw"] == data_lf["sha256_lf"]

    # Expect mismatch -> exit 1 / CANDIDATE_INVALID
    res_mismatch = run_tool("sha256", "--file", str(crlf_file), "--expect-raw", "0" * 64)
    assert res_mismatch.returncode == 1
    data_mm = json.loads(res_mismatch.stdout.decode("ascii"))
    assert data_mm["status"] == "CANDIDATE_INVALID"

    # All expect match -> exit 0 / PASS
    raw_sha = data_crlf["sha256_raw"]
    lf_sha = data_crlf["sha256_lf"]
    res_match = run_tool("sha256", "--file", str(crlf_file), "--expect-raw", raw_sha, "--expect-lf", lf_sha)
    assert res_match.returncode == 0
    data_m = json.loads(res_match.stdout.decode("ascii"))
    assert data_m["status"] == "PASS"

    # Non-hex expect -> exit 2 / INVALID_EXPECT
    res_invalid_expect = run_tool("sha256", "--file", str(crlf_file), "--expect-raw", "not_a_valid_hex")
    assert res_invalid_expect.returncode == 2
    data_ie = json.loads(res_invalid_expect.stdout.decode("ascii"))
    assert data_ie["status"] == "VERIFICATION_TOOL_UNABLE_TO_COMPLETE"
    assert data_ie["reason"] == "INVALID_EXPECT"


def test_t10_git_diff_digest(tmp_path: Path) -> None:
    # 1. Initialize temporary git repository
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=tmp_path, check=True)

    tracked_file = tmp_path / "tracked.txt"
    tracked_file.write_bytes(b"initial line\n")

    subprocess.run(
        ["git", "-c", "user.name=TestUser", "-c", "user.email=test@example.com", "add", "tracked.txt"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "-c", "user.name=TestUser", "-c", "user.email=test@example.com", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # 2. Modify worktree with cp950 non-encodable char and add untracked file
    tracked_file.write_text("initial line\nmodified ✓ 🚀\n", encoding="utf-8")
    untracked_file = tmp_path / "untracked.txt"
    untracked_file.write_text("untracked payload\n", encoding="utf-8")

    # Read-only status before
    status_before = subprocess.run(["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True).stdout

    # 3. Run tool worktree mode
    res1 = run_tool("git-diff-digest", "--base", base_sha, "--repo-root", str(tmp_path))
    assert res1.returncode == 0
    data1 = json.loads(res1.stdout.decode("ascii"))
    assert data1["status"] == "REPORT"
    assert data1["changed_paths"] == ["tracked.txt"]
    assert data1["untracked_paths"] == ["untracked.txt"]

    # 4. Compare diff_sha256 with exact git diff stdout bytes SHA-256
    git_diff_proc = subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "core.quotepath=false",
            "-c",
            "color.ui=never",
            "diff",
            "--binary",
            "--full-index",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            base_sha,
        ],
        capture_output=True,
        check=True,
    )
    expected_diff_sha256 = hashlib.sha256(git_diff_proc.stdout).hexdigest()
    assert data1["diff_sha256"] == expected_diff_sha256

    # 5. Continuous two runs yield identical results
    res2 = run_tool("git-diff-digest", "--base", base_sha, "--repo-root", str(tmp_path))
    assert res2.returncode == 0
    data2 = json.loads(res2.stdout.decode("ascii"))
    assert data1 == data2

    # 6. Read-only negative control: status after equals status before
    status_after = subprocess.run(["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True).stdout
    assert status_before == status_after

    # 7. Expect mismatch -> exit 1
    res_mismatch = run_tool("git-diff-digest", "--base", base_sha, "--expect", "0" * 64, "--repo-root", str(tmp_path))
    assert res_mismatch.returncode == 1
    data_mm = json.loads(res_mismatch.stdout.decode("ascii"))
    assert data_mm["status"] == "CANDIDATE_INVALID"

    # 8. Expect match -> exit 0
    res_match = run_tool(
        "git-diff-digest",
        "--base",
        base_sha,
        "--expect",
        expected_diff_sha256,
        "--repo-root",
        str(tmp_path),
    )
    assert res_match.returncode == 0
    data_m = json.loads(res_match.stdout.decode("ascii"))
    assert data_m["status"] == "PASS"

    # 9. Cached mode
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    res_cached = run_tool("git-diff-digest", "--base", base_sha, "--mode", "cached", "--repo-root", str(tmp_path))
    assert res_cached.returncode == 0
    data_cached = json.loads(res_cached.stdout.decode("ascii"))
    assert data_cached["mode"] == "cached"
    assert data_cached["changed_paths"] == ["tracked.txt"]

    # 10. Head mode
    subprocess.run(
        ["git", "-c", "user.name=TestUser", "-c", "user.email=test@example.com", "commit", "-m", "second"],
        cwd=tmp_path,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    res_head = run_tool("git-diff-digest", "--base", base_sha, "--mode", "head", "--repo-root", str(tmp_path))
    assert res_head.returncode == 0
    data_head = json.loads(res_head.stdout.decode("ascii"))
    assert data_head["mode"] == "head"
    assert data_head["changed_paths"] == ["tracked.txt"]

    # 11. INVALID_BASE -> exit 2
    res_inv = run_tool("git-diff-digest", "--base", "INVALID_BASE_HEX", "--repo-root", str(tmp_path))
    assert res_inv.returncode == 2
    assert json.loads(res_inv.stdout.decode("ascii"))["reason"] == "INVALID_BASE"

    # 12. BASE_NOT_FOUND (non-existent commit) -> exit 2
    res_bnf = run_tool("git-diff-digest", "--base", "0" * 40, "--repo-root", str(tmp_path))
    assert res_bnf.returncode == 2
    assert json.loads(res_bnf.stdout.decode("ascii"))["reason"] == "BASE_NOT_FOUND"

    # 13. BASE_NOT_FOUND (non-repo directory) -> exit 2
    non_repo_dir = tmp_path / "non_repo_directory"
    non_repo_dir.mkdir()
    res_non_repo = run_tool("git-diff-digest", "--base", "a" * 40, "--repo-root", str(non_repo_dir))
    assert res_non_repo.returncode == 2
    assert json.loads(res_non_repo.stdout.decode("ascii"))["reason"] == "BASE_NOT_FOUND"
