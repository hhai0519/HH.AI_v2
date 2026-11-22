"""Alpha batch 1 (D2, TD-100, TD-112) in the runner: what Batch.bounded and the S1 path print.

Commitment -> test table (E27 (a)):
  P1 a persisted S1 inside a step prints one S1_FAILED_LIST (and its items) right after the S1 line, for a Halt and for an
     unexpected exception; a secondary control-save failure and a stop before the step print none
                                                                              test_s1_*
  P2 CI_FAILED reads the jobs object of the ci-status payload the runner kept; names are validated
                                                                              test_ci_*
  P3 a gate stage prints the grouped result lines after BOUNDED_EXIT, before the Halt, for pass and fail; STAGED and
     POSTCOMMIT print none                                                    test_bounded_groups_*
  P4 a gate that timed out (inner code 86 or the outer limit) also prints the progress lines; a plain failure does not;
     a non-gate stage never reads gate records                                test_bounded_progress_*
  P5 whatever the runner prints in each of these cases passes the reply checker (runner and checker agree)
                                                                              test_*_accepted_by_reply_check
  P6 a failure while building the lines never replaces the S1 (prints the unavailable form)  test_s1_list_error_*
"""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import batch_runner as br  # noqa: E402
import bounded_process  # noqa: E402
import gate_report as gr  # noqa: E402
import reply_check as rc  # noqa: E402

TASK = 'B117-ALPHA-RUNNER-261122'
BASE = '9cb34eb306e71c8f4f93538d3bc7ab462e45e205'
SPEC = {'kind': 'production', 'base_oid': BASE, 'branch': 'batch/b117-alpha-runner-261122', 'e24': True,
        'focused': {'pytest_args': ['x'], 'limit_sec': 900}, 'bundle_output': False}
STEPS = br.derive_steps(SPEC)
SUMMARY = ('=========================== short test summary info ============================\n'
           'FAILED scripts/tests/test_a.py::test_one - assert 1 == 2\nERROR scripts/tests/test_b.py::test_two\n'
           '=== 1 failed, 1 error, 5 passed in 1.2s ===\n')
GROUPS = {'schema_version': 1, 'status': 'FAIL', 'collected': 12, 'counted': 12, 'passed': 9, 'skipped': 1, 'failures': 1,
          'errors': 1, 'phase1_sec': 3.0, 'groups_sec': 4.0, 'total_sec': 8.0, 'reasons': ['g1:FAILED_TESTS', 'g1:EXIT_1'],
          'groups': [{'name': 'seq', 'rc': 0, 'sec': 3.0, 'files': 2, 'tests': 4},
                     {'name': 'g1', 'rc': 1, 'sec': 4.0, 'files': 3, 'tests': 8}]}


def make_batch(tmp_path, monkeypatch):
    batch = br.Batch.__new__(br.Batch)
    batch.root, batch.task_id = str(tmp_path), TASK
    batch.ci_jobs = None
    monkeypatch.setattr(batch, 'artifact', lambda suffix: suffix)
    return batch


def raw(tmp_path, stage, gate, text, run=1):
    git = tmp_path / '.git'
    git.mkdir(exist_ok=True)
    path = git / ('%s-local-gates.txt.%s-run%d-gate%d.raw' % (TASK, stage.lower(), run, gate))
    path.write_text(text, encoding='utf-8', newline='\n')
    return path


def fake_run(code, timed_out=False, stdout=b'GATE_RUNNER FAIL stage=PRECOMMIT\n'):
    def fake(*args, **kw):
        Path(kw['capture_path']).write_bytes(stdout)
        return bounded_process.BoundedResult(None if timed_out else code, timed_out, None, stdout, b'', 'TREE_SIGNALLED' if timed_out else 'NOT_NEEDED')
    return fake


def lines_of(capsys):
    return [l for l in capsys.readouterr().out.split('\n') if l]


# ---- P3 / P4 ------------------------------------------------------------------------------------------------------
def test_bounded_groups_lines_follow_bounded_exit_and_precede_the_halt(tmp_path, monkeypatch, capsys):
    r = raw(tmp_path, 'PRECOMMIT', 4, 'x\n')
    Path(str(r) + gr.GROUPS_SUFFIX).write_text(json.dumps(GROUPS), encoding='utf-8', newline='\n')
    monkeypatch.setattr(br, 'run_bounded', fake_run(1))
    batch = make_batch(tmp_path, monkeypatch)
    with pytest.raises(br.Halt, match='PRECOMMIT_NONZERO'):
        batch.bounded('PRECOMMIT', ['-c', 'pass'], 50, gate_timeout=True)
    out = lines_of(capsys)
    assert out[0] == 'BOUNDED_EXIT PRECOMMIT code=1 | GATE_RUNNER FAIL stage=PRECOMMIT'
    assert [l.split(' ')[0] for l in out[1:]] == ['GATE4_GROUPS_RESULT', 'GATE4_GROUP', 'GATE4_GROUP']
    assert out[1].startswith('GATE4_GROUPS_RESULT status=FAIL collected=12 counted=12 passed=9 skipped=1 failures=1 errors=1')


def test_bounded_groups_lines_are_printed_for_a_passing_gate_too(tmp_path, monkeypatch, capsys):
    ok = dict(GROUPS, status='PASS', passed=11, failures=0, errors=0, reasons=[])
    ok['groups'] = [dict(ok['groups'][0]), dict(ok['groups'][1], rc=0)]
    r = raw(tmp_path, 'PRECOMMIT', 4, 'x\n')
    Path(str(r) + gr.GROUPS_SUFFIX).write_text(json.dumps(ok), encoding='utf-8', newline='\n')
    monkeypatch.setattr(br, 'run_bounded', fake_run(0, stdout=b'GATE_RUNNER PASS stage=PRECOMMIT\n'))
    make_batch(tmp_path, monkeypatch).bounded('PRECOMMIT', ['-c', 'pass'], 50, gate_timeout=True)
    out = lines_of(capsys)
    assert out[0].startswith('BOUNDED_EXIT PRECOMMIT code=0') and out[1].startswith('GATE4_GROUPS_RESULT status=PASS')


@pytest.mark.parametrize('stage', ['STAGED', 'POSTCOMMIT'])
def test_bounded_groups_lines_only_for_precommit(tmp_path, monkeypatch, capsys, stage):
    r = raw(tmp_path, stage, 4, 'x\n')
    Path(str(r) + gr.GROUPS_SUFFIX).write_text(json.dumps(GROUPS), encoding='utf-8', newline='\n')
    monkeypatch.setattr(br, 'run_bounded', fake_run(0, stdout=b'GATE_RUNNER PASS stage=' + stage.encode() + b'\n'))
    make_batch(tmp_path, monkeypatch).bounded(stage, ['-c', 'pass'], 50, gate_timeout=True)
    assert len(lines_of(capsys)) == 1


def put_progress(tmp_path):
    r = raw(tmp_path, 'PRECOMMIT', 4, 'x\n')
    Path(str(r) + gr.PROGRESS_INFIX + 'aaa.json').write_text(json.dumps(
        {'schema_version': 1, 'completed': 812, 'running': 'scripts/tests/test_x.py::test_slow', 'last': 'scripts/tests/test_x.py::test_prev'}),
        encoding='utf-8', newline='\n')


def test_bounded_progress_lines_after_the_gate_timeout_code(tmp_path, monkeypatch, capsys):
    put_progress(tmp_path)
    monkeypatch.setattr(br, 'run_bounded', fake_run(br.GATE_TIMEOUT_EXIT_CODE))
    with pytest.raises(br.Halt, match='PRECOMMIT_GATE_TIMEOUT'):
        make_batch(tmp_path, monkeypatch).bounded('PRECOMMIT', ['-c', 'pass'], 50, gate_timeout=True)
    out = lines_of(capsys)
    assert out[1:] == ['GATE_PROGRESS stage=PRECOMMIT run=1 gate=4 procs=1 completed=812',
                       'GATE_PROGRESS_PROC idx=1 completed=812 running=scripts/tests/test_x.py::test_slow last=scripts/tests/test_x.py::test_prev']


def test_bounded_progress_lines_after_the_outer_limit(tmp_path, monkeypatch, capsys):
    put_progress(tmp_path)
    monkeypatch.setattr(br, 'run_bounded', fake_run(None, timed_out=True))
    with pytest.raises(br.Halt, match='PRECOMMIT_TIMEOUT'):
        make_batch(tmp_path, monkeypatch).bounded('PRECOMMIT', ['-c', 'pass'], 50, gate_timeout=True)
    out = lines_of(capsys)
    assert out[0].startswith('BOUNDED_TIMEOUT PRECOMMIT limit=50s') and out[1].startswith('GATE_PROGRESS stage=PRECOMMIT')


def test_bounded_progress_lines_not_printed_for_a_plain_failure_or_a_non_gate_stage(tmp_path, monkeypatch, capsys):
    put_progress(tmp_path)
    monkeypatch.setattr(br, 'run_bounded', fake_run(1))
    with pytest.raises(br.Halt, match='PRECOMMIT_NONZERO'):
        make_batch(tmp_path, monkeypatch).bounded('PRECOMMIT', ['-c', 'pass'], 50, gate_timeout=True)
    assert len(lines_of(capsys)) == 1
    monkeypatch.setattr(br, 'run_bounded', fake_run(br.GATE_TIMEOUT_EXIT_CODE))
    folder = tmp_path / 'f'
    folder.mkdir()
    put_progress(folder)
    with pytest.raises(br.Halt, match='FOCUSED_NONZERO'):
        make_batch(folder, monkeypatch).bounded('FOCUSED', ['-c', 'pass'], 50)
    assert [l.split(' ')[0] for l in lines_of(capsys)] == ['BOUNDED_EXIT']


# ---- P1 / P2 / P6 ------------------------------------------------------------------------------------------------
class StubBatch:
    """A batch whose step raises what the test says; control saving and S1 evidence are replaced by recorders."""

    def __init__(self, root, error, ci_jobs=None):
        self.root, self.task_id, self.ci_jobs = root, TASK, ci_jobs
        self.error = error

    def step_precommit(self):
        raise self.error

    step_push = step_native_preview = step_setup = step_precommit


@pytest.fixture
def quiet_s1(monkeypatch):
    monkeypatch.setattr(br, 'save_control', lambda batch, control: None)
    monkeypatch.setattr(br, 'report_s1_metadata', lambda *a: print('S1_EVIDENCE_STATUS=UNAVAILABLE'))
    monkeypatch.setattr(br, 'report_s1_full_capture', lambda *a: print('S1_FULL_CAPTURE_STATUS=UNAVAILABLE'))


def run_step(batch, step, capsys):
    control = {'task_id': TASK, 'done': STEPS[:STEPS.index(step)], 'halted': None}
    assert br._execute_step(batch, step, control) == 1
    return lines_of(capsys), control


def test_s1_failed_names_are_listed_right_after_the_s1_line(tmp_path, quiet_s1, capsys):
    raw(tmp_path, 'PRECOMMIT', 4, 'output\n' + SUMMARY)
    out, control = run_step(StubBatch(str(tmp_path), br.Halt('PRECOMMIT_NONZERO')), 'precommit', capsys)
    assert out[:4] == ['S1 PRECOMMIT_NONZERO | step precommit', 'S1_FAILED_LIST kind=GATE_FAILED count=2 shown=2',
                       'S1_FAILED_ITEM scripts/tests/test_a.py::test_one', 'S1_FAILED_ITEM scripts/tests/test_b.py::test_two']
    assert out[4] == 'S1_EVIDENCE_STATUS=UNAVAILABLE' and control['halted'] == 'precommit:PRECOMMIT_NONZERO'


def test_s1_failed_rows_with_unsafe_parameter_ids_are_counted_and_listed_reduced(tmp_path, quiet_s1, capsys):
    # D-SO B1: parametrized ids with spaces are reduced, every row is counted, and the reply still passes the checker.
    rows = ['FAILED scripts/tests/test_a.py::test_p[item count below shown] - x', 'FAILED scripts/tests/test_a.py::test_p[C:\\\\p] - x',
            'FAILED x y.py::t - x']
    raw(tmp_path, 'PRECOMMIT', 4, '=== short test summary info ===\n' + '\n'.join(rows) + '\n=== 3 failed in 1s ===\n')
    out, _ = run_step(StubBatch(str(tmp_path), br.Halt('PRECOMMIT_NONZERO')), 'precommit', capsys)
    assert out[:3] == ['S1 PRECOMMIT_NONZERO | step precommit', 'S1_FAILED_LIST kind=GATE_FAILED count=3 shown=1 unsafe=1',
                       'S1_FAILED_ITEM scripts/tests/test_a.py::test_p[*]']


def test_s1_detail_stays_before_the_list(tmp_path, quiet_s1, capsys):
    out, _ = run_step(StubBatch(str(tmp_path), br.Halt('PRECOMMIT_NONZERO', 'exit=1 class=DETAIL_UNAVAILABLE')), 'precommit', capsys)
    assert out[:3] == ['S1 PRECOMMIT_NONZERO | step precommit', 'S1_DETAIL exit=1 class=DETAIL_UNAVAILABLE',
                       'S1_FAILED_LIST kind=FAILED_LIST_UNAVAILABLE reason=NO_RAW_OUTPUT']


def test_s1_unexpected_exception_also_prints_the_list(tmp_path, quiet_s1, capsys):
    out, control = run_step(StubBatch(str(tmp_path), RuntimeError('boom')), 'precommit', capsys)
    assert out[:2] == ['S1 UNEXPECTED_RuntimeError | step precommit', 'S1_FAILED_LIST kind=FAILED_LIST_UNAVAILABLE reason=NO_RAW_OUTPUT']
    assert control['halted'] == 'precommit:UNEXPECTED_RuntimeError'


def test_s1_non_test_step_prints_the_not_a_test_step_form(tmp_path, quiet_s1, capsys):
    out, _ = run_step(StubBatch(str(tmp_path), br.Halt('SETUP_DIRTY')), 'setup', capsys)
    assert out[:2] == ['S1 SETUP_DIRTY | step setup', 'S1_FAILED_LIST kind=FAILED_LIST_UNAVAILABLE reason=NOT_A_TEST_STEP']


def test_s1_secondary_control_save_failure_prints_no_list(tmp_path, monkeypatch, capsys):
    def failing_save(batch, control):
        raise br.Halt('CONTROL_SAVE_FAILED')
    monkeypatch.setattr(br, 'save_control', failing_save)
    control = {'task_id': TASK, 'done': STEPS[:STEPS.index('precommit')], 'halted': None}
    assert br._execute_step(StubBatch(str(tmp_path), br.Halt('PRECOMMIT_NONZERO')), 'precommit', control) == 1
    out = lines_of(capsys)
    assert out == ['S1 CONTROL_SAVE_FAILED | step precommit', 'S1_PRIMARY PRECOMMIT_NONZERO | step precommit']


def test_s1_list_error_never_replaces_the_s1(tmp_path, quiet_s1, monkeypatch, capsys):
    def boom(*a, **kw):
        raise RuntimeError('x')
    monkeypatch.setattr(br.gate_report, 'failed_list_lines', boom)
    out, control = run_step(StubBatch(str(tmp_path), br.Halt('PRECOMMIT_NONZERO')), 'precommit', capsys)
    assert out[:2] == ['S1 PRECOMMIT_NONZERO | step precommit', 'S1_FAILED_LIST kind=FAILED_LIST_UNAVAILABLE reason=LIST_ERROR']
    assert control['halted'] == 'precommit:PRECOMMIT_NONZERO'


def test_ci_failed_jobs_come_from_the_batch_ci_jobs(tmp_path, quiet_s1, capsys):
    jobs = {'verify': {'status': 'completed', 'conclusion': 'success'},
            'gateway-windows': {'status': 'completed', 'conclusion': 'failure'}}
    out, _ = run_step(StubBatch(str(tmp_path), br.Halt('CANDIDATE_CI_NOT_PASS'), jobs), 'push', capsys)
    assert out[:3] == ['S1 CANDIDATE_CI_NOT_PASS | step push', 'S1_FAILED_LIST kind=CI_FAILED count=1 shown=1',
                       'S1_FAILED_ITEM job=gateway-windows conclusion=failure']


def test_ci_status_keeps_the_jobs_object_of_a_payload_that_did_not_pass(tmp_path, monkeypatch):
    payload = {'tool': 'verification_primitives', 'command': 'ci-status', 'head_sha': 'a' * 40, 'branch': 'batch/x', 'event': 'push',
               'repo': br.REPO, 'workflow_name': 'Verify', 'required_jobs': ['verify', 'gateway-windows'], 'status': 'CANDIDATE_INVALID',
               'jobs': {'verify': {'status': 'completed', 'conclusion': 'failure'}, 'gateway-windows': None}}
    cp = SimpleNamespace(returncode=1, stdout=json.dumps(payload).encode(), stderr=b'')
    monkeypatch.setattr(br.subprocess, 'run', lambda *a, **kw: cp)
    batch = make_batch(tmp_path, monkeypatch)
    assert batch.ci_status('a' * 40, 'batch/x', 1, 1, 'candidate') == (1, None)
    assert batch.ci_jobs == payload['jobs']


# ---- P5 -----------------------------------------------------------------------------------------------------------
def s1_text(step, code, middle, halted=None):
    halted = halted or (step + ':' + code)
    return '\n'.join(['S1 ' + code + ' | step ' + step] + middle + [
        'S1_EVIDENCE_STATUS=UNAVAILABLE', 'S1_FULL_CAPTURE_STATUS=UNAVAILABLE',
        'TIMING start=2026-11-22T10:00:00+08:00 end=2026-11-22T10:01:00+08:00 elapsed_sec=60.0 elapsed_min=1',
        'STATE done=' + ','.join(STEPS[:STEPS.index(step)]) + ' halted=' + halted]) + '\n'


def test_s1_lines_printed_by_the_runner_are_accepted_by_the_reply_check(tmp_path, quiet_s1, capsys):
    raw(tmp_path, 'PRECOMMIT', 4, SUMMARY)
    out, _ = run_step(StubBatch(str(tmp_path), br.Halt('PRECOMMIT_NONZERO')), 'precommit', capsys)
    middle = [l for l in out if l.startswith('S1_FAILED_')]
    text = s1_text('precommit', 'PRECOMMIT_NONZERO', middle)
    assert rc.check_spec(TASK, SPEC, text)[2] == 'S1 precommit:PRECOMMIT_NONZERO'


def test_bounded_lines_printed_by_the_runner_are_accepted_by_the_reply_check(tmp_path, monkeypatch, capsys):
    r = raw(tmp_path, 'PRECOMMIT', 4, 'x\n')
    Path(str(r) + gr.GROUPS_SUFFIX).write_text(json.dumps(GROUPS), encoding='utf-8', newline='\n')
    Path(str(r) + gr.PROGRESS_INFIX + 'aaa.json').write_text(json.dumps(
        {'schema_version': 1, 'completed': 12, 'running': None, 'last': 'scripts/tests/test_x.py::test_prev'}), encoding='utf-8', newline='\n')
    monkeypatch.setattr(br, 'run_bounded', fake_run(br.GATE_TIMEOUT_EXIT_CODE))
    with pytest.raises(br.Halt):
        make_batch(tmp_path, monkeypatch).bounded('PRECOMMIT', ['-c', 'pass'], 50, gate_timeout=True)
    out = [l for l in lines_of(capsys)]
    text = s1_text('precommit', 'PRECOMMIT_GATE_TIMEOUT', out + ['S1_FAILED_LIST kind=FAILED_LIST_UNAVAILABLE reason=NO_NAMES_FOUND'])
    assert rc.check_spec(TASK, SPEC, text)[2] == 'S1 precommit:PRECOMMIT_GATE_TIMEOUT'
