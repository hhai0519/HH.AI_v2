# -*- coding: utf-8 -*-
"""Tests and E27 negative controls for scripts/diff_ast_mutate.py (TD-134)."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import bounded_process  # noqa: E402
import diff_ast_mutate as dam  # noqa: E402


def _init_git_repo(repo: Path, files: dict[str, bytes]) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "core.autocrlf", "false"], check=True)
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


def _pytest_cmd(test_rel: str = "") -> str:
    extra = f" {test_rel}" if test_rel else ""
    return f"{{python}} -m pytest -p no:cacheprovider -q -x{extra}"


# --- Fast Fail-Closed Exit-2 & JSON Schema v1 Contract Tests (placed first for -x) ---

def test_pure_stdlib_imports_only() -> None:
    src = (REPO_ROOT / "scripts" / "diff_ast_mutate.py").read_bytes().decode("utf-8")
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


def test_accept_file_invalid_variants_all_exit_2(tmp_path: Path) -> None:
    src = tmp_path / "m.py"
    src.write_bytes(b"def f(x: int) -> int:\n    return x + 1\n")
    bad_payloads = [
        b"{not json\n",
        b"[]\n",
        b'{"schema_version": 2, "accepted": []}\n',
        b'{"schema_version": 1, "accepted": {}}\n',
        b'{"schema_version": 1, "accepted": ["not-an-object"]}\n',
        b'{"schema_version": 1, "accepted": [{"id": "M-1"}]}\n',
        b'{"schema_version": 1, "accepted": [{"id": "M-dup", "reason": "a", "batch": "B1"}, {"id": "M-dup", "reason": "b", "batch": "B2"}]}\n',
    ]
    for idx, payload in enumerate(bad_payloads):
        acc = tmp_path / f"bad_acc_{idx}.json"
        rep = tmp_path / f"bad_rep_{idx}.json"
        acc.write_bytes(payload)
        rc = dam.main([
            "--repo", str(tmp_path), "--files", "m.py", "--list",
            "--accept", str(acc), "--json-out", str(rep), "--work-parent", str(tmp_path),
        ])
        assert rc == 2
        d = json.loads(rep.read_bytes())
        assert d["summary"]["verdict"] == "ERROR"
        assert d["summary"]["exit_code"] == 2
        assert d["summary"]["reason"] == "ACCEPT_FILE_INVALID"


def test_invalid_args_test_map_invalid_target_parse_and_git_patch_errors(tmp_path: Path) -> None:
    repo = tmp_path / "repo_err"
    base = _init_git_repo(repo, {"scripts/ok.py": b"def ok(x: int) -> int:\n    return x + 1\n"})
    (repo / "scripts/broken.py").write_bytes(b"def broken(:\n    pass\n")

    # 1. INVALID_ARGS: missing --test-cmd in run mode (must exit 2, mode=run)
    rep_nocmd = tmp_path / "nocmd.json"
    rc = dam.main(["--repo", str(repo), "--files", "scripts/ok.py", "--json-out", str(rep_nocmd), "--work-parent", str(tmp_path)])
    assert rc == 2
    d = json.loads(rep_nocmd.read_bytes())
    assert d["mode"] == "run" and d["summary"]["reason"] == "INVALID_ARGS"

    # 2. INVALID_ARGS: missing scope, negative --max-mutants, broken quote
    for idx, argv in enumerate([
        ["--repo", str(repo), "--list"],
        ["--repo", str(repo), "--files", "scripts/ok.py", "--list", "--max-mutants", "-1"],
        ["--repo", str(repo), "--files", "scripts/ok.py", "--test-cmd", '"unterminated'],
    ]):
        rp = tmp_path / f"inv_{idx}.json"
        assert dam.main([*argv, "--json-out", str(rp), "--work-parent", str(tmp_path)]) == 2
        assert json.loads(rp.read_bytes())["summary"]["reason"] == "INVALID_ARGS"

    # 3. TARGET_PARSE_ERROR
    rep_parse = tmp_path / "parse.json"
    assert dam.main(["--repo", str(repo), "--files", "scripts/broken.py", "--list", "--json-out", str(rep_parse)]) == 2
    assert json.loads(rep_parse.read_bytes())["summary"]["reason"] == "TARGET_PARSE_ERROR"

    # 4. GIT_ERROR
    rep_git = tmp_path / "git_err.json"
    assert dam.main(["--repo", str(repo), "--base", "nonexistent_ref_xyz", "--list", "--json-out", str(rep_git)]) == 2
    assert json.loads(rep_git.read_bytes())["summary"]["reason"] == "GIT_ERROR"

    # 5. PATCH_ERROR (missing file + unapplicable patch)
    rep_pm = tmp_path / "patch_missing.json"
    assert dam.main(["--repo", str(repo), "--patch", str(tmp_path / "no.patch"), "--list", "--json-out", str(rep_pm)]) == 2
    assert json.loads(rep_pm.read_bytes())["summary"]["reason"] == "PATCH_ERROR"

    bad_patch = tmp_path / "bad.patch"
    bad_patch.write_bytes(
        b"diff --git a/scripts/ok.py b/scripts/ok.py\n--- a/scripts/ok.py\n+++ b/scripts/ok.py\n"
        b"@@ -99,1 +99,1 @@\n-does not exist\n+nope\n"
    )
    rep_pb = tmp_path / "patch_bad.json"
    assert dam.main(["--repo", str(repo), "--patch", str(bad_patch), "--list", "--json-out", str(rep_pb)]) == 2
    assert json.loads(rep_pb.read_bytes())["summary"]["reason"] == "PATCH_ERROR"

    # 6. TEST_MAP_INVALID
    for idx, raw_tm in enumerate([
        b"{bad\n",
        b'{"schema_version": 2, "map": {}}\n',
        b'{"schema_version": 1, "map": {"scripts/ok.py": []}}\n',
        b'{"schema_version": 1, "map": {"scripts/ok.py": ["t.py"]}, "default": []}\n',
    ]):
        tm = tmp_path / f"tm_{idx}.json"
        rp = tmp_path / f"tm_rep_{idx}.json"
        tm.write_bytes(raw_tm)
        assert dam.main(["--repo", str(repo), "--files", "scripts/ok.py", "--list", "--test-map", str(tm), "--json-out", str(rp)]) == 2
        assert json.loads(rp.read_bytes())["summary"]["reason"] == "TEST_MAP_INVALID"


def test_list_and_run_mode_error_reports_and_cap_exact_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = tmp_path / "scripts/mod.py"
    mod.parent.mkdir(parents=True, exist_ok=True)
    mod.write_bytes(b"def f(x: int) -> int:\n    if x == 1:\n        return 2\n    return 3\n")
    muts, _, _ = dam.collect_mutants_for_file("scripts/mod.py", mod.read_bytes(), None)
    assert len(muts) >= 4

    # Exact boundary: max_mutants == len(muts) MUST pass (exit 0)
    rep_eq = tmp_path / "cap_eq.json"
    rc_eq = dam.main([
        "--repo", str(tmp_path), "--files", "scripts/mod.py", "--list",
        "--max-mutants", str(len(muts)), "--json-out", str(rep_eq), "--work-parent", str(tmp_path),
    ])
    assert rc_eq == 0
    assert json.loads(rep_eq.read_bytes())["summary"]["verdict"] == "PASS"

    # Exceeded by 1 in BOTH --list (mode=list) and run (mode=run)
    for list_flag, expected_mode in ((True, "list"), (False, "run")):
        rep_cap = tmp_path / f"cap_{expected_mode}.json"
        argv = ["--repo", str(tmp_path), "--files", "scripts/mod.py", "--max-mutants", str(len(muts) - 1), "--json-out", str(rep_cap), "--work-parent", str(tmp_path)]
        argv.append("--list" if list_flag else "--test-cmd")
        if not list_flag:
            argv.append("{python} -c pass")
        assert dam.main(argv) == 2
        d = json.loads(rep_cap.read_bytes())
        assert d["mode"] == expected_mode and d["summary"]["reason"] == "MUTANT_CAP_EXCEEDED"

    # ACCEPT_STALE_ENTRIES in BOTH --list (mode=list) and run (mode=run)
    stale = tmp_path / "stale.json"
    stale.write_bytes(json.dumps({"schema_version": 1, "accepted": [{"id": "M-deadbeef00", "reason": "r", "batch": "B"}]}).encode("utf-8"))
    for list_flag, expected_mode in ((True, "list"), (False, "run")):
        rep_st = tmp_path / f"stale_{expected_mode}.json"
        argv = ["--repo", str(tmp_path), "--files", "scripts/mod.py", "--accept", str(stale), "--json-out", str(rep_st), "--work-parent", str(tmp_path)]
        argv.append("--list" if list_flag else "--test-cmd")
        if not list_flag:
            argv.append("{python} -c pass")
        assert dam.main(argv) == 2
        d = json.loads(rep_st.read_bytes())
        assert d["mode"] == expected_mode and d["summary"]["reason"] == "ACCEPT_STALE_ENTRIES" and d["stale_accepted"] == ["M-deadbeef00"]

    # MUTANT_SYNTAX_INVALID in BOTH --list (mode=list) and run (mode=run)
    monkeypatch.setattr(dam, "collect_mutants_for_file", lambda _r, _b, _c: ([], 0, 1))
    for list_flag, expected_mode in ((True, "list"), (False, "run")):
        rep_inv = tmp_path / f"syn_{expected_mode}.json"
        argv = ["--repo", str(tmp_path), "--files", "scripts/mod.py", "--json-out", str(rep_inv), "--work-parent", str(tmp_path)]
        argv.append("--list" if list_flag else "--test-cmd")
        if not list_flag:
            argv.append("{python} -c pass")
        assert dam.main(argv) == 2
        d = json.loads(rep_inv.read_bytes())
        assert d["mode"] == expected_mode and d["summary"]["reason"] == "MUTANT_SYNTAX_INVALID" and d["summary"]["invalid"] == 1


def test_pass_no_mutants_skips_baseline_and_exits_0(tmp_path: Path) -> None:
    repo = tmp_path / "repo_nomut"
    base = _init_git_repo(repo, {"scripts/only_comment.py": b"# old\n"})
    (repo / "scripts/only_comment.py").write_bytes(b"# new comment only\n")
    rep_p = tmp_path / "nomut.json"
    # Deliberately failing --test-cmd proves baseline is skipped when total == 0
    rc = dam.main([
        "--repo", str(repo), "--base", base,
        "--test-cmd", '{python} -c "import sys; sys.exit(9)"',
        "--json-out", str(rep_p), "--work-parent", str(tmp_path),
    ])
    assert rc == 0
    d = json.loads(rep_p.read_bytes())
    assert d["summary"]["total"] == 0
    assert d["summary"]["exit_code"] == 0
    assert d["summary"]["verdict"] == "PASS_NO_MUTANTS"
    assert d["summary"]["reason"] == "NO_MUTANTS"
    assert d["baseline"]["executed"] is False


def test_monkeypatched_timeouts_restore_launch_accept_and_summary_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src_bytes = b"def f(x: int) -> bool:\n    return x == 1\n"
    (tmp_path / "scripts").mkdir(exist_ok=True)
    (tmp_path / "scripts/f.py").write_bytes(src_bytes)
    muts, _, _ = dam.collect_mutants_for_file("scripts/f.py", src_bytes, None)
    assert len(muts) == 3

    def _fake_iso(*a, **kw) -> Path:
        d = tmp_path / "iso"
        (d / "scripts").mkdir(parents=True, exist_ok=True)
        (d / "scripts/f.py").write_bytes(src_bytes)
        return d

    monkeypatch.setattr(dam, "prepare_isolated_copy", _fake_iso)

    # 1. RESTORE_FAILED (exit 2)
    orig_sha = dam._sha256_bytes
    calls = {"sha": 0}

    def bad_restore_sha(b: bytes) -> str:
        calls["sha"] += 1
        return ("a" * 64) if calls["sha"] <= 2 else ("b" * 64)

    monkeypatch.setattr(dam, "_sha256_bytes", bad_restore_sha)
    monkeypatch.setattr(
        dam.bounded_process,
        "run_bounded",
        lambda *a, **kw: bounded_process.BoundedResult(0, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED),
    )
    rep_res = tmp_path / "restore.json"
    assert dam.main([
        "--repo", str(tmp_path), "--files", "scripts/f.py",
        "--test-cmd", "dummy", "--json-out", str(rep_res), "--work-parent", str(tmp_path),
    ]) == 2
    assert json.loads(rep_res.read_bytes())["summary"]["reason"] == "RESTORE_FAILED"
    monkeypatch.setattr(dam, "_sha256_bytes", orig_sha)

    # 2. TEST_LAUNCH_ERROR on mutant (exit 2)
    launch_n = {"i": 0}

    def launch_err_run(*a, **kw):
        launch_n["i"] += 1
        if launch_n["i"] == 1:
            return bounded_process.BoundedResult(0, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED)
        return bounded_process.BoundedResult(None, False, "FileNotFoundError", b"", b"", bounded_process.KILL_NOT_NEEDED)

    monkeypatch.setattr(dam.bounded_process, "run_bounded", launch_err_run)
    rep_launch = tmp_path / "launch.json"
    assert dam.main([
        "--repo", str(tmp_path), "--files", "scripts/f.py",
        "--test-cmd", "dummy", "--json-out", str(rep_launch), "--work-parent", str(tmp_path),
    ]) == 2
    d_launch = json.loads(rep_launch.read_bytes())
    assert d_launch["summary"]["reason"] == "TEST_LAUNCH_ERROR" and d_launch["summary"]["caught"] == 0

    # 3. TOTAL_TIMEOUT_EXCEEDED (> vs == boundary)
    ticks = iter([100.0, 100.1, 100.2, 105.0])  # run_start=100, t0=100.1, b_end=100.2, mut0=105.0 (> 4.0)
    monkeypatch.setattr(dam.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(
        dam.bounded_process,
        "run_bounded",
        lambda *a, **kw: bounded_process.BoundedResult(0, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED),
    )
    rep_to = tmp_path / "tt_over.json"
    assert dam.main([
        "--repo", str(tmp_path), "--files", "scripts/f.py",
        "--test-cmd", "dummy", "--total-timeout", "4.0", "--json-out", str(rep_to), "--work-parent", str(tmp_path),
    ]) == 2
    d_to = json.loads(rep_to.read_bytes())
    assert d_to["summary"]["reason"] == "TOTAL_TIMEOUT_EXCEEDED"
    assert all(m["status"] == "NOT_RUN" for m in d_to["mutants"])

    # Exact boundary: elapsed == total_timeout (104.0 - 100.0 == 4.0) MUST NOT trip total timeout
    eq_ticks = iter([100.0, 100.1, 100.2] + [104.0] * 40)
    monkeypatch.setattr(dam.time, "monotonic", lambda: next(eq_ticks))
    seq_i = {"i": 0}

    def all_caught_run(*a, **kw):
        seq_i["i"] += 1
        rc = 0 if seq_i["i"] == 1 else 1
        return bounded_process.BoundedResult(rc, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED)

    monkeypatch.setattr(dam.bounded_process, "run_bounded", all_caught_run)
    rep_eq = tmp_path / "tt_eq.json"
    assert dam.main([
        "--repo", str(tmp_path), "--files", "scripts/f.py",
        "--test-cmd", "dummy", "--total-timeout", "4.0", "--json-out", str(rep_eq), "--work-parent", str(tmp_path),
    ]) == 0
    d_eq = json.loads(rep_eq.read_bytes())
    assert d_eq["summary"]["verdict"] == "PASS" and d_eq["summary"]["reason"] == "OK" and d_eq["summary"]["caught"] == 3

    # 4. --test-map per-mutant argv + unnecessary_accepted + accept_reason/accept_batch + summary counts
    acc_p = tmp_path / "acc3.json"
    acc_p.write_bytes(json.dumps({
        "schema_version": 1,
        "accepted": [
            {"id": muts[0].id, "reason": "r0", "batch": "B0"},
            {"id": muts[1].id, "reason": "r1", "batch": "B1"},
            {"id": muts[2].id, "reason": "r2", "batch": "B2"},
        ],
    }).encode("utf-8"))
    tmap_p = tmp_path / "tmap3.json"
    tmap_p.write_bytes(json.dumps({
        "schema_version": 1,
        "map": {"scripts/f.py": ["scripts/tests/test_f_only.py"]},
    }).encode("utf-8"))

    recorded_cmds: list[list[str]] = []

    def mixed_run(cmd, *a, **kw):
        recorded_cmds.append(list(cmd))
        n = len(recorded_cmds)
        if n == 1:
            return bounded_process.BoundedResult(0, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED)
        if n == 2:
            return bounded_process.BoundedResult(None, True, None, b"", b"", bounded_process.KILL_TREE_SIGNALLED)
        if n == 3:
            return bounded_process.BoundedResult(1, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED)
        return bounded_process.BoundedResult(0, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED)

    eq_ticks2 = iter([100.0 + i * 0.1 for i in range(40)])
    monkeypatch.setattr(dam.time, "monotonic", lambda: next(eq_ticks2))
    monkeypatch.setattr(dam.bounded_process, "run_bounded", mixed_run)
    rep_mix = tmp_path / "mix.json"
    rc_mix = dam.main([
        "--repo", str(tmp_path), "--files", "scripts/f.py",
        "--test-cmd", "dummy_runner", "--test-map", str(tmap_p), "--accept", str(acc_p),
        "--json-out", str(rep_mix), "--work-parent", str(tmp_path),
    ])
    assert rc_mix == 0
    assert all(cmd[-1] == "scripts/tests/test_f_only.py" for cmd in recorded_cmds)
    d_mix = json.loads(rep_mix.read_bytes())
    sm = d_mix["summary"]
    assert sm["total"] == 3 and sm["caught"] == 1 and sm["caught_timeout"] == 1 and sm["accepted"] == 1 and sm["survived"] == 0
    assert sm["unnecessary_accepted_count"] == 2
    assert sm["exit_code"] == 0 and sm["verdict"] == "PASS" and sm["reason"] == "OK"
    assert sorted(d_mix["unnecessary_accepted"]) == sorted([muts[0].id, muts[1].id])
    by_id = {m["id"]: m for m in d_mix["mutants"]}
    assert by_id[muts[0].id]["status"] == "CAUGHT_TIMEOUT" and by_id[muts[0].id]["accept_reason"] is None and by_id[muts[0].id]["accept_batch"] is None
    assert by_id[muts[1].id]["status"] == "CAUGHT" and by_id[muts[1].id]["accept_reason"] is None and by_id[muts[1].id]["accept_batch"] is None
    assert by_id[muts[2].id]["status"] == "ACCEPTED" and by_id[muts[2].id]["accept_reason"] == "r2" and by_id[muts[2].id]["accept_batch"] == "B2"

    # 5. FAIL summary contract when survived > 0
    seq_fail = {"i": 0}

    def all_survived_run(*a, **kw):
        seq_fail["i"] += 1
        return bounded_process.BoundedResult(0, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED)

    eq_ticks3 = iter([100.0 + i * 0.1 for i in range(40)])
    monkeypatch.setattr(dam.time, "monotonic", lambda: next(eq_ticks3))
    monkeypatch.setattr(dam.bounded_process, "run_bounded", all_survived_run)
    rep_fail = tmp_path / "fail_sum.json"
    assert dam.main([
        "--repo", str(tmp_path), "--files", "scripts/f.py",
        "--test-cmd", "dummy", "--json-out", str(rep_fail), "--work-parent", str(tmp_path),
    ]) == 1
    df = json.loads(rep_fail.read_bytes())["summary"]
    assert df["survived"] == 3 and df["exit_code"] == 1 and df["verdict"] == "FAIL" and df["reason"] == "MUTANTS_SURVIVED"


# --- All 14 Operators & Noise Filters ---

def test_all_14_operators_collected_and_valid() -> None:
    code = (
        '"""Module docstring ignored."""\n'
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    X: int = 1\n"
        "def f(a: int, b: int, items: list[int], flag: bool) -> int:\n"
        '    """Function docstring ignored."""\n'
        "    if a == 0:\n"
        "        return 1\n"
        "    if a < 5:\n"
        "        a += 2\n"
        "    if a in items and (flag is True or not flag):\n"
        "        items.append(a + 3)\n"
        "    if flag:\n"
        '        print("noise" + str(a))\n'
        "    while False:\n"
        "        break\n"
        "    res = a if flag else 0\n"
        "    return res\n"
        'if __name__ == "__main__":\n'
        "    f(1, 2, [], False)\n"
    ).encode("utf-8")
    muts, skipped, invalid = dam.collect_mutants_for_file("scripts/mod.py", code, None)
    assert invalid == 0
    assert skipped >= 4  # 2 docstrings + TYPE_CHECKING + print + __main__
    ops_seen = {m.op for m in muts}
    expected_ops = {
        "CMP_EQ_NE",
        "CMP_BOUNDARY",
        "CMP_IN_NOTIN",
        "CMP_IS_ISNOT",
        "BOOL_AND_OR",
        "BOOL_DROP_OPERAND",
        "UNARY_DROP_NOT",
        "IF_COND_FALSE",
        "IF_NEGATE_COND",
        "CONST_BOOL_FLIP",
        "CONST_INT_DELTA",
        "RET_NONE_OR_EMPTY",
        "AUG_OR_BIN_ARITH",
        "STMT_CALL_DELETE",
    }
    assert ops_seen == expected_ops
    assert all(m.id.startswith("M-") and len(m.id) == 12 for m in muts)
    assert all("::" in m.display_id and "#" in m.display_id for m in muts)
    # Never mutate while False -> True
    while_muts = [m for m in muts if m.lineno == 15]
    assert while_muts == []


def test_raise_and_logging_args_and_string_concat_skipped() -> None:
    code = (
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def g(x: int) -> str:\n"
        "    if x == 0:\n"
        '        raise ValueError("bad value " + str(1 == 1))\n'
        '    logger.info("val=%s", x + 1)\n'
        '    return "a" + "b"\n'
    ).encode("utf-8")
    muts, skipped, invalid = dam.collect_mutants_for_file("scripts/g.py", code, None)
    assert invalid == 0
    assert skipped >= 2  # raise + logger.info
    assert not any(m.op == "AUG_OR_BIN_ARITH" for m in muts)
    assert not any(m.lineno == 5 for m in muts)
    assert not any(m.lineno == 6 for m in muts)


def test_unchanged_outer_if_not_mutated_when_only_body_changed(tmp_path: Path) -> None:
    repo = tmp_path / "repo_scope"
    v1 = (
        "def h(x: int, y: int) -> int:\n"
        "    if x > 10:\n"
        "        return y + 1\n"
        "    return 0\n"
    ).encode("utf-8")
    base = _init_git_repo(repo, {
        "scripts/h.py": v1,
        "scripts/tests/test_h.py": b"from scripts.h import h\ndef test_h():\n    assert h(20, 3) == 4\n",
    })
    v2 = (
        "def h(x: int, y: int) -> int:\n"
        "    if x > 10:\n"
        "        return y + 2\n"
        "    return 0\n"
    ).encode("utf-8")
    (repo / "scripts/h.py").write_bytes(v2)
    rc, rep = dam.execute_mutation_run(
        repo=repo,
        scope_kind="git_diff",
        base_ref=base,
        list_only=True,
        work_parent=tmp_path,
    )
    assert rc == 0
    assert rep["summary"]["total"] > 0
    assert all(m["lineno"] == 3 for m in rep["mutants"])


# --- End-to-End Subprocess Controls & Windows Form ---

def test_boundary_survived_exits_1_and_killed_exits_0(tmp_path: Path) -> None:
    repo2 = tmp_path / "repo_surv2"
    base2 = _init_git_repo(repo2, {
        "scripts/b2.py": b"def check(x: int) -> bool:\n    return False\n",
        "scripts/tests/test_b2.py": b"from scripts.b2 import check\ndef test_check():\n    assert check(10) is True\n    assert check(1) is False\n",
    })
    (repo2 / "scripts/b2.py").write_bytes(b"def check(x: int) -> bool:\n    return x >= 5\n")
    rep_surv = tmp_path / "surv.json"
    rc_surv = dam.main([
        "--repo", str(repo2), "--base", base2,
        "--test-cmd", _pytest_cmd("scripts/tests/test_b2.py"),
        "--json-out", str(rep_surv),
        "--work-parent", str(tmp_path),
    ])
    assert rc_surv == 1
    data = json.loads(rep_surv.read_bytes())
    assert data["summary"]["exit_code"] == 1
    assert data["summary"]["verdict"] == "FAIL"
    assert data["summary"]["reason"] == "MUTANTS_SURVIVED"
    assert data["summary"]["survived"] >= 1
    assert any(m["op"] == "CMP_BOUNDARY" and m["status"] == "SURVIVED" for m in data["mutants"])

    (repo2 / "scripts/tests/test_b2.py").write_bytes(
        b"from scripts.b2 import check\ndef test_check():\n    assert check(10) is True\n    assert check(5) is True\n    assert check(4) is False\n"
    )
    rep_pass = tmp_path / "pass.json"
    rc_pass = dam.main([
        "--repo", str(repo2), "--base", base2,
        "--test-cmd", _pytest_cmd("scripts/tests/test_b2.py"),
        "--json-out", str(rep_pass),
        "--work-parent", str(tmp_path),
    ])
    assert rc_pass == 0
    dp = json.loads(rep_pass.read_bytes())
    assert dp["summary"]["exit_code"] == 0
    assert dp["summary"]["verdict"] == "PASS"
    assert dp["summary"]["reason"] == "OK"
    assert dp["summary"]["survived"] == 0 and dp["summary"]["caught"] == dp["summary"]["total"]


def test_infinite_loop_mutant_caught_timeout(tmp_path: Path) -> None:
    repo2 = tmp_path / "repo_to2"
    base2 = _init_git_repo(repo2, {
        "scripts/cnt.py": b"def countdown(n: int) -> int:\n    return 0\n",
        "scripts/tests/test_cnt.py": b"from scripts.cnt import countdown\ndef test_cnt():\n    assert countdown(2) == 0\n",
    })
    (repo2 / "scripts/cnt.py").write_bytes(
        b"def countdown(n: int) -> int:\n    while n > 0:\n        n -= 1\n    return n\n"
    )
    rep_p2 = tmp_path / "to2.json"
    rc = dam.main([
        "--repo", str(repo2), "--base", base2,
        "--test-cmd", _pytest_cmd("scripts/tests/test_cnt.py"),
        "--per-mutant-timeout", "2.0",
        "--json-out", str(rep_p2),
        "--work-parent", str(tmp_path),
    ])
    assert rc == 0
    d2 = json.loads(rep_p2.read_bytes())
    assert d2["baseline"]["rc"] == 0
    assert d2["summary"]["caught_timeout"] >= 1
    assert any(m["op"] == "AUG_OR_BIN_ARITH" and m["status"] == "CAUGHT_TIMEOUT" for m in d2["mutants"])


def test_mutant_cap_exceeded_fails_closed(tmp_path: Path) -> None:
    repo = tmp_path / "repo_cap"
    base = _init_git_repo(repo, {
        "scripts/cap.py": b"def c(x: int) -> int:\n    return 0\n",
    })
    (repo / "scripts/cap.py").write_bytes(
        b"def c(x: int) -> int:\n    if x == 1 or x == 2:\n        return x + 3\n    return 0\n"
    )
    rep_p = tmp_path / "cap.json"
    rc = dam.main([
        "--repo", str(repo), "--base", base,
        "--list", "--max-mutants", "2",
        "--json-out", str(rep_p),
        "--work-parent", str(tmp_path),
    ])
    assert rc == 2
    data = json.loads(rep_p.read_bytes())
    assert data["summary"]["reason"] == "MUTANT_CAP_EXCEEDED"
    assert data["summary"]["total"] > 2


def test_caller_repo_untouched_and_temp_cleaned(tmp_path: Path) -> None:
    repo = tmp_path / "repo_clean"
    base = _init_git_repo(repo, {
        "scripts/u.py": b"def u(x: int) -> int:\n    return 0\n",
        "scripts/tests/test_u.py": b"from scripts.u import u\ndef test_u():\n    assert u(3) == 4\n",
    })
    src = b"def u(x: int) -> int:\n    return x + 1\n"
    (repo / "scripts/u.py").write_bytes(src)
    wp = tmp_path / "work_iso"
    wp.mkdir()
    before_status = subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True)
    rc = dam.main([
        "--repo", str(repo), "--base", base,
        "--test-cmd", _pytest_cmd("scripts/tests/test_u.py"),
        "--work-parent", str(wp),
    ])
    assert rc == 0
    after_status = subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True)
    assert after_status == before_status
    assert (repo / "scripts/u.py").read_bytes() == src
    assert list(wp.iterdir()) == []


def test_windows_patch_crlf_and_backslash_files_deterministic(tmp_path: Path) -> None:
    repo = tmp_path / "repo_win"
    _init_git_repo(repo, {
        "scripts/w.py": b"def w(a: int) -> bool:\n    return False\n",
    })
    patch = tmp_path / "win.patch"
    patch.write_bytes(
        b"diff --git a/scripts/w.py b/scripts/w.py\n"
        b"--- a/scripts/w.py\n"
        b"+++ b/scripts/w.py\n"
        b"@@ -1,2 +1,2 @@\n"
        b" def w(a: int) -> bool:\n"
        b"-    return False\n"
        b"+    return a == 7\n"
    )
    out1 = tmp_path / "l1.json"
    out2 = tmp_path / "l2.json"
    rc1 = dam.main(["--repo", str(repo), "--patch", str(patch), "--list", "--json-out", str(out1)])
    (repo / "scripts/w.py").write_bytes(b"def w(a: int) -> bool:\n    return a == 7\n")
    rc2 = dam.main(["--repo", str(repo), "--files", "scripts\\w.py", "--list", "--json-out", str(out2)])
    assert rc1 == 0 and rc2 == 0
    d1 = json.loads(out1.read_bytes())
    d2 = json.loads(out2.read_bytes())
    assert d1["schema_version"] == 1 and d1["tool"] == "diff_ast_mutate.py"
    assert [m["id"] for m in d1["mutants"]] == [m["id"] for m in d2["mutants"]]

    crlf_py = repo / "scripts/crlf_mod.py"
    crlf_py.write_bytes(b"def cr(x: int) -> int:\r\n    return x + 1\r\n")
    out3 = tmp_path / "l3.json"
    rc3 = dam.main(["--repo", str(repo), "--files", "scripts\\crlf_mod.py", "--list", "--json-out", str(out3)])
    assert rc3 == 0
    assert json.loads(out3.read_bytes())["summary"]["total"] >= 2


# --- Second Opinion Suggestion #5: 4 Required Negative Controls ---

def test_so_neg1_single_condition_guard_untested_caught_by_if_cond_false(tmp_path: Path) -> None:
    repo = tmp_path / "repo_guard"
    base = _init_git_repo(repo, {
        "scripts/guard.py": b"def validate(x: int) -> int:\n    return x\n",
        "scripts/tests/test_guard.py": b"from scripts.guard import validate\ndef test_ok():\n    assert validate(5) == 5\n",
    })
    (repo / "scripts/guard.py").write_bytes(
        b"def validate(x: int) -> int:\n"
        b"    if x == 0:\n"
        b'        raise ValueError("zero")\n'
        b"    return x\n"
    )
    rep_p = tmp_path / "guard.json"
    rc = dam.main([
        "--repo", str(repo), "--base", base,
        "--test-cmd", _pytest_cmd("scripts/tests/test_guard.py"),
        "--json-out", str(rep_p),
        "--work-parent", str(tmp_path),
    ])
    assert rc == 1
    data = json.loads(rep_p.read_bytes())
    assert any(m["op"] == "IF_COND_FALSE" and m["status"] == "SURVIVED" for m in data["mutants"])


def test_so_neg2_accept_exemption_valid_and_stale_fail_closed(tmp_path: Path) -> None:
    repo = tmp_path / "repo_acc"
    base = _init_git_repo(repo, {
        "scripts/acc.py": b"def f(x: int) -> int:\n    return 0\n",
        "scripts/tests/test_acc.py": (
            b"from scripts.acc import f\n"
            b"def test_f():\n"
            b"    assert f(10) == 10\n"
            b"    assert f(4) == 4\n"
        ),
    })
    (repo / "scripts/acc.py").write_bytes(
        b"def f(x: int) -> int:\n"
        b"    if x >= 5:\n"
        b"        return x\n"
        b"    return x\n"
    )
    list_p = tmp_path / "acc_list.json"
    assert dam.main(["--repo", str(repo), "--base", base, "--list", "--json-out", str(list_p)]) == 0
    muts = json.loads(list_p.read_bytes())["mutants"]
    acc_p = tmp_path / "accept.json"
    acc_doc = {
        "schema_version": 1,
        "accepted": [
            {"id": m["id"], "reason": "Equivalent for test", "batch": "B117-TD134-DIFF-AST-MUTATE-R2-261125"}
            for m in muts
        ],
    }
    acc_p.write_bytes((json.dumps(acc_doc, indent=2) + "\n").encode("utf-8"))
    run_p = tmp_path / "acc_run.json"
    rc = dam.main([
        "--repo", str(repo), "--base", base,
        "--test-cmd", _pytest_cmd("scripts/tests/test_acc.py"),
        "--accept", str(acc_p),
        "--json-out", str(run_p),
        "--work-parent", str(tmp_path),
    ])
    assert rc == 0
    d = json.loads(run_p.read_bytes())
    assert d["summary"]["survived"] == 0
    assert d["summary"]["accepted"] >= 1
    assert d["summary"]["caught"] >= 1
    assert d["summary"]["unnecessary_accepted_count"] == d["summary"]["caught"]
    acc_recs = [m for m in d["mutants"] if m["status"] == "ACCEPTED"]
    assert acc_recs and all(m["accept_reason"] == "Equivalent for test" and m["accept_batch"] == "B117-TD134-DIFF-AST-MUTATE-R2-261125" for m in acc_recs)

    stale_p = tmp_path / "stale_accept.json"
    stale_p.write_bytes((json.dumps({
        "schema_version": 1,
        "accepted": [{"id": "M-deadbeef00", "reason": "Old id", "batch": "B117-OLD"}],
    }) + "\n").encode("utf-8"))
    stale_rep = tmp_path / "stale_rep.json"
    rc_stale = dam.main([
        "--repo", str(repo), "--base", base, "--list",
        "--accept", str(stale_p), "--json-out", str(stale_rep),
    ])
    assert rc_stale == 2
    assert json.loads(stale_rep.read_bytes())["summary"]["reason"] == "ACCEPT_STALE_ENTRIES"


def test_so_neg3_offset_free_id_unchanged_after_unrelated_lines_inserted(tmp_path: Path) -> None:
    fn_src = (
        "def target_fn(val: int) -> int:\n"
        "    if val == 0:\n"
        "        return 1\n"
        "    return val + 2\n"
    )
    v1 = ("def helper_before() -> int:\n    return 0\n\n" + fn_src).encode("utf-8")
    v2 = (
        "# Added header comment\n\n\n"
        "def another_helper(z: int) -> int:\n"
        "    if z == 0:\n"
        "        return 9\n"
        "    return z\n\n\n"
        + fn_src
    ).encode("utf-8")
    m1, _, _ = dam.collect_mutants_for_file("scripts/stable.py", v1, None)
    m2, _, _ = dam.collect_mutants_for_file("scripts/stable.py", v2, None)
    id1 = [(m.display_id, m.id) for m in m1 if m.qualname == "target_fn"]
    id2 = [(m.display_id, m.id) for m in m2 if m.qualname == "target_fn"]
    assert len(id1) >= 4
    assert id1 == id2


def test_so_neg4_missing_git_fails_baseline_exit_2_whereas_preserved_git_passes(tmp_path: Path) -> None:
    repo = tmp_path / "repo_git"
    test_body = (
        b"import subprocess\n"
        b"from pathlib import Path\n"
        b"from scripts.gmod import check_pos\n"
        b"def test_git_and_logic():\n"
        b"    rc = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(Path(__file__).resolve().parents[2])).returncode\n"
        b"    assert rc == 0\n"
        b"    assert check_pos(1) is True\n"
        b"    assert check_pos(0) is False\n"
    )
    base = _init_git_repo(repo, {
        "scripts/gmod.py": b"def check_pos(x: int) -> bool:\n    return False\n",
        "scripts/tests/test_gmod.py": test_body,
    })
    (repo / "scripts/gmod.py").write_bytes(b"def check_pos(x: int) -> bool:\n    return x > 0\n")

    rc_ok, rep_ok = dam.execute_mutation_run(
        repo=repo,
        scope_kind="git_diff",
        base_ref=base,
        test_cmd=_pytest_cmd("scripts/tests/test_gmod.py"),
        work_parent=tmp_path,
        preserve_git=True,
    )
    assert rep_ok["baseline"]["rc"] == 0
    assert rep_ok["summary"]["total"] >= 1
    assert rc_ok == 0

    rc_nogit, rep_nogit = dam.execute_mutation_run(
        repo=repo,
        scope_kind="git_diff",
        base_ref=base,
        test_cmd=_pytest_cmd("scripts/tests/test_gmod.py"),
        work_parent=tmp_path,
        preserve_git=False,
    )
    assert rc_nogit == 2
    assert rep_nogit["summary"]["verdict"] == "ERROR"
    assert rep_nogit["summary"]["exit_code"] == 2
    assert rep_nogit["summary"]["reason"] == "BASELINE_FAILED"
    assert rep_nogit["summary"]["caught"] == 0
    assert all(m["status"] == "NOT_RUN" for m in rep_nogit["mutants"])


# --- --test-map Routing & Fallback ---

def test_test_map_routing_and_unmapped_fail_closed(tmp_path: Path) -> None:
    repo = tmp_path / "repo_map"
    base = _init_git_repo(repo, {
        "scripts/m1.py": b"def m1(x: int) -> bool:\n    return False\n",
        "scripts/tests/test_m1.py": b"from scripts.m1 import m1\ndef test_m1():\n    assert m1(1) is True\n    assert m1(0) is False\n",
        "scripts/tests/test_fail.py": b"def test_bad():\n    assert False\n",
    })
    (repo / "scripts/m1.py").write_bytes(b"def m1(x: int) -> bool:\n    return x > 0\n")
    tmap = tmp_path / "tmap.json"
    tmap.write_bytes((json.dumps({
        "schema_version": 1,
        "map": {"scripts/m1.py": ["scripts/tests/test_m1.py"]},
    }) + "\n").encode("utf-8"))
    rc = dam.main([
        "--repo", str(repo), "--base", base,
        "--test-cmd", _pytest_cmd(),
        "--test-map", str(tmap),
        "--work-parent", str(tmp_path),
    ])
    assert rc == 0

    tmap2 = tmp_path / "tmap2.json"
    tmap2.write_bytes((json.dumps({"schema_version": 1, "map": {"scripts/other.py": ["scripts/tests/test_m1.py"]}}) + "\n").encode("utf-8"))
    rep_unm = tmp_path / "unm.json"
    rc_unm = dam.main([
        "--repo", str(repo), "--base", base,
        "--test-cmd", _pytest_cmd(),
        "--test-map", str(tmap2),
        "--json-out", str(rep_unm),
        "--work-parent", str(tmp_path),
    ])
    assert rc_unm == 2
    assert json.loads(rep_unm.read_bytes())["summary"]["reason"] == "TEST_MAP_UNMAPPED"

    tmap3 = tmp_path / "tmap3.json"
    tmap3.write_bytes((json.dumps({
        "schema_version": 1,
        "map": {"scripts/other.py": ["scripts/tests/test_fail.py"]},
        "default": ["scripts/tests/test_m1.py"],
    }) + "\n").encode("utf-8"))
    rc_def = dam.main([
        "--repo", str(repo), "--base", base,
        "--test-cmd", _pytest_cmd(),
        "--test-map", str(tmap3),
        "--work-parent", str(tmp_path),
    ])
    assert rc_def == 0
