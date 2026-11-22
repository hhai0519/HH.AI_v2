"""Alpha batch 1 (D2, TD-100, TD-112) in the reply checker (scripts/reply_check.py).

Commitment -> test table (E27 (a)); the counterexamples are the mutation rows of each table:
  K1 every persisted S1 inside a step needs exactly one S1_FAILED_LIST; S1 forms that are not persisted inside a step
     (stop before the step, task already halted, secondary save failure) must not carry one
                                                                              test_list_required_*, test_list_not_expected_*
  K2 GATE_FAILED only at a test step: count = every FAILED/ERROR row, up to 20 unique node-id items (reduced names carry
     the fixed mark [*]), unsafe = rows whose name cannot be shown, shown + unsafe <= count and an item when a row can be
     shown; CI_FAILED only with a CI
     code and fixed job items; FAILED_LIST_UNAVAILABLE has a reason, no items, and NOT_A_TEST_STEP only where that is true
                                                                              test_list_valid_*, test_list_mutations_*
  K3 a grouped gate 4 result is consistent in itself (arithmetic, status, reasons), with the bounded lines (the PRECOMMIT
     stage ran; exit 0 means PASS) and with its group lines (unique, total equals counted, PASS means rc 0)
                                                                              test_groups_valid_*, test_groups_mutations_*
  K4 timeout progress only for the timed-out gate stage of the stopped step, with one process line per process and a
     matching total                                                           test_progress_valid_*, test_progress_mutations_*
  K5 none of these lines is accepted in a success reply except the grouped gate 4 lines  test_success_*
"""
import os
import sys

import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import batch_runner as br  # noqa: E402
import gate_report as gr  # noqa: E402
import reply_check as rc  # noqa: E402
from test_reply_check import PROD_REPLY, PROD_SPEC, PROD_TASK, PRE, PROMO_REPLY, PROMO_SPEC, PROMO_TASK  # noqa: E402

STEPS = br.derive_steps(PROD_SPEC)
NODE_A = 'scripts/tests/test_a.py::test_one'
NODE_B = 'scripts/tests/test_b.py::test_two'


def s1(step, code, lines, bounded=(), spec_steps=STEPS, task=PROD_TASK, halted=True):
    body = list(bounded) + ['S1 ' + code + ' | step ' + step] + list(lines) + [
        'S1_EVIDENCE_STATUS=UNAVAILABLE', 'S1_FULL_CAPTURE_STATUS=UNAVAILABLE', PRE.strip(),
        'STATE done=' + ','.join(spec_steps[:spec_steps.index(step)]) + ' halted=' + (step + ':' + code if halted else 'None')]
    return '\n'.join(body) + '\n'


def check(text, spec=PROD_SPEC, task=PROD_TASK):
    return rc.check_spec(task, spec, text)


def code_of(text, spec=PROD_SPEC, task=PROD_TASK):
    with pytest.raises(rc.CheckError) as e:
        check(text, spec, task)
    return str(e.value)


def gate_list(n=2):
    ids = [NODE_A, NODE_B][:n]
    return ['S1_FAILED_LIST kind=GATE_FAILED count=%d shown=%d' % (n, n)] + ['S1_FAILED_ITEM ' + i for i in ids]


UNAVAIL = 'S1_FAILED_LIST kind=FAILED_LIST_UNAVAILABLE reason='


# ---- K1 / K2 ------------------------------------------------------------------------------------------------------
def test_list_valid_forms_are_accepted():
    assert check(s1('precommit', 'PRECOMMIT_NONZERO', gate_list()))[2] == 'S1 precommit:PRECOMMIT_NONZERO'
    assert check(s1('focused', 'FOCUSED_NONZERO', gate_list(1)))[2] == 'S1 focused:FOCUSED_NONZERO'
    assert check(s1('postcommit', 'POSTCOMMIT_NONZERO', gate_list(1)))[2] == 'S1 postcommit:POSTCOMMIT_NONZERO'
    assert check(s1('precommit', 'PRECOMMIT_GATE_TIMEOUT', [UNAVAIL + 'NO_NAMES_FOUND']))
    assert check(s1('precommit', 'PRECOMMIT_NONZERO', [UNAVAIL + 'NO_RAW_OUTPUT']))
    assert check(s1('setup', 'SETUP_DIRTY', [UNAVAIL + 'NOT_A_TEST_STEP']))
    assert check(s1('precommit', 'PRECOMMIT_NONZERO', [UNAVAIL + 'LIST_ERROR']))


def test_list_valid_forms_with_reduced_names_and_unsafe_rows():
    # D-SO B1: count = every FAILED/ERROR row; shown = distinct listed names; unsafe = rows whose name cannot be shown.
    reduced = 'scripts/tests/test_a.py::test_param[*]'
    forms = [['S1_FAILED_LIST kind=GATE_FAILED count=5 shown=2', 'S1_FAILED_ITEM ' + NODE_A, 'S1_FAILED_ITEM ' + reduced],
             ['S1_FAILED_LIST kind=GATE_FAILED count=4 shown=1 unsafe=2', 'S1_FAILED_ITEM ' + reduced],
             ['S1_FAILED_LIST kind=GATE_FAILED count=3 shown=0 unsafe=3'],
             ['S1_FAILED_LIST kind=GATE_FAILED count=2 shown=1 unsafe=1', 'S1_FAILED_ITEM ' + NODE_A]]
    for lines in forms:
        assert check(s1('precommit', 'PRECOMMIT_NONZERO', lines))[2] == 'S1 precommit:PRECOMMIT_NONZERO'


def test_list_valid_twenty_shown_of_more():
    ids = ['scripts/tests/test_a.py::t%02d' % i for i in range(20)]
    lines = ['S1_FAILED_LIST kind=GATE_FAILED count=31 shown=20'] + ['S1_FAILED_ITEM ' + i for i in ids]
    assert check(s1('precommit', 'PRECOMMIT_NONZERO', lines))


def test_list_valid_ci_failed_in_production_and_promotion():
    ci = ['S1_FAILED_LIST kind=CI_FAILED count=2 shown=2', 'S1_FAILED_ITEM job=verify conclusion=failure',
          'S1_FAILED_ITEM job=gateway-windows conclusion=cancelled']
    assert check(s1('push', 'CANDIDATE_CI_NOT_PASS', ci))[2] == 'S1 push:CANDIDATE_CI_NOT_PASS'
    psteps = br.derive_steps(PROMO_SPEC)
    one = ['S1_FAILED_LIST kind=CI_FAILED count=1 shown=1', 'S1_FAILED_ITEM job=verify conclusion=failure']
    text = s1('postmain', 'POST_MAIN_CI_NOT_PASS', one, spec_steps=psteps)
    assert check(text, PROMO_SPEC, PROMO_TASK)[2] == 'S1 postmain:POST_MAIN_CI_NOT_PASS'


@pytest.mark.parametrize('step,code', [('precommit', 'PRECOMMIT_NONZERO'), ('focused', 'FOCUSED_NONZERO'), ('setup', 'SETUP_DIRTY'),
                                       ('push', 'CANDIDATE_CI_NOT_PASS')])
def test_list_required_for_every_persisted_s1_inside_a_step(step, code):
    assert code_of(s1(step, code, [])) == 'REPLY_S1_FAILED_LIST_MISSING'
    first = {'setup': UNAVAIL + 'NOT_A_TEST_STEP'}.get(step, UNAVAIL + 'NO_NAMES_FOUND')
    assert code_of(s1(step, code, [first, first])) == 'REPLY_S1_FAILED_LIST_REPEATED'


def test_list_not_expected_when_the_s1_is_not_persisted_inside_a_step():
    base = ['S1 START_STATE_MISMATCH | step preflight', 'STATE done= halted=None']
    assert check('\n'.join(base) + '\n' + PRE)[2] == 'S1 preflight:START_STATE_MISMATCH'
    before = ['S1 START_STATE_MISMATCH | step preflight', UNAVAIL + 'NOT_A_TEST_STEP', 'STATE done= halted=None']
    assert code_of('\n'.join(before) + '\n' + PRE) == 'REPLY_LINE_NOT_EXPECTED'
    done = ','.join(STEPS[:STEPS.index('precommit')])
    already = ['S1 TASK_ALREADY_HALTED precommit:PRECOMMIT_NONZERO', gate_list(1)[0], 'STATE done=' + done + ' halted=precommit:PRECOMMIT_NONZERO']
    assert code_of('\n'.join(already) + '\n' + PRE) == 'REPLY_LINE_NOT_EXPECTED'


def _base(**over):
    lines = gate_list(2)
    return s1('precommit', over.get('code', 'PRECOMMIT_NONZERO'), over.get('lines', lines))


LIST_MUTATIONS = [
    ('item count below shown', lambda: s1('precommit', 'PRECOMMIT_NONZERO', gate_list(2)[:2]), 'REPLY_S1_FAILED_LIST_INVALID'),
    ('item count above shown', lambda: s1('precommit', 'PRECOMMIT_NONZERO', gate_list(1) + ['S1_FAILED_ITEM ' + NODE_B]), 'REPLY_S1_FAILED_LIST_INVALID'),
    ('shown above count', lambda: s1('precommit', 'PRECOMMIT_NONZERO', ['S1_FAILED_LIST kind=GATE_FAILED count=1 shown=2', 'S1_FAILED_ITEM ' + NODE_A, 'S1_FAILED_ITEM ' + NODE_B]),
     'REPLY_S1_FAILED_LIST_INVALID'),
    ('twenty one shown', lambda: s1('precommit', 'PRECOMMIT_NONZERO', ['S1_FAILED_LIST kind=GATE_FAILED count=21 shown=21']
                                     + ['S1_FAILED_ITEM scripts/tests/test_a.py::t%02d' % i for i in range(21)]), 'REPLY_S1_FAILED_ITEM_REPEATED'),
    ('shown plus unsafe above count', lambda: s1('precommit', 'PRECOMMIT_NONZERO', ['S1_FAILED_LIST kind=GATE_FAILED count=2 shown=2 unsafe=1', 'S1_FAILED_ITEM ' + NODE_A, 'S1_FAILED_ITEM ' + NODE_B]),
     'REPLY_S1_FAILED_LIST_INVALID'),
    ('unsafe above count', lambda: s1('precommit', 'PRECOMMIT_NONZERO', ['S1_FAILED_LIST kind=GATE_FAILED count=1 shown=0 unsafe=2']), 'REPLY_S1_FAILED_LIST_INVALID'),
    ('rows that can be shown but nothing listed', lambda: s1('precommit', 'PRECOMMIT_NONZERO', ['S1_FAILED_LIST kind=GATE_FAILED count=3 shown=0']), 'REPLY_S1_FAILED_LIST_INVALID'),
    ('rows that can be shown but nothing listed with unsafe rows', lambda: s1('precommit', 'PRECOMMIT_NONZERO', ['S1_FAILED_LIST kind=GATE_FAILED count=3 shown=0 unsafe=2']), 'REPLY_S1_FAILED_LIST_INVALID'),
    ('unsafe on CI_FAILED', lambda: s1('push', 'CANDIDATE_CI_NOT_PASS', ['S1_FAILED_LIST kind=CI_FAILED count=1 shown=1 unsafe=1', 'S1_FAILED_ITEM job=verify conclusion=failure']),
     'REPLY_S1_FAILED_LIST_INVALID'),
    ('unsafe written as zero', lambda: s1('precommit', 'PRECOMMIT_NONZERO', ['S1_FAILED_LIST kind=GATE_FAILED count=1 shown=1 unsafe=0', 'S1_FAILED_ITEM ' + NODE_A]), 'REPLY_LINE_MALFORMED'),
    ('unsafe under FAILED_LIST_UNAVAILABLE', lambda: s1('precommit', 'PRECOMMIT_NONZERO', [UNAVAIL + 'NO_NAMES_FOUND unsafe=1']), 'REPLY_LINE_MALFORMED'),
    ('zero names under GATE_FAILED', lambda: s1('precommit', 'PRECOMMIT_NONZERO', ['S1_FAILED_LIST kind=GATE_FAILED count=0 shown=0']), 'REPLY_S1_FAILED_LIST_INVALID'),
    ('duplicate item', lambda: s1('precommit', 'PRECOMMIT_NONZERO', ['S1_FAILED_LIST kind=GATE_FAILED count=2 shown=2'] + ['S1_FAILED_ITEM ' + NODE_A] * 2),
     'REPLY_S1_FAILED_LIST_INVALID'),
    ('items under UNAVAILABLE', lambda: s1('precommit', 'PRECOMMIT_NONZERO', [UNAVAIL + 'NO_NAMES_FOUND', 'S1_FAILED_ITEM ' + NODE_A]), 'REPLY_S1_FAILED_LIST_INVALID'),
    ('GATE_FAILED at a non-test step', lambda: s1('setup', 'SETUP_DIRTY', gate_list(1)), 'REPLY_S1_FAILED_LIST_MISMATCH'),
    ('GATE_FAILED with a CI code', lambda: s1('push', 'CANDIDATE_CI_NOT_PASS', gate_list(1)), 'REPLY_S1_FAILED_LIST_MISMATCH'),
    ('GATE_FAILED with a job item', lambda: s1('precommit', 'PRECOMMIT_NONZERO', ['S1_FAILED_LIST kind=GATE_FAILED count=1 shown=1', 'S1_FAILED_ITEM job=verify conclusion=failure']),
     'REPLY_S1_FAILED_LIST_MISMATCH'),
    ('CI_FAILED with a test code', lambda: s1('precommit', 'PRECOMMIT_NONZERO', ['S1_FAILED_LIST kind=CI_FAILED count=1 shown=1', 'S1_FAILED_ITEM job=verify conclusion=failure']),
     'REPLY_S1_FAILED_LIST_MISMATCH'),
    ('CI_FAILED with a node item', lambda: s1('push', 'CANDIDATE_CI_NOT_PASS', ['S1_FAILED_LIST kind=CI_FAILED count=1 shown=1', 'S1_FAILED_ITEM ' + NODE_A]),
     'REPLY_S1_FAILED_LIST_MISMATCH'),
    ('CI_FAILED count above shown', lambda: s1('push', 'CANDIDATE_CI_NOT_PASS', ['S1_FAILED_LIST kind=CI_FAILED count=3 shown=1', 'S1_FAILED_ITEM job=verify conclusion=failure']),
     'REPLY_S1_FAILED_LIST_INVALID'),
    ('NOT_A_TEST_STEP at a test step', lambda: s1('precommit', 'PRECOMMIT_NONZERO', [UNAVAIL + 'NOT_A_TEST_STEP']), 'REPLY_S1_FAILED_LIST_MISMATCH'),
    ('NOT_A_TEST_STEP with a CI code', lambda: s1('push', 'CANDIDATE_CI_NOT_PASS', [UNAVAIL + 'NOT_A_TEST_STEP']), 'REPLY_S1_FAILED_LIST_MISMATCH'),
    ('NO_RAW_OUTPUT with a CI code', lambda: s1('push', 'CANDIDATE_CI_NOT_PASS', [UNAVAIL + 'NO_RAW_OUTPUT']), 'REPLY_S1_FAILED_LIST_MISMATCH'),
    ('unknown reason', lambda: s1('precommit', 'PRECOMMIT_NONZERO', [UNAVAIL + 'BECAUSE']), 'REPLY_LINE_MALFORMED'),
    ('unknown kind', lambda: s1('precommit', 'PRECOMMIT_NONZERO', ['S1_FAILED_LIST kind=MAYBE count=1 shown=1']), 'REPLY_LINE_MALFORMED'),
    ('unsafe node id', lambda: s1('precommit', 'PRECOMMIT_NONZERO', ['S1_FAILED_LIST kind=GATE_FAILED count=1 shown=1', 'S1_FAILED_ITEM scripts/tests/test_a.py::t;rm']),
     'REPLY_LINE_MALFORMED'),
    ('job item with a free conclusion', lambda: s1('push', 'CANDIDATE_CI_NOT_PASS', ['S1_FAILED_LIST kind=CI_FAILED count=1 shown=1', 'S1_FAILED_ITEM job=verify conclusion=because']),
     'REPLY_LINE_MALFORMED'),
    ('unknown job name', lambda: s1('push', 'CANDIDATE_CI_NOT_PASS', ['S1_FAILED_LIST kind=CI_FAILED count=1 shown=1', 'S1_FAILED_ITEM job=other conclusion=failure']),
     'REPLY_LINE_MALFORMED'),
    ('item without a list', lambda: s1('precommit', 'PRECOMMIT_NONZERO', ['S1_FAILED_ITEM ' + NODE_A]), 'REPLY_S1_FAILED_LIST_MISSING'),
]


@pytest.mark.parametrize('name,build,expected', LIST_MUTATIONS, ids=[m[0] for m in LIST_MUTATIONS])
def test_list_mutations_fail_with_a_fixed_code(name, build, expected):
    assert code_of(build()) == expected


# ---- K3 -----------------------------------------------------------------------------------------------------------
def result(status='PASS', collected=12, counted=12, passed=11, skipped=1, failures=0, errors=0, reasons='NONE'):
    return ('GATE4_GROUPS_RESULT status=%s collected=%d counted=%d passed=%d skipped=%d failures=%d errors=%d phase1_sec=3.0 '
            'groups_sec=4.0 total_sec=8.0 reasons=%s' % (status, collected, counted, passed, skipped, failures, errors, reasons))


def group(name='seq', rc_='0', tests='4'):
    return 'GATE4_GROUP name=%s rc=%s sec=3.0 files=2 tests=%s' % (name, rc_, tests)


EXIT_OK = 'BOUNDED_EXIT PRECOMMIT code=0 | GATE_RUNNER PASS stage=PRECOMMIT'
EXIT_FAIL = 'BOUNDED_EXIT PRECOMMIT code=1 | GATE_RUNNER FAIL stage=PRECOMMIT'


def success_with(lines, bounded=EXIT_OK):
    parts = PROD_REPLY.split('\n')
    at = next(i for i, l in enumerate(parts) if l.startswith('CI_RUN '))
    return '\n'.join(parts[:at] + [bounded] + lines + parts[at:])


def test_groups_valid_success_reply_is_accepted_and_still_pass():
    text = success_with([result(), group('seq', '0', '4'), group('g1', '0', '8')])
    assert check(text)[3:] == ('N/A', 'NO_S1')
    assert check(success_with([result()]))[3:] == ('N/A', 'NO_S1')
    assert check(success_with([]))[3:] == ('N/A', 'NO_S1')


def test_groups_valid_failed_result_in_an_s1_reply():
    lines = gate_list(1) + [result('FAIL', passed=10, failures=1, reasons='g1:FAILED_TESTS,g1:EXIT_1'), group('seq', '0', '4'), group('g1', '1', '8')]
    assert check(s1('precommit', 'PRECOMMIT_NONZERO', lines, bounded=[EXIT_FAIL]))[2] == 'S1 precommit:PRECOMMIT_NONZERO'


S1_FAIL_RESULT = result('FAIL', passed=10, failures=1, reasons='g1:FAILED_TESTS')
GROUP_MUTATIONS = [
    ('group without result', lambda: success_with([group('seq', '0', '12')]), 'REPLY_GATE4_GROUP_WITHOUT_RESULT'),
    ('result without the PRECOMMIT bounded line', lambda: success_with([result(), group('seq', '0', '12')], bounded='BOUNDED_EXIT FOCUSED code=0 | 5 passed in 1.00s'),
     'REPLY_GATE4_RESULT_UNBOUND'),
    ('arithmetic: passed too high', lambda: success_with([result(passed=12)]), 'REPLY_GATE4_RESULT_ARITHMETIC'),
    ('arithmetic: counted differs from the parts', lambda: success_with([result(counted=13, collected=13)]), 'REPLY_GATE4_RESULT_ARITHMETIC'),
    ('PASS with a reason', lambda: success_with([result(reasons='g1:EXIT_1')]), 'REPLY_GATE4_RESULT_STATUS'),
    ('FAIL without a reason', lambda: success_with([result('FAIL')]), 'REPLY_GATE4_RESULT_STATUS'),
    ('PASS with a failure', lambda: success_with([result(passed=10, failures=1)]), 'REPLY_GATE4_RESULT_STATUS'),
    ('PASS with an error', lambda: success_with([result(passed=10, errors=1)]), 'REPLY_GATE4_RESULT_STATUS'),
    ('PASS with counted below collected', lambda: success_with([result(collected=13)]), 'REPLY_GATE4_RESULT_STATUS'),
    ('PASS with zero tests', lambda: success_with([result(collected=0, counted=0, passed=0, skipped=0)]), 'REPLY_GATE4_RESULT_STATUS'),
    ('exit 0 but the result says FAIL', lambda: success_with([S1_FAIL_RESULT]), 'REPLY_GATE4_RESULT_CONTRADICTS_EXIT'),
    ('group total differs from counted', lambda: success_with([result(), group('seq', '0', '4'), group('g1', '0', '7')]), 'REPLY_GATE4_GROUP_TOTAL_MISMATCH'),
    ('group repeated', lambda: success_with([result(), group('g1', '0', '6'), group('g1', '0', '6')]), 'REPLY_GATE4_GROUP_REPEATED'),
    ('PASS with a failing group rc', lambda: success_with([result(), group('seq', '0', '4'), group('g1', '1', '8')]), 'REPLY_GATE4_GROUP_RC_MISMATCH'),
    ('two results', lambda: success_with([result(), result()]), 'REPLY_GATE4_GROUPS_RESULT_REPEATED'),
    ('six groups', lambda: success_with([result()] + [group(n, '0', '1') for n in ('seq', 'g1', 'g2', 'g3', 'g4')] + [group('g1', '0', '1')]),
     'REPLY_GATE4_GROUP_REPEATED'),
    ('unknown group name', lambda: success_with([result(), group('g9', '0', '12')]), 'REPLY_LINE_MALFORMED'),
    ('free text in reasons', lambda: success_with([result('FAIL', reasons='because it failed')]), 'REPLY_LINE_MALFORMED'),
    ('missing field', lambda: success_with([result().replace(' errors=0', '')]), 'REPLY_LINE_MALFORMED'),
    ('progress line in a success reply', lambda: success_with(['GATE_PROGRESS stage=PRECOMMIT run=1 gate=4 procs=1 completed=3',
                                                              'GATE_PROGRESS_PROC idx=1 completed=3 running=none last=none']), 'REPLY_LINE_NOT_EXPECTED'),
    ('failed list in a success reply', lambda: success_with(gate_list(1)), 'REPLY_LINE_NOT_EXPECTED'),
]


@pytest.mark.parametrize('name,build,expected', GROUP_MUTATIONS, ids=[m[0] for m in GROUP_MUTATIONS])
def test_groups_mutations_fail_with_a_fixed_code(name, build, expected):
    assert code_of(build()) == expected


def test_success_reply_carries_no_failed_list_not_even_the_unavailable_form():
    assert code_of(success_with([UNAVAIL + 'NO_NAMES_FOUND'])) == 'REPLY_LINE_NOT_EXPECTED'


def test_groups_lines_are_not_accepted_in_a_promotion_reply():
    text = PROMO_REPLY.replace('MAIN ', result() + '\nMAIN ', 1)
    assert code_of(text, PROMO_SPEC, PROMO_TASK) == 'REPLY_LINE_NOT_EXPECTED'


# ---- K4 -----------------------------------------------------------------------------------------------------------
def prog(stage='PRECOMMIT', completed=7, procs=((4, 'none', 'x/t.py::a'), (3, 'x/t.py::b', 'x/t.py::c'))):
    lines = ['GATE_PROGRESS stage=%s run=1 gate=4 procs=%d completed=%d' % (stage, len(procs), completed)]
    for i, (c, running, last) in enumerate(procs, 1):
        lines.append('GATE_PROGRESS_PROC idx=%d completed=%d running=%s last=%s' % (i, c, running, last))
    return lines


def test_progress_valid_after_a_gate_timeout_and_after_the_outer_limit():
    ok = s1('precommit', 'PRECOMMIT_GATE_TIMEOUT', prog() + [UNAVAIL + 'NO_NAMES_FOUND'], bounded=[EXIT_FAIL.replace('code=1', 'code=86')])
    assert check(ok)[2] == 'S1 precommit:PRECOMMIT_GATE_TIMEOUT'
    outer = s1('precommit', 'PRECOMMIT_TIMEOUT', prog() + [UNAVAIL + 'NO_NAMES_FOUND'], bounded=['BOUNDED_TIMEOUT PRECOMMIT limit=7200s kill=TREE_SIGNALLED'])
    assert check(outer)[2] == 'S1 precommit:PRECOMMIT_TIMEOUT'
    stage = s1('stage', 'STAGED_GATE_TIMEOUT', prog('STAGED', 2, ((2, 'none', 'x/t.py::a'),)) + [UNAVAIL + 'NOT_A_TEST_STEP'],
               bounded=['BOUNDED_EXIT STAGED code=86 | GATE_RUNNER FAIL stage=STAGED'])
    assert check(stage)[2] == 'S1 stage:STAGED_GATE_TIMEOUT'


def test_progress_valid_with_a_withheld_or_reduced_test_name():
    procs = ((4, 'withheld', 'x/t.py::a[*]'), (3, 'x/t.py::b', 'withheld'))
    text = s1('precommit', 'PRECOMMIT_GATE_TIMEOUT', prog(procs=procs) + [UNAVAIL + 'NO_NAMES_FOUND'],
              bounded=[EXIT_FAIL.replace('code=1', 'code=86')])
    assert check(text)[2] == 'S1 precommit:PRECOMMIT_GATE_TIMEOUT'


def _timeout(lines, code='PRECOMMIT_GATE_TIMEOUT', step='precommit', bounded=None):
    return s1(step, code, lines + [UNAVAIL + ('NO_NAMES_FOUND' if step in gr.TEST_STEPS else 'NOT_A_TEST_STEP')],
              bounded=[bounded or 'BOUNDED_EXIT PRECOMMIT code=86 | GATE_RUNNER FAIL stage=PRECOMMIT'])


PROGRESS_MUTATIONS = [
    ('total differs from the parts', lambda: _timeout(prog(completed=8)), 'REPLY_GATE_PROGRESS_MISMATCH'),
    ('process count differs', lambda: _timeout([prog()[0].replace('procs=2', 'procs=3')] + prog()[1:]), 'REPLY_GATE_PROGRESS_MISMATCH'),
    ('process index skips', lambda: _timeout([prog()[0], prog()[1], prog()[2].replace('idx=2', 'idx=3')]), 'REPLY_GATE_PROGRESS_MISMATCH'),
    ('progress after a plain failure code', lambda: _timeout(prog(), code='PRECOMMIT_NONZERO'), 'REPLY_GATE_PROGRESS_MISMATCH'),
    ('progress of another stage', lambda: _timeout(prog('POSTCOMMIT')), 'REPLY_GATE_PROGRESS_MISMATCH'),
    ('progress at a step with another stage', lambda: _timeout(prog('STAGED'), code='PRECOMMIT_GATE_TIMEOUT'), 'REPLY_GATE_PROGRESS_MISMATCH'),
    ('process lines without a total', lambda: _timeout(prog()[1:]), 'REPLY_GATE_PROGRESS_WITHOUT_TOTAL'),
    ('two totals', lambda: _timeout(prog() + [prog()[0]]), 'REPLY_GATE_PROGRESS_REPEATED'),
    ('nine processes', lambda: _timeout(prog(procs=tuple((1, 'none', 'none') for _ in range(9)), completed=9)), 'REPLY_GATE_PROGRESS_PROC_REPEATED'),
    ('free text as a test name', lambda: _timeout(prog(procs=((7, 'some test name', 'none'),))), 'REPLY_LINE_MALFORMED'),
    ('another word instead of withheld', lambda: _timeout(prog(procs=((7, 'hidden', 'none'),))), 'REPLY_LINE_MALFORMED'),
]


@pytest.mark.parametrize('name,build,expected', PROGRESS_MUTATIONS, ids=[m[0] for m in PROGRESS_MUTATIONS])
def test_progress_mutations_fail_with_a_fixed_code(name, build, expected):
    assert code_of(build()) == expected


def test_progress_is_accepted_in_a_secondary_failure_reply_for_the_original_code():
    lines = [EXIT_FAIL.replace('code=1', 'code=86')] + prog()
    text = '\n'.join(lines + ['S1 CONTROL_SAVE_FAILED | step precommit', 'S1_PRIMARY PRECOMMIT_GATE_TIMEOUT | step precommit', PRE.strip(),
                              'STATE done=' + ','.join(STEPS[:STEPS.index('precommit')]) + ' halted=None']) + '\n'
    assert check(text)[3:] == ('NOT_VERIFIED', 'SECONDARY_CONTROL_SAVE_FAILURE')
    assert code_of(text.replace('GATE_TIMEOUT |', 'NONZERO |')) == 'REPLY_GATE_PROGRESS_MISMATCH'
