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


# --- Fast Unit Tests for TD-139 / 4a / M1 / M3 / M4 / S4 (placed first for -x) ---


def test_td144a_fast_unit_workers_cache_dir_and_content_canonical(tmp_path: Path) -> None:
    """Kill every branch of _resolve_workers_arg, _validate_mutate_cache_dir, compute_content_canonical_sha256, and _dir_prefixes_for_casefold."""
    assert dv._resolve_workers_arg(1) == "1"
    assert dv._resolve_workers_arg(8) == "8"
    assert dv._resolve_workers_arg("1") == "1"
    assert dv._resolve_workers_arg("8") == "8"
    assert dv._resolve_workers_arg(" 4 ") == "4"
    assert dv._resolve_workers_arg("AUTO") == "auto"
    for bad_w in (True, False, 0, 9, "", "   ", "0", "9", "-1", "abc", 1.5):
        with pytest.raises(dv.DsoVerifyError) as ei:
            dv._resolve_workers_arg(bad_w)  # type: ignore[arg-type]
        assert ei.value.reason_code == "INVALID_ARGS"

    repo_d = tmp_path / "repo_v"
    pack_d = tmp_path / "pack_v"
    repo_d.mkdir()
    pack_d.mkdir()
    for bad_c in (repo_d, repo_d / "sub", pack_d, pack_d / "nested"):
        with pytest.raises(dv.DsoVerifyError) as ei:
            dv._validate_mutate_cache_dir(bad_c, repo_d, pack_d)
        assert ei.value.reason_code == "INVALID_ARGS"
    file_c = tmp_path / "cfile.txt"
    file_c.write_bytes(b"x")
    with pytest.raises(dv.DsoVerifyError) as ei:
        dv._validate_mutate_cache_dir(file_c, repo_d, pack_d)
    assert ei.value.reason_code == "INVALID_ARGS"
    pack_zip = tmp_path / "p_file.zip"
    pack_zip.write_bytes(b"PK")
    assert dv._validate_mutate_cache_dir(pack_zip / "sub", repo_d, pack_zip) == (pack_zip / "sub").resolve()
    ok_c = tmp_path / "ok_c"
    assert dv._validate_mutate_cache_dir(ok_c, repo_d, pack_d) == ok_c.resolve()

    assert dv._dir_prefixes_for_casefold("a") == []
    assert dv._dir_prefixes_for_casefold("a/b/c") == ["a", "a/b"]

    rep_a = {
        "schema_version": 1, "tool": "dso_verify", "tool_version": "1.1.0",
        "base_oid": "a" * 40, "task_id": "T1", "overall_status": "VERIFIED", "exit_code": 0,
        "skip_fast": False, "qualname_filter": [],
        "inputs": {"author_patch_sha256": "1" * 64, "pack_sha256": "9" * 64},
        "author_manifest": [], "checks": [{"name": "c", "status": "PASS", "reason_code": "OK"}], "mutation": None,
    }
    rep_b = copy.deepcopy(rep_a)
    rep_b["inputs"] = {"author_patch_sha256": "1" * 64}
    assert dv.compute_content_canonical_sha256(rep_a) == dv.compute_content_canonical_sha256(rep_b)
    assert dv.compute_canonical_sha256(rep_a) != dv.compute_canonical_sha256(rep_b)
    rep_no_in = {**rep_a, "inputs": None}
    assert dv.compute_content_canonical_sha256(rep_no_in) == dv.compute_content_canonical_sha256({**rep_a, "inputs": {}})


def test_td144a_fast_unit_verify_pack_mocked_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fast in-memory verification of verify_pack full_run=False, workers/cache forwarding, error handling, and dir-mode."""
    pack_dir = tmp_path / "pdir_fast"
    (pack_dir / "authors/scripts").mkdir(parents=True)
    mod_b = b"def fn(x: int) -> int:\n    return x + 1\n"
    (pack_dir / "authors/scripts/mod.py").write_bytes(mod_b)
    (pack_dir / "author.patch").write_bytes(b"diff --git a/scripts/mod.py b/scripts/mod.py\n--- a/scripts/mod.py\n+++ b/scripts/mod.py\n@@ -1 +1 @@\n-x\n+y\n")
    (pack_dir / "plan.json").write_bytes(b'{"task_id":"T1","base_oid":"' + b"a" * 40 + b'"}\n')
    (pack_dir / "definition.json").write_bytes(b'{"task_id":"T1","base_oid":"' + b"a" * 40 + b'","focused":{"pytest_args":["scripts/tests/t.py"]}}\n')
    (pack_dir / "T1-prompt.txt").write_bytes(b"<<<BEGIN PLAN_JSON>>>\n{}\n<<<END PLAN_JSON>>>\n")
    (pack_dir / "authors.json").write_bytes(json.dumps({
        "schema_version": 1, "task_id": "T1", "base_oid": "a" * 40, "author_count": 1,
        "authors": [{"path": "scripts/mod.py", "sha256": hashlib.sha256(mod_b).hexdigest()}],
    }).encode("utf-8"))
    all_r = sorted(p.relative_to(pack_dir).as_posix() for p in pack_dir.rglob("*") if p.is_file())
    (pack_dir / "SHA256SUMS.txt").write_bytes(("\n".join(f"{hashlib.sha256((pack_dir / r).read_bytes()).hexdigest()}  {r}" for r in all_r) + "\n").encode("utf-8"))

    repo = tmp_path / "repo_fast_vp"
    (repo / "scripts/tests").mkdir(parents=True)
    (repo / "docs").mkdir(parents=True)
    (repo / "docs/TASKBOARD.md").write_bytes(b"**last**: 2026\n")
    (repo / "scripts/mod.py").write_bytes(mod_b)
    (repo / "scripts/tests/t.py").write_bytes(b"def test_t(): assert True\n")

    monkeypatch.setattr(dv, "_check_pack_integrity", lambda pd, ef: (True, "OK", {"task_id": "T1", "base_oid": "a" * 40}, {r: "0" * 64 for r in ef}))
    monkeypatch.setattr(dv, "_run_git", lambda rp, args, timeout=30.0: (
        ("a" * 40).encode("utf-8") if args[0] == "rev-parse"
        else (b"scripts/mod.py\x00" if args[0] == "diff" else b"")
    ))
    monkeypatch.setattr(dv, "scan_added_lines", lambda *a, **kw: (True, [], {}))
    monkeypatch.setattr(dv, "validate_contract_qualnames", lambda *a, **kw: [])

    seen_dam: list[list[str]] = []
    mode = {"case": "summary_partial"}

    def _mock_rb(argv, cwd, timeout, env=None, merge_stderr=False):
        cmd_s = " ".join(str(x) for x in argv)
        if "clone" in argv:
            Path(argv[-1]).mkdir(parents=True, exist_ok=True)
            (Path(argv[-1]) / "scripts/tests").mkdir(parents=True, exist_ok=True)
            (Path(argv[-1]) / "docs").mkdir(parents=True, exist_ok=True)
            (Path(argv[-1]) / "scripts/mod.py").write_bytes(mod_b)
            (Path(argv[-1]) / "scripts/tests/t.py").write_bytes(b"def test_t(): assert True\n")
            (Path(argv[-1]) / "docs/README.md").write_bytes(b"# doc\n")
            return bounded_process.BoundedResult(0, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED)
        if "apply" in argv or "prompt_builder" in cmd_s:
            return bounded_process.BoundedResult(0, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED)
        if "diff_ast_mutate.py" in cmd_s:
            seen_dam.append(list(argv))
            jout = Path(argv[argv.index("--json-out") + 1])
            if mode["case"] == "timeout":
                return bounded_process.BoundedResult(None, True, None, b"", b"", bounded_process.KILL_TREE_SIGNALLED)
            if mode["case"] == "no_json":
                return bounded_process.BoundedResult(2, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED)
            fr = mode["case"] == "ok"
            sfr = mode["case"] != "summary_partial"
            tfr = mode["case"] != "top_partial"
            rc_m = 2 if mode["case"] == "rc2" else (1 if mode["case"] == "rc1" else 0)
            st_m = "SURVIVED" if rc_m == 1 else "CAUGHT"
            reason_m = "" if mode["case"] == "rc2" else ("OK" if rc_m == 0 else "MUTANTS_SURVIVED")
            jout.write_bytes(json.dumps({
                "full_run": tfr, "workers": 4,
                "cache": {"enabled": True, "hit": False, "cache_key": "k", "source_report_sha256": "s"},
                "summary": {"total": 1, "caught": 1 if rc_m == 0 else 0, "caught_timeout": 0, "survived": 1 if rc_m == 1 else 0, "accepted": 0, "invalid": 0, "exit_code": rc_m, "verdict": "PASS", "reason": reason_m, "full_run": sfr},
                "mutants": [{"id": "M-1", "status": st_m}],
            }).encode("utf-8"))
            return bounded_process.BoundedResult(rc_m, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED)
        return bounded_process.BoundedResult(0, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED)

    monkeypatch.setattr(dv.bounded_process, "run_bounded", _mock_rb)
    ext_cd = tmp_path / "ext_vp_c"

    mode["case"] = "summary_partial"
    rc_sp, rep_sp = dv.verify_pack(
        repo=repo, pack_path=pack_dir, work_parent=tmp_path, skip_fast=True,
        mutate_workers=4, mutate_cache_dir=ext_cd, monotonic_fn=FakeClock([100.0], tail_step=1.0),
    )
    assert rc_sp == dv.EXIT_BLOCKING and rep_sp["checks"][-1]["reason_code"] == "PARTIAL_MUTATION_RUN_FORBIDDEN"
    assert rep_sp["checks"][0]["elapsed_sec"] == 1.0
    assert all(1.0 <= c["elapsed_sec"] < 50.0 for c in rep_sp["checks"])
    assert 10.0 <= rep_sp["evidence_manifest"]["total_elapsed_sec"] < 100.0
    assert "--workers" in seen_dam[-1] and "4" in seen_dam[-1]
    assert "--cache-dir" in seen_dam[-1] and "--caller-tool-sha256" in seen_dam[-1]

    mode["case"] = "top_partial"
    rc_tp, rep_tp = dv.verify_pack(repo=repo, pack_path=pack_dir, work_parent=tmp_path, skip_fast=True)
    assert rc_tp == dv.EXIT_BLOCKING and rep_tp["checks"][-1]["reason_code"] == "PARTIAL_MUTATION_RUN_FORBIDDEN"

    mode["case"] = "ok"
    acc_p = tmp_path / "acc.json"
    rc_ok, rep_ok = dv.verify_pack(
        repo=repo, pack_path=pack_dir, work_parent=tmp_path, skip_fast=True,
        qualnames=["fn"], max_mutants=0, mutate_test_cmd="custom-pytest-cmd",
        accept_path=acc_p, monotonic_fn=FakeClock([100.0], tail_step=1.0),
    )
    assert rc_ok == dv.EXIT_INCOMPLETE and rep_ok["pack_mode"] == "dir"
    assert rep_ok["checks"][-1]["status"] == "PASS" and rep_ok["checks"][-1]["reason_code"] == "OK"
    assert rep_ok["mutation"]["full_run"] is True and rep_ok["mutation"]["accepted"] == []
    assert rep_ok["checks"][0]["elapsed_sec"] == 1.0
    assert all(1.0 <= c["elapsed_sec"] < 50.0 for c in rep_ok["checks"])
    assert 10.0 <= rep_ok["evidence_manifest"]["total_elapsed_sec"] < 100.0
    last_dam = seen_dam[-1]
    assert last_dam[last_dam.index("--max-mutants") + 1] == "0"
    assert last_dam[last_dam.index("--test-cmd") + 1] == "custom-pytest-cmd"
    assert last_dam[last_dam.index("--qualname") + 1] == "fn"
    assert last_dam[last_dam.index("--accept") + 1] == str(acc_p.resolve())

    mode["case"] = "rc1"
    rc_1, rep_1 = dv.verify_pack(repo=repo, pack_path=pack_dir, work_parent=tmp_path, skip_fast=True)
    assert rc_1 == dv.EXIT_BLOCKING and rep_1["checks"][-1]["status"] == "FAIL" and rep_1["checks"][-1]["details"]["survived"] == 1

    mode["case"] = "rc2"
    rc_2, rep_2 = dv.verify_pack(repo=repo, pack_path=pack_dir, work_parent=tmp_path, skip_fast=True)
    assert rc_2 == dv.EXIT_INCOMPLETE and rep_2["checks"][-1]["status"] == "ERROR" and rep_2["checks"][-1]["reason_code"] == "MUTATE_ERROR"

    rc_mm, rep_mm = dv.verify_pack(repo=repo, pack_path=pack_dir, work_parent=tmp_path, max_mutants=-1)
    assert rc_mm == dv.EXIT_INCOMPLETE and rep_mm["checks"][0]["reason_code"] == "INVALID_ARGS"

    for bad_qn in ([123], ["   "]):
        rc_bq, rep_bq = dv.verify_pack(repo=repo, pack_path=pack_dir, work_parent=tmp_path, qualnames=bad_qn)  # type: ignore[arg-type]
        assert rc_bq == dv.EXIT_INCOMPLETE and rep_bq["checks"][0]["reason_code"] == "INVALID_ARGS"

    mode["case"] = "timeout"
    rc_to, rep_to = dv.verify_pack(repo=repo, pack_path=pack_dir, work_parent=tmp_path, skip_fast=True)
    assert rc_to == dv.EXIT_INCOMPLETE and rep_to["checks"][-1]["reason_code"] == "MUTATE_TIMEOUT"

    mode["case"] = "no_json"
    rc_nj, rep_nj = dv.verify_pack(repo=repo, pack_path=pack_dir, work_parent=tmp_path, skip_fast=True)
    assert rc_nj == dv.EXIT_INCOMPLETE and rep_nj["checks"][-1]["reason_code"] == "MUTATE_ERROR"

    dam_before = len(seen_dam)
    pack_nm = tmp_path / "pdir_nm"
    (pack_nm / "authors/docs").mkdir(parents=True)
    (pack_nm / "authors/scripts/tests").mkdir(parents=True)
    doc_b = b"# doc\n"
    tst_b = b"def test_t(): assert True\n"
    (pack_nm / "authors/docs/README.md").write_bytes(doc_b)
    (pack_nm / "authors/scripts/tests/t.py").write_bytes(tst_b)
    (pack_nm / "author.patch").write_bytes(b"diff --git a/docs/README.md b/docs/README.md\n--- a/docs/README.md\n+++ b/docs/README.md\n@@ -1 +1 @@\n-a\n+b\n")
    (pack_nm / "plan.json").write_bytes((pack_dir / "plan.json").read_bytes())
    (pack_nm / "definition.json").write_bytes((pack_dir / "definition.json").read_bytes())
    (pack_nm / "T1-prompt.txt").write_bytes((pack_dir / "T1-prompt.txt").read_bytes())
    (pack_nm / "authors.json").write_bytes(json.dumps({
        "schema_version": 1, "task_id": "T1", "base_oid": "a" * 40, "author_count": 2,
        "authors": [
            {"path": "docs/README.md", "sha256": hashlib.sha256(doc_b).hexdigest()},
            {"path": "scripts/tests/t.py", "sha256": hashlib.sha256(tst_b).hexdigest()},
        ],
    }).encode("utf-8"))
    with monkeypatch.context() as mp:
        mp.setattr(dv, "_run_git", lambda rp, args, timeout=30.0: (
            ("a" * 40).encode("utf-8") if args[0] == "rev-parse"
            else (b"docs/README.md\x00scripts/tests/t.py\x00" if args[0] == "diff" else b"")
        ))
        rc_nm, rep_nm = dv.verify_pack(repo=repo, pack_path=pack_nm, work_parent=tmp_path, skip_fast=True)
        assert rc_nm == dv.EXIT_INCOMPLETE and len(seen_dam) == dam_before
        assert rep_nm["checks"][-1]["reason_code"] == "NO_MUTANTS"
        assert rep_nm["checks"][-1]["details"]["changed_non_test_py"] == []


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
        "tool_version": "1.1.0",
        "tool_sha256": "a" * 64,
        "pack_mode": "zip",
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


def test_td139_s4_bounded_prefixes_equivalence_and_leading_slash_rejection(tmp_path: Path) -> None:
    """S4: Compare old while-loop prefixes vs _dir_prefixes_for_casefold across path shapes and assert no empty segment."""
    def _legacy_prefixes(cf: str) -> set[str]:
        out: set[str] = set()
        parent = cf.rpartition("/")[0]
        while parent:
            out.add(parent)
            parent = parent.rpartition("/")[0]
        return out

    samples = [
        ("single.txt", False),
        ("a/b.txt", False),
        ("a/b/c/d/e.py", False),
        ("DirA/SubB/FileC.json", False),
        ("authors/", True),
        ("a/b/c/", True),
    ]
    for raw, allow_dir in samples:
        norm = dv.validate_archive_entry_name(raw, allow_dir_trailing_slash=allow_dir)
        assert norm is not None
        cf = norm.casefold()
        got_new = set(dv._dir_prefixes_for_casefold(cf))
        got_old = _legacy_prefixes(cf)
        assert got_new == got_old, f"Mismatch for {raw!r}: {got_new} != {got_old}"
        assert "" not in got_new

    # Explicitly confirm leading slashes and empty segments are rejected before prefix enumeration
    for unsafe in ("/a", "/a/b", "/a/", "a//b", "a///", "//"):
        assert dv.validate_archive_entry_name(unsafe, allow_dir_trailing_slash=False) is None
        assert dv.validate_archive_entry_name(unsafe, allow_dir_trailing_slash=True) is None

    # Deep nested prefix collision fails cleanly with UNSAFE_ARCHIVE
    z_deep = tmp_path / "deep_col.zip"
    _build_zip_from_specs(z_deep, [("a/b/c/d", b"file", 0), ("a/b/c/d/e/f.txt", b"nested", 0)])
    with pytest.raises(dv.DsoVerifyError) as ei:
        dv.safe_extract_zip(z_deep, tmp_path / "deep_out")
    assert ei.value.reason_code == "UNSAFE_ARCHIVE"










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


def test_4a_dir_vs_zip_pack_mode_and_content_canonical_equivalence(tmp_path: Path) -> None:
    """Q3 (4a): Dir mode canonical_sha256 == dir content_canonical_sha256 == zip content_canonical_sha256."""
    repo, pack_zip, _ = _make_synthetic_pack(tmp_path)
    pack_dir = tmp_path / "unpacked_dir"
    assert dv.safe_extract_zip(pack_zip, pack_dir)

    rc_dir, rep_dir = dv.verify_pack(repo=repo, pack_path=pack_dir, work_parent=tmp_path)
    rc_zip, rep_zip = dv.verify_pack(repo=repo, pack_path=pack_zip, work_parent=tmp_path)
    assert rc_dir == 0 and rc_zip == 0
    assert rep_dir["pack_mode"] == "dir" and rep_zip["pack_mode"] == "zip"
    assert "pack_sha256" not in rep_dir["inputs"] and "pack_sha256" in rep_zip["inputs"]
    assert rep_dir["canonical_sha256"] == rep_dir["content_canonical_sha256"]
    assert rep_zip["content_canonical_sha256"] == rep_dir["canonical_sha256"]
    assert rep_zip["canonical_sha256"] != rep_dir["canonical_sha256"]
    assert len(dv.CANONICAL_INCLUDED_FIELDS) == 13
    assert [c["name"] for c in rep_zip["checks"]] == [
        "safe_archive", "pack_integrity", "repo_base_check", "patch_and_authors",
        "prompt_check", "added_lines_scan", "fast_precheck", "contract_qualnames", "diff_ast_mutate",
    ]


def test_m1_dso_verify_never_executes_candidate_diff_ast_mutate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M1: Even when author.patch modifies scripts/diff_ast_mutate.py, verifier executes sibling tool, NOT work_patched."""
    sib_dir = tmp_path / "sib_verifier" / "scripts"
    sib_dir.mkdir(parents=True)
    fake_dv = sib_dir / "dso_verify.py"
    fake_dv.write_bytes(b"# fake verifier stub\n")
    sib_log = tmp_path / "m1_sib_invoked.txt"
    cand_log = tmp_path / "m1_cand_invoked.txt"
    sib_dam = sib_dir / "diff_ast_mutate.py"
    sib_dam.write_bytes((
        "import json, sys\n"
        "from pathlib import Path\n"
        f"with Path({str(sib_log)!r}).open('a', encoding='utf-8', newline='\\n') as f:\n"
        "    f.write(str(Path(__file__).resolve()) + '\\n')\n"
        "jout = Path(sys.argv[sys.argv.index('--json-out') + 1])\n"
        "jout.write_bytes(json.dumps({\n"
        "    'full_run': True, 'workers': 1,\n"
        "    'cache': {'enabled': False, 'hit': False, 'cache_key': None, 'source_report_sha256': None},\n"
        "    'summary': {'total': 1, 'caught': 1, 'caught_timeout': 0, 'survived': 0, 'accepted': 0, 'invalid': 0, 'exit_code': 0, 'verdict': 'PASS', 'reason': 'OK', 'full_run': True},\n"
        "    'mutants': [{'id': 'M-1', 'status': 'CAUGHT'}],\n"
        "}).encode('utf-8'))\n"
        "raise SystemExit(0)\n"
    ).encode("utf-8"))

    # Build a synthetic pack modifying scripts/diff_ast_mutate.py with valid AST preserving contract qualnames
    repo2 = tmp_path / "repo_m1"
    (repo2 / "scripts/tests").mkdir(parents=True)
    (repo2 / "docs").mkdir(parents=True)
    for fn in ("bounded_process.py", "diff_ast_mutate.py"):
        (repo2 / "scripts" / fn).write_bytes((REPO_ROOT / "scripts" / fn).read_bytes())
    (repo2 / "scripts/prompt_builder.py").write_bytes(b"print('PROMPT_BUILDER CHECK PASS B117-M1-R1-261127')\n")
    (repo2 / "scripts/draft_precheck.py").write_bytes(
        b"import argparse, json\nfrom pathlib import Path\n"
        b"ap = argparse.ArgumentParser()\n"
        b"for a in ('--source','--patch','--plan','--definition','--prompt','--workdir'): ap.add_argument(a)\n"
        b"ap.add_argument('--fast', action='store_true')\n"
        b"ns = ap.parse_args(); wd = Path(ns.workdir); wd.mkdir(parents=True, exist_ok=True)\n"
        b"(wd / 'fast-result.json').write_text(json.dumps({'overall': 'FAST_PRECHECK_PASS'}), encoding='utf-8')\n"
    )
    (repo2 / "docs/TASKBOARD.md").write_bytes("# Board\n**最後更新**：2026-11-27；init\n".encode("utf-8"))
    (repo2 / "scripts/tests/test_m1_stub.py").write_bytes(
        b"from scripts.diff_ast_mutate import _matches_qualname\n"
        b"def test_ok():\n"
        b"    assert _matches_qualname('a.b', ['a.*']) is True\n"
        b"    assert _matches_qualname('x.y', ['a.*']) is False\n"
    )
    subprocess.run(["git", "init", "-q", str(repo2)], check=True)
    subprocess.run(["git", "-C", str(repo2), "config", "user.name", "T"], check=True)
    subprocess.run(["git", "-C", str(repo2), "config", "user.email", "t@e.test"], check=True)
    subprocess.run(["git", "-C", str(repo2), "config", "core.autocrlf", "false"], check=True)
    subprocess.run(["git", "-C", str(repo2), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo2), "commit", "-qm", "base"], check=True)
    base_oid = subprocess.check_output(["git", "-C", str(repo2), "rev-parse", "HEAD"], text=True).strip()

    pclone = tmp_path / "pclone_m1"
    subprocess.run(["git", "clone", "-q", "-c", "core.autocrlf=false", "--no-local", str(repo2), str(pclone)], check=True)
    dam_orig = (pclone / "scripts/diff_ast_mutate.py").read_bytes().decode("utf-8")
    # Modify a safe return line inside _matches_qualname AND mark candidate entrypoint fail-loud if ever executed
    dam_text = dam_orig.replace(
        "return any(fnmatch.fnmatchcase(qualname, pat) for pat in patterns)",
        "return any(fnmatch.fnmatchcase(qualname, p) for p in patterns)",
    )
    assert "raise SystemExit(main())" in dam_text
    dam_text = dam_text.replace(
        "raise SystemExit(main())",
        f"Path({str(cand_log)!r}).write_text(str(Path(__file__).resolve()), encoding='utf-8'); raise SystemExit(99)",
    )
    dam_new = dam_text.encode("utf-8")
    assert dam_new != dam_orig.encode("utf-8")
    (pclone / "scripts/diff_ast_mutate.py").write_bytes(dam_new)
    patch_b = subprocess.check_output(["git", "-C", str(pclone), "diff", "--binary", "--no-ext-diff", "HEAD"])

    stage = tmp_path / "stage_m1"
    (stage / "authors/scripts").mkdir(parents=True)
    (stage / "authors/scripts/diff_ast_mutate.py").write_bytes(dam_new)
    tid = "B117-M1-R1-261127"
    (stage / "author.patch").write_bytes(patch_b)
    (stage / f"{tid}-prompt.txt").write_bytes(b"<<<BEGIN PLAN_JSON>>>\n{}\n<<<END PLAN_JSON>>>\n")
    (stage / "plan.json").write_bytes(json.dumps({"task_id": tid, "base_oid": base_oid}).encode("utf-8"))
    (stage / "definition.json").write_bytes(json.dumps({
        "task_id": tid, "base_oid": base_oid,
        "focused": {"pytest_args": ["-q", "-rs", "scripts/tests/test_m1_stub.py"]},
    }).encode("utf-8"))
    (stage / "authors.json").write_bytes(json.dumps({
        "schema_version": 1, "task_id": tid, "base_oid": base_oid, "author_count": 1,
        "authors": [{"path": "scripts/diff_ast_mutate.py", "sha256": hashlib.sha256(dam_new).hexdigest()}],
    }).encode("utf-8"))
    all_f = sorted(p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file())
    (stage / "SHA256SUMS.txt").write_bytes(("\n".join(f"{hashlib.sha256((stage / r).read_bytes()).hexdigest()}  {r}" for r in all_f) + "\n").encode("utf-8"))
    z_m1 = tmp_path / "m1.zip"
    with zipfile.ZipFile(z_m1, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for r in all_f:
            zf.writestr(r, (stage / r).read_bytes())
        zf.writestr("SHA256SUMS.txt", (stage / "SHA256SUMS.txt").read_bytes())

    monkeypatch.setattr(dv, "__file__", str(fake_dv))
    rc_m1, rep_m1 = dv.verify_pack(
        repo=repo2, pack_path=z_m1, work_parent=tmp_path, skip_fast=True,
        qualnames=["_matches_qualname"], mutate_test_cmd="{python} -m pytest -p no:cacheprovider -q -x scripts/tests/test_m1_stub.py",
    )
    assert rc_m1 == dv.EXIT_INCOMPLETE  # skip_fast=True => INCOMPLETE, diff_ast_mutate PASS
    dam_chks = [c for c in rep_m1["checks"] if c["name"] == "diff_ast_mutate"]
    assert len(dam_chks) == 1 and dam_chks[0]["status"] == "PASS"
    assert not cand_log.exists()
    assert sib_log.is_file()
    invoked = [ln.strip() for ln in sib_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(invoked) == 1
    assert "work_patched" not in invoked[0].replace("\\", "/")
    assert Path(invoked[0]).resolve() == sib_dam.resolve()


def test_td144a_precondition1_full_run_enforcement_and_m3_workers_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, pack_zip, _ = _make_synthetic_pack(tmp_path)

    # 1. Invalid --mutate-workers and --mutate-cache-dir inside repo/pack -> exit 2 INVALID_ARGS
    for bad_w in ("0", "9", "abc", "", True):
        rc_w, rep_w = dv.verify_pack(repo=repo, pack_path=pack_zip, work_parent=tmp_path, mutate_workers=bad_w)  # type: ignore[arg-type]
        assert rc_w == dv.EXIT_INCOMPLETE and rep_w["checks"][0]["reason_code"] == "INVALID_ARGS"

    rc_ci, rep_ci = dv.verify_pack(repo=repo, pack_path=pack_zip, work_parent=tmp_path, mutate_cache_dir=repo / "bad_cache")
    assert rc_ci == dv.EXIT_INCOMPLETE and rep_ci["checks"][0]["reason_code"] == "INVALID_ARGS"

    unpacked = tmp_path / "unpacked_pack_c"
    dv.safe_extract_zip(pack_zip, unpacked)
    rc_cp, rep_cp = dv.verify_pack(repo=repo, pack_path=unpacked, work_parent=tmp_path, mutate_cache_dir=unpacked / "inner_c")
    assert rc_cp == dv.EXIT_INCOMPLETE and rep_cp["checks"][0]["reason_code"] == "INVALID_ARGS"

    # 2. Workers=1 no cache vs workers=2 + external cache (cold then warm) -> IDENTICAL canonical_sha256!
    ext_cache = tmp_path / "ext_dso_cache"
    rc_w1, rep_w1 = dv.verify_pack(repo=repo, pack_path=pack_zip, work_parent=tmp_path, mutate_workers="1")
    rc_cold, rep_cold = dv.verify_pack(
        repo=repo, pack_path=pack_zip, work_parent=tmp_path, mutate_workers="2", mutate_cache_dir=ext_cache
    )
    rc_warm, rep_warm = dv.verify_pack(
        repo=repo, pack_path=pack_zip, work_parent=tmp_path, mutate_workers="2", mutate_cache_dir=ext_cache
    )
    assert rc_w1 == 0 and rc_cold == 0 and rc_warm == 0
    assert rep_w1["canonical_sha256"] == rep_cold["canonical_sha256"] == rep_warm["canonical_sha256"]
    assert rep_cold["mutation"]["cache"]["hit"] is False
    assert rep_warm["mutation"]["cache"]["hit"] is True
    assert rep_cold["mutation"]["cache"]["source_report_sha256"] == rep_warm["mutation"]["cache"]["source_report_sha256"]

    # 3. Precondition #1 + M4(a): full_run=False -> BLOCKING FAIL on existing diff_ast_mutate check, zero new check names
    stub_dir = tmp_path / "stub_partial_dv" / "scripts"
    stub_dir.mkdir(parents=True)
    stub_dv = stub_dir / "dso_verify.py"
    stub_dv.write_bytes(b"# stub verifier\n")
    stub_dam = stub_dir / "diff_ast_mutate.py"
    stub_dam.write_bytes((
        "import json, sys\n"
        "from pathlib import Path\n"
        "jout = Path(sys.argv[sys.argv.index('--json-out') + 1])\n"
        "jout.write_bytes(json.dumps({\n"
        "    'full_run': False, 'workers': 1,\n"
        "    'cache': {'enabled': False, 'hit': False, 'cache_key': None, 'source_report_sha256': None},\n"
        "    'summary': {'total': 1, 'caught': 1, 'caught_timeout': 0, 'survived': 0, 'accepted': 0, 'invalid': 0, 'exit_code': 0, 'verdict': 'PASS', 'reason': 'OK', 'full_run': False},\n"
        "    'mutants': [{'id': 'M-1', 'status': 'CAUGHT'}],\n"
        "    'stale_accepted': [], 'unnecessary_accepted': [], 'out_of_scope_accepted': [],\n"
        "}).encode('utf-8'))\n"
        "raise SystemExit(0)\n"
    ).encode("utf-8"))

    monkeypatch.setattr(dv, "__file__", str(stub_dv))
    rc_part, rep_part = dv.verify_pack(repo=repo, pack_path=pack_zip, work_parent=tmp_path)
    assert rc_part == dv.EXIT_BLOCKING and rep_part["overall_status"] == "BLOCKING"
    dam_chks = [c for c in rep_part["checks"] if c["name"] == "diff_ast_mutate"]
    assert len(dam_chks) == 1
    assert dam_chks[0]["status"] == "FAIL" and dam_chks[0]["reason_code"] == "PARTIAL_MUTATION_RUN_FORBIDDEN"


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
