"""Verification Primitives Tool (Pilot INC-A, B-69).

This module provides cross-platform read-only verification primitives designed
to produce identical results across Windows and Linux environments.

Exit code contract:
  0 = PASS (expect matched) or REPORT (no expect provided)
  1 = CANDIDATE_INVALID (tool completed normally, but candidate expect mismatched)
  2 = VERIFICATION_TOOL_UNABLE_TO_COMPLETE (tool unable to complete verification,
      e.g., file read error, invalid UTF-8, git failure, invalid arguments)

Crucial Safety Rule:
  When this tool reports VERIFICATION_TOOL_UNABLE_TO_COMPLETE (exit code 2),
  the executor MUST STOP and escalate for decision. Do NOT modify the tool on
  the fly and do NOT attempt alternative ad-hoc comparison methods.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def emit_json(payload: dict) -> None:
    """Emit a single line of sorted ASCII-only JSON to stdout."""
    line = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    sys.stdout.write(line + "\n")


def emit_unable(command: str, reason: str) -> None:
    """Emit UNABLE status JSON and exit with code 2."""
    emit_json({
        "command": command,
        "reason": reason,
        "status": "VERIFICATION_TOOL_UNABLE_TO_COMPLETE",
        "tool": "verification_primitives",
        "version": 1,
    })
    sys.exit(2)


def cmd_count(args: argparse.Namespace) -> None:
    command = "count"
    target_path = Path(args.target)
    needle_path = Path(args.needle_file)

    try:
        target_bytes = target_path.read_bytes()
    except Exception:
        emit_unable(command, "FILE_READ_ERROR")

    try:
        needle_bytes = needle_path.read_bytes()
    except Exception:
        emit_unable(command, "FILE_READ_ERROR")

    if needle_bytes.startswith(b"\xef\xbb\xbf"):
        emit_unable(command, "NEEDLE_HAS_BOM")

    try:
        target_text = target_bytes.decode("utf-8")
    except UnicodeDecodeError:
        emit_unable(command, "UTF8_DECODE_ERROR")

    try:
        needle_text = needle_bytes.decode("utf-8")
    except UnicodeDecodeError:
        emit_unable(command, "UTF8_DECODE_ERROR")

    # needle 只剝除檔尾恰好一個行尾（CRLF 或 LF）；剝除後為空 → UNABLE（EMPTY_NEEDLE）
    if needle_text.endswith("\r\n"):
        needle_text = needle_text[:-2]
    elif needle_text.endswith("\n"):
        needle_text = needle_text[:-1]

    if not needle_text:
        emit_unable(command, "EMPTY_NEEDLE")

    # 比對前 target 與 needle 皆僅將 CRLF 正規化為 LF；計數 = 非重疊出現次數
    target_normalized = target_text.replace("\r\n", "\n")
    needle_normalized = needle_text.replace("\r\n", "\n")

    match_count = target_normalized.count(needle_normalized)
    target_sha256 = hashlib.sha256(target_bytes).hexdigest()

    if args.expect is None:
        status = "REPORT"
        exit_code = 0
    else:
        if match_count == args.expect:
            status = "PASS"
            exit_code = 0
        else:
            status = "CANDIDATE_INVALID"
            exit_code = 1

    emit_json({
        "command": command,
        "count": match_count,
        "expect": args.expect,
        "status": status,
        "target_sha256": target_sha256,
        "tool": "verification_primitives",
        "version": 1,
    })
    sys.exit(exit_code)


def _is_64_hex(val: str) -> bool:
    return len(val) == 64 and all(c in "0123456789abcdefABCDEF" for c in val)


def cmd_sha256(args: argparse.Namespace) -> None:
    command = "sha256"
    file_path = Path(args.file)

    if args.expect_raw is not None and not _is_64_hex(args.expect_raw):
        emit_unable(command, "INVALID_EXPECT")
    if args.expect_lf is not None and not _is_64_hex(args.expect_lf):
        emit_unable(command, "INVALID_EXPECT")

    try:
        raw_bytes = file_path.read_bytes()
    except Exception:
        emit_unable(command, "FILE_READ_ERROR")

    sha256_raw = hashlib.sha256(raw_bytes).hexdigest()
    sha256_lf = hashlib.sha256(raw_bytes.replace(b"\r\n", b"\n")).hexdigest()

    if args.expect_raw is None and args.expect_lf is None:
        status = "REPORT"
        exit_code = 0
    else:
        match_raw = (args.expect_raw is None) or (args.expect_raw.lower() == sha256_raw)
        match_lf = (args.expect_lf is None) or (args.expect_lf.lower() == sha256_lf)
        if match_raw and match_lf:
            status = "PASS"
            exit_code = 0
        else:
            status = "CANDIDATE_INVALID"
            exit_code = 1

    emit_json({
        "command": command,
        "expect_lf": args.expect_lf.lower() if args.expect_lf else None,
        "expect_raw": args.expect_raw.lower() if args.expect_raw else None,
        "sha256_lf": sha256_lf,
        "sha256_raw": sha256_raw,
        "status": status,
        "tool": "verification_primitives",
        "version": 1,
    })
    sys.exit(exit_code)


def _is_40_lower_hex(val: str) -> bool:
    return len(val) == 40 and all(c in "0123456789abcdef" for c in val)


def cmd_git_diff_digest(args: argparse.Namespace) -> None:
    command = "git-diff-digest"
    repo_root = args.repo_root

    if not _is_40_lower_hex(args.base):
        emit_unable(command, "INVALID_BASE")

    if args.expect is not None and not _is_64_hex(args.expect):
        emit_unable(command, "INVALID_EXPECT")

    # Check commit existence
    cat_cmd = ["git", "-C", repo_root, "cat-file", "-e", f"{args.base}^{{commit}}"]
    try:
        cat_proc = subprocess.run(
            cat_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            shell=False,
        )
    except FileNotFoundError:
        emit_unable(command, "GIT_EXEC_ERROR")
    except subprocess.TimeoutExpired:
        emit_unable(command, "GIT_TIMEOUT")
    except Exception:
        emit_unable(command, "GIT_EXEC_ERROR")

    if cat_proc.returncode != 0:
        emit_unable(command, "BASE_NOT_FOUND")

    # Mode parameters
    if args.mode == "worktree":
        mode_args = [args.base]
    elif args.mode == "cached":
        mode_args = ["--cached", args.base]
    elif args.mode == "head":
        mode_args = [args.base, "HEAD"]
    else:
        emit_unable(command, "GIT_EXEC_ERROR")

    base_git_cmd = ["git", "-C", repo_root, "-c", "core.quotepath=false", "-c", "color.ui=never"]

    # 1. Diff raw bytes
    diff_cmd = base_git_cmd + [
        "diff",
        "--binary",
        "--full-index",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
    ] + mode_args

    try:
        diff_proc = subprocess.run(
            diff_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            shell=False,
        )
    except FileNotFoundError:
        emit_unable(command, "GIT_EXEC_ERROR")
    except subprocess.TimeoutExpired:
        emit_unable(command, "GIT_TIMEOUT")
    except Exception:
        emit_unable(command, "GIT_EXEC_ERROR")

    if diff_proc.returncode != 0:
        emit_unable(command, "GIT_NONZERO_EXIT")

    diff_sha256 = hashlib.sha256(diff_proc.stdout).hexdigest()

    # 2. Changed paths
    name_cmd = base_git_cmd + ["diff", "--name-only", "-z"] + mode_args
    try:
        name_proc = subprocess.run(
            name_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            shell=False,
        )
    except FileNotFoundError:
        emit_unable(command, "GIT_EXEC_ERROR")
    except subprocess.TimeoutExpired:
        emit_unable(command, "GIT_TIMEOUT")
    except Exception:
        emit_unable(command, "GIT_EXEC_ERROR")

    if name_proc.returncode != 0:
        emit_unable(command, "GIT_NONZERO_EXIT")

    raw_changed = name_proc.stdout.split(b"\x00")
    changed_paths = [p.decode("utf-8", errors="surrogateescape") for p in raw_changed if p]

    # 3. Untracked paths
    untracked_cmd = ["git", "-C", repo_root, "-c", "core.quotepath=false", "ls-files", "--others", "--exclude-standard", "-z"]
    try:
        untracked_proc = subprocess.run(
            untracked_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            shell=False,
        )
    except FileNotFoundError:
        emit_unable(command, "GIT_EXEC_ERROR")
    except subprocess.TimeoutExpired:
        emit_unable(command, "GIT_TIMEOUT")
    except Exception:
        emit_unable(command, "GIT_EXEC_ERROR")

    if untracked_proc.returncode != 0:
        emit_unable(command, "GIT_NONZERO_EXIT")

    raw_untracked = untracked_proc.stdout.split(b"\x00")
    untracked_paths = [p.decode("utf-8", errors="surrogateescape") for p in raw_untracked if p]

    # Comparison and status
    if args.expect is None:
        status = "REPORT"
        exit_code = 0
    else:
        if diff_sha256 == args.expect.lower():
            status = "PASS"
            exit_code = 0
        else:
            status = "CANDIDATE_INVALID"
            exit_code = 1

    payload = {
        "base": args.base,
        "changed_paths": changed_paths,
        "command": command,
        "diff_sha256": diff_sha256,
        "mode": args.mode,
        "status": status,
        "tool": "verification_primitives",
        "untracked_paths": untracked_paths,
        "version": 1,
    }
    if args.expect is not None:
        payload["expect"] = args.expect.lower()

    emit_json(payload)
    sys.exit(exit_code)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="verification_primitives",
        description="Cross-platform read-only verification primitives (B-69).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: count
    parser_count = subparsers.add_parser("count", help="Count needle occurrences in target file")
    parser_count.add_argument("--target", required=True, help="Target file path")
    parser_count.add_argument("--needle-file", required=True, help="Needle file path")
    parser_count.add_argument("--expect", type=int, default=None, help="Expected count")
    parser_count.set_defaults(func=cmd_count)

    # Subcommand: sha256
    parser_sha256 = subparsers.add_parser("sha256", help="Compute raw and LF sha256 digests")
    parser_sha256.add_argument("--file", required=True, help="File path")
    parser_sha256.add_argument("--expect-raw", default=None, help="Expected 64-hex SHA-256 for raw bytes")
    parser_sha256.add_argument("--expect-lf", default=None, help="Expected 64-hex SHA-256 for CRLF->LF bytes")
    parser_sha256.set_defaults(func=cmd_sha256)

    # Subcommand: git-diff-digest
    parser_diff = subparsers.add_parser("git-diff-digest", help="Digest git diff and changed/untracked paths")
    parser_diff.add_argument("--base", required=True, help="40-hex base commit OID")
    parser_diff.add_argument(
        "--mode",
        choices=["worktree", "cached", "head"],
        default="worktree",
        help="Diff mode (default: worktree)",
    )
    parser_diff.add_argument("--expect", default=None, help="Expected 64-hex SHA-256 for diff bytes")
    parser_diff.add_argument("--repo-root", default=".", help="Path to repo root (default: current directory)")
    parser_diff.set_defaults(func=cmd_git_diff_digest)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
