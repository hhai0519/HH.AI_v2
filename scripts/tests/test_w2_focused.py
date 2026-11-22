# -*- coding: utf-8 -*-
"""
scripts/tests/test_w2_focused.py

D9 batch 2 (TD-019): the optional production-spec flag "w2_focused": false.

The runner on the user's workstation skips the focused step for a flagged spec; native preview and the batch
simulator still rehearse it (rehearsal_spec); reply_check follows the runner's own step list. The flag is carried only
when the Base runner declares it in SPEC_FLAGS (verify_w2_focused_binding), so a Base that cannot honour the flag never
receives a spec that silently asks for it. Each rule has a positive control and at least one counter-example.
"""

import os
import sys

import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import batch_runner as br  # noqa: E402
import batch_sim  # noqa: E402
import gate_runner  # noqa: E402
import native_preview  # noqa: E402
import reply_check as rc  # noqa: E402
from test_batch_runner import BASE, TASK, halt_code, lines_of, production_blocks, production_spec, prompt  # noqa: E402

FOCUSED = {"pytest_args": ["-q", "scripts/tests/x.py"], "limit_sec": 900}
FULL = ["preflight", "setup", "e24", "apply", "focused", "generate", "precommit", "stage", "commit", "postcommit",
        "push"]
SKIPPED = [s for s in FULL if s != "focused"]


def load(**over):
    return br.load_spec(lines_of(prompt(production_blocks(production_spec(**over)))), TASK)


def base_blob(flags):
    return ("PRODUCTION_STEPS = ('preflight', 'setup')\n" + (flags + "\n" if flags is not None else "")).encode()


# --- runner_declares_spec_flag ------------------------------------------------------------------------------------

@pytest.mark.parametrize("flags,expected", [
    ("SPEC_FLAGS = ('w2_focused',)", True),
    ("SPEC_FLAGS = ('other', 'w2_focused')", True),
    ("SPEC_FLAGS = ('other',)", False),
    ("SPEC_FLAGS = ()", False),
    (None, False),  # an older runner without the constant declares nothing
])
def test_declares_flag_only_when_listed_in_a_literal_tuple(flags, expected):
    assert br.runner_declares_spec_flag(base_blob(flags), "w2_focused") is expected


@pytest.mark.parametrize("flags", ["SPEC_FLAGS = get_flags()", "SPEC_FLAGS = ['w2_focused']", "SPEC_FLAGS = (1,)"])
def test_non_literal_or_non_string_flag_declaration_is_refused(flags):
    assert halt_code(br.runner_declares_spec_flag, base_blob(flags), "w2_focused") == "SPEC_FLAGS_BASE_INVALID"


def test_unparsable_runner_source_is_refused_not_treated_as_older():
    assert halt_code(br.runner_declares_spec_flag, b"SPEC_FLAGS = (\n", "w2_focused") == "SPEC_FLAGS_BASE_INVALID"


def test_this_runner_declares_its_own_flag():
    src = open(os.path.join(SCRIPTS_DIR, "batch_runner.py"), "rb").read()
    assert br.runner_declares_spec_flag(src, "w2_focused") is True
    assert "w2_focused" in br.SPEC_FLAGS


# --- load_spec ----------------------------------------------------------------------------------------------------

def test_flag_false_with_a_focused_selection_is_accepted():
    assert load(focused=FOCUSED, w2_focused=False)["w2_focused"] is False


@pytest.mark.parametrize("value", [True, 0, "false", None, 1])
def test_any_flag_value_but_false_is_refused(value):
    with pytest.raises(br.Halt) as exc:
        load(focused=FOCUSED, w2_focused=value)
    assert str(exc.value) == "SPEC_W2_FOCUSED_INVALID"


def test_flag_without_a_focused_selection_is_refused():
    with pytest.raises(br.Halt) as exc:
        load(focused=None, w2_focused=False)
    assert str(exc.value) == "SPEC_W2_FOCUSED_INVALID"


@pytest.fixture(autouse=True)
def not_a_simulation(monkeypatch):
    """These tests describe the workstation runner; the simulator marker is set only where a test says so."""
    monkeypatch.delenv(br.SIM_ROOT_ENV, raising=False)


# --- derive_steps and rehearsal_spec ------------------------------------------------------------------------------

def test_flagged_spec_skips_only_the_focused_step():
    assert br.derive_steps(load(focused=FOCUSED, w2_focused=False)) == SKIPPED


def test_unflagged_spec_keeps_the_focused_step():
    assert br.derive_steps(load(focused=FOCUSED)) == FULL


def test_flag_does_not_change_other_optional_steps():
    spec = load(focused=FOCUSED, w2_focused=False, e24=False, bundle_output=True)
    assert br.derive_steps(spec) == ["preflight", "setup", "apply", "generate", "precommit", "stage", "commit",
                                     "postcommit", "push", "bundle"]


def test_rehearsal_spec_restores_the_focused_step_without_touching_the_original():
    spec = load(focused=FOCUSED, w2_focused=False)
    assert br.derive_steps(br.rehearsal_spec(spec)) == FULL
    assert spec["w2_focused"] is False and br.derive_steps(spec) == SKIPPED


def test_a_process_marked_as_a_simulation_keeps_the_focused_step(monkeypatch):
    monkeypatch.setenv(br.SIM_ROOT_ENV, "/tmp/sim")
    assert br.derive_steps(load(focused=FOCUSED, w2_focused=False)) == FULL


def test_an_empty_marker_is_still_a_marker_and_no_marker_means_workstation(monkeypatch):
    monkeypatch.setenv(br.SIM_ROOT_ENV, "")
    assert br.derive_steps(load(focused=FOCUSED, w2_focused=False)) == FULL
    monkeypatch.delenv(br.SIM_ROOT_ENV)
    assert br.derive_steps(load(focused=FOCUSED, w2_focused=False)) == SKIPPED


def test_every_tool_that_recognises_a_simulation_uses_the_same_variable():
    assert br.SIM_ROOT_ENV == gate_runner.PREVIEW_ROOT_ENV == native_preview.SIM_ROOT == "HHAI_BATCH_SIM_ROOT"


def test_the_simulator_marks_every_process_it_starts(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    sim = batch_sim.Sim(str(src), str(tmp_path / "wd"), "utf8", out=lambda line: None)
    assert sim.env[br.SIM_ROOT_ENV] == str(sim.workdir)


def test_batch_simulator_rehearses_focused_for_a_flagged_spec():
    spec = load(focused=FOCUSED, w2_focused=False)
    assert "focused" in batch_sim.production_steps(spec)
    assert "focused" not in br.derive_steps(spec)


def test_batch_simulator_steps_match_the_runner_for_an_unflagged_spec():
    spec = load(focused=FOCUSED)
    assert list(batch_sim.production_steps(spec)) == br.derive_steps(spec)[:-1]


# --- Base binding -------------------------------------------------------------------------------------------------

@pytest.fixture
def declaring(monkeypatch):
    monkeypatch.setattr(br, "git_bytes", lambda root, *a: base_blob("SPEC_FLAGS = ('w2_focused',)"))


@pytest.fixture
def older(monkeypatch):
    monkeypatch.setattr(br, "git_bytes", lambda root, *a: base_blob(None))


def test_declaring_base_requires_the_flag_when_there_is_a_focused_selection(declaring):
    assert br.w2_focused_required(".", {"focused": FOCUSED, "base_oid": BASE}) is True
    br.verify_w2_focused_binding(".", load(focused=FOCUSED, w2_focused=False))
    assert halt_code(br.verify_w2_focused_binding, ".", load(focused=FOCUSED)) == "W2_FOCUSED_SPEC_MISMATCH"


def test_declaring_base_without_a_focused_selection_needs_no_flag(declaring):
    br.verify_w2_focused_binding(".", load(focused=None))


def test_older_base_refuses_a_flagged_spec(older):
    assert br.w2_focused_required(".", {"focused": FOCUSED, "base_oid": BASE}) is False
    assert halt_code(br.verify_w2_focused_binding, ".", load(focused=FOCUSED, w2_focused=False)) == \
        "W2_FOCUSED_SPEC_MISMATCH"


def test_older_base_accepts_an_unflagged_spec(older):
    br.verify_w2_focused_binding(".", load(focused=FOCUSED))


# --- reply_check follows the runner's step list -------------------------------------------------------------------

TASK_R = "B119-G1-Q1-DELIVERY-PACK-R2-261024"
BASE_R = "8320b0d4dc385c5ea1ffe367eea8ce0e46428ceb"
CAND_R = "1d9f22e041df181e9f4805223b8838ab65952af5"
BRANCH_R = "batch/b119-g1-q1-delivery-pack-r2-261024"


def reply(done):
    return "\n".join([
        "CI_RUN phase=candidate run_id=40107662314 attempt=1 event=push branch=" + BRANCH_R + " head_sha=" + CAND_R
        + " verify=success gateway-windows=success",
        "COMMIT " + CAND_R + " | CI PASS | S1 NONE",
        "TIMING start=2026-10-24T23:07:19.063264+08:00 end=2026-10-24T23:39:48.359859+08:00 elapsed_sec=1949.3 "
        "elapsed_min=32",
        "STATE done=" + ",".join(done) + " halted=None",
        "以上是 Antigravity IDE Agent 的回覆。", ""])


def spec_r(**over):
    spec = {"kind": "production", "base_oid": BASE_R, "branch": BRANCH_R, "e24": True, "focused": FOCUSED}
    spec.update(over)
    return spec


def test_reply_for_a_flagged_spec_has_no_focused_step():
    done = [s for s in SKIPPED]
    assert rc.check_spec(TASK_R, spec_r(w2_focused=False), reply(done))[3] == "N/A"


def test_reply_for_a_flagged_spec_that_still_lists_focused_fails():
    with pytest.raises(rc.CheckError):
        rc.check_spec(TASK_R, spec_r(w2_focused=False), reply(FULL))


def test_reply_for_an_unflagged_spec_without_focused_fails():
    with pytest.raises(rc.CheckError):
        rc.check_spec(TASK_R, spec_r(), reply(SKIPPED))


def test_reply_for_an_unflagged_spec_with_focused_passes():
    assert rc.check_spec(TASK_R, spec_r(), reply(FULL))[3] == "N/A"


# --- the control state machine follows the same list --------------------------------------------------------------

def control_after(done):
    return {"task_id": TASK, "prompt_sha256": "p", "runner_sha256": "r", "done": list(done), "halted": None}


def test_workstation_run_goes_from_apply_straight_to_generate():
    steps = br.derive_steps(load(focused=FOCUSED, w2_focused=False))
    assert br.check_control(control_after(["preflight", "setup", "e24", "apply"]), TASK, "p", "r", steps, "generate") == "OK"


def test_workstation_run_refuses_a_focused_step_it_does_not_have():
    steps = br.derive_steps(load(focused=FOCUSED, w2_focused=False))
    assert halt_code(br.check_control, control_after(["preflight", "setup", "e24", "apply"]), TASK, "p", "r", steps,
                     "focused") == "STEP_ORDER_VIOLATION"


def test_simulated_run_still_needs_focused_before_generate(monkeypatch):
    monkeypatch.setenv(br.SIM_ROOT_ENV, "/tmp/sim")
    steps = br.derive_steps(load(focused=FOCUSED, w2_focused=False))
    done = ["preflight", "setup", "e24", "apply"]
    assert halt_code(br.check_control, control_after(done), TASK, "p", "r", steps, "generate") == "STEP_ORDER_VIOLATION"
    assert br.check_control(control_after(done + ["focused"]), TASK, "p", "r", steps, "generate") == "OK"
