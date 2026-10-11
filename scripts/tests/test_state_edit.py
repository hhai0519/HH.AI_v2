#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scripts/state_edit.py (B-107 G4 slice 3b).

Expected texts and hashes are written by hand or computed here with hashlib from those hand-written texts,
never taken from the tool's own constants or helpers.
"""

import hashlib
import json
import os
import shutil
import stat
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
import state_edit as se  # noqa: E402

TASK = "B107-STATE-EDIT-TEST-261011"
BASE = "0123456789abcdef0123456789abcdef01234567"
TB, BL, AL, EL = "docs/TASKBOARD.md", "docs/refactor-backlog.md", "docs/AUDIT-LOG.md", "docs/EXEC-LOG.md"

ORIG_TB = "# Board\n\n**NEXT_WORK**：B-1\n| B-1 | open | first |\n| B-2 | open | second |\n"
ORIG_EL = "# Exec log\n| aaa | row one |\n| bbb | row two |\n"


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def prompt_text(task, allowed):
    return "\n".join([
        "BEGIN_HHAI_PROMPT_MANIFEST", "schema_version: 1", "batch_mode: GOAL_SPEC", "base_oid: " + BASE,
        "finding_disposition: NONE", "backlog_disposition: NO_CHANGE", "taskboard_disposition: UPDATE",
        "audit_log_disposition: NO_CHANGE", "rules_reread_required: true", "fixed_signature_required: true",
        "destructive_git_allowed: false", "END_HHAI_PROMPT_MANIFEST", "",
        "BEGIN_HHAI_EXECUTION_CONTRACT", "contract_version: 2", "task_id: " + task, "base_oid: " + BASE,
        "main_advancement: FORBIDDEN", "authorized_main_sha: NONE", "remote_ref_deletion: FORBIDDEN",
        "authorized_delete_refs: NONE", "local_destructive_git: FORBIDDEN", "credential_access: FORBIDDEN",
        "environment_enumeration: FORBIDDEN", "cross_session_access: FORBIDDEN",
        "browser_github_mutation: FORBIDDEN", "raw_actions_log_access: EXTERNAL_MACRO_ONLY",
        "branch_creation: GIT_SWITCH_C", "hook_bypass: FORBIDDEN", "goal_pressure_policy: SAFETY_BOUNDARY_WINS",
        "ide_ephemeral_guards_required: false", "allowed_mutation_paths: " + ";".join(allowed),
        "required_mutation_paths: " + allowed[0], "max_plan_revisions: 3", "execution_record_required: true",
        "END_HHAI_EXECUTION_CONTRACT", ""])


def make_repo(tmp_path, allowed=(TB, EL), files=None, task=TASK):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "docs" / "governance").mkdir(parents=True)
    shutil.copyfile(os.path.join(REPO_ROOT, "docs", "governance", "rule-registry.json"),
                    str(repo / "docs" / "governance" / "rule-registry.json"))
    (repo / ".git" / (task + "-prompt.txt")).write_text(prompt_text(task, list(allowed)), encoding="utf-8")
    for path, text in (files if files is not None else {TB: ORIG_TB, EL: ORIG_EL}).items():
        p = repo / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    return repo


def write_ops(repo, files, task=TASK, **extra):
    doc = {"schema_version": 1, "task_id": task, "files": files}
    doc.update(extra)
    (repo / ".git" / (task + "-state-ops.json")).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def plan_of(repo, task=TASK):
    return json.loads((repo / ".git" / (task + "-state-plan.json")).read_text(encoding="utf-8"))


def write_plan(repo, plan, task=TASK):
    (repo / ".git" / (task + "-state-plan.json")).write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")


def psha(repo, task=TASK):
    try:
        return sha((repo / ".git" / (task + "-prompt.txt")).read_bytes())
    except OSError:
        return "0" * 64


def plan_sha(repo, task=TASK):
    return sha((repo / ".git" / (task + "-state-plan.json")).read_bytes())


def do_seal(repo):
    se.seal(repo, TASK, psha(repo))
    return plan_sha(repo)


def do_apply(repo, sealed=None):
    # Default: the operator passes the hash of the plan file as it is now (forged-but-consistent when tampered).
    se.apply(repo, TASK, psha(repo), sealed if sealed is not None else plan_sha(repo))


def stop_code(fn, *args):
    with pytest.raises(se.Stop) as exc:
        fn(*args)
    return str(exc.value)


def read(repo, path):
    return (repo / path).read_bytes()


TB_OPS = [
    {"type": "replace_line", "prefix": "**NEXT_WORK**：", "new": "**NEXT_WORK**：B-2"},
    {"type": "replace", "old": "| B-1 | open | first |", "new": "| B-1 | done | first |"},
    # Sequential: this anchor exists only after the previous op.
    {"type": "insert_after_line", "prefix": "| B-1 | done |", "text": "| B-1a | open | inserted |"},
]
EXPECTED_TB = "# Board\n\n**NEXT_WORK**：B-2\n| B-1 | done | first |\n| B-1a | open | inserted |\n| B-2 | open | second |\n"
EL_OPS = [{"type": "insert_after_line", "prefix": "| bbb |", "text": "| ccc | row three |"}]
EXPECTED_EL = "# Exec log\n| aaa | row one |\n| bbb | row two |\n| ccc | row three |\n"


def sealed_two(tmp_path):
    repo = make_repo(tmp_path)
    write_ops(repo, [{"path": TB, "ops": TB_OPS}, {"path": EL, "ops": EL_OPS}])
    do_seal(repo)
    return repo


# --- seal ---------------------------------------------------------------------------------------

def test_seal_records_before_and_after_hashes_of_ops_applied_in_order(tmp_path, capsys):
    repo = sealed_two(tmp_path)
    plan = plan_of(repo)
    assert [f["path"] for f in plan["files"]] == [EL, TB]
    by = {f["path"]: f for f in plan["files"]}
    assert by[TB]["before_sha256"] == sha(ORIG_TB) and by[TB]["after_sha256"] == sha(EXPECTED_TB)
    assert by[EL]["before_sha256"] == sha(ORIG_EL) and by[EL]["after_sha256"] == sha(EXPECTED_EL)
    assert by[TB]["ops"] == TB_OPS
    assert read(repo, TB) == ORIG_TB.encode() and read(repo, EL) == ORIG_EL.encode(), "seal writes no tracked file"
    out = capsys.readouterr().out
    assert "STATE_EDIT RESULT sealed=2" in out and "B-1a" not in out, "no file content is printed"


def test_seal_never_overwrites_an_existing_plan(tmp_path):
    repo = sealed_two(tmp_path)
    before = (repo / ".git" / (TASK + "-state-plan.json")).read_bytes()
    assert stop_code(do_seal, repo) == "STATE_PLAN_EXISTS"
    assert (repo / ".git" / (TASK + "-state-plan.json")).read_bytes() == before


@pytest.mark.parametrize("ops,code", [
    ([{"type": "replace", "old": "| B-9 |", "new": "x"}], "STATE_OP_ANCHOR_INVALID"),        # anchor absent
    ([{"type": "replace", "old": "| B-", "new": "x"}], "STATE_OP_ANCHOR_INVALID"),           # anchor twice
    ([{"type": "replace_line", "prefix": "| B-", "new": "x"}], "STATE_OP_ANCHOR_INVALID"),   # prefix on two lines
    ([{"type": "replace", "old": "| B-1 | open | first |", "new": "| B-1 | done | first |"},
      {"type": "replace", "old": "| B-1 | open | first |", "new": "y"}], "STATE_OP_ANCHOR_INVALID"),  # gone after op 1
    ([{"type": "replace", "old": "second |", "new": "second | "}], "STATE_RESULT_TRAILING_WHITESPACE"),
    ([{"type": "replace", "old": "second", "new": "second"}], "STATE_RESULT_UNCHANGED"),
])
def test_seal_stops_on_anchor_and_result_rule_violations(tmp_path, ops, code):
    repo = make_repo(tmp_path)
    write_ops(repo, [{"path": TB, "ops": ops}])
    assert stop_code(do_seal, repo) == code
    assert not (repo / ".git" / (TASK + "-state-plan.json")).exists()


@pytest.mark.parametrize("files,extra", [
    ([{"path": TB, "ops": [{"type": "rename", "old": "a", "new": "b"}]}], {}),
    ([{"path": TB, "ops": [{"type": "replace", "old": "a", "new": "b", "x": 1}]}], {}),
    ([{"path": TB, "ops": [{"type": "replace", "old": "", "new": "b"}]}], {}),
    ([{"path": TB, "ops": []}], {}),
    ([{"path": TB, "ops": TB_OPS}, {"path": TB, "ops": TB_OPS}], {}),
    ([], {}),
    ([{"path": TB, "ops": TB_OPS, "before_sha256": "0" * 64}], {}),
    ([{"path": TB, "ops": TB_OPS}], {"extra": True}),
])
def test_seal_rejects_malformed_ops(tmp_path, files, extra):
    repo = make_repo(tmp_path)
    write_ops(repo, files, **extra)
    assert stop_code(do_seal, repo) == "STATE_OPS_INVALID"


def test_seal_rejects_ops_of_another_task_and_missing_ops(tmp_path):
    repo = make_repo(tmp_path)
    assert stop_code(do_seal, repo) == "STATE_OPS_MISSING"
    write_ops(repo, [{"path": TB, "ops": TB_OPS}])
    doc = json.loads((repo / ".git" / (TASK + "-state-ops.json")).read_text(encoding="utf-8"))
    doc["task_id"] = "OTHER-TASK"
    (repo / ".git" / (TASK + "-state-ops.json")).write_text(json.dumps(doc), encoding="utf-8")
    assert stop_code(do_seal, repo) == "STATE_OPS_INVALID"


def test_registered_list_and_task_allowed_paths_are_separate(tmp_path):
    # docs/HANDOVER.md is allowed by the prompt but is not a registered state file.
    repo = make_repo(tmp_path, allowed=(TB, "docs/HANDOVER.md"), files={TB: ORIG_TB, "docs/HANDOVER.md": "# H\n"})
    write_ops(repo, [{"path": "docs/HANDOVER.md", "ops": [{"type": "replace", "old": "# H", "new": "# G"}]}])
    assert stop_code(do_seal, repo) == "STATE_PATH_NOT_REGISTERED"
    # docs/EXEC-LOG.md is registered but this task's prompt does not allow it.
    repo2 = make_repo(tmp_path / "b", allowed=(TB,))
    write_ops(repo2, [{"path": EL, "ops": EL_OPS}])
    assert stop_code(do_seal, repo2) == "STATE_PATH_NOT_ALLOWED"
    assert read(repo2, EL) == ORIG_EL.encode()


def test_missing_or_invalid_task_prompt_stops(tmp_path):
    repo = make_repo(tmp_path)
    write_ops(repo, [{"path": TB, "ops": TB_OPS}])
    (repo / ".git" / (TASK + "-prompt.txt")).write_text("not a prompt\n", encoding="utf-8")
    assert stop_code(do_seal, repo) == "STATE_TASK_PROMPT_INVALID"
    (repo / ".git" / (TASK + "-prompt.txt")).unlink()
    assert stop_code(do_seal, repo) == "STATE_TASK_PROMPT_INVALID"


def test_prompt_of_another_task_does_not_authorize(tmp_path):
    repo = make_repo(tmp_path)
    write_ops(repo, [{"path": TB, "ops": TB_OPS}])
    (repo / ".git" / (TASK + "-prompt.txt")).write_text(prompt_text("OTHER-TASK", [TB, EL]), encoding="utf-8")
    assert stop_code(do_seal, repo) == "STATE_TASK_PROMPT_INVALID"


@pytest.mark.parametrize("data,code", [
    (ORIG_TB.replace("\n", "\r\n").encode(), "STATE_SOURCE_CR"),
    (b"# Board \xff\n", "STATE_SOURCE_NOT_UTF8"),
    (ORIG_TB.rstrip("\n").encode(), "STATE_SOURCE_TRAILING_NEWLINE"),
])
def test_seal_applies_the_byte_rule_to_the_source(tmp_path, data, code):
    repo = make_repo(tmp_path, files={TB: data, EL: ORIG_EL})
    write_ops(repo, [{"path": TB, "ops": [{"type": "replace", "old": "B-2", "new": "B-3"}]}])
    assert stop_code(do_seal, repo) == code


def test_ops_artifact_that_is_a_link_stops(tmp_path):
    repo = make_repo(tmp_path)
    real = tmp_path / "ops.json"
    real.write_text(json.dumps({"schema_version": 1, "task_id": TASK, "files": [{"path": TB, "ops": TB_OPS}]}),
                    encoding="utf-8")
    try:
        os.symlink(str(real), str(repo / ".git" / (TASK + "-state-ops.json")))
    except (OSError, NotImplementedError) as exc:
        pytest.skip("capability gap: symbolic links cannot be created here (" + type(exc).__name__ + ")")
    assert stop_code(do_seal, repo) == "STATE_ARTIFACT_PATH_INVALID"


# --- apply --------------------------------------------------------------------------------------

def test_apply_writes_the_planned_result_and_a_rerun_writes_nothing(tmp_path, capsys):
    repo = sealed_two(tmp_path)
    do_apply(repo)
    assert read(repo, TB) == EXPECTED_TB.encode() and read(repo, EL) == EXPECTED_EL.encode()
    assert "STATE_EDIT RESULT written=2 already=0" in capsys.readouterr().out
    st = os.stat(str(repo / TB))
    do_apply(repo)
    out = capsys.readouterr().out
    assert "STATE_EDIT ALREADY_APPLIED " + TB in out and "STATE_EDIT RESULT written=0 already=2" in out
    assert os.stat(str(repo / TB)).st_ino == st.st_ino, "already applied: the file is not replaced again"
    assert not [n for n in os.listdir(str(repo / "docs")) if n.endswith(".state-edit.tmp")], "no temporary file left"


def test_interrupted_after_the_first_replace_then_a_rerun_completes(tmp_path, capsys, monkeypatch):
    # Second-opinion counterexample 1: the first file is replaced, the second replace fails.
    repo = sealed_two(tmp_path)
    real_replace = os.replace
    calls = []

    def flaky(src, dst):
        calls.append(dst)
        if len(calls) == 2:
            raise PermissionError("synthetic replace failure")
        return real_replace(src, dst)

    monkeypatch.setattr(se.os, "replace", flaky)
    assert stop_code(do_apply, repo) == "STATE_WRITE_FAILED"
    monkeypatch.setattr(se.os, "replace", real_replace)
    assert read(repo, EL) == EXPECTED_EL.encode() and read(repo, TB) == ORIG_TB.encode()
    assert not [n for n in os.listdir(str(repo / "docs")) if n.endswith(".state-edit.tmp")], "temporary file removed"
    capsys.readouterr()
    do_apply(repo)
    out = capsys.readouterr().out
    assert "STATE_EDIT ALREADY_APPLIED " + EL in out and "STATE_EDIT WRITTEN " + TB in out
    assert read(repo, TB) == EXPECTED_TB.encode()


def test_interrupted_then_a_file_changed_to_third_content_is_a_conflict(tmp_path):
    # Second-opinion counterexample 2: after the interruption a file holds neither the before nor the after bytes.
    repo = sealed_two(tmp_path)
    (repo / EL).write_bytes(EXPECTED_EL.encode())          # finished earlier
    (repo / TB).write_bytes((ORIG_TB + "| B-3 | open | third |\n").encode())
    assert stop_code(do_apply, repo) == "STATE_CONFLICT"
    assert read(repo, TB) == (ORIG_TB + "| B-3 | open | third |\n").encode()
    assert plan_of(repo)["files"][1]["before_sha256"] == sha(ORIG_TB), "the plan is never re-sealed"


def test_every_file_is_classified_before_any_write(tmp_path):
    # EL sorts first and is writable; TB conflicts: nothing at all may be written.
    repo = sealed_two(tmp_path)
    (repo / TB).write_bytes(b"# Board\n\nchanged elsewhere\n")
    assert stop_code(do_apply, repo) == "STATE_CONFLICT"
    assert read(repo, EL) == ORIG_EL.encode()


def test_a_differently_encoded_copy_of_the_result_is_not_already_applied(tmp_path):
    repo = sealed_two(tmp_path)
    (repo / EL).write_bytes(EXPECTED_EL.replace("\n", "\r\n").encode())
    assert stop_code(do_apply, repo) == "STATE_CONFLICT"


def test_a_plan_whose_after_hash_does_not_match_the_ops_stops_without_writing(tmp_path):
    repo = sealed_two(tmp_path)
    plan = plan_of(repo)
    plan["files"][0]["after_sha256"] = "f" * 64
    write_plan(repo, plan)
    assert stop_code(do_apply, repo) == "STATE_RESULT_MISMATCH"
    assert read(repo, EL) == ORIG_EL.encode() and read(repo, TB) == ORIG_TB.encode()


@pytest.mark.parametrize("mutate", [
    lambda p: p["files"][0].update(after_sha256=p["files"][0]["before_sha256"]),
    lambda p: p["files"][0].update(before_sha256="XYZ"),
    lambda p: p["files"][0].update(extra=1),
    lambda p: p.update(task_id="OTHER-TASK"),
    lambda p: p.update(schema_version=2),
])
def test_malformed_plan_stops(tmp_path, mutate):
    repo = sealed_two(tmp_path)
    plan = plan_of(repo)
    mutate(plan)
    write_plan(repo, plan)
    assert stop_code(do_apply, repo) == "STATE_PLAN_INVALID"


def test_missing_plan_stops(tmp_path):
    repo = make_repo(tmp_path)
    assert stop_code(do_apply, repo, "a" * 64) == "STATE_PLAN_MISSING"


def test_safety_checks_run_again_even_when_the_hash_says_already_applied(tmp_path):
    repo = sealed_two(tmp_path)
    do_apply(repo)
    outside = tmp_path / "outside.md"
    shutil.copyfile(str(repo / EL), str(outside))
    (repo / EL).unlink()
    try:
        os.link(str(outside), str(repo / EL))
    except (OSError, NotImplementedError, AttributeError) as exc:
        pytest.skip("capability gap: hard links cannot be created here (" + type(exc).__name__ + ")")
    assert stop_code(do_apply, repo) == "STATE_TARGET_UNSAFE"


def test_rerun_checks_the_current_prompt_scope(tmp_path):
    repo = sealed_two(tmp_path)
    delivered, sealed = psha(repo), plan_sha(repo)
    (repo / ".git" / (TASK + "-prompt.txt")).write_text(prompt_text(TASK, [TB]), encoding="utf-8")
    assert stop_code(se.apply, repo, TASK, delivered, sealed) == "STATE_PROMPT_SHA_MISMATCH"
    assert stop_code(do_apply, repo) == "STATE_PROMPT_SHA_MISMATCH", "the plan names the sealed prompt"
    assert read(repo, TB) == ORIG_TB.encode()


def test_linked_parent_directory_stops(tmp_path):
    repo = make_repo(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    shutil.copytree(str(repo / "docs"), str(elsewhere))
    shutil.rmtree(str(repo / "docs"))
    try:
        os.symlink(str(elsewhere), str(repo / "docs"), target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip("capability gap: symbolic links cannot be created here (" + type(exc).__name__ + ")")
    write_ops(repo, [{"path": TB, "ops": TB_OPS}])
    assert stop_code(do_seal, repo) == "STATE_TARGET_UNSAFE"
    assert (elsewhere / "TASKBOARD.md").read_text(encoding="utf-8") == ORIG_TB


def test_missing_state_file_stops(tmp_path):
    repo = make_repo(tmp_path, files={TB: ORIG_TB})
    write_ops(repo, [{"path": EL, "ops": EL_OPS}])
    assert stop_code(do_seal, repo) == "STATE_TARGET_MISSING"


def test_read_only_target_stops_before_any_write(tmp_path, monkeypatch):
    repo = sealed_two(tmp_path)
    real_access = os.access
    target = os.path.join(os.path.realpath(str(repo)), "docs", "TASKBOARD.md")
    monkeypatch.setattr(se.os, "access", lambda p, m: False if os.fspath(p) == target else real_access(p, m))
    assert stop_code(do_apply, repo) == "STATE_TARGET_READONLY"
    assert read(repo, EL) == ORIG_EL.encode(), "EL sorts first but nothing is written"


def test_unreadable_target_stops(tmp_path, monkeypatch):
    repo = sealed_two(tmp_path)
    real_open = open
    target = os.path.join(os.path.realpath(str(repo)), "docs", "TASKBOARD.md")

    def fake_open(file, mode="r", *a, **k):
        if os.fspath(file) == target and "r" in mode:
            raise PermissionError("synthetic read failure")
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr("builtins.open", fake_open)
    assert stop_code(do_apply, repo) == "STATE_TARGET_UNREADABLE"


def test_existing_temporary_file_stops_and_is_left_untouched(tmp_path):
    repo = sealed_two(tmp_path)
    leftover = repo / "docs" / (".EXEC-LOG.md." + TASK + ".state-edit.tmp")
    leftover.write_bytes(b"left by an interrupted run\n")
    assert stop_code(do_apply, repo) == "STATE_TEMP_EXISTS"
    assert leftover.read_bytes() == b"left by an interrupted run\n"
    assert read(repo, EL) == ORIG_EL.encode()


def test_failed_temporary_write_removes_only_its_own_file(tmp_path, monkeypatch):
    repo = sealed_two(tmp_path)
    monkeypatch.setattr(se.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("synthetic fsync failure")))
    assert stop_code(do_apply, repo) == "STATE_WRITE_FAILED"
    assert not [n for n in os.listdir(str(repo / "docs")) if n.endswith(".state-edit.tmp")]
    assert read(repo, EL) == ORIG_EL.encode()


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_replace_keeps_the_permission_bits(tmp_path):
    repo = sealed_two(tmp_path)
    os.chmod(str(repo / TB), 0o640)
    do_apply(repo)
    assert stat.S_IMODE(os.stat(str(repo / TB)).st_mode) == 0o640


# --- command line -------------------------------------------------------------------------------

def test_main_usage_and_task_id_errors(capsys):
    p = "a" * 64
    assert se.main(["bogus", "--task-id", TASK, "--prompt-sha256", p]) == 2
    assert se.main(["seal", "--task-id", "bad id!", "--prompt-sha256", p]) == 2
    assert se.main(["seal", "--task-id", TASK]) == 2                                   # no prompt hash
    assert se.main(["seal", "--task-id", TASK, "--prompt-sha256", "xyz"]) == 2           # not a SHA-256
    assert se.main(["apply", "--task-id", TASK, "--prompt-sha256", p]) == 2              # no plan hash
    assert se.main(["seal", "--task-id", TASK, "--prompt-sha256", p, "--plan-sha256", p]) == 2
    out = capsys.readouterr().out
    assert out.count("S1 USAGE") == 5 and "S1 STATE_TASK_ID_INVALID" in out


def test_main_requires_the_repository_root_as_working_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(str(tmp_path))
    assert se.main(["seal", "--task-id", TASK, "--prompt-sha256", "a" * 64]) == 1
    assert "S1 STATE_WORKING_DIRECTORY_MISMATCH" in capsys.readouterr().out


def test_main_runs_seal_and_apply_and_reports_stops(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path)
    write_ops(repo, [{"path": TB, "ops": TB_OPS}])
    monkeypatch.setattr(se, "ROOT", repo.resolve())
    monkeypatch.chdir(str(repo))
    p = psha(repo)
    assert se.main(["seal", "--task-id", TASK, "--prompt-sha256", p.upper()]) == 0
    out = capsys.readouterr().out
    q = [line.split("=", 1)[1] for line in out.splitlines() if line.startswith("STATE_EDIT PLAN sha256=")]
    assert q == [plan_sha(repo)], "seal prints the SHA-256 of the plan file it wrote"
    assert se.main(["apply", "--task-id", TASK, "--prompt-sha256", p, "--plan-sha256", q[0]]) == 0
    assert read(repo, TB) == EXPECTED_TB.encode()
    (repo / TB).write_bytes(b"# third content\n")
    assert se.main(["apply", "--task-id", TASK, "--prompt-sha256", p, "--plan-sha256", q[0]]) == 1
    assert "S1 STATE_CONFLICT" in capsys.readouterr().out


def test_registered_state_files_are_the_four_written_in_the_rule():
    assert se.STATE_FILES == ("docs/TASKBOARD.md", "docs/refactor-backlog.md", "docs/AUDIT-LOG.md", "docs/EXEC-LOG.md")
    rule = open(os.path.join(REPO_ROOT, ".agents", "rules", "governance-gate-integrity.md"), encoding="utf-8").read()
    for path in se.STATE_FILES:
        assert "`" + path + "`" in rule


def test_a_prompt_that_fails_the_governance_preflight_does_not_authorize(tmp_path, monkeypatch):
    # Fault injection: the preflight reports failure but still returns a well-formed prompt text.
    repo = make_repo(tmp_path)
    write_ops(repo, [{"path": TB, "ops": TB_OPS}])
    text = prompt_text(TASK, [TB, EL])
    monkeypatch.setattr(se, "verify_current_task_prompt", lambda root, task: (False, "S1 synthetic", text, []))
    assert stop_code(do_seal, repo) == "STATE_TASK_PROMPT_INVALID"


def test_target_is_checked_again_right_before_its_write(tmp_path, monkeypatch):
    # The file becomes a hard link after classification: the write is refused and the linked file is unchanged.
    repo = sealed_two(tmp_path)
    outside = tmp_path / "outside.md"
    real_classify = se.classify

    def classify_then_link(*args):
        out = real_classify(*args)
        shutil.copyfile(str(repo / EL), str(outside))
        (repo / EL).unlink()
        try:
            os.link(str(outside), str(repo / EL))
        except (OSError, NotImplementedError, AttributeError) as exc:
            pytest.skip("capability gap: hard links cannot be created here (" + type(exc).__name__ + ")")
        return out

    monkeypatch.setattr(se, "classify", classify_then_link)
    assert stop_code(do_apply, repo) == "STATE_TARGET_UNSAFE"
    assert outside.read_bytes() == ORIG_EL.encode()


def test_an_existing_line_with_trailing_whitespace_is_kept_and_no_new_one_may_be_added(tmp_path):
    # The real refactor-backlog has such a line (a Markdown line break); editing elsewhere must still work.
    src = ORIG_TB.replace("# Board", "# Board  ")
    repo = make_repo(tmp_path, files={TB: src, EL: ORIG_EL})
    write_ops(repo, [{"path": TB, "ops": [{"type": "replace", "old": "| B-2 | open |", "new": "| B-2 | done |"}]}])
    do_seal(repo)
    do_apply(repo)
    assert read(repo, TB) == src.replace("| B-2 | open |", "| B-2 | done |").encode()
    repo2 = make_repo(tmp_path / "b", files={TB: src, EL: ORIG_EL})
    write_ops(repo2, [{"path": TB, "ops": [{"type": "insert_after_line", "prefix": "| B-2 |", "text": "| B-3 |  "}]}])
    assert stop_code(do_seal, repo2) == "STATE_RESULT_TRAILING_WHITESPACE"


def test_the_real_state_files_satisfy_the_byte_rule():
    for path in se.STATE_FILES:
        with open(os.path.join(REPO_ROOT, path), "rb") as f:
            se.clean_text(f.read(), "STATE_SOURCE")


def test_apply_checks_the_byte_rule_of_the_result_too(tmp_path):
    # A tampered plan whose after hash matches a result that adds trailing whitespace is still refused.
    repo = make_repo(tmp_path)
    ops = [{"type": "insert_after_line", "prefix": "| B-2 |", "text": "| B-3 |  "}]
    result = (ORIG_TB + "| B-3 |  \n").encode()
    write_plan(repo, {"schema_version": 1, "task_id": TASK, "prompt_sha256": psha(repo), "files": [
        {"path": TB, "before_sha256": sha(ORIG_TB), "after_sha256": sha(result), "ops": ops}]})
    assert stop_code(do_apply, repo) == "STATE_RESULT_TRAILING_WHITESPACE"
    assert read(repo, TB) == ORIG_TB.encode()


# --- second-opinion counterexamples: the plan and the prompt are bound to values given from outside ----------

def test_a_plan_with_a_removed_entry_stops_on_the_sealed_plan_hash(tmp_path):
    repo = make_repo(tmp_path)
    write_ops(repo, [{"path": TB, "ops": TB_OPS}, {"path": EL, "ops": EL_OPS}])
    sealed = do_seal(repo)
    plan = plan_of(repo)
    plan["files"] = [f for f in plan["files"] if f["path"] != TB]
    write_plan(repo, plan)
    assert stop_code(do_apply, repo, sealed) == "STATE_PLAN_SHA_MISMATCH"
    assert read(repo, TB) == ORIG_TB.encode() and read(repo, EL) == ORIG_EL.encode()


def test_a_plan_with_swapped_before_and_after_stops_on_the_sealed_plan_hash(tmp_path):
    repo = make_repo(tmp_path)
    write_ops(repo, [{"path": TB, "ops": TB_OPS}, {"path": EL, "ops": EL_OPS}])
    sealed = do_seal(repo)
    plan = plan_of(repo)
    for f in plan["files"]:
        f["before_sha256"], f["after_sha256"] = f["after_sha256"], f["before_sha256"]
    write_plan(repo, plan)
    assert stop_code(do_apply, repo, sealed) == "STATE_PLAN_SHA_MISMATCH"
    assert read(repo, TB) == ORIG_TB.encode() and read(repo, EL) == ORIG_EL.encode()


def test_a_replaced_prompt_of_the_same_task_cannot_widen_the_scope(tmp_path):
    # The delivered prompt allows only TASKBOARD; a well-formed replacement of the same task also allows EXEC-LOG.
    repo = make_repo(tmp_path, allowed=(TB,))
    delivered = psha(repo)
    write_ops(repo, [{"path": EL, "ops": EL_OPS}])
    (repo / ".git" / (TASK + "-prompt.txt")).write_text(prompt_text(TASK, [TB, EL]), encoding="utf-8")
    assert stop_code(se.seal, repo, TASK, delivered) == "STATE_PROMPT_SHA_MISMATCH"
    assert not (repo / ".git" / (TASK + "-state-plan.json")).exists()
    assert read(repo, EL) == ORIG_EL.encode()


def test_a_prompt_replaced_between_seal_and_apply_stops(tmp_path):
    repo = make_repo(tmp_path, allowed=(TB, EL))
    delivered = psha(repo)
    write_ops(repo, [{"path": EL, "ops": EL_OPS}])
    sealed = do_seal(repo)
    (repo / ".git" / (TASK + "-prompt.txt")).write_text(prompt_text(TASK, [EL, TB]), encoding="utf-8")
    assert stop_code(se.apply, repo, TASK, delivered, sealed) == "STATE_PROMPT_SHA_MISMATCH"
    # Passing the replacement's hash is refused too: the plan names the prompt it was sealed under.
    assert stop_code(se.apply, repo, TASK, psha(repo), sealed) == "STATE_PROMPT_SHA_MISMATCH"
    assert read(repo, EL) == ORIG_EL.encode()


def test_already_applied_still_requires_the_byte_rule(tmp_path):
    # Forged-but-consistent plan: its after hash is the hash of the current CRLF file.
    crlf = ORIG_TB.replace("\n", "\r\n").encode()
    repo = make_repo(tmp_path, files={TB: crlf, EL: ORIG_EL})
    write_plan(repo, {"schema_version": 1, "task_id": TASK, "prompt_sha256": psha(repo), "files": [
        {"path": TB, "before_sha256": sha(ORIG_TB), "after_sha256": sha(crlf), "ops": TB_OPS}]})
    assert stop_code(do_apply, repo) == "STATE_SOURCE_CR"
