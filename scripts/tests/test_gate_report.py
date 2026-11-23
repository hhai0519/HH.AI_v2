"""Alpha batch 1 (D2, TD-100, TD-104, TD-112): the fixed-shape diagnostic lines of scripts/gate_report.py.

Commitment -> test table (E27 (a); counterexamples in the last column of each row are the tests named after it):
  R1 failed names come only from pytest "short test summary info" sections (several in grouped output), in order,
     without duplicates; text outside a section never adds a name           test_parse_*
  R2 a name that is not a safe node id is listed only in its reduced form (the part before the first "[" plus the fixed
     mark "[*]") when that part is safe; otherwise it is counted in unsafe and never listed; every FAILED/ERROR row is
     counted                                                                  test_parse_unsafe_*, test_parse_an_unsafe_*
  R3 a persisted S1 gets exactly one list: GATE_FAILED with names (at most 20 shown, total counted), CI_FAILED with
     failed jobs, or FAILED_LIST_UNAVAILABLE with a fixed reason              test_list_*
  R4 only the highest run of the stage is read; a source that cannot be read gives the unavailable form
                                                                              test_list_highest_run_*, test_list_no_raw_*
  R5 an internal error never raises: it gives reason LIST_ERROR              test_list_error_*
  R6 the grouped gate 4 result and group lines are built only from a record of the exact schema, types and
     vocabulary; anything else gives no line                                  test_groups_*
  R7 timeout progress is built only from valid progress records of the highest gate that has any; at most 8 processes
                                                                              test_progress_*
  R8 the plugin writes the progress record while pytest runs, so a killed run still says what was running and how
     many tests had finished (real process)                                   test_plugin_progress_*
  R9 an end-to-end run of the real gate runner leaves a raw sidecar from which the failed names are listed (real
     process, real pytest output)                                             test_end_to_end_*
  R10 the module constants, the gate4_groups record suffix and the plugin file name agree  test_constants_*
  R11 (D-SO B1, N1, O6) count = rows, never NO_NAMES_FOUND while rows exist, progress keeps a record whose test name
     cannot be shown (the word withheld), the progress file has no stale tail, a classname is not mapped to a file
     whose stem is its prefix, and the count of a real grouped run equals its failures plus errors
                                                                              test_list_every_*, test_progress_*, test_end_to_end_grouped_*
  R12 (S1C-024) a name never carries a backslash (Windows summary rows are normalized); the Windows-form literal
     cases are in scripts/tests/test_gate_report_windows_form.py           test_end_to_end_*, test_gate_report_windows_form.py
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
REPO_ROOT = os.path.dirname(SCRIPTS_DIR)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import gate4_groups  # noqa: E402
import gate_durations  # noqa: E402
import gate_report as gr  # noqa: E402
import gate_runner  # noqa: E402

TASK = 'B117-ALPHA-FIXTURE-261122'


def section(*rows, header='=========================== short test summary info ============================'):
    return '\n'.join([header] + list(rows) + ['=== %d failed, 5 passed in 1.2s ===' % len(rows)]) + '\n'


def put_raw(root, stage, run, gate, text, task=TASK):
    git = Path(root) / '.git'
    git.mkdir(exist_ok=True)
    path = git / ('%s-local-gates.txt.%s-run%d-gate%d.raw' % (task, stage.lower(), run, gate))
    path.write_text(text, encoding='utf-8', newline='\n')
    return path


# ---- R1 / R2 ------------------------------------------------------------------------------------------------------
def test_parse_reads_failed_and_error_rows_of_one_section_in_order():
    text = 'noise\n' + section('FAILED scripts/tests/test_b.py::test_two - assert 1 == 2',
                              'ERROR scripts/tests/test_a.py::test_one', 'FAILED scripts/tests/test_c.py::test_p[a-1]')
    assert gr.parse_failed_ids(text) == (['scripts/tests/test_b.py::test_two', 'scripts/tests/test_a.py::test_one',
                                          'scripts/tests/test_c.py::test_p[a-1]'], 0)


def test_parse_reads_every_section_of_grouped_output_and_drops_duplicates():
    text = ('GATE4_GROUP name=seq rc=1 sec=3.0 files=1 tests=2\n'
            + section('FAILED scripts/tests/test_a.py::t1') + 'GATE4_GROUP name=g1 rc=1 sec=4.0 files=2 tests=9\n'
            + section('FAILED scripts/tests/test_b.py::t2', 'FAILED scripts/tests/test_a.py::t1')
            + 'GATE4_GROUPS_RESULT status=FAIL collected=11 counted=11 passed=9 skipped=0 failures=2 errors=0\n')
    assert gr.parse_failed_ids(text)[0] == ['scripts/tests/test_a.py::t1', 'scripts/tests/test_b.py::t2']


def test_parse_ignores_matching_lines_outside_a_section_and_the_gate_summary_line():
    text = ('FAILED scripts/tests/test_spoof.py::t0\nERROR scripts/tests/test_spoof.py::t0\n'
            'FAILED gates (1): unit_tests\n' + section('FAILED scripts/tests/test_real.py::t1')
            + 'FAILED scripts/tests/test_after.py::t9\n')
    assert gr.parse_failed_ids(text)[0] == ['scripts/tests/test_real.py::t1']


def test_parse_section_ends_at_the_first_line_that_is_not_a_result_row():
    text = section('FAILED scripts/tests/test_a.py::t1').replace('=== 1 failed', 'FAILED scripts/tests/test_late.py::t2\n=== 1 failed')
    assert gr.parse_failed_ids(text)[0] == ['scripts/tests/test_a.py::t1', 'scripts/tests/test_late.py::t2']
    broken = 'x\n=== short test summary info ===\nFAILED scripts/tests/test_a.py::t1\n\nFAILED scripts/tests/test_late.py::t2\n'
    assert gr.parse_failed_ids(broken)[0] == ['scripts/tests/test_a.py::t1']


def test_parse_accepts_crlf_and_file_level_collection_errors():
    text = section('ERROR scripts/tests/test_broken.py - ImportError: x', 'FAILED scripts/tests/test_a.py::t1').replace('\n', '\r\n')
    assert gr.parse_failed_ids(text)[0] == ['scripts/tests/test_broken.py', 'scripts/tests/test_a.py::t1']


@pytest.mark.parametrize('token', ['scripts/tests/test_a.py::t]', 'x y.py::t', '../../etc/passwd',
                                   'scripts/tests/test_a.py::' + 'x' * 400, 'scripts/tests/test_a.py::t;rm', 'a.txt::t',
                                   'scripts/tests/test_a.py::t`id`', 'scripts/tests/test_a.py::t$HOME',
                                   'scripts/tests/test_a.py::t;rm[x y]', 'x y.py::t[1]'])
def test_parse_unsafe_names_are_counted_and_never_listed(token):
    ids, unsafe = gr.parse_failed_ids(section('FAILED ' + token, 'FAILED scripts/tests/test_ok.py::t1'))
    assert ids == ['scripts/tests/test_ok.py::t1'] and unsafe == 1


@pytest.mark.parametrize('token,shown', [
    ('scripts/tests/test_a.py::t[a', 'scripts/tests/test_a.py::t[*]'),
    ('scripts/tests/test_a.py::test_param[item count below shown]', 'scripts/tests/test_a.py::test_param[*]'),
    ('scripts/tests/test_a.py::test_param[C:\\\\path\\\\x]', 'scripts/tests/test_a.py::test_param[*]'),
    ('scripts/tests/test_a.py::test_lambda[<lambda>]', 'scripts/tests/test_a.py::test_lambda[*]'),
    ('scripts/tests/test_a.py::TestX::test_y[a b-\\u00e9]', 'scripts/tests/test_a.py::TestX::test_y[*]'),
    ('scripts/tests/test_a.py::test_ok[safe-1]', 'scripts/tests/test_a.py::test_ok[safe-1]')])
def test_parse_an_unsafe_parametrized_id_is_listed_in_its_reduced_form_with_the_fixed_mark(token, shown):
    # B1 (alpha 1 D-SO): 19% of the real test tree has parameter ids with spaces, escapes or <>; they are shown reduced.
    assert gr.parse_failed_rows(section('FAILED ' + token + ' - AssertionError: x')) == ([shown], 0, 1)


def test_parse_counts_every_failed_or_error_row_and_lists_each_reduced_name_once():
    rows = ['FAILED scripts/tests/test_a.py::p[a b] - x', 'FAILED scripts/tests/test_a.py::p[c d] - x', 'ERROR scripts/tests/test_a.py::q[z z]',
            'FAILED scripts/tests/test_a.py::ok', 'FAILED scripts/tests/test_a.py::ok', 'FAILED x y.py::t']
    items, unsafe, count = gr.parse_failed_rows(section(*rows))
    assert items == ['scripts/tests/test_a.py::p[*]', 'scripts/tests/test_a.py::q[*]', 'scripts/tests/test_a.py::ok']
    assert (unsafe, count) == (1, 6)


def test_display_id_forms():
    assert gr.display_id('scripts/tests/test_a.py::t') == 'scripts/tests/test_a.py::t'
    assert gr.display_id('scripts/tests/test_a.py::t[a b]') == 'scripts/tests/test_a.py::t[*]'
    for bad in (None, 3, '', '[x]', 'a b.py::t[x]', 'scripts/tests/test_a.py::' + 'x' * 400 + '[1 2]', 'scripts/tests/test_a.py::t;x[1 2]'):
        assert gr.display_id(bad) is None


# ---- R3 / R4 / R5 -------------------------------------------------------------------------------------------------
def test_list_gate_failed_names_come_from_the_stage_raw_sidecars(tmp_path):
    put_raw(tmp_path, 'PRECOMMIT', 1, 1, 'gate one output\n')
    put_raw(tmp_path, 'PRECOMMIT', 1, 4, 'output\n' + section('FAILED scripts/tests/test_a.py::t1', 'ERROR scripts/tests/test_b.py::t2'))
    assert gr.failed_list_lines(str(tmp_path), TASK, 'precommit', 'PRECOMMIT_NONZERO') == [
        'S1_FAILED_LIST kind=GATE_FAILED count=2 shown=2', 'S1_FAILED_ITEM scripts/tests/test_a.py::t1',
        'S1_FAILED_ITEM scripts/tests/test_b.py::t2']


def test_list_shows_at_most_twenty_names_and_counts_all(tmp_path):
    rows = ['FAILED scripts/tests/test_a.py::t%02d' % i for i in range(25)]
    put_raw(tmp_path, 'PRECOMMIT', 1, 4, section(*rows))
    lines = gr.failed_list_lines(str(tmp_path), TASK, 'precommit', 'PRECOMMIT_NONZERO')
    assert lines[0] == 'S1_FAILED_LIST kind=GATE_FAILED count=25 shown=20' and len(lines) == 21
    assert lines[1] == 'S1_FAILED_ITEM scripts/tests/test_a.py::t00' and lines[-1] == 'S1_FAILED_ITEM scripts/tests/test_a.py::t19'


def test_list_focused_reads_the_bounded_record(tmp_path):
    git = tmp_path / '.git'
    git.mkdir()
    (git / (TASK + '-bounded-focused.txt')).write_text(section('FAILED scripts/tests/test_f.py::t1'), encoding='utf-8', newline='\n')
    assert gr.failed_list_lines(str(tmp_path), TASK, 'focused', 'FOCUSED_NONZERO')[:2] == [
        'S1_FAILED_LIST kind=GATE_FAILED count=1 shown=1', 'S1_FAILED_ITEM scripts/tests/test_f.py::t1']


def test_list_highest_run_wins_and_other_tasks_are_not_read(tmp_path):
    put_raw(tmp_path, 'PRECOMMIT', 1, 4, section('FAILED scripts/tests/test_old.py::t1'))
    put_raw(tmp_path, 'PRECOMMIT', 2, 4, section('FAILED scripts/tests/test_new.py::t1'))
    put_raw(tmp_path, 'PRECOMMIT', 3, 4, section('FAILED scripts/tests/test_other.py::t1'), task='B117-OTHER-261122')
    assert gr.failed_list_lines(str(tmp_path), TASK, 'precommit', 'PRECOMMIT_NONZERO')[1] == 'S1_FAILED_ITEM scripts/tests/test_new.py::t1'


def test_list_unavailable_reasons(tmp_path):
    assert gr.failed_list_lines(str(tmp_path), TASK, 'precommit', 'PRECOMMIT_NONZERO') == [
        'S1_FAILED_LIST kind=FAILED_LIST_UNAVAILABLE reason=NO_RAW_OUTPUT']
    put_raw(tmp_path, 'PRECOMMIT', 1, 4, 'Timeout, no summary here\n')
    assert gr.failed_list_lines(str(tmp_path), TASK, 'precommit', 'PRECOMMIT_GATE_TIMEOUT') == [
        'S1_FAILED_LIST kind=FAILED_LIST_UNAVAILABLE reason=NO_NAMES_FOUND']
    for step in ('setup', 'native_preview', 'stage', 'push', 'bundle', 'commit', 'apply'):
        assert gr.failed_list_lines(str(tmp_path), TASK, step, 'X_FAILED') == [
            'S1_FAILED_LIST kind=FAILED_LIST_UNAVAILABLE reason=NOT_A_TEST_STEP']


def test_list_ci_failed_names_only_failed_required_jobs_with_fixed_conclusions(tmp_path):
    jobs = {'verify': {'status': 'completed', 'conclusion': 'failure'},
            'gateway-windows': {'status': 'completed', 'conclusion': 'success'}}
    assert gr.failed_list_lines(str(tmp_path), TASK, 'push', 'CANDIDATE_CI_NOT_PASS', jobs) == [
        'S1_FAILED_LIST kind=CI_FAILED count=1 shown=1', 'S1_FAILED_ITEM job=verify conclusion=failure']
    jobs = {'verify': {'status': 'completed', 'conclusion': 'weird; rm -rf'}, 'gateway-windows': None}
    assert gr.failed_list_lines(str(tmp_path), TASK, 'postmain', 'POST_MAIN_CI_NOT_PASS', jobs) == [
        'S1_FAILED_LIST kind=CI_FAILED count=2 shown=2', 'S1_FAILED_ITEM job=verify conclusion=none',
        'S1_FAILED_ITEM job=gateway-windows conclusion=none']
    jobs = {'verify': {'status': 'in_progress', 'conclusion': None}, 'gateway-windows': {'status': 'queued', 'conclusion': None}}
    assert gr.failed_list_lines(str(tmp_path), TASK, 'push', 'CANDIDATE_CI_NOT_PROVEN', jobs)[1:] == [
        'S1_FAILED_ITEM job=verify conclusion=in_progress', 'S1_FAILED_ITEM job=gateway-windows conclusion=queued']


ALL_GREEN = {'verify': {'status': 'completed', 'conclusion': 'success'}, 'gateway-windows': {'status': 'completed', 'conclusion': 'success'}}


@pytest.mark.parametrize('jobs', [None, 'x', [], ALL_GREEN])
def test_list_ci_code_without_a_failed_job_is_unavailable(tmp_path, jobs):
    assert gr.failed_list_lines(str(tmp_path), TASK, 'push', 'CI_STATUS_NOT_PASS', jobs) == [
        'S1_FAILED_LIST kind=FAILED_LIST_UNAVAILABLE reason=NO_NAMES_FOUND']


def test_list_ci_code_with_missing_required_jobs_names_both_with_conclusion_none(tmp_path):
    assert gr.failed_list_lines(str(tmp_path), TASK, 'push', 'CI_STATUS_NOT_PASS', {})[:3] == [
        'S1_FAILED_LIST kind=CI_FAILED count=2 shown=2', 'S1_FAILED_ITEM job=verify conclusion=none',
        'S1_FAILED_ITEM job=gateway-windows conclusion=none']


def test_list_error_never_raises_and_says_so(tmp_path, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError('x')
    monkeypatch.setattr(gr, 'failed_sources', boom)
    assert gr.failed_list_lines(str(tmp_path), TASK, 'precommit', 'PRECOMMIT_NONZERO') == [
        'S1_FAILED_LIST kind=FAILED_LIST_UNAVAILABLE reason=LIST_ERROR']


def test_list_oversized_raw_is_unavailable_not_read(tmp_path, monkeypatch):
    put_raw(tmp_path, 'PRECOMMIT', 1, 4, section('FAILED scripts/tests/test_a.py::t1'))
    monkeypatch.setattr(gr, 'MAX_SOURCE_BYTES', 10)
    assert gr.failed_list_lines(str(tmp_path), TASK, 'precommit', 'PRECOMMIT_NONZERO') == [
        'S1_FAILED_LIST kind=FAILED_LIST_UNAVAILABLE reason=NO_RAW_OUTPUT']


# ---- R6 -----------------------------------------------------------------------------------------------------------
GOOD_GROUPS = {'schema_version': 1, 'status': 'PASS', 'collected': 1229, 'counted': 1229, 'passed': 1225, 'skipped': 4,
               'failures': 0, 'errors': 0, 'phase1_sec': 410.2, 'groups_sec': 380.5, 'total_sec': 800.1, 'reasons': [],
               'groups': [{'name': 'seq', 'rc': 0, 'sec': 410.2, 'files': 7, 'tests': 600},
                          {'name': 'g1', 'rc': 0, 'sec': 380.5, 'files': 10, 'tests': 629}]}


def put_groups(root, doc, run=1):
    raw = put_raw(root, 'PRECOMMIT', run, 4, 'x\n')
    path = Path(str(raw) + gr.GROUPS_SUFFIX)
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding='utf-8', newline='\n')


def test_groups_lines_have_the_fixed_shape(tmp_path):
    put_groups(tmp_path, GOOD_GROUPS)
    assert gr.groups_lines(str(tmp_path), TASK, 'PRECOMMIT') == [
        'GATE4_GROUPS_RESULT status=PASS collected=1229 counted=1229 passed=1225 skipped=4 failures=0 errors=0 '
        'phase1_sec=410.2 groups_sec=380.5 total_sec=800.1 reasons=NONE',
        'GATE4_GROUP name=seq rc=0 sec=410.2 files=7 tests=600', 'GATE4_GROUP name=g1 rc=0 sec=380.5 files=10 tests=629']


def test_groups_failed_record_lists_reasons_and_none_values(tmp_path):
    doc = json.loads(json.dumps(GOOD_GROUPS))
    doc.update(status='FAIL', failures=1, passed=1224, reasons=['g1:FAILED_TESTS', 'g1:EXIT_1'])
    doc['groups'][1].update(rc=None, tests=None)
    put_groups(tmp_path, doc)
    lines = gr.groups_lines(str(tmp_path), TASK, 'PRECOMMIT')
    assert lines[0].endswith('reasons=g1:FAILED_TESTS,g1:EXIT_1') and lines[2] == 'GATE4_GROUP name=g1 rc=None sec=380.5 files=10 tests=n/a'


def _mut(**changes):
    doc = json.loads(json.dumps(GOOD_GROUPS))
    for key, value in changes.items():
        doc[key] = value
    return doc


@pytest.mark.parametrize('doc', [
    _mut(schema_version=2), _mut(status='pass'), _mut(status='OK'), _mut(collected='1229'), _mut(counted=-1), _mut(passed=True),
    _mut(phase1_sec='1.0'), _mut(total_sec=1e400), _mut(reasons='NONE'), _mut(reasons=['bad reason']), _mut(reasons=['a;b']),
    _mut(reasons=[1]), _mut(groups='x'), _mut(groups=[{'name': 'g9', 'rc': 0, 'sec': 1.0, 'files': 1, 'tests': 1}]),
    _mut(groups=[{'name': 'g1', 'rc': 0, 'sec': 1.0, 'files': 1, 'tests': 1}] * 2),
    _mut(groups=[{'name': 'g1', 'rc': 'x', 'sec': 1.0, 'files': 1, 'tests': 1}]),
    _mut(groups=[{'name': 'g1', 'rc': 0, 'sec': -1.0, 'files': 1, 'tests': 1}]),
    _mut(groups=[{'name': 'g1', 'rc': 0, 'sec': 1.0, 'files': 1, 'tests': 'many'}]), _mut(groups=[1]),
    [], 'not json', '{"schema_version": 1', None])
def test_groups_invalid_record_gives_no_line(tmp_path, doc):
    text = doc if isinstance(doc, str) else json.dumps(doc, allow_nan=True)
    put_groups(tmp_path, text)
    assert gr.groups_lines(str(tmp_path), TASK, 'PRECOMMIT') == []


def test_groups_only_for_precommit_and_only_when_a_record_exists(tmp_path):
    assert gr.groups_lines(str(tmp_path), TASK, 'PRECOMMIT') == []
    put_groups(tmp_path, GOOD_GROUPS)
    assert gr.groups_lines(str(tmp_path), TASK, 'POSTCOMMIT') == [] and gr.groups_lines(str(tmp_path), TASK, 'STAGED') == []
    put_raw(tmp_path, 'PRECOMMIT', 2, 4, 'a later run without a record\n')
    assert gr.groups_lines(str(tmp_path), TASK, 'PRECOMMIT') == []


# ---- R7 -----------------------------------------------------------------------------------------------------------
def put_progress(root, stage, run, gate, tag, doc):
    raw = put_raw(root, stage, run, gate, 'x\n') if not (Path(root) / '.git' / ('%s-local-gates.txt.%s-run%d-gate%d.raw' % (
        TASK, stage.lower(), run, gate))).exists() else Path(root) / '.git' / ('%s-local-gates.txt.%s-run%d-gate%d.raw' % (
            TASK, stage.lower(), run, gate))
    Path(str(raw) + gr.PROGRESS_INFIX + tag + '.json').write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding='utf-8', newline='\n')


def prog(completed, running=None, last=None):
    return {'schema_version': 1, 'completed': completed, 'running': running, 'last': last}


def test_progress_sums_processes_and_names_running_and_last(tmp_path):
    put_progress(tmp_path, 'PRECOMMIT', 1, 4, 'aaa', prog(120, 'scripts/tests/test_a.py::t1', 'scripts/tests/test_a.py::t0'))
    put_progress(tmp_path, 'PRECOMMIT', 1, 4, 'bbb', prog(300, None, 'scripts/tests/test_b.py::t9'))
    assert gr.progress_lines(str(tmp_path), TASK, 'PRECOMMIT') == [
        'GATE_PROGRESS stage=PRECOMMIT run=1 gate=4 procs=2 completed=420',
        'GATE_PROGRESS_PROC idx=1 completed=120 running=scripts/tests/test_a.py::t1 last=scripts/tests/test_a.py::t0',
        'GATE_PROGRESS_PROC idx=2 completed=300 running=none last=scripts/tests/test_b.py::t9']


def test_progress_uses_the_highest_gate_with_records_and_the_highest_run(tmp_path):
    put_progress(tmp_path, 'PRECOMMIT', 1, 4, 'aaa', prog(5))
    put_progress(tmp_path, 'PRECOMMIT', 1, 5, 'aaa', prog(7))
    assert gr.progress_lines(str(tmp_path), TASK, 'PRECOMMIT')[0] == 'GATE_PROGRESS stage=PRECOMMIT run=1 gate=5 procs=1 completed=7'
    put_progress(tmp_path, 'PRECOMMIT', 2, 4, 'aaa', prog(9))
    assert gr.progress_lines(str(tmp_path), TASK, 'PRECOMMIT')[0] == 'GATE_PROGRESS stage=PRECOMMIT run=2 gate=4 procs=1 completed=9'


@pytest.mark.parametrize('doc', [prog(-1), prog('3'), prog(True), {'schema_version': 2, 'completed': 1, 'running': None, 'last': None},
                                 prog(1, 7), prog(1, None, ['x']), '{"completed": 1', '[]', '',
                                 {'schema_version': 1, 'running': None, 'last': None}])
def test_progress_invalid_record_gives_no_line(tmp_path, doc):
    put_progress(tmp_path, 'PRECOMMIT', 1, 4, 'aaa', doc)
    assert gr.progress_lines(str(tmp_path), TASK, 'PRECOMMIT') == []


def test_progress_more_than_eight_processes_or_unknown_stage_gives_no_line(tmp_path):
    for i in range(9):
        put_progress(tmp_path, 'PRECOMMIT', 1, 4, 'p%02d' % i, prog(1))
    assert gr.progress_lines(str(tmp_path), TASK, 'PRECOMMIT') == []
    assert gr.progress_lines(str(tmp_path), TASK, 'WHATEVER') == []
    assert gr.progress_lines(str(tmp_path / 'missing'), TASK, 'PRECOMMIT') == []


def test_gate_lines_adds_progress_only_after_a_timeout(tmp_path):
    put_groups(tmp_path, GOOD_GROUPS)
    put_progress(tmp_path, 'PRECOMMIT', 1, 4, 'aaa', prog(3, 'scripts/tests/test_a.py::t1'))
    assert [l.split(' ')[0] for l in gr.gate_lines(str(tmp_path), TASK, 'PRECOMMIT', False)] == ['GATE4_GROUPS_RESULT', 'GATE4_GROUP', 'GATE4_GROUP']
    assert [l.split(' ')[0] for l in gr.gate_lines(str(tmp_path), TASK, 'PRECOMMIT', True)][-2:] == ['GATE_PROGRESS', 'GATE_PROGRESS_PROC']
    assert gr.gate_lines(str(tmp_path), TASK, 'STAGED', False) == []


# ---- R8: the plugin, real process ---------------------------------------------------------------------------------
HANG_SAMPLE = '''
import time

def test_first():
    assert True

def test_second():
    assert True

def test_hangs():
    time.sleep(120)
'''


def _plugin_env(prefix):
    env = {k: v for k, v in os.environ.items() if k not in ('PYTEST_ADDOPTS', gate_durations.PREFIX_ENV)}
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTEST_ADDOPTS=gate_durations.ADDOPT)
    env[gate_durations.PREFIX_ENV] = prefix
    return env


def test_plugin_progress_survives_a_killed_run_and_names_the_running_test(tmp_path):
    tests = tmp_path / 'sample'
    tests.mkdir()
    (tests / 'test_sample.py').write_text(HANG_SAMPLE, encoding='utf-8', newline='\n')
    prefix = str(tmp_path / 'gate.raw')
    proc = subprocess.Popen(gate_runner.resolve_command([gate_runner.PY, '-m', 'pytest', str(tests), '-q', '-p', 'no:cacheprovider']),
                            cwd=REPO_ROOT, env=_plugin_env(prefix), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 60
        doc = None
        while time.monotonic() < deadline:
            files = list(tmp_path.glob('gate.raw.progress-*.json'))
            if files:
                try:
                    doc = json.loads(files[0].read_text(encoding='utf-8'))
                except ValueError:
                    doc = None
                if doc and doc['running'] and doc['running'].endswith('::test_hangs'):
                    break
            time.sleep(0.2)
        assert doc and doc['running'].endswith('::test_hangs'), 'the hanging test must be reported as running'
    finally:
        proc.kill()
        proc.wait(timeout=30)
    doc = json.loads(next(tmp_path.glob('gate.raw.progress-*.json')).read_text(encoding='utf-8'))
    assert doc['schema_version'] == 1 and doc['completed'] == 2 and doc['last'].endswith('::test_second')
    assert doc['running'].endswith('::test_hangs')


def test_plugin_progress_after_a_normal_run_has_no_running_test_and_the_full_count(tmp_path):
    tests = tmp_path / 'sample'
    tests.mkdir()
    (tests / 'test_sample.py').write_text('def test_a():\n    pass\n\ndef test_b():\n    pass\n', encoding='utf-8', newline='\n')
    prefix = str(tmp_path / 'gate.raw')
    done = subprocess.run(gate_runner.resolve_command([gate_runner.PY, '-m', 'pytest', str(tests), '-q', '-p', 'no:cacheprovider']),
                          cwd=REPO_ROOT, env=_plugin_env(prefix), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    assert done.returncode == 0
    doc = json.loads(next(tmp_path.glob('gate.raw.progress-*.json')).read_text(encoding='utf-8'))
    assert (doc['completed'], doc['running']) == (2, None) and doc['last'].endswith('::test_b')


def test_plugin_progress_counts_skipped_and_setup_error_tests_as_completed(tmp_path):
    tests = tmp_path / 'sample'
    tests.mkdir()
    (tests / 'test_sample.py').write_text(
        'import pytest\n\n@pytest.fixture\ndef broken():\n    raise RuntimeError("x")\n\n'
        'def test_ok():\n    pass\n\n@pytest.mark.skip(reason="r")\ndef test_skipped():\n    pass\n\n'
        'def test_setup_error(broken):\n    pass\n', encoding='utf-8', newline='\n')
    prefix = str(tmp_path / 'gate.raw')
    subprocess.run(gate_runner.resolve_command([gate_runner.PY, '-m', 'pytest', str(tests), '-q', '-p', 'no:cacheprovider']),
                   cwd=REPO_ROOT, env=_plugin_env(prefix), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    doc = json.loads(next(tmp_path.glob('gate.raw.progress-*.json')).read_text(encoding='utf-8'))
    assert doc['completed'] == 3 and doc['running'] is None


def test_plugin_progress_drops_a_node_id_longer_than_the_limit():
    assert gate_durations._short('a' * gate_durations.PROGRESS_MAX_NODEID) == 'a' * gate_durations.PROGRESS_MAX_NODEID
    assert gate_durations._short('a' * (gate_durations.PROGRESS_MAX_NODEID + 1)) is None
    assert gate_durations._short(None) is None and gate_durations._short(7) is None


def test_parse_lists_only_failed_and_error_rows_not_skipped_or_expected_failures():
    text = section('FAILED scripts/tests/test_a.py::t1').replace(
        '=== 1 failed', 'SKIPPED scripts/tests/test_s.py::t2 - why\nXFAIL scripts/tests/test_x.py::t3\n'
        'XPASS scripts/tests/test_p.py::t4\nERROR scripts/tests/test_e.py::t5 - boom\n=== 1 failed')
    assert gr.parse_failed_ids(text)[0] == ['scripts/tests/test_a.py::t1', 'scripts/tests/test_e.py::t5']


def test_plugin_progress_is_not_written_without_the_runner_variable(tmp_path):
    tests = tmp_path / 'sample'
    tests.mkdir()
    (tests / 'test_sample.py').write_text('def test_a():\n    pass\n', encoding='utf-8', newline='\n')
    env = _plugin_env(str(tmp_path / 'gate.raw'))
    env.pop(gate_durations.PREFIX_ENV)
    done = subprocess.run(gate_runner.resolve_command([gate_runner.PY, '-m', 'pytest', str(tests), '-q', '-p', 'no:cacheprovider']),
                          cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    assert done.returncode == 0 and not list(tmp_path.glob('*.json'))


# ---- R9: real gate runner, real pytest output -----------------------------------------------------------------------
FAIL_SAMPLE = '''
import pytest

def test_ok():
    assert True

def test_bad_one():
    assert 1 == 2

@pytest.mark.parametrize("n", [1, 2])
def test_bad_param(n):
    assert n == 99
'''


def test_end_to_end_gate_runner_sidecar_gives_the_failed_names(tmp_path):
    tests = tmp_path / 'sample'
    tests.mkdir()
    (tests / 'test_sample.py').write_text(FAIL_SAMPLE, encoding='utf-8', newline='\n')
    (tmp_path / '.git').mkdir()
    log = tmp_path / '.git' / (TASK + '-local-gates.txt')
    # the gate command carries the output-form flags exactly as the local gate producers add them (S1C-025): without them
    # PY_COLORS or FORCE_COLOR in the caller's environment would put ANSI sequences into the raw sidecar
    gates = [[gate_runner.PY, '-m', 'pytest', str(tests), '-q', '-p', 'no:cacheprovider'] + list(gate4_groups.OUTPUT_FORM)]
    code = gate_runner.run_stage(REPO_ROOT, 'PRECOMMIT', gates, str(log), timeout=120, durations_prefix=str(log))
    assert code != 0
    lines = gr.failed_list_lines(str(tmp_path), TASK, 'precommit', 'PRECOMMIT_NONZERO')
    assert lines[0] == 'S1_FAILED_LIST kind=GATE_FAILED count=3 shown=3'
    names = sorted(l.split(' ', 1)[1] for l in lines[1:])
    assert [n.rsplit('::', 1)[1] for n in names] == ['test_bad_one', 'test_bad_param[1]', 'test_bad_param[2]']
    assert all('\\' not in n for n in names)


# ---- R10 ----------------------------------------------------------------------------------------------------------
def test_constants_agree_between_the_producer_and_the_reader_modules():
    assert gate4_groups.RECORD_SUFFIX == gr.GROUPS_SUFFIX
    assert gate_durations.PROGRESS_MAX_NODEID == gr.MAX_NODEID
    assert gr.MAX_PROCS >= gate4_groups.MAX_GROUPS + 1 and len(gr.GROUP_NAMES) == gate4_groups.MAX_GROUPS + 1
    assert set(gr.STAGE_NAMES) == set(gate_runner.STAGES)
    assert gr.TEST_STEPS == ('focused', 'precommit', 'postcommit')


def test_constants_plugin_file_name_is_found_by_the_reader(tmp_path):
    raw = put_raw(tmp_path, 'PRECOMMIT', 1, 4, 'x\n')
    assert gate_durations.PROGRESS_INFIX == gr.PROGRESS_INFIX
    Path(str(raw) + gate_durations.PROGRESS_INFIX + gate_durations.session_tag(['a']) + '.json').write_text(json.dumps(prog(4)), encoding='utf-8', newline='\n')
    assert gr.progress_lines(str(tmp_path), TASK, 'PRECOMMIT')[0].endswith('completed=4')


# ---- R11: B1 / N1 of the alpha 1 second opinion (every FAILED/ERROR row counted, reduced names, progress kept) ----------
ROWS_B1 = ['scripts/tests/test_a.py::test_ok_name',
           'scripts/tests/test_a.py::test_param[item count below shown]',
           'scripts/tests/test_a.py::test_param[C:\\\\path\\\\x]',
           'scripts/tests/test_a.py::test_lambda[<lambda>]']


def _b1_raw(tmp_path, rows):
    text = section(*['FAILED %s - AssertionError: x' % r for r in rows])
    return put_raw(tmp_path, 'PRECOMMIT', 1, 4, text)


def test_list_every_failed_row_is_counted_even_when_its_id_is_not_a_safe_token(tmp_path):
    _b1_raw(tmp_path, ROWS_B1)
    lines = gr.failed_list_lines(str(tmp_path), TASK, 'precommit', 'PRECOMMIT_NONZERO')
    assert lines[0] == 'S1_FAILED_LIST kind=GATE_FAILED count=4 shown=3'
    assert lines[1:] == ['S1_FAILED_ITEM scripts/tests/test_a.py::test_ok_name', 'S1_FAILED_ITEM scripts/tests/test_a.py::test_param[*]',
                         'S1_FAILED_ITEM scripts/tests/test_a.py::test_lambda[*]']


def test_list_rows_that_exist_are_never_reported_as_no_names_found(tmp_path):
    _b1_raw(tmp_path, ROWS_B1[1:])
    lines = gr.failed_list_lines(str(tmp_path), TASK, 'precommit', 'PRECOMMIT_NONZERO')
    assert 'NO_NAMES_FOUND' not in lines[0] and lines[0].startswith('S1_FAILED_LIST kind=GATE_FAILED count=3 shown=2')


def test_list_rows_whose_names_cannot_be_shown_are_counted_in_unsafe_and_still_not_no_names_found(tmp_path):
    put_raw(tmp_path, 'PRECOMMIT', 1, 4, section('FAILED x y.py::t - a', 'FAILED a;b.py::t - a', 'ERROR scripts/tests/test_a.py::p[1 2] - b'))
    assert gr.failed_list_lines(str(tmp_path), TASK, 'precommit', 'PRECOMMIT_NONZERO') == [
        'S1_FAILED_LIST kind=GATE_FAILED count=3 shown=1 unsafe=2', 'S1_FAILED_ITEM scripts/tests/test_a.py::p[*]']
    put_raw(tmp_path, 'PRECOMMIT', 2, 4, section('FAILED x y.py::t - a', 'FAILED a;b.py::t - a'))
    assert gr.failed_list_lines(str(tmp_path), TASK, 'precommit', 'PRECOMMIT_NONZERO') == ['S1_FAILED_LIST kind=GATE_FAILED count=2 shown=0 unsafe=2']


def test_list_a_section_without_rows_is_still_no_names_found(tmp_path):
    put_raw(tmp_path, 'PRECOMMIT', 1, 4, section())
    assert gr.failed_list_lines(str(tmp_path), TASK, 'precommit', 'PRECOMMIT_NONZERO') == [
        'S1_FAILED_LIST kind=FAILED_LIST_UNAVAILABLE reason=NO_NAMES_FOUND']


def test_list_counts_rows_over_every_section_of_a_grouped_raw(tmp_path):
    put_raw(tmp_path, 'PRECOMMIT', 1, 4, section('FAILED scripts/tests/test_a.py::t[x y] - a') + 'noise\n' + section(
        'FAILED scripts/tests/test_a.py::t[z w] - a', 'FAILED scripts/tests/test_b.py::u - a'))
    lines = gr.failed_list_lines(str(tmp_path), TASK, 'precommit', 'PRECOMMIT_NONZERO')
    assert lines[0] == 'S1_FAILED_LIST kind=GATE_FAILED count=3 shown=2' and len(lines) == 3


def test_list_a_name_printed_by_a_test_inside_a_captured_section_is_counted_like_any_row(tmp_path):
    # Known and accepted (D-SO O1): the names are diagnostics, not evidence; a test that prints a fake section adds rows.
    text = section('FAILED scripts/tests/test_a.py::real - a')
    fake = '=== short test summary info ===\nFAILED scripts/tests/test_fake.py::pretend - b\n'
    put_raw(tmp_path, 'PRECOMMIT', 1, 4, fake + text)
    assert gr.failed_list_lines(str(tmp_path), TASK, 'precommit', 'PRECOMMIT_NONZERO')[0] == 'S1_FAILED_LIST kind=GATE_FAILED count=2 shown=2'


def test_progress_survives_a_running_test_whose_id_has_a_space(tmp_path):
    for tag, running in (('g1', 'scripts/tests/test_a.py::test_ok_name'), ('g2', 'scripts/tests/test_a.py::test_param[item count below shown]')):
        put_progress(tmp_path, 'PRECOMMIT', 1, 4, tag, prog(7, running, None))
    lines = gr.progress_lines(str(tmp_path), TASK, 'PRECOMMIT')
    assert lines[0].endswith('procs=2 completed=14')
    assert lines[1] == 'GATE_PROGRESS_PROC idx=1 completed=7 running=scripts/tests/test_a.py::test_ok_name last=none'
    assert lines[2] == 'GATE_PROGRESS_PROC idx=2 completed=7 running=scripts/tests/test_a.py::test_param[*] last=none'


def test_progress_withholds_only_a_name_that_cannot_be_shown_and_keeps_the_rest(tmp_path):
    put_progress(tmp_path, 'PRECOMMIT', 1, 4, 'aaa', prog(3, 'bad name', 'x;y'))
    put_progress(tmp_path, 'PRECOMMIT', 1, 4, 'bbb', prog(4, 'a.py::' + 'x' * 400, 'scripts/tests/test_b.py::t9'))
    assert gr.progress_lines(str(tmp_path), TASK, 'PRECOMMIT') == [
        'GATE_PROGRESS stage=PRECOMMIT run=1 gate=4 procs=2 completed=7',
        'GATE_PROGRESS_PROC idx=1 completed=3 running=withheld last=withheld',
        'GATE_PROGRESS_PROC idx=2 completed=4 running=withheld last=scripts/tests/test_b.py::t9']


def test_progress_file_is_cut_to_its_padded_width_even_after_a_longer_write(tmp_path):
    # O6: a shorter record written after a longer one must not leave a tail behind.
    path = tmp_path / 'p.json'
    handle = open(path, 'w', encoding='utf-8', newline='')
    saved = dict(gate_durations._progress)
    try:
        gate_durations._progress.update(handle=handle, completed=1, running='\\' * 300, last='\\' * 300)
        gate_durations._write_progress()
        long_size = path.stat().st_size
        gate_durations._progress.update(completed=2, running=None, last=None)
        gate_durations._write_progress()
        assert long_size > gate_durations.PROGRESS_WIDTH
        assert path.stat().st_size == gate_durations.PROGRESS_WIDTH
        assert json.loads(path.read_text(encoding='utf-8'))['completed'] == 2
    finally:
        gate_durations._progress.update(saved)
        handle.close()


def test_classname_of_a_file_is_not_given_to_a_file_whose_stem_is_its_prefix():
    # N1: the real pair test_w2_focused / test_w2_focused_callsites; the "." after the stem is what separates them.
    a, b = 'scripts/tests/test_w2_focused.py', 'scripts/tests/test_w2_focused_callsites.py'
    for files in ([a, b], [b, a]):
        assert gate4_groups.classname_file('scripts.tests.test_w2_focused_callsites', files) == b
        assert gate4_groups.classname_file('scripts.tests.test_w2_focused', files) == a
        assert gate4_groups.classname_file('scripts.tests.test_w2_focused.TestX', files) == a


E2E_FAIL = '''import pytest


@pytest.mark.parametrize('label', ['plain', 'item count below shown', 'C:\\\\path\\\\x'])
def test_param(label):
    assert label == 'never'


def test_simple():
    assert 1 == 2
'''


def test_end_to_end_grouped_run_the_listed_count_equals_failures_plus_errors(tmp_path):
    # D-SO end-to-end: real pytest under the real grouped gate; every FAILED row of the raw output is counted.
    tests = tmp_path / 'tests'
    tests.mkdir()
    (tests / 'test_e2e_fail.py').write_text(E2E_FAIL, encoding='utf-8', newline='\n')
    (tests / 'test_e2e_ok.py').write_text('def test_ok():\n    assert True\n', encoding='utf-8', newline='\n')
    env = {k: v for k, v in os.environ.items() if k not in ('PYTEST_ADDOPTS', gate_durations.PREFIX_ENV)}
    env[gate4_groups.LOCAL_GATE_ENV] = str(tmp_path / 'T-local-gates.txt.precommit-run1-gate4.raw')
    lines = []
    rc = gate4_groups.run_grouped([sys.executable, '-m', 'pytest', str(tests), '-q'], env, str(tmp_path), cpu_count=8,
                                  timings_path=str(tmp_path / 'none.json'), sequential=(), out=lines.append,
                                  tmp_parent=str(tmp_path))
    text = '\n'.join(lines)
    assert rc == 1
    result = next(l for l in lines if l.startswith('GATE4_GROUPS_RESULT'))
    failures = int(result.split(' failures=')[1].split()[0]) + int(result.split(' errors=')[1].split()[0])
    items, unsafe, rows = gr.parse_failed_rows(text)
    assert failures == 4 and rows == failures and unsafe == 0
    assert any(i.endswith('::test_param[*]') for i in items) and any(i.endswith('::test_simple') for i in items)
    assert not any('\\' in i for i in items)
    git = tmp_path / '.git'
    git.mkdir()
    (git / 'T-local-gates.txt.precommit-run1-gate4.raw').write_text(text + '\n', encoding='utf-8', newline='\n')
    listed = gr.failed_list_lines(str(tmp_path), 'T', 'precommit', 'PRECOMMIT_NONZERO')
    assert listed[0].startswith('S1_FAILED_LIST kind=GATE_FAILED count=4 shown=3')
