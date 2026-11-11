# -*- coding: utf-8 -*-
"""
scripts/tests/test_batch_runner.py

Negative and positive controls for scripts/batch_runner.py (B-107 canonical batch runner).
Covers block parsing, batch spec validation, step derivation, the control state machine,
unique-anchor application and the pre-write hash gate, stdout-only path parsing while git
prints CRLF warnings on stderr, bounded execution that terminates a whole process tree, safe
author paths (no drive letter, colon or unsafe segment; reads and writes stay inside the work tree)
the generate step checking authors before any generator runs, and the must-read closure (derived list,
blob hashes at the binding commit, unmapped rule files, and the preflight comparison with MUST_READ_JSON).
"""

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

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
    def synthetic_bounded(*a, **k):
        # New durable primitive creates and writes the task-local file itself.
        from pathlib import Path
        Path(k['capture_path']).write_bytes(result[3])
        return bounded_process.BoundedResult(*result)
    monkeypatch.setattr(br, "run_bounded", synthetic_bounded)
    batch = _bounded_batch(tmp_path, monkeypatch)
    assert halt_code(batch.bounded, "FOCUSED", ["-c", "pass"], 60) == code
    out = capsys.readouterr().out
    if printed:
        assert "BOUNDED_TIMEOUT FOCUSED limit=60s " + printed in out
    assert "BOUNDED_EXIT" not in out
    # Whatever was captured before the stop (for example partial output before a timeout) is kept in the record.
    assert (tmp_path / "bounded-focused.txt").read_bytes() == result[3]


def test_bounded_capture_failure_stops_and_leaves_only_the_empty_record(tmp_path, monkeypatch):
    # Durable primitive can fail after opening an empty raw record, but may
    # never invent success or run the next stage.
    def broken(*a, **k):
        from pathlib import Path
        Path(k['capture_path']).touch(exist_ok=False)
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
    steps = br.derive_steps(dict(spec, focused={}))
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


# --- G4 slice 1: safe author paths and generate order (B-107) --------------------------------

UNSAFE_AUTHOR_PATHS = [
    "C:/escape.py",            # drive-absolute on Windows
    "c:escape.py",             # drive-relative on Windows
    "D:",                      # bare drive
    "docs/a:b.md",             # colon inside a segment
    "docs/a.md:stream",        # NTFS alternate data stream
    "docs//a.md",              # empty segment
    "docs/./a.md",             # '.' segment
    "docs/a.md/",              # trailing slash (empty last segment)
    "docs/../a.md",            # '..' segment
    "/abs/a.md",               # absolute POSIX
    "docs\\a.md",              # backslash
    "docs/a\tb.md",            # control character
    "docs/a\x7fb.md",          # DEL
    "",                        # empty
    "docs./a.md",              # segment ending in '.' (Windows drops it)
    "docs/a.md.",              # last segment ending in '.'
    "docs/a.md ",              # last segment ending in a space
    "sub/.git/config",         # nested .git segment
    "sub/.GIT/config",         # .git segment in another letter case
    "sub/.git.",               # Windows alias of sub/.git
    "Docs/Fingerprints/Exec-Latest.json",   # generator output in another letter case
]


@pytest.mark.parametrize("path", UNSAFE_AUTHOR_PATHS)
def test_unsafe_author_path_is_rejected_by_load_spec(path):
    spec = production_spec()
    blocks = production_blocks(spec)
    spec["authors"][path] = {"source": {"kind": "base"}, "sha256": "0" * 64}
    assert br.safe_author_path(path) is False
    assert halt_code(br.load_spec, lines_of(prompt(blocks)), TASK) == "SPEC_AUTHOR_PATH_INVALID"


@pytest.mark.parametrize("path", ["docs/TASKBOARD.md", "scripts/tests/test_batch_runner.py", "scripts/batch_runner.py",
                                  ".agents/rules/role-boundaries.md", "runtime/channel-gateway/src/a-b_c.v2.js",
                                  "docs/中文檔名.md", "docs/.gitkeep-notes.md", ".github/workflows/verify.yml",
                                  ".gitignore", ".gitattributes", ".gitmodules"])
def test_ordinary_repository_paths_stay_accepted(path):
    assert br.safe_author_path(path) is True



# G5 author-path policy: reject .git metadata components, not valid tracked dotfiles/.github.
@pytest.mark.parametrize("path", [
    ".git", ".GIT", "docs/.git", "docs/.GIT/config", ".git/config", ".GIT/config",
    "docs/.git/config", ".github/../.git/config", ".github//x.yml",
    ".github/./workflows/a.yml", ".github/workflows/x.yml.",
    ".github/workflows/x.yml ", ".github/CON", ".github/aux.txt",
    ".github/COM1.ini", ".github/CONIN$", ".github/a:b.yml",
    ".github\\workflows\\verify.yml", "x/.git", "x/.GiT/HEAD", "a:b",
])
def test_git_metadata_or_alias_path_stays_rejected(path):
    assert br.safe_author_path(path) is False
    spec = production_spec()
    blocks = production_blocks(spec)
    spec["authors"][path] = {"source": {"kind": "base"}, "sha256": "0" * 64}
    assert halt_code(br.load_spec, lines_of(prompt(blocks)), TASK) == "SPEC_AUTHOR_PATH_INVALID"


@pytest.mark.parametrize("path", [
    ".github/workflows/verify.yml", ".gitignore", ".gitattributes", ".gitmodules",
    "docs/.gitkeep-notes.md", ".github/policies/rule.yml",
])
def test_dotfile_author_path_accepted_by_runner_load_spec(path):
    assert br.safe_author_path(path) is True
    spec = production_spec()
    spec["authors"][path] = {"source": {"kind": "base"}, "sha256": "0" * 64}
    assert br.load_spec(lines_of(prompt(production_blocks(spec))), TASK)["authors"][path]


def test_github_workflow_plain_target_is_accessible(tmp_path):
    parent = tmp_path / ".github" / "workflows"
    parent.mkdir(parents=True)
    target = parent / "verify.yml"
    target.write_text("name: verify\n", encoding="utf-8")
    assert br.safe_author_path(".github/workflows/verify.yml") is True
    assert br.author_target(str(tmp_path), ".github/workflows/verify.yml") == str(target)


def test_github_workflow_linked_parent_forbidden(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "workflows").mkdir()
    _symlink_or_skip(str(outside), str(tmp_path / ".github"), True)
    assert halt_code(br.author_target, str(tmp_path), ".github/workflows/verify.yml") == "AUTHOR_PATH_UNSAFE_TARGET"


def test_github_workflow_linked_file_forbidden(tmp_path):
    parent = tmp_path / ".github" / "workflows"
    parent.mkdir(parents=True)
    target = parent / "real.yml"
    target.write_text("name: real\n", encoding="utf-8")
    _symlink_or_skip(str(target), str(parent / "verify.yml"), False)
    assert halt_code(br.author_target, str(tmp_path), ".github/workflows/verify.yml") == "AUTHOR_PATH_UNSAFE_TARGET"


def test_author_paths_equal_apart_from_letter_case_are_rejected():
    spec = production_spec()
    blocks = production_blocks(spec)
    spec["authors"]["Docs/A.md"] = {"source": {"kind": "base"}, "sha256": "0" * 64}
    assert br.safe_author_path("Docs/A.md") is True
    assert halt_code(br.load_spec, lines_of(prompt(blocks)), TASK) == "SPEC_AUTHOR_PATH_INVALID"


@pytest.mark.parametrize("path", ["C:/escape.py", "D:/escape.py", "d:escape.py", "docs/a.md:stream"])
def test_rejected_drive_and_stream_paths_would_not_name_a_work_tree_file_on_windows(path):
    # Why the colon rule exists: the former Path(root) / path join leaves a Windows work tree or addresses a stream.
    import pathlib
    ws = pathlib.PureWindowsPath("C:/ws")
    joined = ws / path
    assert not joined.is_relative_to(ws) or ":" in joined.name
    assert br.safe_author_path(path) is False


def _symlink_or_skip(src, dst, is_dir):
    try:
        os.symlink(src, dst, target_is_directory=is_dir)
    except (OSError, NotImplementedError) as exc:
        pytest.skip("capability gap: symbolic links cannot be created here (" + type(exc).__name__ + ")")


def test_author_target_with_a_plain_parent_chain_is_returned(tmp_path):
    (tmp_path / "docs" / "sub").mkdir(parents=True)
    target = br.author_target(str(tmp_path), "docs/sub/a.md")
    assert target == os.path.join(os.path.realpath(str(tmp_path)), "docs", "sub", "a.md")
    assert br.author_target(str(tmp_path), "top.md") == os.path.join(os.path.realpath(str(tmp_path)), "top.md")


def test_author_target_through_a_linked_directory_outside_stops(tmp_path):
    work, outside = tmp_path / "work", tmp_path / "outside"
    work.mkdir()
    outside.mkdir()
    _symlink_or_skip(str(outside), str(work / "docs"), True)
    assert halt_code(br.author_target, str(work), "docs/a.md") == "AUTHOR_PATH_UNSAFE_TARGET"


def test_author_target_through_a_link_to_git_metadata_inside_stops(tmp_path):
    # Second-opinion counterexample: meta -> .git stays inside the work tree but must never be reachable.
    (tmp_path / ".git").mkdir()
    _symlink_or_skip(str(tmp_path / ".git"), str(tmp_path / "meta"), True)
    assert halt_code(br.author_target, str(tmp_path), "meta/synthetic.dat") == "AUTHOR_PATH_UNSAFE_TARGET"


def test_author_target_through_a_link_to_a_generator_directory_inside_stops(tmp_path):
    (tmp_path / "docs" / "fingerprints").mkdir(parents=True)
    _symlink_or_skip(str(tmp_path / "docs" / "fingerprints"), str(tmp_path / "alias"), True)
    assert halt_code(br.author_target, str(tmp_path), "alias/exec-latest.json") == "AUTHOR_PATH_UNSAFE_TARGET"


def test_author_target_that_is_itself_a_link_stops(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "real.md").write_bytes(b"x\n")
    _symlink_or_skip(str(tmp_path / "docs" / "real.md"), str(tmp_path / "docs" / "a.md"), False)
    assert halt_code(br.author_target, str(tmp_path), "docs/a.md") == "AUTHOR_PATH_UNSAFE_TARGET"


def test_author_target_through_a_link_loop_stops(tmp_path):
    _symlink_or_skip(str(tmp_path / "loop"), str(tmp_path / "loop"), True)
    assert halt_code(br.author_target, str(tmp_path), "loop/a.md") == "AUTHOR_PATH_UNSAFE_TARGET"


def test_author_target_missing_parent_or_file_parent_is_parent_directory_missing(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "file.md").write_bytes(b"x\n")
    assert halt_code(br.author_target, str(tmp_path), "nodir/a.md") == "PARENT_DIRECTORY_MISSING"
    assert halt_code(br.author_target, str(tmp_path), "docs/file.md/a.md") == "PARENT_DIRECTORY_MISSING"


@pytest.mark.parametrize("error", [PermissionError, OSError, ValueError, RuntimeError])
def test_author_target_resolution_failure_stops(tmp_path, monkeypatch, error):
    # Fault injection: when strict resolution itself fails, the result is a stop, never a path.
    (tmp_path / "docs").mkdir()
    def broken(path, strict=False):
        raise error("resolution failed")
    monkeypatch.setattr(br.os.path, "realpath", broken)
    assert halt_code(br.author_target, str(tmp_path), "docs/a.md") == "AUTHOR_PATH_UNSAFE_TARGET"


def test_author_target_probe_failure_after_resolution_stops(tmp_path, monkeypatch):
    (tmp_path / "docs").mkdir()
    def broken(path):
        raise OSError("probe failed")
    monkeypatch.setattr(br.os.path, "islink", broken)
    assert halt_code(br.author_target, str(tmp_path), "docs/a.md") == "AUTHOR_PATH_UNSAFE_TARGET"


def test_worktree_hash_check_rejects_before_any_read_process(tmp_path, monkeypatch):
    # Second-opinion counterexample: no hash child process may read a file behind a link.
    # docs/a.md sorts first and is safe; zlink/ leads outside: no path may be read before all are checked.
    work, outside = tmp_path / "work", tmp_path / "outside"
    (work / "docs").mkdir(parents=True)
    outside.mkdir()
    (outside / "a.md").write_bytes(b"synthetic outside text\n")
    _symlink_or_skip(str(outside), str(work / "zlink"), True)
    calls = []
    monkeypatch.setattr(br, "run", lambda args, label, root, timeout=600: calls.append(args) or "")
    table = {"docs/a.md": "0" * 64, "zlink/a.md": "1" * 64}
    assert halt_code(br.verify_hashes, str(work), table, "ADOPT_HASH_MISMATCH") == "AUTHOR_PATH_UNSAFE_TARGET"
    assert calls == []


def test_worktree_hash_check_reads_through_the_primitive_when_paths_are_safe(tmp_path, monkeypatch):
    (tmp_path / "docs").mkdir()
    calls = []
    monkeypatch.setattr(br, "run", lambda args, label, root, timeout=600: calls.append((args[4], args[6], label)) or "")
    br.verify_hashes(str(tmp_path), {"docs/a.md": "0" * 64}, "FOCUSED_AUTHOR_DRIFT")
    assert calls == [("docs/a.md", "0" * 64, "FOCUSED_AUTHOR_DRIFT")]


def test_only_verify_hashes_starts_the_worktree_hash_primitive():
    src = open(br.__file__, encoding="utf-8").read()
    assert src.count("'scripts/verification_primitives.py', 'sha256'") == 1


def _adopt_apply_batch(work, monkeypatch, calls):
    spec = production_spec(start={"mode": "adopt", "start_branch": "batch/prev-261008",
                                  "adopt_hashes": {"docs/a.md": "0" * 64}})
    spec["authors"]["docs/a.md"] = {"source": {"kind": "keep"}, "sha256": "0" * 64}
    spec["ops"] = []
    batch = br.Batch.__new__(br.Batch)
    batch.root, batch.task_id, batch.spec = str(work), TASK, spec
    batch.lines = lines_of(prompt(production_blocks(spec)))
    monkeypatch.setattr(br, "expect_scope", lambda *a, **k: None)
    monkeypatch.setattr(br, "expect_adopt_scope", lambda *a, **k: None)
    monkeypatch.setattr(br, "run", lambda args, label, root, timeout=600: calls.append(args) or "")
    monkeypatch.setattr(batch, "write_new_artifact", lambda suffix, text: ".git/" + TASK + "-" + suffix)
    return batch


def test_adopt_apply_stops_before_reading_a_linked_start_file(tmp_path, monkeypatch):
    work, outside = tmp_path / "work", tmp_path / "outside"
    work.mkdir()
    outside.mkdir()
    (outside / "a.md").write_bytes(b"synthetic outside text\n")
    _symlink_or_skip(str(outside), str(work / "docs"), True)
    calls = []
    batch = _adopt_apply_batch(work, monkeypatch, calls)
    assert halt_code(batch.step_apply) == "AUTHOR_PATH_UNSAFE_TARGET"
    assert calls == [], "the start-hash read process never started"


def test_apply_writes_nothing_when_an_author_path_leads_outside(tmp_path, monkeypatch):
    # docs/a.md sorts first and is inside; scripts/ leads outside. Nothing may be written anywhere.
    work, outside = tmp_path / "work", tmp_path / "outside"
    (work / "docs").mkdir(parents=True)
    outside.mkdir()
    _symlink_or_skip(str(outside), str(work / "scripts"), True)
    spec = production_spec()
    batch = br.Batch.__new__(br.Batch)
    batch.root, batch.task_id, batch.spec = str(work), TASK, spec
    batch.lines = lines_of(prompt(production_blocks(spec)))
    monkeypatch.setattr(br, "expect_head_clean", lambda *a: None)
    monkeypatch.setattr(br, "git", lambda root, *a: spec["branch"])
    monkeypatch.setattr(br, "build_authors", lambda root, s, lines: {"docs/a.md": "y\n", "scripts/new_tool.py": "print(1)\n"})
    monkeypatch.setattr(batch, "write_new_artifact", lambda suffix, text: ".git/" + TASK + "-" + suffix)
    assert halt_code(batch.step_apply) == "AUTHOR_PATH_UNSAFE_TARGET"
    assert os.listdir(str(outside)) == []
    assert not (work / "docs" / "a.md").exists()


def test_apply_writes_nothing_into_git_metadata_through_an_inside_link(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    (tmp_path / "docs").mkdir()
    _symlink_or_skip(str(tmp_path / ".git"), str(tmp_path / "meta"), True)
    spec = production_spec()
    spec["authors"]["meta/synthetic.dat"] = {"source": {"kind": "block", "name": "NEW_TOOL_PY"}, "sha256": sha("print(1)\n")}
    batch = br.Batch.__new__(br.Batch)
    batch.root, batch.task_id, batch.spec = str(tmp_path), TASK, spec
    batch.lines = lines_of(prompt(production_blocks(spec)))
    monkeypatch.setattr(br, "expect_head_clean", lambda *a: None)
    monkeypatch.setattr(br, "git", lambda root, *a: spec["branch"])
    monkeypatch.setattr(br, "build_authors", lambda root, s, lines: {"docs/a.md": "y\n", "meta/synthetic.dat": "print(1)\n",
                                                                       "scripts/new_tool.py": "print(1)\n"})
    monkeypatch.setattr(batch, "write_new_artifact", lambda suffix, text: ".git/" + TASK + "-" + suffix)
    assert halt_code(batch.step_apply) == "AUTHOR_PATH_UNSAFE_TARGET"
    assert os.listdir(str(tmp_path / ".git")) == []
    assert not (tmp_path / "docs" / "a.md").exists()


def test_apply_writes_nothing_when_a_later_parent_directory_is_missing(tmp_path, monkeypatch):
    (tmp_path / "docs").mkdir()
    spec = production_spec()
    batch = br.Batch.__new__(br.Batch)
    batch.root, batch.task_id, batch.spec = str(tmp_path), TASK, spec
    batch.lines = lines_of(prompt(production_blocks(spec)))
    monkeypatch.setattr(br, "expect_head_clean", lambda *a: None)
    monkeypatch.setattr(br, "git", lambda root, *a: spec["branch"])
    monkeypatch.setattr(br, "build_authors", lambda root, s, lines: {"docs/a.md": "y\n", "scripts/new_tool.py": "print(1)\n"})
    monkeypatch.setattr(batch, "write_new_artifact", lambda suffix, text: ".git/" + TASK + "-" + suffix)
    assert halt_code(batch.step_apply) == "PARENT_DIRECTORY_MISSING"
    assert not (tmp_path / "docs" / "a.md").exists()


def test_adopt_keep_source_is_read_only_through_a_plain_parent_chain(tmp_path):
    work, outside = tmp_path / "work", tmp_path / "outside"
    work.mkdir()
    outside.mkdir()
    (outside / "a.md").write_bytes(b"synthetic outside text\n")
    _symlink_or_skip(str(outside), str(work / "docs"), True)
    spec = production_spec(start={"mode": "adopt"})
    spec["authors"]["docs/a.md"]["source"] = {"kind": "keep"}
    assert halt_code(br.source_text, str(work), spec, [], "docs/a.md") == "AUTHOR_PATH_UNSAFE_TARGET"


def _generate_batch(monkeypatch, rec, fail=None):
    spec = production_spec()
    batch = br.Batch.__new__(br.Batch)
    batch.root, batch.task_id, batch.spec = "/nonexistent", TASK, spec

    def verify_hashes(root, table, label):
        rec.calls.append(("worktree", label))
        if fail == label and sum(1 for c in rec.calls if c == ("worktree", label)) == 1:
            raise br.Halt(label)

    monkeypatch.setattr(br, "expect_scope", lambda root, s, label, exact: rec.calls.append(("scope", exact)))
    monkeypatch.setattr(br, "verify_hashes", verify_hashes)
    monkeypatch.setattr(br, "run", lambda args, label, root, timeout=600: rec.calls.append(("run", os.path.basename(args[1]))) or "")
    return batch


def test_generate_checks_authors_before_any_generator_and_again_after(monkeypatch):
    rec = _Recorder()
    _generate_batch(monkeypatch, rec).step_generate()
    assert rec.calls == [("scope", False), ("worktree", "GENERATE_AUTHOR_DRIFT"), ("run", "fingerprint.py"),
                         ("run", "execution_record.py"), ("scope", True), ("worktree", "GENERATE_AUTHOR_DRIFT")]


def test_generate_runs_no_generator_on_drifted_authors(monkeypatch):
    rec = _Recorder()
    batch = _generate_batch(monkeypatch, rec, fail="GENERATE_AUTHOR_DRIFT")
    assert halt_code(batch.step_generate) == "GENERATE_AUTHOR_DRIFT"
    assert not any(c[0] == "run" for c in rec.calls)


# --- G4 slice 2: must-read closure (B-107) ---------------------------------------------------

ALL_RULES = br.MUST_READ_KERNEL + br.MUST_READ_PRODUCTION + tuple(r for _, rs in br.MUST_READ_BY_PREFIX for r in rs)


def _rules_repo(tmp_path, extra=None):
    files = {rel: ("# " + rel + "\n").encode() for rel in ALL_RULES}
    files.update({"runtime/gw/AGENTS.md": b"# gw\n", "skills/AGENTS.md": b"# skills\n",
                  "skills/execution/AGENTS.md": b"# exec\n", "docs/a.md": b"a\n", "skills/execution/x/SKILL.md": b"s\n"})
    files.update(extra or {})
    return _repo_with(tmp_path, files)


def _paths(closure):
    return [f["path"] for f in closure["files"]]


def test_promotion_must_read_is_the_kernel_at_the_candidate(tmp_path):
    repo, head = _rules_repo(tmp_path)
    spec = {"kind": "promotion", "base_oid": "a" * 40, "candidate_oid": head}
    closure = br.derive_must_read(repo, spec)
    assert closure["commit"] == head and _paths(closure) == list(br.MUST_READ_KERNEL)


def test_production_must_read_adds_production_rules_without_unrelated_scoped_files(tmp_path):
    repo, head = _rules_repo(tmp_path)
    spec = production_spec(base_oid=head)
    assert _paths(br.derive_must_read(repo, spec)) == list(br.MUST_READ_KERNEL + br.MUST_READ_PRODUCTION)


def test_skills_and_runtime_paths_add_path_rules_and_every_scoped_agents_on_the_way(tmp_path):
    repo, head = _rules_repo(tmp_path)
    spec = production_spec(base_oid=head)
    spec["authors"] = {"skills/execution/x/SKILL.md": {}, "runtime/gw/src/a.js": {}}
    expected = list(br.MUST_READ_KERNEL + br.MUST_READ_PRODUCTION + br.MUST_READ_BY_PREFIX[0][1]) + \
        ["runtime/gw/AGENTS.md", "skills/AGENTS.md", "skills/execution/AGENTS.md"]
    assert _paths(br.derive_must_read(repo, spec)) == expected


def test_must_read_hashes_are_lf_blob_hashes_at_the_binding_commit(tmp_path):
    repo, head = _rules_repo(tmp_path, {"AGENTS.md": b"# root\r\nline\r\n"})
    (tmp_path / "AGENTS.md").write_bytes(b"changed in the work tree\n")   # the work tree is not the source
    closure = br.derive_must_read(repo, production_spec(base_oid=head))
    assert closure["files"][0] == {"path": "AGENTS.md", "sha256": sha("# root\nline\n")}


@pytest.mark.parametrize("rel", [".agents/rules/new-rule.md", ".agents/rules/nested/deeper.md"])
def test_unmapped_rule_file_stops(tmp_path, rel):
    repo, head = _rules_repo(tmp_path, {rel: b"# new\n"})
    assert halt_code(br.derive_must_read, repo, production_spec(base_oid=head)) == "MUST_READ_RULE_UNMAPPED"


def test_missing_kernel_file_stops(tmp_path):
    repo, _ = _rules_repo(tmp_path)
    _git(repo, "rm", "-q", "PRINCIPLES.md")
    _git(repo, "commit", "-q", "-m", "drop")
    head = _git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    assert halt_code(br.derive_must_read, repo, production_spec(base_oid=head)) == "MUST_READ_FILE_MISSING"


def test_unknown_binding_commit_stops(tmp_path):
    # Fault injection: a binding commit the repository cannot read is a stop, never an empty closure.
    repo, _ = _rules_repo(tmp_path)
    assert halt_code(br.derive_must_read, repo, production_spec(base_oid="e" * 40)) == "GIT_FAILED"


def _must_read_lines(spec, closure, section=None, body=None):
    """A prompt with a formal must-read section (default: the exact generated lines) and the MUST_READ_JSON block."""
    blocks = production_blocks(spec)
    blocks["MUST_READ_JSON"] = closure
    if section is None:
        section = br.must_read_lines(TASK, closure)
    head = body if body is not None else "二、動手前必讀\n" + "\n".join(section) + "\n每個檔案都必須讀到檔尾。\n三、固定命令\n"
    return lines_of(head + prompt(blocks))


def test_check_must_read_accepts_the_exact_closure(tmp_path):
    repo, head = _rules_repo(tmp_path)
    spec = production_spec(base_oid=head)
    assert br.check_must_read(repo, spec, _must_read_lines(spec, br.derive_must_read(repo, spec))) is None


@pytest.mark.parametrize("mutate", [
    lambda c: c["files"].pop(),                                              # a rule left out
    lambda c: c["files"].append({"path": "docs/a.md", "sha256": "0" * 64}),  # an extra file
    lambda c: c["files"].reverse(),                                          # another order
    lambda c: c["files"][0].update(sha256="0" * 64),                        # stale content
    lambda c: c.update(commit="a" * 40),                                     # another commit
    lambda c: c.update(schema_version=2),
])
def test_check_must_read_stops_on_any_difference(tmp_path, mutate):
    repo, head = _rules_repo(tmp_path)
    spec = production_spec(base_oid=head)
    closure = br.derive_must_read(repo, spec)
    mutate(closure)
    assert halt_code(br.check_must_read, repo, spec, _must_read_lines(spec, closure)) == "MUST_READ_MISMATCH"


@pytest.mark.parametrize("body", [None, "not json", "[]"])
def test_check_must_read_stops_on_a_missing_or_invalid_block(tmp_path, body):
    repo, head = _rules_repo(tmp_path)
    spec = production_spec(base_oid=head)
    blocks = production_blocks(spec)
    if body is not None:
        blocks["MUST_READ_JSON"] = body
    assert halt_code(br.check_must_read, repo, spec, lines_of(prompt(blocks))) == "MUST_READ_BLOCK_INVALID"


def test_must_read_block_name_cannot_be_an_author_source():
    spec = production_spec()
    blocks = production_blocks(spec)
    spec["authors"]["docs/a.md"]["source"] = {"kind": "block", "name": "MUST_READ_JSON"}
    assert halt_code(br.load_spec, lines_of(prompt(blocks)), TASK) == "SPEC_SOURCE_INVALID"


def test_every_tracked_rule_file_is_mapped():
    # Repository conformity: the real .agents/rules/ has no file outside the runner's lists.
    out = subprocess.run(["git", "ls-files", "-z", ".agents/rules"], cwd=os.path.dirname(SCRIPTS_DIR),
                         capture_output=True, check=True).stdout.decode().split("\0")
    assert {p for p in out if p.endswith(".md")} <= set(ALL_RULES)


def _preflight_batch(monkeypatch, calls, fail=None):
    batch = br.Batch.__new__(br.Batch)
    batch.root, batch.task_id, batch.spec, batch.lines = os.path.dirname(SCRIPTS_DIR), TASK, production_spec(), ["x"]
    batch.prompt_rel = ".git/" + TASK + "-prompt.txt"
    runner_blob = br.git_blob_sha1(open(br.__file__, "rb").read())
    monkeypatch.setattr(br, "git", lambda root, *a, **k: runner_blob)
    monkeypatch.setattr(br, "run", lambda args, label, root, timeout=600: calls.append(label) or "")

    def check(root, spec, lines):
        calls.append("MUST_READ")
        if fail:
            raise br.Halt(fail)
    monkeypatch.setattr(br, "check_must_read", check)
    return batch


def test_preflight_checks_the_must_read_closure_then_the_work_tree(monkeypatch):
    calls = []
    batch = _preflight_batch(monkeypatch, calls)
    monkeypatch.setattr(br, "derive_must_read", lambda root, spec: {"files": []})
    monkeypatch.setattr(br, "check_must_read_worktree", lambda root, closure: calls.append("WORKTREE"))
    batch.step_preflight()
    assert calls[-2:] == ["MUST_READ", "WORKTREE"]


def test_preflight_stops_when_the_work_tree_differs(monkeypatch):
    calls = []
    batch = _preflight_batch(monkeypatch, calls)
    monkeypatch.setattr(br, "derive_must_read", lambda root, spec: {"files": []})

    def drift(root, closure):
        raise br.Halt("MUST_READ_WORKTREE_DRIFT")
    monkeypatch.setattr(br, "check_must_read_worktree", drift)
    assert halt_code(batch.step_preflight) == "MUST_READ_WORKTREE_DRIFT"


def test_preflight_stops_when_the_must_read_closure_differs(monkeypatch):
    calls = []
    assert halt_code(_preflight_batch(monkeypatch, calls, fail="MUST_READ_MISMATCH").step_preflight) == "MUST_READ_MISMATCH"


# Hand-written expectations from the decided specification (independent of the runner's constants).
SPEC_KERNEL = ["AGENTS.md", "PRINCIPLES.md", ".agents/rules/role-boundaries.md", ".agents/rules/git-and-reporting.md",
               ".agents/rules/governance-gate-integrity.md", ".agents/rules/powershell-encoding-protocol.md"]
SPEC_PRODUCTION = SPEC_KERNEL + [".agents/rules/prompt-preflight.md", ".agents/rules/secret-output-safety.md"]
SPEC_SKILLS = [".agents/rules/skills-architecture.md", ".agents/rules/skill-engineering-guardrails.md"]


def test_written_specification_promotion_production_and_skills(tmp_path):
    repo, head = _rules_repo(tmp_path)
    promo = {"kind": "promotion", "base_oid": "a" * 40, "candidate_oid": head}
    assert _paths(br.derive_must_read(repo, promo)) == SPEC_KERNEL
    assert _paths(br.derive_must_read(repo, production_spec(base_oid=head))) == SPEC_PRODUCTION
    skills = production_spec(base_oid=head)
    skills["authors"] = {"skills/execution/x/SKILL.md": {}}
    assert _paths(br.derive_must_read(repo, skills)) == SPEC_PRODUCTION + SPEC_SKILLS + ["skills/AGENTS.md", "skills/execution/AGENTS.md"]


def _section_case(tmp_path):
    repo, head = _rules_repo(tmp_path)
    spec = production_spec(base_oid=head)
    return repo, spec, br.derive_must_read(repo, spec)


@pytest.mark.parametrize("edit", [
    lambda s: s[:2],                                          # the section leaves rules out (JSON still complete)
    lambda s: [s[0], s[2], s[1]] + s[3:],                     # another order
    lambda s: ["1. AGENTS.md"],                               # a hand-written list only
    lambda s: s + ["99. 本批允許修改之路徑無 scoped 規則檔"],      # any other numbered line in the section
    lambda s: [line.replace("2. ", "3. ", 1) for line in s],  # wrong numbering
])
def test_check_must_read_stops_when_the_section_differs(tmp_path, edit):
    repo, spec, closure = _section_case(tmp_path)
    lines = _must_read_lines(spec, closure, section=edit(br.must_read_lines(TASK, closure)))
    assert halt_code(br.check_must_read, repo, spec, lines) == "MUST_READ_SECTION_MISMATCH"


def test_check_must_read_stops_when_the_list_sits_outside_the_formal_section(tmp_path):
    repo, spec, closure = _section_case(tmp_path)
    listed = "\n".join(br.must_read_lines(TASK, closure))
    for body in ("二、其他說明\n" + listed + "\n三、固定命令\n",                                   # no formal section
                 "二、動手前必讀\n三、固定命令\n" + listed + "\n",                               # list under another heading
                 "二、動手前必讀\n```\n" + listed + "\n```\n三、固定命令\n",                    # list inside a code fence
                 "二、動手前必讀\n" + listed + "\n# 動手前必讀\n" + listed + "\n"):           # two formal sections
        lines = _must_read_lines(spec, closure, body=body)
        assert halt_code(br.check_must_read, repo, spec, lines) == "MUST_READ_SECTION_MISMATCH", body


def test_check_must_read_section_probe_failure_stops(tmp_path, monkeypatch):
    # Fault injection: the section locator failing is a stop, never an acceptance.
    repo, spec, closure = _section_case(tmp_path)
    lines = _must_read_lines(spec, closure)

    def broken(text):
        raise ValueError("locator failed")
    monkeypatch.setattr(br, "extract_must_read_section", broken)
    assert halt_code(br.check_must_read, repo, spec, lines) == "MUST_READ_SECTION_MISMATCH"


def test_runner_uses_the_validators_section_rule():
    import validate_prompt_manifest as vpm
    assert br.extract_must_read_section is vpm.extract_must_read_section


def test_worktree_must_read_files_equal_to_the_binding_commit_pass(tmp_path):
    repo, spec, closure = _section_case(tmp_path)
    (tmp_path / "AGENTS.md").write_bytes(("# AGENTS.md\n").replace("\n", "\r\n").encode())   # CRLF checkout is fine
    assert br.check_must_read_worktree(repo, closure) is None


@pytest.mark.parametrize("change", [
    lambda root: (root / ".agents/rules/role-boundaries.md").write_bytes(b"# locally edited\n"),   # adopt or local edit
    lambda root: (root / "PRINCIPLES.md").unlink(),                                                # file missing
])
def test_worktree_must_read_drift_stops(tmp_path, change):
    repo, spec, closure = _section_case(tmp_path)
    change(tmp_path)
    assert halt_code(br.check_must_read_worktree, repo, closure) == "MUST_READ_WORKTREE_DRIFT"


def test_worktree_must_read_file_behind_a_link_stops(tmp_path):
    repo, spec, closure = _section_case(tmp_path)
    real = tmp_path / "elsewhere.md"
    real.write_bytes((tmp_path / "AGENTS.md").read_bytes())
    (tmp_path / "AGENTS.md").unlink()
    _symlink_or_skip(str(real), str(tmp_path / "AGENTS.md"), False)
    assert halt_code(br.check_must_read_worktree, repo, closure) == "AUTHOR_PATH_UNSAFE_TARGET"


def test_adopt_start_with_an_edited_rule_file_stops_at_preflight(tmp_path):
    # Second-opinion counterexample: adopt hashes cannot stand in for the must-read binding.
    repo, head = _rules_repo(tmp_path)
    (tmp_path / ".agents/rules/role-boundaries.md").write_bytes(b"# edited under adopt\n")
    spec = production_spec(base_oid=head, start={"mode": "adopt", "start_branch": "batch/prev-261008",
                                                 "adopt_hashes": {".agents/rules/role-boundaries.md": sha("# edited under adopt\n")}})
    spec["authors"][".agents/rules/role-boundaries.md"] = {"source": {"kind": "keep"}, "sha256": sha("# edited under adopt\n")}
    closure = br.derive_must_read(repo, spec)
    assert br.check_must_read(repo, spec, _must_read_lines(spec, closure)) is None   # the prompt itself is consistent
    assert halt_code(br.check_must_read_worktree, repo, closure) == "MUST_READ_WORKTREE_DRIFT"


# --- G4 slice 3a: Windows device names and hard links (B-107) -------------------------------

# Hand-written expectations. Official: Microsoft "Naming Files, Paths, and Namespaces" (reserved device names,
# also followed by an extension; superscript digits one to three count as digits). Policy: project additions.
OFFICIAL_DEVICE_SEGMENTS = (["CON", "PRN", "AUX", "NUL"] + ["COM%d" % i for i in range(1, 10)]
                            + ["LPT%d" % i for i in range(1, 10)]
                            + ["COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³"])
POLICY_DEVICE_SEGMENTS = ["COM0", "LPT0", "CONIN$", "CONOUT$"]


@pytest.mark.parametrize("name", OFFICIAL_DEVICE_SEGMENTS + POLICY_DEVICE_SEGMENTS)
def test_windows_device_name_is_rejected_in_any_case_with_any_extension_in_any_segment(name):
    for seg in (name, name.lower(), name.title(), name + ".txt", name.lower() + ".tar.gz", name.title() + ".md",
                name + " .md"):
        for path in (seg, "docs/" + seg, seg + "/a.md", "docs/" + seg + "/a.md"):
            assert br.windows_device_segment(seg) is True, seg
            assert br.safe_author_path(path) is False, path


@pytest.mark.parametrize("path", ["docs/nul.txt", "AUX/a.md", "docs/Com¹.md", "docs/conout$", "docs/lpt0.md"])
def test_device_name_author_path_stops_load_spec(path):
    spec = production_spec()
    blocks = production_blocks(spec)
    spec["authors"][path] = {"source": {"kind": "base"}, "sha256": "0" * 64}
    assert halt_code(br.load_spec, lines_of(prompt(blocks)), TASK) == "SPEC_AUTHOR_PATH_INVALID"


@pytest.mark.parametrize("path", ["docs/console.md", "docs/CONNECT.md", "docs/com10.md", "docs/LPT10.txt", "docs/com.md",
                                  "docs/lpt", "docs/auxiliary/a.md", "docs/nul_notes.md", "docs/prn-guide.md",
                                  "docs/xcon.md", "docs/CONIN.md", "docs/COM⁴.md", "docs/.con", "docs/a.nul"])
def test_names_that_only_resemble_device_names_stay_accepted(path):
    assert br.safe_author_path(path) is True


def test_device_name_rule_keeps_the_trailing_dot_and_space_rules():
    for path in ("docs/a.md.", "docs/a.md ", "docs/CON.", "docs/nul "):
        assert br.safe_author_path(path) is False


def _hardlink_or_skip(src, dst):
    try:
        os.link(src, dst)
    except (OSError, NotImplementedError, AttributeError) as exc:
        pytest.skip("capability gap: hard links cannot be created here (" + type(exc).__name__ + ")")


def test_author_target_hard_linked_to_a_file_outside_stops_and_the_outside_file_is_unchanged(tmp_path):
    work, outside = tmp_path / "work", tmp_path / "outside"
    (work / "docs").mkdir(parents=True)
    outside.mkdir()
    (outside / "a.md").write_bytes(b"synthetic outside text\n")
    _hardlink_or_skip(str(outside / "a.md"), str(work / "docs" / "a.md"))
    assert halt_code(br.author_target, str(work), "docs/a.md") == "AUTHOR_PATH_UNSAFE_TARGET"
    assert (outside / "a.md").read_bytes() == b"synthetic outside text\n"


def test_author_target_hard_linked_inside_the_work_tree_stops_for_both_names(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_bytes(b"x\n")
    _hardlink_or_skip(str(tmp_path / "docs" / "a.md"), str(tmp_path / "docs" / "b.md"))
    assert halt_code(br.author_target, str(tmp_path), "docs/a.md") == "AUTHOR_PATH_UNSAFE_TARGET"
    assert halt_code(br.author_target, str(tmp_path), "docs/b.md") == "AUTHOR_PATH_UNSAFE_TARGET"


def test_author_target_single_link_file_and_missing_file_are_returned(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_bytes(b"x\n")
    base = os.path.realpath(str(tmp_path))
    assert br.author_target(str(tmp_path), "docs/a.md") == os.path.join(base, "docs", "a.md")
    assert br.author_target(str(tmp_path), "docs/new.md") == os.path.join(base, "docs", "new.md")


def test_author_target_directory_in_place_of_the_file_stops(tmp_path):
    (tmp_path / "docs" / "a.md").mkdir(parents=True)
    assert halt_code(br.author_target, str(tmp_path), "docs/a.md") == "AUTHOR_PATH_UNSAFE_TARGET"


def _fake_target_lstat(monkeypatch, target, result):
    real = os.lstat
    def fake(path, *a, **k):
        if os.fspath(path) == target:
            if isinstance(result, BaseException):
                raise result
            return result
        return real(path, *a, **k)
    monkeypatch.setattr(br.os, "lstat", fake)


@pytest.mark.parametrize("nlink", [0, 2, 3])
def test_author_target_link_count_other_than_one_stops(tmp_path, monkeypatch, nlink):
    # Fault injection: 0 stands for a link count that cannot be determined.
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_bytes(b"x\n")
    target = os.path.join(os.path.realpath(str(tmp_path)), "docs", "a.md")
    st = os.lstat(target)
    fake = os.stat_result((st.st_mode, st.st_ino, st.st_dev, nlink, st.st_uid, st.st_gid, st.st_size,
                           int(st.st_atime), int(st.st_mtime), int(st.st_ctime)))
    _fake_target_lstat(monkeypatch, target, fake)
    assert halt_code(br.author_target, str(tmp_path), "docs/a.md") == "AUTHOR_PATH_UNSAFE_TARGET"


@pytest.mark.parametrize("error", [PermissionError("denied"), OSError("probe failed"), ValueError("bad path")])
def test_author_target_link_count_probe_failure_stops(tmp_path, monkeypatch, error):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_bytes(b"x\n")
    target = os.path.join(os.path.realpath(str(tmp_path)), "docs", "a.md")
    _fake_target_lstat(monkeypatch, target, error)
    assert halt_code(br.author_target, str(tmp_path), "docs/a.md") == "AUTHOR_PATH_UNSAFE_TARGET"


def _apply_batch(work, monkeypatch, texts):
    spec = production_spec()
    batch = br.Batch.__new__(br.Batch)
    batch.root, batch.task_id, batch.spec = str(work), TASK, spec
    batch.lines = lines_of(prompt(production_blocks(spec)))
    monkeypatch.setattr(br, "expect_head_clean", lambda *a: None)
    monkeypatch.setattr(br, "git", lambda root, *a: spec["branch"])
    monkeypatch.setattr(br, "build_authors", lambda root, s, lines: dict(texts))
    monkeypatch.setattr(batch, "write_new_artifact", lambda suffix, text: ".git/" + TASK + "-" + suffix)
    return batch


def test_apply_writes_nothing_when_a_later_target_is_hard_linked_outside(tmp_path, monkeypatch):
    # docs/a.md sorts first and is a plain file; scripts/new_tool.py is a hard link to a file outside.
    work, outside = tmp_path / "work", tmp_path / "outside"
    (work / "docs").mkdir(parents=True)
    (work / "scripts").mkdir()
    outside.mkdir()
    (work / "docs" / "a.md").write_bytes(b"original\n")
    (outside / "tool.py").write_bytes(b"synthetic outside program\n")
    _hardlink_or_skip(str(outside / "tool.py"), str(work / "scripts" / "new_tool.py"))
    batch = _apply_batch(work, monkeypatch, {"docs/a.md": "y\n", "scripts/new_tool.py": "print(1)\n"})
    assert halt_code(batch.step_apply) == "AUTHOR_PATH_UNSAFE_TARGET"
    assert (work / "docs" / "a.md").read_bytes() == b"original\n"
    assert (outside / "tool.py").read_bytes() == b"synthetic outside program\n"


def test_apply_writes_nothing_when_a_later_target_is_a_directory(tmp_path, monkeypatch):
    (tmp_path / "docs").mkdir()
    (tmp_path / "scripts" / "new_tool.py").mkdir(parents=True)
    (tmp_path / "docs" / "a.md").write_bytes(b"original\n")
    batch = _apply_batch(tmp_path, monkeypatch, {"docs/a.md": "y\n", "scripts/new_tool.py": "print(1)\n"})
    assert halt_code(batch.step_apply) == "AUTHOR_PATH_UNSAFE_TARGET"
    assert (tmp_path / "docs" / "a.md").read_bytes() == b"original\n"


def test_worktree_hash_check_stops_on_a_hard_link_before_any_read_process(tmp_path, monkeypatch):
    work, outside = tmp_path / "work", tmp_path / "outside"
    (work / "docs").mkdir(parents=True)
    outside.mkdir()
    (outside / "z.md").write_bytes(b"synthetic outside text\n")
    _hardlink_or_skip(str(outside / "z.md"), str(work / "docs" / "z.md"))
    calls = []
    monkeypatch.setattr(br, "run", lambda args, label, root, timeout=600: calls.append(args) or "")
    table = {"docs/a.md": "0" * 64, "docs/z.md": "1" * 64}
    assert halt_code(br.verify_hashes, str(work), table, "FOCUSED_AUTHOR_DRIFT") == "AUTHOR_PATH_UNSAFE_TARGET"
    assert calls == []


def test_adopt_keep_source_that_is_hard_linked_stops_before_reading(tmp_path):
    work, outside = tmp_path / "work", tmp_path / "outside"
    (work / "docs").mkdir(parents=True)
    outside.mkdir()
    (outside / "a.md").write_bytes(b"synthetic outside text\n")
    _hardlink_or_skip(str(outside / "a.md"), str(work / "docs" / "a.md"))
    spec = production_spec(start={"mode": "adopt"})
    spec["authors"]["docs/a.md"]["source"] = {"kind": "keep"}
    assert halt_code(br.source_text, str(work), spec, [], "docs/a.md") == "AUTHOR_PATH_UNSAFE_TARGET"


def test_worktree_must_read_file_that_is_hard_linked_stops(tmp_path):
    repo, spec, closure = _section_case(tmp_path)
    _hardlink_or_skip(str(tmp_path / "AGENTS.md"), str(tmp_path.parent / (tmp_path.name + "-agents-copy.md")))
    assert halt_code(br.check_must_read_worktree, repo, closure) == "AUTHOR_PATH_UNSAFE_TARGET"


def test_author_target_non_regular_entry_with_one_link_stops(tmp_path, monkeypatch):
    # Fault injection: on Windows a directory reports one link, so the regular-file rule must stop it by itself.
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_bytes(b"x\n")
    target = os.path.join(os.path.realpath(str(tmp_path)), "docs", "a.md")
    st = os.lstat(target)
    fake = os.stat_result((stat.S_IFDIR | 0o755, st.st_ino, st.st_dev, 1, st.st_uid, st.st_gid, st.st_size,
                           int(st.st_atime), int(st.st_mtime), int(st.st_ctime)))
    _fake_target_lstat(monkeypatch, target, fake)
    assert halt_code(br.author_target, str(tmp_path), "docs/a.md") == "AUTHOR_PATH_UNSAFE_TARGET"


def test_author_target_named_pipe_stops(tmp_path):
    (tmp_path / "docs").mkdir()
    if not hasattr(os, "mkfifo"):
        pytest.skip("capability gap: named pipes cannot be created here (no os.mkfifo)")
    os.mkfifo(str(tmp_path / "docs" / "a.md"))
    assert os.lstat(str(tmp_path / "docs" / "a.md")).st_nlink == 1
    assert halt_code(br.author_target, str(tmp_path), "docs/a.md") == "AUTHOR_PATH_UNSAFE_TARGET"


def test_apply_write_failure_after_the_checks_is_not_atomic(tmp_path, monkeypatch):
    # Documented limitation (second opinion N1): the checks precede every write, but the writes are not one
    # transaction. An access error on the second target leaves the first target written and stops the step.
    (tmp_path / "docs").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "docs" / "a.md").write_bytes(b"original\n")
    batch = _apply_batch(tmp_path, monkeypatch, {"docs/a.md": "y\n", "scripts/new_tool.py": "print(1)\n"})
    real_open = open
    failing = os.path.join(os.path.realpath(str(tmp_path)), "scripts", "new_tool.py")
    def fake_open(file, mode="r", *a, **k):
        if os.fspath(file) == failing and "w" in mode:
            raise PermissionError("synthetic access error")
        return real_open(file, mode, *a, **k)
    monkeypatch.setattr("builtins.open", fake_open)
    with pytest.raises(PermissionError):
        batch.step_apply()
    monkeypatch.setattr("builtins.open", real_open)
    assert (tmp_path / "docs" / "a.md").read_bytes() == b"y\n"
    assert not (tmp_path / "scripts" / "new_tool.py").exists()




class _SyntheticStepRecord:
    """Test-only stdout sink for fake Batch objects without a .git task-artifact guard."""
    def __init__(self, *_args):
        self.stdout = sys.stdout
    def write(self, value):
        return self.stdout.write(value)
    def flush(self):
        self.stdout.flush()
    def finish(self, result):
        return True
    def abort(self):
        pass

def test_main_locks_the_task_when_a_step_raises_unexpectedly(monkeypatch, capsys):
    # The stop after a non-atomic write failure: main records UNEXPECTED_<type> and the task stays locked.
    from pathlib import Path as _P
    monkeypatch.chdir(str(_P(br.__file__).resolve().parent.parent))
    saved = {}

    class FakeBatch:
        def __init__(self, root, task_id):
            self.root, self.task_id = root, task_id
            self.spec = {"kind": "production", "e24": True, "focused": None}
            self.prompt_bytes = b"synthetic prompt"

        def step_apply(self):
            raise PermissionError("synthetic access error")

    monkeypatch.setattr(br, "Batch", FakeBatch)
    monkeypatch.setattr(br, "load_control", lambda b: {"task_id": TASK, "prompt_sha256": br.sha256_bytes(b"synthetic prompt"),
                                                       "runner_sha256": "R", "done": ["preflight", "setup", "e24"],
                                                       "halted": None})
    monkeypatch.setattr(br, "accepted_runner_sha", lambda root, spec, control, runner_sha: "R")
    monkeypatch.setattr(br, "save_control", lambda b, c: saved.update(c))
    monkeypatch.setattr(br, '_StepRecord', _SyntheticStepRecord)
    assert br.main(["--task-id", TASK, "apply"]) == 1
    assert saved["halted"] == "apply:UNEXPECTED_PermissionError"
    assert "S1 UNEXPECTED_PermissionError | step apply" in capsys.readouterr().out


# --- B-119 / U-04: before-control production admission ------------------------

def _u04_batch(mode='clean'):
    b=br.Batch.__new__(br.Batch)
    b.root='isolated-root'
    b.spec={'kind':'production','base_oid':BASE,
            'start': {'mode': mode, 'start_branch':'batch/adopt-261020',
                      'adopt_hashes': {'docs/a.md': '1'*64}} if mode=='adopt' else {'mode':'clean'},
            'branch':'batch/u04-261020'}
    return b


def _u04_git(monkeypatch, *, head=BASE, branch='', remote=BASE, shallow=False):
    calls=[]
    def fake(root,*args,**kwargs):
        calls.append(args)
        if args==('rev-parse','--is-shallow-repository'):
            return 'true' if shallow else 'false'
        if args==('rev-parse','HEAD'):
            return head
        if args==('branch','--show-current'):
            return branch
        if args==('ls-remote','origin','refs/heads/main'):
            if remote == 'RAISE':
                raise br.Halt('START_REMOTE_QUERY_FAILED')
            return remote+'\trefs/heads/main' if remote else ''
        raise AssertionError(args)
    monkeypatch.setattr(br,'git',fake)
    monkeypatch.setattr(br,'status_lines',lambda root: [])
    monkeypatch.setattr(br,'runtime_readiness_check',lambda root: None)
    return calls


@pytest.mark.parametrize('branch', ['', 'main', 'batch/old-261019'])
def test_u04_clean_correct_head_accepts_detached_and_old_branch(monkeypatch,branch):
    calls=_u04_git(monkeypatch,branch=branch)
    br.precontrol_start_guard(_u04_batch())
    assert ('ls-remote','origin','refs/heads/main') in calls
    assert not any(args and args[0] in ('fetch','switch','commit') for args in calls)


@pytest.mark.parametrize('case', ['wrong_head','dirty','remote_drift','remote_missing',
                                   'remote_bad_sha','query_error','shallow'])
def test_u04_rejects_without_fetch_or_branch_mutation(monkeypatch,case):
    head='b'*40 if case=='wrong_head' else BASE
    remote=('b'*40 if case=='remote_drift' else '' if case=='remote_missing' else
            'bad' if case=='remote_bad_sha' else 'RAISE' if case=='query_error' else BASE)
    calls=_u04_git(monkeypatch,head=head,remote=remote,shallow=case=='shallow')
    if case=='dirty':
        monkeypatch.setattr(br,'status_lines',lambda root:['?? illegal.tmp'])
    expected=('START_STATE_MISMATCH' if case in ('wrong_head','dirty') else
              'ORIGIN_MAIN_DRIFT' if case=='remote_drift' else
              'START_REMOTE_QUERY_INVALID' if case in ('remote_missing','remote_bad_sha') else
              'START_REMOTE_QUERY_FAILED' if case=='query_error' else 'SHALLOW_CLONE')
    assert halt_code(br.precontrol_start_guard,_u04_batch())==expected
    assert not any(args and args[0] in ('fetch','switch','commit') for args in calls)


def test_u04_adopt_accepts_valid_existing_scope_and_hashes(monkeypatch):
    calls=_u04_git(monkeypatch,branch='batch/adopt-261020')
    monkeypatch.setattr(br,'staged_paths',lambda root:[])
    monkeypatch.setattr(br,'expect_adopt_scope',lambda *args: None)
    monkeypatch.setattr(br,'verify_hashes',lambda *args: None)
    br.precontrol_start_guard(_u04_batch('adopt'))
    assert ('ls-remote','origin','refs/heads/main') in calls


@pytest.mark.parametrize('problem', ['branch','index','scope','hash'])
def test_u04_adopt_rejects_invalid_start(monkeypatch,problem):
    calls=_u04_git(monkeypatch,branch='wrong' if problem=='branch' else 'batch/adopt-261020')
    monkeypatch.setattr(br,'staged_paths',lambda root:['docs/a.md'] if problem=='index' else [])
    def scope(*args):
        if problem=='scope':
            raise br.Halt('PRECONTROL_SCOPE_MISMATCH')
    def hashes(*args):
        if problem=='hash':
            raise br.Halt('PRECONTROL_ADOPT_HASH_MISMATCH')
    monkeypatch.setattr(br,'expect_adopt_scope',scope)
    monkeypatch.setattr(br,'verify_hashes',hashes)
    assert halt_code(br.precontrol_start_guard,_u04_batch('adopt'))=='START_STATE_MISMATCH'
    assert ('ls-remote','origin','refs/heads/main') not in calls


def test_u04_first_preflight_checks_guard_before_new_control(monkeypatch,tmp_path):
    class Stub:
        def __init__(self,*args):
            self.spec={'kind':'production','base_oid':BASE,'start':{'mode':'clean'}}
            self.root=str(tmp_path)
            self.prompt_bytes=b'canonical bytes'
            self.prompt_rel='.git/UNIT-BATCH-261008-prompt.txt'
            self.lines=[]
            self.control_rel='.git/UNIT-BATCH-261008-control.json'
            self.task_id=TASK
        def write_new_artifact(self,*args):
            raise AssertionError('control must not be written on invalid HEAD')
    monkeypatch.setattr(br,'Batch',Stub)
    monkeypatch.setattr(br,'derive_steps',lambda spec:['preflight','setup'])
    monkeypatch.setattr(br,'load_control',lambda batch:None)
    monkeypatch.setattr(br,'precontrol_start_guard',lambda batch: (_ for _ in ()).throw(br.Halt('START_STATE_MISMATCH')))
    monkeypatch.setattr(br.Path,'cwd',lambda:tmp_path)
    monkeypatch.setattr(br,'__file__',str(tmp_path/'scripts'/'batch_runner.py'))
    # main uses the repo root derived from its source file; this is a synthetic
    # admission test and does not need a GitHub remote or a working control file.
    assert br.main(['--task-id', TASK, 'preflight'])==1

# B-115/B-119: readonly is a non-executable delivery kind, not a disguised production batch.
def test_readonly_spec_fixed_probe_only_no_mutations():
    spec = {'schema_version':1, 'task_id':TASK, 'kind':'readonly', 'base_oid':BASE,
            'probe_id':'C9_RECOVERY_PREFLIGHT_V1',
            's1_task_id':'B119-N7N8-POSTMAIN-STATE-R1-261018',
            's1_base_oid':'fdd59488a0632d0654fc6a1251bba004502cef51',
            'allowed_mutation_paths':'NONE', 'required_mutation_paths':'NONE',
            'execution_record_required':False, 'external_artifact_write':'FORBIDDEN'}
    parsed = br.load_spec(lines_of(prompt({'BATCH_SPEC_JSON': spec})), TASK)
    assert parsed == spec and br.derive_steps(parsed) == []
    for key, val in [('probe_id', 'COMMAND'), ('s1_task_id','UNBOUNDED'),
                     ('s1_base_oid','f'*40)]:
        altered = dict(spec, **{key:val})
        assert halt_code(br.load_spec, lines_of(prompt({'BATCH_SPEC_JSON': altered})), TASK) == 'READONLY_PROBE_NOT_REGISTERED'
    for key, val in [('allowed_mutation_paths','docs/TASKBOARD.md'),
                     ('required_mutation_paths','docs/TASKBOARD.md'),
                     ('execution_record_required',True),
                     ('external_artifact_write','DOWNLOADS_BUNDLE_AFTER_PUSH')]:
        altered = dict(spec, **{key:val})
        assert halt_code(br.load_spec, lines_of(prompt({'BATCH_SPEC_JSON': altered})), TASK) == 'READONLY_MUTATION_FORBIDDEN'
    for key in ('script_sha256','readonly_script','branch','authors','ops','commit_message','e24','bundle_output'):
        altered = dict(spec, **{key:'unsafe'})
        assert halt_code(br.load_spec, lines_of(prompt({'BATCH_SPEC_JSON': altered})), TASK) == 'READONLY_SPEC_FIELDS'
    assert halt_code(br.load_spec, lines_of(prompt({'BATCH_SPEC_JSON': spec,
        'READONLY_SCRIPT': 'git push origin main'})), TASK) == 'READONLY_ARBITRARY_SCRIPT_FORBIDDEN'


def test_readonly_runner_rejects_all_steps_before_control_creation(monkeypatch,tmp_path):
    class Stub:
        def __init__(self,*args):
            self.spec={'kind':'readonly'}
            self.prompt_bytes=b'bound'
            self.root=str(tmp_path)
    monkeypatch.setattr(br,'Batch',Stub)
    monkeypatch.setattr(br.Path,'cwd',lambda:tmp_path)
    monkeypatch.setattr(br,'__file__',str(tmp_path/'scripts'/'batch_runner.py'))
    monkeypatch.setattr(br,'load_control',lambda _: (_ for _ in ()).throw(AssertionError('must not load control')))
    for step in ('preflight', 'setup', 'apply', 'stage', 'commit', 'push', 'verify', 'promote', 'postmain'):
        assert br.main(['--task-id', TASK, step]) == 1


@pytest.mark.parametrize('reason', [
    'PYTEST_UNAVAILABLE', 'PYTEST_MISMATCH', 'NODE_MISSING',
    'NODE_RANGE_MISMATCH', 'ENGINES_UNSUPPORTED', 'PYTHON_ALIAS_FORBIDDEN',
])
def test_g5_runtime_reason_classified_without_raw_leak(reason):
    output=('RUNTIME_MISMATCH '+reason+'\n').encode('ascii')
    assert br.classify_failure(1,b'',output)=='exit=1 class='+reason
    assert br.classify_failure(1,b'',b'RUNTIME_MISMATCH PRIVATE_PATH=/user/private')=='exit=1 class=DETAIL_UNAVAILABLE'

def test_g5_runtime_outer_timeout_allows_two_probe_budgets(monkeypatch):
    observed=[]
    def fake_run(args,label,root,timeout=600):
        observed.append((list(args),label,timeout))
        return 'RUNTIME_READY'
    monkeypatch.setattr(br,'run',fake_run)
    br.runtime_readiness_check('/synthetic')
    assert observed==[([br.PY,'scripts/runtime_readiness.py'],'RUNTIME_MISMATCH',50)]


G5_RUNTIME_W01_CLASSES = (
    'PYTEST_MISMATCH', 'PYTEST_UNAVAILABLE', 'NODE_MISSING',
    'NODE_RANGE_MISMATCH', 'ENGINES_UNSUPPORTED', 'PYTHON_ALIAS_FORBIDDEN',
    'NODE_ALIAS_FORBIDDEN', 'PROCESS_NONZERO', 'PROCESS_UNAVAILABLE',
    'SOURCE_INVALID', 'SOURCE_UNREADABLE', 'PYTEST_PIN_INVALID',
    'NVMRC_INVALID', 'ENGINES_INVALID', 'NODE_VERSION_INVALID',
    'PROCESS_OUTPUT_INVALID',
)


@pytest.mark.parametrize('reason', G5_RUNTIME_W01_CLASSES)
@pytest.mark.parametrize('newline', [b'\n', b'\r\n'])
@pytest.mark.parametrize('channel', ['stdout', 'stderr'])
def test_g5_w01_runtime_crlf_exact_both_channels(reason, newline, channel):
    payload = b'RUNTIME_MISMATCH ' + reason.encode('ascii') + newline
    stderr, stdout = (payload, b'') if channel == 'stderr' else (b'', payload)
    assert br.classify_failure(1, stderr, stdout) == 'exit=1 class=' + reason


@pytest.mark.parametrize('newline', [b'\n', b'\r\n'])
def test_g5_w01_rejects_nonanchored_or_invalid_runtime_lines(newline):
    for prefix, suffix in [(b'x', b''), (b'', b' suffix'), (b'', b'\r\r')]:
        payload = prefix + b'RUNTIME_MISMATCH NODE_MISSING' + suffix + newline
        # `\r\r\n` must not be accepted as a valid single CRLF suffix.
        assert br.classify_failure(1, b'', payload) == 'exit=1 class=DETAIL_UNAVAILABLE'
    payload = b'RUNTIME_MISMATCH PRIVATE_DETAIL=token\r\n'
    assert br.classify_failure(1, b'', payload) == 'exit=1 class=DETAIL_UNAVAILABLE'


# B-117/G5 D-2: control atomicity and bounded failure injection; synthetic .git only.
class _D2ControlBatch:
    def __init__(self, root):
        self.root = str(root)
        self.task_id = TASK
        self.control_rel = '.git/' + TASK + '-control.json'

    def artifact(self, suffix):
        rel = '.git/' + self.task_id + '-' + suffix
        import governance_preflight as gp
        ok, reason = gp.verify_task_artifact_path(self.root, self.task_id, rel)
        if not ok:
            raise br.Halt('ARTIFACT_PATH_GUARD_FAILED')
        return rel


def _d2_control(tmp_path):
    (tmp_path / '.git').mkdir()
    batch = _D2ControlBatch(tmp_path)
    path = tmp_path / batch.control_rel
    path.write_bytes(b'{"prior":true}\n')
    return batch, path


def test_d2_save_control_replaces_same_directory_fsyncs_and_keeps_json(tmp_path, monkeypatch):
    batch, path = _d2_control(tmp_path)
    old = path.stat().st_ino
    original_fsync = br.os.fsync
    original_replace = br.os.replace
    calls = []
    def track_fsync(fd):
        calls.append('fsync')
        return original_fsync(fd)
    def track_replace(src, dst):
        assert Path(src).parent == path.parent
        assert Path(dst) == path
        assert 'fsync' in calls
        calls.append('replace')
        return original_replace(src, dst)
    monkeypatch.setattr(br.os, 'fsync', track_fsync)
    monkeypatch.setattr(br.os, 'replace', track_replace)
    br.save_control(batch, {'done':['apply'], 'halted':None})
    assert json.loads(path.read_text()) == {'done':['apply'], 'halted':None}
    assert path.stat().st_ino != old
    assert calls == ['fsync','replace']
    br.save_control(batch, {'done':['apply','focused'], 'halted':None})
    assert json.loads(path.read_text())['done'] == ['apply','focused']
    assert list(path.parent.glob(TASK + '-control-tmp-*')) == []


@pytest.mark.parametrize('fault', ['write', 'fsync', 'replace'])
def test_d2_control_save_fault_preserves_old_bytes_and_cleans_temp(tmp_path, monkeypatch, fault):
    batch, path = _d2_control(tmp_path)
    original = path.read_bytes()
    if fault == 'write':
        original_fdopen = br.os.fdopen
        class FailStream:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): self.stream.__enter__(); return self
            def __exit__(self, *args): return self.stream.__exit__(*args)
            def write(self, data): raise OSError('synthetic write failure')
            def flush(self): self.stream.flush()
            def fileno(self): return self.stream.fileno()
        monkeypatch.setattr(br.os, 'fdopen', lambda fd,mode: FailStream(original_fdopen(fd,mode)))
    elif fault == 'fsync':
        monkeypatch.setattr(br.os, 'fsync', lambda *args: (_ for _ in ()).throw(OSError('synthetic fsync failure')))
    else:
        monkeypatch.setattr(br.os, 'replace', lambda *args: (_ for _ in ()).throw(PermissionError('synthetic locked target')))
    assert halt_code(br.save_control, batch, {'done':['preflight']}) == 'CONTROL_SAVE_FAILED'
    assert path.read_bytes() == original
    assert list(path.parent.glob(TASK + '-control-tmp-*')) == []


def test_d2_replace_transient_permission_error_is_retried_bounded_then_saved(tmp_path, monkeypatch):
    batch, path = _d2_control(tmp_path)
    real_replace = br.os.replace
    calls, sleeps = [], []
    def flaky(src, dst):
        calls.append(1)
        if len(calls) <= 3:
            raise PermissionError('synthetic transient lock')
        return real_replace(src, dst)
    monkeypatch.setattr(br.os, 'replace', flaky)
    monkeypatch.setattr(br.time, 'sleep', lambda s: sleeps.append(s))
    br.save_control(batch, {'done':['apply'], 'halted':None})
    assert json.loads(path.read_text()) == {'done':['apply'], 'halted':None}
    assert len(calls) == 4 and sleeps == [0.05, 0.1, 0.2]
    assert list(path.parent.glob(TASK + '-control-tmp-*')) == []


def test_d2_replace_persistent_permission_error_stops_after_bounded_attempts(tmp_path, monkeypatch):
    batch, path = _d2_control(tmp_path)
    original = path.read_bytes()
    calls, sleeps = [], []
    def locked(src, dst):
        calls.append(1)
        raise PermissionError('synthetic persistent lock')
    monkeypatch.setattr(br.os, 'replace', locked)
    monkeypatch.setattr(br.time, 'sleep', lambda s: sleeps.append(s))
    assert halt_code(br.save_control, batch, {'done':['preflight']}) == 'CONTROL_SAVE_FAILED'
    assert len(calls) == len(br.CONTROL_REPLACE_RETRY_DELAYS) + 1
    assert sleeps == list(br.CONTROL_REPLACE_RETRY_DELAYS) and sum(sleeps) <= 2.0
    assert path.read_bytes() == original
    assert list(path.parent.glob(TASK + '-control-tmp-*')) == []


@pytest.mark.parametrize('exc', [OSError('synthetic io'), FileNotFoundError('synthetic missing')])
def test_d2_replace_non_permission_error_is_not_retried(tmp_path, monkeypatch, exc):
    batch, path = _d2_control(tmp_path)
    original = path.read_bytes()
    calls, sleeps = [], []
    def broken(src, dst):
        calls.append(1)
        raise exc
    monkeypatch.setattr(br.os, 'replace', broken)
    monkeypatch.setattr(br.time, 'sleep', lambda s: sleeps.append(s))
    assert halt_code(br.save_control, batch, {'done':['preflight']}) == 'CONTROL_SAVE_FAILED'
    assert len(calls) == 1 and sleeps == []
    assert path.read_bytes() == original


def test_d2_existing_control_hardlink_to_outside_rejected_without_mutation(tmp_path):
    batch, path = _d2_control(tmp_path)
    outside = tmp_path / 'outside-control.json'
    try:
        os.link(path, outside)
    except OSError as exc:
        pytest.fail('D-2 hardlink capability missing: ' + type(exc).__name__)
    old = path.read_bytes()
    assert halt_code(br.save_control, batch, {'done':['preflight']}) == 'ARTIFACT_PATH_GUARD_FAILED'
    assert path.read_bytes() == old and outside.read_bytes() == old
    assert list(path.parent.glob(TASK + '-control-tmp-*')) == []


def test_d2_main_emits_s1_and_no_step_pass_when_atomic_control_replace_fails(tmp_path, monkeypatch, capsys):
    # Exercise the caller, not only the save helper: no successful step line is allowed.
    class Stub:
        def __init__(self,*args):
            self.root = str(tmp_path)
            self.task_id = TASK
            self.control_rel = '.git/' + TASK + '-control.json'
            self.prompt_bytes = b'synthetic prompt'
            self.spec = {'kind':'promotion'}
            self.lines = []
        def step_preflight(self): return None
        def artifact(self, suffix): return '.git/' + TASK + '-' + suffix
        def write_new_artifact(self, *args): raise AssertionError('unexpected new control')
    (tmp_path / '.git').mkdir()
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts' / 'batch_runner.py').write_text('synthetic runner\n')
    (tmp_path / '.git' / (TASK + '-control.json')).write_text('{}')
    monkeypatch.setattr(br, 'Batch', Stub)
    monkeypatch.setattr(br, 'derive_steps', lambda _: ['preflight'])
    monkeypatch.setattr(br, 'load_control', lambda _: {'task_id':TASK,
        'prompt_sha256':br.sha256_bytes(b'synthetic prompt'), 'runner_sha256':'fixed', 'done':[], 'halted':None})
    monkeypatch.setattr(br, 'save_control', lambda *args: (_ for _ in ()).throw(br.Halt('CONTROL_SAVE_FAILED')))
    monkeypatch.setattr(br, 'accepted_runner_sha', lambda *a:'fixed')
    monkeypatch.setattr(br.Path, 'cwd', lambda:tmp_path)
    monkeypatch.setattr(br, '__file__', str(tmp_path / 'scripts' / 'batch_runner.py'))
    monkeypatch.setattr(br, '_StepRecord', _SyntheticStepRecord)
    assert br.main(['--task-id', TASK, 'preflight']) == 1
    out = capsys.readouterr().out
    assert 'S1 CONTROL_SAVE_FAILED | step preflight' in out
    assert 'STEP_PASS' not in out


# B117 R3 — per-stage envelope and gate-only timeout mapping.
def test_r3_gate_envelope_covers_nested_kill_and_margin():
    for stage, limit in br.GATE_LIMITS.items():
        expected = sum(br.stage_timeouts(stage)) + len(br.CANONICAL_GATES[stage]) * 2 * br.KILL_GRACE_SECONDS + br.GATE_MARGIN_SECONDS
        assert limit >= expected
        assert br.validate_gate_limits()
        reduced = dict(br.GATE_LIMITS)
        reduced[stage] = expected - 1
        assert not br.validate_gate_limits(reduced)


def test_r3_gate_timeout_code_only_for_gate_step(tmp_path, monkeypatch):
    import bounded_process
    result = bounded_process.BoundedResult(br.GATE_TIMEOUT_EXIT_CODE, False, None, b'', b'', 'NOT_NEEDED')
    def fake(*args, **kw):
        Path(kw['capture_path']).write_bytes(b'')
        return result
    monkeypatch.setattr(br, 'run_bounded', fake)
    b1 = _bounded_batch(tmp_path/'gate', monkeypatch)
    (tmp_path/'gate').mkdir()
    with pytest.raises(br.Halt, match='PRECOMMIT_GATE_TIMEOUT'):
        b1.bounded('PRECOMMIT', ['-c','pass'], 20, gate_timeout=True)
    b2 = _bounded_batch(tmp_path/'focused', monkeypatch)
    (tmp_path/'focused').mkdir()
    assert halt_code(b2.bounded, 'FOCUSED', ['-c','pass'], 20) == 'FOCUSED_NONZERO'


def test_r3_gate_nonzero_stays_nonzero_and_external_timeout_stays_timeout(tmp_path, monkeypatch):
    import bounded_process
    for status, expected in [
        (bounded_process.BoundedResult(3, False, None, b'', b'', 'NOT_NEEDED'), 'POSTCOMMIT_NONZERO'),
        (bounded_process.BoundedResult(None, True, None, b'', b'', 'TREE_SIGNALLED'), 'POSTCOMMIT_TIMEOUT'),
        (bounded_process.BoundedResult(None, False, 'launch', b'', b'', 'NOT_NEEDED'), 'POSTCOMMIT_LAUNCH_FAILED'),
    ]:
        folder = tmp_path/expected; folder.mkdir()
        def fake(*args, **kw):
            Path(kw['capture_path']).write_bytes(b'')
            return status
        monkeypatch.setattr(br, 'run_bounded', fake)
        b = _bounded_batch(folder, monkeypatch)
        with pytest.raises(br.Halt) as exc:
            b.bounded('POSTCOMMIT', ['-c','pass'], 10, gate_timeout=True)
        assert str(exc.value) == expected

# G3: Original S1 is authoritative even when a second failure hits cleanup/diagnostics.
def test_g3_primary_control_write_s1_survives_secondary_temp_cleanup_failure(tmp_path, monkeypatch):
    batch, path = _d2_control(tmp_path)
    old = path.read_bytes()
    monkeypatch.setattr(br.os, 'fsync', lambda *_: (_ for _ in ()).throw(OSError('first write failure')))
    monkeypatch.setattr(br.os, 'unlink', lambda *_: (_ for _ in ()).throw(PermissionError('second cleanup failure')))
    assert halt_code(br.save_control, batch, {'done':['preflight']}) == 'CONTROL_SAVE_FAILED'
    assert path.read_bytes() == old
    # Cleanup failed: retain the untouched task-local temporary artifact for diagnosis.
    assert len(list(path.parent.glob(TASK + '-control-tmp-*'))) == 1


def test_g3_primary_path_guard_s1_survives_secondary_temp_cleanup_failure(tmp_path, monkeypatch):
    batch, path = _d2_control(tmp_path)
    old = path.read_bytes()
    original_artifact = batch.artifact
    calls = []
    def fail_second_artifact(name):
        calls.append(name)
        if len(calls) == 2:
            raise br.Halt('ARTIFACT_PATH_GUARD_FAILED')
        return original_artifact(name)
    monkeypatch.setattr(batch, 'artifact', fail_second_artifact)
    monkeypatch.setattr(br.os, 'unlink', lambda *_: (_ for _ in ()).throw(PermissionError('cleanup fails')))
    assert halt_code(br.save_control, batch, {'halted':'precommit:PRECOMMIT_NONZERO'}) == 'ARTIFACT_PATH_GUARD_FAILED'
    assert path.read_bytes() == old
    assert len(list(path.parent.glob(TASK + '-control-tmp-*'))) == 1


def test_g3_secondary_unexpected_metadata_error_does_not_mask_original_s1(tmp_path, monkeypatch, capsys):
    class DiagnosticsBatch:
        root = str(tmp_path)
        task_id = TASK
        def artifact(self, name): return '.git/' + TASK + '-' + name
    def fail_metadata(*_args, **_kwargs):
        raise RuntimeError('synthetic secondary metadata error; must not leak')
    def fail_capture(*_args, **_kwargs):
        raise RuntimeError('synthetic tertiary capture error; must not leak')
    monkeypatch.setattr(br, 'create_metadata', fail_metadata)
    monkeypatch.setattr(br, 'create_full_capture', fail_capture)
    batch = DiagnosticsBatch()
    reason = br.Halt('PRECOMMIT_NONZERO')
    br.report_halt(reason, 'precommit')
    br.report_s1_metadata(batch, 'precommit', reason)
    br.report_s1_full_capture(batch, 'precommit', reason)
    assert capsys.readouterr().out.splitlines() == [
        'S1 PRECOMMIT_NONZERO | step precommit',
        'S1_EVIDENCE_STATUS=UNAVAILABLE',
        'S1_FULL_CAPTURE_STATUS=UNAVAILABLE',
    ]


# G3 next slice: a failed control save after a step S1 must not erase the first S1.
@pytest.mark.parametrize('exception,original', [
    (br.Halt('PRECOMMIT_GATE_TIMEOUT'), 'PRECOMMIT_GATE_TIMEOUT'),
    (RuntimeError('synthetic failure'), 'UNEXPECTED_RuntimeError'),
])
def test_g3_halted_step_control_save_failure_preserves_primary_code(tmp_path, monkeypatch, capsys, exception, original):
    class Stub:
        def __init__(self, *_args):
            self.root = str(tmp_path)
            self.task_id = TASK
            self.prompt_bytes = b'synthetic prompt'
            self.spec = {'kind': 'promotion'}
        def step_preflight(self):
            raise exception
    (tmp_path / '.git').mkdir()
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts' / 'batch_runner.py').write_text('synthetic runner\n')
    monkeypatch.setattr(br, 'Batch', Stub)
    monkeypatch.setattr(br, 'derive_steps', lambda _: ['preflight'])
    monkeypatch.setattr(br, 'load_control', lambda _: {
        'task_id': TASK, 'prompt_sha256': br.sha256_bytes(b'synthetic prompt'),
        'runner_sha256': 'fixed', 'done': [], 'halted': None,
    })
    monkeypatch.setattr(br, 'save_control', lambda *args: (_ for _ in ()).throw(br.Halt('CONTROL_SAVE_FAILED')))
    monkeypatch.setattr(br, 'accepted_runner_sha', lambda *args: 'fixed')
    monkeypatch.setattr(br.Path, 'cwd', lambda: tmp_path)
    monkeypatch.setattr(br, '__file__', str(tmp_path / 'scripts' / 'batch_runner.py'))
    monkeypatch.setattr(br, '_StepRecord', _SyntheticStepRecord)
    assert br.main(['--task-id', TASK, 'preflight']) == 1
    assert capsys.readouterr().out.splitlines() == [
        'S1 CONTROL_SAVE_FAILED | step preflight',
        'S1_PRIMARY ' + original + ' | step preflight',
        'EXECUTOR_REPLY_UNAVAILABLE TIMING_UNAVAILABLE',
    ]

# B115 G3 CI-PENDING-REPLY R1: task-local, single-writer step output and timing.

def _lf(path, text):
    """Byte-exact LF fixture: Path.write_text translates newlines on Windows (B-123 class)."""
    path.write_bytes(text.encode('utf-8'))


def _g3_output_stub(root, spec=None, task=TASK):
    class Stub:
        def __init__(self):
            self.root = str(root)
            self.task_id = task
            self.spec = spec or {'kind': 'promotion'}
            self.prompt_rel = '.git/' + task + '-prompt.txt'
            self.prompt_bytes = b'prompt'
        def artifact(self, name):
            return '.git/' + self.task_id + '-' + name
        def write_new_artifact(self, name, text):
            rel = self.artifact(name)
            with open(Path(self.root) / rel, 'x', encoding='utf-8', newline='') as f:
                f.write(text)
            return rel
    return Stub()


def test_g3_step_record_complete_once_and_preserves_stdout(tmp_path, capsys):
    (tmp_path / '.git').mkdir()
    b = _g3_output_stub(tmp_path)
    record = br._StepRecord(b, 'preflight')
    record.write('STEP_PASS preflight\n')
    assert record.finish(0) is True
    assert capsys.readouterr().out == 'STEP_PASS preflight\n'
    out = tmp_path / '.git' / (TASK + '-step-preflight.out')
    assert out.read_bytes() == b'STEP_PASS preflight\nSTEP_OUTPUT_COMPLETE step=preflight result=0\n'
    assert halt_code(br._StepRecord, b, 'preflight') == 'STEP_OUTPUT_ALREADY_EXISTS'


def test_g3_step_record_secondary_io_failure_never_masks_stdout(tmp_path, monkeypatch, capsys):
    (tmp_path / '.git').mkdir()
    b = _g3_output_stub(tmp_path)
    rec = br._StepRecord(b, 'precommit')
    monkeypatch.setattr(br.os, 'fsync', lambda fd: (_ for _ in ()).throw(OSError('synthetic fsync')))
    rec.write('S1 PRECOMMIT_NONZERO | step precommit\n')
    assert rec.finish(1) is False
    assert capsys.readouterr().out == 'S1 PRECOMMIT_NONZERO | step precommit\n'
    raw = (tmp_path / '.git' / (TASK + '-step-precommit.out')).read_text()
    assert 'STEP_OUTPUT_COMPLETE' not in raw


def test_g3_step_output_complete_and_truncation_fail_closed(tmp_path):
    (tmp_path / '.git').mkdir()
    b = _g3_output_stub(tmp_path)
    st = ['preflight', 'verify']
    control = {'done': st, 'halted': None}
    for step in st:
        _lf((tmp_path / '.git' / (TASK + '-step-' + step + '.out')),
            'STEP_PASS ' + step + '\nSTEP_OUTPUT_COMPLETE step=' + step + ' result=0\n')
    assert br._step_output_lines(b, st, control) == ['STEP_PASS preflight', 'STEP_PASS verify']
    p = tmp_path / '.git' / (TASK + '-step-verify.out')
    _lf(p, 'STEP_PASS verify\n')
    assert halt_code(br._step_output_lines, b, st, control) == 'REPLY_STEP_OUTPUT_TRUNCATED'
    _lf(p, 'STEP_PASS verify\nSTEP_OUTPUT_COMPLETE step=verify result=0\n')
    assert halt_code(br._step_output_lines, b, st, {'done': ['verify'], 'halted': None}) == 'REPLY_CONTROL_INVALID'


def test_g3_legacy_runner_preapply_without_step_records_is_bound(tmp_path, monkeypatch):
    (tmp_path / '.git').mkdir()
    (tmp_path / 'scripts').mkdir()
    _lf((tmp_path / 'scripts' / 'batch_runner.py'), 'new runner\n')
    base = b"PRODUCTION_STEPS = ('preflight', 'setup', 'e24', 'apply', 'generate')\n"
    steps = ['preflight', 'setup', 'e24', 'apply', 'generate']
    spec = {'kind': 'production', 'runner_update': True, 'base_oid': BASE,
            'authors': {br.RUNNER_REL: {'sha256': br.sha256_bytes(b'new runner\n')}}}
    b = _g3_output_stub(tmp_path, spec)
    control = {'done': steps, 'halted': None, 'runner_sha256': br.sha256_bytes(base)}
    monkeypatch.setattr(br, 'git_bytes', lambda root, *args: base)
    _lf((tmp_path / '.git' / (TASK + '-step-generate.out')),
        'STEP_PASS generate\nSTEP_OUTPUT_COMPLETE step=generate result=0\n')
    assert br._step_output_lines(b, steps, control) == ['STEP_PASS ' + s for s in steps]
    assert halt_code(br._step_output_lines, b, steps, {**control, 'done': steps[:3], 'halted': 'apply:APPLY_FAILED'}) \
           == 'REPLY_STEP_OUTPUT_MISSING'
    assert br._legacy_preapply_record_allowed(b, control, 'generate', steps) is False
    assert br._legacy_preapply_record_allowed(b, control, 'apply', steps) is True


def test_g3_timing_emits_single_bound_reply_and_self_check_after_end(tmp_path, monkeypatch, capsys):
    (tmp_path / '.git').mkdir()
    b = _g3_output_stub(tmp_path)
    st = ['preflight', 'verify']
    for step in st:
        _lf((tmp_path / '.git' / (TASK + '-step-' + step + '.out')),
            'STEP_PASS ' + step + '\nSTEP_OUTPUT_COMPLETE step=' + step + ' result=0\n')
    control = {'task_id': TASK, 'done': st, 'halted': None, 'prompt_sha256': br.sha256_bytes(b'prompt')}
    t = 'TIMING start=2026-11-08T00:00:00+08:00 end=2026-11-08T00:00:02+08:00 elapsed_sec=2.0 elapsed_min=0'
    s = 'STATE done=preflight,verify halted=None'
    monkeypatch.setattr(br, '_timing_lines', lambda root, task: (t, s, control))
    monkeypatch.setattr(br, 'Batch', lambda root, task: b)
    monkeypatch.setattr(br, 'derive_steps', lambda spec: st)
    observed = []
    monkeypatch.setattr(br, '_self_check_reply', lambda batch, reply: observed.append(reply) or 'PASS')
    assert br.timing(str(tmp_path), TASK) == 0
    output = capsys.readouterr().out
    assert output.index('EXECUTOR_REPLY_BEGIN') < output.index('EXECUTOR_REPLY_END') < output.index('REPLY_SELF_CHECK=PASS')
    assert observed[0] == '\n'.join(['STEP_PASS preflight', 'STEP_PASS verify', t, s]) + '\n'


def test_g3_selfcheck_cli_pending_is_not_pass(tmp_path, monkeypatch):
    (tmp_path / '.git').mkdir()
    b = _g3_output_stub(tmp_path)
    from types import SimpleNamespace
    p = SimpleNamespace(returncode=2,
                        stdout=('REPLY_CHECK TASK=' + TASK + ' KIND=production OUTCOME=COMMIT=x\n'
                                'REPLY_CHECK FIELDS=PASS\nREPLY_CHECK RESULT=CI_PENDING\n').encode(), stderr=b'')
    monkeypatch.setattr(br.subprocess, 'run', lambda *a, **kw: p)
    assert br._self_check_reply(b, 'COMMIT x | CI PENDING | S1 NONE\n') == 'CI_PENDING'
    p.returncode = 0
    (tmp_path / 'second' / '.git').mkdir(parents=True)
    assert halt_code(br._self_check_reply, _g3_output_stub(tmp_path / 'second'), 'x') == 'REPLY_SELF_CHECK_CONTRADICTION'


# SO F-1: RESULT=PASS of a well-formed S1 reply (evidence N/A) must never surface as CLASS=PASS.
@pytest.mark.parametrize('rc_, result, outcome, expected', [
    (0, 'PASS', 'S1=commit:COMMIT_FAILED', 'S1'),
    (2, 'NOT_VERIFIED', 'S1=precommit:PRECOMMIT_NONZERO', 'S1'),
    (0, 'PASS', 'COMMIT=x', 'PASS'),
])
def test_g3_selfcheck_class_never_reports_s1_as_pass(tmp_path, monkeypatch, rc_, result, outcome, expected):
    (tmp_path / '.git').mkdir()
    from types import SimpleNamespace
    p = SimpleNamespace(returncode=rc_, stderr=b'', stdout=(
        'REPLY_CHECK TASK=' + TASK + ' KIND=production OUTCOME=' + outcome + '\n'
        'REPLY_CHECK FIELDS=PASS\nREPLY_CHECK RESULT=' + result + '\n').encode())
    monkeypatch.setattr(br.subprocess, 'run', lambda *a, **kw: p)
    assert br._self_check_reply(_g3_output_stub(tmp_path), 'x\n') == expected


@pytest.mark.parametrize('stdout', [
    'REPLY_CHECK FIELDS=PASS\nREPLY_CHECK RESULT=PASS\n',
    'REPLY_CHECK TASK=OTHER-TASK-261108 KIND=production OUTCOME=COMMIT=x\nREPLY_CHECK FIELDS=PASS\nREPLY_CHECK RESULT=PASS\n',
])
def test_g3_selfcheck_requires_single_task_bound_outcome(tmp_path, monkeypatch, stdout):
    (tmp_path / '.git').mkdir()
    from types import SimpleNamespace
    p = SimpleNamespace(returncode=0, stderr=b'', stdout=stdout.encode())
    monkeypatch.setattr(br.subprocess, 'run', lambda *a, **kw: p)
    assert halt_code(br._self_check_reply, _g3_output_stub(tmp_path), 'x\n') == 'REPLY_SELF_CHECK_INVALID'


# SO: D5 negatives that the author suite did not kill under mutation.
def test_g3_interrupted_step_leaves_no_completion_marker(tmp_path, monkeypatch):
    class Stub:
        def __init__(self, *_args):
            self.root = str(tmp_path)
            self.task_id = TASK
            self.prompt_bytes = b'synthetic prompt'
            self.spec = {'kind': 'promotion'}
        def artifact(self, name):
            return '.git/' + TASK + '-' + name
        def step_preflight(self):
            print('BEFORE_INTERRUPT')
            raise KeyboardInterrupt
    (tmp_path / '.git').mkdir()
    (tmp_path / 'scripts').mkdir()
    _lf((tmp_path / 'scripts' / 'batch_runner.py'), 'synthetic runner\n')
    monkeypatch.setattr(br, 'Batch', Stub)
    monkeypatch.setattr(br, 'derive_steps', lambda _: ['preflight'])
    monkeypatch.setattr(br, 'load_control', lambda _: {
        'task_id': TASK, 'prompt_sha256': br.sha256_bytes(b'synthetic prompt'),
        'runner_sha256': 'fixed', 'done': [], 'halted': None})
    monkeypatch.setattr(br, 'accepted_runner_sha', lambda *a: 'fixed')
    monkeypatch.setattr(br.Path, 'cwd', lambda: tmp_path)
    monkeypatch.setattr(br, '__file__', str(tmp_path / 'scripts' / 'batch_runner.py'))
    with pytest.raises(KeyboardInterrupt):
        br.main(['--task-id', TASK, 'preflight'])
    raw = (tmp_path / '.git' / (TASK + '-step-preflight.out')).read_text()
    assert 'BEFORE_INTERRUPT' in raw and 'STEP_OUTPUT_COMPLETE' not in raw


@pytest.mark.parametrize('body', [
    'STEP_PASS verify\nSTEP_PASS verify\nSTEP_OUTPUT_COMPLETE step=verify result=0\n',
    'STEP_OUTPUT_COMPLETE step=verify result=0\nSTEP_PASS verify\nSTEP_OUTPUT_COMPLETE step=verify result=0\n',
    'S1 X | step verify\nSTEP_OUTPUT_COMPLETE step=verify result=0\n',
])
def test_g3_step_output_duplicate_or_missing_pass_or_marker_fail_closed(tmp_path, body):
    (tmp_path / '.git').mkdir()
    b = _g3_output_stub(tmp_path)
    st = ['preflight', 'verify']
    _lf((tmp_path / '.git' / (TASK + '-step-preflight.out')),
        'STEP_PASS preflight\nSTEP_OUTPUT_COMPLETE step=preflight result=0\n')
    _lf((tmp_path / '.git' / (TASK + '-step-verify.out')), body)
    assert halt_code(br._step_output_lines, b, st, {'done': st, 'halted': None}) == 'REPLY_STEP_OUTPUT_INVALID'


def test_g3_timing_rejects_prompt_binding_drift(tmp_path, monkeypatch, capsys):
    (tmp_path / '.git').mkdir()
    b = _g3_output_stub(tmp_path)
    control = {'task_id': TASK, 'done': ['preflight'], 'halted': None, 'prompt_sha256': br.sha256_bytes(b'other')}
    monkeypatch.setattr(br, '_timing_lines', lambda root, task: ('TIMING x', 'STATE y', control))
    monkeypatch.setattr(br, 'Batch', lambda root, task: b)
    monkeypatch.setattr(br, 'derive_steps', lambda spec: ['preflight'])
    monkeypatch.setattr(br, '_self_check_reply', lambda batch, reply: 'PASS')
    br.timing(str(tmp_path), TASK)
    out = capsys.readouterr().out
    assert 'EXECUTOR_REPLY_UNAVAILABLE REPLY_CONTROL_BINDING_DRIFT' in out and 'EXECUTOR_REPLY_BEGIN' not in out


# G3 F — keep the original S1 as authority; auto timing is terminal, not a new tool action.
def test_g3_f_auto_s1_timing_same_invocation(tmp_path, monkeypatch, capsys):
    (tmp_path / '.git').mkdir()
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts' / 'batch_runner.py').write_bytes(b'fixture runner\n')
    class Stub:
        def __init__(self, *_args):
            self.root = str(tmp_path)
            self.task_id = TASK
            self.prompt_bytes = b'prompt'
            self.spec = {'kind': 'promotion'}
        def step_preflight(self):
            raise br.Halt('TEST_HALT')
    monkeypatch.setattr(br, 'Batch', Stub)
    monkeypatch.setattr(br, 'derive_steps', lambda _: ['preflight'])
    monkeypatch.setattr(br, 'load_control', lambda _: {'task_id': TASK, 'done': [], 'halted': None,
        'prompt_sha256': br.sha256_bytes(b'prompt'), 'runner_sha256': 'fixed'})
    monkeypatch.setattr(br, 'accepted_runner_sha', lambda *args: 'fixed')
    monkeypatch.setattr(br.Path, 'cwd', lambda: tmp_path)
    monkeypatch.setattr(br, '__file__', str(tmp_path / 'scripts' / 'batch_runner.py'))
    monkeypatch.setattr(br, '_StepRecord', _SyntheticStepRecord)
    monkeypatch.setattr(br, 'save_control', lambda *args: None)
    calls=[]
    def reporter(root, task):
        calls.append((root,task))
        print('TIMING synthetic')
        return 0
    monkeypatch.setattr(br, 'timing', reporter)
    assert br.main(['--task-id', TASK, 'preflight']) == 1
    out=capsys.readouterr().out
    assert 'S1 TEST_HALT | step preflight' in out
    assert out.endswith('TIMING synthetic\n')
    assert calls == [(str(tmp_path),TASK)]


def test_g3_f_budget_warn_sanitized_and_forwarded_without_relaxing_summary(tmp_path, monkeypatch, capsys):
    import bounded_process
    folder=tmp_path/'warn';folder.mkdir()
    b=_bounded_batch(folder, monkeypatch)
    raw=b'GATE_BUDGET_WARN stage=PRECOMMIT gate=4 elapsed=3155.690 limit=3600 pct=87.7\nGATE_RUNNER PASS stage=PRECOMMIT\n'
    def fake(*args, **kw):
        Path(kw['capture_path']).write_bytes(raw)
        return bounded_process.BoundedResult(0, False, None, raw, b'', 'NOT_NEEDED')
    monkeypatch.setattr(br, 'run_bounded', fake)
    b.bounded('PRECOMMIT', ['-c', 'pass'], 8000, gate_timeout=True)
    out=capsys.readouterr().out
    assert out.splitlines()==[
        'GATE_BUDGET_WARN stage=PRECOMMIT gate=4 elapsed=3155.690 limit=3600 pct=87.7',
        'BOUNDED_EXIT PRECOMMIT code=0 | GATE_RUNNER PASS stage=PRECOMMIT',
    ]
    assert br.bounded_summary(['arbitrary secret text'])=='(summary withheld)'
    assert br.checked_budget_warnings('GATE_BUDGET_WARN stage=PRECOMMIT gate=4 elapsed=3155.690 limit=3600 pct=87.7', 'PRECOMMIT')
    assert halt_code(br.checked_budget_warnings, 'GATE_BUDGET_WARN stage=PRECOMMIT gate=4 elapsed=3155.690 limit=3601 pct=87.7', 'PRECOMMIT')=='GATE_BUDGET_WARN_INVALID'
    assert halt_code(br.checked_budget_warnings, 'GATE_BUDGET_WARN stage=PRECOMMIT gate=4 elapsed=3155.690 limit=3600 pct=87.7\nGATE_BUDGET_WARN stage=PRECOMMIT gate=4 elapsed=3155.690 limit=3600 pct=87.7', 'PRECOMMIT')=='GATE_BUDGET_WARN_INVALID'


def test_g3_f_handoff_carries_only_verified_task_local_budget_warnings(tmp_path, monkeypatch, capsys):
    # Exercise the real bundle helper's warning path without publishing a commit.
    from types import MethodType
    (tmp_path / '.git').mkdir()
    base = 'a'*40
    cand = 'b'*40
    branch = 'batch/local-test'
    b = br.Batch.__new__(br.Batch)
    b.root, b.task_id = str(tmp_path), TASK
    b.spec = {'kind': 'production', 'base_oid':base, 'branch':branch}
    b.artifact = MethodType(lambda self, name:'.git/'+self.task_id+'-'+name,b)
    def write_new(suffix, value):
        path=tmp_path/b.artifact(suffix)
        with path.open('x',encoding='utf-8',newline='') as f: f.write(value)
        return b.artifact(suffix)
    b.write_new_artifact=write_new
    b.remote_sha=lambda ref:base if ref=='refs/heads/main' else cand
    def fake_git(root,*args):
        if args[:2]==('rev-parse','HEAD'):return cand
        if args[:2]==('rev-parse','HEAD~1'):return base
        if args[:2]==('rev-parse','--is-shallow-repository'):return 'false'
        if args[:2]==('branch','--show-current'):return branch
        raise AssertionError(args)
    monkeypatch.setattr(br,'git',fake_git)
    monkeypatch.setattr(br,'status_lines',lambda root:[])
    monkeypatch.setattr(br,'create_bundle',lambda *a,**k: 'C:\\Downloads\\HH.AI_v2-20261110-110000-aaaaaaa-bbbbbbb.bundle')
    warn='GATE_BUDGET_WARN stage=PRECOMMIT gate=4 elapsed=3155.690 limit=3600 pct=87.7'
    for step in ('precommit','stage','postcommit'):
        body=('STEP_PASS '+step+'\n'+ (warn+'\n' if step=='precommit' else '')+
              'STEP_OUTPUT_COMPLETE step='+step+' result=0\n')
        _lf(tmp_path/b.artifact('step-'+step+'.out'),body)
    assert br.Batch.step_bundle(b)=='READY'
    out=capsys.readouterr().out
    card=json.loads(next(x.removeprefix('HANDOFF_CARD_JSON=') for x in out.splitlines()
                         if x.startswith('HANDOFF_CARD_JSON=')))
    assert card['gate_budget_warnings']==[warn]
    assert 'HANDOFF_CARD_SHA256=' in out


# G3 F (E27 second-opinion additions): each WARN guard and the pre-step S1 path
# has its own killing case; one guard cannot silently cover for another.
@pytest.mark.parametrize('line', [
    'GATE_BUDGET_WARN stage=PRECOMMIT gate=4 elapsed=2400.000 limit=3600 pct=66.7',
    'GATE_BUDGET_WARN stage=PRECOMMIT gate=4 elapsed=3155.690 limit=3600 pct=90.0',
    'GATE_BUDGET_WARN stage=STAGED gate=1 elapsed=250.000 limit=300 pct=83.3',
    'GATE_BUDGET_WARN stage=PRECOMMIT gate=4 elapsed=2520.700 limit=3601 pct=70.0',
], ids=['below_threshold', 'pct_inconsistent', 'other_stage', 'self_consistent_wrong_limit'])
def test_g3_f_checked_budget_warnings_each_guard_is_independent(line):
    assert halt_code(br.checked_budget_warnings, line, 'PRECOMMIT') == 'GATE_BUDGET_WARN_INVALID'


def test_g3_f_prestep_halt_also_reports_timing_in_same_invocation(tmp_path, monkeypatch, capsys):
    (tmp_path / 'scripts').mkdir()
    monkeypatch.setattr(br, '__file__', str(tmp_path / 'scripts' / 'batch_runner.py'))
    monkeypatch.setattr(br.Path, 'cwd', lambda: tmp_path / 'not-the-repo')
    calls = []
    def reporter(root, task):
        calls.append((root, task))
        print('TIMING synthetic')
        return 0
    monkeypatch.setattr(br, 'timing', reporter)
    assert br.main(['--task-id', TASK, 'preflight']) == 1
    out = capsys.readouterr().out
    assert out.startswith('S1 WORKING_DIRECTORY_MISMATCH | step preflight\n')
    assert out.endswith('TIMING synthetic\n')
    assert calls == [(str(tmp_path), TASK)]
