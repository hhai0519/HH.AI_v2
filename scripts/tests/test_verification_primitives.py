"""Unit tests for verification_primitives.py (Pilot INC-C, B-69).

All tests execute the production tool via subprocess using sys.executable.
No parallel comparison logic replaces the production tool.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.server
import json
import os
import subprocess
import sys
import threading
import urllib.parse
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


def test_t11_multiline_crlf_normalization(tmp_path: Path) -> None:
    # target CRLF: "alpha\r\nbeta\r\n", needle LF: "alpha\nbeta\n" -> count 1
    target1 = tmp_path / "target1.txt"
    needle1 = tmp_path / "needle1.txt"
    target1.write_bytes(b"alpha\r\nbeta\r\n")
    needle1.write_bytes(b"alpha\nbeta\n")

    res1 = run_tool("count", "--target", str(target1), "--needle-file", str(needle1), "--expect", "1")
    assert res1.returncode == 0
    data1 = json.loads(res1.stdout.decode("ascii"))
    assert data1["status"] == "PASS"
    assert data1["count"] == 1

    # needle CRLF: "alpha\r\nbeta\r\n", target LF: "alpha\nbeta\n" -> count 1
    target2 = tmp_path / "target2.txt"
    needle2 = tmp_path / "needle2.txt"
    target2.write_bytes(b"alpha\nbeta\n")
    needle2.write_bytes(b"alpha\r\nbeta\r\n")

    res2 = run_tool("count", "--target", str(target2), "--needle-file", str(needle2), "--expect", "1")
    assert res2.returncode == 0
    data2 = json.loads(res2.stdout.decode("ascii"))
    assert data2["status"] == "PASS"
    assert data2["count"] == 1


def test_t12_non_utf8_diff(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo_t12"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=repo_dir, check=True)

    f = repo_dir / "data.bin"
    f.write_bytes(b"initial line\n")
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@e.com", "add", "data.bin"], cwd=repo_dir, check=True)
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@e.com", "commit", "-m", "init"], cwd=repo_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, check=True).stdout.strip()

    # Modify with non-UTF-8 bytes
    non_utf8_payload = b"initial line\n\x80\x81\xff\xfe\n"
    with pytest.raises(UnicodeDecodeError):
        non_utf8_payload.decode("utf-8")

    f.write_bytes(non_utf8_payload)

    res = run_tool("git-diff-digest", "--base", base_sha, "--repo-root", str(repo_dir))
    assert res.returncode == 0
    data = json.loads(res.stdout.decode("ascii"))

    # Compute expected diff_sha256 from raw git diff bytes
    git_diff_proc = subprocess.run(
        [
            "git",
            "-C",
            str(repo_dir),
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
    assert data["diff_sha256"] == expected_diff_sha256


def test_t13_non_ascii_output_digest(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo_t13"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=repo_dir, check=True)

    test_char = "✓"
    with pytest.raises(UnicodeEncodeError):
        test_char.encode("cp950")

    filename = f"tracked_{test_char}.txt"
    f = repo_dir / filename
    f.write_text("initial\n", encoding="utf-8")

    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@e.com", "add", filename], cwd=repo_dir, check=True)
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@e.com", "commit", "-m", "init"], cwd=repo_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, check=True).stdout.strip()

    f.write_text("initial\nmodified\n", encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp950"
    env["PYTHONUTF8"] = "0"

    res = run_tool("git-diff-digest", "--base", base_sha, "--repo-root", str(repo_dir), env=env)
    assert res.returncode == 0
    assert all(b < 128 for b in res.stdout)
    data = json.loads(res.stdout.decode("ascii"))
    assert filename in data["changed_paths"]


class MockGitHubHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        server_state = getattr(self.server, "handler_state", {})
        recorded_requests = server_state.setdefault("recorded_requests", [])
        recorded_requests.append({
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
        })

        status_override = server_state.get("status_code_override")
        if status_override is not None:
            self.send_response(status_override)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"message": "error"}')
            return

        raw_override = server_state.get("raw_response_override")
        if raw_override is not None:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(raw_override)
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.endswith("/actions/runs"):
            runs_queue = server_state.get("runs_queue")
            if runs_queue:
                body = runs_queue.pop(0)
            else:
                body = server_state.get("default_runs", {"total_count": 0, "workflow_runs": []})
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.github+json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode("utf-8"))
            return

        if "/actions/runs/" in path and path.endswith("/jobs"):
            parts = path.split("/")
            run_id = None
            try:
                run_id_idx = parts.index("runs") + 1
                run_id = int(parts[run_id_idx])
            except (ValueError, IndexError):
                pass

            jobs_map = server_state.get("jobs_map", {})
            body = jobs_map.get(run_id, {"total_count": 0, "jobs": []})
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.github+json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()


class MockGitHubServer:
    def __init__(self) -> None:
        self.server = http.server.HTTPServer(("127.0.0.1", 0), MockGitHubHandler)
        self.server.handler_state = {
            "recorded_requests": [],
            "runs_queue": [],
            "jobs_map": {},
            "status_code_override": None,
            "raw_response_override": None,
        }
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        port = self.server.server_address[1]
        return f"http://127.0.0.1:{port}"

    @property
    def state(self) -> dict:
        return self.server.handler_state

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@contextlib.contextmanager
def mock_github_server():
    srv = MockGitHubServer()
    try:
        yield srv
    finally:
        srv.close()


def test_t14_ci_status_pass() -> None:
    with mock_github_server() as srv:
        head_sha = "a" * 40
        branch = "main"
        event = "push"
        workflow_name = "Verify"

        # 1. Single attempt PASS
        srv.state["default_runs"] = {
            "total_count": 1,
            "workflow_runs": [
                {
                    "id": 1001,
                    "name": workflow_name,
                    "head_sha": head_sha,
                    "head_branch": branch,
                    "event": event,
                    "status": "completed",
                    "conclusion": "success",
                    "run_attempt": 1,
                }
            ],
        }
        srv.state["jobs_map"][1001] = {
            "total_count": 2,
            "jobs": [
                {"id": 1, "name": "verify", "status": "completed", "conclusion": "success"},
                {"id": 2, "name": "gateway-windows", "status": "completed", "conclusion": "success"},
            ],
        }

        res = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--require-job", "gateway-windows",
            "--api-base", srv.url,
            "--max-attempts", "5",
            "--interval-seconds", "0",
        )
        assert res.returncode == 0
        data = json.loads(res.stdout.decode("ascii"))
        assert data["status"] == "PASS"
        assert data["command"] == "ci-status"
        assert data["attempts_used"] == 1
        assert data["run_id"] == 1001
        assert data["run_attempt"] == 1
        assert data["run_status"] == "completed"
        assert data["run_conclusion"] == "success"
        assert data["jobs"]["verify"] == {"status": "completed", "conclusion": "success"}
        assert data["jobs"]["gateway-windows"] == {"status": "completed", "conclusion": "success"}

        # Assert server received requests do NOT contain Authorization header
        for req in srv.state["recorded_requests"]:
            assert "authorization" not in req["headers"]

        # Assert query params in runs request contain head_sha, branch, event
        runs_req = [r for r in srv.state["recorded_requests"] if "/actions/runs?" in r["path"]][0]
        parsed_q = urllib.parse.parse_qs(urllib.parse.urlparse(runs_req["path"]).query)
        assert parsed_q["head_sha"] == [head_sha]
        assert parsed_q["branch"] == [branch]
        assert parsed_q["event"] == [event]

        # 2. Polling: two in_progress attempts, third completed PASS
        srv.state["recorded_requests"].clear()
        srv.state["runs_queue"] = [
            {
                "total_count": 1,
                "workflow_runs": [
                    {
                        "id": 1002,
                        "name": workflow_name,
                        "head_sha": head_sha,
                        "head_branch": branch,
                        "event": event,
                        "status": "in_progress",
                        "conclusion": None,
                        "run_attempt": 1,
                    }
                ],
            },
            {
                "total_count": 1,
                "workflow_runs": [
                    {
                        "id": 1002,
                        "name": workflow_name,
                        "head_sha": head_sha,
                        "head_branch": branch,
                        "event": event,
                        "status": "in_progress",
                        "conclusion": None,
                        "run_attempt": 1,
                    }
                ],
            },
            {
                "total_count": 1,
                "workflow_runs": [
                    {
                        "id": 1002,
                        "name": workflow_name,
                        "head_sha": head_sha,
                        "head_branch": branch,
                        "event": event,
                        "status": "completed",
                        "conclusion": "success",
                        "run_attempt": 1,
                    }
                ],
            },
        ]
        srv.state["jobs_map"][1002] = {
            "total_count": 2,
            "jobs": [
                {"id": 1, "name": "verify", "status": "completed", "conclusion": "success"},
                {"id": 2, "name": "gateway-windows", "status": "completed", "conclusion": "success"},
            ],
        }

        res2 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--require-job", "gateway-windows",
            "--api-base", srv.url,
            "--max-attempts", "5",
            "--interval-seconds", "0",
        )
        assert res2.returncode == 0
        data2 = json.loads(res2.stdout.decode("ascii"))
        assert data2["status"] == "PASS"
        assert data2["attempts_used"] == 3
        assert data2["run_id"] == 1002


def test_t15_ci_status_candidate_invalid() -> None:
    with mock_github_server() as srv:
        head_sha = "b" * 40
        branch = "main"

        # 1. run conclusion failure -> exit 1
        srv.state["default_runs"] = {
            "total_count": 1,
            "workflow_runs": [
                {
                    "id": 2001,
                    "name": "Verify",
                    "head_sha": head_sha,
                    "head_branch": branch,
                    "event": "push",
                    "status": "completed",
                    "conclusion": "failure",
                    "run_attempt": 1,
                }
            ],
        }
        srv.state["jobs_map"][2001] = {
            "total_count": 2,
            "jobs": [
                {"id": 1, "name": "verify", "status": "completed", "conclusion": "success"},
                {"id": 2, "name": "gateway-windows", "status": "completed", "conclusion": "success"},
            ],
        }
        res1 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--require-job", "gateway-windows",
            "--api-base", srv.url,
            "--max-attempts", "2",
            "--interval-seconds", "0",
        )
        assert res1.returncode == 1
        data1 = json.loads(res1.stdout.decode("ascii"))
        assert data1["status"] == "CANDIDATE_INVALID"
        assert data1["run_conclusion"] == "failure"

        # 2. run success but a required job failure -> exit 1
        srv.state["default_runs"] = {
            "total_count": 1,
            "workflow_runs": [
                {
                    "id": 2002,
                    "name": "Verify",
                    "head_sha": head_sha,
                    "head_branch": branch,
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                    "run_attempt": 1,
                }
            ],
        }
        srv.state["jobs_map"][2002] = {
            "total_count": 2,
            "jobs": [
                {"id": 1, "name": "verify", "status": "completed", "conclusion": "failure"},
                {"id": 2, "name": "gateway-windows", "status": "completed", "conclusion": "success"},
            ],
        }
        res2 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--require-job", "gateway-windows",
            "--api-base", srv.url,
            "--max-attempts", "2",
            "--interval-seconds", "0",
        )
        assert res2.returncode == 1
        data2 = json.loads(res2.stdout.decode("ascii"))
        assert data2["status"] == "CANDIDATE_INVALID"
        assert data2["jobs"]["verify"]["conclusion"] == "failure"

        # 3. required job missing -> exit 1
        srv.state["default_runs"] = {
            "total_count": 1,
            "workflow_runs": [
                {
                    "id": 2003,
                    "name": "Verify",
                    "head_sha": head_sha,
                    "head_branch": branch,
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                    "run_attempt": 1,
                }
            ],
        }
        srv.state["jobs_map"][2003] = {
            "total_count": 1,
            "jobs": [
                {"id": 1, "name": "verify", "status": "completed", "conclusion": "success"},
            ],
        }
        res3 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--require-job", "gateway-windows",
            "--api-base", srv.url,
            "--max-attempts", "2",
            "--interval-seconds", "0",
        )
        assert res3.returncode == 1
        data3 = json.loads(res3.stdout.decode("ascii"))
        assert data3["status"] == "CANDIDATE_INVALID"
        assert data3["jobs"]["gateway-windows"] is None


def test_t16_ci_status_unable() -> None:
    with mock_github_server() as srv:
        head_sha = "c" * 40
        branch = "main"

        # 1. Always in_progress up to max-attempts -> exit 2 / CI_PENDING_TIMEOUT
        srv.state["default_runs"] = {
            "total_count": 1,
            "workflow_runs": [
                {
                    "id": 3001,
                    "name": "Verify",
                    "head_sha": head_sha,
                    "head_branch": branch,
                    "event": "push",
                    "status": "in_progress",
                    "conclusion": None,
                    "run_attempt": 1,
                }
            ],
        }
        res1 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", srv.url,
            "--max-attempts", "2",
            "--interval-seconds", "0",
        )
        assert res1.returncode == 2
        data1 = json.loads(res1.stdout.decode("ascii"))
        assert data1["status"] == "VERIFICATION_TOOL_UNABLE_TO_COMPLETE"
        assert data1["reason"] == "CI_PENDING_TIMEOUT"
        assert data1["attempts_used"] == 2
        assert data1["run_id"] == 3001

        # 2. Always 0 runs -> exit 2 / CI_PENDING_TIMEOUT and run_id is null
        srv.state["default_runs"] = {"total_count": 0, "workflow_runs": []}
        res2 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", srv.url,
            "--max-attempts", "2",
            "--interval-seconds", "0",
        )
        assert res2.returncode == 2
        data2 = json.loads(res2.stdout.decode("ascii"))
        assert data2["status"] == "VERIFICATION_TOOL_UNABLE_TO_COMPLETE"
        assert data2["reason"] == "CI_PENDING_TIMEOUT"
        assert data2["run_id"] is None
        assert data2["attempts_used"] == 2

        # 3. Two matching runs -> exit 2 / AMBIGUOUS_RUNS
        srv.state["default_runs"] = {
            "total_count": 2,
            "workflow_runs": [
                {
                    "id": 3002,
                    "name": "Verify",
                    "head_sha": head_sha,
                    "head_branch": branch,
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                    "run_attempt": 1,
                },
                {
                    "id": 3003,
                    "name": "Verify",
                    "head_sha": head_sha,
                    "head_branch": branch,
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                    "run_attempt": 1,
                },
            ],
        }
        res3 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", srv.url,
            "--max-attempts", "1",
            "--interval-seconds", "0",
        )
        assert res3.returncode == 2
        data3 = json.loads(res3.stdout.decode("ascii"))
        assert data3["reason"] == "AMBIGUOUS_RUNS"

        # 4. Non-matching runs (different SHA, branch, workflow name, event) are ignored
        srv.state["default_runs"] = {
            "total_count": 4,
            "workflow_runs": [
                {
                    "id": 4001,
                    "name": "Verify",
                    "head_sha": "d" * 40,  # other SHA
                    "head_branch": branch,
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "id": 4002,
                    "name": "Verify",
                    "head_sha": head_sha,
                    "head_branch": "other-branch",  # other branch (must be ignored!)
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "id": 4003,
                    "name": "OtherWorkflow",  # other workflow name
                    "head_sha": head_sha,
                    "head_branch": branch,
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "id": 4004,
                    "name": "Verify",
                    "head_sha": head_sha,
                    "head_branch": branch,
                    "event": "push",  # exactly matching run!
                    "status": "completed",
                    "conclusion": "success",
                    "run_attempt": 1,
                },
            ],
        }
        srv.state["jobs_map"][4004] = {
            "total_count": 1,
            "jobs": [{"id": 1, "name": "verify", "status": "completed", "conclusion": "success"}],
        }
        res4 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", srv.url,
            "--max-attempts", "1",
            "--interval-seconds", "0",
        )
        assert res4.returncode == 0
        data4 = json.loads(res4.stdout.decode("ascii"))
        assert data4["status"] == "PASS"
        assert data4["run_id"] == 4004

        # 5. HTTP 403 -> exit 2 / HTTP_ERROR
        srv.state["status_code_override"] = 403
        res5 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", srv.url,
            "--max-attempts", "1",
            "--interval-seconds", "0",
        )
        assert res5.returncode == 2
        data5 = json.loads(res5.stdout.decode("ascii"))
        assert data5["reason"] == "HTTP_ERROR"
        srv.state["status_code_override"] = None

        # 6. Non-JSON response -> exit 2 / INVALID_RESPONSE
        srv.state["raw_response_override"] = b"<html>502 Bad Gateway</html>"
        res6 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", srv.url,
            "--max-attempts", "1",
            "--interval-seconds", "0",
        )
        assert res6.returncode == 2
        data6 = json.loads(res6.stdout.decode("ascii"))
        assert data6["reason"] == "INVALID_RESPONSE"
        srv.state["raw_response_override"] = None

        # 7. api-base is https://example.invalid -> exit 2 / INVALID_API_BASE and server receives 0 requests
        srv.state["recorded_requests"].clear()
        res7 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", "https://example.invalid",
            "--max-attempts", "1",
            "--interval-seconds", "0",
        )
        assert res7.returncode == 2
        data7 = json.loads(res7.stdout.decode("ascii"))
        assert data7["reason"] == "INVALID_API_BASE"
        assert len(srv.state["recorded_requests"]) == 0

        # 8. head-sha invalid -> exit 2 / INVALID_HEAD_SHA
        res8 = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", "NOT_A_HEX_SHA",
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", srv.url,
            "--max-attempts", "1",
            "--interval-seconds", "0",
        )
        assert res8.returncode == 2
        data8 = json.loads(res8.stdout.decode("ascii"))
        assert data8["reason"] == "INVALID_HEAD_SHA"


def test_t17_ci_status_reject_trailing_newline() -> None:
    with mock_github_server() as srv:
        head_sha = "c" * 40
        branch = "main"

        # (a) head-sha with trailing LF -> exit 2 / INVALID_HEAD_SHA
        srv.state["recorded_requests"].clear()
        res_sha = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha + "\n",
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", srv.url,
            "--max-attempts", "1",
            "--interval-seconds", "0",
        )
        assert res_sha.returncode == 2
        data_sha = json.loads(res_sha.stdout.decode("ascii"))
        assert data_sha["status"] == "VERIFICATION_TOOL_UNABLE_TO_COMPLETE"
        assert data_sha["reason"] == "INVALID_HEAD_SHA"
        assert len(srv.state["recorded_requests"]) == 0

        # (b) api-base with trailing LF -> exit 2 / INVALID_API_BASE
        srv.state["recorded_requests"].clear()
        res_api = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", srv.url + "\n",
            "--max-attempts", "1",
            "--interval-seconds", "0",
        )
        assert res_api.returncode == 2
        data_api = json.loads(res_api.stdout.decode("ascii"))
        assert data_api["status"] == "VERIFICATION_TOOL_UNABLE_TO_COMPLETE"
        assert data_api["reason"] == "INVALID_API_BASE"
        assert len(srv.state["recorded_requests"]) == 0

        # (c) repo with trailing LF -> exit 2 / INVALID_ARGUMENT
        srv.state["recorded_requests"].clear()
        res_repo = run_tool(
            "ci-status",
            "--repo", "hhai0519/HH.AI_v2\n",
            "--head-sha", head_sha,
            "--branch", branch,
            "--require-job", "verify",
            "--api-base", srv.url,
            "--max-attempts", "1",
            "--interval-seconds", "0",
        )
        assert res_repo.returncode == 2
        data_repo = json.loads(res_repo.stdout.decode("ascii"))
        assert data_repo["status"] == "VERIFICATION_TOOL_UNABLE_TO_COMPLETE"
        assert data_repo["reason"] == "INVALID_ARGUMENT"
        assert len(srv.state["recorded_requests"]) == 0

