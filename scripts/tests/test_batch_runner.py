# -*- coding: utf-8 -*-
"""
scripts/tests/test_batch_runner.py

Negative and positive controls for scripts/batch_runner.py (B-107 canonical batch runner).
Covers block parsing, batch spec validation, step derivation, the control state machine,
unique-anchor application and the pre-write hash gate, stdout-only path parsing while git
prints CRLF warnings on stderr, and bounded execution that terminates a whole process tree.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time

import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import batch_runner as br  # noqa: E402

BASE = "a" * 40
TASK = "UNIT-BATCH-261008"
GEN = list(br.GENERATED)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prompt(blocks):
    parts = ["header line"]
    for name, body in blocks.items():
        parts.append("<<<BEGIN " + name + ">>>")
        parts.append(body if isinstance(body, str) else json.dumps(body, ensure_ascii=False))
        parts.append("<<<END " + name + ">>>")
    parts.append("tail line")
    return "\n".join(parts) + "\n"


def lines_of(text):
    return br.prompt_lines(text.encode("utf-8"))


def production_spec(**over):
    authors = {
        "docs/a.md": {"source": {"kind": "base"}, "sha256": "0" * 64},
        "scripts/new_tool.py": {"source": {"kind": "block", "name": "NEW_TOOL_PY"}, "sha256": sha("print(1)\n")},
    }
    spec = {
        "schema_version": 1, "task_id": TASK, "kind": "production", "base_oid": BASE,
        "branch": "batch/unit-batch-261008", "commit_message": "Unit: batch", "e24": True, "focused": None,
        "start": {"mode": "clean"}, "authors": authors,
        "ops": [{"path": "docs/a.md", "old": "x", "new": "y"}],
    }
    spec.update(over)
    return spec


def production_blocks(spec):
    allowed = sorted(set(spec["authors"]) | set(GEN))
    return {
        "BATCH_SPEC_JSON": spec,
        "PLAN_JSON": {"task_id": TASK, "base_oid": BASE, "allowed_paths": list(allowed), "required_paths": list(allowed)},
        "ALLOWED_SCOPE_JSON": {"schema_version": 1, "allowed_scope": list(allowed)},
        "E24_EVIDENCE_JSON": {"schema_version": 1, "base_oid": BASE, "mode": "REQUIRED", "queries": [], "results": []},
        "NEW_TOOL_PY": "print(1)",
    }


def halt_code(fn, *args):
    with pytest.raises(br.Halt) as exc:
        fn(*args)
    return str(exc.value)


# --- blocks -----------------------------------------------------------------

def test_extract_block_requires_exactly_one_pair_and_normalizes_crlf():
    text = prompt({"X_JSON": '{"k": 1}'}).replace("\n", "\r\n")
    lines = br.prompt_lines(text.encode("utf-8"))
    assert br.block_json(lines, "X_JSON") == {"k": 1}
    dup = lines_of(prompt({"X_JSON": "{}"}) + "<<<BEGIN X_JSON>>>\n{}\n<<<END X_JSON>>>\n")
    assert halt_code(br.extract_block, dup, "X_JSON") == "BLOCK_BOUNDARY_INVALID"
    assert halt_code(br.extract_block, lines_of("no blocks\n"), "X_JSON") == "BLOCK_BOUNDARY_INVALID"
    assert halt_code(br.block_json, lines_of(prompt({"X_JSON": "{not json"})), "X_JSON") == "BLOCK_JSON_INVALID"
    assert halt_code(br.extract_block, lines_of("x\n"), "bad-name") == "BLOCK_NAME_INVALID"


# --- spec -------------------------------------------------------------------

def test_production_spec_valid_and_steps_follow_spec():
    spec = br.load_spec(lines_of(prompt(production_blocks(production_spec()))), TASK)
    assert br.derive_steps(spec) == ["preflight", "setup", "e24", "apply", "generate", "precommit", "stage",
                                     "commit", "postcommit", "push"]
    focused = production_spec(e24=False, focused={"pytest_args": ["scripts/tests/x.py", "-q"], "limit_sec": 900})
    spec2 = br.load_spec(lines_of(prompt(production_blocks(focused))), TASK)
    assert br.derive_steps(spec2) == ["preflight", "setup", "apply", "focused", "generate", "precommit", "stage",
                                      "commit", "postcommit", "push"]
    assert br.allowed_paths(spec2) == sorted(["docs/a.md", "scripts/new_tool.py"] + GEN)


@pytest.mark.parametrize("mutate,code", [
    (lambda s: s.update(task_id="OTHER-TASK"), "SPEC_TASK_MISMATCH"),
    (lambda s: s.update(base_oid="abc"), "SPEC_BASE_INVALID"),
    (lambda s: s.update(kind="other"), "SPEC_KIND_INVALID"),
    (lambda s: s.update(branch="main"), "SPEC_BRANCH_INVALID"),
    (lambda s: s.update(commit_message="two\nlines"), "SPEC_MESSAGE_INVALID"),
    (lambda s: s["authors"].update({"../escape.md": {"source": {"kind": "base"}, "sha256": "0" * 64}}), "SPEC_AUTHOR_PATH_INVALID"),
    (lambda s: s["authors"].update({GEN[0]: {"source": {"kind": "base"}, "sha256": "0" * 64}}), "SPEC_AUTHOR_PATH_INVALID"),
    (lambda s: s["authors"].update({".git/x": {"source": {"kind": "base"}, "sha256": "0" * 64}}), "SPEC_AUTHOR_PATH_INVALID"),
    (lambda s: s["authors"]["docs/a.md"].update(sha256="zz"), "SPEC_AUTHOR_HASH_INVALID"),
    (lambda s: s["authors"]["docs/a.md"].update(source={"kind": "keep"}), "SPEC_SOURCE_INVALID"),
    (lambda s: s["authors"]["docs/a.md"].update(source={"kind": "block", "name": "PLAN_JSON"}), "SPEC_SOURCE_INVALID"),
    (lambda s: s["authors"]["docs/a.md"].update(source={"kind": "shell"}), "SPEC_SOURCE_INVALID"),
    (lambda s: s.update(ops=[{"path": "docs/unknown.md", "old": "x", "new": "y"}]), "SPEC_OPS_INVALID"),
    (lambda s: s.update(ops=[{"path": "docs/a.md", "old": "", "new": "y"}]), "SPEC_OPS_INVALID"),
    (lambda s: s.update(focused={"pytest_args": [], "limit_sec": 900}), "SPEC_FOCUSED_INVALID"),
    (lambda s: s.update(start={"mode": "adopt"}), "SPEC_START_INVALID"),
])
def test_production_spec_rejections(mutate, code):
    spec = production_spec()
    blocks = production_blocks(spec)
    mutate(spec)
    assert halt_code(br.load_spec, lines_of(prompt(blocks)), TASK) == code


def test_plan_and_scope_must_pair_with_authors_and_generators():
    spec = production_spec()
    blocks = production_blocks(spec)
    blocks["PLAN_JSON"]["allowed_paths"] = blocks["PLAN_JSON"]["allowed_paths"][:-1]
    assert halt_code(br.load_spec, lines_of(prompt(blocks)), TASK) == "PLAN_SCOPE_MISMATCH"
    blocks = production_blocks(spec)
    blocks["ALLOWED_SCOPE_JSON"]["allowed_scope"].append("docs/extra.md")
    assert halt_code(br.load_spec, lines_of(prompt(blocks)), TASK) == "E24_SCOPE_MISMATCH"
    blocks = production_blocks(spec)
    blocks["E24_EVIDENCE_JSON"]["base_oid"] = "b" * 40
    assert halt_code(br.load_spec, lines_of(prompt(blocks)), TASK) == "E24_BINDING_DRIFT"


def test_adopt_mode_requires_start_branch_and_matching_keep_hashes():
    spec = production_spec()
    spec["authors"]["scripts/new_tool.py"]["source"] = {"kind": "keep"}
    keep_hash = spec["authors"]["scripts/new_tool.py"]["sha256"]
    spec["start"] = {"mode": "adopt", "start_branch": "batch/earlier-261008", "adopt_hashes": {"scripts/new_tool.py": keep_hash}}
    assert br.load_spec(lines_of(prompt(production_blocks(spec))), TASK)["start"]["mode"] == "adopt"
    spec["start"]["adopt_hashes"]["scripts/new_tool.py"] = "1" * 64
    assert halt_code(br.load_spec, lines_of(prompt(production_blocks(spec))), TASK) == "SPEC_START_INVALID"


def test_promotion_spec_and_steps():
    spec = {"schema_version": 1, "task_id": TASK, "kind": "promotion", "base_oid": BASE,
            "candidate_oid": "c" * 40, "candidate_branch": "batch/unit-batch-261008"}
    loaded = br.load_spec(lines_of(prompt({"BATCH_SPEC_JSON": spec})), TASK)
    assert br.derive_steps(loaded) == ["preflight", "verify", "promote", "postmain"]
    spec["candidate_oid"] = BASE
    assert halt_code(br.load_spec, lines_of(prompt({"BATCH_SPEC_JSON": spec})), TASK) == "SPEC_CANDIDATE_INVALID"


# --- control ------------------------------------------------------------------

def test_control_enforces_order_uniqueness_binding_and_lock():
    steps = ["preflight", "verify", "promote", "postmain"]
    c = {"task_id": TASK, "prompt_sha256": "p", "runner_sha256": "r", "done": [], "halted": None}
    assert br.check_control(c, TASK, "p", "r", steps, "preflight") == "OK"
    assert halt_code(br.check_control, c, TASK, "p", "r", steps, "verify") == "STEP_ORDER_VIOLATION"
    c["done"] = ["preflight"]
    assert halt_code(br.check_control, c, TASK, "p", "r", steps, "preflight") == "STEP_ORDER_VIOLATION"
    assert br.check_control(c, TASK, "p", "r", steps, "verify") == "OK"
    assert halt_code(br.check_control, c, TASK, "p2", "r", steps, "verify") == "CONTROL_BINDING_DRIFT"
    assert halt_code(br.check_control, c, TASK, "p", "r2", steps, "verify") == "CONTROL_BINDING_DRIFT"
    c["halted"] = "verify:MAIN_DRIFT"
    assert br.check_control(c, TASK, "p", "r", steps, "verify") == "HALTED"


# --- author content ---------------------------------------------------------------

def test_apply_ops_requires_unique_anchor():
    texts = {"f": "alpha beta alpha\n"}
    assert halt_code(br.apply_ops, dict(texts), [{"path": "f", "old": "alpha", "new": "x"}]) == "ANCHOR_NOT_UNIQUE"
    assert halt_code(br.apply_ops, dict(texts), [{"path": "f", "old": "gamma", "new": "x"}]) == "ANCHOR_NOT_UNIQUE"
    assert br.apply_ops(dict(texts), [{"path": "f", "old": "beta", "new": "BETA"}])["f"] == "alpha BETA alpha\n"


def test_build_authors_rejects_hash_mismatch_before_any_write(tmp_path):
    spec = {"base_oid": BASE, "authors": {"tool.py": {"source": {"kind": "block", "name": "TOOL_PY"}, "sha256": sha("ok\n")}},
            "ops": []}
    lines = lines_of(prompt({"TOOL_PY": "ok"}))
    assert br.build_authors(str(tmp_path), spec, lines) == {"tool.py": "ok\n"}
    spec["authors"]["tool.py"]["sha256"] = sha("other\n")
    assert halt_code(br.build_authors, str(tmp_path), spec, lines) == "PREWRITE_HASH_MISMATCH"
    assert not (tmp_path / "tool.py").exists()


# --- git output parsing --------------------------------------------------------------

def _git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=repo,
                          check=True, capture_output=True)


def test_changed_paths_ignore_crlf_warning_on_stderr(tmp_path):
    repo = str(tmp_path)
    _git(repo, "init", "-q")
    (tmp_path / ".gitattributes").write_bytes(b"* text=auto eol=lf\n")
    (tmp_path / "gen.json").write_bytes(b'{\n  "a": 1\n}\n')
    _git(repo, "add", ".gitattributes", "gen.json")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    (tmp_path / "gen.json").write_bytes(b'{\r\n  "a": 2\r\n}\r\n')
    (tmp_path / "new file.txt").write_bytes(b"x\n")
    merged = subprocess.run(["git", "diff", "--name-only", base], cwd=repo, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT).stdout.decode("utf-8", "replace")
    assert "CRLF will be replaced by LF" in merged, "negative control: the warning must actually occur on stderr"
    assert br.changed_paths(repo, base) == ["gen.json", "new file.txt"]


# --- bounded execution (shared primitive: scripts/bounded_process.py) ---------------------

def _bounded_batch(tmp_path, monkeypatch):
    batch = br.Batch.__new__(br.Batch)
    batch.root, batch.task_id = str(tmp_path), TASK
    monkeypatch.setattr(batch, "artifact", lambda suffix: suffix)
    return batch


def test_runner_has_no_private_process_code():
    # Convergence guard: the runner launches bounded steps only through bounded_process.run_bounded.
    source = open(br.__file__, encoding="utf-8").read()
    assert not hasattr(br, "bounded_run") and not hasattr(br, "kill_tree")
    assert "Popen(" not in source and "killpg" not in source and "taskkill" not in source
    import bounded_process
    assert br.run_bounded is bounded_process.run_bounded


def test_bounded_writes_record_and_reports_exit_code(tmp_path, monkeypatch, capsys):
    batch = _bounded_batch(tmp_path, monkeypatch)
    with pytest.raises(br.Halt) as exc:
        batch.bounded("FOCUSED", ["-c", "import sys; print('done'); sys.stderr.write('err\\n'); sys.exit(3)"], 60)
    assert str(exc.value) == "FOCUSED_NONZERO"
    record = (tmp_path / "bounded-focused.txt").read_text(encoding="utf-8")
    assert "done" in record and "err" in record, "stdout and stderr are both kept in the step record"
    assert "BOUNDED_EXIT FOCUSED code=3 | (summary withheld)" in capsys.readouterr().out
    (tmp_path / "ok").mkdir()
    _bounded_batch(tmp_path / "ok", monkeypatch).bounded("FOCUSED", ["-c", "print('7 passed in 0.10s')"], 60)
    assert "BOUNDED_EXIT FOCUSED code=0 | 7 passed in 0.10s" in capsys.readouterr().out


def test_bounded_passes_runner_environment_and_merges_output(tmp_path, monkeypatch):
    seen = {}

    import bounded_process

    def fake(cmd, cwd, timeout, env=None, merge_stderr=False, **kw):
        seen.update(cmd=cmd, cwd=cwd, timeout=timeout, env=env, merge=merge_stderr)
        return bounded_process.BoundedResult(0, False, None, b"1 passed in 0.01s\n", b"", "NOT_NEEDED")

    monkeypatch.setattr(br, "run_bounded", fake)
    _bounded_batch(tmp_path, monkeypatch).bounded("PRECOMMIT", ["scripts/gate_runner.py"], 123)
    assert seen["cmd"][0] == br.PY and seen["timeout"] == 123 and seen["merge"] is True
    assert seen["env"]["PYTHONUTF8"] == "1" and seen["env"]["PYTHONIOENCODING"] == "utf-8"


@pytest.mark.parametrize("result,code,printed", [
    ((None, False, "OSError", b"", b"", "NOT_NEEDED"), "FOCUSED_LAUNCH_FAILED", None),
    ((None, True, None, b"partial\n", b"", "TREE_KILL_FAILED"), "FOCUSED_TIMEOUT", "kill=TREE_KILL_FAILED"),
    ((None, True, None, b"", b"", "TREE_SIGNALLED"), "FOCUSED_TIMEOUT", "kill=TREE_SIGNALLED"),
])
def test_bounded_failure_paths_stop(tmp_path, monkeypatch, capsys, result, code, printed):
    # Fault injection: launch failure and timeouts (including a failed tree kill) are stops, never passes.
    import bounded_process
    monkeypatch.setattr(br, "run_bounded", lambda *a, **k: bounded_process.BoundedResult(*result))
    batch = _bounded_batch(tmp_path, monkeypatch)
    assert halt_code(batch.bounded, "FOCUSED", ["-c", "pass"], 60) == code
    out = capsys.readouterr().out
    if printed:
        assert "BOUNDED_TIMEOUT FOCUSED limit=60s " + printed in out
    assert "BOUNDED_EXIT" not in out
    # Whatever was captured before the stop (for example partial output before a timeout) is kept in the record.
    assert (tmp_path / "bounded-focused.txt").read_bytes() == result[3]


def test_bounded_capture_failure_stops_and_leaves_only_the_empty_record(tmp_path, monkeypatch):
    # Documented limitation: the record is written after run_bounded returns, so a failure inside the shared
    # primitive leaves an empty record; the step still stops (main reports UNEXPECTED_<type>), never passes.
    def broken(*a, **k):
        raise OSError("injected capture failure")

    monkeypatch.setattr(br, "run_bounded", broken)
    batch = _bounded_batch(tmp_path, monkeypatch)
    with pytest.raises(OSError):
        batch.bounded("FOCUSED", ["-c", "print('x')"], 60)
    assert (tmp_path / "bounded-focused.txt").read_bytes() == b""


def test_bounded_refuses_second_run_of_a_stage(tmp_path, monkeypatch):
    batch = _bounded_batch(tmp_path, monkeypatch)
    (tmp_path / "bounded-focused.txt").write_text("", encoding="utf-8")
    assert halt_code(batch.bounded, "FOCUSED", ["-c", "pass"], 60) == "FOCUSED_ALREADY_RUN"


def _alive(pid):
    # Shared probe: a failed platform query raises instead of reporting the process as dead.
    import bounded_process
    return bounded_process.process_alive(pid)


def test_bounded_timeout_terminates_whole_tree(tmp_path, monkeypatch, capsys):
    pid_file = tmp_path / "grandchild.pid"
    child = (
        "import subprocess, sys, time\n"
        "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "open(sys.argv[1], 'w').write(str(g.pid))\n"
        "time.sleep(120)\n"
    )
    batch = _bounded_batch(tmp_path, monkeypatch)
    started = time.monotonic()
    # The limit leaves room for two interpreter start-ups on slow Windows hosts before the tree is terminated.
    assert halt_code(batch.bounded, "FOCUSED", ["-c", child, str(pid_file)], 10) == "FOCUSED_TIMEOUT"
    assert time.monotonic() - started < 90
    assert "BOUNDED_TIMEOUT FOCUSED limit=10s kill=TREE_SIGNALLED" in capsys.readouterr().out
    assert pid_file.exists(), "grandchild must have started before the timeout"
    grandchild = int(pid_file.read_text())
    deadline = time.monotonic() + 15
    while _alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not _alive(grandchild), "grandchild must be terminated with the tree"


# --- B-107 runner update path: (2) fixed-vocabulary failure detail ------------------------------

def test_child_env_pins_utf8_like_verify_all():
    env = br.child_env()
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"


DETAIL_SHAPE = re.compile(r"exit=-?\d+ class=[A-Z_]+")
SECRET_SAMPLES = [
    "password=hunter2",                                                   # short value
    "Authorization: Bearer " + "abcdefghijklmnopqrstuvwxyz",              # letters only
    "token=" + "abc.def.ghi" + "123456.tail",                             # separators
    "ghp_" + "Q7" * 18,                                                   # long signature
    "plain unknown failure text",
]


@pytest.mark.parametrize("sample", SECRET_SAMPLES)
def test_classify_failure_never_echoes_output(sample):
    for stderr, stdout in ((sample.encode(), b""), (b"", sample.encode()), (b"\xff\xfe" + sample.encode(), b"")):
        detail = br.classify_failure(2, stderr, stdout)
        assert DETAIL_SHAPE.fullmatch(detail), detail
        assert detail == "exit=2 class=DETAIL_UNAVAILABLE"
        for part in re.split(r"[\s=.:]+", sample):
            if len(part) >= 4:
                assert part not in detail


@pytest.mark.parametrize("text,cls", [
    ("[SECRET_SCAN BLOCK] x:1 detector=GENERIC", "SECRET_SCAN_BLOCK"),
    ("fatal: Unable to create '/r/.git/index.lock': File exists.", "GIT_INDEX_LOCKED"),
    (" ! [rejected]        main -> main (non-fast-forward)", "GIT_REMOTE_REJECTED"),
    ("fatal: Authentication failed for 'https://example.invalid/'", "GIT_AUTH_FAILED"),
    ("fatal: unable to access: Could not resolve host: example.invalid", "NETWORK_UNAVAILABLE"),
    ("The process cannot access the file because it is being used by another process.", "FILE_IN_USE"),
    ("error: open(\"x\"): Permission denied", "ACCESS_DENIED"),
    ("[SECRET_SCAN BLOCK] and index.lock", "SECRET_SCAN_BLOCK"),
])
def test_classify_failure_known_classes_first_match_wins(text, cls):
    assert br.classify_failure(1, text.encode(), b"") == "exit=1 class=" + cls
    assert br.classify_failure(1, b"", text.encode()) == "exit=1 class=" + cls  # stdout-only output is classified too


def test_classify_failure_random_text_stays_in_fixed_vocabulary():
    import random
    rng = random.Random(261009)
    alphabet = "abcXYZ0129_-+/=.:;[]() \t\u4e2d\u6587"
    for _ in range(300):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 80)))
        detail = br.classify_failure(rng.randint(-5, 300), text.encode("utf-8"), b"")
        assert DETAIL_SHAPE.fullmatch(detail), detail


def test_run_failure_keeps_fixed_code_and_fixed_detail(tmp_path):
    secret = "password=hunter2"
    script = "import sys; sys.stderr.write('boom " + secret + "\\n'); sys.exit(2)"
    with pytest.raises(br.Halt) as exc:
        br.run([sys.executable, "-c", script], "UNIT_FAILED", str(tmp_path))
    assert str(exc.value) == "UNIT_FAILED"
    assert exc.value.detail == "exit=2 class=DETAIL_UNAVAILABLE"
    lock = "import sys; sys.stderr.write(\"fatal: Unable to create 'x/.git/index.lock': File exists.\\n\"); sys.exit(128)"
    with pytest.raises(br.Halt) as locked:
        br.run([sys.executable, "-c", lock], "STAGE_FAILED", str(tmp_path))
    assert locked.value.detail == "exit=128 class=GIT_INDEX_LOCKED"


def test_report_halt_prints_detail_only_when_present(capsys):
    br.report_halt(br.Halt("STAGE_FAILED", "exit=128 class=GIT_INDEX_LOCKED"), "stage")
    br.report_halt(br.Halt("SETUP_DIRTY"), "setup")
    assert capsys.readouterr().out.splitlines() == [
        "S1 STAGE_FAILED | step stage", "S1_DETAIL exit=128 class=GIT_INDEX_LOCKED", "S1 SETUP_DIRTY | step setup"]


@pytest.mark.parametrize("line,shown", [
    ("GATE_RUNNER FAIL stage=PRECOMMIT", True),
    ("112 passed in 12.68s", True),
    ("=========== 3 failed, 740 passed, 1 skipped in 121.60s (0:02:01) ===========", True),
    ("leak password=hunter2", False),
    ("password=hunter2 1 passed in 1s", False),
    ("GATE_RUNNER FAIL stage=PRECOMMIT " + "secret", False),
])
def test_bounded_summary_prints_only_fixed_shapes(line, shown):
    assert br.bounded_summary(["earlier", line]) == (line if shown else "(summary withheld)")
    assert br.bounded_summary([]) == "(no output)"


def test_bounded_prints_withheld_summary_for_unknown_output(tmp_path, monkeypatch, capsys):
    secret = "password=hunter2"
    batch = br.Batch.__new__(br.Batch)
    batch.root, batch.task_id = str(tmp_path), TASK
    monkeypatch.setattr(batch, "artifact", lambda suffix: "bounded.txt")
    with pytest.raises(br.Halt) as exc:
        batch.bounded("FOCUSED", ["-c", "print('leak " + secret + "'); raise SystemExit(1)"], 60)
    assert str(exc.value) == "FOCUSED_NONZERO"
    out = capsys.readouterr().out
    assert "BOUNDED_EXIT FOCUSED code=1 | (summary withheld)" in out and "hunter2" not in out


# --- (3) author hashes at stage and commit -----------------------------------------------

def _repo_with(tmp_path, files):
    repo = str(tmp_path)
    _git(repo, "init", "-q")
    for name, data in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    _git(repo, "add", *files)
    _git(repo, "commit", "-q", "-m", "base")
    return repo, _git(repo, "rev-parse", "HEAD").stdout.decode().strip()


def test_verify_blob_hashes_checks_index_and_commit_with_lf_normalization(tmp_path):
    repo, _ = _repo_with(tmp_path, {"docs/a.md": b"one\n"})
    assert br.verify_blob_hashes(repo, {"docs/a.md": sha("one\n")}, "HEAD", "COMMITTED_AUTHOR_MISMATCH") is None
    (tmp_path / "docs/a.md").write_bytes(b"two\n")
    _git(repo, "add", "docs/a.md")
    assert br.verify_blob_hashes(repo, {"docs/a.md": sha("two\n")}, "", "STAGED_AUTHOR_MISMATCH") is None
    assert halt_code(br.verify_blob_hashes, repo, {"docs/a.md": sha("one\n")}, "", "STAGED_AUTHOR_MISMATCH") == "STAGED_AUTHOR_MISMATCH"
    assert halt_code(br.verify_blob_hashes, repo, {"docs/a.md": sha("two\n")}, "HEAD", "COMMITTED_AUTHOR_MISMATCH") == "COMMITTED_AUTHOR_MISMATCH"
    crlf_repo = tmp_path / "crlf"
    crlf_repo.mkdir()
    r2, _ = _repo_with(crlf_repo, {"c.txt": b"x\r\ny\r\n"})
    assert br.verify_blob_hashes(r2, {"c.txt": sha("x\ny\n")}, "HEAD", "L") is None


def test_verify_blob_hashes_fails_closed_when_blob_unreadable(tmp_path):
    # Fault injection: a missing blob is a failure, never a pass.
    repo, _ = _repo_with(tmp_path, {"docs/a.md": b"one\n"})
    assert halt_code(br.verify_blob_hashes, repo, {"docs/missing.md": sha("one\n")}, "HEAD", "L") == "GIT_READ_FAILED"


class _Recorder:
    def __init__(self):
        self.calls = []


def _stage_batch(monkeypatch, rec, fail=None):
    spec = production_spec()
    batch = br.Batch.__new__(br.Batch)
    batch.root, batch.task_id, batch.spec = "/nonexistent", TASK, spec
    paths = br.allowed_paths(spec)

    def verify_hashes(root, table, label):
        rec.calls.append(("worktree", label))
        if fail == label:
            raise br.Halt(label)

    def verify_blob_hashes(root, table, rev, label):
        rec.calls.append(("blob", rev, label))
        if fail == label:
            raise br.Halt(label)

    monkeypatch.setattr(br, "expect_scope", lambda *a, **k: rec.calls.append(("scope",)))
    monkeypatch.setattr(br, "verify_hashes", verify_hashes)
    monkeypatch.setattr(br, "verify_blob_hashes", verify_blob_hashes)
    monkeypatch.setattr(br, "run", lambda args, label, root, timeout=600: rec.calls.append(("run", args[1])) or "")
    monkeypatch.setattr(br, "staged_paths", lambda root: paths)
    monkeypatch.setattr(br, "status_lines", lambda root: ["M  " + p for p in paths])
    monkeypatch.setattr(batch, "gate", lambda stage: rec.calls.append(("gate", stage)))
    return batch


def test_stage_verifies_author_hashes_before_add_and_in_index_around_gate(monkeypatch):
    rec = _Recorder()
    _stage_batch(monkeypatch, rec).step_stage()
    assert rec.calls == [("scope",), ("worktree", "STAGE_AUTHOR_DRIFT"), ("run", "add"),
                         ("blob", "", "STAGED_AUTHOR_MISMATCH"), ("gate", "STAGED"), ("blob", "", "STAGED_AUTHOR_DRIFT")]


@pytest.mark.parametrize("label", ["STAGE_AUTHOR_DRIFT", "STAGED_AUTHOR_MISMATCH", "STAGED_AUTHOR_DRIFT"])
def test_stage_stops_on_each_author_hash_failure(monkeypatch, label):
    rec = _Recorder()
    batch = _stage_batch(monkeypatch, rec, fail=label)
    assert halt_code(batch.step_stage) == label
    if label == "STAGE_AUTHOR_DRIFT":
        assert ("run", "add") not in rec.calls, "nothing is staged after a working-tree drift"
    if label == "STAGED_AUTHOR_MISMATCH":
        assert ("gate", "STAGED") not in rec.calls


def test_commit_verifies_committed_author_blobs(monkeypatch):
    rec = _Recorder()
    spec = production_spec()
    batch = br.Batch.__new__(br.Batch)
    batch.root, batch.task_id, batch.spec = "/nonexistent", TASK, spec
    answers = {("rev-parse", "HEAD"): BASE, ("branch", "--show-current"): spec["branch"], ("rev-parse", "HEAD~1"): BASE}
    monkeypatch.setattr(br, "git", lambda root, *args, **k: answers[args])
    monkeypatch.setattr(br, "run", lambda args, label, root, timeout=600: rec.calls.append(("run", args[1])) or "")
    monkeypatch.setattr(br, "status_lines", lambda root: [])
    monkeypatch.setattr(br, "git_paths", lambda root, *args: br.allowed_paths(spec))
    monkeypatch.setattr(br, "staged_paths", lambda root: br.allowed_paths(spec))

    def verify_blob_hashes(root, table, rev, label):
        rec.calls.append(("blob", rev, label))
        if rev == "HEAD":
            raise br.Halt(label)

    monkeypatch.setattr(br, "verify_blob_hashes", verify_blob_hashes)
    assert halt_code(batch.step_commit) == "COMMITTED_AUTHOR_MISMATCH"
    assert rec.calls == [("blob", "", "COMMIT_INDEX_DRIFT"), ("run", "commit"), ("blob", "HEAD", "COMMITTED_AUTHOR_MISMATCH")]


def test_commit_refuses_drifted_index_and_leaves_head_unchanged(tmp_path):
    # Real git: the index is changed after staging; nothing may be committed.
    files = {"docs/a.md": b"old\n", GEN[0]: b"{}\n", GEN[1]: b"{}\n"}
    repo, base = _repo_with(tmp_path, files)
    spec = production_spec(base_oid=base)
    spec["authors"] = {"docs/a.md": {"source": {"kind": "base"}, "sha256": sha("new\n")}}
    _git(repo, "switch", "-q", "-c", spec["branch"])
    _git(repo, "config", "user.name", "t")  # the runner commits without -c overrides; CI hosts may lack an identity
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "commit.gpgsign", "false")
    for path, data in ((GEN[0], b'{"g": 1}\n'), (GEN[1], b'{"g": 2}\n'), ("docs/a.md", b"new\n")):
        (tmp_path / path).write_bytes(data)
        _git(repo, "add", path)
    batch = br.Batch.__new__(br.Batch)
    batch.root, batch.task_id, batch.spec = repo, TASK, spec
    blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=repo, input=b"tampered\n",
                          capture_output=True, check=True).stdout.decode().strip()
    head = lambda: _git(repo, "rev-parse", "HEAD").stdout.decode().strip()  # noqa: E731
    _git(repo, "update-index", "--cacheinfo", "100644," + blob + ",docs/a.md")
    assert halt_code(batch.step_commit) == "COMMIT_INDEX_DRIFT" and head() == base  # author content drift
    _git(repo, "add", "docs/a.md")
    _git(repo, "update-index", "--force-remove", GEN[1])
    assert halt_code(batch.step_commit) == "COMMIT_INDEX_DRIFT" and head() == base  # generated output unstaged
    _git(repo, "add", GEN[1])
    _git(repo, "update-index", "--cacheinfo", "100644," + blob + "," + GEN[0])
    assert halt_code(batch.step_commit) == "COMMIT_INDEX_DRIFT" and head() == base  # index differs from worktree
    _git(repo, "add", GEN[0])
    (tmp_path / "extra.md").write_bytes(b"x\n")
    _git(repo, "add", "extra.md")
    assert halt_code(batch.step_commit) == "COMMIT_INDEX_DRIFT" and head() == base  # undeclared path staged
    _git(repo, "rm", "-q", "--cached", "extra.md")
    (tmp_path / "extra.md").unlink()
    assert batch.step_commit() is None and head() != base  # positive control: consistent index is committed


# --- (7) adopt a workspace that stopped before generate ------------------------------------

def _adopt_spec():
    spec = production_spec()
    spec["authors"] = {"docs/a.md": {"source": {"kind": "keep"}, "sha256": sha("new\n")}}
    spec["ops"] = []
    spec["start"] = {"mode": "adopt", "start_branch": "batch/earlier-261008", "adopt_hashes": {"docs/a.md": sha("new\n")}}
    return spec


def test_adopt_scope_accepts_stop_before_or_after_generate(tmp_path):
    repo, base = _repo_with(tmp_path, {"docs/a.md": b"old\n", GEN[0]: b"{}\n", GEN[1]: b"{}\n", "docs/other.md": b"o\n"})
    spec = _adopt_spec()
    spec["base_oid"] = base
    (tmp_path / "docs/a.md").write_bytes(b"new\n")
    assert br.expect_adopt_scope(repo, spec, "START") is None  # stopped before generate
    (tmp_path / GEN[0]).write_bytes(b'{"x": 1}\n')
    assert br.expect_adopt_scope(repo, spec, "START") is None  # stopped after generate


def test_adopt_scope_rejects_outside_change_and_missing_adopted_file(tmp_path):
    repo, base = _repo_with(tmp_path, {"docs/a.md": b"old\n", "docs/other.md": b"o\n"})
    spec = _adopt_spec()
    spec["base_oid"] = base
    assert halt_code(br.expect_adopt_scope, repo, spec, "START") == "START_SCOPE_MISMATCH"
    (tmp_path / "docs/a.md").write_bytes(b"new\n")
    (tmp_path / "docs/other.md").write_bytes(b"changed\n")
    assert halt_code(br.expect_adopt_scope, repo, spec, "START") == "START_SCOPE_DRIFT"
    (tmp_path / "docs/other.md").write_bytes(b"o\n")
    (tmp_path / "stray.txt").write_bytes(b"x\n")
    assert halt_code(br.expect_adopt_scope, repo, spec, "START") == "START_SCOPE_DRIFT"


# --- runner update: controlled succession ----------------------------------------------------

def _runner_update_spec(new_runner_text, base):
    spec = production_spec(base_oid=base, runner_update=True)
    spec["authors"][br.RUNNER_REL] = {"source": {"kind": "block", "name": "RUNNER_PY"}, "sha256": sha(new_runner_text)}
    return spec


def test_runner_update_must_be_declared_both_ways():
    spec = _runner_update_spec("new\n", BASE)
    blocks = production_blocks(spec)
    blocks["RUNNER_PY"] = "new"
    assert br.load_spec(lines_of(prompt(blocks)), TASK)["runner_update"] is True
    spec.pop("runner_update")
    assert halt_code(br.load_spec, lines_of(prompt(production_blocks(spec))), TASK) == "SPEC_RUNNER_UPDATE_UNDECLARED"
    plain = production_spec(runner_update=True)
    assert halt_code(br.load_spec, lines_of(prompt(production_blocks(plain))), TASK) == "SPEC_RUNNER_UPDATE_UNDECLARED"
    plain = production_spec(runner_update="yes")
    assert halt_code(br.load_spec, lines_of(prompt(production_blocks(plain))), TASK) == "SPEC_RUNNER_UPDATE_INVALID"


def _succession_case(tmp_path):
    old, new = "old runner\n", "new runner\n"
    repo, base = _repo_with(tmp_path, {br.RUNNER_REL: old.encode()})
    spec = _runner_update_spec(new, base)
    control = {"task_id": TASK, "prompt_sha256": "p", "runner_sha256": sha(old),
               "done": ["preflight", "setup", "e24", "apply"], "halted": None}
    return repo, spec, control, sha(old), sha(new)


def test_successor_runner_is_accepted_only_after_apply_with_declared_hash(tmp_path):
    repo, spec, control, old_sha, new_sha = _succession_case(tmp_path)
    steps = br.PRODUCTION_STEPS
    accepted = br.accepted_runner_sha(repo, spec, control, new_sha)
    assert accepted == old_sha
    assert br.check_control(control, TASK, "p", accepted, list(steps), "focused") == "OK"
    assert br.accepted_runner_sha(repo, spec, control, old_sha) == old_sha


@pytest.mark.parametrize("mutate", [
    lambda spec, control: control.update(done=["preflight", "setup", "e24"]),             # before apply
    lambda spec, control: spec["authors"][br.RUNNER_REL].update(sha256="1" * 64),        # not the declared file
    lambda spec, control: control.update(runner_sha256="2" * 64),                        # bound value is not the Base runner
    lambda spec, control: spec.update(runner_update=False),                              # undeclared
    lambda spec, control: spec.update(kind="promotion"),                                 # never in promotion
])
def test_successor_runner_rejected_otherwise(tmp_path, mutate):
    repo, spec, control, old_sha, new_sha = _succession_case(tmp_path)
    mutate(spec, control)
    accepted = br.accepted_runner_sha(repo, spec, control, new_sha)
    assert accepted == new_sha
    assert halt_code(br.check_control, control, TASK, "p", accepted, list(br.PRODUCTION_STEPS), "focused") == "CONTROL_BINDING_DRIFT"


def test_successor_check_fails_closed_when_base_runner_unreadable(tmp_path):
    # Fault injection: the Base blob probe failing is a stop, never an acceptance.
    repo, spec, control, old_sha, new_sha = _succession_case(tmp_path)
    spec["base_oid"] = "f" * 40
    assert halt_code(br.accepted_runner_sha, repo, spec, control, new_sha) == "GIT_READ_FAILED"
