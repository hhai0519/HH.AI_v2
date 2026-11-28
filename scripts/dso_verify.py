#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TD-136b/TD-139/TD-144a: Deterministic one-command D-SO review verifier (scripts/dso_verify.py).

Read-only with respect to the caller repository; extracts D-SO evidence packs safely,
rebuilds dual isolated Base/Patched worktrees, verifies author files/patch/manifest/
prompt, scans added patch lines, checks explicit contract qualnames, runs fast
precheck and sibling/Base diff_ast_mutate.py (never self-verifying with candidate code),
and emits JSON Schema v1 with a platform-invariant whitelist canonical_sha256 plus
content_canonical_sha256. Pure Python 3.14 stdlib + bounded_process.py only.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bounded_process  # noqa: E402

SCHEMA_VERSION = 1
TOOL_NAME = "dso_verify.py"
TOOL_VERSION = "1.1.0"

EXIT_VERIFIED = 0
EXIT_BLOCKING = 1
EXIT_INCOMPLETE = 2

MAX_ZIP_FILES = 200
MAX_ZIP_SINGLE_BYTES = 10 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 50 * 1024 * 1024
MAX_WORKERS_HARD_CAP = 8

DEFAULT_STEP_TIMEOUTS: dict[str, float] = {
    "git_clone": 120.0,
    "patch_apply": 60.0,
    "fast_precheck": 300.0,
    "diff_ast_mutate_baseline": 180.0,
    "diff_ast_mutate_per_mutant": 180.0,
    "diff_ast_mutate_total": 3600.0,
}
DEFAULT_OVERALL_BUDGET_SEC = 4500.0
DEFAULT_MAX_MUTANTS = 120

_DEFAULT_MONOTONIC: Callable[[], float] = time.monotonic

_WINDOWS_RESERVED_STEMS: frozenset[str] = frozenset({
    "con", "prn", "aux", "nul",
    "conin$", "conout$",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
    "com\u00b9", "com\u00b2", "com\u00b3",
    "lpt\u00b9", "lpt\u00b2", "lpt\u00b3",
})

CONTRACT_QUALNAMES_BY_FILE: dict[str, tuple[str, ...]] = {
    "scripts/dso_verify.py": (
        "validate_archive_entry_name",
        "_dir_prefixes_for_casefold",
        "safe_extract_zip",
        "validate_contract_qualnames",
        "compute_canonical_sha256",
        "compute_content_canonical_sha256",
        "scan_added_lines",
    ),
    "scripts/diff_ast_mutate.py": (
        "_matches_qualname",
        "resolve_workers",
        "discover_changed_qualnames",
        "load_survived_from_file",
        "load_accept_file",
        "load_test_map",
        "compute_cache_key",
        "execute_mutation_run",
        "_build_report",
    ),
    "scripts/draft_precheck.py": (
        "validate_plan",
        "validate_author_targets",
        "lint_added_sha_labels",
        "execute_fast",
        "execute",
    ),
    "scripts/s1_registry.py": (
        "validate_reverse_verification",
        "validate_doc",
        "check_monotonic",
        "check",
    ),
    "scripts/taskboard_archive.py": (
        "check_records",
        "check_ledger",
        "records_apply",
        "check",
    ),
    "scripts/cap_count.py": (
        "count_d6",
        "count_cap2",
        "compute_all",
    ),
    "scripts/audit_packet.py": (
        "Packet.preissue_facts",
        "Packet.checks",
        "Packet.build",
    ),
    "scripts/delivery_pack.py": (
        "assemble",
        "verify_reply_blocks",
        "verify_reply",
    ),
    "scripts/reply_check.py": (
        "check_reply",
        "check_spec",
    ),
}

CANONICAL_INCLUDED_FIELDS: tuple[str, ...] = (
    "schema_version",
    "tool",
    "tool_version",
    "base_oid",
    "task_id",
    "overall_status",
    "exit_code",
    "skip_fast",
    "qualname_filter",
    "inputs",
    "author_manifest",
    "checks",
    "mutation",
)

TASK_ID_RE = re.compile(r"\bB\d+(?:-[A-Z0-9]+)+-\d{6}\b")
HEX_HASH_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)
ANSI_ESC_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
SHA256SUM_LINE_RE = re.compile(r"^([0-9a-f]{64})  (.+)$")


class DsoVerifyError(Exception):
    """Fail-closed verifier error mapped to exit code 2 (INCOMPLETE)."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _force_rmtree(path: Path) -> None:
    if not path.exists():
        return

    def _onexc(func: Callable[..., Any], p: str, _exc: BaseException) -> None:
        os.chmod(p, stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onexc=_onexc)


def _clean_git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run_git(repo: Path, args: list[str], *, timeout: float) -> bytes:
    res = bounded_process.run_bounded(
        ["git", "--no-optional-locks", "--no-replace-objects", "-C", str(repo), *args],
        str(repo),
        timeout,
        env=_clean_git_env(),
        merge_stderr=True,
    )
    if res.launch_error is not None or res.timed_out or res.returncode != 0:
        msg = res.launch_error or res.stdout.decode("utf-8", errors="replace").strip()
        raise DsoVerifyError("GIT_ERROR", f"git {' '.join(args)} failed: {msg}")
    return res.stdout


def _is_test_rel(rel: str) -> bool:
    p = rel.replace("\\", "/")
    name = p.rsplit("/", 1)[-1]
    return "/tests/" in f"/{p}" or name.startswith("test_") or name.endswith("_test.py")


def _is_safe_segment(seg: str) -> bool:
    if not seg or seg in (".", "..") or seg[-1] in (" ", "."):
        return False
    stem = seg.split(".", 1)[0].casefold()
    return seg.casefold() not in _WINDOWS_RESERVED_STEMS and stem not in _WINDOWS_RESERVED_STEMS


def validate_archive_entry_name(name: str, *, allow_dir_trailing_slash: bool = False) -> str | None:
    """Validate an archive member path; return normalized POSIX path or None if unsafe."""
    if not isinstance(name, str):
        return None
    if any(ord(ch) < 32 for ch in name) or "\\" in name or ":" in name:
        return None
    trimmed = name[:-1] if (allow_dir_trailing_slash and name.endswith("/")) else name
    return trimmed if all(_is_safe_segment(seg) for seg in trimmed.split("/")) else None


def _dir_prefixes_for_casefold(cf: str) -> list[str]:
    """Return bounded non-empty ancestor directory prefixes for normalized POSIX casefolded path (TD-139)."""
    parts = cf.split("/")
    return ["/".join(parts[:depth]) for depth in range(1, len(parts))]


def _check_member_mode_and_target(info: zipfile.ZipInfo, norm: str, dest_root: Path) -> Path:
    is_dir = info.is_dir()
    mode = (info.external_attr >> 16) & 0xFFFF
    if stat.S_IFMT(mode) != 0:
        if stat.S_ISLNK(mode):
            raise DsoVerifyError("UNSAFE_ARCHIVE", f"symlink not allowed: {norm!r}")
        if (is_dir and not stat.S_ISDIR(mode)) or ((not is_dir) and not stat.S_ISREG(mode)):
            raise DsoVerifyError("UNSAFE_ARCHIVE", f"unsafe entry mode: {norm!r}")
    target = (dest_root / norm).resolve()
    if not target.is_relative_to(dest_root):
        raise DsoVerifyError("UNSAFE_ARCHIVE", f"path escapes destination: {norm!r}")
    return target


def _stream_member_bytes(
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    norm: str,
    target: Path,
    *,
    prior_total: int,
    max_single_bytes: int,
    max_total_bytes: int,
) -> int:
    if info.file_size > max_single_bytes:
        raise DsoVerifyError("UNSAFE_ARCHIVE", f"declared size exceeds limit: {norm!r}")
    written = 0
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info, mode="r") as src, target.open("wb") as dst:
            while chunk := src.read(65536):
                written += len(chunk)
                if written > max_single_bytes or (prior_total + written) > max_total_bytes:
                    raise DsoVerifyError("UNSAFE_ARCHIVE", f"decompressed size exceeds limit at {norm!r}")
                dst.write(chunk)
    except DsoVerifyError:
        raise
    except (zipfile.BadZipFile, RuntimeError, OSError, EOFError) as exc:
        raise DsoVerifyError("UNSAFE_ARCHIVE", f"corrupt member {norm!r}: {exc}") from None
    return written


def safe_extract_zip(
    zip_path: Path,
    dest_dir: Path,
    *,
    max_files: int = MAX_ZIP_FILES,
    max_single_bytes: int = MAX_ZIP_SINGLE_BYTES,
    max_total_bytes: int = MAX_ZIP_TOTAL_BYTES,
) -> list[str]:
    """Safely extract zip_path into dest_dir; fail-closed UNSAFE_ARCHIVE on any anomaly."""
    dest_root = dest_dir.resolve()
    try:
        dest_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DsoVerifyError("UNSAFE_ARCHIVE", f"cannot create dest dir: {exc}") from None

    extracted: list[str] = []
    seen_casefold: set[str] = set()
    file_cfs: set[str] = set()
    dir_prefix_cfs: set[str] = set()
    plan: list[tuple[zipfile.ZipInfo, str, bool, Path]] = []
    total_written = 0

    try:
        zf_ctx = zipfile.ZipFile(zip_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise DsoVerifyError("UNSAFE_ARCHIVE", f"invalid zip archive: {exc}") from None

    with zf_ctx as zf:
        infos = zf.infolist()
        if len(infos) > max_files:
            raise DsoVerifyError("UNSAFE_ARCHIVE", f"archive entry count {len(infos)} > {max_files}")
        for info in infos:
            is_dir = info.is_dir()
            norm = validate_archive_entry_name(info.filename, allow_dir_trailing_slash=is_dir)
            if norm is None:
                raise DsoVerifyError("UNSAFE_ARCHIVE", f"unsafe entry name: {info.filename!r}")
            cf = norm.casefold()
            if cf in seen_casefold:
                raise DsoVerifyError("UNSAFE_ARCHIVE", f"duplicate or case-folding entry collision: {norm!r}")
            seen_casefold.add(cf)
            if not is_dir:
                file_cfs.add(cf)
            dir_prefix_cfs.update(_dir_prefixes_for_casefold(cf))
            target = _check_member_mode_and_target(info, norm, dest_root)
            plan.append((info, norm, is_dir, target))

        if file_cfs & dir_prefix_cfs:
            raise DsoVerifyError("UNSAFE_ARCHIVE", "file/directory collision")

        for info, norm, is_dir, target in plan:
            if is_dir:
                try:
                    target.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    raise DsoVerifyError("UNSAFE_ARCHIVE", f"cannot create dir {norm!r}: {exc}") from None
            else:
                total_written += _stream_member_bytes(
                    zf, info, norm, target,
                    prior_total=total_written,
                    max_single_bytes=max_single_bytes,
                    max_total_bytes=max_total_bytes,
                )
                extracted.append(norm)
    return sorted(extracted)


def _extract_ast_qualnames(source_bytes: bytes, rel_path: str) -> set[str]:
    try:
        tree = ast.parse(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise DsoVerifyError("TARGET_PARSE_ERROR", f"failed to parse {rel_path}: {exc}") from None

    found: set[str] = set()

    def _walk(node: ast.AST, prefix: str = "") -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qn = f"{prefix}.{child.name}" if prefix else child.name
                found.add(qn)
            elif isinstance(child, ast.ClassDef):
                qn = f"{prefix}.{child.name}" if prefix else child.name
                _walk(child, qn)

    _walk(tree)
    return found


def validate_contract_qualnames(
    repo_root: Path,
    changed_paths: list[str],
    contract_map: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, list[str]]:
    """Verify every listed contract qualname exists in the file's AST; fail-closed CONTRACT_QUALNAME_STALE."""
    cmap = CONTRACT_QUALNAMES_BY_FILE if contract_map is None else contract_map
    verified: dict[str, list[str]] = {}
    for rel in sorted(set(changed_paths)):
        norm = rel.replace("\\", "/")
        expected = cmap.get(norm)
        if not expected:
            continue
        fpath = repo_root / norm
        if not fpath.is_file():
            raise DsoVerifyError("CONTRACT_QUALNAME_STALE", f"contract file missing: {norm}")
        present = _extract_ast_qualnames(fpath.read_bytes(), norm)
        missing = sorted(q for q in expected if q not in present)
        if missing:
            raise DsoVerifyError(
                "CONTRACT_QUALNAME_STALE",
                f"stale contract qualnames in {norm}: {', '.join(missing)}",
            )
        verified[norm] = list(expected)
    return verified


def _scan_added_line_item(cur_file: str, content: str, violations: list[str]) -> None:
    if "\ufeff" in content:
        violations.append(f"{cur_file}: added line contains UTF-8 BOM")
    if ANSI_ESC_RE.search(content):
        violations.append(f"{cur_file}: added line contains ANSI escape sequence")
    if cur_file.startswith("docs/"):
        if "<!--" in content:
            violations.append(f"{cur_file}: added docs line contains '<!--'")
        if "file:///" in content.lower():
            violations.append(f"{cur_file}: added docs line contains 'file:///'")
    if cur_file == "docs/TASKBOARD.md" and HEX_HASH_RE.search(content):
        if content.startswith("**ACTIVE_MACRO_AUDITOR**：") or content.startswith("**最後更新**："):
            violations.append(f"docs/TASKBOARD.md: CHECK 8 hash in metadata line: {content[:80]}")


def _check_archived_records_fidelity(
    added_by_file: dict[str, list[str]],
    base_tb_set: set[str],
    patched_tb_set: set[str],
    violations: list[str],
) -> dict[str, int]:
    record_checks: dict[str, int] = {}
    for rel, lines in added_by_file.items():
        if not (rel.startswith("docs/archive/TASKBOARD-RECORDS-") and rel.endswith(".md")):
            continue
        rec_lines = [ln for ln in lines if ln.startswith("**B-") or ln.startswith("- **B-")]
        if not rec_lines:
            in_box = False
            for ln in lines:
                if ln.startswith("````text"):
                    in_box = True
                elif ln.startswith("````") and in_box:
                    in_box = False
                elif in_box and ln.strip():
                    rec_lines.append(ln)
        for rec_ln in rec_lines:
            if rec_ln not in base_tb_set:
                violations.append(f"{rel}: archived record line not found verbatim in Base TASKBOARD.md")
            elif rec_ln in patched_tb_set:
                violations.append(f"{rel}: archived record line still present in Patched TASKBOARD.md")
        record_checks[rel] = len(rec_lines)
    return record_checks


def scan_added_lines(
    patch_bytes: bytes,
    *,
    work_base: Path,
    work_patched: Path,
    current_task_id: str,
) -> tuple[bool, list[str], dict[str, Any]]:
    """Scan added lines in author.patch for encoding/hygiene/marker/TASKBOARD-RECORDS fidelity."""
    violations: list[str] = []
    if b"\r\n" in patch_bytes or b"\x00" in patch_bytes:
        violations.append("author.patch contains CR or NUL bytes")
    try:
        patch_text = patch_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return False, [f"author.patch invalid UTF-8: {exc}"], {}

    pending_file: str | None = None
    hunk_file: str | None = None
    added_by_file: dict[str, list[str]] = {}
    mentioned_task_ids: set[str] = set()

    for line in patch_text.splitlines():
        if line.startswith("+++ "):
            tok = line[4:].strip()
            pending_file = tok[2:] if tok.startswith("b/") else (None if tok == "/dev/null" else tok)
            hunk_file = None
        elif line.startswith("@@ "):
            hunk_file = pending_file
        elif hunk_file is not None and line.startswith("+"):
            content = line[1:]
            added_by_file.setdefault(hunk_file, []).append(content)
            mentioned_task_ids.update(tid for tid in TASK_ID_RE.findall(content) if tid != current_task_id)
            _scan_added_line_item(hunk_file, content, violations)

    base_tb_set = set((work_base / "docs/TASKBOARD.md").read_bytes().decode("utf-8").splitlines())
    patched_tb_set = set((work_patched / "docs/TASKBOARD.md").read_bytes().decode("utf-8").splitlines())
    record_checks = _check_archived_records_fidelity(added_by_file, base_tb_set, patched_tb_set, violations)
    details = {
        "added_files": sorted(added_by_file),
        "old_task_ids_mentioned": sorted(mentioned_task_ids),
        "archived_records_checked": record_checks,
        "violations": violations,
    }
    return (len(violations) == 0), violations, details


def compute_canonical_payload(report: dict[str, Any]) -> dict[str, Any]:
    """Build strict whitelist payload excluding elapsed_sec, timestamps, temp paths, and OS counts."""
    raw_inputs = report.get("inputs") or {}
    canon_inputs = {
        k: raw_inputs[k]
        for k in sorted(raw_inputs)
        if k.endswith("_sha256")
    }
    canon_authors = sorted(
        (
            {
                "path": str(item["path"]).replace("\\", "/"),
                "sha256": item["sha256"],
                "match": bool(item["match"]),
            }
            for item in (report.get("author_manifest") or [])
        ),
        key=lambda x: x["path"],
    )
    canon_checks = [
        {
            "name": chk["name"],
            "status": chk["status"],
            "reason_code": chk["reason_code"],
        }
        for chk in (report.get("checks") or [])
    ]
    mut = report.get("mutation")
    if mut is None:
        canon_mut: dict[str, Any] | None = None
    else:
        msum = mut.get("summary") or {}
        canon_mut = {
            "summary": {
                k: msum.get(k)
                for k in (
                    "total",
                    "caught",
                    "caught_timeout",
                    "survived",
                    "accepted",
                    "invalid",
                    "exit_code",
                    "verdict",
                    "reason",
                )
            },
            "mutants": sorted(
                ({"id": m["id"], "status": m["status"]} for m in (mut.get("mutants") or [])),
                key=lambda x: x["id"],
            ),
            "stale_accepted": sorted(mut.get("stale_accepted") or []),
            "unnecessary_accepted": sorted(mut.get("unnecessary_accepted") or []),
            "out_of_scope_accepted": sorted(mut.get("out_of_scope_accepted") or []),
        }
    return {
        "schema_version": report["schema_version"],
        "tool": report["tool"],
        "tool_version": report["tool_version"],
        "base_oid": report["base_oid"],
        "task_id": report["task_id"],
        "overall_status": report["overall_status"],
        "exit_code": report["exit_code"],
        "skip_fast": bool(report["skip_fast"]),
        "qualname_filter": sorted(report.get("qualname_filter") or []),
        "inputs": canon_inputs,
        "author_manifest": canon_authors,
        "checks": canon_checks,
        "mutation": canon_mut,
    }


def compute_canonical_sha256(report: dict[str, Any]) -> str:
    """Compute SHA-256 over the strict canonical whitelist payload."""
    payload = compute_canonical_payload(report)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(raw)


def compute_content_canonical_sha256(report: dict[str, Any]) -> str:
    """Compute packaging-invariant SHA-256 (same whitelist excluding inputs['pack_sha256'], 4a)."""
    payload = compute_canonical_payload(report)
    inputs = dict(payload.get("inputs") or {})
    inputs.pop("pack_sha256", None)
    payload["inputs"] = inputs
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(raw)


def _resolve_workers_arg(raw: str | int) -> str:
    if isinstance(raw, bool):
        raise DsoVerifyError("INVALID_ARGS", "--mutate-workers cannot be bool")
    if isinstance(raw, int):
        if raw < 1 or raw > MAX_WORKERS_HARD_CAP:
            raise DsoVerifyError("INVALID_ARGS", f"--mutate-workers must be in 1..{MAX_WORKERS_HARD_CAP}")
        return str(raw)
    if not isinstance(raw, str):
        raise DsoVerifyError("INVALID_ARGS", "--mutate-workers must be int or str")
    txt = raw.strip()
    if txt.lower() == "auto":
        return "auto"
    try:
        val = int(txt)
    except ValueError:
        raise DsoVerifyError("INVALID_ARGS", f"invalid --mutate-workers: {raw!r}") from None
    if val < 1 or val > MAX_WORKERS_HARD_CAP:
        raise DsoVerifyError("INVALID_ARGS", f"--mutate-workers must be in 1..{MAX_WORKERS_HARD_CAP}")
    return str(val)


def _validate_mutate_cache_dir(cache_dir: Path, repo: Path, pack_path: Path) -> Path:
    c = cache_dir.resolve()
    r = repo.resolve()
    p = pack_path.resolve()
    if c.is_relative_to(r):
        raise DsoVerifyError("INVALID_ARGS", f"--mutate-cache-dir must be outside --repo: {c}")
    if pack_path.is_dir() and c.is_relative_to(p):
        raise DsoVerifyError("INVALID_ARGS", f"--mutate-cache-dir must be outside --pack dir: {c}")
    if c.exists() and not c.is_dir():
        raise DsoVerifyError("INVALID_ARGS", f"--mutate-cache-dir exists and is not a directory: {c}")
    return c


def _validate_budgets(timeouts: dict[str, float], overall_budget: float) -> None:
    if overall_budget <= 0 or any(v <= 0 for v in timeouts.values()):
        raise DsoVerifyError("INVALID_TIMEOUT_BUDGET", "all timeouts and overall_budget must be > 0")
    seq_sum = (
        timeouts["git_clone"]
        + timeouts["patch_apply"]
        + timeouts["fast_precheck"]
        + timeouts["diff_ast_mutate_total"]
    )
    if overall_budget <= seq_sum:
        raise DsoVerifyError(
            "INVALID_TIMEOUT_BUDGET",
            f"overall_budget ({overall_budget}s) must exceed sum of sequential steps ({seq_sum}s)",
        )


def _load_json_bytes(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DsoVerifyError("PACK_INVALID", f"cannot load {label}: {exc}") from None


def _derive_mutate_test_cmd(defn: dict[str, Any], work_patched: Path) -> str:
    focused = defn.get("focused")
    if isinstance(focused, dict) and isinstance(focused.get("pytest_args"), list):
        tests = [
            arg.replace("\\", "/")
            for arg in focused["pytest_args"]
            if isinstance(arg, str) and arg.endswith(".py") and (work_patched / arg).is_file()
        ]
        if tests:
            return "{python} -m pytest -p no:cacheprovider -q -x " + " ".join(tests)
    raise DsoVerifyError("TEST_CMD_MISSING", "no --mutate-test-cmd given and no focused .py tests in definition.json")


def _select_mutation_qualnames(
    changed_non_test_py: list[str],
    explicit_qualnames: list[str] | None,
) -> list[str]:
    if explicit_qualnames:
        cleaned: list[str] = []
        for q in explicit_qualnames:
            if not isinstance(q, str) or not q.strip():
                raise DsoVerifyError("INVALID_ARGS", "--qualname must be non-empty")
            cleaned.append(q.strip())
        return cleaned
    if "scripts/diff_ast_mutate.py" in changed_non_test_py:
        return list(CONTRACT_QUALNAMES_BY_FILE["scripts/diff_ast_mutate.py"])
    return []


def _make_check(name: str, status: str, reason_code: str, elapsed_sec: float, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "reason_code": reason_code,
        "elapsed_sec": round(elapsed_sec, 3),
        "details": details or {},
    }


def _finalize_status(checks: list[dict[str, Any]], skip_fast: bool) -> tuple[int, str]:
    statuses = {c["status"] for c in checks}
    if "FAIL" in statuses:
        return EXIT_BLOCKING, "BLOCKING"
    if "ERROR" in statuses or "SKIPPED" in statuses or skip_fast:
        return EXIT_INCOMPLETE, "INCOMPLETE"
    return EXIT_VERIFIED, "VERIFIED"


def _copy_pack_dir(src_dir: Path, dst_dir: Path) -> list[str]:
    dst_root = dst_dir.resolve()
    dst_root.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    seen_cf: set[str] = set()
    for p in sorted(src_dir.rglob("*")):
        rel = p.relative_to(src_dir).as_posix()
        norm = validate_archive_entry_name(rel, allow_dir_trailing_slash=p.is_dir())
        if norm is None:
            raise DsoVerifyError("UNSAFE_ARCHIVE", f"unsafe pack dir entry: {rel!r}")
        if norm.casefold() in seen_cf:
            raise DsoVerifyError("UNSAFE_ARCHIVE", f"case-fold collision in pack dir: {norm!r}")
        seen_cf.add(norm.casefold())
        if p.is_symlink():
            raise DsoVerifyError("UNSAFE_ARCHIVE", f"symlink in pack dir: {norm!r}")
        if p.is_file():
            dst = dst_root / norm
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
            files.append(norm)
    return sorted(files)


def _check_pack_integrity(
    pack_dir: Path,
    extracted_files: list[str],
) -> tuple[bool, str, dict[str, Any], dict[str, str]]:
    if any("__pycache__" in f or f.endswith(".pyc") for f in extracted_files):
        return False, "BYTECODE_IN_PACK", {"files": [f for f in extracted_files if "__pycache__" in f or f.endswith(".pyc")]}, {}

    sums_path = pack_dir / "SHA256SUMS.txt"
    if not sums_path.is_file():
        return False, "SHA256SUMS_MISSING", {}, {}
    sums_map: dict[str, str] = {}
    for ln in sums_path.read_bytes().decode("utf-8").splitlines():
        m = SHA256SUM_LINE_RE.match(ln)
        if not m:
            return False, "SHA256SUMS_INVALID", {"bad_line": ln}, {}
        digest, rel = m.group(1), m.group(2)
        norm = validate_archive_entry_name(rel)
        if norm is None or norm in sums_map:
            return False, "SHA256SUMS_INVALID", {"bad_path": rel}, {}
        sums_map[norm] = digest

    expected_set = {f for f in extracted_files if f != "SHA256SUMS.txt"}
    if set(sums_map) != expected_set:
        return False, "SHA256SUMS_SET_MISMATCH", {
            "missing": sorted(expected_set - set(sums_map)),
            "extra": sorted(set(sums_map) - expected_set),
        }, {}

    actual_shas: dict[str, str] = {}
    for rel, want_sha in sums_map.items():
        got = _sha256_bytes((pack_dir / rel).read_bytes())
        if got != want_sha:
            return False, "SHA256_MISMATCH", {"path": rel, "expected": want_sha, "actual": got}, {}
        actual_shas[rel] = got

    req_meta = ("authors.json", "author.patch", "plan.json", "definition.json")
    missing_meta = [m for m in req_meta if not (pack_dir / m).is_file()]
    if missing_meta:
        return False, "PACK_METADATA_MISSING", {"missing": missing_meta}, actual_shas

    authors_doc = _load_json_bytes(pack_dir / "authors.json", "authors.json")
    plan_doc = _load_json_bytes(pack_dir / "plan.json", "plan.json")
    defn_doc = _load_json_bytes(pack_dir / "definition.json", "definition.json")
    task_id = str(plan_doc.get("task_id") or "")
    base_oid = str(plan_doc.get("base_oid") or "")
    if (
        not task_id
        or not base_oid
        or authors_doc.get("task_id") != task_id
        or authors_doc.get("base_oid") != base_oid
        or defn_doc.get("task_id") != task_id
        or defn_doc.get("base_oid") != base_oid
    ):
        return False, "METADATA_CONSISTENCY_MISMATCH", {"task_id": task_id, "base_oid": base_oid}, actual_shas

    prompt_path = pack_dir / f"{task_id}-prompt.txt"
    if not prompt_path.is_file():
        return False, "PROMPT_FILE_MISSING", {"expected": f"{task_id}-prompt.txt"}, actual_shas

    manifest_path = pack_dir / "EVIDENCE_MANIFEST.json"
    missing_elapsed: list[str] = []
    if manifest_path.is_file():
        em = _load_json_bytes(manifest_path, "EVIDENCE_MANIFEST.json")
        if em.get("task_id") != task_id or em.get("base_oid") != base_oid:
            return False, "MANIFEST_MISMATCH", {"task_id": em.get("task_id")}, actual_shas
        for rel, entry in (em.get("files") or {}).items():
            if rel not in actual_shas or actual_shas[rel] != entry.get("sha256"):
                return False, "MANIFEST_FILE_MISMATCH", {"path": rel}, actual_shas
        for run_entry in (em.get("runs") or []):
            if "elapsed_sec" not in run_entry:
                missing_elapsed.append(str(run_entry.get("name")))

    return True, "OK", {"task_id": task_id, "base_oid": base_oid, "missing_elapsed_runs": missing_elapsed}, actual_shas


def verify_pack(
    *,
    repo: Path,
    pack_path: Path,
    work_parent: Path | None = None,
    skip_fast: bool = False,
    qualnames: list[str] | None = None,
    mutate_test_cmd: str | None = None,
    accept_path: Path | None = None,
    test_map_path: Path | None = None,
    max_mutants: int = DEFAULT_MAX_MUTANTS,
    step_timeouts: dict[str, float] | None = None,
    overall_budget: float = DEFAULT_OVERALL_BUDGET_SEC,
    contract_map: dict[str, tuple[str, ...]] | None = None,
    monotonic_fn: Callable[[], float] | None = None,
    mutate_workers: str | int = "1",
    mutate_cache_dir: Path | None = None,
) -> tuple[int, dict[str, Any]]:
    """Run deterministic D-SO verification on a D-SO PACK.zip or unpacked directory."""
    clock = monotonic_fn if monotonic_fn is not None else _DEFAULT_MONOTONIC
    timeouts = dict(DEFAULT_STEP_TIMEOUTS)
    if step_timeouts:
        timeouts.update(step_timeouts)

    checks: list[dict[str, Any]] = []
    inputs: dict[str, str] = {}
    author_manifest: list[dict[str, Any]] = []
    mutation_block: dict[str, Any] | None = None
    task_id = ""
    base_oid = ""
    q_filters: list[str] = []
    pack_mode = "unknown"
    run_start = clock()

    def _finish(code: int | None = None, overall: str | None = None) -> tuple[int, dict[str, Any]]:
        c_code, c_status = _finalize_status(checks, skip_fast) if code is None else (code, str(overall))
        report: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "tool": TOOL_NAME,
            "tool_version": TOOL_VERSION,
            "tool_sha256": _sha256_bytes(Path(__file__).read_bytes()),
            "pack_mode": pack_mode,
            "base_oid": base_oid,
            "task_id": task_id,
            "overall_status": c_status,
            "exit_code": c_code,
            "skip_fast": bool(skip_fast),
            "qualname_filter": sorted(q_filters),
            "inputs": dict(sorted(inputs.items())),
            "author_manifest": author_manifest,
            "checks": checks,
            "mutation": mutation_block,
            "timeout_budgets": {"steps": timeouts, "overall_budget_sec": overall_budget},
            "evidence_manifest": {
                "total_elapsed_sec": round(max(0.0, clock() - run_start), 3),
                "runs": [
                    {
                        "name": c["name"],
                        "status": c["status"],
                        "reason_code": c["reason_code"],
                        "elapsed_sec": c["elapsed_sec"],
                    }
                    for c in checks
                ],
            },
            "canonical_included_fields": list(CANONICAL_INCLUDED_FIELDS),
        }
        report["canonical_sha256"] = compute_canonical_sha256(report)
        report["content_canonical_sha256"] = compute_content_canonical_sha256(report)
        return c_code, report

    try:
        _validate_budgets(timeouts, overall_budget)
        if max_mutants < 0:
            raise DsoVerifyError("INVALID_ARGS", "--max-mutants must be >= 0")
        workers_arg = _resolve_workers_arg(mutate_workers)
        resolved_cache = (
            _validate_mutate_cache_dir(mutate_cache_dir, repo, pack_path)
            if mutate_cache_dir is not None
            else None
        )
        if qualnames:
            for q in qualnames:
                if not isinstance(q, str) or not q.strip():
                    raise DsoVerifyError("INVALID_ARGS", "--qualname must be non-empty")
            q_filters = [q.strip() for q in qualnames]
    except DsoVerifyError as exc:
        checks.append(_make_check("precheck_args", "ERROR", exc.reason_code, clock() - run_start, {"detail": exc.message}))
        return _finish(EXIT_INCOMPLETE, "INCOMPLETE")

    wp = (work_parent or Path(tempfile.gettempdir())).resolve()
    wp.mkdir(parents=True, exist_ok=True)
    iso_root = Path(tempfile.mkdtemp(prefix="hhai-dso-verify-", dir=str(wp)))

    def _remaining() -> float:
        rem = overall_budget - (clock() - run_start)
        if rem <= 0:
            raise DsoVerifyError("OVERALL_BUDGET_EXCEEDED", "overall_budget elapsed before next step")
        return rem

    try:
        # 1. Safe Archive Extraction
        t0 = clock()
        pack_dir = iso_root / "pack"
        if pack_path.is_dir():
            pack_mode = "dir"
            extracted_files = _copy_pack_dir(pack_path, pack_dir)
        elif pack_path.is_file():
            pack_mode = "zip"
            inputs["pack_sha256"] = _sha256_bytes(pack_path.read_bytes())
            extracted_files = safe_extract_zip(pack_path, pack_dir)
        else:
            raise DsoVerifyError("UNSAFE_ARCHIVE", f"pack path missing: {pack_path.name}")
        checks.append(_make_check("safe_archive", "PASS", "OK", clock() - t0, {"file_count": len(extracted_files), "pack_mode": pack_mode}))

        # 2. Pack Integrity
        t0 = clock()
        ok_pi, pi_reason, pi_det, file_shas = _check_pack_integrity(pack_dir, extracted_files)
        if not ok_pi:
            checks.append(_make_check("pack_integrity", "FAIL", pi_reason, clock() - t0, pi_det))
            return _finish()
        task_id = pi_det["task_id"]
        base_oid = pi_det["base_oid"]
        inputs["author_patch_sha256"] = file_shas["author.patch"]
        inputs["plan_sha256"] = file_shas["plan.json"]
        inputs["definition_sha256"] = file_shas["definition.json"]
        inputs["prompt_sha256"] = file_shas[f"{task_id}-prompt.txt"]
        inputs["authors_json_sha256"] = file_shas["authors.json"]
        checks.append(_make_check("pack_integrity", "PASS", "OK", clock() - t0, pi_det))

        # 3. Repo Base Check & Dual Isolated Workdirs
        t0 = clock()
        _remaining()
        resolved_base = _run_git(repo, ["rev-parse", f"{base_oid}^{{commit}}"], timeout=min(timeouts["git_clone"], _remaining())).decode("utf-8").strip()
        if resolved_base != base_oid:
            raise DsoVerifyError("GIT_ERROR", f"base_oid mismatch: {resolved_base} != {base_oid}")
        work_base = iso_root / "work_base"
        work_patched = iso_root / "work_patched"
        git_env = _clean_git_env()
        for clone_dir in (work_base, work_patched):
            cl_res = bounded_process.run_bounded(
                [
                    "git", "--no-optional-locks", "--no-replace-objects",
                    "clone", "-q", "-c", "core.autocrlf=false", "--no-local", "--template=",
                    str(repo), str(clone_dir),
                ],
                str(iso_root),
                min(timeouts["git_clone"], _remaining()),
                env=git_env,
                merge_stderr=True,
            )
            if cl_res.launch_error or cl_res.timed_out or cl_res.returncode != 0:
                raise DsoVerifyError("GIT_ERROR", f"clone to {clone_dir.name} failed")
            _run_git(clone_dir, ["checkout", "-q", base_oid], timeout=min(timeouts["git_clone"], _remaining()))
            _run_git(clone_dir, ["config", "core.autocrlf", "false"], timeout=30.0)
        checks.append(_make_check("repo_base_check", "PASS", "OK", clock() - t0, {"base_oid": base_oid}))

        # 4. Patch Apply & Author File Verification
        t0 = clock()
        _remaining()
        patch_file = pack_dir / "author.patch"
        patch_bytes = patch_file.read_bytes()
        for subcmd in (["apply", "--check", "--whitespace=error", str(patch_file)], ["apply", "--whitespace=error", str(patch_file)]):
            ap_res = bounded_process.run_bounded(
                ["git", "--no-optional-locks", "-C", str(work_patched), *subcmd],
                str(work_patched),
                min(timeouts["patch_apply"], _remaining()),
                env=git_env,
                merge_stderr=True,
            )
            if ap_res.launch_error or ap_res.timed_out or ap_res.returncode != 0:
                checks.append(_make_check(
                    "patch_and_authors",
                    "FAIL",
                    "PATCH_APPLY_FAILED",
                    clock() - t0,
                    {"detail": ap_res.stdout.decode("utf-8", errors="replace")[:500]},
                ))
                return _finish()

        authors_doc = _load_json_bytes(pack_dir / "authors.json", "authors.json")
        declared_entries = {str(a["path"]).replace("\\", "/"): str(a["sha256"]) for a in authors_doc["authors"]}
        diff_out = _run_git(work_patched, ["diff", "--name-only", "-z", base_oid], timeout=30.0).split(b"\x00")
        unt_out = _run_git(work_patched, ["ls-files", "--others", "--exclude-standard", "-z"], timeout=30.0).split(b"\x00")
        actual_changed = sorted({b.decode("utf-8").replace("\\", "/") for b in (*diff_out, *unt_out) if b})

        scope_mismatch = actual_changed != sorted(declared_entries)
        author_mismatch = False
        for rel in sorted(declared_entries):
            want_sha = declared_entries[rel]
            pkg_author = pack_dir / "authors" / rel
            pat_author = work_patched / rel
            got_pkg = _sha256_bytes(pkg_author.read_bytes()) if pkg_author.is_file() else ""
            got_pat = _sha256_bytes(pat_author.read_bytes()) if pat_author.is_file() else ""
            is_match = bool(got_pkg and got_pat and got_pkg == want_sha and got_pat == want_sha)
            if not is_match:
                author_mismatch = True
            author_manifest.append({"path": rel, "sha256": want_sha, "match": is_match})

        if scope_mismatch or author_mismatch:
            checks.append(_make_check(
                "patch_and_authors",
                "FAIL",
                "AUTHOR_SCOPE_MISMATCH" if scope_mismatch else "AUTHOR_SHA_MISMATCH",
                clock() - t0,
                {"declared_count": len(declared_entries), "actual_count": len(actual_changed)},
            ))
            return _finish()
        checks.append(_make_check("patch_and_authors", "PASS", "OK", clock() - t0, {"author_count": len(author_manifest)}))

        # 5. Prompt Builder Check (against clean work_base)
        t0 = clock()
        _remaining()
        prompt_file = pack_dir / f"{task_id}-prompt.txt"
        pb_res = bounded_process.run_bounded(
            [sys.executable, str(work_base / "scripts/prompt_builder.py"), "check", "--prompt", str(prompt_file), "--repo", str(work_base)],
            str(work_base),
            min(timeouts["fast_precheck"], _remaining()),
            env=git_env,
            merge_stderr=True,
        )
        if pb_res.launch_error or pb_res.timed_out or pb_res.returncode != 0:
            checks.append(_make_check("prompt_check", "FAIL", "PROMPT_CHECK_FAILED", clock() - t0, {"rc": pb_res.returncode}))
            return _finish()
        checks.append(_make_check("prompt_check", "PASS", "OK", clock() - t0, {}))

        # 6. Added-Lines Scan (S2)
        t0 = clock()
        scan_ok, scan_viol, scan_det = scan_added_lines(
            patch_bytes, work_base=work_base, work_patched=work_patched, current_task_id=task_id
        )
        if not scan_ok:
            checks.append(_make_check("added_lines_scan", "FAIL", "ADDED_LINES_VIOLATION", clock() - t0, scan_det))
            return _finish()
        checks.append(_make_check("added_lines_scan", "PASS", "OK", clock() - t0, scan_det))

        # 7. Fast Precheck (--fast in isolated fast_wd)
        t0 = clock()
        if skip_fast:
            checks.append(_make_check("fast_precheck", "SKIPPED", "FAST_SKIPPED", clock() - t0, {}))
        else:
            _remaining()
            fast_wd = iso_root / "fast_wd"
            fast_res = bounded_process.run_bounded(
                [
                    sys.executable,
                    str(work_base / "scripts/draft_precheck.py"),
                    "--source", str(work_base),
                    "--patch", str(patch_file),
                    "--plan", str(pack_dir / "plan.json"),
                    "--definition", str(pack_dir / "definition.json"),
                    "--prompt", str(prompt_file),
                    "--workdir", str(fast_wd),
                    "--fast",
                ],
                str(work_base),
                min(timeouts["fast_precheck"], _remaining()),
                env=git_env,
                merge_stderr=True,
            )
            if fast_res.launch_error or fast_res.timed_out:
                raise DsoVerifyError("FAST_PRECHECK_TIMEOUT", "draft_precheck --fast timed out or failed to launch")
            fr_path = fast_wd / "fast-result.json"
            if fast_res.returncode != 0 or not fr_path.is_file():
                checks.append(_make_check("fast_precheck", "FAIL", "FAST_PRECHECK_FAILED", clock() - t0, {"rc": fast_res.returncode}))
                return _finish()
            fr_doc = _load_json_bytes(fr_path, "fast-result.json")
            if fr_doc.get("overall") != "FAST_PRECHECK_PASS":
                checks.append(_make_check("fast_precheck", "FAIL", "FAST_PRECHECK_FAILED", clock() - t0, {"overall": fr_doc.get("overall")}))
                return _finish()
            checks.append(_make_check("fast_precheck", "PASS", "OK", clock() - t0, {"overall": fr_doc.get("overall")}))

        # 8. Contract Qualnames Existence Verification
        t0 = clock()
        cq_verified = validate_contract_qualnames(work_patched, actual_changed, contract_map=contract_map)
        checks.append(_make_check("contract_qualnames", "PASS", "OK", clock() - t0, {"checked_files": cq_verified}))

        # 9. Diff AST Mutation Verification (M1: NEVER execute candidate work_patched/scripts/diff_ast_mutate.py!)
        t0 = clock()
        changed_non_test_py = [rel for rel in actual_changed if rel.endswith(".py") and not _is_test_rel(rel)]
        if not changed_non_test_py:
            checks.append(_make_check("diff_ast_mutate", "PASS", "NO_MUTANTS", clock() - t0, {"changed_non_test_py": []}))
        else:
            rem_sec = _remaining()
            q_filters = _select_mutation_qualnames(changed_non_test_py, qualnames)
            defn_doc = _load_json_bytes(pack_dir / "definition.json", "definition.json")
            test_cmd = mutate_test_cmd or _derive_mutate_test_cmd(defn_doc, work_patched)
            sibling_dam = Path(__file__).resolve().parent / "diff_ast_mutate.py"
            dam_script = sibling_dam if sibling_dam.is_file() else (work_base / "scripts/diff_ast_mutate.py")
            mut_out = iso_root / "mutate-report.json"
            dam_cmd = [
                sys.executable,
                str(dam_script),
                "--repo", str(work_base),
                "--patch", str(patch_file),
                "--test-cmd", test_cmd,
                "--max-mutants", str(max_mutants),
                "--baseline-timeout", str(timeouts["diff_ast_mutate_baseline"]),
                "--per-mutant-timeout", str(timeouts["diff_ast_mutate_per_mutant"]),
                "--total-timeout", str(min(timeouts["diff_ast_mutate_total"], rem_sec)),
                "--workers", workers_arg,
                "--json-out", str(mut_out),
                "--work-parent", str(iso_root),
            ]
            if resolved_cache is not None:
                verifier_sha = _sha256_bytes(Path(__file__).read_bytes().replace(b"\r\n", b"\n"))
                dam_cmd.extend(["--cache-dir", str(resolved_cache), "--caller-tool-sha256", verifier_sha])
            for q in q_filters:
                dam_cmd.extend(["--qualname", q])
            if accept_path is not None:
                dam_cmd.extend(["--accept", str(accept_path)])
            if test_map_path is not None:
                dam_cmd.extend(["--test-map", str(test_map_path)])

            proc_limit = min(timeouts["diff_ast_mutate_total"] + timeouts["diff_ast_mutate_baseline"] + 60.0, rem_sec + 30.0)
            m_res = bounded_process.run_bounded(dam_cmd, str(iso_root), proc_limit, env=git_env, merge_stderr=True)
            if m_res.launch_error or m_res.timed_out:
                raise DsoVerifyError("MUTATE_TIMEOUT", "diff_ast_mutate timed out or failed to launch")
            if not mut_out.is_file():
                raise DsoVerifyError("MUTATE_ERROR", f"diff_ast_mutate rc={m_res.returncode} produced no json")
            m_doc = _load_json_bytes(mut_out, "mutate-report.json")
            survived_list = [m for m in m_doc.get("mutants", []) if m.get("status") == "SURVIVED"]
            accepted_list = [m for m in m_doc.get("mutants", []) if m.get("status") == "ACCEPTED"]
            mutation_block = {
                "summary": m_doc.get("summary", {}),
                "full_run": m_doc.get("full_run"),
                "workers": m_doc.get("workers"),
                "cache": m_doc.get("cache"),
                "mutants": m_doc.get("mutants", []),
                "survived": survived_list,
                "accepted": accepted_list,
                "stale_accepted": m_doc.get("stale_accepted", []),
                "unnecessary_accepted": m_doc.get("unnecessary_accepted", []),
                "out_of_scope_accepted": m_doc.get("out_of_scope_accepted", []),
            }
            if m_doc.get("full_run") is not True or (m_doc.get("summary") or {}).get("full_run") is not True:
                checks.append(_make_check(
                    "diff_ast_mutate",
                    "FAIL",
                    "PARTIAL_MUTATION_RUN_FORBIDDEN",
                    clock() - t0,
                    {"full_run": m_doc.get("full_run")},
                ))
                return _finish()
            m_reason = str(m_doc.get("summary", {}).get("reason") or "MUTATE_ERROR")
            if m_res.returncode == 0:
                checks.append(_make_check("diff_ast_mutate", "PASS", m_reason, clock() - t0, {"total": m_doc["summary"]["total"]}))
            elif m_res.returncode == 1:
                checks.append(_make_check("diff_ast_mutate", "FAIL", m_reason, clock() - t0, {"survived": len(survived_list)}))
            else:
                checks.append(_make_check("diff_ast_mutate", "ERROR", m_reason, clock() - t0, {"rc": m_res.returncode}))
        return _finish()
    except DsoVerifyError as exc:
        step_name = (
            "contract_qualnames"
            if exc.reason_code in ("CONTRACT_QUALNAME_STALE", "TARGET_PARSE_ERROR")
            else ("safe_archive" if exc.reason_code == "UNSAFE_ARCHIVE" else "dso_verify_runtime")
        )
        checks.append(_make_check(step_name, "ERROR", exc.reason_code, clock() - run_start, {"detail": exc.message}))
        return _finish(EXIT_INCOMPLETE, "INCOMPLETE")
    finally:
        _force_rmtree(iso_root)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="One-command D-SO review verifier (TD-136b/TD-139/TD-144a)")
    ap.add_argument("--repo", default=".", help="Read-only base repository path")
    ap.add_argument("--pack", required=True, help="Path to D-SO PACK.zip or unpacked directory")
    ap.add_argument("--work-parent", help="Directory for disposable isolated verification (default: TEMP)")
    ap.add_argument("--skip-fast", action="store_true", help="Skip draft_precheck --fast (forces exit 2 INCOMPLETE)")
    ap.add_argument("--qualname", action="append", default=[], help="Optional qualname glob passed to diff_ast_mutate.py")
    ap.add_argument("--mutate-test-cmd", help="Override pytest command passed to diff_ast_mutate.py")
    ap.add_argument("--accept", help="Optional --accept JSON passed to diff_ast_mutate.py")
    ap.add_argument("--test-map", help="Optional --test-map JSON passed to diff_ast_mutate.py")
    ap.add_argument("--max-mutants", type=int, default=DEFAULT_MAX_MUTANTS)
    ap.add_argument("--mutate-workers", default="1", help="Parallel worker count 1..8 or 'auto' (default: 1)")
    ap.add_argument("--mutate-cache-dir", help="Optional external content-addressed mutation cache directory")
    ap.add_argument("--mutate-baseline-timeout", type=float, default=DEFAULT_STEP_TIMEOUTS["diff_ast_mutate_baseline"])
    ap.add_argument("--mutate-per-mutant-timeout", type=float, default=DEFAULT_STEP_TIMEOUTS["diff_ast_mutate_per_mutant"])
    ap.add_argument("--mutate-total-timeout", type=float, default=DEFAULT_STEP_TIMEOUTS["diff_ast_mutate_total"])
    ap.add_argument("--overall-budget", type=float, default=DEFAULT_OVERALL_BUDGET_SEC)
    ap.add_argument("--json-out", help="Write JSON Schema v1 report to this path")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    ns = parse_args(argv)
    timeouts = {
        "diff_ast_mutate_baseline": ns.mutate_baseline_timeout,
        "diff_ast_mutate_per_mutant": ns.mutate_per_mutant_timeout,
        "diff_ast_mutate_total": ns.mutate_total_timeout,
    }
    rc, report = verify_pack(
        repo=Path(ns.repo).resolve(),
        pack_path=Path(ns.pack).resolve(),
        work_parent=Path(ns.work_parent).resolve() if ns.work_parent else None,
        skip_fast=ns.skip_fast,
        qualnames=ns.qualname or None,
        mutate_test_cmd=ns.mutate_test_cmd,
        accept_path=Path(ns.accept).resolve() if ns.accept else None,
        test_map_path=Path(ns.test_map).resolve() if ns.test_map else None,
        max_mutants=ns.max_mutants,
        step_timeouts=timeouts,
        overall_budget=ns.overall_budget,
        mutate_workers=ns.mutate_workers,
        mutate_cache_dir=Path(ns.mutate_cache_dir) if ns.mutate_cache_dir else None,
    )
    if ns.json_out:
        out_p = Path(ns.json_out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(
        f"DSO_VERIFY status={report['overall_status']} exit={rc} "
        f"task={report['task_id']} canonical_sha256={report['canonical_sha256']}"
    )
    for chk in report["checks"]:
        print(f"DSO_CHECK name={chk['name']} status={chk['status']} reason={chk['reason_code']} sec={chk['elapsed_sec']}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
