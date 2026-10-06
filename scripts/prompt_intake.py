#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/prompt_intake.py

Canonical prompt intake for Executor batches (B-107 canonical tooling).

Copies an auditor-delivered prompt file into .git/<task-id>-prompt.txt only after
mechanical qualification, replacing per-batch hand-written PowerShell checks.

Checks (fail-closed, no content echo):
1. task id is safe ASCII; expected SHA-256 is 64 hex characters.
2. source path is absolute and has no traversal segment.
3. every ancestor directory of the source and of the repository .git directory
   is a real directory (not a symlink, junction or other reparse point).
4. source exists, is a regular non-reparse file, and 0 < size <= 1 MiB.
5. SHA-256 of the bytes read equals the expected value.
6. target .git/<task-id>-prompt.txt does not exist; it is created exclusively
   from the same bytes that were hashed, then re-read and re-hashed.

Exit codes: 0 PASS; 2 USAGE; 3 SOURCE_MISSING; 4 SOURCE_INVALID;
5 SOURCE_HASH_MISMATCH; 6 TARGET_EXISTS; 7 PATH_NOT_SAFE; 8 COPY_VERIFY_FAILED.
The tool never deletes, overwrites or renames any file.
"""

import argparse
import hashlib
import os
import re
import stat
import sys

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from scripts.governance_preflight import (  # noqa: E402
    is_safe_task_id,
    check_raw_path_segments,
    get_canonical_git_dir,
)

MAX_PROMPT_BYTES = 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REPARSE_ATTR = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

EXIT_USAGE = 2
EXIT_SOURCE_MISSING = 3
EXIT_SOURCE_INVALID = 4
EXIT_SOURCE_HASH_MISMATCH = 5
EXIT_TARGET_EXISTS = 6
EXIT_PATH_NOT_SAFE = 7
EXIT_COPY_VERIFY_FAILED = 8


class IntakeError(Exception):
    def __init__(self, code: int, label: str):
        super().__init__(label)
        self.code = code
        self.label = label


def is_link_or_reparse(st_result, path: str) -> bool:
    if stat.S_ISLNK(st_result.st_mode) or os.path.islink(path):
        return True
    if getattr(st_result, "st_reparse_tag", 0) != 0:
        return True
    if getattr(st_result, "st_file_attributes", 0) & REPARSE_ATTR:
        return True
    return False


def ensure_safe_directory_chain(directory: str) -> None:
    """Every component from the filesystem root down to `directory` must be a real directory."""
    current = os.path.abspath(directory)
    chain = []
    while True:
        chain.append(current)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    for path in reversed(chain):
        try:
            st_result = os.lstat(path)
        except OSError:
            raise IntakeError(EXIT_PATH_NOT_SAFE, "PATH_NOT_SAFE")
        if is_link_or_reparse(st_result, path) or not stat.S_ISDIR(st_result.st_mode):
            raise IntakeError(EXIT_PATH_NOT_SAFE, "PATH_NOT_SAFE")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def intake(task_id: str, source: str, expected_sha256: str, repo_root_arg: str) -> str:
    if not is_safe_task_id(task_id):
        raise IntakeError(EXIT_USAGE, "USAGE_INVALID_TASK_ID")
    expected = (expected_sha256 or "").strip().lower()
    if not SHA256_RE.fullmatch(expected):
        raise IntakeError(EXIT_USAGE, "USAGE_INVALID_SHA256")
    if not source or not os.path.isabs(source):
        raise IntakeError(EXIT_USAGE, "USAGE_SOURCE_NOT_ABSOLUTE")
    ok_raw, _ = check_raw_path_segments(source)
    if not ok_raw:
        raise IntakeError(EXIT_USAGE, "USAGE_SOURCE_PATH_INVALID")

    source_abs = os.path.abspath(source)
    ensure_safe_directory_chain(os.path.dirname(source_abs))

    if not os.path.lexists(source_abs):
        raise IntakeError(EXIT_SOURCE_MISSING, "SOURCE_MISSING")
    try:
        st_source = os.lstat(source_abs)
    except OSError:
        raise IntakeError(EXIT_SOURCE_INVALID, "SOURCE_INVALID")
    if is_link_or_reparse(st_source, source_abs) or not stat.S_ISREG(st_source.st_mode):
        raise IntakeError(EXIT_SOURCE_INVALID, "SOURCE_INVALID")
    if st_source.st_size <= 0 or st_source.st_size > MAX_PROMPT_BYTES:
        raise IntakeError(EXIT_SOURCE_INVALID, "SOURCE_INVALID")

    try:
        with open(source_abs, "rb") as handle:
            data = handle.read(MAX_PROMPT_BYTES + 1)
    except OSError:
        raise IntakeError(EXIT_SOURCE_INVALID, "SOURCE_INVALID")
    if len(data) == 0 or len(data) > MAX_PROMPT_BYTES:
        raise IntakeError(EXIT_SOURCE_INVALID, "SOURCE_INVALID")
    if sha256_hex(data) != expected:
        raise IntakeError(EXIT_SOURCE_HASH_MISMATCH, "SOURCE_HASH_MISMATCH")

    repo_root_abs = os.path.abspath(repo_root_arg)
    ok_git, _, git_dir_abs = get_canonical_git_dir(repo_root_abs)
    if not ok_git:
        raise IntakeError(EXIT_PATH_NOT_SAFE, "PATH_NOT_SAFE")
    ensure_safe_directory_chain(git_dir_abs)

    target = os.path.join(git_dir_abs, f"{task_id}-prompt.txt")
    if os.path.lexists(target):
        raise IntakeError(EXIT_TARGET_EXISTS, "TARGET_EXISTS")
    try:
        with open(target, "xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        raise IntakeError(EXIT_TARGET_EXISTS, "TARGET_EXISTS")
    except OSError:
        raise IntakeError(EXIT_COPY_VERIFY_FAILED, "COPY_VERIFY_FAILED")

    try:
        st_target = os.lstat(target)
        if is_link_or_reparse(st_target, target) or not stat.S_ISREG(st_target.st_mode):
            raise IntakeError(EXIT_COPY_VERIFY_FAILED, "COPY_VERIFY_FAILED")
        with open(target, "rb") as handle:
            written = handle.read()
    except OSError:
        raise IntakeError(EXIT_COPY_VERIFY_FAILED, "COPY_VERIFY_FAILED")
    if sha256_hex(written) != expected:
        raise IntakeError(EXIT_COPY_VERIFY_FAILED, "COPY_VERIFY_FAILED")
    return f".git/{task_id}-prompt.txt"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Canonical prompt intake (B-107 canonical tooling).")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--source", required=True, help="Absolute path of the downloaded prompt file")
    parser.add_argument("--sha256", required=True, help="Expected SHA-256 (64 hex)")
    parser.add_argument("--repo-root", default=".")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE
    try:
        rel_target = intake(args.task_id, args.source, args.sha256, args.repo_root)
    except IntakeError as exc:
        print(f"S1 {exc.label}")
        return exc.code
    print(f"PROMPT_INTAKE PASS task={args.task_id} sha256={args.sha256.strip().lower()} target={rel_target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
