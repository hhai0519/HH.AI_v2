# -*- coding: utf-8 -*-
"""
scripts/tests/test_audit_packet.py

Controls for scripts/audit_packet.py (B-115 pending item 5): every fact on a real Git fixture, each input that is
absent reported as MISSING (never MATCH), every probe failure, timeout or malformed input reported as a CONFLICT or
a tool failure, the read-only and isolation guarantees, the pre-issue mode, and the fixed output with no verdict.
All fixtures are written as bytes (exact LF), never through text-mode writes.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import audit_packet as ap  # noqa: E402
import batch_runner as br  # noqa: E402

TASK = "UNIT-SLICE-R1-261010"
BRANCH = "batch/unit-slice-r1-261010"
SUBJECT = "Unit: candidate for the packet fixture"
OK_STUB = b"import sys\nsys.exit(0)\n"
BASE_FILES = {
    "docs/A.md": b"alpha\n",
    "scripts/tool.py": b"print(1)\n",
    "scripts/check_consistency.py": OK_STUB,
    "scripts/execution_record.py": OK_STUB,
    "scripts/fingerprint.py": OK_STUB,
    "scripts/tests/test_ok.py": b"def test_ok():\n    assert True\n",
    "docs/fingerprints/exec-latest.json": b"{}\n",
    "docs/governance/execution-record.json": b"{}\n",
}
FINAL = {"docs/A.md": b"alpha2\n", "scripts/tool.py": b"print(2)\n"}
ALLOWED = sorted(list(FINAL) + list(br.GENERATED))
FOCUSED = {"pytest_args": ["scripts/tests/test_ok.py", "-q", "-p", "no:cacheprovider"], "limit_sec": 60}
ALL_FACTS = list(ap.FACT_IDS)


def _w(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(data)


def _block(name, body):
    return "<<<BEGIN " + name + ">>>\n" + body + "\n<<<END " + name + ">>>\n"


def _allowed(paths):
    return sorted(set(paths) | set(br.GENERATED))


def _record(base, task=TASK, actual=None, allowed=None):
    allowed = ALLOWED if allowed is None else allowed
    return (json.dumps({"schema_version": 1, "task_id": task, "base_oid": base,
                        "plan": {"allowed_paths": allowed, "required_paths": allowed},
                        "actual": {"changed_paths": allowed if actual is None else actual}}, indent=1) + "\n").encode()


class Fx:
    """A real repository: main = base; candidate branches are built from base on demand."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.repo = tmp_path / "repo"
        self.repo.mkdir()
        cfg = tmp_path / "fixture-gitconfig"
        cfg.write_bytes(b"")
        self.env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
        self.env.update({"GIT_CONFIG_GLOBAL": str(cfg), "GIT_CONFIG_NOSYSTEM": "1"})
        self.git("init", "-q", "-b", "main")
        for path, data in BASE_FILES.items():
            _w(self.repo / path, data)
        self.base = self.commit("Base")

    def git(self, *args, cwd=None):
        r = subprocess.run(["git", "-c", "user.name=HH.AI", "-c", "user.email=unit@example.invalid",
                            "-c", "commit.gpgsign=false", *args], cwd=str(cwd or self.repo), env=self.env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert r.returncode == 0, r.stderr
        return r.stdout.decode().strip()

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", msg)
        return self.git("rev-parse", "HEAD")

    def candidate(self, files=None, subject=SUBJECT, parent=None, name="cand"):
        files = dict(FINAL if files is None else files)
        self.git("checkout", "-q", "-b", name, parent or self.base)
        record = files.pop("_record", None)
        if record is None:
            record = _record(self.base, allowed=_allowed(files))
        merged = {"docs/fingerprints/exec-latest.json": b'{"x": 1}\n', br.GENERATED[1]: record}
        merged.update(files)
        for path, data in merged.items():
            if data is None:
                (self.repo / path).unlink()
            else:
                _w(self.repo / path, data)
        oid = self.commit(subject)
        self.git("checkout", "-q", "main")
        return oid

    def prompt(self, kind="production", focused=FOCUSED, authors=None, task=TASK, branch=BRANCH, base=None):
        base = base or self.base
        authors = FINAL if authors is None else authors
        spec = {"schema_version": 1, "task_id": task, "kind": kind, "base_oid": base, "branch": branch,
                "commit_message": SUBJECT, "start": {"mode": "clean"}, "e24": False, "focused": focused,
                "authors": {p: {"source": {"kind": "base"}, "sha256": hashlib.sha256(b).hexdigest()}
                            for p, b in authors.items()}, "ops": []}
        if kind == "promotion":
            spec = {"schema_version": 1, "task_id": task, "kind": "promotion", "base_oid": base,
                    "candidate_oid": "c" * 40, "candidate_branch": branch}
        plan = {"task_id": task, "base_oid": base, "allowed_paths": _allowed(authors), "required_paths": _allowed(authors)}
        text = "prose\n" + _block("BATCH_SPEC_JSON", json.dumps(spec)) + _block("PLAN_JSON", json.dumps(plan))
        path = self.tmp / "prompts" / (task + "-prompt.txt")
        _w(path, text.encode())
        return str(path)

    def refs(self, cand, branch=BRANCH, main=None, extra=()):
        lines = [(main or self.base) + "\tHEAD", (main or self.base) + "\trefs/heads/main"]
        if cand is not None:
            lines.append(cand + "\trefs/heads/" + branch)
        lines += [oid + "\t" + ref for ref, oid in extra]
        path = self.tmp / "refs.txt"
        _w(path, ("\n".join(lines) + "\n").encode())
        return str(path)

    def ci(self, cand, **over):
        data = {"schema_version": 1, "run_id": 101, "head_sha": cand, "head_branch": BRANCH, "event": "push",
                "workflow_name": "Verify", "run_attempt": 1, "status": "completed", "conclusion": "success",
                "jobs": [{"name": "verify", "status": "completed", "conclusion": "success"},
                         {"name": "gateway-windows", "status": "completed", "conclusion": "success"}],
                "raw_markers": {"verify": "ALL 5 GATES PASSED", "gateway-windows": "57 passed"}}
        data.update(over)
        path = self.tmp / "ci.json"
        _w(path, json.dumps(data).encode())
        return str(path)


def _packet(fx, prompt, cand, **kw):
    p = ap.Packet(str(fx.repo), prompt, cand, **kw)
    try:
        return p.build()
    finally:
        p.close()


def _status(result):
    return {f["id"]: f["status"] for f in result["facts"]}


def _detail(result, fid):
    return [f for f in result["facts"] if f["id"] == fid][0]["detail"]


def _code(fn, *a, **kw):
    with pytest.raises(ap.PacketError) as e:
        fn(*a, **kw)
    return str(e.value)


@pytest.fixture
def fx(tmp_path):
    return Fx(tmp_path)


# -- complete packet ------------------------------------------------------------------------------------------

def test_complete_packet_is_all_match_and_carries_no_verdict(fx, tmp_path):
    cand = fx.candidate()
    res = _packet(fx, fx.prompt(), cand, remote_refs=fx.refs(cand), ci=fx.ci(cand), workdir=str(tmp_path / "wd"))
    assert _status(res) == {f: ap.MATCH for f in ALL_FACTS}
    assert res["authority"] == "DATA_ONLY_NOT_A_VERDICT" and res["summary"] == {"conflicts": [], "missing": []}
    assert "verdict" not in res and "PASS" not in json.dumps(res)
    assert res["ci_origin"] == "AUDITOR_PROVIDED" and res["mode"] == "candidate"
    assert _detail(res, "K_FOCUSED")["totals"].startswith("1 passed")


def test_absent_inputs_are_missing_never_match(fx):
    cand = fx.candidate()
    st = _status(_packet(fx, fx.prompt(), cand))
    for fid in ALL_FACTS:
        assert st[fid] == (ap.MISSING if fid[0] in "RKI" else ap.MATCH)


# -- repository facts -----------------------------------------------------------------------------------------

def test_parent_other_than_base_is_a_conflict(fx):
    other = fx.candidate(files={"docs/A.md": b"x\n"}, name="side")
    cand = fx.candidate(parent=other, name="cand2")
    res = _packet(fx, fx.prompt(), cand)
    assert _status(res)["C_PARENT"] == ap.CONFLICT and _detail(res, "C_PARENT")["parents"] == [other]


def test_merge_commit_with_base_among_its_parents_is_a_conflict(fx):
    side = fx.candidate(name="side")
    fx.git("checkout", "-q", "-b", "merged", fx.base)
    fx.git("merge", "-q", "--no-ff", "-m", SUBJECT, side)
    merged = fx.git("rev-parse", "HEAD")
    fx.git("checkout", "-q", "main")
    res = _packet(fx, fx.prompt(), merged)
    assert _status(res)["C_PARENT"] == ap.CONFLICT and _detail(res, "C_PARENT")["parents"] == [fx.base, side]


def test_subject_other_than_the_spec_message_is_a_conflict(fx):
    cand = fx.candidate(subject="Something else")
    assert _status(_packet(fx, fx.prompt(), cand))["C_SUBJECT"] == ap.CONFLICT


def test_extra_and_missing_paths_are_conflicts_with_their_lists(fx):
    files = dict(FINAL)
    files["docs/B.md"] = b"extra\n"
    cand = fx.candidate(files=files, name="extra")
    res = _packet(fx, fx.prompt(), cand)
    assert _status(res)["C_PATHS"] == ap.CONFLICT and _detail(res, "C_PATHS")["extra"] == ["docs/B.md"]
    cand2 = fx.candidate(files={"docs/A.md": FINAL["docs/A.md"]}, name="missing")
    res2 = _packet(fx, fx.prompt(), cand2)
    assert _status(res2)["C_PATHS"] == ap.CONFLICT and _detail(res2, "C_PATHS")["missing"] == ["scripts/tool.py"]


def test_author_hash_mismatch_and_absent_author_are_conflicts(fx):
    cand = fx.candidate(files={"docs/A.md": b"alpha3\n", "scripts/tool.py": FINAL["scripts/tool.py"]})
    res = _packet(fx, fx.prompt(), cand)
    assert _status(res)["C_AUTHOR_HASHES"] == ap.CONFLICT
    assert _detail(res, "C_AUTHOR_HASHES") == {"mismatched": ["docs/A.md"], "checked": 2}
    gone = fx.candidate(files={"docs/A.md": None, "scripts/tool.py": FINAL["scripts/tool.py"]}, name="gone")
    assert _detail(_packet(fx, fx.prompt(), gone), "C_AUTHOR_HASHES")["mismatched"] == ["docs/A.md"]


def test_author_path_that_is_a_link_counts_as_absent(fx):
    fx.git("checkout", "-q", "-b", "linkcand", fx.base)
    for path, data in FINAL.items():
        _w(fx.repo / path, data)
    _w(fx.repo / "docs/fingerprints/exec-latest.json", b'{"x": 1}\n')
    _w(fx.repo / br.GENERATED[1], _record(fx.base))
    fx.git("add", "-A")
    blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=str(fx.repo), env=fx.env, input=b"alpha2\n",
                          stdout=subprocess.PIPE, check=True).stdout.decode().strip()
    fx.git("update-index", "--cacheinfo", "120000," + blob + ",docs/A.md")
    fx.git("commit", "-q", "-m", SUBJECT)
    cand = fx.git("rev-parse", "HEAD")
    fx.git("reset", "-q", "--hard")
    fx.git("checkout", "-q", "main")
    res = _packet(fx, fx.prompt(), cand)
    assert _status(res)["C_AUTHOR_HASHES"] == ap.CONFLICT and _detail(res, "C_AUTHOR_HASHES")["mismatched"] == ["docs/A.md"]


def test_author_hash_is_lf_normalized_like_the_runner(fx):
    cand = fx.candidate(files={"docs/A.md": b"alpha2\r\n", "scripts/tool.py": FINAL["scripts/tool.py"]})
    assert _status(_packet(fx, fx.prompt(), cand))["C_AUTHOR_HASHES"] == ap.MATCH


def test_whitespace_error_fails_diff_check(fx):
    cand = fx.candidate(files={"docs/A.md": b"alpha2 \n", "scripts/tool.py": FINAL["scripts/tool.py"]})
    res = _packet(fx, fx.prompt(authors={"docs/A.md": b"alpha2 \n", "scripts/tool.py": FINAL["scripts/tool.py"]}), cand)
    assert _status(res)["C_DIFF_CHECK"] == ap.CONFLICT and _detail(res, "C_DIFF_CHECK")["exit_code"] != 0


@pytest.mark.parametrize("record", [
    None,
    b"not json\n",
    b"[]\n",
    "WRONG_TASK",
    "WRONG_ACTUAL",
])
def test_execution_record_must_bind_task_base_plan_and_actual(fx, record):
    files = dict(FINAL)
    if record is None:
        files[br.GENERATED[1]] = None
        files["_record"] = b"{}\n"
    elif record == "WRONG_TASK":
        files["_record"] = _record(fx.base, task="OTHER-261010")
    elif record == "WRONG_ACTUAL":
        files["_record"] = _record(fx.base, actual=ALLOWED[:-1])
    else:
        files["_record"] = record
    cand = fx.candidate(files=files)
    assert _status(_packet(fx, fx.prompt(), cand))["C_EXEC_RECORD"] == ap.CONFLICT


def test_shallow_repository_is_a_conflict(fx, tmp_path):
    cand = fx.candidate()
    shallow = tmp_path / "shallow"
    fx.git("clone", "-q", "--depth", "2", "--branch", "cand", fx.repo.as_uri(), str(shallow), cwd=tmp_path)
    p = ap.Packet(str(shallow), fx.prompt(), cand)
    try:
        assert _status(p.build())["C_FULL_CLONE"] == ap.CONFLICT
    finally:
        p.close()


def test_unknown_base_or_candidate_makes_the_tool_fail(fx):
    cand = fx.candidate()
    assert _code(_packet, fx, fx.prompt(), "d" * 40) == "CANDIDATE_NOT_IN_REPO"
    assert _code(_packet, fx, fx.prompt(base="e" * 40), cand) == "BASE_NOT_IN_REPO"
    assert _code(ap.Packet, str(fx.repo), fx.prompt(), "short") == "CANDIDATE_INVALID"


# -- remote facts ---------------------------------------------------------------------------------------------

def test_remote_branch_main_and_siblings(fx):
    cand = fx.candidate()
    st = _status(_packet(fx, fx.prompt(), cand, remote_refs=fx.refs(None)))
    assert st["R_BRANCH"] == ap.CONFLICT
    st = _status(_packet(fx, fx.prompt(), cand, remote_refs=fx.refs(fx.base)))
    assert st["R_BRANCH"] == ap.CONFLICT
    res = _packet(fx, fx.prompt(), cand, remote_refs=fx.refs(cand, main=cand))
    assert _status(res)["R_MAIN"] == ap.CONFLICT and _detail(res, "R_MAIN")["at"] == "candidate"
    res = _packet(fx, fx.prompt(), cand, remote_refs=fx.refs(cand, main=cand), expect_main="candidate")
    assert _status(res)["R_MAIN"] == ap.MATCH


@pytest.mark.parametrize("sibling,flagged", [
    ("batch/unit-slice-261010", True),
    ("batch/unit-slice-r2-261010", True),
    ("batch/unit-slice-r1-261011", True),
    ("batch/unit-slice-two-r1-261010", False),
    ("batch/other-slice-r1-261010", False),
])
def test_sibling_revisions_of_the_same_slice_are_conflicts(fx, sibling, flagged):
    cand = fx.candidate()
    res = _packet(fx, fx.prompt(), cand, remote_refs=fx.refs(cand, extra=[("refs/heads/" + sibling, fx.base)]))
    assert _status(res)["R_SIBLINGS"] == (ap.CONFLICT if flagged else ap.MATCH)
    assert _detail(res, "R_SIBLINGS")["siblings"] == ([sibling] if flagged else [])


DUPLICATE_MAIN = ("a" * 40 + "\trefs/heads/main\n" + "b" * 40 + "\trefs/heads/main\n").encode()


@pytest.mark.parametrize("text", [b"", b"zz\trefs/heads/main\n", b"a" * 40 + b" refs/heads/main\n",
                                  DUPLICATE_MAIN, b"\xff\xfe"])
def test_malformed_remote_refs_make_the_tool_fail(fx, tmp_path, text):
    cand = fx.candidate()
    path = tmp_path / "bad-refs.txt"
    path.write_bytes(text)
    assert _code(_packet, fx, fx.prompt(), cand, remote_refs=str(path)) in ("REMOTE_REFS_INVALID", "REMOTE_REFS_UNREADABLE")


# -- CI facts -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("over", [
    {"head_sha": "f" * 40}, {"head_branch": "main"}, {"event": "pull_request"}, {"workflow_name": "Other"},
    {"status": "in_progress"}, {"conclusion": "failure"}, {"run_id": "101"}, {"run_id": True}, {"run_attempt": 0},
])
def test_ci_run_fields_must_bind_the_candidate(fx, over):
    cand = fx.candidate()
    assert _status(_packet(fx, fx.prompt(), cand, ci=fx.ci(cand, **over)))["I_RUN"] == ap.CONFLICT


def test_ci_branch_override_for_post_main_runs(fx):
    cand = fx.candidate()
    res = _packet(fx, fx.prompt(), cand, ci=fx.ci(cand, head_branch="main"), ci_branch="main")
    assert _status(res)["I_RUN"] == ap.MATCH


@pytest.mark.parametrize("jobs", [
    [{"name": "verify", "status": "completed", "conclusion": "success"}],
    [{"name": "verify", "status": "completed", "conclusion": "success"},
     {"name": "gateway-windows", "status": "completed", "conclusion": "failure"}],
    [{"name": "verify", "status": "completed", "conclusion": "success"},
     {"name": "verify", "status": "completed", "conclusion": "success"},
     {"name": "gateway-windows", "status": "completed", "conclusion": "success"}],
    "jobs",
    ["x"],
])
def test_ci_jobs_need_exactly_one_successful_verify_and_gateway(fx, jobs):
    cand = fx.candidate()
    assert _status(_packet(fx, fx.prompt(), cand, ci=fx.ci(cand, jobs=jobs)))["I_JOBS"] == ap.CONFLICT


@pytest.mark.parametrize("markers,status", [
    (None, "MISSING"), ({}, "MISSING"),
    ({"verify": "ALL 4 GATES PASSED", "gateway-windows": "57 passed"}, "CONFLICT"),
    ({"verify": "ALL 5 GATES PASSED", "gateway-windows": "1 failed, 56 passed"}, "CONFLICT"),
    ({"verify": "ALL 5 GATES PASSED", "gateway-windows": "0 passed"}, "CONFLICT"),
    ({"verify": "ALL 5 GATES PASSED"}, "CONFLICT"),
])
def test_raw_log_markers_are_never_inferred(fx, markers, status):
    cand = fx.candidate()
    assert _status(_packet(fx, fx.prompt(), cand, ci=fx.ci(cand, raw_markers=markers)))["I_RAW_MARKERS"] == status


@pytest.mark.parametrize("text,code", [(b"{", "CI_UNREADABLE"), (b"[]", "CI_SCHEMA_INVALID"),
                                       (b'{"schema_version": 2}', "CI_SCHEMA_INVALID")])
def test_malformed_ci_input_makes_the_tool_fail(fx, tmp_path, text, code):
    cand = fx.candidate()
    path = tmp_path / "bad-ci.json"
    path.write_bytes(text)
    assert _code(_packet, fx, fx.prompt(), cand, ci=str(path)) == code


# -- local checks (fault injection) ---------------------------------------------------------------------------

@pytest.mark.parametrize("path,data,fid", [
    ("scripts/check_consistency.py", b"import sys\nsys.exit(1)\n", "K_CHECK_CONSISTENCY"),
    ("scripts/execution_record.py", b"import no_such_module_for_the_fixture\n", "K_EXECUTION_RECORD_VERIFY"),
    ("scripts/fingerprint.py", b"raise SystemExit(3)\n", "K_FINGERPRINT_VERIFY"),
    ("scripts/tests/test_ok.py", b"def test_ok():\n    assert False\n", "K_FOCUSED"),
])
def test_failing_check_is_a_conflict(fx, tmp_path, path, data, fid):
    files = dict(FINAL)
    files[path] = data
    cand = fx.candidate(files=files)
    res = _packet(fx, fx.prompt(authors=files), cand, workdir=str(tmp_path / "wd"))
    assert _status(res)[fid] == ap.CONFLICT
    others = [f for f in ("K_CHECK_CONSISTENCY", "K_EXECUTION_RECORD_VERIFY", "K_FINGERPRINT_VERIFY", "K_FOCUSED")
              if f != fid]
    assert all(_status(res)[f] == ap.MATCH for f in others)


def test_checks_never_run_unverified_candidate_content(fx, tmp_path):
    files = dict(FINAL)
    files["scripts/check_consistency.py"] = b"import sys\nsys.exit(0)\n# changed\n"
    cand = fx.candidate(files=files)
    wd = tmp_path / "wd"
    res = _packet(fx, fx.prompt(), cand, workdir=str(wd))
    for fid in ("K_CHECK_CONSISTENCY", "K_EXECUTION_RECORD_VERIFY", "K_FINGERPRINT_VERIFY", "K_FOCUSED"):
        assert _status(res)[fid] == ap.MISSING and _detail(res, fid) == {"skipped": "CONTENT_NOT_VERIFIED"}
    assert list(wd.iterdir()) == []
    bad_hash = fx.candidate(files={"docs/A.md": b"other\n", "scripts/tool.py": FINAL["scripts/tool.py"]}, name="hash")
    res = _packet(fx, fx.prompt(), bad_hash, workdir=str(tmp_path / "wd2"))
    assert _status(res)["K_FOCUSED"] == ap.MISSING


def test_check_timeout_is_a_conflict(fx, tmp_path):
    files = dict(FINAL)
    files["scripts/check_consistency.py"] = b"import time\ntime.sleep(60)\n"
    cand = fx.candidate(files=files)
    res = _packet(fx, fx.prompt(authors=files), cand, workdir=str(tmp_path / "wd"), check_timeout=3)
    assert _status(res)["K_CHECK_CONSISTENCY"] == ap.CONFLICT
    assert _detail(res, "K_CHECK_CONSISTENCY")["exit_code"] in (124, 125)


def test_focused_without_a_totals_line_is_a_conflict(fx, tmp_path):
    cand = fx.candidate()
    prompt = fx.prompt(focused={"pytest_args": ["--version"], "limit_sec": 60})
    res = _packet(fx, prompt, cand, workdir=str(tmp_path / "wd"))
    assert _status(res)["K_FOCUSED"] == ap.CONFLICT and _detail(res, "K_FOCUSED")["totals"] is None


def test_batch_without_focused_tests_reports_none(fx, tmp_path):
    cand = fx.candidate()
    res = _packet(fx, fx.prompt(focused=None), cand, workdir=str(tmp_path / "wd"))
    assert _status(res)["K_FOCUSED"] == ap.MATCH and _detail(res, "K_FOCUSED") == {"focused": "NONE"}


@pytest.mark.parametrize("line,ok", [
    ("3 passed in 0.10s", True), ("3 passed, 1 skipped in 0.10s", True), ("1 failed, 2 passed in 0.1s", False),
    ("2 passed, 1 error in 0.1s", False), ("2 passed, 1 xpassed in 0.1s", False), ("1 skipped in 0.1s", False),
])
def test_focused_totals_need_passes_and_no_failure(line, ok):
    assert (ap.PYTEST_TOTALS.match(line) is not None and " passed" in " " + line
            and not ap.PYTEST_BAD.search(line)) == ok


def test_workdir_must_be_new_or_empty_and_outside_the_repository(fx, tmp_path):
    cand = fx.candidate()
    assert _code(_packet, fx, fx.prompt(), cand, workdir=str(fx.repo / "inside")) == "WORKDIR_OVERLAPS_REPO"
    full = tmp_path / "full"
    _w(full / "x", b"x")
    assert _code(_packet, fx, fx.prompt(), cand, workdir=str(full)) == "WORKDIR_NOT_EMPTY"


# -- probe failures, isolation and read-only ------------------------------------------------------------------

@pytest.mark.parametrize("needle", ["--name-only", "ls-tree", "rev-parse", "log"])
def test_git_probe_failure_makes_the_tool_fail_never_match(fx, needle):
    cand = fx.candidate()

    def failing(args, cwd, env, timeout):
        if needle in args:
            return 128, b""
        return ap.default_run(args, cwd, env, timeout)
    assert _code(_packet, fx, fx.prompt(), cand, run=failing) in ("GIT_FAILED", "BASE_NOT_IN_REPO")


def test_blob_read_failure_makes_the_tool_fail(fx):
    cand = fx.candidate()

    def failing(args, cwd, env, timeout):
        if "blob" in args:
            return 128, b""
        return ap.default_run(args, cwd, env, timeout)
    assert _code(_packet, fx, fx.prompt(), cand, run=failing) == "BLOB_UNREADABLE"


def test_diff_check_probe_failure_is_a_conflict(fx):
    cand = fx.candidate()

    def failing(args, cwd, env, timeout):
        if "--check" in args:
            return 124, b""
        return ap.default_run(args, cwd, env, timeout)
    assert _status(_packet(fx, fx.prompt(), cand, run=failing))["C_DIFF_CHECK"] == ap.CONFLICT


def test_default_run_never_raises_and_reports_timeout_and_launch_failure(tmp_path):
    assert ap.default_run([sys.executable, "-c", "import time; time.sleep(30)"], str(tmp_path), None, 2)[0] in (124, 125)
    assert ap.default_run([str(tmp_path / "no-such-program")], str(tmp_path), None, 5)[0] == 127


def _snapshot(root):
    entries = []
    for base, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(dirs) + sorted(files):
            st = os.lstat(os.path.join(base, name))
            entries.append((os.path.relpath(os.path.join(base, name), root), st.st_mode, st.st_size,
                            st.st_mtime_ns, st.st_ctime_ns))
    return entries


def test_repository_is_left_unchanged(fx, tmp_path):
    cand = fx.candidate()
    before = _snapshot(fx.repo)
    _packet(fx, fx.prompt(), cand, remote_refs=fx.refs(cand), ci=fx.ci(cand), workdir=str(tmp_path / "wd"))
    assert _snapshot(fx.repo) == before


def test_inherited_git_variables_and_global_configuration_are_ignored(fx, tmp_path, monkeypatch):
    cand = fx.candidate()
    # A global configuration that would change what git prints (commit subjects re-encoded as UTF-16).
    hostile = b"[i18n]\n\tlogOutputEncoding = UTF-16LE\n[core]\n\tautocrlf = true\n"
    home = tmp_path / "hostile-home"
    _w(home / ".gitconfig", hostile)
    _w(home / "xdg" / "git" / "config", hostile)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "xdg"))
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "nowhere"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "nowhere-index"))
    res = _packet(fx, fx.prompt(), cand, workdir=str(tmp_path / "wd"))
    assert all(_status(res)[f] == ap.MATCH for f in ALL_FACTS if f[0] in "CK")


# -- prompt input ---------------------------------------------------------------------------------------------

def test_prompt_kind_name_and_spec_are_checked(fx, tmp_path):
    cand = fx.candidate()
    assert _code(_packet, fx, fx.prompt(kind="promotion"), cand) == "KIND_UNSUPPORTED"
    bad = tmp_path / "nameless.txt"
    bad.write_bytes(b"x")
    assert _code(_packet, fx, str(bad), cand) == "PROMPT_NAME_INVALID"
    broken = tmp_path / "p" / (TASK + "-prompt.txt")
    _w(broken, b"no blocks\n")
    assert _code(_packet, fx, str(broken), cand) == "PROMPT_UNREADABLE"
    assert _code(_packet, fx, fx.prompt(branch="Not-A-Batch"), cand) == "PROMPT_SPEC_INVALID"


# -- pre-issue mode -------------------------------------------------------------------------------------------

def test_preissue_reports_main_own_branch_and_siblings(fx):
    prompt = fx.prompt()
    res = _packet(fx, prompt, None, remote_refs=fx.refs(None))
    assert res["mode"] == "preissue" and _status(res) == {f: ap.MATCH for f in ap.PREISSUE_FACT_IDS}
    st = _status(_packet(fx, prompt, None, remote_refs=fx.refs(fx.base)))
    assert st["P_BRANCH_ABSENT"] == ap.CONFLICT
    sib = [("refs/heads/batch/unit-slice-261010", fx.base)]
    res = _packet(fx, prompt, None, remote_refs=fx.refs(None, extra=sib))
    assert _status(res)["P_NO_SIBLINGS"] == ap.CONFLICT and _detail(res, "P_NO_SIBLINGS")["siblings"] == [
        "batch/unit-slice-261010"]
    other = fx.candidate(name="moved")
    assert _status(_packet(fx, prompt, None, remote_refs=fx.refs(None, main=other)))["P_MAIN"] == ap.CONFLICT
    assert _status(_packet(fx, fx.prompt(base="e" * 40), None, remote_refs=fx.refs(None)))["P_BASE"] == ap.CONFLICT


def test_preissue_needs_remote_refs_and_takes_no_candidate_inputs(fx, tmp_path):
    prompt = fx.prompt()
    assert _code(ap.Packet, str(fx.repo), prompt, None) == "PREISSUE_NEEDS_REMOTE_REFS"
    refs = fx.refs(None)
    for kw in ({"ci": "x"}, {"ci_branch": "main"}, {"workdir": str(tmp_path / "wd")}, {"expect_main": "candidate"}):
        assert _code(ap.Packet, str(fx.repo), prompt, None, remote_refs=refs, **kw) == "PREISSUE_OPTION_INVALID"


# -- command line ---------------------------------------------------------------------------------------------

def test_cli_prints_only_fixed_lines_and_exit_codes(fx, tmp_path, capsys):
    secret_like = b"TOKEN_SHOULD_NEVER_BE_PRINTED\n"
    files = dict(FINAL)
    files["docs/A.md"] = secret_like
    cand = fx.candidate(files=files)
    prompt = fx.prompt(authors={"docs/A.md": secret_like, "scripts/tool.py": FINAL["scripts/tool.py"]})
    out_json = tmp_path / "packet.json"
    rc = ap.main(["--repo", str(fx.repo), "--prompt", prompt, "--candidate", cand, "--remote-refs", fx.refs(cand),
                  "--ci", fx.ci(cand), "--checks", "--workdir", str(tmp_path / "wd"), "--out", str(out_json)])
    out = capsys.readouterr().out
    assert rc == 0
    lines = out.splitlines()
    assert lines[:-1] == ["AUDIT_PACKET " + f + " MATCH" for f in ALL_FACTS]
    assert lines[-1] == "AUDIT_PACKET RESULT conflicts=0 missing=0"
    assert "TOKEN_SHOULD_NEVER_BE_PRINTED" not in out
    assert "TOKEN_SHOULD_NEVER_BE_PRINTED" not in out_json.read_text(encoding="utf-8")
    assert ap.main(["--repo", str(fx.repo), "--prompt", prompt, "--candidate", cand]) == 1
    capsys.readouterr()
    assert ap.main(["--repo", str(fx.repo), "--prompt", prompt, "--candidate", "zz"]) == 2
    assert capsys.readouterr().out == "AUDIT_PACKET FAIL CANDIDATE_INVALID\n"


@pytest.mark.parametrize("with_candidate,extra,code", [
    (True, ["--checks"], "CHECKS_NEED_WORKDIR"),
    (True, ["--preissue"], "MODE_INVALID"),
    (False, [], "MODE_INVALID"),
])
def test_cli_rejects_inconsistent_modes(fx, capsys, with_candidate, extra, code):
    cand = fx.candidate()
    argv = ["--repo", str(fx.repo), "--prompt", fx.prompt()] + (["--candidate", cand] if with_candidate else [])
    assert ap.main(argv + extra) == 2
    assert capsys.readouterr().out == "AUDIT_PACKET FAIL " + code + "\n"


def test_slice_stem_drops_only_revision_and_date():
    assert ap.slice_stem("batch/b107-g4-s2-must-read-r1-261010") == "batch/b107-g4-s2-must-read"
    assert ap.slice_stem("batch/b107-g4-s2-must-read-261010") == "batch/b107-g4-s2-must-read"
    assert ap.slice_stem("batch/g3-close-state-sync-261010") == "batch/g3-close-state-sync"
    assert ap.slice_stem("batch/unit-slice-r1") == "batch/unit-slice"
    assert ap.slice_stem("batch/no-date") == "batch/no-date"
    assert ap.branch_classified("batch/x-r1-261010") and not ap.branch_classified("batch/x-r1")


# -- second-opinion counterexamples (replacement objects, source-side settings, output path, slice naming) -------

def _marker_stub(marker):
    return ("open(" + repr(str(marker)) + ", 'w').write('ran')\n").encode()


def test_replacement_objects_are_ignored_and_undeclared_content_never_runs(fx, tmp_path):
    marker = tmp_path / "undeclared-program-ran"
    good = fx.candidate(name="good")
    bad_files = dict(FINAL)
    bad_files["scripts/check_consistency.py"] = _marker_stub(marker)
    bad = fx.candidate(files=bad_files, name="bad")
    fx.git("replace", bad, good)
    res = _packet(fx, fx.prompt(focused=None), bad, remote_refs=fx.refs(bad), ci=fx.ci(bad),
                  workdir=str(tmp_path / "wd"))
    assert _status(res)["C_PATHS"] == ap.CONFLICT and _detail(res, "C_PATHS")["extra"] == ["scripts/check_consistency.py"]
    assert _status(res)["K_CHECK_CONSISTENCY"] == ap.MISSING and not marker.exists()
    assert fx.git("for-each-ref", "refs/replace") != ""


def test_source_side_configuration_attributes_and_grafts_do_not_change_facts(fx):
    spaced = {"docs/A.md": b"alpha2 \n", "scripts/tool.py": FINAL["scripts/tool.py"]}
    cand = fx.candidate(files=spaced)
    fx.git("config", "core.whitespace", "-trailing-space,-space-before-tab")
    _w(fx.repo / ".git" / "info" / "attributes", b"* -whitespace\n")
    assert _status(_packet(fx, fx.prompt(authors=spaced), cand))["C_DIFF_CHECK"] == ap.CONFLICT
    side = fx.candidate(files={"docs/C.md": b"side\n"}, name="side")
    off = fx.candidate(parent=side, name="off")
    _w(fx.repo / ".git" / "info" / "grafts", (off + " " + fx.base + "\n").encode())
    res = _packet(fx, fx.prompt(), off)
    assert _status(res)["C_PARENT"] == ap.CONFLICT and _detail(res, "C_PARENT")["parents"] == [side]


@pytest.mark.parametrize("tamper", ["tracked", "untracked"])
def test_execution_tree_is_verified_before_any_candidate_program_runs(fx, tmp_path, tamper):
    marker = tmp_path / "tampered-program-ran"
    cand = fx.candidate()

    def tampering(args, cwd, env, timeout):
        rc, out = ap.default_run(args, cwd, env, timeout)
        if "checkout" in args and "--detach" in args:
            clone = Path(args[args.index("-C") + 1])
            if tamper == "tracked":
                _w(clone / "scripts" / "check_consistency.py", _marker_stub(marker))
            else:
                _w(clone / "scripts" / "extra.py", b"x = 1\n")
        return rc, out
    res = _packet(fx, fx.prompt(), cand, workdir=str(tmp_path / "wd"), run=tampering)
    for fid in ("K_CHECK_CONSISTENCY", "K_EXECUTION_RECORD_VERIFY", "K_FINGERPRINT_VERIFY", "K_FOCUSED"):
        assert _status(res)[fid] == ap.CONFLICT and _detail(res, fid) == {"tree": "EXECUTION_TREE_MISMATCH"}
    assert not marker.exists()


def _out_main(fx, out, extra=()):
    return ap.main(["--repo", str(fx.repo), "--prompt", fx.prompt(), "--preissue", "--remote-refs", fx.refs(None),
                    "--out", str(out), *extra])


def test_output_must_be_new_and_outside_the_repository(fx, tmp_path, capsys):
    tracked = fx.repo / "docs" / "A.md"
    before = tracked.read_bytes()
    assert _out_main(fx, tracked) == 2 and capsys.readouterr().out == "AUDIT_PACKET FAIL OUT_EXISTS\n"
    assert tracked.read_bytes() == before
    for inside in (fx.repo / "packet.json", fx.repo / ".git" / "packet.json"):
        assert _out_main(fx, inside) == 2 and capsys.readouterr().out == "AUDIT_PACKET FAIL OUT_INSIDE_REPO\n"
        assert not inside.exists()
    outside = tmp_path / "existing.json"
    outside.write_bytes(b"keep\n")
    assert _out_main(fx, outside) == 2 and capsys.readouterr().out == "AUDIT_PACKET FAIL OUT_EXISTS\n"
    assert outside.read_bytes() == b"keep\n"
    assert _out_main(fx, tmp_path / "missing-dir" / "p.json") == 2
    assert capsys.readouterr().out == "AUDIT_PACKET FAIL OUT_INVALID\n"
    fresh = tmp_path / "packet.json"
    assert _out_main(fx, fresh) == 0 and json.loads(fresh.read_text(encoding="utf-8"))["mode"] == "preissue"


def test_output_inside_the_common_git_directory_of_a_worktree_is_refused(fx, tmp_path, capsys):
    wt = tmp_path / "wt"
    fx.git("worktree", "add", "-q", "--detach", str(wt), fx.base)
    rc = ap.main(["--repo", str(wt), "--prompt", fx.prompt(), "--preissue", "--remote-refs", fx.refs(None),
                  "--out", str(fx.repo / ".git" / "from-worktree.json")])
    assert rc == 2 and capsys.readouterr().out == "AUDIT_PACKET FAIL OUT_INSIDE_REPO\n"


def test_output_through_a_linked_parent_into_the_repository_is_refused(fx, tmp_path, capsys):
    link = tmp_path / "link-to-repo"
    try:
        os.symlink(str(fx.repo), str(link), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available to this account (documented capability gap)")
    assert _out_main(fx, link / "p.json") == 2 and capsys.readouterr().out == "AUDIT_PACKET FAIL OUT_INSIDE_REPO\n"
    assert not (fx.repo / "p.json").exists()


def test_output_inside_the_work_directory_is_refused(fx, tmp_path, capsys):
    cand = fx.candidate()
    wd = tmp_path / "wd"
    wd.mkdir()
    rc = ap.main(["--repo", str(fx.repo), "--prompt", fx.prompt(), "--candidate", cand, "--checks", "--workdir",
                  str(wd), "--out", str(wd / "p.json")])
    assert rc == 2 and capsys.readouterr().out == "AUDIT_PACKET FAIL OUT_INSIDE_WORKDIR\n"


@pytest.mark.parametrize("branch,remote,status,unclassified,siblings", [
    ("batch/unit-slice-r2", "batch/unit-slice-r1", "CONFLICT", True, []),
    ("batch/unit-slice-r2-261010", "batch/unit-slice-r1", "CONFLICT", False, ["batch/unit-slice-r1"]),
    ("batch/unit-slice-r2-261010", "batch/unit-slice", "CONFLICT", False, ["batch/unit-slice"]),
    ("batch/unit-slice-261010", "batch/unit-slice-r3-261011", "CONFLICT", False, ["batch/unit-slice-r3-261011"]),
    ("batch/unit-slice-r2-261010", "batch/unit-slice-two", "MATCH", False, []),
    ("batch/unit-slice-r2-261010", "batch/unit-slice-two-r1-261010", "MATCH", False, []),
])
def test_slice_identity_follows_the_branch_convention_and_unclassified_names_fail(fx, branch, remote, status,
                                                                                  unclassified, siblings):
    prompt = fx.prompt(branch=branch)
    res = _packet(fx, prompt, None, remote_refs=fx.refs(None, extra=[("refs/heads/" + remote, fx.base)]))
    assert _status(res)["P_NO_SIBLINGS"] == status
    assert _detail(res, "P_NO_SIBLINGS") == {"unclassified": unclassified, "siblings": siblings}
    cand = fx.candidate(name="c-" + hashlib.sha256((branch + remote).encode()).hexdigest()[:8])
    res = _packet(fx, prompt, cand, remote_refs=fx.refs(cand, branch=branch,
                                                        extra=[("refs/heads/" + remote, fx.base)]))
    assert _status(res)["R_SIBLINGS"] == status


@pytest.mark.parametrize("lines", [["refs/heads/main"], ["HEAD"], ["refs/heads/batch/x-261010"]])
def test_filtered_remote_snapshot_is_refused(fx, tmp_path, lines):
    path = tmp_path / "filtered.txt"
    path.write_bytes(("".join(fx.base + "\t" + ref + "\n" for ref in lines)).encode())
    assert _code(_packet, fx, fx.prompt(), None, remote_refs=str(path)) == "REMOTE_REFS_INCOMPLETE"


def test_remote_snapshot_origin_and_hash_are_recorded(fx):
    refs = fx.refs(None)
    res = _packet(fx, fx.prompt(), None, remote_refs=refs)
    assert res["remote_origin"] == "AUDITOR_PROVIDED_SNAPSHOT"
    assert res["remote_refs_sha256"] == hashlib.sha256(Path(refs).read_bytes()).hexdigest()
