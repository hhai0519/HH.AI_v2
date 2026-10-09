# -*- coding: utf-8 -*-
"""
scripts/tests/test_prompt_builder.py

Controls for scripts/prompt_builder.py (B-115): deterministic build accepted by the runner's own spec
parser and op algorithm, fail-closed definition errors, start-up text, and the check wrapper.
"""

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import batch_runner as br  # noqa: E402
import prompt_builder as pb  # noqa: E402

TASK = "UNIT-BUILD-261009"


def _w(path, text):
    """Write UTF-8 text with LF exactly (Path.write_text would translate newlines to CRLF on Windows)."""
    Path(path).write_bytes(text.encode("utf-8"))


WINDOWS_PRIVILEGE_NOT_HELD = 1314


def _symlink_or_skip(link, target, **kw):
    """Skip only for the documented Windows capability gap (no symlink privilege); any other error fails."""
    try:
        link.symlink_to(target, **kw)
    except NotImplementedError:
        pytest.skip("symbolic links are not supported on this platform")
    except OSError as exc:
        if getattr(exc, "winerror", None) == WINDOWS_PRIVILEGE_NOT_HELD:
            pytest.skip("symbolic links need a privilege this Windows account does not hold")
        raise


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=repo,
                          check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "scripts" / "tool.py").write_bytes(b"def a():\n    return 1\n\n\ndef b():\n    return 2\n")
    (root / "docs" / "BOARD.md").write_bytes("# Board\n**NEXT_SLICE**：old\n| X-1 | row |\n| X-2 | row |\n".encode("utf-8"))
    _git(str(root), "init", "-q")
    _git(str(root), "add", ".")
    _git(str(root), "commit", "-q", "-m", "base")
    return str(root), _git(str(root), "rev-parse", "HEAD").stdout.decode().strip()


def _definition(tmp_path, base, **over):
    d = tmp_path / "def"
    d.mkdir(exist_ok=True)
    _w(d / "tool.py", "def a():\n    return 10\n\n\ndef b():\n    return 2\n")
    _w(d / "new.py", "print('new')\n")
    _w(d / "head.txt", "{TASK_ID} on {BASE7} branch {BRANCH}\n二、動手前必讀\n1. x\n")
    _w(d / "tail.txt", "scope {ALLOWED}\nrecord {SO}\n")
    _w(d / "so.txt", "second opinion record\n")
    _w(d / "e24.json", json.dumps({"schema_version": 1, "base_oid": base, "mode": "REQUIRED", "queries": [],
                                   "results": [{"query_id": "q1", "matched_paths": ["scripts/tool.py", "docs/OTHER.md", "docs/archive/old.md"]}]}))
    defn = {
        "schema_version": 1, "task_id": TASK, "kind": "production", "base_oid": base,
        "branch": "batch/unit-build-261009", "commit_message": "Unit: build", "e24": True, "focused": None,
        "code_files": {"scripts/tool.py": "tool.py"},
        "new_files": {"scripts/new_tool.py": {"file": "new.py", "block": "NEW_TOOL_PY"}},
        "text_ops": [
            {"path": "docs/BOARD.md", "type": "replace_line", "prefix": "**NEXT_SLICE**：", "new": "**NEXT_SLICE**：{TASK_ID}"},
            {"path": "docs/BOARD.md", "type": "insert_after_line", "prefix": "| X-2 |", "text": "| X-3 | {BASE7} |"},
            {"path": "docs/BOARD.md", "type": "replace", "old": "# Board\n", "new": "# Board (v2)\n"},
        ],
        "e24_evidence": "e24.json", "verify_only": ["docs/OTHER.md"], "historical": ["docs/archive/"],
        "prose_head": "head.txt", "prose_tail": "tail.txt", "substitutions": {"{SO}": "so.txt"},
    }
    defn.update(over)
    path = d / "def.json"
    _w(path, json.dumps(defn, ensure_ascii=False))
    return str(path)


def _code(fn, *args):
    with pytest.raises(pb.BuildError) as exc:
        fn(*args)
    return str(exc.value)


# --- build -------------------------------------------------------------------------------------

def test_build_is_accepted_by_runner_and_reproduces_authored_files(tmp_path, repo):
    root, base = repo
    text, authors, authored = pb.build(root, _definition(tmp_path, base))
    lines = br.prompt_lines(text.encode("utf-8"))
    spec = br.load_spec(lines, TASK)                       # the runner's own validator accepts it
    assert spec["branch"] == "batch/unit-build-261009" and spec["e24"] is True
    built = br.build_authors(root, spec, lines)            # the runner's own reconstruction
    assert built == authored
    assert {p: sha(t) for p, t in built.items()} == authors
    assert authored["docs/BOARD.md"] == "# Board (v2)\n**NEXT_SLICE**：" + TASK + "\n| X-1 | row |\n| X-2 | row |\n| X-3 | " + base[:7] + " |\n"
    assert TASK + " on " + base[:7] + " branch batch/unit-build-261009" in text
    allowed = ";".join(sorted(["docs/BOARD.md", "scripts/new_tool.py", "scripts/tool.py"] + list(br.GENERATED)))
    assert "scope " + allowed + "\n" in text and "record second opinion record\n" in text
    ev = json.loads(br.extract_block(lines, "E24_EVIDENCE_JSON"))
    assert ev["results"][0]["dispositions"] == {"scripts/tool.py": "UPDATE", "docs/OTHER.md": "VERIFY_ONLY",
                                                "docs/archive/old.md": "HISTORICAL_NO_CHANGE"}
    assert "\r" not in text


def test_build_is_deterministic(tmp_path, repo):
    root, base = repo
    defn = _definition(tmp_path, base)
    assert pb.build(root, defn)[0] == pb.build(root, defn)[0]


def test_runner_update_flag_is_emitted_where_the_runner_expects_it(tmp_path, repo):
    root, base = repo
    d = _definition(tmp_path, base, runner_update=True)
    assert _code(pb.build, root, d) == "RUNNER_SPEC_REJECTED_SPEC_RUNNER_UPDATE_UNDECLARED"
    plain = json.loads(br.extract_block(br.prompt_lines(pb.build(root, _definition(tmp_path, base))[0].encode()), "BATCH_SPEC_JSON"))
    assert "runner_update" not in plain


@pytest.mark.parametrize("over,code", [
    ({"commit_message": "two\nlines"}, "RUNNER_SPEC_REJECTED_SPEC_MESSAGE_INVALID"),
    ({"text_ops": [{"path": "docs/BOARD.md", "type": "replace_line", "prefix": "| X-", "new": "x"}]}, "TEXT_OP_LINE_NOT_UNIQUE"),
    ({"text_ops": [{"path": "docs/BOARD.md", "type": "replace", "old": "row", "new": "x"}]}, "TEXT_OP_ANCHOR_NOT_UNIQUE"),
    ({"text_ops": [{"path": "docs/BOARD.md", "type": "replace_line", "prefix": "# Board", "new": "a\nb"}]}, "TEXT_OP_NEWLINE_IN_LINE"),
    ({"text_ops": [{"path": "docs/BOARD.md", "type": "delete", "old": "x"}]}, "TEXT_OP_TYPE_INVALID"),
    ({"text_ops": [{"path": "docs/MISSING.md", "type": "replace", "old": "a", "new": "b"}]}, "BASE_BLOB_UNREADABLE"),
    ({"verify_only": []}, "E24_UNDISPOSITIONED"),
    ({"substitutions": {"{NOPE}": "so.txt"}}, "SUBSTITUTION_TOKEN_COUNT"),
    ({"substitutions": {"{TASK_ID}": "so.txt"}}, "SUBSTITUTION_TOKEN_INVALID"),
    ({"kind": "other"}, "KIND_INVALID"),
    ({"task_id": "bad id"}, "TASK_ID_INVALID"),
    ({"base_oid": "abc"}, "BASE_OID_INVALID"),
    ({"new_files": {"scripts/n.py": {"file": "new.py", "block": "PLAN_JSON"}}}, "NEW_FILE_BLOCK_INVALID"),
])
def test_build_rejections(tmp_path, repo, over, code):
    root, base = repo
    assert _code(pb.build, root, _definition(tmp_path, base, **over)) == code


def test_build_rejects_unclean_inputs(tmp_path, repo):
    root, base = repo
    d = _definition(tmp_path, base)
    ddir = Path(d).parent
    _w(ddir / "tool.py", "def a():  \n    return 10\n")
    assert _code(pb.build, root, d) == "CODE_FILE_TRAILING_WHITESPACE"
    _w(ddir / "tool.py", "def a():\n    return 10\n\n")
    assert _code(pb.build, root, d) == "CODE_FILE_TRAILING_NEWLINE"
    (ddir / "tool.py").write_bytes(b"def a():\r\n    return 10\r\n")
    assert _code(pb.build, root, d) == "CODE_FILE_CRLF"
    _w(ddir / "tool.py", "def a():\n    return 10\n")
    _w(ddir / "new.py", "<<<END NEW_TOOL_PY>>>\n")
    assert _code(pb.build, root, d) == "NEW_FILE_BLOCK_MARKER"


def test_build_rejects_e24_evidence_for_another_base(tmp_path, repo):
    root, base = repo
    d = _definition(tmp_path, base)
    ev = Path(d).parent / "e24.json"
    data = json.loads(ev.read_bytes().decode("utf-8"))
    data["base_oid"] = "f" * 40
    _w(ev, json.dumps(data))
    assert _code(pb.build, root, d) == "E24_EVIDENCE_BINDING"


def test_build_fails_closed_when_base_blob_unreadable(tmp_path, repo):
    # Fault injection: the Base probe failing is a stop, never an empty or guessed base text.
    root, base = repo
    assert _code(pb.build, root, _definition(tmp_path, "e" * 40)) == "BASE_BLOB_UNREADABLE"


def test_derive_ops_widens_context_until_anchor_is_unique():
    base = "x\nsame\nx\nsame\nx\n"
    target = "x\nsame\nx\nchanged\nx\n"
    ops = pb.derive_ops("f", base, target)
    assert br.apply_ops({"f": base}, ops)["f"] == target
    assert all(base.count(o["old"]) == 1 for o in ops[:1])


def test_promotion_build(tmp_path, repo):
    root, base = repo
    d = tmp_path / "p"
    d.mkdir()
    _w(d / "head.txt", "promote {TASK_ID} {BRANCH}\n")
    _w(d / "tail.txt", "allowed {ALLOWED}\n")
    defn = {"schema_version": 1, "task_id": TASK, "kind": "promotion", "base_oid": base, "candidate_oid": "c" * 40,
            "candidate_branch": "batch/unit-build-261009", "prose_head": "head.txt", "prose_tail": "tail.txt"}
    _w(d / "def.json", json.dumps(defn))
    text, authors, authored = pb.build(root, str(d / "def.json"))
    spec = br.load_spec(br.prompt_lines(text.encode()), TASK)
    assert spec["kind"] == "promotion" and authors == {} and "allowed NONE" in text
    assert "promote " + TASK + " batch/unit-build-261009" in text


# --- outputs, start-up text and check -----------------------------------------------------------

def test_cli_build_writes_prompt_authors_and_tree(tmp_path, repo, capsys):
    root, base = repo
    out = tmp_path / "out"
    assert pb.main(["build", "--repo", root, "--definition", _definition(tmp_path, base), "--out-dir", str(out)]) == 0
    prompt = out / (TASK + "-prompt.txt")
    data = prompt.read_bytes()
    assert "PROMPT_BUILDER BUILT" in capsys.readouterr().out
    authors = json.loads((out / "authors.json").read_bytes().decode("utf-8"))
    for path, digest in authors.items():
        assert sha((out / "authored" / path).read_bytes().decode("utf-8")) == digest
    assert hashlib.sha256(data).hexdigest() == hashlib.sha256(pb.build(root, _definition(tmp_path, base))[0].encode()).hexdigest()


def test_cli_reports_fixed_failure_codes(tmp_path, repo, capsys):
    root, base = repo
    d = _definition(tmp_path, base, commit_message=None)
    assert pb.main(["build", "--repo", root, "--definition", d, "--out-dir", str(tmp_path / "o")]) == 1
    assert capsys.readouterr().out.strip() == "PROMPT_BUILDER FAIL RUNNER_SPEC_REJECTED_SPEC_MESSAGE_INVALID"
    broken = Path(d).parent / "broken.json"
    _w(broken, json.dumps({"schema_version": 1, "task_id": TASK, "kind": "production", "base_oid": base}))
    assert pb.main(["build", "--repo", root, "--definition", str(broken), "--out-dir", str(tmp_path / "o")]) == 1
    assert capsys.readouterr().out.strip() == "PROMPT_BUILDER FAIL DEFINITION_INVALID"


def test_startup_lines_bind_exact_bytes_and_paths(tmp_path, repo):
    root, base = repo
    out = tmp_path / "out"
    pb.main(["build", "--repo", root, "--definition", _definition(tmp_path, base), "--out-dir", str(out)])
    prompt = out / (TASK + "-prompt.txt")
    digest = hashlib.sha256(prompt.read_bytes()).hexdigest()
    lines = pb.startup_lines(str(prompt), "C:\\Users\\U\\Downloads\\", "C:\\Users\\U\\Desktop\\HH.AI_v2")
    assert lines[0] == "SHA256_UPPER=" + digest.upper()
    src = "C:\\Users\\U\\Downloads\\" + TASK + "-prompt.txt"
    assert lines[3] == "python scripts/prompt_intake.py --task-id " + TASK + " --source " + src + " --sha256 " + digest
    assert "C:\\Users\\U\\Desktop\\HH.AI_v2" in lines[2]
    assert lines[-1] == "Get-FileHash -Algorithm SHA256 -LiteralPath '" + src + "'"


@pytest.mark.parametrize("download,workspace", [
    ("C:\\Users\\U V\\Downloads", "C:\\W"),          # space
    ("C:\\Users\\$(calc)\\Downloads", "C:\\W"),      # subexpression
    ("C:\\Users\\U`n\\Downloads", "C:\\W"),          # backtick
    ("C:\\Users\\U'x\\Downloads", "C:\\W"),          # single quote
    ('C:\\Users\\U"x\\Downloads', "C:\\W"),          # double quote
    ("C:\\Users\\U\nx", "C:\\W"),                    # control character
    ("Users\\U\\Downloads", "C:\\W"),                 # not drive-absolute
    ("\\\\server\\share", "C:\\W"),                   # UNC
    ("C:\\Users\\..\\Downloads", "C:\\W"),            # parent segment
    ("C:/Users/U/Downloads", "C:\\W"),                  # forward slashes
    ("C:\\Users\\U\\Downloads", "C:\\W;rm"),          # workspace checked too
])
def test_startup_rejects_paths_that_are_not_one_literal_token(tmp_path, repo, download, workspace):
    root, base = repo
    out = tmp_path / "out"
    pb.main(["build", "--repo", root, "--definition", _definition(tmp_path, base), "--out-dir", str(out)])
    code = _code(pb.startup_lines, str(out / (TASK + "-prompt.txt")), download, workspace)
    assert code in ("DOWNLOAD_DIR_INVALID", "WORKSPACE_INVALID")


def test_ps_literal_never_expands():
    assert pb.ps_literal("C:\\a'b$(x)`c") == "'C:\\a''b$(x)`c'"


def test_startup_rejects_prompt_whose_name_and_task_differ(tmp_path, repo):
    root, base = repo
    out = tmp_path / "out"
    pb.main(["build", "--repo", root, "--definition", _definition(tmp_path, base), "--out-dir", str(out)])
    renamed = out / "OTHER-TASK-261009-prompt.txt"
    renamed.write_bytes((out / (TASK + "-prompt.txt")).read_bytes())
    assert _code(pb.startup_lines, str(renamed), "D", "W") == "PROMPT_TASK_MISMATCH"
    bad = out / "notaprompt.txt"
    bad.write_bytes(b"x")
    assert _code(pb.startup_lines, str(bad), "D", "W") == "PROMPT_NAME_INVALID"


class _Result:
    def __init__(self, code):
        self.returncode = code


def _built_prompt(tmp_path, repo):
    root, base = repo
    out = tmp_path / "out"
    pb.main(["build", "--repo", root, "--definition", _definition(tmp_path, base), "--out-dir", str(out)])
    return root, out / (TASK + "-prompt.txt")


def test_check_runs_both_tools_on_exact_bytes_and_removes_its_copy(tmp_path, repo):
    root, prompt = _built_prompt(tmp_path, repo)
    seen = []

    def fake(args, cwd, **kw):
        target = Path(cwd) / ".git" / (TASK + "-prompt.txt")
        seen.append((args[1], target.read_bytes() == prompt.read_bytes()))
        return _Result(0)

    assert pb.check(root, str(prompt), runner=fake) == TASK
    assert seen == [("scripts/validate_prompt_manifest.py", True), ("scripts/governance_preflight.py", True)]
    assert not (Path(root) / ".git" / (TASK + "-prompt.txt")).exists()


@pytest.mark.parametrize("codes,expected", [([1, 0], "CHECK_MANIFEST_FAILED"), ([0, 2], "CHECK_PREFLIGHT_FAILED")])
def test_check_fails_on_either_tool(tmp_path, repo, codes, expected):
    root, prompt = _built_prompt(tmp_path, repo)
    results = iter(codes)
    assert _code(pb.check, root, str(prompt), lambda *a, **k: _Result(next(results))) == expected
    assert not (Path(root) / ".git" / (TASK + "-prompt.txt")).exists()


def test_check_fails_closed_on_launch_error_timeout_and_foreign_copy(tmp_path, repo):
    # Fault injection: a tool that cannot run, or a different file already in place, is a failure.
    root, prompt = _built_prompt(tmp_path, repo)

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("x", 1)

    assert _code(pb.check, root, str(prompt), boom) == "CHECK_COMMAND_FAILED"
    target = Path(root) / ".git" / (TASK + "-prompt.txt")
    target.write_bytes(b"other bytes")
    assert _code(pb.check, root, str(prompt), lambda *a, **k: _Result(0)) == "CHECK_TARGET_DIFFERS"
    assert target.read_bytes() == b"other bytes", "a file the tool did not create is never removed or overwritten"


def test_build_detects_ops_that_do_not_reproduce_the_final_text(tmp_path, repo, monkeypatch):
    # Fault injection: if derived ops ever disagree with the declared final text, the build stops.
    root, base = repo
    real = pb.derive_ops
    monkeypatch.setattr(pb, "derive_ops", lambda path, b, t: real(path, b, t.replace("10", "11")))
    assert _code(pb.build, root, _definition(tmp_path, base)) == "REPLAY_MISMATCH"


def test_build_rejects_placeholder_left_by_a_substitution(tmp_path, repo):
    root, base = repo
    d = _definition(tmp_path, base)
    _w(Path(d).parent / "so.txt", "see {TASK_ID}\n")
    assert _code(pb.build, root, d) == "PLACEHOLDER_LEFT"


def test_new_file_text_is_carried_verbatim_even_with_placeholder_text(tmp_path, repo):
    # The builder must be able to deliver itself: a new file may contain "{TASK_ID}" literally.
    root, base = repo
    d = _definition(tmp_path, base)
    _w(Path(d).parent / "new.py", "TOKENS = ('{TASK_ID}', '{ALLOWED}')\n")
    text, authors, authored = pb.build(root, d)
    assert authored["scripts/new_tool.py"] == "TOKENS = ('{TASK_ID}', '{ALLOWED}')\n"
    lines = br.prompt_lines(text.encode("utf-8"))
    assert br.build_authors(root, br.load_spec(lines, TASK), lines)["scripts/new_tool.py"] == authored["scripts/new_tool.py"]


# --- second-opinion fixes (R1–R4) ------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["C:/outside/payload.py", "/abs/x.py", "a/../b.py", "a\\b.py", ".git/hooks/x",
                                 "a//b.py", "./a.py", "docs/x:y.md", "", "docs/fingerprints/exec-latest.json",
                                 "docs/a./b.md", "docs/NUL.md", "docs/com1", "a/../../b.py", ".GIT/config"])
@pytest.mark.parametrize("where", ["new_files", "code_files", "text_ops"])
def test_build_rejects_unsafe_paths_before_any_output(tmp_path, repo, bad, where):
    root, base = repo
    if where == "new_files":
        over = {"new_files": {bad: {"file": "new.py", "block": "NEW_TOOL_PY"}}}
    elif where == "code_files":
        over = {"code_files": {bad: "tool.py"}}
    else:
        over = {"text_ops": [{"path": bad, "type": "replace", "old": "x", "new": "y"}]}
    out = tmp_path / "out"
    assert pb.main(["build", "--repo", root, "--definition", _definition(tmp_path, base, **over), "--out-dir", str(out)]) == 1
    assert not out.exists(), "nothing is written when a path is rejected"
    assert _code(pb.build, root, _definition(tmp_path, base, **over)) == "PATH_INVALID"


def test_write_outputs_rejects_unsafe_paths(tmp_path):
    out = tmp_path / "out"
    for bad in ["C:/outside/x.py", "../x.py", "/abs/x.py"]:
        assert _code(pb.write_outputs, str(out), TASK, "p\n", {}, {bad: "x\n"}) == "PATH_INVALID"
    assert not (tmp_path / "x.py").exists()


def test_write_outputs_refuses_destination_outside_its_tree(tmp_path):
    out = tmp_path / "out"
    (out / "authored").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    _symlink_or_skip(out / "authored" / "link", outside, target_is_directory=True)
    assert _code(pb.write_outputs, str(out), TASK, "p\n", {"link/x.py": "h"}, {"link/x.py": "x\n"}) == "OUTPUT_PATH_ESCAPE"
    assert not (outside / "x.py").exists()


@pytest.mark.parametrize("over", [
    {"new_files": {"scripts/tool.py": {"file": "new.py", "block": "NEW_TOOL_PY"}}},
    {"text_ops": [{"path": "scripts/tool.py", "type": "replace", "old": "return 2", "new": "return 3"}]},
    {"text_ops": [{"path": "scripts/new_tool.py", "type": "replace", "old": "new", "new": "old"}]},
])
def test_build_rejects_one_path_in_two_source_categories(tmp_path, repo, over):
    root, base = repo
    assert _code(pb.build, root, _definition(tmp_path, base, **over)) == "SOURCE_CATEGORY_OVERLAP"


def test_build_reconstructs_with_runner_and_fails_closed(tmp_path, repo, monkeypatch):
    # Fault injection on the reference reconstruction: a different rebuild or a runner halt stops the build.
    root, base = repo
    real = br.build_authors
    monkeypatch.setattr(br, "build_authors", lambda *a: dict(real(*a), **{"scripts/tool.py": "changed\n"}))
    assert _code(pb.build, root, _definition(tmp_path, base)) == "RUNNER_REBUILD_MISMATCH"

    def halt(*a):
        raise br.Halt("ANCHOR_NOT_UNIQUE")
    monkeypatch.setattr(br, "build_authors", halt)
    assert _code(pb.build, root, _definition(tmp_path, base)) == "RUNNER_REBUILD_FAILED_ANCHOR_NOT_UNIQUE"


def test_check_never_deletes_a_copy_replaced_while_running(tmp_path, repo):
    # Race injection: after check created its copy, another writer replaces it; the replacement survives.
    root, prompt = _built_prompt(tmp_path, repo)
    target = Path(root) / ".git" / (TASK + "-prompt.txt")

    replaced = []

    def replace_then_pass(args, cwd, **kw):
        if "governance" in args[1]:
            try:
                target.unlink()
            except PermissionError:
                return _Result(0)                            # Windows: an open file cannot be deleted or replaced
            target.write_bytes(prompt.read_bytes())          # same bytes, different file
            replaced.append(True)
        return _Result(0)

    if os.name == "nt":
        assert pb.check(root, str(prompt), runner=replace_then_pass) == TASK
        assert not replaced and not target.exists(), "replacement impossible while open; own copy removed"
    else:
        assert _code(pb.check, root, str(prompt), replace_then_pass) == "CHECK_COPY_REPLACED"
        assert replaced and target.read_bytes() == prompt.read_bytes()


def test_check_uses_an_identical_existing_copy_without_removing_it_and_refuses_symlinks(tmp_path, repo):
    root, prompt = _built_prompt(tmp_path, repo)
    target = Path(root) / ".git" / (TASK + "-prompt.txt")
    target.write_bytes(prompt.read_bytes())
    assert pb.check(root, str(prompt), runner=lambda *a, **k: _Result(0)) == TASK
    assert target.exists(), "a copy the tool did not create is left in place"
    target.unlink()
    _symlink_or_skip(target, prompt)
    assert _code(pb.check, root, str(prompt), lambda *a, **k: _Result(0)) == "CHECK_TARGET_DIFFERS"
    assert target.is_symlink()


def test_check_repo_path_accepts_ordinary_and_dot_directories():
    for ok in ["scripts/tool.py", ".claude/README.md", ".agents/rules/x.md", ".gitignore", "docs/a.b-c_d.md"]:
        assert pb.check_repo_path(ok) == ok


def test_adopt_start_is_emitted_for_the_runner_and_validated(tmp_path, repo):
    # Resume from a stopped batch: the runner's own load_spec accepts the adopt start and its hashes.
    root, base = repo
    clean = pb.build(root, _definition(tmp_path, base))[1]
    start = {"mode": "adopt", "start_branch": "batch/unit-build-r0-261009", "adopt_hashes": dict(clean)}
    text = pb.build(root, _definition(tmp_path, base, start=start))[0]
    spec = br.load_spec(br.prompt_lines(text.encode("utf-8")), TASK)
    assert spec["start"] == {"mode": "adopt", "start_branch": "batch/unit-build-r0-261009", "adopt_hashes": dict(sorted(clean.items()))}
    plain = json.loads(br.extract_block(br.prompt_lines(pb.build(root, _definition(tmp_path, base))[0].encode()), "BATCH_SPEC_JSON"))
    assert plain["start"] == {"mode": "clean"}


@pytest.mark.parametrize("start,code", [
    ({"mode": "clean"}, "START_INVALID"),
    ({"mode": "adopt", "start_branch": "batch/x", "adopt_hashes": {}}, "START_INVALID"),
    ({"mode": "adopt", "start_branch": "batch/x", "adopt_hashes": {"docs/NOT_AUTHORED.md": "0" * 64}}, "START_INVALID"),
    ({"mode": "adopt", "start_branch": "batch/x", "adopt_hashes": {"docs/BOARD.md": "0" * 64}, "extra": 1}, "START_INVALID"),
    ({"mode": "adopt", "start_branch": "batch/unit-build-261009", "adopt_hashes": {"docs/BOARD.md": "0" * 64}},
     "RUNNER_SPEC_REJECTED_SPEC_START_INVALID"),          # start branch equal to the new branch
    ({"mode": "adopt", "start_branch": "batch/x", "adopt_hashes": {"docs/BOARD.md": "zz"}},
     "RUNNER_SPEC_REJECTED_SPEC_START_INVALID"),          # not a SHA-256
])
def test_adopt_start_rejections(tmp_path, repo, start, code):
    root, base = repo
    assert _code(pb.build, root, _definition(tmp_path, base, start=start)) == code


def test_check_never_deletes_a_copy_altered_while_running(tmp_path, repo):
    # Same file, different bytes: ownership is not proven, so the file is kept and the check fails.
    root, prompt = _built_prompt(tmp_path, repo)
    target = Path(root) / ".git" / (TASK + "-prompt.txt")

    def alter_then_pass(args, cwd, **kw):
        if "governance" in args[1]:
            with open(target, "r+b") as fh:
                fh.write(b"X")
        return _Result(0)

    assert _code(pb.check, root, str(prompt), alter_then_pass) == "CHECK_COPY_REPLACED"
    assert target.read_bytes()[:1] == b"X"


def test_check_never_deletes_a_name_turned_into_a_symlink(tmp_path, repo):
    # The name is replaced by a symlink to a hard link of the very same file: the name is no longer ours.
    if os.name == "nt":
        pytest.skip("an open file cannot be unlinked on Windows")
    _symlink_or_skip(tmp_path / "probe-link", tmp_path)       # skip up front where symlinks are unavailable
    root, prompt = _built_prompt(tmp_path, repo)
    target = Path(root) / ".git" / (TASK + "-prompt.txt")
    other = Path(root) / ".git" / "other-link.txt"
    swapped = []

    def swap_then_pass(args, cwd, **kw):
        if "governance" in args[1]:
            os.link(target, other)
            target.unlink()
            target.symlink_to(other)
            swapped.append(True)
        return _Result(0)

    assert _code(pb.check, root, str(prompt), swap_then_pass) == "CHECK_COPY_REPLACED"
    assert swapped and target.is_symlink() and other.read_bytes() == prompt.read_bytes()


def test_symlink_tests_really_run_off_windows(tmp_path):
    # Guard: on Linux CI the symlink-dependent tests must execute, never silently skip.
    if os.name == "nt":
        pytest.skip("Windows may lack the symlink privilege")
    (tmp_path / "t").write_bytes(b"x")
    _symlink_or_skip(tmp_path / "l", tmp_path / "t")
    assert (tmp_path / "l").is_symlink()
    with pytest.raises(FileExistsError):
        _symlink_or_skip(tmp_path / "l", tmp_path / "t")      # unexpected errors fail, they are not skips


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs exist only on POSIX")
def test_check_cleanup_never_blocks_on_a_fifo_swapped_in(tmp_path, repo):
    # Native POSIX counterexample: the name is replaced by a FIFO with no writer; clean-up must not open-block.
    import signal
    root, prompt = _built_prompt(tmp_path, repo)
    target = Path(root) / ".git" / (TASK + "-prompt.txt")

    def fifo_then_pass(args, cwd, **kw):
        if "governance" in args[1]:
            target.unlink()
            os.mkfifo(target)
        return _Result(0)

    def too_slow(*a):
        raise _Hung()
    old = signal.signal(signal.SIGALRM, too_slow)
    signal.alarm(10)
    try:
        assert _code(pb.check, root, str(prompt), fifo_then_pass) == "CHECK_COPY_REPLACED"
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)
    assert stat.S_ISFIFO(os.lstat(target).st_mode), "the FIFO is left in place"


class _Hung(Exception):
    """Raised by an alarm; deliberately not an OSError so no code under test can swallow it."""


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs exist only on POSIX")
def test_still_owned_does_not_block_when_a_fifo_appears_after_the_lstat(tmp_path, monkeypatch):
    # Race injection: lstat still reports the regular file, the open then meets a FIFO without a writer.
    import signal
    regular = tmp_path / "regular"
    regular.write_bytes(b"abc")
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    real_lstat = os.lstat
    monkeypatch.setattr(os, "lstat", lambda p, *a, **k: real_lstat(regular) if str(p) == str(fifo) else real_lstat(p, *a, **k))
    st = real_lstat(regular)

    def hung(*a):
        raise _Hung()
    old = signal.signal(signal.SIGALRM, hung)
    signal.alarm(10)
    try:
        assert pb.still_owned(fifo, (st.st_dev, st.st_ino), b"abc") is False
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def test_still_owned_rejects_a_symlink_where_the_platform_cannot_refuse_to_follow(tmp_path, monkeypatch):
    # Windows-like platform (no O_NOFOLLOW): a symlink to a hard link of the owned file must still be rejected.
    owned_file = tmp_path / "owned"
    owned_file.write_bytes(b"abc")
    other = tmp_path / "hardlink"
    os.link(owned_file, other)
    link = tmp_path / "name"
    _symlink_or_skip(link, other)
    st = os.stat(owned_file)
    monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
    assert pb.still_owned(link, (st.st_dev, st.st_ino), b"abc") is False


def test_still_owned_reads_at_most_one_byte_past_the_expected_length(tmp_path, monkeypatch):
    path = tmp_path / "big"
    path.write_bytes(b"abc" + b"x" * 100000)
    st = os.stat(path)
    seen = []
    real_read = os.read
    monkeypatch.setattr(os, "read", lambda fd, n: seen.append(n) or real_read(fd, n))
    assert pb.still_owned(path, (st.st_dev, st.st_ino), b"abc") is False
    assert sum(seen) <= 4, "reads are bounded by len(data) + 1"


def test_still_owned_basic_cases(tmp_path):
    path = tmp_path / "f"
    path.write_bytes(b"abc" + b"x" * 100000)
    st = os.stat(path)
    assert pb.still_owned(path, (st.st_dev, st.st_ino), b"abc") is False
    path.write_bytes(b"abc")
    st = os.stat(path)
    assert pb.still_owned(path, (st.st_dev, st.st_ino), b"abc") is True
    assert pb.still_owned(path, (st.st_dev, st.st_ino + 1), b"abc") is False
    assert pb.still_owned(tmp_path / "missing", (st.st_dev, st.st_ino), b"abc") is False
    assert pb.still_owned(tmp_path, (st.st_dev, st.st_ino), b"abc") is False          # a directory


def test_fixtures_never_rely_on_default_newline_translation():
    # Mechanical guard: exact-byte fixtures in this file are written with _w / write_bytes only.
    src = Path(__file__).read_bytes().decode("utf-8")
    banned = [".write" + "_text(", "open(" + "target, \"w\"", "mode=" + "\"w\""]
    assert not [b for b in banned if b in src]
    assert not re.search(r"open\([^)]*,\s*[\"'](w|a|x)t?[\"']", src)
