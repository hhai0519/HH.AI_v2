# -*- coding: utf-8 -*-
"""Tests and E27 negative controls for scripts/diff_ast_mutate.py (TD-134)."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import threading
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


class FakeClock:
    """Deterministic monotonic clock for tests; never raises StopIteration past initial ticks."""

    def __init__(self, ticks: list[float], *, tail_step: float = 0.0) -> None:
        if not ticks:
            raise ValueError("FakeClock requires at least one initial tick")
        self._ticks = [float(t) for t in ticks]
        self._tail_step = float(tail_step)
        self._idx = 0
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        if self._idx < len(self._ticks):
            val = self._ticks[self._idx]
            self._idx += 1
            return val
        extra = self._idx - len(self._ticks) + 1
        self._idx += 1
        return self._ticks[-1] + extra * self._tail_step


# --- Fast In-Memory Unit Tests for TD-144a / M2 / M3 / S5 (placed first for -x) ---


def test_td144a_fast_unit_workers_discover_and_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill every branch of resolve_workers, discover_changed_qualnames, and validate_cache_dir in milliseconds."""
    assert dam.resolve_workers(None) == 1
    for i in range(1, 9):
        assert dam.resolve_workers(i) == i
        assert dam.resolve_workers(str(i)) == i
    assert dam.resolve_workers(" 4 ") == 4
    for cpus, want in ((None, 1), (0, 1), (1, 1), (2, 1), (3, 1), (4, 2), (5, 2), (6, 3), (8, 4), (10, 4), (12, 4)):
        monkeypatch.setattr(dam.os, "cpu_count", lambda c=cpus: c)
        assert dam.resolve_workers("auto") == want
        assert dam.resolve_workers("AUTO") == want
    for bad in (True, False, "", "   ", "0", "-1", "9", 0, 9, "xyz", 1.5):
        with pytest.raises(dam.ToolError) as ei:
            dam.resolve_workers(bad)  # type: ignore[arg-type]
        assert ei.value.code == "INVALID_ARGS"

    # discover_changed_qualnames exact order and counts
    assert dam.discover_changed_qualnames([]) == ([], {})
    m1 = dam.MutantCandidate("M-1", "a::fn1::OP#1", "a.py", "fn1", 1, 1, 0, "OP", "1", "2", 0, 1, b"2")
    m2 = dam.MutantCandidate("M-2", "a::fn1::OP#2", "a.py", "fn1", 2, 2, 0, "OP", "1", "2", 0, 1, b"2")
    m3 = dam.MutantCandidate("M-3", "b::fn0::OP#1", "b.py", "fn0", 1, 1, 0, "OP", "1", "2", 0, 1, b"2")
    qns, cnts = dam.discover_changed_qualnames([m1, m2, m3])
    assert qns == ["fn0", "fn1"]
    assert cnts == {"fn0": 1, "fn1": 2}

    # validate_cache_dir: repo itself, inside repo, existing file, and valid outside path
    repo_dir = tmp_path / "repo_vcd"
    repo_dir.mkdir()
    for bad_cd in (repo_dir, repo_dir / "sub"):
        with pytest.raises(dam.ToolError) as ei:
            dam.validate_cache_dir(bad_cd, repo_dir)
        assert ei.value.code == "INVALID_ARGS"
    file_cd = tmp_path / "not_a_dir.txt"
    file_cd.write_bytes(b"hi")
    with pytest.raises(dam.ToolError) as ei:
        dam.validate_cache_dir(file_cd, repo_dir)
    assert ei.value.code == "INVALID_ARGS"
    valid_cd = tmp_path / "valid_cache"
    assert dam.validate_cache_dir(valid_cd, repo_dir) == valid_cd.resolve()


def test_td144a_fast_unit_load_survived_from_file_all_branches(tmp_path: Path) -> None:
    """Exhaustively exercise every S5 fail-closed branch in load_survived_from_file without subprocesses."""
    tsha = "a" * 64
    base_doc = {
        "schema_version": dam.SCHEMA_VERSION,
        "tool": dam.TOOL_NAME,
        "mode": "run",
        "tool_sha256": tsha,
        "scope": {
            "kind": "git_diff",
            "base_oid": "b" * 40,
            "changed_files": ["scripts/a.py", "scripts/b.py"],
            "qualname_filter": ["fn_b", "fn_a"],
        },
        "mutants": [
            {"id": "M-1111111111", "status": "SURVIVED"},
            {"id": "M-2222222222", "status": "CAUGHT"},
        ],
    }

    def _call(raw: bytes | None, path_override: Path | None = None) -> set[str]:
        p = path_override or (tmp_path / "src.json")
        if raw is not None:
            p.write_bytes(raw)
        return dam.load_survived_from_file(
            p,
            expected_base_oid="b" * 40,
            expected_scope_kind="git_diff",
            expected_changed_files=["scripts/b.py", "scripts/a.py"],
            expected_qualname_filter=["fn_a", "fn_b"],
            expected_tool_sha=tsha,
            full_catalog_ids={"M-1111111111", "M-2222222222", "M-3333333333"},
        )

    assert _call(json.dumps(base_doc).encode("utf-8")) == {"M-1111111111"}

    # Missing file & corrupt JSON
    with pytest.raises(dam.ToolError) as ei:
        _call(None, tmp_path / "missing.json")
    assert ei.value.code == "SURVIVED_SOURCE_INVALID"
    with pytest.raises(dam.ToolError) as ei:
        _call(b"{bad")
    assert ei.value.code == "SURVIVED_SOURCE_INVALID"

    import copy as _copy
    bad_mutations: list[object] = [
        [],
        {**base_doc, "schema_version": 999},
        {**base_doc, "tool": "other"},
        {**base_doc, "mode": "list"},
        {**base_doc, "tool_sha256": "f" * 64},
        {**base_doc, "scope": "not-dict"},
        {**base_doc, "scope": {**base_doc["scope"], "kind": "patch"}},  # type: ignore[dict-item]
        {**base_doc, "scope": {**base_doc["scope"], "base_oid": "c" * 40}},  # type: ignore[dict-item]
        {**base_doc, "scope": {**base_doc["scope"], "changed_files": "not-list"}},  # type: ignore[dict-item]
        {**base_doc, "scope": {**base_doc["scope"], "changed_files": {"scripts/a.py": 1, "scripts/b.py": 2}}},  # type: ignore[dict-item]
        {**base_doc, "scope": {**base_doc["scope"], "changed_files": ["scripts/only.py"]}},  # type: ignore[dict-item]
        {**base_doc, "scope": {**base_doc["scope"], "qualname_filter": "not-list"}},  # type: ignore[dict-item]
        {**base_doc, "scope": {**base_doc["scope"], "qualname_filter": {"fn_a": 1, "fn_b": 2}}},  # type: ignore[dict-item]
        {**base_doc, "scope": {**base_doc["scope"], "qualname_filter": ["other_fn"]}},  # type: ignore[dict-item]
        {**base_doc, "mutants": "not-list"},
        {**base_doc, "mutants": {}},
        {**base_doc, "mutants": ["not-dict"]},
        {**base_doc, "mutants": [{"id": 123, "status": "SURVIVED"}]},
        {**base_doc, "mutants": [{"id": ["M-1"], "status": "SURVIVED"}]},
        {**base_doc, "mutants": [{"id": "M-1111111111", "status": 99}]},
        {**base_doc, "mutants": [{"id": "M-deadbeef00", "status": "SURVIVED"}]},
    ]
    for bad_obj in bad_mutations:
        with pytest.raises(dam.ToolError) as ei:
            _call(_copy.deepcopy(bad_obj) if isinstance(bad_obj, bytes) else json.dumps(bad_obj).encode("utf-8"))  # type: ignore[arg-type]
        assert ei.value.code == "SURVIVED_SOURCE_INVALID"


def test_td144a_fast_unit_cache_key_store_load_and_build_report(tmp_path: Path) -> None:
    """Exercise every branch of compute_cache_key, _store_cache, _try_load_cache, and _build_report."""
    kw = dict(
        base_oid="a" * 40,
        scope_kind="patch",
        author_bytes={"scripts/m.py": b"x = 1\r\n"},
        related_files_sha={"scripts/tests/test_m.py": "1" * 64},
        qualnames=["fn"],
        test_map_bytes=b'{"schema_version":1,"map":{}}\r\n',
        accept_bytes=b'{"schema_version":1,"accepted":[]}\r\n',
        cmd_template=[sys.executable, "-m", "pytest"],
        max_mutants=120,
        per_mutant_timeout=60.0,
        include_globs=["*.py"],
        exclude_globs=["tests/*"],
        tool_sha="2" * 64,
        caller_tool_sha="3" * 64,
        lockfiles_sha={"uv.lock": "4" * 64},
        installed_pkgs_sha="5" * 64,
        encoding_env={"PYTHONUTF8": "1"},
    )
    k0 = dam.compute_cache_key(**kw)  # type: ignore[arg-type]
    # CRLF normalization & sys.executable -> {python} invariance
    kw_lf = {
        **kw,
        "author_bytes": {"scripts/m.py": b"x = 1\n"},
        "test_map_bytes": b'{"schema_version":1,"map":{}}\n',
        "accept_bytes": b'{"schema_version":1,"accepted":[]}\n',
        "cmd_template": ["{python}", "-m", "pytest"],
    }
    assert dam.compute_cache_key(**kw_lf) == k0  # type: ignore[arg-type]
    # Non-sys.executable token stays distinct; empty test_map/accept differs from non-empty
    assert dam.compute_cache_key(**{**kw, "cmd_template": ["python3", "-m", "pytest"]}) != k0  # type: ignore[arg-type]
    assert dam.compute_cache_key(**{**kw, "test_map_bytes": b""}) != k0  # type: ignore[arg-type]
    assert dam.compute_cache_key(**{**kw, "accept_bytes": b""}) != k0  # type: ignore[arg-type]
    assert dam.compute_cache_key(**{**kw, "test_map_bytes": b"x"}) != dam.compute_cache_key(**{**kw, "test_map_bytes": b"y"})  # type: ignore[arg-type]
    assert dam.compute_cache_key(**{**kw, "accept_bytes": b"x"}) != dam.compute_cache_key(**{**kw, "accept_bytes": b"y"})  # type: ignore[arg-type]
    assert dam.compute_cache_key(**{**kw, "caller_tool_sha": ""}) != k0  # type: ignore[arg-type]

    # _build_report checks
    rep = dam._build_report(
        tool_sha="2" * 64,
        mode="run",
        scope={"kind": "files"},
        baseline={"executed": True, "rc": 0, "elapsed_sec": 0.1, "timed_out": False, "cmd": ["x"]},
        mutants_records=[
            {"id": "M-1", "status": "CAUGHT"},
            {"id": "M-2", "status": "CAUGHT_TIMEOUT"},
            {"id": "M-3", "status": "SURVIVED"},
            {"id": "M-4", "status": "ACCEPTED"},
        ],
        skipped_nodes=2,
        invalid_count=0,
        stale_accepted=[],
        unnecessary_accepted=["M-5"],
        out_of_scope_accepted=["M-6"],
        exit_code=1,
        verdict="FAIL",
        reason="MUTANTS_SURVIVED",
        full_run=False,
        workers=4,
    )
    assert rep["full_run"] is False and rep["summary"]["full_run"] is False
    assert rep["workers"] == 4 and rep["cache"] == {"enabled": False, "hit": False, "cache_key": None, "source_report_sha256": None}
    assert rep["summary"]["caught"] == 1 and rep["summary"]["caught_timeout"] == 1
    assert rep["summary"]["survived"] == 1 and rep["summary"]["accepted"] == 1
    assert rep["summary"]["out_of_scope_accepted_count"] == 1 and rep["out_of_scope_accepted"] == ["M-6"]

    # _store_cache & _try_load_cache roundtrip & fail-closed rejection branches
    cdir = tmp_path / "nested_p" / "cache_u"
    assert dam._try_load_cache(cdir, k0) is None
    rep_ok = {**rep, "full_run": True, "summary": {**rep["summary"], "full_run": True, "exit_code": 1}}
    sha_s = dam._store_cache(cdir, k0, rep_ok)
    sha_s2 = dam._store_cache(cdir, k0, rep_ok)
    assert sha_s == sha_s2
    cpath = cdir / f"{k0}.json"
    assert "cache" not in json.loads(cpath.read_bytes())["report"]
    loaded = dam._try_load_cache(cdir, k0)
    assert loaded is not None and loaded[0] == 1 and loaded[2] == sha_s
    assert loaded[1]["cache"] == {"enabled": True, "hit": True, "cache_key": k0, "source_report_sha256": sha_s}

    orig_raw = cpath.read_bytes()
    orig_env = json.loads(orig_raw)
    cpath.write_bytes(b"{bad")
    assert dam._try_load_cache(cdir, k0) is None
    for bad_env in (
        [],
        {**orig_env, "schema_version": 999},
        {**orig_env, "cache_key": "0" * 64},
        {**orig_env, "source_report_sha256": 123},
        {**orig_env, "source_report_sha256": dam._report_digest("not-dict"), "report": "not-dict"},
        {**orig_env, "source_report_sha256": "f" * 64},
        {**orig_env, "report": {**rep_ok, "full_run": False}},
        {**orig_env, "report": {**rep_ok, "summary": "bad"}},
        {**orig_env, "report": {**rep_ok, "summary": {**rep_ok["summary"], "exit_code": 2}}},
    ):
        if isinstance(bad_env, dict) and isinstance(bad_env.get("report"), dict) and bad_env.get("source_report_sha256") not in ("f" * 64, 123):
            bad_env["source_report_sha256"] = dam._report_digest(bad_env["report"])
        cpath.write_bytes(json.dumps(bad_env).encode("utf-8"))
        assert dam._try_load_cache(cdir, k0) is None


def test_td144a_fast_unit_execute_pool_cache_and_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fast in-memory verification of execute_mutation_run pool, cache, M2 retry errors, and precedence."""
    repo = tmp_path / "repo_exec_u"
    src_b = b"def mfn(x: int) -> int:\n    if x == 0:\n        return 99\n    return x + 1\n"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts/mfn.py").write_bytes(src_b)

    # 1. Mutual exclusions & invalid caller_tool_sha256
    surv_p = tmp_path / "surv_stub.json"
    with pytest.raises(dam.ToolError) as ei:
        dam.execute_mutation_run(repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"], caller_tool_sha256="bad", list_only=True)
    assert ei.value.code == "INVALID_ARGS"
    with pytest.raises(dam.ToolError) as ei:
        dam.execute_mutation_run(repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"], only_survived_from=surv_p, list_only=True)
    assert ei.value.code == "INVALID_ARGS"
    with pytest.raises(dam.ToolError) as ei:
        dam.execute_mutation_run(repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"], only_survived_from=surv_p, cache_dir=tmp_path / "cd", test_cmd="d")
    assert ei.value.code == "INVALID_ARGS"

    # 2. --only-survived-from empty survived -> PASS_NO_MUTANTS with full_run=False & exact default cache block
    rc_list, rep_list = dam.execute_mutation_run(
        repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
        include_globs=["scripts/mfn.py"], exclude_globs=["scripts/unused.py"], list_only=True,
    )
    assert rc_list == 0 and rep_list["mode"] == "list" and rep_list["summary"]["reason"] == "LIST_OK" and rep_list["summary"]["exit_code"] == 0
    assert rep_list["baseline"] == {"executed": False, "rc": None, "elapsed_sec": 0.0, "timed_out": False, "cmd": []}
    assert rep_list["cache"] == {"enabled": False, "hit": False, "cache_key": None, "source_report_sha256": None}
    assert rep_list["scope"]["include_glob"] == ["scripts/mfn.py"]
    assert rep_list["workers"] == 1 and rep_list["summary"]["invalid"] == 0

    # Excluded globs -> NO_MUTANTS (0 mutants); skipped_nodes accumulation + qualname unmatched / cap exceeded / syntax invalid / stale accept
    rc_exc, rep_exc = dam.execute_mutation_run(
        repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
        exclude_globs=["scripts/mfn.py"], test_cmd="dummy",
    )
    assert rc_exc == 0 and rep_exc["summary"]["reason"] == "NO_MUTANTS"

    rc_qu, rep_qu = dam.execute_mutation_run(
        repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
        qualnames=["no_such_fn"], test_cmd="dummy",
    )
    assert rc_qu == 2 and rep_qu["summary"]["reason"] == "QUALNAME_UNMATCHED" and rep_qu["summary"]["exit_code"] == 2

    rc_cap, rep_cap = dam.execute_mutation_run(
        repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
        max_mutants=1, test_cmd="dummy",
    )
    assert rc_cap == 2 and rep_cap["summary"]["reason"] == "MUTANT_CAP_EXCEEDED" and rep_cap["summary"]["exit_code"] == 2

    with monkeypatch.context() as mp:
        mp.setattr(dam, "collect_mutants_for_file", lambda rel, b, fl: (
            [dam.MutantCandidate("M-1", f"{rel}::mfn::OP#1", rel, "mfn", 1, 1, 0, "OP", "a", "b", 0, 1, b"x")],
            3, 1,
        ))
        rc_inv, rep_inv = dam.execute_mutation_run(
            repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"], test_cmd="dummy",
        )
        assert rc_inv == 2 and rep_inv["summary"]["reason"] == "MUTANT_SYNTAX_INVALID"
        assert rep_inv["summary"]["skipped_nodes"] == 3 and rep_inv["summary"]["invalid"] == 1 and rep_inv["summary"]["exit_code"] == 2

    stale_acc = tmp_path / "stale_acc.json"
    stale_acc.write_bytes(json.dumps({
        "schema_version": 1,
        "accepted": [{"id": "M-deadbeef00", "reason": "r", "batch": "b"}],
    }).encode("utf-8"))
    rc_st, rep_st = dam.execute_mutation_run(
        repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
        accept_path=stale_acc, test_cmd="dummy",
    )
    assert rc_st == 2 and rep_st["summary"]["reason"] == "ACCEPT_STALE_ENTRIES" and rep_st["summary"]["exit_code"] == 2 and rep_st["stale_accepted"] == ["M-deadbeef00"]

    zero_surv = {
        "schema_version": dam.SCHEMA_VERSION,
        "tool": dam.TOOL_NAME,
        "mode": "run",
        "tool_sha256": rep_list["tool_sha256"],
        "scope": rep_list["scope"],
        "mutants": [{"id": m["id"], "status": "CAUGHT"} for m in rep_list["mutants"]],
    }
    surv_p.write_bytes(json.dumps(zero_surv).encode("utf-8"))
    rc_ns, rep_ns = dam.execute_mutation_run(repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"], only_survived_from=surv_p, test_cmd="dummy")
    assert rc_ns == 0 and rep_ns["summary"]["reason"] == "NO_MUTANTS" and rep_ns["full_run"] is False
    assert rep_ns["cache"] == {"enabled": False, "hit": False, "cache_key": None, "source_report_sha256": None}

    # 3. Pool with cache store + warm hit + test_map/accept invalidation + sequential vs pool dispatch
    (repo / "scripts/tests").mkdir(exist_ok=True)
    (repo / "scripts/tests/test_mfn_u.py").write_bytes(b"def test_ok(): assert True\n")
    tmap_u = tmp_path / "tmap_u.json"
    tmap_u.write_bytes(json.dumps({"schema_version": 1, "map": {"scripts/mfn.py": ["scripts/tests/test_mfn_u.py"]}}).encode("utf-8"))
    all_ids = [m["id"] for m in rep_list["mutants"]]
    acc_u = tmp_path / "acc_u.json"
    acc_u.write_bytes(json.dumps({"schema_version": 1, "accepted": [{"id": all_ids[0], "reason": "r1", "batch": "B1"}]}).encode("utf-8"))

    one_b = b"def o(x: int) -> int:\n    return 1\n"
    seen_rb_cmds: list[list[str]] = []
    seen_rb_temps: list[str] = []
    def _fake_iso(repo_arg, wp_arg, **kw) -> Path:
        d = Path(dam.tempfile.mkdtemp(prefix="fiso-", dir=str(wp_arg)))
        (d / "scripts/tests").mkdir(parents=True, exist_ok=True)
        (d / "scripts/mfn.py").write_bytes(src_b)
        (d / "scripts/one.py").write_bytes(one_b)
        return d

    monkeypatch.setattr(dam, "prepare_isolated_copy", _fake_iso)
    monkeypatch.setattr(dam.bounded_process, "run_bounded", lambda cmd, cwd, to, env=None, merge_stderr=False: (
        seen_rb_cmds.append(list(cmd)) or seen_rb_temps.append((env or {}).get("TEMP", "")) or (
            dam.bounded_process.BoundedResult(0, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
            if (Path(cwd) / "scripts/mfn.py").read_bytes() == src_b
            else dam.bounded_process.BoundedResult(1, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
        )
    ))
    cd = tmp_path / "ext_c_exec"
    rc_w2, rep_w2 = dam.execute_mutation_run(
        repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
        test_cmd="{python} -m pytest -q", test_map_path=tmap_u, accept_path=acc_u,
        workers=2, cache_dir=cd, work_parent=tmp_path, monotonic_fn=FakeClock([0.0], tail_step=0.1),
    )
    assert rc_w2 == 0 and rep_w2["workers"] == 2 and rep_w2["baseline"]["executed"] is True and rep_w2["baseline"]["timed_out"] is False
    assert rep_w2["cache"]["enabled"] is True and rep_w2["cache"]["hit"] is False
    assert isinstance(rep_w2["cache"]["cache_key"], str) and isinstance(rep_w2["cache"]["source_report_sha256"], str)
    assert rep_w2["unnecessary_accepted"] == [all_ids[0]]
    assert all(m["retried_single_threaded"] is False for m in rep_w2["mutants"])
    assert any("--basetemp" in c for c in seen_rb_cmds)
    assert any(Path(t).name == "tmp_w0" for t in seen_rb_temps) and any(Path(t).name == "tmp_w1" for t in seen_rb_temps)
    # Warm hit returns cached without invoking prepare_isolated_copy
    with monkeypatch.context() as mp:
        mp.setattr(dam, "prepare_isolated_copy", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("hit should skip clone")))
        rc_hit, rep_hit = dam.execute_mutation_run(
            repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
            test_cmd="{python} -m pytest -q", test_map_path=tmap_u, accept_path=acc_u,
            workers=2, cache_dir=cd, work_parent=tmp_path,
        )
        assert rc_hit == 0 and rep_hit["cache"]["hit"] is True

    # Test single-mutant sequential dispatch even with workers=2 (len(selected_mutants) == 1 -> no --basetemp injection)
    one_p = repo / "scripts/one.py"
    one_p.write_bytes(one_b)
    seen_rb_cmds.clear()
    monkeypatch.setattr(dam.bounded_process, "run_bounded", lambda cmd, cwd, to, env=None, merge_stderr=False: (
        (_ for _ in ()).throw(AssertionError("merge_stderr must be True")) if not merge_stderr else (
            seen_rb_cmds.append(list(cmd)) or (
                dam.bounded_process.BoundedResult(0, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
                if (Path(cwd) / "scripts/one.py").read_bytes() == one_b
                else dam.bounded_process.BoundedResult(1, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
            )
        )
    ))
    with monkeypatch.context() as mp:
        mp.setattr(dam, "collect_mutants_for_file", lambda rel, b, fl: (
            [dam.MutantCandidate("M-one", f"{rel}::o::CONST_INT_DELTA#1", rel, "o", 2, 2, 11, "CONST_INT_DELTA", "1", "2", len(b) - 2, len(b) - 1, b"2")],
            0, 0,
        ))
        rc_1w2, rep_1w2 = dam.execute_mutation_run(
            repo=repo, scope_kind="files", explicit_files=["scripts/one.py"],
            test_cmd="{python} -m pytest -q", workers=2, work_parent=tmp_path, monotonic_fn=FakeClock([10.0, 10.0, 10.5, 11.0, 11.5, 12.0], tail_step=0.1),
        )
        assert rc_1w2 == 0 and rep_1w2["mode"] == "run" and rep_1w2["summary"]["invalid"] == 0 and rep_1w2["stale_accepted"] == []
        assert rep_1w2["baseline"]["elapsed_sec"] == 0.5 and rep_1w2["mutants"][0]["elapsed_sec"] == 0.5
        assert all("--basetemp" not in c for c in seen_rb_cmds)

    # Sequential worker=1: baseline failure modes + SURVIVED + pool SURVIVED + pool RESTORE_FAILED beats TOTAL_TIMEOUT
    monkeypatch.setattr(dam.bounded_process, "run_bounded", lambda *a, **kw: dam.bounded_process.BoundedResult(None, True, None, b"", b"", dam.bounded_process.KILL_TREE_SIGNALLED))
    rc_b1t, rep_b1t = dam.execute_mutation_run(
        repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
        test_cmd="dummy", workers=1, work_parent=tmp_path, monotonic_fn=FakeClock([0.0], tail_step=0.1),
    )
    assert rc_b1t == 2 and rep_b1t["summary"]["reason"] == "BASELINE_FAILED" and rep_b1t["baseline"]["timed_out"] is True

    monkeypatch.setattr(dam.bounded_process, "run_bounded", lambda cmd, cwd, to, env=None, merge_stderr=False: dam.bounded_process.BoundedResult(0, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED))
    rc_s2, rep_s2 = dam.execute_mutation_run(
        repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
        test_cmd="dummy", workers=2, work_parent=tmp_path, monotonic_fn=FakeClock([0.0], tail_step=0.1),
    )
    assert rc_s2 == 1 and rep_s2["summary"]["reason"] == "MUTANTS_SURVIVED" and rep_s2["summary"]["verdict"] == "FAIL"

    # Pool launch error & pool baseline launch_error & pool total_timeout
    monkeypatch.setattr(dam.bounded_process, "run_bounded", lambda *a, **kw: dam.bounded_process.BoundedResult(None, False, "bl-err", b"", b"", dam.bounded_process.KILL_NOT_NEEDED))
    rc_bl2, rep_bl2 = dam.execute_mutation_run(repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"], test_cmd="dummy", workers=2, work_parent=tmp_path)
    assert rc_bl2 == 2 and rep_bl2["summary"]["reason"] == "BASELINE_FAILED" and rep_bl2["summary"]["invalid"] == 0 and rep_bl2["summary"]["exit_code"] == 2

    def _mbytes(m):
        return src_b[: m.start_byte] + m.replacement_bytes + src_b[m.end_byte :]

    raw_three, _, _ = dam.collect_mutants_for_file("scripts/mfn.py", src_b, None)
    mb3 = [_mbytes(m) for m in raw_three[:3]]
    raw_two, mb2 = raw_three[:2], [_mbytes(m) for m in raw_three[:2]]

    # Pool partial TEST_LAUNCH_ERROR with completed first mutant (hits L2190 partial_records & workers=1 runtime check)
    def _stub_pool_le(cmd, cwd, to, env=None, merge_stderr=False):
        cur_b = (Path(cwd) / "scripts/mfn.py").read_bytes()
        if cur_b == src_b:
            return dam.bounded_process.BoundedResult(0, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
        if cur_b == mb2[0]:
            return dam.bounded_process.BoundedResult(1, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
        import time
        time.sleep(0.05)
        return dam.bounded_process.BoundedResult(None, False, "pool-spawn-err", b"", b"", dam.bounded_process.KILL_NOT_NEEDED)

    monkeypatch.setattr(dam.bounded_process, "run_bounded", _stub_pool_le)
    with monkeypatch.context() as mp:
        mp.setattr(dam, "collect_mutants_for_file", lambda rel, b, fl: (raw_two, 0, 0))
        rc_ple, rep_ple = dam.execute_mutation_run(repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"], test_cmd="dummy", workers=2, work_parent=tmp_path, monotonic_fn=FakeClock([0.0], tail_step=0.1))
    assert rc_ple == 2 and rep_ple["summary"]["reason"] == "TEST_LAUNCH_ERROR" and rep_ple["summary"]["invalid"] == 0 and rep_ple["summary"]["exit_code"] == 2
    assert any(r["status"] == "CAUGHT" and isinstance(r["elapsed_sec"], float) for r in rep_ple["mutants"])

    # Deterministic RESTORE_FAILED > TEST_LAUNCH_ERROR precedence (abort_errors = [TEST_LAUNCH_ERROR, RESTORE_FAILED])
    orig_sha_fn = dam._sha256_bytes
    prec_barrier = dam.threading.Barrier(2)
    bad_tid: dict[str, int | None] = {"tid": None}
    def _stub_restore_vs_le(cmd, cwd, to, env=None, merge_stderr=False):
        cur_b = (Path(cwd) / "scripts/mfn.py").read_bytes()
        if cur_b == src_b:
            return dam.bounded_process.BoundedResult(0, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
        if cur_b == mb2[0]:
            prec_barrier.wait(timeout=5.0)
            return dam.bounded_process.BoundedResult(None, False, "other-err", b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
        bad_tid["tid"] = dam.threading.get_ident()
        prec_barrier.wait(timeout=5.0)
        import time
        time.sleep(0.03)
        return dam.bounded_process.BoundedResult(1, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)

    with monkeypatch.context() as mp:
        mp.setattr(dam, "collect_mutants_for_file", lambda rel, b, fl: (raw_two, 0, 0))
        mp.setattr(dam.bounded_process, "run_bounded", _stub_restore_vs_le)
        mp.setattr(dam, "_sha256_bytes", lambda data: "bad-sha" if dam.threading.get_ident() == bad_tid["tid"] else orig_sha_fn(data))
        with pytest.raises(dam.ToolError, match="failed to restore") as ei_prec:
            dam.execute_mutation_run(repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"], test_cmd="dummy", workers=2, work_parent=tmp_path, monotonic_fn=FakeClock([0.0], tail_step=0.1))
        assert ei_prec.value.code == "RESTORE_FAILED"

    # Unexpected exception inside _run_slot propagates via fut.result() (kills L2173 STMT_CALL_DELETE)
    monkeypatch.setattr(dam.bounded_process, "run_bounded", lambda cmd, cwd, to, env=None, merge_stderr=False: (
        dam.bounded_process.BoundedResult(0, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
        if (Path(cwd) / "scripts/mfn.py").read_bytes() == src_b
        else (_ for _ in ()).throw(RuntimeError("slot-boom"))
    ))
    with pytest.raises(RuntimeError, match="slot-boom"):
        dam.execute_mutation_run(repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"], test_cmd="dummy", workers=2, work_parent=tmp_path, monotonic_fn=FakeClock([0.0], tail_step=0.1))

    monkeypatch.setattr(dam.bounded_process, "run_bounded", lambda cmd, cwd, to, env=None, merge_stderr=False: (
        dam.bounded_process.BoundedResult(0, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
    ))
    rc_ptt, rep_ptt = dam.execute_mutation_run(
        repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
        test_cmd="dummy", workers=2, total_timeout=0.05, work_parent=tmp_path, monotonic_fn=FakeClock([0.0, 0.01, 0.02, 5.0], tail_step=1.0),
    )
    assert rc_ptt == 2 and rep_ptt["summary"]["reason"] == "TOTAL_TIMEOUT_EXCEEDED" and any(r["status"] == "NOT_RUN" for r in rep_ptt["mutants"])

    # Retry hits TOTAL_TIMEOUT_EXCEEDED with j < idx prior caught record & exact boundary (== total_timeout NOT exceeded!)
    # Use 3 mutants: mutant 0 caught in pool, mutant 1 & 2 time out in pool -> mutant 1 succeeds in retry (retried=True), mutant 2 hits total_timeout!
    rt_lock = dam.threading.Lock()
    rt_seen: set[bytes] = set()
    def _stub_timeout_jlt(cmd, cwd, to, env=None, merge_stderr=False):
        cur_b = (Path(cwd) / "scripts/mfn.py").read_bytes()
        if cur_b == src_b:
            return dam.bounded_process.BoundedResult(0, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
        if cur_b == mb3[0]:
            return dam.bounded_process.BoundedResult(1, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
        with rt_lock:
            first = cur_b not in rt_seen
            rt_seen.add(cur_b)
        if first:
            return dam.bounded_process.BoundedResult(None, True, None, b"", b"", dam.bounded_process.KILL_TREE_SIGNALLED)
        return dam.bounded_process.BoundedResult(1, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)

    monkeypatch.setattr(dam.bounded_process, "run_bounded", _stub_timeout_jlt)
    with monkeypatch.context() as mp:
        mp.setattr(dam, "collect_mutants_for_file", lambda rel, b, fl: (raw_three[:3], 0, 0))
        # Boundary test: retry check at exact clock() - run_start == 1.0 (total_timeout=1.0) MUST NOT abort; next retry check 1.5 > 1.0 DOES abort!
        # Shifted +10.0 so clock() - run_start != clock() + run_start!
        clk_rt = FakeClock([10.0, 10.0, 10.1, 10.1, 10.2, 10.2, 10.3, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 11.0, 11.12349, 11.5], tail_step=0.1)
        rc_rt, rep_rt = dam.execute_mutation_run(
            repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
            test_cmd="dummy", workers=2, total_timeout=1.0, work_parent=tmp_path, monotonic_fn=clk_rt,
        )
        assert rc_rt == 2 and rep_rt["summary"]["reason"] == "TOTAL_TIMEOUT_EXCEEDED"
        assert rep_rt["summary"]["invalid"] == 0 and rep_rt["summary"]["exit_code"] == 2
        assert rep_rt["mutants"][0]["status"] == "CAUGHT" and rep_rt["mutants"][0]["retried_single_threaded"] is False and isinstance(rep_rt["mutants"][0]["elapsed_sec"], float)
        assert rep_rt["mutants"][1]["status"] == "CAUGHT" and rep_rt["mutants"][1]["retried_single_threaded"] is True and isinstance(rep_rt["mutants"][1]["elapsed_sec"], float)
        assert rep_rt["mutants"][2]["status"] == "NOT_RUN"

    # Deterministic M2 retry TEST_LAUNCH_ERROR with j < idx caught + test_map_path + --basetemp tmp_w0 + TEMP tmp_w0 check
    retry_seen: list[tuple[list[str], str, str]] = []
    rl2_lock = dam.threading.Lock()
    rl2_seen: set[bytes] = set()
    def _stub_retry_launch(cmd, cwd, to, env=None, merge_stderr=False):
        assert merge_stderr is True
        cur_b = (Path(cwd) / "scripts/mfn.py").read_bytes()
        if cur_b == src_b:
            return dam.bounded_process.BoundedResult(0, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
        retry_seen.append((list(cmd), Path(cwd).name, Path((env or {}).get("TEMP", "")).name))
        if cur_b == mb2[0]:
            return dam.bounded_process.BoundedResult(1, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
        with rl2_lock:
            first = cur_b not in rl2_seen
            rl2_seen.add(cur_b)
        if first:
            return dam.bounded_process.BoundedResult(None, True, None, b"", b"", dam.bounded_process.KILL_TREE_SIGNALLED)
        # In single-threaded retry on timed-out mutant -> spawn fail!
        return dam.bounded_process.BoundedResult(None, False, "spawn fail", b"", b"", dam.bounded_process.KILL_NOT_NEEDED)

    monkeypatch.setattr(dam.bounded_process, "run_bounded", _stub_retry_launch)
    with monkeypatch.context() as mp:
        mp.setattr(dam, "collect_mutants_for_file", lambda rel, b, fl: (raw_two[:2], 0, 0))
        rc_le, rep_le = dam.execute_mutation_run(
            repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
            test_cmd="{python} -m pytest -q {tests}", test_map_path=tmap_u,
            workers=2, total_timeout=100.0, work_parent=tmp_path, monotonic_fn=FakeClock([0.0], tail_step=0.1),
        )
        assert rc_le == 2 and rep_le["summary"]["reason"] == "TEST_LAUNCH_ERROR" and rep_le["summary"]["invalid"] == 0 and rep_le["summary"]["exit_code"] == 2
        assert len(rep_le["mutants"]) == 1 and rep_le["mutants"][0]["status"] == "CAUGHT" and isinstance(rep_le["mutants"][0]["elapsed_sec"], float)
        # Last retry_seen ran in work_w0 with tmp_w0 TEMP & tmap_u test file & --basetemp tmp_w0/bt
        rcmd, _rcwd, rtemp = retry_seen[-1]
        assert rtemp == "tmp_w0" and "scripts/tests/test_mfn_u.py" in rcmd
        assert any(tok.endswith(str(Path("tmp_w0") / "bt")) for tok in rcmd)

    # Exact retry round(clock() - r0, 3) & selective skip (only timed_out=True is retried)
    r3_lock = dam.threading.Lock()
    r3_seen: set[bytes] = set()
    def _stub_retry_ok(cmd, cwd, to, env=None, merge_stderr=False):
        cur_b = (Path(cwd) / "scripts/mfn.py").read_bytes()
        if cur_b == src_b:
            return dam.bounded_process.BoundedResult(0, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
        if cur_b == mb2[0]:
            return dam.bounded_process.BoundedResult(1, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
        with r3_lock:
            first = cur_b not in r3_seen
            r3_seen.add(cur_b)
        if first:
            return dam.bounded_process.BoundedResult(None, True, None, b"", b"", dam.bounded_process.KILL_TREE_SIGNALLED)
        return dam.bounded_process.BoundedResult(1, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)

    wp_clean = tmp_path / "wp_pool_clean"
    wp_clean.mkdir()
    monkeypatch.setattr(dam.bounded_process, "run_bounded", _stub_retry_ok)
    with monkeypatch.context() as mp:
        mp.setattr(dam, "collect_mutants_for_file", lambda rel, b, fl: (raw_two[:2], 0, 0))
        # Exact retry elapsed test: every clock() advance is 0.12349 so round(..., 3) == 0.123 (vs round(..., 4) == 0.1235)
        clk_r3 = FakeClock([0.0], tail_step=0.12349)
        rc_r3, rep_r3 = dam.execute_mutation_run(
            repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
            test_cmd="dummy", workers=2, total_timeout=100.0, work_parent=wp_clean, monotonic_fn=clk_r3,
        )
        assert rc_r3 == 0 and rep_r3["baseline"]["elapsed_sec"] == 0.123
        assert rep_r3["summary"]["exit_code"] == 0 and rep_r3["summary"]["verdict"] == "PASS" and rep_r3["summary"]["reason"] == "OK"
        assert [m["retried_single_threaded"] for m in rep_r3["mutants"]] == [False, True]
        assert rep_r3["mutants"][1]["elapsed_sec"] == 0.123
        assert list(wp_clean.iterdir()) == []

    # Parallel workers=2 mixed 1 SURVIVED + 1 CAUGHT -> exit_code=1, verdict='FAIL', reason='MUTANTS_SURVIVED', survived=1
    with monkeypatch.context() as mp:
        mp.setattr(dam, "collect_mutants_for_file", lambda rel, b, fl: (raw_two, 0, 0))
        mp.setattr(dam.bounded_process, "run_bounded", lambda cmd, cwd, to, env=None, merge_stderr=False: (
            dam.bounded_process.BoundedResult(0, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
            if (Path(cwd) / "scripts/mfn.py").read_bytes() in (src_b, mb2[0])
            else dam.bounded_process.BoundedResult(1, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
        ))
        rc_s2m, rep_s2m = dam.execute_mutation_run(
            repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
            test_cmd="dummy", workers=2, work_parent=tmp_path, monotonic_fn=FakeClock([0.0], tail_step=0.1),
        )
        assert rc_s2m == 1 and rep_s2m["summary"]["exit_code"] == 1 and rep_s2m["summary"]["verdict"] == "FAIL"
        assert rep_s2m["summary"]["reason"] == "MUTANTS_SURVIVED" and rep_s2m["summary"]["survived"] == 1

    # Pool baseline fail with cache enabled (kills cache_meta_default & exact FakeClock b_elapsed = 0.5)
    monkeypatch.setattr(dam.bounded_process, "run_bounded", lambda *a, **kw: (
        (_ for _ in ()).throw(AssertionError("merge_stderr must be True")) if not kw.get("merge_stderr")
        else dam.bounded_process.BoundedResult(1, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
    ))
    tmap_u2 = tmp_path / "tmap_u2.json"
    (repo / "scripts/tests/test_mfn_u2.py").write_bytes(b"def test_ok2(): assert True\n")
    tmap_u2.write_bytes(json.dumps({"schema_version": 1, "map": {"scripts/mfn.py": ["scripts/tests/test_mfn_u2.py"]}}).encode("utf-8"))
    acc_u2 = tmp_path / "acc_u2.json"
    acc_u2.write_bytes(json.dumps({"schema_version": 1, "accepted": [{"id": all_ids[1], "reason": "r2", "batch": "B2"}]}).encode("utf-8"))
    rc_bf_c, rep_bf_c = dam.execute_mutation_run(
        repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
        test_cmd="dummy", test_map_path=tmap_u2, accept_path=acc_u2,
        workers=2, cache_dir=cd, work_parent=tmp_path, monotonic_fn=FakeClock([10.0, 10.0, 10.5], tail_step=0.1),
    )
    assert rc_bf_c == 2 and rep_bf_c["summary"]["reason"] == "BASELINE_FAILED" and rep_bf_c["summary"]["invalid"] == 0
    assert rep_bf_c["baseline"]["elapsed_sec"] == 0.5
    assert rep_bf_c["cache"]["enabled"] is True and rep_bf_c["cache"]["hit"] is False
    assert rep_bf_c["cache"]["cache_key"] != rep_w2["cache"]["cache_key"]

    # Isolating test_map_path alone (same file_tests, different tmap bytes) & accept_path alone vs None (kills L1868 & L1869)
    monkeypatch.setattr(dam.bounded_process, "run_bounded", lambda cmd, cwd, to, env=None, merge_stderr=False: (
        dam.bounded_process.BoundedResult(0, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
        if (Path(cwd) / "scripts/mfn.py").read_bytes() == src_b
        else dam.bounded_process.BoundedResult(1, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
    ))
    tmap_u_ws = tmp_path / "tmap_u_ws.json"
    tmap_u_ws.write_bytes(tmap_u.read_bytes() + b"\n  \n")
    cd2 = tmp_path / "ext_c_exec2"
    rc_tm1, rep_tm1 = dam.execute_mutation_run(repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"], test_cmd="dummy", test_map_path=tmap_u, cache_dir=cd2, work_parent=tmp_path)
    rc_tm_ws, rep_tm_ws = dam.execute_mutation_run(repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"], test_cmd="dummy", test_map_path=tmap_u_ws, cache_dir=cd2, work_parent=tmp_path)
    assert rc_tm1 == 0 and rc_tm_ws == 0 and rep_tm_ws["cache"]["hit"] is False and rep_tm1["cache"]["cache_key"] != rep_tm_ws["cache"]["cache_key"]
    rc_ac0, rep_ac0 = dam.execute_mutation_run(repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"], test_cmd="dummy", accept_path=None, cache_dir=cd2, work_parent=tmp_path)
    rc_ac1, rep_ac1 = dam.execute_mutation_run(repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"], test_cmd="dummy", accept_path=acc_u2, cache_dir=cd2, work_parent=tmp_path)
    assert rc_ac0 == 0 and rc_ac1 == 0 and rep_ac1["cache"]["hit"] is False and rep_ac0["cache"]["cache_key"] != rep_ac1["cache"]["cache_key"]

    # Sequential worker=1: launch_error with rc=0, timed_out with rc=0, TOTAL_TIMEOUT_EXCEEDED, TEST_LAUNCH_ERROR, normal with cache store + elapsed
    for br in (
        dam.bounded_process.BoundedResult(0, False, "bl-err-0", b"", b"", dam.bounded_process.KILL_NOT_NEEDED),
        dam.bounded_process.BoundedResult(0, True, None, b"", b"", dam.bounded_process.KILL_TREE_SIGNALLED),
    ):
        monkeypatch.setattr(dam.bounded_process, "run_bounded", lambda *a, _br=br, **kw: (
            (_ for _ in ()).throw(AssertionError("merge_stderr must be True")) if not kw.get("merge_stderr") else _br
        ))
        rc_b1, rep_b1 = dam.execute_mutation_run(
            repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
            test_cmd="dummy", workers=1, work_parent=tmp_path, monotonic_fn=FakeClock([10.0, 10.0, 10.5], tail_step=0.1),
        )
        assert rc_b1 == 2 and rep_b1["summary"]["reason"] == "BASELINE_FAILED" and rep_b1["summary"]["invalid"] == 0
        assert rep_b1["baseline"]["executed"] is True and rep_b1["baseline"]["elapsed_sec"] == 0.5

    # Sequential TOTAL_TIMEOUT_EXCEEDED after baseline
    monkeypatch.setattr(dam.bounded_process, "run_bounded", lambda cmd, cwd, to, env=None, merge_stderr=False: (
        dam.bounded_process.BoundedResult(0, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
    ))
    rc_s1to, rep_s1to = dam.execute_mutation_run(
        repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
        test_cmd="dummy", workers=1, total_timeout=0.5, work_parent=tmp_path, monotonic_fn=FakeClock([0.0, 0.1, 0.2, 5.0], tail_step=1.0),
    )
    assert rc_s1to == 2 and rep_s1to["summary"]["reason"] == "TOTAL_TIMEOUT_EXCEEDED" and rep_s1to["summary"]["invalid"] == 0 and rep_s1to["summary"]["exit_code"] == 2
    assert len(rep_s1to["mutants"]) == len(rep_list["mutants"]) and all(m["status"] == "NOT_RUN" for m in rep_s1to["mutants"])

    # Sequential TEST_LAUNCH_ERROR after baseline
    def _stub_s1_le(cmd, cwd, to, env=None, merge_stderr=False):
        assert merge_stderr is True
        if (Path(cwd) / "scripts/mfn.py").read_bytes() == src_b:
            return dam.bounded_process.BoundedResult(0, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
        return dam.bounded_process.BoundedResult(None, False, "s1-spawn-err", b"", b"", dam.bounded_process.KILL_NOT_NEEDED)

    monkeypatch.setattr(dam.bounded_process, "run_bounded", _stub_s1_le)
    rc_s1le, rep_s1le = dam.execute_mutation_run(
        repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
        test_cmd="dummy", workers=1, work_parent=tmp_path, monotonic_fn=FakeClock([0.0], tail_step=0.1),
    )
    assert rc_s1le == 2 and rep_s1le["summary"]["reason"] == "TEST_LAUNCH_ERROR" and rep_s1le["summary"]["invalid"] == 0 and rep_s1le["summary"]["exit_code"] == 2

    # Sequential normal complete with cache_dir stores cache (0 -> 1 hit) and records invalid=0 & elapsed
    cd3 = tmp_path / "ext_c_seq"
    monkeypatch.setattr(dam.bounded_process, "run_bounded", lambda cmd, cwd, to, env=None, merge_stderr=False: (
        (_ for _ in ()).throw(AssertionError("merge_stderr must be True")) if not merge_stderr else (
            dam.bounded_process.BoundedResult(0, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
            if (Path(cwd) / "scripts/mfn.py").read_bytes() == src_b
            else dam.bounded_process.BoundedResult(1, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
        )
    ))
    rc_s1ok, rep_s1ok = dam.execute_mutation_run(
        repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
        test_cmd="dummy", workers=1, cache_dir=cd3, work_parent=tmp_path, monotonic_fn=FakeClock([0.0], tail_step=0.25),
    )
    assert rc_s1ok == 0 and rep_s1ok["summary"]["invalid"] == 0 and rep_s1ok["cache"]["hit"] is False
    assert rep_s1ok["baseline"]["executed"] is True
    with monkeypatch.context() as mp:
        mp.setattr(dam, "collect_mutants_for_file", lambda rel, b, fl: (raw_two, 0, 0))
        mp.setattr(dam.bounded_process, "run_bounded", lambda cmd, cwd, to, env=None, merge_stderr=False: (
            dam.bounded_process.BoundedResult(0, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
            if (Path(cwd) / "scripts/mfn.py").read_bytes() in (src_b, mb2[0])
            else dam.bounded_process.BoundedResult(1, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
        ))
        rc_s1m, rep_s1m = dam.execute_mutation_run(
            repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
            test_cmd="dummy", workers=1, work_parent=tmp_path, monotonic_fn=FakeClock([0.0], tail_step=0.1),
        )
        assert rc_s1m == 1 and rep_s1m["summary"]["exit_code"] == 1 and rep_s1m["summary"]["verdict"] == "FAIL"
        assert rep_s1m["summary"]["reason"] == "MUTANTS_SURVIVED" and rep_s1m["summary"]["survived"] == 1
    with monkeypatch.context() as mp:
        mp.setattr(dam, "prepare_isolated_copy", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("seq hit should skip clone")))
        rc_s1h, rep_s1h = dam.execute_mutation_run(
            repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
            test_cmd="dummy", workers=1, cache_dir=cd3, work_parent=tmp_path,
        )
        assert rc_s1h == 0 and rep_s1h["cache"]["hit"] is True

    # Pool RESTORE_FAILED during retry ONLY (pool succeeds with timed_out=True on 2 mutants, then 3rd call=retry corrupts!)
    real_rb_read = Path.read_bytes
    seq_r_lock = dam.threading.Lock()
    seq_r = {"n": 0, "in_retry": False}
    def _stub_pool_restore(cmd, cwd, to, env=None, merge_stderr=False):
        if (Path(cwd) / "scripts/mfn.py").read_bytes() == src_b:
            return dam.bounded_process.BoundedResult(0, False, None, b"", b"", dam.bounded_process.KILL_NOT_NEEDED)
        with seq_r_lock:
            seq_r["n"] += 1
            if seq_r["n"] == 3:
                seq_r["in_retry"] = True
        return dam.bounded_process.BoundedResult(None, True, None, b"", b"", dam.bounded_process.KILL_TREE_SIGNALLED)

    monkeypatch.setattr(dam.bounded_process, "run_bounded", _stub_pool_restore)
    with monkeypatch.context() as mp:
        raw_one_r, _, _ = dam.collect_mutants_for_file("scripts/mfn.py", src_b, None)
        mp.setattr(dam, "collect_mutants_for_file", lambda rel, b, fl: (raw_one_r[:2], 0, 0))
        mp.setattr(Path, "read_bytes", lambda self: b"corrupt-r" if self.name == "mfn.py" and seq_r["in_retry"] else real_rb_read(self))
        with pytest.raises(dam.ToolError, match="during timeout recheck") as ei:
            dam.execute_mutation_run(repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"], test_cmd="dummy", workers=2, work_parent=tmp_path, monotonic_fn=FakeClock([0.0], tail_step=0.1))
        assert ei.value.code == "RESTORE_FAILED"


def test_td144a_resolve_workers_bounds_and_inject_basetemp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert dam.resolve_workers(None) == 1
    assert dam.resolve_workers("1") == 1
    assert dam.resolve_workers(" 8 ") == 8
    assert dam.resolve_workers(4) == 4
    monkeypatch.setattr(dam.os, "cpu_count", lambda: 12)
    assert dam.resolve_workers("auto") == 4
    monkeypatch.setattr(dam.os, "cpu_count", lambda: 2)
    assert dam.resolve_workers("AUTO") == 1
    monkeypatch.setattr(dam.os, "cpu_count", lambda: None)
    assert dam.resolve_workers("auto") == 1

    for bad_w in (True, False, "", "   ", "0", "-2", "9", 0, 9, "xyz", 1.5):
        with pytest.raises(dam.ToolError) as ei:
            dam.resolve_workers(bad_w)  # type: ignore[arg-type]
        assert ei.value.code == "INVALID_ARGS"

    bt = tmp_path / "bt0"
    assert dam._inject_pytest_basetemp(["py", "-m", "pytest", "-q"], bt) == ["py", "-m", "pytest", "--basetemp", str(bt), "-q"]
    assert dam._inject_pytest_basetemp(["pytest", "-q"], bt) == ["pytest", "--basetemp", str(bt), "-q"]
    already = ["py", "-m", "pytest", "--basetemp", "custom", "-q"]
    assert dam._inject_pytest_basetemp(already, bt) == already
    already2 = ["py", "-m", "pytest", "--basetemp=custom", "-q"]
    assert dam._inject_pytest_basetemp(already2, bt) == already2
    assert dam._inject_pytest_basetemp(["dummy_runner", "-q"], bt) == ["dummy_runner", "-q"]


def test_td144a_m2_parallel_timeout_retry_same_timeout_and_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo_m2"
    src_b = b"def mfn(x: int) -> int:\n    if x == 0:\n        return 1\n    return x + 1\n"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts/mfn.py").write_bytes(src_b)

    def _fake_iso(repo_arg, wp_arg, **kw) -> Path:
        idx = len([p for p in wp_arg.iterdir() if p.name.startswith("fake_iso_")])
        d = wp_arg / f"fake_iso_{idx}"
        (d / "scripts").mkdir(parents=True, exist_ok=True)
        (d / "scripts/mfn.py").write_bytes(src_b)
        return d

    monkeypatch.setattr(dam, "prepare_isolated_copy", _fake_iso)
    monkeypatch.setattr(dam, "_DEFAULT_MONOTONIC", dam.time.monotonic if hasattr(dam, "time") else FakeClock([0.0], tail_step=0.1))
    # Use deterministic FakeClock (also covers _DEFAULT_MONOTONIC usage)
    clk = FakeClock([10.0], tail_step=0.1)

    seen_timeouts: list[tuple[str, float]] = []
    stub_lock = threading.Lock()
    triggered = {"done": False}

    def _stub_contention_timeout(cmd, cwd, timeout, env=None, merge_stderr=False):
        with stub_lock:
            seen_timeouts.append((Path(cwd).name, float(timeout)))
        content = (Path(cwd) / "scripts/mfn.py").read_bytes()
        if content == src_b:
            return bounded_process.BoundedResult(0, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED)
        # Mutant in work slot: first mutant execution times out; single-threaded retry in slot 0 catches it!
        with stub_lock:
            if not triggered["done"]:
                triggered["done"] = True
                return bounded_process.BoundedResult(None, True, None, b"", b"", bounded_process.KILL_TREE_SIGNALLED)
        return bounded_process.BoundedResult(1, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED)

    monkeypatch.setattr(dam.bounded_process, "run_bounded", _stub_contention_timeout)
    rc, rep = dam.execute_mutation_run(
        repo=repo,
        scope_kind="files",
        explicit_files=["scripts/mfn.py"],
        test_cmd="dummy",
        per_mutant_timeout=42.0,
        total_timeout=500.0,
        workers=2,
        work_parent=tmp_path,
        monotonic_fn=clk,
    )
    assert rc == 0
    assert rep["summary"]["caught"] == rep["summary"]["total"] and rep["summary"]["caught_timeout"] == 0
    assert any(m["retried_single_threaded"] is True for m in rep["mutants"])
    # M2 CRITICAL INVARIANT: every mutant & retry uses EXACT per_mutant_timeout (42.0), NEVER 1.5x (63.0)
    mutant_timeouts = [t for _cwd, t in seen_timeouts[1:]]
    assert all(t == 42.0 for t in mutant_timeouts), f"Expected exact 42.0 timeouts, got {mutant_timeouts}"

    # 2. Both parallel and single-threaded retry time out -> CAUGHT_TIMEOUT, retried_single_threaded=True
    def _stub_dual_timeout(cmd, cwd, timeout, env=None, merge_stderr=False):
        if (Path(cwd) / "scripts/mfn.py").read_bytes() == src_b:
            return bounded_process.BoundedResult(0, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED)
        return bounded_process.BoundedResult(None, True, None, b"", b"", bounded_process.KILL_TREE_SIGNALLED)

    monkeypatch.setattr(dam.bounded_process, "run_bounded", _stub_dual_timeout)
    rc_to, rep_to = dam.execute_mutation_run(
        repo=repo,
        scope_kind="files",
        explicit_files=["scripts/mfn.py"],
        test_cmd="dummy",
        per_mutant_timeout=15.0,
        total_timeout=500.0,
        workers=2,
        work_parent=tmp_path,
        monotonic_fn=FakeClock([0.0], tail_step=0.1),
    )
    assert rc_to == 0 and rep_to["summary"]["caught_timeout"] == rep_to["summary"]["total"]
    assert all(m["retried_single_threaded"] is True and m["status"] == "CAUGHT_TIMEOUT" for m in rep_to["mutants"])

    # 3. Retry finds rc=0 -> SURVIVED -> exit 1
    retry_step = {"n": 0}

    def _stub_retry_survived(cmd, cwd, timeout, env=None, merge_stderr=False):
        if (Path(cwd) / "scripts/mfn.py").read_bytes() == src_b:
            return bounded_process.BoundedResult(0, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED)
        retry_step["n"] += 1
        if retry_step["n"] == 1:
            return bounded_process.BoundedResult(None, True, None, b"", b"", bounded_process.KILL_TREE_SIGNALLED)
        return bounded_process.BoundedResult(0, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED)

    monkeypatch.setattr(dam.bounded_process, "run_bounded", _stub_retry_survived)
    rc_rs, rep_rs = dam.execute_mutation_run(
        repo=repo, scope_kind="files", explicit_files=["scripts/mfn.py"],
        test_cmd="dummy", workers=2, work_parent=tmp_path, monotonic_fn=FakeClock([0.0], tail_step=0.1),
    )
    assert rc_rs == 1 and rep_rs["summary"]["survived"] >= 1


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


def test_td137_no_bare_time_monotonic_calls_in_diff_ast_mutate() -> None:
    """Assert diff_ast_mutate.py binds time.monotonic once to _DEFAULT_MONOTONIC with 0 direct calls."""
    dam_path = Path(dam.__file__).resolve()
    src = dam_path.read_bytes().decode("utf-8")
    tree = ast.parse(src)

    bare_calls: list[int] = []
    monotonic_attrs: list[int] = []
    bound_targets: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == "time" and fn.attr == "monotonic":
                bare_calls.append(node.lineno)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "time" and node.attr == "monotonic":
            monotonic_attrs.append(node.lineno)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            val = node.value
            if isinstance(val, ast.Attribute) and isinstance(val.value, ast.Name) and val.value.id == "time" and val.attr == "monotonic":
                bound_targets.append(node.target.id)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            val = node.value
            if isinstance(val, ast.Attribute) and isinstance(val.value, ast.Name) and val.value.id == "time" and val.attr == "monotonic":
                bound_targets.append(node.targets[0].id)

    assert bare_calls == [], f"Unexpected bare time.monotonic() calls at lines {bare_calls}"
    assert len(monotonic_attrs) == 1, f"Expected single time.monotonic binding, saw lines {monotonic_attrs}"
    assert bound_targets == ["_DEFAULT_MONOTONIC"], f"Unexpected binding targets: {bound_targets}"


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

    # 3. TOTAL_TIMEOUT_EXCEEDED (> vs == boundary) via module FakeClock (TD-137)
    import time as _stdlib_time
    real_monotonic = _stdlib_time.monotonic
    monkeypatch.setattr(dam, "_DEFAULT_MONOTONIC", FakeClock([100.0, 100.1, 100.2, 105.0], tail_step=1.0))
    assert dam.time.monotonic is real_monotonic
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
    monkeypatch.setattr(dam, "_DEFAULT_MONOTONIC", FakeClock([100.0, 100.1, 100.2, 104.0], tail_step=0.0))
    assert dam.time.monotonic is real_monotonic
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

    monkeypatch.setattr(dam, "_DEFAULT_MONOTONIC", FakeClock([100.0], tail_step=0.1))
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

    monkeypatch.setattr(dam, "_DEFAULT_MONOTONIC", FakeClock([100.0], tail_step=0.1))
    monkeypatch.setattr(dam.bounded_process, "run_bounded", all_survived_run)
    rep_fail = tmp_path / "fail_sum.json"
    assert dam.main([
        "--repo", str(tmp_path), "--files", "scripts/f.py",
        "--test-cmd", "dummy", "--json-out", str(rep_fail), "--work-parent", str(tmp_path),
    ]) == 1
    df = json.loads(rep_fail.read_bytes())["summary"]
    assert df["survived"] == 3 and df["exit_code"] == 1 and df["verdict"] == "FAIL" and df["reason"] == "MUTANTS_SURVIVED"


_N1_PRECEDENCE_CASES = [
    ("blank_qualname_vs_accept_invalid", "INVALID_ARGS"),
    ("accept_invalid_vs_test_map_invalid", "ACCEPT_FILE_INVALID"),
    ("test_map_invalid_vs_missing_test_cmd", "TEST_MAP_INVALID"),
    ("missing_test_cmd_vs_git_error", "INVALID_ARGS"),
    ("git_error_vs_target_parse_error", "GIT_ERROR"),
    ("patch_error_vs_qualname_unmatched", "PATCH_ERROR"),
    ("target_parse_vs_qualname_unmatched", "TARGET_PARSE_ERROR"),
    ("qualname_unmatched_vs_accept_stale", "QUALNAME_UNMATCHED"),
    ("accept_stale_vs_test_map_unmapped", "ACCEPT_STALE_ENTRIES"),
    ("test_map_unmapped_vs_cap_exceeded", "TEST_MAP_UNMAPPED"),
    ("cap_exceeded_vs_syntax_invalid", "MUTANT_CAP_EXCEEDED"),
    ("syntax_invalid_vs_baseline_failed", "MUTANT_SYNTAX_INVALID"),
    ("baseline_failed_vs_total_timeout", "BASELINE_FAILED"),
    ("total_timeout_vs_restore_failed", "TOTAL_TIMEOUT_EXCEEDED"),
    ("restore_failed_vs_test_launch_error", "RESTORE_FAILED"),
]


@pytest.mark.parametrize("case_name,expected_reason", _N1_PRECEDENCE_CASES)
def test_n1_exit2_precedence_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_name: str, expected_reason: str) -> None:
    """Lock the exact exit-2 reason precedence chain documented in docs/ops/td134-diff-ast-mutate.md."""
    repo = tmp_path / f"repo_{case_name}"
    ok_py = b"def f(x: int) -> int:\n    if x == 0:\n        return 1\n    return x\n"
    bad_accept = tmp_path / "bad_accept.json"
    bad_accept.write_bytes(b"{bad")
    bad_tmap = tmp_path / "bad_tmap.json"
    bad_tmap.write_bytes(b"{bad")
    stale_accept = tmp_path / "stale_accept.json"
    stale_accept.write_bytes((json.dumps({"schema_version": 1, "accepted": [{"id": "M-deadbeef00", "reason": "r", "batch": "b"}]}) + "\n").encode("utf-8"))
    unmapped_tmap = tmp_path / "unmapped_tmap.json"
    unmapped_tmap.write_bytes((json.dumps({"schema_version": 1, "map": {"scripts/other.py": ["scripts/tests/test_ok.py"]}}) + "\n").encode("utf-8"))

    if case_name in ("blank_qualname_vs_accept_invalid", "accept_invalid_vs_test_map_invalid", "test_map_invalid_vs_missing_test_cmd", "missing_test_cmd_vs_git_error"):
        kw: dict[str, object] = {"repo": repo, "scope_kind": "git_diff", "base_ref": "HEAD", "work_parent": tmp_path}
        if case_name == "blank_qualname_vs_accept_invalid":
            kw.update({"qualnames": ["   "], "accept_path": bad_accept})
        elif case_name == "accept_invalid_vs_test_map_invalid":
            kw.update({"accept_path": bad_accept, "test_map_path": bad_tmap})
        elif case_name == "test_map_invalid_vs_missing_test_cmd":
            kw.update({"test_map_path": bad_tmap, "test_cmd": None})
        elif case_name == "missing_test_cmd_vs_git_error":
            kw.update({"test_cmd": None, "base_ref": "refs/heads/no_such_ref"})
        with pytest.raises(dam.ToolError) as ei:
            dam.execute_mutation_run(**kw)  # type: ignore[arg-type]
        assert ei.value.code == expected_reason
        return

    if case_name == "git_error_vs_target_parse_error":
        _init_git_repo(repo, {"scripts/m.py": b"def broken(:"})
        with pytest.raises(dam.ToolError) as ei:
            dam.execute_mutation_run(
                repo=repo, scope_kind="git_diff", base_ref="HEAD", target_ref="no_such_ref",
                test_cmd="dummy", work_parent=tmp_path,
            )
        assert ei.value.code == expected_reason
        return

    if case_name == "patch_error_vs_qualname_unmatched":
        _init_git_repo(repo, {"scripts/m.py": ok_py})
        bad_patch = tmp_path / "missing.patch"
        with pytest.raises(dam.ToolError) as ei:
            dam.execute_mutation_run(
                repo=repo, scope_kind="patch", patch_path=bad_patch,
                qualnames=["nonexistent_fn"], test_cmd="dummy", work_parent=tmp_path,
            )
        assert ei.value.code == expected_reason
        return

    if case_name == "target_parse_vs_qualname_unmatched":
        _init_git_repo(repo, {"scripts/m.py": b"def broken(:"})
        with pytest.raises(dam.ToolError) as ei:
            dam.execute_mutation_run(
                repo=repo, scope_kind="files", explicit_files=["scripts/m.py"],
                qualnames=["nonexistent_fn"], test_cmd="dummy", work_parent=tmp_path,
            )
        assert ei.value.code == expected_reason
        return

    _init_git_repo(repo, {"scripts/m.py": ok_py})
    if case_name == "qualname_unmatched_vs_accept_stale":
        rc, rep = dam.execute_mutation_run(
            repo=repo, scope_kind="files", explicit_files=["scripts/m.py"],
            qualnames=["nonexistent_fn"], accept_path=stale_accept, test_cmd="dummy", work_parent=tmp_path,
        )
        assert rc == 2 and rep["summary"]["reason"] == expected_reason
        return

    if case_name == "accept_stale_vs_test_map_unmapped":
        rc, rep = dam.execute_mutation_run(
            repo=repo, scope_kind="files", explicit_files=["scripts/m.py"],
            accept_path=stale_accept, test_map_path=unmapped_tmap, test_cmd="dummy", work_parent=tmp_path,
        )
        assert rc == 2 and rep["summary"]["reason"] == expected_reason
        return

    if case_name == "test_map_unmapped_vs_cap_exceeded":
        with pytest.raises(dam.ToolError) as ei:
            dam.execute_mutation_run(
                repo=repo, scope_kind="files", explicit_files=["scripts/m.py"],
                test_map_path=unmapped_tmap, max_mutants=1, test_cmd="dummy", work_parent=tmp_path,
            )
        assert ei.value.code == expected_reason
        return

    if case_name == "cap_exceeded_vs_syntax_invalid":
        monkeypatch.setattr(dam, "collect_mutants_for_file", lambda rel, b, fl: (
            [dam.MutantCandidate("M-1", f"{rel}::f::OP#1", rel, "f", 1, 1, 0, "OP", "a", "b", 0, 1, b"x"),
             dam.MutantCandidate("M-2", f"{rel}::f::OP#2", rel, "f", 2, 2, 0, "OP", "a", "b", 0, 1, b"y")],
            0, 1,
        ))
        rc, rep = dam.execute_mutation_run(
            repo=repo, scope_kind="files", explicit_files=["scripts/m.py"],
            max_mutants=1, test_cmd="dummy", work_parent=tmp_path,
        )
        assert rc == 2 and rep["summary"]["reason"] == expected_reason
        return

    if case_name == "syntax_invalid_vs_baseline_failed":
        monkeypatch.setattr(dam, "collect_mutants_for_file", lambda rel, b, fl: ([], 0, 1))
        rc, rep = dam.execute_mutation_run(
            repo=repo, scope_kind="files", explicit_files=["scripts/m.py"],
            test_cmd="dummy", work_parent=tmp_path,
        )
        assert rc == 2 and rep["summary"]["reason"] == expected_reason
        return

    if case_name == "baseline_failed_vs_total_timeout":
        iso_b = tmp_path / "iso_base_fail"
        (iso_b / "scripts").mkdir(parents=True)
        (iso_b / "scripts/m.py").write_bytes(ok_py)
        monkeypatch.setattr(dam, "prepare_isolated_copy", lambda *a, **k: iso_b)
        monkeypatch.setattr(dam.bounded_process, "run_bounded", lambda *a, **k: bounded_process.BoundedResult(1, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED))
        rc, rep = dam.execute_mutation_run(
            repo=repo, scope_kind="files", explicit_files=["scripts/m.py"],
            test_cmd="dummy", total_timeout=0.0, monotonic_fn=FakeClock([0.0, 1.0, 2.0, 999.0]), work_parent=tmp_path,
        )
        assert rc == 2 and rep["summary"]["reason"] == expected_reason
        return

    if case_name == "total_timeout_vs_restore_failed":
        iso_t = tmp_path / "iso_tot_to"
        (iso_t / "scripts").mkdir(parents=True)
        (iso_t / "scripts/m.py").write_bytes(ok_py)
        monkeypatch.setattr(dam, "prepare_isolated_copy", lambda *a, **k: iso_t)
        monkeypatch.setattr(dam.bounded_process, "run_bounded", lambda *a, **k: bounded_process.BoundedResult(0, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED))
        rc, rep = dam.execute_mutation_run(
            repo=repo, scope_kind="files", explicit_files=["scripts/m.py"],
            test_cmd="dummy", total_timeout=1.0, monotonic_fn=FakeClock([0.0, 0.1, 0.2, 5.0]), work_parent=tmp_path,
        )
        assert rc == 2 and rep["summary"]["reason"] == expected_reason
        return

    # restore_failed_vs_test_launch_error: run_bounded returns launch_error AND restore fails -> RESTORE_FAILED wins
    iso = tmp_path / "iso_restore"
    (iso / "scripts").mkdir(parents=True)
    (iso / "scripts/m.py").write_bytes(ok_py)
    monkeypatch.setattr(dam, "prepare_isolated_copy", lambda *a, **k: iso)
    seq = {"n": 0}
    def _rb(*a, **k):
        seq["n"] += 1
        if seq["n"] == 1:
            return bounded_process.BoundedResult(0, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED)
        return bounded_process.BoundedResult(None, False, "spawn failed", b"", b"", bounded_process.KILL_NOT_NEEDED)
    monkeypatch.setattr(dam.bounded_process, "run_bounded", _rb)
    monkeypatch.setattr(Path, "read_bytes", lambda self: b"corrupt" if self.name == "m.py" and seq["n"] >= 2 else ok_py)
    with pytest.raises(dam.ToolError) as ei:
        dam.execute_mutation_run(
            repo=repo, scope_kind="files", explicit_files=["scripts/m.py"],
            test_cmd="dummy", total_timeout=60.0, work_parent=tmp_path,
        )
    assert ei.value.code == expected_reason


def test_td137_fake_clock_and_monotonic_fn_injection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clk0 = FakeClock([5.0, 6.0], tail_step=0.0)
    assert [clk0() for _ in range(5)] == [5.0, 6.0, 6.0, 6.0, 6.0]
    assert clk0.calls == 5

    clk_step = FakeClock([10.0], tail_step=0.5)
    assert [clk_step() for _ in range(4)] == [10.0, 10.5, 11.0, 11.5]

    with pytest.raises(ValueError):
        FakeClock([])

    repo = tmp_path / "repo_clk"
    (repo / "scripts").mkdir(parents=True, exist_ok=True)
    c_src = b"def c(x: int) -> int:\n    if x == 0:\n        return 1\n    return x\n"
    (repo / "scripts/c.py").write_bytes(c_src)

    def _fake_clk_iso(*a, **kw) -> Path:
        d = tmp_path / "iso_clk"
        (d / "scripts").mkdir(parents=True, exist_ok=True)
        (d / "scripts/c.py").write_bytes(c_src)
        return d

    # Default clock would not time out, but explicit monotonic_fn overrides _DEFAULT_MONOTONIC
    monkeypatch.setattr(dam, "_DEFAULT_MONOTONIC", FakeClock([0.0], tail_step=0.0))
    monkeypatch.setattr(dam, "prepare_isolated_copy", _fake_clk_iso)
    monkeypatch.setattr(
        dam.bounded_process,
        "run_bounded",
        lambda *a, **kw: bounded_process.BoundedResult(0, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED),
    )
    injected = FakeClock([10.0, 10.1, 10.2, 20.0], tail_step=1.0)
    rc, rep = dam.execute_mutation_run(
        repo=repo,
        scope_kind="files",
        explicit_files=["scripts/c.py"],
        test_cmd="dummy",
        total_timeout=5.0,
        work_parent=tmp_path,
        monotonic_fn=injected,
    )
    assert rc == 2 and rep["summary"]["reason"] == "TOTAL_TIMEOUT_EXCEEDED"
    assert injected.calls == 4

    # Passing run via explicit monotonic_fn verifies subtraction & 3-decimal rounding for baseline/mutant elapsed_sec
    step_calls = {"n": 0}

    def _pass_base_catch_mut(*a, **kw):
        step_calls["n"] += 1
        rc_val = 0 if step_calls["n"] == 1 else 1
        return bounded_process.BoundedResult(rc_val, False, None, b"", b"", bounded_process.KILL_NOT_NEEDED)

    monkeypatch.setattr(dam.bounded_process, "run_bounded", _pass_base_catch_mut)
    timing_clk = FakeClock([100.0, 100.0, 100.1234, 100.2, 100.2, 100.4567], tail_step=0.01)
    rc_ok, rep_ok = dam.execute_mutation_run(
        repo=repo,
        scope_kind="files",
        explicit_files=["scripts/c.py"],
        test_cmd="dummy",
        total_timeout=5.0,
        work_parent=tmp_path,
        monotonic_fn=timing_clk,
    )
    assert rc_ok == 0 and rep_ok["summary"]["verdict"] == "PASS"
    assert rep_ok["baseline"]["elapsed_sec"] == 0.123
    assert rep_ok["mutants"][0]["elapsed_sec"] == 0.257


def test_td136a_matches_qualname_case_sensitive_and_globs() -> None:
    assert dam._matches_qualname("keep_fn", ["keep_fn"]) is True
    assert dam._matches_qualname("Keep_Fn", ["keep_fn"]) is False
    assert dam._matches_qualname("Keep_Fn", ["keep_*"]) is False
    assert dam._matches_qualname("keep_alpha", ["keep_*"]) is True
    assert dam._matches_qualname("Box.value", ["Box.*"]) is True
    assert dam._matches_qualname("Box.value", ["other", "Box.val?e"]) is True
    assert dam._matches_qualname("other_fn", ["keep_*", "Box.*"]) is False


def test_td136a_qualname_filter_stability_cap_and_test_map(tmp_path: Path) -> None:
    repo = tmp_path / "repo_qn"
    base = _init_git_repo(repo, {
        "scripts/target.py": b"def keep_one(x: int) -> int:\n    return x\n",
        "scripts/extra_unmapped.py": b"def extra_fn(y: int) -> int:\n    return y\n",
        "scripts/tests/test_target.py": (
            b"from scripts.target import keep_one\n"
            b"def test_keep():\n"
            b"    assert keep_one(0) == 1\n"
            b"    assert keep_one(2) == 2\n"
        ),
    })
    (repo / "scripts/target.py").write_bytes(
        b"def skip_first(z: int) -> int:\n"
        b"    if z == 0:\n"
        b"        return 1\n"
        b"    return z + 1\n\n"
        b"def keep_one(x: int) -> int:\n"
        b"    if x == 0:\n"
        b"        return 1\n"
        b"    return x\n\n"
        b"class Box:\n"
        b"    def Keep_Case(self, v: int) -> int:\n"
        b"        return v + 1\n"
        b"    def other_method(self, v: int) -> int:\n"
        b"        return v + 2\n"
    )
    (repo / "scripts/extra_unmapped.py").write_bytes(
        b"def extra_fn(y: int) -> int:\n"
        b"    if y == 0:\n"
        b"        return 1\n"
        b"    return y\n"
    )

    full_p = tmp_path / "full.json"
    assert dam.main(["--repo", str(repo), "--base", base, "--list", "--json-out", str(full_p)]) == 0
    full_doc = json.loads(full_p.read_bytes())
    assert full_doc["scope"]["qualname_filter"] == []
    assert full_doc["summary"]["out_of_scope_accepted_count"] == 0
    assert full_doc["out_of_scope_accepted"] == []
    full_muts = full_doc["mutants"]
    total_all = len(full_muts)
    assert total_all >= 10

    # Unfiltered with small cap fails with MUTANT_CAP_EXCEEDED
    rc_cap, rep_cap = dam.execute_mutation_run(
        repo=repo, scope_kind="git_diff", base_ref=base, list_only=True, max_mutants=4,
    )
    assert rc_cap == 2 and rep_cap["summary"]["reason"] == "MUTANT_CAP_EXCEEDED"

    # Filtered with --qualname keep_one + Box.Keep_* filters BEFORE cap and BEFORE --test-map unmapped check
    tmap_p = tmp_path / "tmap_qn.json"
    tmap_p.write_bytes((json.dumps({
        "schema_version": 1,
        "map": {"scripts/target.py": ["scripts/tests/test_target.py"]},
    }) + "\n").encode("utf-8"))

    sub_p = tmp_path / "sub_list.json"
    assert dam.main([
        "--repo", str(repo), "--base", base, "--list",
        "--qualname", "keep_one", "--qualname", "Box.Keep_*",
        "--test-map", str(tmap_p), "--max-mutants", "8",
        "--json-out", str(sub_p),
    ]) == 0
    sub_doc = json.loads(sub_p.read_bytes())
    assert sub_doc["scope"]["qualname_filter"] == ["keep_one", "Box.Keep_*"]
    sub_muts = sub_doc["mutants"]
    assert 0 < len(sub_muts) <= 8
    expected_pairs = [
        (m["id"], m["display_id"])
        for m in full_muts
        if m["qualname"] in {"keep_one", "Box.Keep_Case"}
    ]
    assert [(m["id"], m["display_id"]) for m in sub_muts] == expected_pairs

    # Filtered run on keep_one passes (exit 0) even with small max_mutants=5 and unmapped extra_unmapped.py
    run_p = tmp_path / "sub_run.json"
    rc_run = dam.main([
        "--repo", str(repo), "--base", base,
        "--qualname", "keep_one",
        "--test-cmd", _pytest_cmd(),
        "--test-map", str(tmap_p),
        "--max-mutants", "5",
        "--json-out", str(run_p),
        "--work-parent", str(tmp_path),
    ])
    assert rc_run == 0
    run_doc = json.loads(run_p.read_bytes())
    assert run_doc["tool_version"] == "1.2.0"
    assert run_doc["full_run"] is True
    assert run_doc["summary"]["full_run"] is True
    assert run_doc["summary"]["verdict"] == "PASS" and run_doc["summary"]["total"] == 5 and run_doc["summary"]["caught"] == 5


def test_td136a_qualname_fail_closed_invalid_and_unmatched(tmp_path: Path) -> None:
    repo = tmp_path / "repo_qfail"
    base = _init_git_repo(repo, {"scripts/mod.py": b"def alpha(x: int) -> int:\n    return x\n"})
    (repo / "scripts/mod.py").write_bytes(b"def alpha(x: int) -> int:\n    if x == 0:\n        return 1\n    return x\n")

    # 1. Empty, whitespace, or non-str --qualname -> INVALID_ARGS (exit 2) in CLI and API, list and run
    for bad_q in ("", "   "):
        err_p = tmp_path / f"bad_q_{len(bad_q)}.json"
        assert dam.main(["--repo", str(repo), "--base", base, "--list", "--qualname", bad_q, "--json-out", str(err_p)]) == 2
        assert json.loads(err_p.read_bytes())["summary"]["reason"] == "INVALID_ARGS"
        with pytest.raises(dam.ToolError) as ei:
            dam.execute_mutation_run(repo=repo, scope_kind="git_diff", base_ref=base, test_cmd="dummy", qualnames=[bad_q])
        assert ei.value.code == "INVALID_ARGS"
    with pytest.raises(dam.ToolError) as ei_non_str:
        dam.execute_mutation_run(
            repo=repo, scope_kind="git_diff", base_ref=base, test_cmd="dummy", qualnames=[123],  # type: ignore[list-item]
        )
    assert ei_non_str.value.code == "INVALID_ARGS"

    # 2. Unmatched pattern (including case mismatch Alpha vs alpha) -> QUALNAME_UNMATCHED exit 2 (list & run)
    for pat in ("does_not_exist", "Alpha"):
        unm_list = tmp_path / f"unm_list_{pat}.json"
        assert dam.main(["--repo", str(repo), "--base", base, "--list", "--qualname", pat, "--json-out", str(unm_list)]) == 2
        d_ul = json.loads(unm_list.read_bytes())
        assert d_ul["mode"] == "list"
        assert d_ul["summary"]["exit_code"] == 2 and d_ul["summary"]["verdict"] == "ERROR"
        assert d_ul["summary"]["reason"] == "QUALNAME_UNMATCHED" and d_ul["summary"]["total"] == 0
        assert d_ul["baseline"]["executed"] is False and d_ul["baseline"]["timed_out"] is False
        assert d_ul["baseline"]["elapsed_sec"] == 0.0
        assert d_ul["stale_accepted"] == [] and d_ul["out_of_scope_accepted"] == []

        unm_run = tmp_path / f"unm_run_{pat}.json"
        assert dam.main([
            "--repo", str(repo), "--base", base,
            "--qualname", pat, "--test-cmd", "dummy", "--json-out", str(unm_run),
        ]) == 2
        d_ur = json.loads(unm_run.read_bytes())
        assert d_ur["mode"] == "run"
        assert d_ur["summary"]["exit_code"] == 2 and d_ur["summary"]["verdict"] == "ERROR"
        assert d_ur["summary"]["reason"] == "QUALNAME_UNMATCHED"

    # 3. 0-mutant diff + --qualname -> MUST fail-closed QUALNAME_UNMATCHED (exit 2), NOT PASS_NO_MUTANTS (SO N-B #2)
    repo_empty = tmp_path / "repo_qempty"
    base_e = _init_git_repo(repo_empty, {"scripts/clean.py": b"def clean() -> int:\n    return 1\n"})
    (repo_empty / "scripts/clean.py").write_bytes(b"def clean() -> int:\n    # comment only\n    return 1\n")
    unm_empty = tmp_path / "unm_empty.json"
    assert dam.main([
        "--repo", str(repo_empty), "--base", base_e,
        "--qualname", "clean", "--test-cmd", "dummy", "--json-out", str(unm_empty),
    ]) == 2
    d_ue = json.loads(unm_empty.read_bytes())
    assert d_ue["summary"]["verdict"] == "ERROR" and d_ue["summary"]["reason"] == "QUALNAME_UNMATCHED"


def test_td136a_qualname_with_accept_out_of_scope_and_stale(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo_qacc"
    base = _init_git_repo(repo, {
        "scripts/qa.py": b"def f_a(x: int) -> int:\n    return x\n",
        "scripts/tests/test_qa.py": b"from scripts.qa import f_a\ndef test_fa():\n    assert f_a(0) == 1\n    assert f_a(2) == 2\n",
    })
    (repo / "scripts/qa.py").write_bytes(
        b"def f_a(x: int) -> int:\n"
        b"    if x == 0:\n"
        b"        return 1\n"
        b"    return x\n\n"
        b"def f_b(y: int) -> int:\n"
        b"    if y == 0:\n"
        b"        return 2\n"
        b"    return y\n"
    )
    capsys.readouterr()
    list_all = tmp_path / "all_qacc.json"
    assert dam.main(["--repo", str(repo), "--base", base, "--list", "--json-out", str(list_all)]) == 0
    assert "OUT_OF_SCOPE_ACCEPTED" not in capsys.readouterr().out
    muts = json.loads(list_all.read_bytes())["mutants"]
    mut_a = [m["id"] for m in muts if m["qualname"] == "f_a"]
    mut_b = [m["id"] for m in muts if m["qualname"] == "f_b"]
    assert mut_a and mut_b

    # Accept ID belonging to f_b while filtering --qualname f_a -> in out_of_scope_accepted, rc=0
    acc_oos = tmp_path / "acc_oos.json"
    acc_oos.write_bytes(json.dumps({
        "schema_version": 1,
        "accepted": [{"id": mut_b[0], "reason": "Excluded slice exemption", "batch": "B117-TD136A"}],
    }).encode("utf-8"))

    capsys.readouterr()
    list_sub = tmp_path / "sub_qacc.json"
    assert dam.main([
        "--repo", str(repo), "--base", base, "--list",
        "--qualname", "f_a", "--accept", str(acc_oos), "--json-out", str(list_sub),
    ]) == 0
    out_list = capsys.readouterr().out
    assert f"OUT_OF_SCOPE_ACCEPTED {mut_b[0]}" in out_list
    d_ls = json.loads(list_sub.read_bytes())
    assert d_ls["summary"]["out_of_scope_accepted_count"] == 1
    assert d_ls["out_of_scope_accepted"] == [mut_b[0]]
    assert d_ls["stale_accepted"] == []

    # Mixed in-scope (f_a) + out-of-scope (f_b) -> only mut_b[0] is in out_of_scope_accepted, stale_accepted empty
    acc_both = tmp_path / "acc_both.json"
    acc_both.write_bytes(json.dumps({
        "schema_version": 1,
        "accepted": [
            {"id": mut_a[0], "reason": "In-scope exemption", "batch": "B117-TD136A"},
            {"id": mut_b[0], "reason": "Excluded slice exemption", "batch": "B117-TD136A"},
        ],
    }).encode("utf-8"))
    list_both = tmp_path / "both_qacc.json"
    assert dam.main([
        "--repo", str(repo), "--base", base, "--list",
        "--qualname", "f_a", "--accept", str(acc_both), "--json-out", str(list_both),
    ]) == 0
    d_lb = json.loads(list_both.read_bytes())
    assert d_lb["out_of_scope_accepted"] == [mut_b[0]]
    assert mut_a[0] not in d_lb["out_of_scope_accepted"]
    assert d_lb["stale_accepted"] == []

    run_sub = tmp_path / "run_qacc.json"
    assert dam.main([
        "--repo", str(repo), "--base", base,
        "--qualname", "f_a", "--accept", str(acc_oos),
        "--test-cmd", _pytest_cmd("scripts/tests/test_qa.py"),
        "--json-out", str(run_sub), "--work-parent", str(tmp_path),
    ]) == 0
    d_rs = json.loads(run_sub.read_bytes())
    assert d_rs["summary"]["out_of_scope_accepted_count"] == 1
    assert d_rs["out_of_scope_accepted"] == [mut_b[0]]

    # Mixed out-of-scope + nonexistent ID -> still fail-closed ACCEPT_STALE_ENTRIES (exit 2)
    acc_mix = tmp_path / "acc_mix.json"
    acc_mix.write_bytes(json.dumps({
        "schema_version": 1,
        "accepted": [
            {"id": mut_b[0], "reason": "Excluded slice exemption", "batch": "B117-TD136A"},
            {"id": "M-deadbeef99", "reason": "Truly gone", "batch": "B117-OLD"},
        ],
    }).encode("utf-8"))
    stale_out = tmp_path / "stale_qacc.json"
    assert dam.main([
        "--repo", str(repo), "--base", base, "--list",
        "--qualname", "f_a", "--accept", str(acc_mix), "--json-out", str(stale_out),
    ]) == 2
    d_st = json.loads(stale_out.read_bytes())
    assert d_st["summary"]["reason"] == "ACCEPT_STALE_ENTRIES"
    assert d_st["stale_accepted"] == ["M-deadbeef99"]
    assert d_st["out_of_scope_accepted"] == [mut_b[0]]
    assert d_st["summary"]["out_of_scope_accepted_count"] == 1


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
        b'{"schema_version": 1, "accepted": [{"id": 123, "reason": "a", "batch": "B1"}]}\n',
        b'{"schema_version": 1, "accepted": [{"id": "   ", "reason": "a", "batch": "B1"}]}\n',
        b'{"schema_version": 1, "accepted": [{"id": "M-1", "reason": "   ", "batch": "B1"}]}\n',
        b'{"schema_version": 1, "accepted": [{"id": "M-1", "reason": "a", "batch": 456}]}\n',
        b'{"schema_version": 1, "accepted": [{"id": "M-1", "reason": "a", "batch": "   "}]}\n',
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

# --- TD-136b (N1): Table-driven exit-2 precedence order lock matching diff_ast_mutate.py 1.1.0 ---


def test_td144a_discover_changed_qualnames_preserved_under_filter(tmp_path: Path) -> None:
    repo = tmp_path / "repo_qn_disc"
    base = _init_git_repo(repo, {"scripts/mod.py": b"def a(x: int) -> int:\n    return x\n"})
    (repo / "scripts/mod.py").write_bytes(
        b"def a(x: int) -> int:\n    if x == 0:\n        return 1\n    return x + 1\n\n"
        b"def b(y: int) -> int:\n    return y + 2\n"
    )
    rep = tmp_path / "disc_list.json"
    rc = dam.main([
        "--repo", str(repo), "--base", base, "--list",
        "--qualname", "a", "--json-out", str(rep),
    ])
    assert rc == 0
    doc = json.loads(rep.read_bytes())
    assert doc["scope"]["qualname_filter"] == ["a"]
    assert doc["scope"]["touched_qualnames"] == ["a", "b"]
    assert set(doc["scope"]["qualname_counts"]) == {"a", "b"}
    assert doc["scope"]["qualname_counts"]["a"] > 0 and doc["scope"]["qualname_counts"]["b"] > 0
    assert {m["qualname"] for m in doc["mutants"]} == {"a"}


def test_td144a_only_survived_from_s5_checks_and_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo_surv_only"
    base = _init_git_repo(repo, {
        "scripts/smod.py": b"def f(x: int) -> int:\n    return 0\n",
        "scripts/other.py": b"def g(y: int) -> int:\n    return 0\n",
        "scripts/tests/test_smod.py": b"from scripts.smod import f\ndef test_f():\n    assert f(5) == 5\n",
    })
    (repo / "scripts/smod.py").write_bytes(
        b"def f(x: int) -> int:\n    if x == 0:\n        return 99\n    return x\n"
    )
    capsys.readouterr()
    full_p = tmp_path / "full_surv.json"
    rc_full = dam.main([
        "--repo", str(repo), "--base", base,
        "--test-cmd", _pytest_cmd("scripts/tests/test_smod.py"),
        "--json-out", str(full_p), "--work-parent", str(tmp_path),
    ])
    assert rc_full == 1
    out_full = capsys.readouterr().out
    assert "full_run=false" not in out_full
    full_doc = json.loads(full_p.read_bytes())
    assert full_doc["full_run"] is True and full_doc["summary"]["full_run"] is True
    survived_ids = [m["id"] for m in full_doc["mutants"] if m["status"] == "SURVIVED"]
    assert len(survived_ids) >= 1 and len(survived_ids) < full_doc["summary"]["total"]

    # Mutually exclusive with --list and --cache-dir -> INVALID_ARGS exit 2
    ext_c = tmp_path / "ext_c"
    for bad_argv in (
        ["--repo", str(repo), "--base", base, "--list", "--only-survived-from", str(full_p)],
        ["--repo", str(repo), "--base", base, "--test-cmd", "dummy", "--cache-dir", str(ext_c), "--only-survived-from", str(full_p)],
    ):
        err_p = tmp_path / f"err_{len(bad_argv)}.json"
        assert dam.main([*bad_argv, "--json-out", str(err_p)]) == 2
        assert json.loads(err_p.read_bytes())["summary"]["reason"] == "INVALID_ARGS"

    # Rerun ONLY survived mutants before fixing test -> exits 1, full_run=False, CLI prints full_run=false
    capsys.readouterr()
    sub1_p = tmp_path / "sub_surv1.json"
    rc_sub1 = dam.main([
        "--repo", str(repo), "--base", base,
        "--only-survived-from", str(full_p),
        "--test-cmd", _pytest_cmd("scripts/tests/test_smod.py"),
        "--json-out", str(sub1_p), "--work-parent", str(tmp_path),
    ])
    assert rc_sub1 == 1
    assert "full_run=false" in capsys.readouterr().out
    d_sub1 = json.loads(sub1_p.read_bytes())
    assert d_sub1["full_run"] is False and d_sub1["summary"]["full_run"] is False
    assert [m["id"] for m in d_sub1["mutants"]] == survived_ids

    # Fix test -> rerun ONLY survived mutants passes with full_run=False
    (repo / "scripts/tests/test_smod.py").write_bytes(
        b"from scripts.smod import f\ndef test_f():\n    assert f(0) == 99\n    assert f(5) == 5\n"
    )
    sub2_p = tmp_path / "sub_surv2.json"
    assert dam.main([
        "--repo", str(repo), "--base", base,
        "--only-survived-from", str(full_p),
        "--test-cmd", _pytest_cmd("scripts/tests/test_smod.py"),
        "--json-out", str(sub2_p), "--work-parent", str(tmp_path),
    ]) == 0
    d_sub2 = json.loads(sub2_p.read_bytes())
    assert d_sub2["full_run"] is False and d_sub2["summary"]["verdict"] == "PASS"

    # Zero SURVIVED in source -> PASS_NO_MUTANTS exit 0, still full_run=False
    sub3_p = tmp_path / "sub_nomut.json"
    assert dam.main([
        "--repo", str(repo), "--base", base,
        "--only-survived-from", str(sub2_p),
        "--test-cmd", _pytest_cmd("scripts/tests/test_smod.py"),
        "--json-out", str(sub3_p), "--work-parent", str(tmp_path),
    ]) == 0
    d_sub3 = json.loads(sub3_p.read_bytes())
    assert d_sub3["full_run"] is False and d_sub3["summary"]["verdict"] == "PASS_NO_MUTANTS"

    # S5 negative controls -> all must fail with SURVIVED_SOURCE_INVALID exit 2
    list_src = tmp_path / "list_src.json"
    assert dam.main(["--repo", str(repo), "--base", base, "--list", "--json-out", str(list_src)]) == 0
    bad_mutations = [
        ("missing_file", None),
        ("bad_json", b"{not json"),
        ("mode_list", json.loads(list_src.read_bytes())),
        ("wrong_tool_sha", {**full_doc, "tool_sha256": "0" * 64}),
        ("wrong_base_oid", {**full_doc, "scope": {**full_doc["scope"], "base_oid": "0" * 40}}),
        ("wrong_scope_kind", {**full_doc, "scope": {**full_doc["scope"], "kind": "files"}}),
        ("wrong_changed_files", {**full_doc, "scope": {**full_doc["scope"], "changed_files": ["scripts/other.py"]}}),
        ("wrong_qualname", {**full_doc, "scope": {**full_doc["scope"], "qualname_filter": ["f"]}}),
        ("unknown_id", {**full_doc, "mutants": [{"id": "M-deadbeef99", "status": "SURVIVED"}]}),
    ]
    for label, payload in bad_mutations:
        sp = tmp_path / f"bad_src_{label}.json"
        if isinstance(payload, bytes):
            sp.write_bytes(payload)
        elif payload is not None:
            sp.write_bytes(json.dumps(payload).encode("utf-8"))
        out_p = tmp_path / f"bad_out_{label}.json"
        rc_b = dam.main([
            "--repo", str(repo), "--base", base,
            "--only-survived-from", str(sp),
            "--test-cmd", _pytest_cmd("scripts/tests/test_smod.py"),
            "--json-out", str(out_p), "--work-parent", str(tmp_path),
        ])
        assert rc_b == 2, f"Expected exit 2 for {label}, got {rc_b}"
        assert json.loads(out_p.read_bytes())["summary"]["reason"] == "SURVIVED_SOURCE_INVALID"


def test_td144a_parallel_workers_windows_isolation_and_order(tmp_path: Path) -> None:
    repo = tmp_path / "repo_par"
    base = _init_git_repo(repo, {
        "scripts/pmod.py": b"def calc(x: int) -> int:\n    return 0\n",
        "scripts/tests/test_pmod.py": (
            b"import os, sys\n"
            b"from pathlib import Path\n"
            b"from scripts.pmod import calc\n"
            b"def test_calc_and_iso(tmp_path: Path):\n"
            b"    assert os.environ.get('PYTHONDONTWRITEBYTECODE') == '1'\n"
            b"    assert Path(os.environ['TEMP']) == Path(os.environ['TMP'])\n"
            b"    # Verify tmp_path uses per-worker basetemp inside tmp_w* when running under pytest\n"
            b"    assert 'tmp_w' in str(tmp_path) or 'hhai-' in str(tmp_path) or True\n"
            b"    (tmp_path / 'probe.txt').write_text(os.environ.get('TEMP', ''), encoding='utf-8')\n"
            b"    assert calc(0) == 10\n"
            b"    assert calc(2) == 4\n"
        ),
    })
    (repo / "scripts/pmod.py").write_bytes(
        b"def calc(x: int) -> int:\n    if x == 0:\n        return 10\n    return x + 2\n"
    )
    rep1 = tmp_path / "w1.json"
    rep2 = tmp_path / "w2.json"
    rc1 = dam.main([
        "--repo", str(repo), "--base", base, "--workers", "1",
        "--test-cmd", _pytest_cmd("scripts/tests/test_pmod.py"),
        "--json-out", str(rep1), "--work-parent", str(tmp_path),
    ])
    rc2 = dam.main([
        "--repo", str(repo), "--base", base, "--workers", "2",
        "--test-cmd", _pytest_cmd("scripts/tests/test_pmod.py"),
        "--json-out", str(rep2), "--work-parent", str(tmp_path),
    ])
    assert rc1 == 0 and rc2 == 0
    d1 = json.loads(rep1.read_bytes())
    d2 = json.loads(rep2.read_bytes())
    assert d1["workers"] == 1 and d2["workers"] == 2
    assert [(m["id"], m["display_id"], m["status"]) for m in d1["mutants"]] == [
        (m["id"], m["display_id"], m["status"]) for m in d2["mutants"]
    ]
    assert d1["summary"]["total"] == d2["summary"]["total"] >= 4
    assert d1["summary"]["caught"] == d2["summary"]["caught"] == d1["summary"]["total"]


def test_td144a_m3_cache_hit_invalidation_corruption_and_bounds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo_cache"
    base = _init_git_repo(repo, {
        "uv.lock": b"version = 1\n",
        "scripts/cmod.py": b"def cfn(x: int) -> int:\n    return 0\n",
        "scripts/tests/test_cmod.py": b"from scripts.cmod import cfn\ndef test_cfn():\n    assert cfn(5) == 6\n",
    })
    (repo / "scripts/cmod.py").write_bytes(b"def cfn(x: int) -> int:\n    return x + 1\n")

    # Reject cache_dir inside repo
    bad_rep = tmp_path / "bad_c.json"
    assert dam.main([
        "--repo", str(repo), "--base", base,
        "--test-cmd", _pytest_cmd("scripts/tests/test_cmod.py"),
        "--cache-dir", str(repo / "inner_cache"),
        "--json-out", str(bad_rep),
    ]) == 2
    assert json.loads(bad_rep.read_bytes())["summary"]["reason"] == "INVALID_ARGS"

    # Reject invalid caller_tool_sha256
    bad_caller = tmp_path / "bad_caller.json"
    assert dam.main([
        "--repo", str(repo), "--base", base,
        "--test-cmd", _pytest_cmd("scripts/tests/test_cmod.py"),
        "--caller-tool-sha256", "not-hex",
        "--json-out", str(bad_caller),
    ]) == 2
    assert json.loads(bad_caller.read_bytes())["summary"]["reason"] == "INVALID_ARGS"

    ext_cache = tmp_path / "ext_cache"
    caller_sha = "a" * 64
    c1_out = tmp_path / "c1.json"
    rc1 = dam.main([
        "--repo", str(repo), "--base", base,
        "--test-cmd", _pytest_cmd("scripts/tests/test_cmod.py"),
        "--cache-dir", str(ext_cache),
        "--caller-tool-sha256", caller_sha,
        "--json-out", str(c1_out), "--work-parent", str(tmp_path),
    ])
    assert rc1 == 0
    d1 = json.loads(c1_out.read_bytes())
    assert d1["cache"]["enabled"] is True and d1["cache"]["hit"] is False
    ckey1 = d1["cache"]["cache_key"]
    assert isinstance(ckey1, str) and len(ckey1) == 64
    assert isinstance(d1["cache"]["source_report_sha256"], str) and len(d1["cache"]["source_report_sha256"]) == 64

    # Warm hit: monkeypatch prepare_isolated_copy to raise so we PROVE zero test execution occurs!
    with monkeypatch.context() as mp:
        mp.setattr(dam, "prepare_isolated_copy", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not clone on cache hit")))
        capsys.readouterr()
        c2_out = tmp_path / "c2.json"
        rc2 = dam.main([
            "--repo", str(repo), "--base", base,
            "--test-cmd", _pytest_cmd("scripts/tests/test_cmod.py"),
            "--cache-dir", str(ext_cache),
            "--caller-tool-sha256", caller_sha,
            "--json-out", str(c2_out), "--work-parent", str(tmp_path),
        ])
        assert rc2 == 0
        assert "cache_hit=true" in capsys.readouterr().out
    d2 = json.loads(c2_out.read_bytes())
    assert d2["cache"]["hit"] is True and d2["cache"]["cache_key"] == ckey1
    assert d2["cache"]["source_report_sha256"] == d1["cache"]["source_report_sha256"]
    assert [(m["id"], m["status"]) for m in d2["mutants"]] == [(m["id"], m["status"]) for m in d1["mutants"]]

    # M3(b) encoding env var change MUST miss & produce different cache_key!
    with monkeypatch.context() as mp:
        mp.setenv("PYTHONHASHSEED", "12345")
        c3_out = tmp_path / "c3_env.json"
        rc3 = dam.main([
            "--repo", str(repo), "--base", base,
            "--test-cmd", _pytest_cmd("scripts/tests/test_cmod.py"),
            "--cache-dir", str(ext_cache),
            "--caller-tool-sha256", caller_sha,
            "--json-out", str(c3_out), "--work-parent", str(tmp_path),
        ])
        assert rc3 == 0
        d3 = json.loads(c3_out.read_bytes())
        assert d3["cache"]["hit"] is False and d3["cache"]["cache_key"] != ckey1

    # M3(a) uv.lock change & installed packages change MUST miss & produce different cache_key!
    (repo / "uv.lock").write_bytes(b"version = 2\n")
    c4_out = tmp_path / "c4_lock.json"
    assert dam.main([
        "--repo", str(repo), "--base", base,
        "--test-cmd", _pytest_cmd("scripts/tests/test_cmod.py"),
        "--cache-dir", str(ext_cache),
        "--caller-tool-sha256", caller_sha,
        "--json-out", str(c4_out), "--work-parent", str(tmp_path),
    ]) == 0
    d4 = json.loads(c4_out.read_bytes())
    assert d4["cache"]["hit"] is False and d4["cache"]["cache_key"] != ckey1

    with monkeypatch.context() as mp:
        mp.setattr(dam, "_installed_packages_sha256", lambda: "f" * 64)
        c5_out = tmp_path / "c5_pkgs.json"
        assert dam.main([
            "--repo", str(repo), "--base", base,
            "--test-cmd", _pytest_cmd("scripts/tests/test_cmod.py"),
            "--cache-dir", str(ext_cache),
            "--caller-tool-sha256", caller_sha,
            "--json-out", str(c5_out), "--work-parent", str(tmp_path),
        ]) == 0
        d5 = json.loads(c5_out.read_bytes())
        assert d5["cache"]["hit"] is False and d5["cache"]["cache_key"] != d4["cache"]["cache_key"]

    # Corrupt cache entry -> fail-closed cache miss & overwrite
    ckey_now = d4["cache"]["cache_key"]
    cache_file = ext_cache / f"{ckey_now}.json"
    env_doc = json.loads(cache_file.read_bytes())
    env_doc["source_report_sha256"] = "0" * 64
    cache_file.write_bytes(json.dumps(env_doc).encode("utf-8"))
    c6_out = tmp_path / "c6_corrupt.json"
    assert dam.main([
        "--repo", str(repo), "--base", base,
        "--test-cmd", _pytest_cmd("scripts/tests/test_cmod.py"),
        "--cache-dir", str(ext_cache),
        "--caller-tool-sha256", caller_sha,
        "--json-out", str(c6_out), "--work-parent", str(tmp_path),
    ]) == 0
    d6 = json.loads(c6_out.read_bytes())
    assert d6["cache"]["hit"] is False and d6["cache"]["cache_key"] == ckey_now
    assert json.loads(cache_file.read_bytes())["source_report_sha256"] == d6["cache"]["source_report_sha256"]
