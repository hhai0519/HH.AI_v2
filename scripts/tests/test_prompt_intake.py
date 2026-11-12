# -*- coding: utf-8 -*-
"""
scripts/tests/test_prompt_intake.py

Negative and positive controls for scripts/prompt_intake.py (B-107 canonical tooling).
"""

import hashlib
import os
import subprocess
import sys

import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TOOL = os.path.join(SCRIPTS_DIR, "prompt_intake.py")
TASK = "TEST-INTAKE-001"
CONTENT = "prompt body\n第二行\n".encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def env(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    source = downloads / "prompt.txt"
    source.write_bytes(CONTENT)
    return repo, source


def run(repo, source, digest, task=TASK):
    proc = subprocess.run(
        [sys.executable, TOOL, "--task-id", task, "--source", str(source), "--sha256", digest, "--repo-root", str(repo)],
        capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout


def target_of(repo, task=TASK):
    return repo / ".git" / f"{task}-prompt.txt"


def test_pass_copies_exact_bytes(env):
    repo, source = env
    code, out = run(repo, source, sha(CONTENT))
    assert code == 0, out
    assert "PROMPT_INTAKE PASS" in out
    assert target_of(repo).read_bytes() == CONTENT


def test_uppercase_hash_accepted(env):
    repo, source = env
    code, _ = run(repo, source, sha(CONTENT).upper())
    assert code == 0


def test_hash_mismatch_creates_nothing(env):
    repo, source = env
    code, out = run(repo, source, sha(b"other"))
    assert code == 5 and "SOURCE_HASH_MISMATCH" in out
    assert not target_of(repo).exists()


def test_source_missing(env):
    repo, source = env
    code, out = run(repo, source.parent / "absent.txt", sha(CONTENT))
    assert code == 3 and "SOURCE_MISSING" in out


def test_target_exists_is_not_overwritten(env):
    repo, source = env
    target_of(repo).write_bytes(b"old")
    code, out = run(repo, source, sha(CONTENT))
    assert code == 6 and "TARGET_EXISTS" in out
    assert target_of(repo).read_bytes() == b"old"


def test_target_exists_even_with_same_content(env):
    repo, source = env
    target_of(repo).write_bytes(CONTENT)
    code, _ = run(repo, source, sha(CONTENT))
    assert code == 6


def test_empty_and_oversize_source_rejected(env):
    repo, source = env
    source.write_bytes(b"")
    assert run(repo, source, sha(b""))[0] == 4
    big = b"a" * (1024 * 1024 + 1)
    source.write_bytes(big)
    assert run(repo, source, sha(big))[0] == 4
    assert not target_of(repo).exists()


def test_directory_source_rejected(env):
    repo, source = env
    code, _ = run(repo, source.parent, sha(CONTENT))
    assert code == 4


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unsupported")
def test_symlink_source_rejected(env, tmp_path):
    repo, source = env
    link = source.parent / "link.txt"
    try:
        os.symlink(source, link)
    except OSError:
        pytest.skip("symlink not permitted")
    code, _ = run(repo, link, sha(CONTENT))
    assert code == 4
    assert not target_of(repo).exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unsupported")
def test_symlinked_ancestor_directory_rejected(env, tmp_path):
    repo, source = env
    link_dir = tmp_path / "linked"
    try:
        os.symlink(source.parent, link_dir, target_is_directory=True)
    except OSError:
        pytest.skip("symlink not permitted")
    code, out = run(repo, link_dir / "prompt.txt", sha(CONTENT))
    assert code == 7 and "PATH_NOT_SAFE" in out
    assert not target_of(repo).exists()


def test_git_file_instead_of_directory_rejected(tmp_path):
    repo = tmp_path / "wt"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    source = tmp_path / "prompt.txt"
    source.write_bytes(CONTENT)
    code, _ = run(repo, source, sha(CONTENT))
    assert code == 7


@pytest.mark.parametrize("task", ["", "bad id", "../x", "a/b"])
def test_invalid_task_id_rejected(env, task):
    repo, source = env
    code, _ = run(repo, source, sha(CONTENT), task=task)
    assert code == 2


@pytest.mark.parametrize("digest", ["", "abc", "g" * 64])
def test_invalid_digest_rejected(env, digest):
    repo, source = env
    code, _ = run(repo, source, digest)
    assert code == 2


def test_relative_source_rejected(env):
    repo, _ = env
    code, _ = run(repo, "prompt.txt", sha(CONTENT))
    assert code == 2


def test_no_content_echo(env):
    repo, source = env
    secret_like = b"TOKEN_VALUE_SHOULD_NOT_ECHO\n"
    source.write_bytes(secret_like)
    code, out = run(repo, source, sha(b"different"))
    assert code == 5
    assert "TOKEN_VALUE_SHOULD_NOT_ECHO" not in out


# ---------------------------------------------------------------------------
# Existing target: read-only description (B-112 / G5 intake re-paste safety).
# Every case below keeps exit code 6, never changes a byte under .git, never echoes file content,
# and never reports an unreadable or untrusted record as "not started".
# ---------------------------------------------------------------------------

import json  # noqa: E402


def control_path(repo, task=TASK):
    return repo / ".git" / f"{task}-control.json"


def control_record(**over):
    record = {"task_id": TASK, "prompt_sha256": sha(CONTENT), "runner_sha256": "0" * 64, "done": [], "halted": None}
    record.update(over)
    return json.dumps(record).encode("utf-8")


def snapshot(repo):
    """Name -> bytes for every plain file directly under .git whose name starts with the task id."""
    out = {}
    for item in sorted((repo / ".git").iterdir()):
        if item.name.startswith(TASK) and item.is_file():
            out[item.name] = item.read_bytes()
    return out


def existing_state(repo, source, digest=None):
    before = snapshot(repo)
    code, out = run(repo, source, digest or sha(CONTENT))
    assert code == 6, out
    assert out.startswith("S1 TARGET_EXISTS "), out
    assert snapshot(repo) == before
    return out.strip()


def test_existing_same_bytes_without_control_is_reported_as_control_none_but_still_refused(env):
    repo, source = env
    target_of(repo).write_bytes(CONTENT)
    assert existing_state(repo, source) == "S1 TARGET_EXISTS prompt=SAME control=NONE"


def test_existing_different_bytes_are_reported_as_different(env):
    repo, source = env
    target_of(repo).write_bytes(b"old")
    assert existing_state(repo, source) == "S1 TARGET_EXISTS prompt=DIFFERENT control=NONE"


def test_existing_empty_target_is_reported_as_different(env):
    repo, source = env
    target_of(repo).write_bytes(b"")
    assert existing_state(repo, source) == "S1 TARGET_EXISTS prompt=DIFFERENT control=NONE"


def test_existing_target_that_is_a_directory_is_unreadable(env):
    repo, source = env
    target_of(repo).mkdir()
    out = run(repo, source, sha(CONTENT))
    assert out[0] == 6 and out[1].strip() == "S1 TARGET_EXISTS prompt=UNREADABLE control=NONE"
    assert target_of(repo).is_dir()


def test_existing_target_with_started_control_reports_completed_steps_and_halt(env):
    repo, source = env
    target_of(repo).write_bytes(CONTENT)
    control_path(repo).write_bytes(control_record(done=["preflight", "native_preview", "setup"]))
    assert existing_state(repo, source) == (
        "S1 TARGET_EXISTS prompt=SAME control=PRESENT done=preflight,native_preview,setup halted=None binding=MATCH")


def test_existing_target_with_halted_control_reports_the_halt_code(env):
    repo, source = env
    target_of(repo).write_bytes(CONTENT)
    control_path(repo).write_bytes(control_record(done=["preflight"], halted="focused:FOCUSED_NONZERO"))
    assert existing_state(repo, source) == (
        "S1 TARGET_EXISTS prompt=SAME control=PRESENT done=preflight halted=focused:FOCUSED_NONZERO binding=MATCH")


def test_existing_control_with_no_steps_done_is_present_not_none(env):
    repo, source = env
    target_of(repo).write_bytes(CONTENT)
    control_path(repo).write_bytes(control_record())
    assert existing_state(repo, source) == (
        "S1 TARGET_EXISTS prompt=SAME control=PRESENT done=NONE halted=None binding=MATCH")


def test_existing_control_bound_to_other_prompt_bytes_reports_binding_mismatch(env):
    repo, source = env
    target_of(repo).write_bytes(CONTENT)
    control_path(repo).write_bytes(control_record(prompt_sha256="f" * 64))
    assert existing_state(repo, source).endswith("control=PRESENT done=NONE halted=None binding=MISMATCH")
    control_path(repo).write_bytes(json.dumps({"task_id": TASK, "done": [], "halted": None}).encode("utf-8"))
    assert existing_state(repo, source).endswith("binding=MISMATCH")


# Fault injection: a control record that cannot be trusted is UNREADABLE, never NONE and never PRESENT.
UNTRUSTED_CONTROLS = {
    "not_json": b"{not json",
    "empty": b"",
    "not_utf8": b"\xff\xfe\x00",
    "list_root": b"[]",
    "duplicate_key": b'{"task_id": "%s", "done": [], "done": ["preflight"], "halted": null}' % TASK.encode(),
    "other_task": control_record(task_id="OTHER-TASK"),
    "done_not_list": control_record(done="preflight"),
    "done_item_not_string": control_record(done=[1]),
    "done_item_uppercase": control_record(done=["PREFLIGHT"]),
    "done_item_with_space": control_record(done=["pre flight"]),
    "done_item_path": control_record(done=["../x"]),
    "done_too_long": control_record(done=["a"] * 41),
    "halted_not_string": control_record(halted=5),
    "halted_with_space": control_record(halted="focused FOCUSED"),
    "halted_with_newline": control_record(halted="focused\nS1 FAKE"),
    "halted_too_long": control_record(halted="a" * 121),
    "oversize_but_otherwise_valid": control_record(done=["preflight"]) + b" " * (1024 * 1024),
}


@pytest.mark.parametrize("name", sorted(UNTRUSTED_CONTROLS))
def test_untrusted_control_record_is_unreadable_never_none(env, name):
    repo, source = env
    target_of(repo).write_bytes(CONTENT)
    control_path(repo).write_bytes(UNTRUSTED_CONTROLS[name])
    assert existing_state(repo, source) == "S1 TARGET_EXISTS prompt=SAME control=UNREADABLE"


def test_control_that_is_a_directory_is_unreadable_never_none(env):
    repo, source = env
    target_of(repo).write_bytes(CONTENT)
    control_path(repo).mkdir()
    code, out = run(repo, source, sha(CONTENT))
    assert code == 6 and out.strip() == "S1 TARGET_EXISTS prompt=SAME control=UNREADABLE"
    assert control_path(repo).is_dir()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unsupported")
def test_control_that_is_a_symlink_is_unreadable_never_none(env, tmp_path):
    repo, source = env
    target_of(repo).write_bytes(CONTENT)
    real = tmp_path / "real-control.json"
    real.write_bytes(control_record(done=["preflight"]))
    try:
        os.symlink(real, control_path(repo))
    except OSError:
        pytest.skip("symlink not permitted")
    code, out = run(repo, source, sha(CONTENT))
    assert code == 6 and out.strip() == "S1 TARGET_EXISTS prompt=SAME control=UNREADABLE"


def test_hostile_control_content_is_never_echoed(env):
    repo, source = env
    target_of(repo).write_bytes(CONTENT)
    control_path(repo).write_bytes(control_record(done=["TOKEN_VALUE_SHOULD_NOT_ECHO"], halted="TOKEN VALUE SHOULD NOT ECHO"))
    code, out = run(repo, source, sha(CONTENT))
    assert code == 6 and "TOKEN" not in out and "ECHO" not in out
    control_path(repo).write_bytes(control_record(halted="TOKEN VALUE SHOULD NOT ECHO"))
    code, out = run(repo, source, sha(CONTENT))
    assert code == 6 and "TOKEN" not in out and "ECHO" not in out


def test_wrong_source_hash_is_still_reported_as_a_hash_mismatch_when_target_exists(env):
    repo, source = env
    target_of(repo).write_bytes(CONTENT)
    code, out = run(repo, source, sha(b"other"))
    assert code == 5 and "SOURCE_HASH_MISMATCH" in out and "TARGET_EXISTS" not in out


def test_describe_failure_still_exits_6_with_an_unknown_description(env, monkeypatch):
    repo, source = env
    sys.path.insert(0, os.path.dirname(TOOL))
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(TOOL), "..")))
    import prompt_intake  # noqa: E402
    target_of(repo).write_bytes(CONTENT)

    def boom(*_args, **_kwargs):
        raise RuntimeError("probe failure")

    monkeypatch.setattr(prompt_intake, "_read_plain_file", boom)
    with pytest.raises(prompt_intake.IntakeError) as caught:
        prompt_intake.intake(TASK, str(source), sha(CONTENT), str(repo))
    assert caught.value.code == 6
    assert caught.value.label == "TARGET_EXISTS prompt=UNKNOWN control=UNKNOWN"


@pytest.mark.parametrize("error,expected", [
    (FileNotFoundError, "control=NONE"),
    (PermissionError, "control=UNREADABLE"),
    (NotADirectoryError, "control=UNREADABLE"),
    (OSError, "control=UNREADABLE"),
], ids=["not-found-is-none", "permission-is-unreadable", "not-a-directory-is-unreadable", "other-oserror-is-unreadable"])
def test_control_lstat_error_other_than_not_found_is_unreadable_never_none(env, monkeypatch, error, expected):
    """Only a lstat that reports 'does not exist' may print NONE; a failed query must never read as 'not started'."""
    repo, source = env
    sys.path.insert(0, os.path.dirname(TOOL))
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(TOOL), "..")))
    import prompt_intake  # noqa: E402
    target_of(repo).write_bytes(CONTENT)
    control = os.path.abspath(str(control_path(repo)))
    real_lstat = os.lstat

    def lstat(path, *args, **kwargs):
        if os.path.abspath(str(path)) == control:
            raise error("injected")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(prompt_intake.os, "lstat", lstat)
    with pytest.raises(prompt_intake.IntakeError) as caught:
        prompt_intake.intake(TASK, str(source), sha(CONTENT), str(repo))
    assert caught.value.code == 6
    assert caught.value.label == "TARGET_EXISTS prompt=SAME " + expected


def test_exclusive_create_race_reports_the_existing_target_without_overwriting(env, monkeypatch):
    repo, source = env
    sys.path.insert(0, os.path.dirname(TOOL))
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(TOOL), "..")))
    import prompt_intake  # noqa: E402
    target = str(target_of(repo))
    real_lexists = os.path.lexists
    calls = {"hidden": 0}

    def lexists(path):
        if os.path.abspath(str(path)) == os.path.abspath(target) and calls["hidden"] == 0:
            calls["hidden"] += 1
            target_of(repo).write_bytes(CONTENT)  # the other conversation wins the race right here
            return False
        return real_lexists(path)

    monkeypatch.setattr(prompt_intake.os.path, "lexists", lexists)
    with pytest.raises(prompt_intake.IntakeError) as caught:
        prompt_intake.intake(TASK, str(source), sha(CONTENT), str(repo))
    assert caught.value.code == 6
    assert caught.value.label == "TARGET_EXISTS prompt=SAME control=NONE"
    assert target_of(repo).read_bytes() == CONTENT
