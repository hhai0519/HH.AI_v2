# -*- coding: utf-8 -*-
"""Tests and negative controls for scripts/dso_verify.py (TD-136b)."""

from __future__ import annotations

import ast
import copy
import hashlib
import io
import json
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import bounded_process  # noqa: E402
import dso_verify as dv  # noqa: E402


class FakeClock:
    """Deterministic monotonic clock for timeout budget tests; never raises StopIteration."""

    def __init__(self, ticks: list[float], *, tail_step: float = 0.0) -> None:
        self._ticks = [float(t) for t in ticks]
        self._tail_step = float(tail_step)
        self._idx = 0

    def __call__(self) -> float:
        if self._idx < len(self._ticks):
            val = self._ticks[self._idx]
            self._idx += 1
            return val
        extra = self._idx - len(self._ticks) + 1
        self._idx += 1
        return self._ticks[-1] + extra * self._tail_step


# --- Fast AST, Stdlib, Clock & Contract Guard Tests (placed first for -x) ---

def test_pure_stdlib_imports_only() -> None:
    src = Path(dv.__file__).read_bytes().decode("utf-8")
    tree = ast.parse(src)
    allowed_local = {"bounded_process"}
    stdlib = sys.stdlib_module_names
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    bad = sorted(m for m in imported if m not in stdlib and m not in allowed_local)
    assert bad == [], f"Unexpected non-stdlib imports: {bad}"


def test_single_time_monotonic_binding() -> None:
    src = Path(dv.__file__).read_bytes().decode("utf-8")
    tree = ast.parse(src)
    bare_calls: list[int] = []
    attrs: list[int] = []
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            fn = node.func
            if isinstance(fn.value, ast.Name) and fn.value.id == "time" and fn.attr == "monotonic":
                bare_calls.append(node.lineno)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "time" and node.attr == "monotonic":
            attrs.append(node.lineno)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            v = node.value
            if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) and v.value.id == "time" and v.attr == "monotonic":
                targets.append(node.target.id)
    assert bare_calls == []
    assert len(attrs) == 1
    assert targets == ["_DEFAULT_MONOTONIC"]


# --- Safe Archive Validation & Zip Extraction Contract Tests ---

@pytest.mark.parametrize("bad_name", [
    "",
    "../secret.txt",
    "a/../b.txt",
    "./a.txt",
    "a//b.txt",
    "/etc/passwd",
    "a\\b.txt",
    "C:foo.txt",
    "C:/foo.txt",
    "file.txt:zone.identifier",
    "dir:ads/file.txt",
    "bad\x00name.txt",
    "bad\x1fname.txt",
    "bad\nname.txt",
    "authors/",
    "trailing_space ",
    "dir /file.txt",
    "trailing_dot.",
    "dir./file.txt",
    "CON",
    "con.txt",
    "PRN.tar.gz",
    "aux",
    "NUL.json",
    "COM1",
    "com9.log",
    "LPT1",
    "lpt9.md",
    "COM\u00b9.txt",
    "com\u00b2",
    "COM\u00b3.bin",
    "LPT\u00b9",
    "lpt\u00b2.txt",
    "LPT\u00b3.md",
    "CONIN$",
    "conin$.txt",
    "CONOUT$",
    "sub/conout$.log",
    "sub/aux.txt",
])
def test_validate_archive_entry_name_rejects_unsafe(bad_name: str) -> None:
    assert dv.validate_archive_entry_name(bad_name) is None
    assert dv.validate_archive_entry_name(None) is None  # type: ignore[arg-type]
    assert dv.validate_archive_entry_name("/", allow_dir_trailing_slash=True) is None
    assert dv.validate_archive_entry_name("a//", allow_dir_trailing_slash=True) is None


@pytest.mark.parametrize("good_name,allow_dir,expected", [
    ("README.md", False, "README.md"),
    ("my file.txt", False, "my file.txt"),
    ("authors/scripts/dso_verify.py", False, "authors/scripts/dso_verify.py"),
    ("console.log", False, "console.log"),
    ("con0.txt", False, "con0.txt"),
    ("com0.txt", False, "com0.txt"),
    ("my.aux", False, "my.aux"),
    ("authors/", True, "authors"),
    ("authors/a.txt", True, "authors/a.txt"),
])
def test_validate_archive_entry_name_accepts_safe(good_name: str, allow_dir: bool, expected: str) -> None:
    assert dv.validate_archive_entry_name(good_name, allow_dir_trailing_slash=allow_dir) == expected


def _build_zip_from_specs(path: Path, specs: list[tuple[str, bytes, int]]) -> None:
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, data, ext_attr in specs:
                zi = zipfile.ZipInfo(name, date_time=(2026, 11, 26, 12, 0, 0))
                zi.external_attr = ext_attr
                zf.writestr(zi, data)


def test_safe_extract_zip_rejects_collisions_symlinks_bombs_and_corrupt(tmp_path: Path) -> None:
    dest = tmp_path / "out"

    # Bad zip
    bad_zip = tmp_path / "bad.zip"
    bad_zip.write_bytes(b"not a zip")
    with pytest.raises(dv.DsoVerifyError) as ei:
        dv.safe_extract_zip(bad_zip, dest)
    assert ei.value.reason_code == "UNSAFE_ARCHIVE"

    # Case-fold collision
    z_cf = tmp_path / "cf.zip"
    _build_zip_from_specs(z_cf, [("Foo.txt", b"a", 0), ("foo.txt", b"b", 0)])
    with pytest.raises(dv.DsoVerifyError) as ei:
        dv.safe_extract_zip(z_cf, dest)
    assert ei.value.reason_code == "UNSAFE_ARCHIVE"

    # Exact duplicate name
    z_dup = tmp_path / "dup.zip"
    _build_zip_from_specs(z_dup, [("dup.txt", b"1", 0), ("dup.txt", b"2", 0)])
    with pytest.raises(dv.DsoVerifyError) as ei:
        dv.safe_extract_zip(z_dup, dest)
    assert ei.value.reason_code == "UNSAFE_ARCHIVE"

    # Symlink & FIFO mode
    for mode_bits in (stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o600):
        z_mode = tmp_path / f"mode_{mode_bits}.zip"
        _build_zip_from_specs(z_mode, [("evil", b"target", mode_bits << 16)])
        with pytest.raises(dv.DsoVerifyError) as ei:
            dv.safe_extract_zip(z_mode, dest)
        assert ei.value.reason_code == "UNSAFE_ARCHIVE"

    # Non-dir mode on dir entry
    z_baddir = tmp_path / "baddir.zip"
    _build_zip_from_specs(z_baddir, [("d/", b"", (stat.S_IFREG | 0o644) << 16)])
    with pytest.raises(dv.DsoVerifyError) as ei:
        dv.safe_extract_zip(z_baddir, dest)
    assert ei.value.reason_code == "UNSAFE_ARCHIVE"

    # Too many files
    z_cnt = tmp_path / "cnt.zip"
    _build_zip_from_specs(z_cnt, [(f"f{i}.txt", b"x", 0) for i in range(4)])
    with pytest.raises(dv.DsoVerifyError) as ei:
        dv.safe_extract_zip(z_cnt, dest, max_files=3)
    assert ei.value.reason_code == "UNSAFE_ARCHIVE"

    # Single file size limit & total size limit
    z_big = tmp_path / "big.zip"
    _build_zip_from_specs(z_big, [("a.bin", b"A" * 20, 0)])
    with pytest.raises(dv.DsoVerifyError) as ei:
        dv.safe_extract_zip(z_big, dest, max_single_bytes=10)
    assert ei.value.reason_code == "UNSAFE_ARCHIVE"

    z_tot = tmp_path / "tot.zip"
    _build_zip_from_specs(z_tot, [("a.bin", b"A" * 10, 0), ("b.bin", b"B" * 10, 0)])
    with pytest.raises(dv.DsoVerifyError) as ei:
        dv.safe_extract_zip(z_tot, dest, max_single_bytes=15, max_total_bytes=18)
    assert ei.value.reason_code == "UNSAFE_ARCHIVE"

    # Unsafe filename inside zip
    z_ads = tmp_path / "ads.zip"
    _build_zip_from_specs(z_ads, [("sub/COM\u00b2.txt", b"x", 0)])
    with pytest.raises(dv.DsoVerifyError) as ei:
        dv.safe_extract_zip(z_ads, dest)
    assert ei.value.reason_code == "UNSAFE_ARCHIVE"

    # File/directory prefix collisions (including case-fold and 2-level nested ancestor) with zero partial extraction
    for idx_c, pair in enumerate((("a", "a/b"), ("a/b", "a"), ("A", "a/b"), ("a", "a/b/c"))):
        z_fdc = tmp_path / f"fdc_{idx_c}.zip"
        fdc_dest = tmp_path / f"fdc_out_{idx_c}"
        _build_zip_from_specs(z_fdc, [(pair[0], b"x", 0), (pair[1], b"y", 0)])
        with pytest.raises(dv.DsoVerifyError) as ei:
            dv.safe_extract_zip(z_fdc, fdc_dest)
        assert ei.value.reason_code == "UNSAFE_ARCHIVE"
        assert list(fdc_dest.iterdir()) == []

    # Destination path blocked by existing file -> UNSAFE_ARCHIVE (not FileExistsError)
    file_as_dest = tmp_path / "existing_file_dest"
    file_as_dest.write_bytes(b"block")
    z_simple = tmp_path / "simple.zip"
    _build_zip_from_specs(z_simple, [("authors/", b"", (stat.S_IFDIR | 0o755) << 16)])
    with pytest.raises(dv.DsoVerifyError) as ei:
        dv.safe_extract_zip(z_simple, file_as_dest)
    assert ei.value.reason_code == "UNSAFE_ARCHIVE"

    # Empty zip extracted to non-existent multi-level destination & idempotent re-extraction
    deep_empty = tmp_path / "deep" / "empty_dest"
    z_empty = tmp_path / "empty.zip"
    _build_zip_from_specs(z_empty, [])
    assert dv.safe_extract_zip(z_empty, deep_empty) == []
    assert deep_empty.is_dir()
    assert dv.safe_extract_zip(z_empty, deep_empty) == []

    # Exact max_files and max_total_bytes boundaries succeed
    z_exact_cnt = tmp_path / "exact_cnt.zip"
    _build_zip_from_specs(z_exact_cnt, [(f"e{i}.txt", b"x", 0) for i in range(3)])
    assert len(dv.safe_extract_zip(z_exact_cnt, tmp_path / "exact_cnt_out", max_files=3)) == 3

    z_exact_tot = tmp_path / "exact_tot.zip"
    _build_zip_from_specs(z_exact_tot, [("a.bin", b"A" * 10, 0), ("b.bin", b"B" * 10, 0)])
    assert dv.safe_extract_zip(z_exact_tot, tmp_path / "exact_tot_out", max_single_bytes=10, max_total_bytes=20) == ["a.bin", "b.bin"]

    # Valid roundtrip including nested empty directory entry, safe dir entry, regular file mode, & idempotent re-extract
    ok_dest = tmp_path / "ok_out"
    z_ok = tmp_path / "ok.zip"
    _build_zip_from_specs(z_ok, [
        ("authors/", b"", (stat.S_IFDIR | 0o755) << 16),
        ("empty_parent/empty_child/", b"", (stat.S_IFDIR | 0o755) << 16),
        ("authors/a.txt", b"hello\n", (stat.S_IFREG | 0o644) << 16),
    ])
    names = dv.safe_extract_zip(z_ok, ok_dest)
    assert names == ["authors/a.txt"]
    assert (ok_dest / "authors/a.txt").read_bytes() == b"hello\n"
    assert (ok_dest / "empty_parent" / "empty_child").is_dir()
    assert dv.safe_extract_zip(z_ok, ok_dest) == ["authors/a.txt"]


# --- Contract Qualnames Tests ---

def test_contract_qualnames_exist_in_real_repo() -> None:
    """Verify every file & qualname in CONTRACT_QUALNAMES_BY_FILE exists in the real repo AST."""
    all_files = sorted(dv.CONTRACT_QUALNAMES_BY_FILE)
    verified = dv.validate_contract_qualnames(REPO_ROOT, all_files)
    assert sorted(verified) == all_files


def test_validate_contract_qualnames_positive_and_stale(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts/mod.py").write_bytes(
        b"class Box:\n    def check(self) -> int:\n        return 1\ndef top() -> int:\n    return 2\n"
    )
    cmap = {"scripts/mod.py": ("Box.check", "top")}
    assert dv.validate_contract_qualnames(repo, ["scripts/mod.py", "scripts/other.py"], cmap) == {
        "scripts/mod.py": ["Box.check", "top"]
    }

    # Stale qualname when renamed -> CONTRACT_QUALNAME_STALE
    cmap_stale = {"scripts/mod.py": ("Box.check", "missing_fn")}
    with pytest.raises(dv.DsoVerifyError) as ei:
        dv.validate_contract_qualnames(repo, ["scripts/mod.py"], cmap_stale)
    assert ei.value.reason_code == "CONTRACT_QUALNAME_STALE"

    # Missing file in contract map -> CONTRACT_QUALNAME_STALE
    with pytest.raises(dv.DsoVerifyError) as ei2:
        dv.validate_contract_qualnames(repo, ["scripts/absent.py"], {"scripts/absent.py": ("x",)})
    assert ei2.value.reason_code == "CONTRACT_QUALNAME_STALE"


# --- Whitelist canonical_sha256 Cross-Platform Invariance Tests ---

def _sample_report() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "tool": "dso_verify.py",
        "tool_version": "1.0.0",
        "tool_sha256": "a" * 64,
        "base_oid": "9" * 40,
        "task_id": "B117-TEST-R1-261126",
        "overall_status": "VERIFIED",
        "exit_code": 0,
        "skip_fast": False,
        "qualname_filter": ["f_b", "f_a"],
        "inputs": {
            "author_patch_sha256": "1" * 64,
            "plan_sha256": "2" * 64,
            "local_patch_path": "C:\\Users\\foo\\author.patch",
        },
        "author_manifest": [
            {"path": "b.py", "sha256": "3" * 64, "match": True},
            {"path": "a.py", "sha256": "4" * 64, "match": True},
        ],
        "checks": [
            {
                "name": "fast_precheck",
                "status": "PASS",
                "reason_code": "OK",
                "elapsed_sec": 31.2,
                "details": {"counts": "Windows 288 passed, 7 skipped", "workdir": "C:\\tmp\\w"},
            },
        ],
        "mutation": {
            "summary": {
                "total": 2, "caught": 1, "caught_timeout": 0, "survived": 0, "accepted": 1,
                "invalid": 0, "exit_code": 0, "verdict": "PASS", "reason": "OK",
                "skipped_nodes": 5,
            },
            "mutants": [
                {"id": "M-2222222222", "status": "ACCEPTED", "elapsed_sec": 9.1},
                {"id": "M-1111111111", "status": "CAUGHT", "elapsed_sec": 3.4},
            ],
            "stale_accepted": [],
            "unnecessary_accepted": [],
            "out_of_scope_accepted": ["M-9999999999"],
        },
        "timeout_budgets": {"overall_budget_sec": 4500.0},
        "evidence_manifest": {"total_elapsed_sec": 120.5, "runs": [{"name": "fast", "elapsed_sec": 31.2}]},
    }


def test_canonical_sha256_cross_platform_invariance() -> None:
    r_win = _sample_report()
    h_win = dv.compute_canonical_sha256(r_win)

    # Linux counterpart differs on elapsed_sec, local paths, tool_sha256? Wait: Linux keeps same author_manifest order,
    # different elapsed_sec, different OS pytest skipped counts (295 vs 288+7), different workdir/patch paths.
    r_lin = copy.deepcopy(r_win)
    r_lin["inputs"]["local_patch_path"] = "/tmp/linux/author.patch"
    r_lin["checks"][0]["elapsed_sec"] = 12.8
    r_lin["checks"][0]["details"] = {"counts": "Linux 295 passed", "workdir": "/tmp/w"}
    r_lin["mutation"]["mutants"][0]["elapsed_sec"] = 1.1
    r_lin["mutation"]["mutants"][1]["elapsed_sec"] = 0.8
    r_lin["evidence_manifest"]["total_elapsed_sec"] = 45.0
    assert dv.compute_canonical_sha256(r_lin) == h_win

    # Semantic field change MUST change canonical_sha256
    r_diff_status = copy.deepcopy(r_win)
    r_diff_status["overall_status"] = "BLOCKING"
    assert dv.compute_canonical_sha256(r_diff_status) != h_win

    r_diff_mutant = copy.deepcopy(r_win)
    r_diff_mutant["mutation"]["mutants"][0]["status"] = "SURVIVED"
    assert dv.compute_canonical_sha256(r_diff_mutant) != h_win

    # mutation=None handled cleanly
    r_nomut = copy.deepcopy(r_win)
    r_nomut["mutation"] = None
    assert len(dv.compute_canonical_sha256(r_nomut)) == 64


# --- Added-Lines Scan (S2) & TASKBOARD-RECORDS Fidelity Tests ---

def test_scan_added_lines_and_taskboard_records_fidelity(tmp_path: Path) -> None:
    wb = tmp_path / "base"
    wp = tmp_path / "patched"
    for d in (wb, wp):
        (d / "docs").mkdir(parents=True)
    rec_line = "**B-117／舊批紀錄（2026-11-24）**：一句話：舊紀錄。新增待辦：無。"
    (wb / "docs/TASKBOARD.md").write_bytes((f"# Board\n{rec_line}\n").encode("utf-8"))
    (wp / "docs/TASKBOARD.md").write_bytes(b"# Board\n")

    good_patch = (
        "diff --git a/docs/archive/TASKBOARD-RECORDS-0099.md b/docs/archive/TASKBOARD-RECORDS-0099.md\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/docs/archive/TASKBOARD-RECORDS-0099.md\n"
        "@@ -0,0 +1,4 @@\n"
        "+# Archive\n"
        "+````text\n"
        f"+{rec_line}\n"
        "+````\n"
        "diff --git a/docs/EXEC-LOG.md b/docs/EXEC-LOG.md\n"
        "--- a/docs/EXEC-LOG.md\n"
        "+++ b/docs/EXEC-LOG.md\n"
        "@@ -1,1 +1,2 @@\n"
        "+| 9d76f907 | 2026-11-26 | B117-PREV-TASK-R1-261125 |\n"
    ).encode("utf-8")
    ok, viol, det = dv.scan_added_lines(good_patch, work_base=wb, work_patched=wp, current_task_id="B117-CURR-TASK-R1-261126")
    assert ok is True and viol == []
    assert det["old_task_ids_mentioned"] == ["B117-PREV-TASK-R1-261125"]

    # Negative: <!-- and TASKBOARD CHECK 8 hash and mismatched archived record line
    bad_patch = (
        "diff --git a/docs/TASKBOARD.md b/docs/TASKBOARD.md\n"
        "--- a/docs/TASKBOARD.md\n"
        "+++ b/docs/TASKBOARD.md\n"
        "@@ -1,1 +1,2 @@\n"
        "+**最後更新**：2026-11-26 deadbeef\n"
        "+<!-- hidden -->\n"
        "diff --git a/docs/archive/TASKBOARD-RECORDS-0099.md b/docs/archive/TASKBOARD-RECORDS-0099.md\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/docs/archive/TASKBOARD-RECORDS-0099.md\n"
        "@@ -0,0 +1,3 @@\n"
        "+````text\n"
        "+**B-117／偽造紀錄**：改寫。\n"
        "+````\n"
    ).encode("utf-8")
    ok2, viol2, _ = dv.scan_added_lines(bad_patch, work_base=wb, work_patched=wp, current_task_id="B117-CURR-TASK-R1-261126")
    assert ok2 is False and len(viol2) == 3

    # Negative: CR byte & NUL byte in patch
    ok3, viol3, _ = dv.scan_added_lines(b"--- a/x\r\n+++ b/x\r\n", work_base=wb, work_patched=wp, current_task_id="T")
    assert ok3 is False and viol3
    ok_nul, viol_nul, _ = dv.scan_added_lines(
        b"--- a/x\n+++ b/x\n@@ -1,1 +1,1 @@\n+hi\x00there\n",
        work_base=wb, work_patched=wp, current_task_id="T",
    )
    assert ok_nul is False and viol_nul

    # Context/removed lines, deleted file (/dev/null), pre-hunk '+' lines ignored; plain non-b/ '+++ docs/plain.md' scanned
    edge_patch = (
        "diff --git a/docs/a.md b/docs/a.md\n"
        "--- a/docs/a.md\n"
        "+++ b/docs/a.md\n"
        "+<!-- preamble before hunk header ignored -->\n"
        "@@ -1,2 +1,2 @@\n"
        " <!-- context line ignored -->\n"
        "-<!-- deleted line ignored -->\n"
        "+safe added line\n"
        "diff --git a/docs/deleted.md b/docs/deleted.md\n"
        "deleted file mode 100644\n"
        "--- a/docs/deleted.md\n"
        "+++ /dev/null\n"
        "@@ -1,1 +0,0 @@\n"
        "+<!-- deleted hunk '+' ignored when tok == /dev/null -->\n"
        "diff --git a/docs/c.md b/docs/c.md\n"
        "--- a/docs/c.md\n"
        "+++ b/docs/c.md\n"
        "+<!-- pre-hunk line after second +++ before @@ ignored -->\n"
    ).encode("utf-8")
    ok_edge, viol_edge, det_edge = dv.scan_added_lines(edge_patch, work_base=wb, work_patched=wp, current_task_id="T")
    assert ok_edge is True and viol_edge == []
    assert "/dev/null" not in det_edge["added_files"]

    plain_bad = (
        "--- a/docs/plain.md\n"
        "+++ docs/plain.md\n"
        "@@ -0,0 +1,1 @@\n"
        "+<!-- unsafe plain path -->\n"
    ).encode("utf-8")
    ok_plain, viol_plain, _ = dv.scan_added_lines(plain_bad, work_base=wb, work_patched=wp, current_task_id="T")
    assert ok_plain is False and viol_plain


# --- Timeout Budget & End-to-End Pack Verification Tests ---

def test_budget_validation_and_overall_timeout_exceeded(tmp_path: Path) -> None:
    rc, rep = dv.verify_pack(
        repo=tmp_path,
        pack_path=tmp_path / "missing.zip",
        overall_budget=100.0,
        work_parent=tmp_path,
    )
    assert rc == dv.EXIT_INCOMPLETE
    assert rep["overall_status"] == "INCOMPLETE"
    assert rep["checks"][0]["reason_code"] == "INVALID_TIMEOUT_BUDGET"

    # Non-positive timeout also INVALID_TIMEOUT_BUDGET
    rc2, rep2 = dv.verify_pack(
        repo=tmp_path,
        pack_path=tmp_path / "missing.zip",
        step_timeouts={"git_clone": 0},
        overall_budget=5000.0,
        work_parent=tmp_path,
    )
    assert rc2 == dv.EXIT_INCOMPLETE
    assert rep2["checks"][0]["reason_code"] == "INVALID_TIMEOUT_BUDGET"


def test_select_mutation_qualnames_auto_rule() -> None:
    # Only auto-adds CONTRACT_QUALNAMES_BY_FILE when scripts/diff_ast_mutate.py is changed
    assert dv._select_mutation_qualnames(["scripts/dso_verify.py"], None) == []
    assert dv._select_mutation_qualnames(["scripts/diff_ast_mutate.py"], None) == list(
        dv.CONTRACT_QUALNAMES_BY_FILE["scripts/diff_ast_mutate.py"]
    )
    assert dv._select_mutation_qualnames(["scripts/dso_verify.py"], ["scan_added_lines"]) == ["scan_added_lines"]
    with pytest.raises(dv.DsoVerifyError) as ei:
        dv._select_mutation_qualnames(["scripts/dso_verify.py"], ["   "])
    assert ei.value.reason_code == "INVALID_ARGS"


def _make_synthetic_pack(
    tmp_path: Path,
    *,
    mutate_code: bytes | None = None,
    corrupt_sum: bool = False,
) -> tuple[Path, Path, str]:
    repo = tmp_path / "repo"
    (repo / "scripts/tests").mkdir(parents=True)
    (repo / "docs/archive").mkdir(parents=True)

    # Minimal stub scripts inside synthetic repo so verify_pack stays fast (< 2s) and isolated
    (repo / "scripts/bounded_process.py").write_bytes((REPO_ROOT / "scripts/bounded_process.py").read_bytes())
    (repo / "scripts/diff_ast_mutate.py").write_bytes((REPO_ROOT / "scripts/diff_ast_mutate.py").read_bytes())
    (repo / "scripts/prompt_builder.py").write_bytes(
        b"import sys\nprint('PROMPT_BUILDER CHECK PASS B117-SYNTH-R1-261126')\n"
    )
    (repo / "scripts/draft_precheck.py").write_bytes(
        b"import argparse, json\nfrom pathlib import Path\n"
        b"ap = argparse.ArgumentParser()\n"
        b"ap.add_argument('--source'); ap.add_argument('--patch'); ap.add_argument('--plan')\n"
        b"ap.add_argument('--definition'); ap.add_argument('--prompt'); ap.add_argument('--workdir')\n"
        b"ap.add_argument('--fast', action='store_true')\n"
        b"ns = ap.parse_args()\n"
        b"wd = Path(ns.workdir); wd.mkdir(parents=True, exist_ok=True)\n"
        b"(wd / 'fast-result.json').write_text(json.dumps({'overall': 'FAST_PRECHECK_PASS'}), encoding='utf-8')\n"
    )
    (repo / "scripts/target_mod.py").write_bytes(b"def is_pos(x: int) -> bool:\n    return False\n")
    (repo / "scripts/tests/test_target_mod.py").write_bytes(
        b"from scripts.target_mod import is_pos\n"
        b"def test_is_pos():\n"
        b"    assert is_pos(1) is True\n"
        b"    assert is_pos(0) is False\n"
        b"    assert is_pos(-1) is False\n"
    )
    (repo / "docs/TASKBOARD.md").write_bytes("# Board\n**最後更新**：2026-11-26；init\n".encode("utf-8"))

    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "core.autocrlf", "false"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    base_oid = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()

    # Patched change in a temp worktree to generate exact author.patch
    new_code = mutate_code if mutate_code is not None else b"def is_pos(x: int) -> bool:\n    return x > 0\n"
    new_tb = "# Board\n**最後更新**：2026-11-26；B117-SYNTH-R1-261126\n".encode("utf-8")
    pclone = tmp_path / "pclone"
    subprocess.run(["git", "clone", "-q", "-c", "core.autocrlf=false", "--no-local", str(repo), str(pclone)], check=True)
    (pclone / "scripts/target_mod.py").write_bytes(new_code)
    (pclone / "docs/TASKBOARD.md").write_bytes(new_tb)
    patch_bytes = subprocess.check_output(["git", "-C", str(pclone), "diff", "--binary", "--no-ext-diff", "HEAD"])

    stage = tmp_path / "stage"
    (stage / "authors/scripts").mkdir(parents=True)
    (stage / "authors/docs").mkdir(parents=True)
    (stage / "authors/scripts/target_mod.py").write_bytes(new_code)
    (stage / "authors/docs/TASKBOARD.md").write_bytes(new_tb)

    task_id = "B117-SYNTH-R1-261126"
    (stage / "author.patch").write_bytes(patch_bytes)
    (stage / f"{task_id}-prompt.txt").write_bytes(b"<<<BEGIN PLAN_JSON>>>\n{}\n<<<END PLAN_JSON>>>\n")
    (stage / "plan.json").write_bytes((json.dumps({"task_id": task_id, "base_oid": base_oid}) + "\n").encode("utf-8"))
    (stage / "definition.json").write_bytes((json.dumps({
        "task_id": task_id,
        "base_oid": base_oid,
        "focused": {"pytest_args": ["-q", "-rs", "scripts/tests/test_target_mod.py"]},
    }) + "\n").encode("utf-8"))
    authors_doc = {
        "schema_version": 1,
        "task_id": task_id,
        "base_oid": base_oid,
        "author_count": 2,
        "authors": [
            {"path": "docs/TASKBOARD.md", "sha256": hashlib.sha256(new_tb).hexdigest(), "bytes": len(new_tb)},
            {"path": "scripts/target_mod.py", "sha256": hashlib.sha256(new_code).hexdigest(), "bytes": len(new_code)},
        ],
    }
    (stage / "authors.json").write_bytes((json.dumps(authors_doc) + "\n").encode("utf-8"))

    all_files = sorted(p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file())
    sums_lines = [f"{hashlib.sha256((stage / rel).read_bytes()).hexdigest()}  {rel}" for rel in all_files]
    if corrupt_sum:
        sums_lines[0] = ("f" * 64) + sums_lines[0][64:]
    (stage / "SHA256SUMS.txt").write_bytes(("\n".join(sums_lines) + "\n").encode("utf-8"))

    zpath = tmp_path / "pack.zip"
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in sorted(p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file()):
            zf.writestr(rel, (stage / rel).read_bytes())
    return repo, zpath, base_oid


def test_verify_pack_end_to_end_verified_skipfast_blocking_and_cli(tmp_path: Path) -> None:
    repo, pack_zip, _ = _make_synthetic_pack(tmp_path)

    # 1. End-to-end VERIFIED (exit 0) via main() + --json-out
    out_json = tmp_path / "rep_ok.json"
    rc_ok = dv.main(["--repo", str(repo), "--pack", str(pack_zip), "--work-parent", str(tmp_path), "--json-out", str(out_json)])
    rep_ok = json.loads(out_json.read_bytes())
    assert rc_ok == 0
    assert rep_ok["overall_status"] == "VERIFIED"
    assert rep_ok["mutation"]["summary"]["survived"] == 0
    assert rep_ok["mutation"]["summary"]["caught"] >= 2
    assert len(rep_ok["evidence_manifest"]["runs"]) == 9
    assert all("elapsed_sec" in r for r in rep_ok["evidence_manifest"]["runs"])

    # 2. --skip-fast forces exit 2 INCOMPLETE
    rc_sf, rep_sf = dv.verify_pack(repo=repo, pack_path=pack_zip, work_parent=tmp_path, skip_fast=True)
    assert rc_sf == dv.EXIT_INCOMPLETE
    assert rep_sf["overall_status"] == "INCOMPLETE"
    assert any(c["name"] == "fast_precheck" and c["status"] == "SKIPPED" and c["reason_code"] == "FAST_SKIPPED" for c in rep_sf["checks"])

    # 3. Corrupted SHA256SUMS -> exit 1 BLOCKING
    repo_b, bad_zip, _ = _make_synthetic_pack(tmp_path / "bcase", corrupt_sum=True)
    rc_bad, rep_bad = dv.verify_pack(repo=repo_b, pack_path=bad_zip, work_parent=tmp_path)
    assert rc_bad == dv.EXIT_BLOCKING
    assert rep_bad["overall_status"] == "BLOCKING"
    assert any(c["reason_code"] == "SHA256_MISMATCH" for c in rep_bad["checks"])

    # 4. Survived mutant -> exit 1 BLOCKING with full un-truncated survived list
    repo_s, surv_zip, _ = _make_synthetic_pack(
        tmp_path / "scase",
        mutate_code=b"def is_pos(x: int) -> bool:\n    y = 42\n    return x > 0\n",
    )
    rc_sv, rep_sv = dv.verify_pack(repo=repo_s, pack_path=surv_zip, work_parent=tmp_path)
    assert rc_sv == dv.EXIT_BLOCKING
    assert rep_sv["overall_status"] == "BLOCKING"
    assert rep_sv["mutation"]["summary"]["survived"] >= 1
    assert len(rep_sv["mutation"]["survived"]) == rep_sv["mutation"]["summary"]["survived"]


@pytest.mark.parametrize("pair", [("a", "a/b"), ("a/b", "a"), ("A", "a/b")])
def test_n1_file_dir_collision_cli_returns_exit2_and_writes_json(tmp_path: Path, pair: tuple[str, str]) -> None:
    """TD-136b R2 N1: file/dir collision returns exit 2 UNSAFE_ARCHIVE and writes JSON report."""
    zpath = tmp_path / "collision.zip"
    out_json = tmp_path / "collision_report.json"
    _build_zip_from_specs(zpath, [(pair[0], b"x", 0), (pair[1], b"y", 0)])
    rc = dv.main(["--repo", str(tmp_path), "--pack", str(zpath), "--work-parent", str(tmp_path), "--json-out", str(out_json)])
    assert rc == dv.EXIT_INCOMPLETE
    assert out_json.is_file()
    rep = json.loads(out_json.read_bytes())
    assert rep["overall_status"] == "INCOMPLETE"
    assert rep["exit_code"] == 2
    assert rep["checks"][0]["reason_code"] == "UNSAFE_ARCHIVE"


def test_n1_dir_mkdir_oserror_converts_to_unsafe_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Defensive OSError during directory entry creation converts to UNSAFE_ARCHIVE."""
    zpath = tmp_path / "dir_err.zip"
    dest = tmp_path / "dir_err_out"
    _build_zip_from_specs(zpath, [("sub/", b"", (stat.S_IFDIR | 0o755) << 16)])
    real_mkdir = Path.mkdir

    def _fail_sub(self: Path, parents: bool = False, exist_ok: bool = False) -> None:
        if self.name == "sub":
            raise PermissionError("simulated mkdir error")
        real_mkdir(self, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", _fail_sub)
    with pytest.raises(dv.DsoVerifyError) as ei:
        dv.safe_extract_zip(zpath, dest)
    assert ei.value.reason_code == "UNSAFE_ARCHIVE"
