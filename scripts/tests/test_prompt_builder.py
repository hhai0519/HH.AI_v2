# -*- coding: utf-8 -*-
"""
scripts/tests/test_prompt_builder.py

Controls for scripts/prompt_builder.py (B-115): deterministic build accepted by the runner's own spec
parser and op algorithm, fail-closed definition errors, start-up text, the check wrapper, and the generated
must-read list with its MUST_READ_JSON block (G4 slice 2).
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


def _write_rules(root):
    """The runner's must-read files (kernel, production and path-bound rules) as small synthetic texts."""
    for rel in br.MUST_READ_KERNEL + br.MUST_READ_PRODUCTION + tuple(r for _, rules in br.MUST_READ_BY_PREFIX for r in rules):
        target = Path(root) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(("# " + rel + "\n").encode("utf-8"))


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "scripts" / "tool.py").write_bytes(b"def a():\n    return 1\n\n\ndef b():\n    return 2\n")
    (root / "docs" / "EXEC-LOG.md").write_bytes(b"| batch commit | date | result |\n|---|---|---|\n| BOOTSTRAP | 2026-09-01 | ok |\n")
    (root / "docs" / "BOARD.md").write_bytes("# Board\n**NEXT_SLICE**：old\n| X-1 | row |\n| X-2 | row |\n".encode("utf-8"))
    _write_rules(root)
    # Fixed C9 probe/guard identity files included in readonly must-read closure.
    for rel in ('scripts/readonly_probe.py', 'scripts/prompt_builder.py',
                'scripts/batch_runner.py', 'scripts/c9_base_guard.py',
                'scripts/c9_local_history_guard.py', 'scripts/c9_s1_capture_guard.py',
                'scripts/s1_evidence.py', 'scripts/s1_full_capture.py'):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(('# fixture ' + rel + '\n').encode('utf-8'))
    (root / "scripts" / "batch_runner.py").write_bytes(b"PRODUCTION_STEPS = ('preflight', 'setup', 'apply')\n")
    _git(str(root), "init", "-q")
    _git(str(root), "add", ".")
    _git(str(root), "commit", "-q", "-m", "base")
    return str(root), _git(str(root), "rev-parse", "HEAD").stdout.decode().strip()


def _definition(tmp_path, base, **over):
    d = tmp_path / "def"
    d.mkdir(exist_ok=True)
    _w(d / "tool.py", "def a():\n    return 10\n\n\ndef b():\n    return 2\n")
    _w(d / "new.py", "print('new')\n")
    _w(d / "head.txt", "{TASK_ID} on {BASE7} branch {BRANCH}\n二、動手前必讀\n{MUST_READ}\n")
    _w(d / "tail.txt", "scope {ALLOWED}\nrecord {SO}\n")
    _w(d / "so.txt", "second opinion record\n")
    _w(d / "e24.json", json.dumps({"schema_version": 1, "base_oid": base, "mode": "REQUIRED", "queries": [],
                                   "results": [{"query_id": "q1", "matched_paths": ["scripts/tool.py", "docs/OTHER.md", "docs/archive/old.md"]}]}))
    defn = {
        "schema_version": 1, "task_id": TASK, "kind": "production", "base_oid": base,
        "branch": "batch/unit-build-261009", "commit_message": "Unit: build", "one_liner": "單元測試用的一句話說明文字", "e24": True, "focused": None,
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

STATE_PATHS = ["docs/AUDIT-LOG.md", "docs/EXEC-LOG.md", "docs/TASKBOARD.md", "docs/refactor-backlog.md"]


@pytest.mark.parametrize("path", STATE_PATHS)
@pytest.mark.parametrize("where", ["code_files", "new_files"])
def test_state_files_take_only_declared_text_ops(tmp_path, repo, where, path):
    """B-115 C2（USER 2026-10-25 D-C2-1）：狀態檔只能以 text_ops（事前宣告的授權帳）修改。"""
    root, base = repo
    if where == "code_files":
        over = {"code_files": {"scripts/tool.py": "tool.py", path: "tool.py"}}
    else:
        over = {"new_files": {"scripts/new_tool.py": {"file": "new.py", "block": "NEW_TOOL_PY"},
                              path: {"file": "new.py", "block": "NEW_STATE_MD"}}}
    assert _code(pb.build, root, _definition(tmp_path, base, **over)) == "STATE_FILE_REQUIRES_TEXT_OPS"


def test_state_file_list_matches_the_precheck_status_files():
    import draft_precheck
    assert sorted(pb.STATE_FILES) == STATE_PATHS == sorted(draft_precheck.STATUS)


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
    _w(d / "head.txt", "promote {TASK_ID} {BRANCH}\n二、動手前必讀\n{MUST_READ}\n")
    _w(d / "tail.txt", "allowed {ALLOWED}\n")
    (Path(root) / "docs" / "BOARD.md").write_bytes(b"# Board\ncandidate\n")
    _git(root, "commit", "-q", "-am", "candidate")
    cand = _git(root, "rev-parse", "HEAD").stdout.decode().strip()
    ptask = "PROMOTE-UNIT-BUILD-261009"
    defn = {"schema_version": 1, "task_id": ptask, "kind": "promotion", "base_oid": base, "candidate_oid": cand,
            "candidate_branch": "batch/unit-build-261009", "prose_head": "head.txt", "prose_tail": "tail.txt"}
    _w(d / "def.json", json.dumps(defn))
    text, authors, authored = pb.build(root, str(d / "def.json"))
    lines = br.prompt_lines(text.encode())
    spec = br.load_spec(lines, ptask)
    assert spec["kind"] == "promotion" and authors == {} and "allowed NONE" in text
    assert "promote " + ptask + " batch/unit-build-261009" in text
    must = json.loads(br.extract_block(lines, "MUST_READ_JSON"))
    assert must["commit"] == cand and [f["path"] for f in must["files"]] == list(br.MUST_READ_KERNEL)
    br.check_must_read(root, spec, lines)
    defn["candidate_oid"] = "c" * 40               # a candidate the repository does not hold cannot be bound
    _w(d / "def.json", json.dumps(defn))
    assert _code(pb.build, root, str(d / "def.json")) == "MUST_READ_GIT_FAILED"


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
    assert lines[3] == ("uv run --offline --no-sync --no-python-downloads --python .venv\\Scripts\\python.exe "
                         "python scripts/prompt_intake.py --task-id " + TASK + " --source " + src + " --sha256 " + digest)
    assert "C:\\Users\\U\\Desktop\\HH.AI_v2" in lines[2]
    assert lines[-1] == "Get-FileHash -Algorithm SHA256 -LiteralPath '" + src + "'"


# G5 (B-117): the startup text pins what the Executor does when prompt_intake fails, including the read-only
# S1 TARGET_EXISTS description; the wording is fixed here so any change to the rule is a reviewed change.
STARTUP_FAILURE_EXPECTED = (
    "命令失敗（任何非 0 退出碼，含 S1 TARGET_EXISTS）則停止並原樣回報輸出，不得重試或修改命令，"
    "不得讀取 .git 內任何檔案，不得刪除、移動、改名或重建任何檔案，也不得執行任何其他命令；"
    "回覆最後一行逐字為「以上是 Antigravity IDE Agent 的回覆。」")


def test_startup_intake_failure_rule_is_fixed_and_forbids_repair(tmp_path, repo):
    root, base = repo
    out = tmp_path / "out"
    pb.main(["build", "--repo", root, "--definition", _definition(tmp_path, base), "--out-dir", str(out)])
    lines = pb.startup_lines(str(out / (TASK + "-prompt.txt")), "C:\\Users\\U\\Downloads", "C:\\W")
    assert pb.STARTUP_INTAKE_FAILURE_RULE == STARTUP_FAILURE_EXPECTED
    assert lines[4] == ("命令成功後，以 IDE 原生檢視工具從第一行讀到最後一行 .git/" + TASK
                        + "-prompt.txt，並完全依其指示執行；" + STARTUP_FAILURE_EXPECTED)
    # Exactly one failure rule, and the success instruction still comes first on the same line.
    assert lines[4].count("命令失敗") == 1 and lines[4].index("命令成功後") == 0
    for phrase in ("S1 TARGET_EXISTS", "不得重試或修改命令", "不得刪除、移動、改名或重建任何檔案",
                   "也不得執行任何其他命令", "以上是 Antigravity IDE Agent 的回覆。"):
        assert phrase in lines[4]


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


# --- must-read closure (G4 slice 2) -------------------------------------------------------------

def test_build_generates_the_must_read_list_and_block_from_the_runner(tmp_path, repo):
    root, base = repo
    text = pb.build(root, _definition(tmp_path, base))[0]
    lines = br.prompt_lines(text.encode("utf-8"))
    spec = br.load_spec(lines, TASK)
    closure = br.derive_must_read(root, spec)
    assert json.loads(br.extract_block(lines, "MUST_READ_JSON")) == closure
    i = lines.index("二、動手前必讀")
    expected = ["1. .git/" + TASK + "-prompt.txt（本提示詞；機器區塊由 runner 使用，確認存在即可）"]
    expected += [str(n) + ". " + f["path"] for n, f in enumerate(closure["files"], start=2)]
    assert lines[i + 1:i + 1 + len(expected)] == expected
    assert "{MUST_READ}" not in text


@pytest.mark.parametrize("head", ["{TASK_ID}\n二、動手前必讀\n1. AGENTS.md\n", "{TASK_ID}\n{MUST_READ}\n{MUST_READ}\n"])
def test_build_requires_exactly_one_must_read_token(tmp_path, repo, head):
    root, base = repo
    path = _definition(tmp_path, base)
    _w(Path(path).parent / "head.txt", head)
    assert _code(pb.build, root, path) == "MUST_READ_TOKEN_COUNT"


def test_build_stops_when_a_rule_file_is_unmapped(tmp_path, repo):
    root, _ = repo
    (Path(root) / ".agents" / "rules" / "unlisted.md").write_bytes(b"# new\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "new rule")
    base = _git(root, "rev-parse", "HEAD").stdout.decode().strip()
    assert _code(pb.build, root, _definition(tmp_path, base)) == "MUST_READ_RULE_UNMAPPED"


def test_check_rejects_a_tampered_must_read_block_before_running_validators(tmp_path, repo):
    root, base = repo
    out = tmp_path / "out"
    assert pb.main(["build", "--repo", root, "--definition", _definition(tmp_path, base), "--out-dir", str(out)]) == 0
    prompt_path = out / (TASK + "-prompt.txt")
    data = prompt_path.read_text(encoding="utf-8")
    closure = json.loads(br.extract_block(br.prompt_lines(data.encode()), "MUST_READ_JSON"))
    tampered = dict(closure, files=closure["files"][:-1])
    old_block = "<<<BEGIN MUST_READ_JSON>>>\n" + json.dumps(closure, ensure_ascii=False, indent=1) + "\n<<<END MUST_READ_JSON>>>"
    assert data.count(old_block) == 1
    prompt_path.write_bytes(data.replace(old_block, "<<<BEGIN MUST_READ_JSON>>>\n" + json.dumps(tampered, indent=1)
                                         + "\n<<<END MUST_READ_JSON>>>").encode("utf-8"))
    calls = []
    with pytest.raises(pb.BuildError) as exc:
        pb.check(root, str(prompt_path), runner=lambda *a, **k: calls.append(a))
    assert str(exc.value) == "CHECK_MUST_READ_MISMATCH" and calls == []



@pytest.mark.parametrize("head", [
    "{TASK_ID}\n二、動手前必讀\n說明\n三、其他\n{MUST_READ}\n",          # token outside the formal section
    "{TASK_ID}\n二、動手前必讀\n{MUST_READ}\n4. 手寫之額外項目\n",          # an extra numbered line in the section
    "{TASK_ID}\n說明\n{MUST_READ}\n",                                      # no formal section at all
])
def test_build_rejects_a_misplaced_or_padded_must_read_section(tmp_path, repo, head):
    root, base = repo
    path = _definition(tmp_path, base)
    _w(Path(path).parent / "head.txt", head)
    assert _code(pb.build, root, path) == "RUNNER_MUST_READ_SECTION_MISMATCH"


def test_check_rejects_a_section_edited_after_build_with_the_block_intact(tmp_path, repo):
    # Second-opinion counterexample: a correct MUST_READ_JSON with a shortened reading list must not pass.
    root, base = repo
    out = tmp_path / "out"
    assert pb.main(["build", "--repo", root, "--definition", _definition(tmp_path, base), "--out-dir", str(out)]) == 0
    prompt_path = out / (TASK + "-prompt.txt")
    text = prompt_path.read_text(encoding="utf-8")
    lines = br.prompt_lines(text.encode())
    spec = br.load_spec(lines, TASK)
    generated = "\n".join(br.must_read_lines(TASK, br.derive_must_read(root, spec)))
    assert text.count(generated) == 1
    prompt_path.write_bytes(text.replace(generated, "1. AGENTS.md").encode("utf-8"))
    calls = []
    with pytest.raises(pb.BuildError) as exc:
        pb.check(root, str(prompt_path), runner=lambda *a, **k: calls.append(a))
    assert str(exc.value) == "CHECK_MUST_READ_SECTION_MISMATCH" and calls == []


# --- B-116 F1: reject branch names the audit packet cannot classify -----------------------------

@pytest.mark.parametrize("bad", [
    "batch/aud-gpt-261013-state-sync-r1",  # observed F1, revision after date
    "batch/unit-build-r1",                  # date omitted
    "batch/unit-build-20261013",            # eight-digit date suffix
    "batch/unit-build",                     # no date
])
def test_f1_build_refuses_unclassifiable_branch_before_outputs(tmp_path, repo, bad):
    root, base = repo
    out = tmp_path / "out"
    definition = _definition(tmp_path, base, branch=bad)
    assert pb.main(["build", "--repo", root, "--definition", definition, "--out-dir", str(out)]) == 1
    assert not out.exists(), "build must not create an output directory for an invalid branch"


def test_f1_build_accepts_valid_revision_and_no_revision(tmp_path, repo):
    root, base = repo
    for branch in ("batch/unit-build-r1-261013", "batch/unit-build-261013"):
        task = branch.removeprefix("batch/").upper()
        text, _, _ = pb.build(root, _definition(tmp_path, base, branch=branch, task_id=task))
        assert br.load_spec(br.prompt_lines(text.encode()), task)["branch"] == branch


def test_f1_check_fails_before_owning_any_temporary_copy(tmp_path, repo):
    root, prompt = _built_prompt(tmp_path, repo)
    # A forged prompt whose task id and branch agree but carry no date: only the classifier can refuse it.
    forged = prompt.with_name("UNIT-BUILD-FORGED-prompt.txt")
    data = prompt.read_bytes().replace(b"UNIT-BUILD-261009", b"UNIT-BUILD-FORGED").replace(b"unit-build-261009", b"unit-build-forged")
    forged.write_bytes(data)

    def must_not_run(*a, **kw):
        raise AssertionError("validator and preflight must not run after branch rejection")

    assert _code(pb.check, root, str(forged), must_not_run) == "BRANCH_UNCLASSIFIABLE"
    assert not (Path(root) / ".git" / "UNIT-BUILD-FORGED-prompt.txt").exists()
    assert _code(pb.startup_lines, str(forged), "C:\\D", "C:\\W") == "BRANCH_UNCLASSIFIABLE"


def test_f1_classifier_unknown_must_fail_closed(tmp_path, repo, monkeypatch):
    root, base = repo
    monkeypatch.setattr(pb.audit_packet, "branch_classified", lambda _branch: None)
    assert _code(pb.build, root, _definition(tmp_path, base)) == "BRANCH_UNCLASSIFIABLE"


def test_f1_promotion_build_rejects_unclassifiable_candidate_branch(tmp_path, repo):
    root, base = repo
    d = tmp_path / "promo"
    d.mkdir()
    _w(d / "head.txt", "promotion {BRANCH}\n二、動手前必讀\n{MUST_READ}\n")
    _w(d / "tail.txt", "ready\n")
    definition = {"schema_version": 1, "task_id": TASK, "kind": "promotion", "base_oid": base,
                  "candidate_oid": "c" * 40, "candidate_branch": "batch/aud-gpt-261013-state-sync-r1",
                  "prose_head": "head.txt", "prose_tail": "tail.txt"}
    _w(d / "def.json", json.dumps(definition))
    assert _code(pb.build, root, str(d / "def.json")) == "BRANCH_UNCLASSIFIABLE"

@pytest.mark.parametrize('bad', [
    'batch/UNIT-build-r1-261013',
    'batch/unit-build-R1-261013',
])
def test_f1_build_rejects_noncanonical_branch_chars_before_outputs(tmp_path, repo, bad):
    root, base = repo
    out = tmp_path / 'out'
    definition = _definition(tmp_path, base, branch=bad)
    assert _code(pb.build, root, definition) == 'BRANCH_UNCLASSIFIABLE'
    assert not out.exists()


def _f1_promotion_prompt(tmp_path, repo, branch):
    root, base = repo
    _git(root, 'commit', '-q', '--allow-empty', '-m', 'candidate')
    candidate_oid = _git(root, 'rev-parse', 'HEAD').stdout.decode().strip()
    d = tmp_path / 'promotion'
    d.mkdir()
    _w(d / 'head.txt', '{TASK_ID} promotion {BRANCH}\n二、動手前必讀\n{MUST_READ}\n')
    _w(d / 'tail.txt', 'ready\n')
    task = br.promotion_task_for_branch(branch)
    definition = {'schema_version': 1, 'task_id': task, 'kind': 'promotion',
                  'base_oid': base, 'candidate_oid': candidate_oid,
                  'candidate_branch': branch, 'prose_head': 'head.txt', 'prose_tail': 'tail.txt'}
    _w(d / 'def.json', json.dumps(definition))
    text, _, _ = pb.build(root, str(d / 'def.json'))
    prompt = tmp_path / (task + '-prompt.txt')
    prompt.write_bytes(text.encode('utf-8'))
    return root, prompt


def test_f1_promotion_check_and_startup_accept_valid_candidate_branch(tmp_path, repo):
    root, prompt = _f1_promotion_prompt(tmp_path, repo, 'batch/unit-promotion-r2-261013')
    seen = []

    def fake(*a, **k):
        seen.append(a[0][1])
        return _Result(0)

    task = 'PROMOTE-UNIT-PROMOTION-R2-261013'
    assert pb.check(root, str(prompt), runner=fake) == task
    assert seen == ['scripts/validate_prompt_manifest.py', 'scripts/governance_preflight.py']
    lines = pb.startup_lines(str(prompt), 'C:\\D', 'C:\\W')
    assert any(line.startswith('SHA256_UPPER=') for line in lines)
    assert any('prompt_intake.py' in line for line in lines)
    assert not (Path(root) / '.git' / (task + '-prompt.txt')).exists()


def test_f1_promotion_check_and_startup_reject_bad_candidate_branch_without_side_effect(tmp_path, repo):
    root, prompt = _f1_promotion_prompt(tmp_path, repo, 'batch/unit-promotion-r2-261013')
    # Task id and branch agree (so only the classifier can refuse): a revision after the date.
    forged = prompt.with_name('PROMOTE-AUD-GPT-261013-STATE-SYNC-R1-prompt.txt')
    forged.write_bytes(prompt.read_bytes().replace(b'batch/unit-promotion-r2-261013', b'batch/aud-gpt-261013-state-sync-r1')
                       .replace(b'PROMOTE-UNIT-PROMOTION-R2-261013', b'PROMOTE-AUD-GPT-261013-STATE-SYNC-R1'))
    calls = []
    assert _code(pb.check, root, str(forged), lambda *a, **k: calls.append(a)) == 'BRANCH_UNCLASSIFIABLE'
    assert _code(pb.startup_lines, str(forged), 'C:\\D', 'C:\\W') == 'BRANCH_UNCLASSIFIABLE'
    assert calls == []
    assert not (Path(root) / '.git' / (TASK + '-prompt.txt')).exists()

# B-115 (9) slice 1: candidate-derived promotion prose must not inherit prior claims.
def _auto_promotion_fixture(tmp_path, repo):
    import promotion_template
    root, base = repo
    _git(root, 'update-ref', 'refs/remotes/origin/main', base)
    branch = 'batch/b115-auto-promotion-r1-261013'
    _git(root, 'switch', '-q', '-c', branch)
    _w(Path(root) / 'docs' / 'BOARD.md', '# Board\ncandidate\n')
    _git(root, 'add', 'docs/BOARD.md')
    _git(root, 'commit', '-qm', 'candidate')
    candidate = _git(root, 'rev-parse', 'HEAD').stdout.decode().strip()
    _git(root, 'update-ref', 'refs/remotes/origin/' + branch, candidate)
    return promotion_template, root, base, branch, candidate


def test_b115_auto_promotion_deterministic_and_runner_accepted(tmp_path, repo):
    pm, root, base, branch, candidate = _auto_promotion_fixture(tmp_path, repo)
    a = pm.auto_promotion(root, candidate, branch, tmp_path / 'a')
    b = pm.auto_promotion(root, candidate, branch, tmp_path / 'b')
    assert a.read_bytes() == b.read_bytes()
    text = a.read_text('utf-8')
    assert candidate in text and base in text
    assert '- docs/BOARD.md' in text
    assert '候選修改 runner: NO' in text
    assert '草稿' not in text and '不得視為晉級授權' not in text
    assert 'USER 同一 SHA 晉級常設授權' in text and candidate in text
    assert '已啟動或背景執行中不算完成' in text
    assert 'post-main PENDING 不得當作 PASS' in text
    # B-119: promotion generator must hand off both actual CI_RUN locators.
    assert 'CI_RUN phase=candidate' in text
    assert 'CI_RUN phase=postmain' in text
    assert 'MAIN、TIMING、STATE' in text
    assert '成功只逐字複製 runner 的 MAIN、TIMING、STATE 三行' not in text
    assert text.count('CI_RUN phase=candidate') == 1
    assert text.count('CI_RUN phase=postmain') == 1
    assert '只准執行下列兩個命令' in text
    assert text.count('scripts/batch_runner.py --task-id') == 2
    assert text.count(' run\n') == 1 and text.count(' resume-check\n') == 1
    assert not any(' ' + step + '\n' in text for step in ('preflight', 'verify', 'promote', 'postmain', 'timing'))
    assert 'RUN_END STATE=COMPLETE' in text and '不看 exit code' in text
    assert '2. 本批不更新 runner' in text
    assert 'scripts/batch_runner.py 已更新' not in text
    spec = br.load_spec(br.prompt_lines(a.read_bytes()), a.name.removesuffix('-prompt.txt'))
    assert spec['candidate_oid'] == candidate and spec['base_oid'] == base


@pytest.mark.parametrize('mode,expected', [
    ('wrong_oid', 'PROMOTION_PARENT_MISMATCH'),
    ('wrong_ref', 'PROMOTION_BRANCH_MISMATCH'),
    ('bad_name', 'BRANCH_UNCLASSIFIABLE'),
    ('non_full_oid', 'CANDIDATE_OID_INVALID'),
    ('changed_main', 'PROMOTION_PARENT_MISMATCH'),
    ('unreachable', 'PROMOTION_GIT_UNAVAILABLE'),
    ('local_only_ref', 'PROMOTION_BRANCH_MISMATCH'),
])
def test_b115_auto_promotion_fail_closed(tmp_path, repo, mode, expected):
    pm, root, base, branch, candidate = _auto_promotion_fixture(tmp_path, repo)
    oid = candidate
    if mode == 'wrong_oid':
        oid = base
    elif mode == 'wrong_ref':
        branch = 'batch/b115-missing-261013'
    elif mode == 'bad_name':
        branch = 'batch/b115-no-date'
    elif mode == 'non_full_oid':
        oid = '1234'
    elif mode == 'changed_main':
        _git(root, 'update-ref', 'refs/remotes/origin/main', candidate)
    elif mode == 'local_only_ref':
        _git(root, 'update-ref', '-d', 'refs/remotes/origin/' + branch)
    else:
        oid = 'e' * 40
        expected = 'PROMOTION_GIT_UNAVAILABLE'
    with pytest.raises(pb.BuildError) as e:
        pm.auto_promotion(root, oid, branch, tmp_path / 'out')
    assert str(e.value) == expected
    assert not (tmp_path / 'out').exists()


def test_b115_auto_promotion_rejects_existing_prompt(tmp_path, repo):
    pm, root, _, branch, oid = _auto_promotion_fixture(tmp_path, repo)
    out = tmp_path / 'out'
    first = pm.auto_promotion(root, oid, branch, out)
    existing = first.read_bytes()
    with pytest.raises(pb.BuildError, match='PROMOTION_OUTPUT_EXISTS'):
        pm.auto_promotion(root, oid, branch, out)
    assert first.read_bytes() == existing


def test_b115_auto_promotion_rejects_output_in_repo(tmp_path, repo):
    pm, root, _, branch, oid = _auto_promotion_fixture(tmp_path, repo)
    with pytest.raises(pb.BuildError, match='PROMOTION_OUT_DIR_INVALID'):
        pm.auto_promotion(root, oid, branch, Path(root) / '.git' / 'out')


def test_b115_auto_promotion_accepts_canonical_generated_diff_paths(tmp_path, repo):
    pm, root, base, branch, oid = _auto_promotion_fixture(tmp_path, repo)
    from pathlib import Path
    for path in br.GENERATED:
        target = Path(root) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'{}\n')
    _git(root, 'add', '--', *br.GENERATED)
    _git(root, 'commit', '-qm', 'generated metadata')
    # The new candidate is a two-commit range and must be rejected for its parent.
    new_oid = _git(root, 'rev-parse', 'HEAD').stdout.decode().strip()
    with pytest.raises(pb.BuildError, match='PROMOTION_PARENT_MISMATCH'):
        pm.auto_promotion(root, new_oid, branch, tmp_path / 'wrong')
    # A single candidate including both generated paths is legal; reset only this disposable synthetic tree.
    _git(root, 'reset', '--soft', base)
    _git(root, 'commit', '-qm', 'single synthetic candidate')
    new_oid = _git(root, 'rev-parse', 'HEAD').stdout.decode().strip()
    _git(root, 'update-ref', 'refs/remotes/origin/' + branch, new_oid)
    path = pm.auto_promotion(root, new_oid, branch, tmp_path / 'right')
    text = path.read_text('utf-8')
    for item in br.GENERATED:
        assert '- ' + item in text


def test_b115_auto_promotion_detects_runner_modified(tmp_path, repo):
    pm, root, base, branch, _ = _auto_promotion_fixture(tmp_path, repo)
    # Single commit, same Base; keep the remote tracking ref exact.
    _w(Path(root) / 'scripts/batch_runner.py', '# synthetic runner update\n')
    _git(root, 'add', 'scripts/batch_runner.py')
    _git(root, 'reset', '--soft', base)
    _git(root, 'commit', '-qam', 'single candidate including runner')
    changed = _git(root, 'rev-parse', 'HEAD').stdout.decode().strip()
    _git(root, 'update-ref', 'refs/remotes/origin/' + branch, changed)
    path = pm.auto_promotion(root, changed, branch, tmp_path / 'out')
    assert '候選修改 runner: YES' in path.read_text('utf-8')


def test_b115_auto_promotion_rejects_shallow_source(tmp_path, repo):
    pm, root, base, branch, oid = _auto_promotion_fixture(tmp_path, repo)
    git_dir = Path(_git(root, 'rev-parse', '--absolute-git-dir').stdout.decode().strip())
    (git_dir / 'shallow').write_bytes((base + '\n').encode('ascii'))
    assert _git(root, 'rev-parse', '--is-shallow-repository').stdout.strip() == b'true'
    with pytest.raises(pb.BuildError, match='PROMOTION_SHALLOW'):
        pm.auto_promotion(root, oid, branch, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_b115_auto_promotion_rejects_authors_json_overwrite(tmp_path, repo):
    pm, root, _, branch, oid = _auto_promotion_fixture(tmp_path, repo)
    out = tmp_path / 'out'
    out.mkdir()
    before = b'PRESERVE EXTERNAL EVIDENCE\n'
    (out / 'authors.json').write_bytes(before)
    with pytest.raises(pb.BuildError, match='PROMOTION_OUTPUT_EXISTS'):
        pm.auto_promotion(root, oid, branch, out)
    assert (out / 'authors.json').read_bytes() == before
    assert list(out.iterdir()) == [out / 'authors.json']

# B-115 (9) slice 2: repo-owned production prose is derived from one structured definition.
def _auto_production_definition(tmp_path, repo, **updates):
    root, base = repo
    import production_template
    _git(root, 'update-ref', 'refs/remotes/origin/main', base)
    d = tmp_path / 'def'
    d.mkdir()
    _w(d / 'final.py', 'def a():\n    return 3\n\n\ndef b():\n    return 2\n')
    body = {
        'schema_version': 1, 'task_id': 'UNIT-PRODUCTION-261014', 'kind': 'production',
        'base_oid': base, 'branch': 'batch/unit-production-261014',
        'commit_message': 'autoproduction unit candidate', 'one_liner': '自動產生測試用的一句話說明文字', 'e24': False, 'bundle_output': False,
        'code_files': {'scripts/tool.py': 'final.py'},
        'new_files': {}, 'text_ops': [], 'focused': None,
        'production_prose': {
            'goal': '機械產生 production prose 並保留授權邊界。',
            'scope': ['測試範圍限 scripts/tool.py。'],
            'invariants': ['禁止額外 tracked mutation。'],
            'stops': ['任何權威漂移即停止。'],
            'e27': 'APPLICABLE_PRE_EXEC_REVIEW',
            'finding_disposition': 'EXISTING B-115',
            'backlog_disposition': 'UPDATE', 'taskboard_disposition': 'UPDATE', 'audit_log_disposition': 'UPDATE',
        },
    }
    body.update(updates)
    (d / 'def.json').write_bytes((json.dumps(body, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    return production_template, root, body, d / 'def.json'


def test_b115_auto_production_deterministic_and_canonical(tmp_path, repo):
    mod, root, d, f = _auto_production_definition(tmp_path, repo)
    p1 = mod.auto_production(root, f, tmp_path / 'a')
    p2 = mod.auto_production(root, f, tmp_path / 'b')
    assert p1.read_bytes() == p2.read_bytes()
    text = p1.read_text('utf-8')
    assert '目標：機械產生' in text and 'batch/unit-production-261014' in text
    assert '- scripts/tool.py' in text
    assert 'docs/governance/execution-record.json' in text
    assert text.count('scripts/batch_runner.py --task-id') == 2
    assert text.count(' run\n') == 1 and text.count(' resume-check\n') == 1
    assert 'BEGIN_HHAI_EXECUTION_CONTRACT' in text and 'main_advancement: FORBIDDEN' in text
    assert 'E27=APPLICABLE_PRE_EXEC_REVIEW' in text
    spec = br.load_spec(br.prompt_lines(p1.read_bytes()), d['task_id'])
    assert spec['authors']['scripts/tool.py']['sha256'] == sha('def a():\n    return 3\n\n\ndef b():\n    return 2\n')
    assert len(spec['ops']) > 0


@pytest.mark.parametrize('case,expected', [
    ('base_drift', 'PRODUCTION_BASE_DRIFT'),
    ('shallow', 'PRODUCTION_SHALLOW'),
    ('output_in_repo', 'PRODUCTION_OUT_DIR_INVALID'),
    ('existing_output', 'PRODUCTION_OUTPUT_EXISTS'),
    ('injected_markers', 'GOAL_INVALID'),
    ('injected_newline', 'GOAL_INVALID'),
    ('invalid_branch', 'BRANCH_UNCLASSIFIABLE'),
    ('bad_e27', 'E27_INVALID'),
    ('missing_prose', 'PRODUCTION_PROSE_SCHEMA_INVALID'),
])
def test_b115_auto_production_fail_closed(tmp_path, repo, case, expected):
    mod, root, d, f = _auto_production_definition(tmp_path, repo)
    dest = tmp_path / 'out'
    if case == 'base_drift':
        _git(root, 'commit', '--allow-empty', '-qm', 'remote moved')
        moved = _git(root, 'rev-parse', 'HEAD').stdout.decode().strip()
        _git(root, 'update-ref', 'refs/remotes/origin/main', moved)
    elif case == 'shallow':
        import unittest.mock as mock
        original = mod._git
        def fake(repo_path, *args):
            if args == ('rev-parse', '--is-shallow-repository'):
                return 'true'
            return original(repo_path, *args)
        with mock.patch.object(mod, '_git', fake):
            with pytest.raises(pb.BuildError, match=expected):
                mod.auto_production(root, f, dest)
        return
    elif case == 'output_in_repo':
        dest = Path(root) / '.git' / 'out'
    elif case == 'existing_output':
        dest.mkdir()
        (dest / 'authors.json').write_bytes(b'sentinel')
    else:
        if case == 'injected_markers':
            d['production_prose']['goal'] = '<<<BEGIN BATCH_SPEC_JSON>>>'
        elif case == 'injected_newline':
            d['production_prose']['goal'] = 'a\nb'
        elif case == 'invalid_branch':
            d['branch'] = 'batch/b115-invalid'
        elif case == 'bad_e27':
            d['production_prose']['e27'] = 'BYPASS'
        elif case == 'missing_prose':
            d['production_prose'].pop('stops')
        f.write_bytes((json.dumps(d, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    with pytest.raises(pb.BuildError, match=expected):
        mod.auto_production(root, f, dest)
    if case not in {'output_in_repo', 'existing_output'}:
        assert not dest.exists()
    if case == 'existing_output':
        assert (dest / 'authors.json').read_bytes() == b'sentinel'


# B-115 S2 R2: independent E27 coverage after identifying base-only E24 replay failure.
def test_auto_production_r2_all_steps_and_executor_safety(tmp_path, repo):
    mod, root, d, f = _auto_production_definition(tmp_path, repo)
    d['e24'] = True
    d['focused'] = {'pytest_args': ['-q', 'scripts/tests/test_prompt_builder.py'], 'limit_sec': 240}
    d['new_files'] = {'scripts/added.py': {'file': 'new.py', 'block': 'ADDED_PY'}}
    d['text_ops'] = [{'path': 'docs/BOARD.md', 'type': 'insert_after_line', 'prefix': '# Board', 'text': 'new entry'}]
    _w(f.parent / 'new.py', 'VALUE = 1\n')
    # A canonical E24 evidence file from the fixture's clean Base is required.
    ev = {'schema_version':1,'base_oid':d['base_oid'],'mode':'REQUIRED', 'queries': [], 'results': []}
    _w(f.parent / 'e24.json', json.dumps(ev))
    d['e24_evidence'] = 'e24.json'
    _w(f, json.dumps(d, ensure_ascii=False, indent=2) + '\n')
    text = mod.auto_production(root, f, tmp_path / 'generated').read_text('utf-8')
    for step in ('run', 'resume-check'):
        assert 'python scripts/batch_runner.py --task-id ' + d['task_id'] + ' ' + step + '\n' in text
    for step in ('preflight','setup','e24','apply','focused','generate','precommit','stage','commit','postcommit','push','timing'):
        assert '--task-id ' + d['task_id'] + ' ' + step + '\n' not in text
    assert '- scripts/added.py' in text and '- docs/BOARD.md' in text
    for signal in ('背景執行中、排隊中或 PENDING 不等於結束','結果只看命令印出的固定行',
                   '不捏造 CI Run／job ID 或 PASS', 'E24=REQUIRED', 'main_advancement: FORBIDDEN'):
        assert signal in text
    assert 'B-115 repo-owned production prose' not in text

@pytest.mark.parametrize('unsupported', ['start','substitutions','prose_head','prose_tail'])
def test_auto_production_r2_disallowed_fields_fail_closed(tmp_path, repo, unsupported):
    mod, root, d, f = _auto_production_definition(tmp_path, repo)
    d[unsupported] = {} if unsupported in ('start','substitutions') else 'file.txt'
    _w(f, json.dumps(d, ensure_ascii=False, indent=2) + '\n')
    with pytest.raises(pb.BuildError, match='PRODUCTION_FIELD_UNSUPPORTED'):
        mod.auto_production(root, f, tmp_path / 'out')

def test_auto_production_r2_cli_error_is_fixed_code(tmp_path, repo):
    mod, root, d, f = _auto_production_definition(tmp_path, repo)
    out = tmp_path / 'already';out.mkdir();_w(out/'authors.json', 'UNTOUCHED')
    res = subprocess.run([sys.executable, str(Path(pb.__file__)), 'auto-production',
                          '--repo', str(root), '--definition', str(f), '--out-dir', str(out)],
                         text=True, capture_output=True, timeout=45)
    assert res.returncode == 1
    assert res.stdout.strip() == 'PROMPT_BUILDER FAIL PRODUCTION_OUTPUT_EXISTS'
    assert not res.stderr.strip()
    assert (out/'authors.json').read_text() == 'UNTOUCHED'


def test_check16_prospective_rejects_stale_log_and_accepts_fresh_row(repo, tmp_path):
    import check16_preflight as cp
    root, initial = repo
    log = Path(root) / 'docs' / 'EXEC-LOG.md'
    _w(log, '| batch commit | date | result |\n|---|---|---|\n'
            + f'| {initial} | 2026-10-14 | ok |\n')
    _git(root, 'add', 'docs/EXEC-LOG.md')
    _git(root, 'commit', '-q', '-m', 'advance')
    base = _git(root, 'rev-parse', 'HEAD').stdout.decode().strip()
    with pytest.raises(cp.ProspectiveError, match='CHECK16_PROSPECTIVE_FAIL'):
        cp.prospective_check16(root, base)
    fresh = log.read_bytes().decode('utf-8') + f'| {base} | 2026-10-14 | ok |\n'
    assert cp.prospective_check16(root, base, fresh)
    _w(log, fresh)  # dirty, not committed: no false success on Base-only evidence
    with pytest.raises(cp.ProspectiveError, match='CHECK16_PROSPECTIVE_FAIL'):
        cp.prospective_check16(root, base)
    _w(log, fresh.rsplit(f'| {base} |',1)[0])
    with pytest.raises(cp.ProspectiveError, match='CHECK16_PROSPECTIVE_FAIL'):
        cp.prospective_check16(root, base, fresh.replace(base, 'f'*40))
    with pytest.raises(cp.ProspectiveError, match='CHECK16_PROSPECTIVE_FAIL'):
        cp.prospective_check16(root, base, fresh + '| BAD | x | x |\n')
    with pytest.raises(cp.ProspectiveError, match='CHECK16_BASE_DRIFT'):
        cp.prospective_check16(root, initial, fresh)
    # No new current-repo file or commit, even on a negative path.
    assert _git(root, 'rev-parse', 'HEAD').stdout.decode().strip() == base
    assert log.read_bytes().decode('utf-8').count(base) == 0
    assert _git(root, 'status', '--porcelain').stdout == b''


def test_check16_prospective_builder_build_and_check_bind_final_authors(repo, tmp_path):
    import check16_preflight as cp
    root, initial = repo
    log = Path(root) / 'docs' / 'EXEC-LOG.md'
    _w(log, f'| commit | info |\n|---|---|\n| {initial} | ok |\n')
    _git(root, 'add', 'docs/EXEC-LOG.md')
    _git(root, 'commit', '-q', '-m', 'move')
    head = _git(root, 'rev-parse', 'HEAD').stdout.decode().strip()
    d = _definition(tmp_path, head)
    assert _code(pb.build, root, d) == 'CHECK16_PROSPECTIVE_FAIL'
    raw = json.loads(Path(d).read_bytes().decode('utf-8'))
    raw['text_ops'].append({'path': 'docs/EXEC-LOG.md', 'type': 'insert_after_line',
                            'prefix': f'| {initial} |', 'text': f'| {head} | ok |'})
    _w(d, json.dumps(raw, ensure_ascii=False))
    text, _, authored = pb.build(root, d)
    assert f'| {head} | ok |' in authored['docs/EXEC-LOG.md']
    built = tmp_path / (TASK+'-prompt.txt')
    built.write_bytes(text.encode('utf-8'))
    # Use exact same final bytes in both checks. check() also invokes external
    # manifest/preflight, which synthetic fixture does not carry; inject success
    # for only those two external tools.
    def _ok(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, '', '')
    assert pb.check(root, str(built), runner=_ok) == TASK
    _w(log, log.read_bytes().decode('utf-8') + '| corrupt | ok |\n')
    assert pb.check(root, str(built), runner=_ok) == TASK  # final prompt authors outrank dirty worktree


# B-118 first-activation negative tests: new auto-production must explicitly decide output.
def test_b118_auto_production_bundle_field_missing_rejected(tmp_path, repo):
    mod, root, d, path = _auto_production_definition(tmp_path, repo)
    d.pop('bundle_output')
    _w(path, json.dumps(d, ensure_ascii=False) + '\n')
    with pytest.raises(pb.BuildError, match='PRODUCTION_BUNDLE_OUTPUT_REQUIRED'):
        mod.auto_production(root, path, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('bad', [None, 'true', 1, 0, [], {}])
def test_b118_auto_production_bundle_field_invalid_rejected(tmp_path, repo, bad):
    mod, root, d, path = _auto_production_definition(tmp_path, repo)
    d['bundle_output'] = bad
    _w(path, json.dumps(d, ensure_ascii=False) + '\n')
    with pytest.raises(pb.BuildError, match='PRODUCTION_BUNDLE_OUTPUT_INVALID'):
        mod.auto_production(root, path, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_b118_auto_production_bundle_enabled_contract_steps_and_reply(tmp_path, repo):
    mod, root, d, path = _auto_production_definition(tmp_path, repo, bundle_output=True)
    text = mod.auto_production(root, path, tmp_path / 'out').read_text('utf-8')
    spec = br.load_spec(br.prompt_lines(text.encode()), d['task_id'])
    assert spec['bundle_output'] is True
    assert br.derive_steps(spec)[-1] == 'bundle'
    assert 'external_artifact_write: DOWNLOADS_BUNDLE_AFTER_PUSH' in text
    assert '--task-id ' + d['task_id'] + ' bundle' not in text  # the single run command includes the bundle step
    assert 'python scripts/batch_runner.py --task-id ' + d['task_id'] + ' run\n' in text
    assert 'BUNDLE_FILE=、ORIGIN_MAIN=' in text and 'BUNDLE FAILED <CODE>' in text


def test_b118_auto_production_bundle_disabled_legacy_route_explicit(tmp_path, repo):
    mod, root, d, path = _auto_production_definition(tmp_path, repo, bundle_output=False)
    text = mod.auto_production(root, path, tmp_path / 'out').read_text('utf-8')
    spec = br.load_spec(br.prompt_lines(text.encode()), d['task_id'])
    assert not spec.get('bundle_output', False)
    assert br.derive_steps(spec)[-1] == 'push'
    assert 'external_artifact_write: FORBIDDEN' in text


def test_b118_enabled_contract_unknown_enum_rejected_by_validator(tmp_path, repo):
    import validate_prompt_manifest as validator
    mod, root, d, path = _auto_production_definition(tmp_path, repo, bundle_output=True)
    valid = mod.auto_production(root, path, tmp_path / 'out').read_text('utf-8')
    ok, _, parsed = validator.parse_execution_contract_block(valid)
    assert ok and parsed['external_artifact_write'] == 'DOWNLOADS_BUNDLE_AFTER_PUSH'
    tampered = valid.replace('external_artifact_write: DOWNLOADS_BUNDLE_AFTER_PUSH',
                             'external_artifact_write: ALL_FILES_UNRESTRICTED')
    ok, _, parsed = validator.parse_execution_contract_block(tampered)
    assert ok
    ok, error, _ = validator.validate_execution_contract(parsed)
    assert not ok and 'external_artifact_write invalid' in error


def test_b118_enabled_contract_wrong_but_valid_enum_detected_by_builder(tmp_path, repo, monkeypatch):
    import validate_prompt_manifest as validator
    mod, root, d, path = _auto_production_definition(tmp_path, repo, bundle_output=True)
    actual = validator.parse_execution_contract_block
    def corrupted_contract(prompt_text):
        ok, error, parsed = actual(prompt_text)
        if ok:
            parsed['external_artifact_write'] = 'FORBIDDEN'
        return ok, error, parsed
    monkeypatch.setattr(validator, 'parse_execution_contract_block', corrupted_contract)
    with pytest.raises(pb.BuildError, match='BUNDLE_CONTRACT_MISMATCH'):
        mod.auto_production(root, path, tmp_path / 'out')

# The canonical builder/checker recognises READONLY without granting canonical production-runner rights.
def test_readonly_builder_accepts_only_registered_probe_and_fixed_contract(tmp_path, repo):
    root, base = repo
    d = tmp_path / 'ro'; d.mkdir()
    definition = {'schema_version': 1, 'task_id': TASK, 'kind': 'readonly', 'base_oid': base,
                  'probe_id': 'C9_RECOVERY_PREFLIGHT_V1',
                  's1_task_id': 'B119-N7N8-POSTMAIN-STATE-R1-261018',
                  's1_base_oid': 'fdd59488a0632d0654fc6a1251bba004502cef51'}
    _w(d / 'def.json', json.dumps(definition))
    result, authors, authored = pb.build(root, str(d / 'def.json'))
    assert authors == authored == {}
    spec = br.load_spec(br.prompt_lines(result.encode()), TASK)
    assert spec['kind'] == 'readonly' and br.derive_steps(spec) == []
    assert 'READONLY_SCRIPT' not in result and 'git push origin main' not in result
    assert 'allowed_mutation_paths: NONE' in result
    assert 'branch_creation: FORBIDDEN' in result
    assert 'python scripts/readonly_probe.py --task-id ' + TASK in result
    assert pb.build(root, str(d / 'def.json'))[0] == result
    for key, value in [('readonly_script', 'unsafe.ps1'), ('prose_tail', 'unsafe.txt'),
                       ('command', 'git push origin main'), ('path', '../bad')]:
        altered = dict(definition, **{key:value})
        _w(d / 'def.json', json.dumps(altered))
        assert _code(pb.build, root, str(d / 'def.json')) == 'READONLY_DEFINITION_FIELDS'
    for key, value in [('probe_id', 'ARBITRARY'), ('s1_task_id', 'OTHER-TASK'),
                       ('s1_base_oid', 'a'*40)]:
        altered = dict(definition, **{key:value})
        _w(d / 'def.json', json.dumps(altered))
        assert _code(pb.build, root, str(d / 'def.json')) == 'READONLY_PROBE_NOT_REGISTERED'
    for old, new in [('allowed_mutation_paths: NONE', 'allowed_mutation_paths: docs/TASKBOARD.md'),
                     ('required_mutation_paths: NONE', 'required_mutation_paths: docs/TASKBOARD.md'),
                     ('execution_record_required: false', 'execution_record_required: true'),
                     ('external_artifact_write: FORBIDDEN', 'external_artifact_write: DOWNLOADS_BUNDLE_AFTER_PUSH'),
                     ('branch_creation: FORBIDDEN', 'branch_creation: GIT_SWITCH_C')]:
        with pytest.raises(pb.BuildError, match='READONLY_CONTRACT_DRIFT'):
            pb.validate_readonly_contract(result.replace(old, new), spec)

def test_readonly_checker_rejects_injected_prose_even_with_new_sha(tmp_path, repo):
    root, base = repo
    folder=tmp_path/'readonly';folder.mkdir()
    definition={'schema_version':1,'task_id':TASK,'kind':'readonly','base_oid':base,
                'probe_id':'C9_RECOVERY_PREFLIGHT_V1',
                's1_task_id':'B119-N7N8-POSTMAIN-STATE-R1-261018',
                's1_base_oid':'fdd59488a0632d0654fc6a1251bba004502cef51'}
    path=folder/'definition.json';_w(path,json.dumps(definition))
    good=pb.build(root,str(path))[0]
    canonical=folder/(TASK+'-prompt.txt')
    canonical.write_bytes(good.encode())
    def success(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, b'', b'')
    assert pb.check(root,str(canonical),runner=success)==TASK
    for attack in ('git push origin main', 'Set-Content -LiteralPath probe.txt -Value synthetic',
                   "& ('g'+'it') push origin main", "Write-Output 'OBSERVED_HOLD'"):
        changed=good.replace('五、回覆：',attack+'\n五、回覆：')
        canonical.write_bytes(changed.encode())
        assert _code(pb.check,root,str(canonical),success)=='READONLY_PROMPT_CANONICAL_DRIFT'
    canonical.write_bytes(good.replace('四、唯一固定唯讀探針命令','四、固定可信命令').encode())
    assert _code(pb.check,root,str(canonical),success)=='READONLY_PROMPT_CANONICAL_DRIFT'

# B115/G3 CI-PENDING-REPLY: positive terminal handoff; no checker command for Executor.
def test_g3_auto_production_reply_terminal_contract(tmp_path, repo):
    mod, root, definition, path = _auto_production_definition(tmp_path, repo)
    text = mod.auto_production(root, path, tmp_path / 'reply_contract').read_text('utf-8')
    assert 'EXECUTOR_REPLY_BEGIN' in text and 'EXECUTOR_REPLY_END' in text
    assert 'REPLY_SELF_CHECK=PASS' in text and '立即結束' in text
    assert 'CI PENDING' in text and '不捏造 CI Run／job ID 或 PASS' in text
    assert 'reply_check.py --prompt' not in text
    assert 'EXECUTOR_REPLY_UNAVAILABLE' in text  # self-hosting pre-apply fallback
    assert 'runner 在同一命令內自動輸出 timing' in text
    assert '成功路徑的 timing 由 run 在最後自動執行' in text
    assert '首批 runner_update 的 apply 階段（含）以前' not in text


def test_g3_auto_promotion_reply_terminal_contract(tmp_path, repo):
    pm, root, _base, branch, candidate = _auto_promotion_fixture(tmp_path, repo)
    text = pm.auto_promotion(root, candidate, branch, tmp_path / 'promote_reply').read_text('utf-8')
    assert 'EXECUTOR_REPLY_BEGIN' in text and 'EXECUTOR_REPLY_END' in text
    assert 'REPLY_SELF_CHECK=PASS' in text and '立即' in text
    assert 'CI PENDING' in text and '不得補造 PASS' in text
    assert 'runner 在同一命令內自動輸出 timing' in text
    assert '成功路徑的 timing 由 run 在最後自動執行' in text
    assert '僅舊 runner 未輸出 timing' not in text
    assert 'reply_check.py --prompt' not in text


def test_b123b_f1_f2_focus_adds_every_changed_test_and_preserves_explicit():
    import production_template as pt
    d={'code_files': {'scripts/tests/test_one.py':'one','scripts/tests/test_two.py':'two',
                      'scripts/misc.py':'misc'}, 'new_files': {}}
    assert pt.canonical_focused(d)['pytest_args']==['-q','-rs','scripts/tests/test_one.py','scripts/tests/test_two.py']
    d['focused']={'pytest_args':['-q','scripts/tests/test_two.py','scripts/tests/test_manual.py'],
                  'limit_sec': 1800}
    focused=pt.canonical_focused(d)
    assert focused['pytest_args'].count('scripts/tests/test_two.py')==1
    assert 'scripts/tests/test_manual.py' in focused['pytest_args']
    assert '-rs' in focused['pytest_args']


def test_so_check_rejects_changed_test_without_canonical_focused(tmp_path, repo):
    # A hand-built prompt (build, not auto-production) that changes a test file must still fail check.
    root, base = repo
    out = tmp_path / "out"
    nf = {"scripts/new_tool.py": {"file": "new.py", "block": "NEW_TOOL_PY"},
          "scripts/tests/test_new_x.py": {"file": "new.py", "block": "NEW_TEST_X_PY"}}
    pb.main(["build", "--repo", root, "--definition", _definition(tmp_path, base, new_files=nf), "--out-dir", str(out)])
    assert _code(pb.check, root, str(out / (TASK + "-prompt.txt")), lambda *a, **k: _Result(0)) == "CHECK_FOCUSED_MISSING"


# G5-b2: the Executor is only ever told to run the single command (and the read-only check); one text for both kinds.
def test_g5b2_run_protocol_text_is_one_fixed_table_with_conditional_rows():
    plain = pb.run_protocol_text('production')
    assert plain == pb.run_protocol_text('production', False, False)
    update = pb.run_protocol_text('production', runner_update=True)
    preview = pb.run_protocol_text('production', preview=True)
    promo = pb.run_protocol_text('promotion')
    assert any('RUN_IDLE_CHECK seconds=210' in line for line in preview)
    assert not any('RUN_IDLE_CHECK' in line for line in plain + update + promo)
    assert any(line.startswith('2. 印出 `RUN_STOPPED CODE=RUNNER_UPDATED') for line in update)
    assert any(line.startswith('2. 本批不更新 runner') for line in plain + promo)
    assert [line[:2] for line in plain if line[0].isdigit()] == ['1.', '2.', '3.', '4.', '5.']
    assert plain[0].startswith('啟動第一個命令之前，若 IDE 顯示額度或權限不足') and all(plain[0] == p[0] for p in (update, preview, promo))
    assert any('第六節' in line for line in plain) and not any('第六節' in line for line in promo)
    assert any('第五節' in line for line in promo)
    assert all('scripts/batch_runner.py' not in line for line in plain + update + preview + promo)
    # only a state that can continue may be run again; a running or interrupted batch is never touched
    resume = [line for line in plain if line.startswith('5.')][0]
    assert '`NOT_STARTED` 或 `RESUMABLE` → 再執行一次第一個命令' in resume
    assert '`RUNNING`' in resume and '`INTERRUPTED`' in resume and '立即停止並回報原始輸出' in resume
    # every rerun is bounded: an Executor never loops on the single command
    assert '（這種情形只准一次）' in resume
    second = [line for line in update if line.startswith('2.')][0]
    assert '（這種情形只准一次）' in second and 'exit code 為 5，不是失敗' in second
    assert sum('再執行一次第一個命令' in line for line in update) == 2
    assert any('對 run 本身以本表為準' in line for line in plain)
    # an IDE that keeps showing a finished command as running: one read-only check after about four hours, never a kill
    assert '約 4 小時' in resume and '不得中止它' in resume


def test_g5b2_commands_are_exactly_run_then_resume_check_and_preview_is_checked_against_them(monkeypatch):
    import validate_prompt_manifest as vpm
    commands = pb.production_runner_commands('T-1', pb.RUN_COMMAND_STEPS, True)
    assert pb.RUN_COMMAND_STEPS == ['run', 'resume-check']
    assert [c.rsplit(' ', 1)[1] for c in commands] == ['run', 'resume-check']
    assert all('python -B scripts/batch_runner.py --task-id T-1 ' in c for c in commands)
    monkeypatch.setattr(vpm, 'parse_execution_contract_block',
                        lambda text: (True, None, {'native_preview_external_write': 'TEMP_ISOLATED_NATIVE_PREVIEW'}))
    spec = {'task_id': 'T-1', 'native_preview': True}
    tail = '\n<<<BEGIN BATCH_SPEC_JSON>>>\n'
    pb.check_preview_contract('\n'.join(commands) + tail, spec)
    old = pb.production_runner_commands('T-1', ['preflight', 'native_preview', 'timing'], True)
    for wrong in (old, commands[:1], commands[::-1], commands + commands[:1]):
        with pytest.raises(pb.BuildError, match='NATIVE_PREVIEW_COMMANDS_MISMATCH'):
            pb.check_preview_contract('\n'.join(wrong) + tail, spec)


# --- G7-b3b2：每批「一句話」由工具寫入，不靠手寫 ------------------------------------------------------------

ONE_LINER_TEXT = "單元測試用的一句話說明文字"
ONE_LINER_LEAD = "一句話：" + ONE_LINER_TEXT + "。"


@pytest.mark.parametrize("over", [
    {"one_liner": None}, {"one_liner": ""}, {"one_liner": 7}, {"one_liner": "短"}, {"one_liner": "字" * 61},
    {"one_liner": "含句號的一句話說明文字。"}, {"one_liner": "含 B117-G7B3B2-ONE-261119 的說明文字"},
    {"one_liner": "含 5dc5105188 的一句話說明文字"}, {"one_liner": "改了 scripts/x.py 的一句話說明"},
    {"one_liner": "含大括號{TASK_ID}的一句話說明"}, {"one_liner": "兩行\n的一句話說明文字"},
])
def test_one_liner_must_be_present_and_valid_for_production(tmp_path, repo, over):
    root, base = repo
    assert _code(pb.build, root, _definition(tmp_path, base, **over)) == "ONE_LINER_INVALID"


def test_one_liner_missing_key_is_rejected(tmp_path, repo):
    root, base = repo
    d = _definition(tmp_path, base)
    raw = json.loads(Path(d).read_bytes().decode("utf-8"))
    del raw["one_liner"]
    _w(d, json.dumps(raw, ensure_ascii=False))
    assert _code(pb.build, root, d) == "ONE_LINER_INVALID"


def test_one_liner_placeholder_expands_in_prose_and_text_ops(tmp_path, repo):
    root, base = repo
    d = _definition(tmp_path, base)
    raw = json.loads(Path(d).read_bytes().decode("utf-8"))
    raw["text_ops"].append({"path": "docs/BOARD.md", "type": "insert_after_line", "prefix": "| X-3 |", "text": "| X-4 | {ONE_LINER} |"})
    _w(Path(d).parent / "tail.txt", "scope {ALLOWED}\nrecord {SO}\n{ONE_LINER}\n")
    _w(d, json.dumps(raw, ensure_ascii=False))
    text, _, authored = pb.build(root, d)
    assert "| X-4 | " + ONE_LINER_LEAD + " |\n" in authored["docs/BOARD.md"]
    assert "\n" + ONE_LINER_LEAD + "\n" in text


def _state_repo(root, with_board=True):
    """在 fixture repo 補上看板與 EXEC-LOG（含錨點之前的一列）並 commit，回傳新的 Base。"""
    board = ("# 任務看板\n\n**NEXT_SLICE**：old\n\n"
             "**舊批（2026-11-18；本批 B117-OLD-R1-261118）**：舊批紀錄。\n")
    _w(Path(root) / "docs" / "TASKBOARD.md", board)
    base0 = _git(root, "rev-parse", "HEAD").stdout.decode().strip()
    _w(Path(root) / "docs" / "EXEC-LOG.md",
       "| 批次 commit | 日期 | 說明 |\n|---|---|---|\n" + f"| {base0} | 2026-11-18 | B117-OLD-R1-261118：舊列。 |\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "state")
    return _git(root, "rev-parse", "HEAD").stdout.decode().strip(), base0


def _state_definition(tmp_path, root, board_text, log_text):
    base, base0 = _state_repo(root)
    d = _definition(tmp_path, base)
    raw = json.loads(Path(d).read_bytes().decode("utf-8"))
    raw["text_ops"] += [
        {"path": "docs/TASKBOARD.md", "type": "insert_after_line", "prefix": "**NEXT_SLICE**：", "text": "\n" + board_text},
        {"path": "docs/EXEC-LOG.md", "type": "insert_after_line", "prefix": f"| {base0} |", "text": log_text.replace("{BASE}", base)},
    ]
    _w(d, json.dumps(raw, ensure_ascii=False))
    return d


GOOD_BOARD = "**本批（2026-11-19；本批 {TASK_ID}）**：{ONE_LINER}一、說明。"
GOOD_LOG = "| {BASE} | 2026-11-19 | {TASK_ID}：{ONE_LINER}說明。 |"


def test_state_rows_written_with_the_placeholder_are_accepted(tmp_path, repo):
    root, _ = repo
    d = _state_definition(tmp_path, root, GOOD_BOARD, GOOD_LOG)
    _, _, authored = pb.build(root, d)
    assert ("：" + ONE_LINER_LEAD + "一、說明。") in authored["docs/TASKBOARD.md"]
    assert (TASK + "：" + ONE_LINER_LEAD + "說明。 |") in authored["docs/EXEC-LOG.md"]


@pytest.mark.parametrize("board,log,code", [
    ("**本批（2026-11-19；本批 {TASK_ID}）**：手寫的一句話說明文字。一、說明。", GOOD_LOG, "ONE_LINER_BOARD_RECORD"),
    ("**本批（2026-11-19；本批 {TASK_ID}）**：一句話：別的說明文字也很長很長。一、說明。", GOOD_LOG, "ONE_LINER_BOARD_RECORD"),
    (GOOD_BOARD, "| {BASE} | 2026-11-19 | {TASK_ID}：手寫的說明文字。 |", "ONE_LINER_EXEC_LOG_ROW"),
    (GOOD_BOARD, "| {BASE} | 2026-11-19 | {TASK_ID}：一句話：別的說明文字也很長很長。說明。 |", "ONE_LINER_EXEC_LOG_ROW"),
])
def test_state_rows_that_do_not_carry_the_tool_written_sentence_are_rejected(tmp_path, repo, board, log, code):
    root, _ = repo
    assert _code(pb.build, root, _state_definition(tmp_path, root, board, log)) == code
