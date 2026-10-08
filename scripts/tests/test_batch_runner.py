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


# --- bounded execution -----------------------------------------------------------------

def test_bounded_run_returns_exit_code_and_writes_output_to_file(tmp_path):
    log = tmp_path / "log.txt"
    code = br.bounded_run([sys.executable, "-c", "import sys; print('done'); sys.exit(3)"], str(tmp_path), log, 60)
    assert code == 3
    assert "done" in log.read_text(encoding="utf-8")


def _alive(pid):
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", "PID eq " + str(pid), "/NH"], capture_output=True).stdout.decode("utf-8", "replace")
        return str(pid) in out
    stat = "/proc/" + str(pid) + "/stat"
    if os.path.exists("/proc"):
        try:
            with open(stat, encoding="utf-8") as f:
                return f.read().rsplit(")", 1)[1].split()[0] != "Z"
        except OSError:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_bounded_run_timeout_terminates_whole_tree(tmp_path):
    pid_file = tmp_path / "grandchild.pid"
    child = (
        "import subprocess, sys, time\n"
        "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "open(sys.argv[1], 'w').write(str(g.pid))\n"
        "time.sleep(120)\n"
    )
    log = tmp_path / "log.txt"
    started = time.monotonic()
    # The limit leaves room for two interpreter start-ups on slow Windows hosts before the tree is terminated.
    code = br.bounded_run([sys.executable, "-c", child, str(pid_file)], str(tmp_path), log, 10)
    assert code is None
    assert time.monotonic() - started < 90
    assert pid_file.exists(), "grandchild must have started before the timeout"
    grandchild = int(pid_file.read_text())
    deadline = time.monotonic() + 15
    while _alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not _alive(grandchild), "grandchild must be terminated with the tree"
