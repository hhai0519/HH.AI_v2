# -*- coding: utf-8 -*-
"""One pytest output form wherever scripts/gate_report.py reads (alpha 1 R4 and R5, S1C-025).

R3 passed every local check and failed on GitHub Actions: pytest prints each row of the short test summary with its
full multi-line message when CI or BUILD_NUMBER is set or at verbosity 2, and with colour escapes when PY_COLORS or
FORCE_COLOR is set, and gate_report ends a section at the first line that is not a result row (1 row counted of 4).
A -r in PYTEST_ADDOPTS changes which rows are listed (-rf, -rE, -rN, -rs; the last -r wins). The local producers (the
grouped gate subprocesses, the local sequential pytest gates and the focused step) pass OUTPUT_FORM (--force-short-summary,
--color=no, -rfE), which overrides those variables; the CI command stays unchanged. These tests run real pytest under the
real grouped gate in every form, so they behave the same on a developer machine and on CI (they build their own
environment).
"""
import os
import sys
from types import SimpleNamespace

import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import gate4_groups  # noqa: E402
import gate_durations  # noqa: E402
import gate_report as gr  # noqa: E402
import verify_all  # noqa: E402

# Variables that change how pytest prints; every test starts without them and adds exactly the form under test.
FORM_VARS = ('CI', 'BUILD_NUMBER', 'PY_COLORS', 'FORCE_COLOR', 'NO_COLOR', 'COLUMNS', 'PYTEST_ADDOPTS')

E2E_FAIL = '''import pytest


@pytest.mark.parametrize('label', ['plain', 'item count below shown'])
def test_param(label):
    assert label == 'never'


def test_multi_line_message():
    raise RuntimeError('line1\\n\\nFAILED tests/fake.py::not_a_row\\n  indented')


@pytest.fixture
def boom():
    raise RuntimeError('setup\\nfail')


def test_setup(boom):
    pass
'''

FORMS = [
    ({}, []),
    ({'CI': 'true'}, []),
    ({'BUILD_NUMBER': '7'}, []),
    ({}, ['-vvv']),
    ({'CI': 'true'}, ['-vvv']),
    ({'PY_COLORS': '1'}, []),
    ({'FORCE_COLOR': '1'}, []),
    ({'CI': 'true', 'PY_COLORS': '1', 'BUILD_NUMBER': '7'}, ['-vvv']),
    ({'COLUMNS': '20'}, []),
    ({'COLUMNS': '400'}, []),
    ({'PYTEST_ADDOPTS': '-rf'}, []),
    ({'PYTEST_ADDOPTS': '-rE'}, []),
    ({'PYTEST_ADDOPTS': '-rN'}, []),
    ({'PYTEST_ADDOPTS': '-rs'}, []),
]
FORM_IDS = ['plain', 'CI', 'BUILD_NUMBER', 'vvv', 'CI+vvv', 'PY_COLORS', 'FORCE_COLOR', 'everything', 'COLUMNS20', 'COLUMNS400', 'ADDOPTS-rf', 'ADDOPTS-rE', 'ADDOPTS-rN', 'ADDOPTS-rs']


def clean_env(extra=None):
    env = {k: v for k, v in os.environ.items() if k not in FORM_VARS and k != gate_durations.PREFIX_ENV}
    env.update(extra or {})
    return env


def run_grouped_sample(tmp_path, extra_env, extra_args):
    tests = tmp_path / 'tests'
    tests.mkdir()
    (tests / 'test_e2e_fail.py').write_text(E2E_FAIL, encoding='utf-8', newline='\n')
    (tests / 'test_e2e_ok.py').write_text('def test_ok():\n    assert True\n', encoding='utf-8', newline='\n')
    env = clean_env(extra_env)
    env[gate4_groups.LOCAL_GATE_ENV] = str(tmp_path / 'T-local-gates.txt.precommit-run1-gate4.raw')
    lines = []
    rc = gate4_groups.run_grouped([sys.executable, '-m', 'pytest', str(tests), '-q'] + extra_args, env, str(tmp_path),
                                  cpu_count=8, timings_path=str(tmp_path / 'none.json'), sequential=(), out=lines.append)
    return rc, lines


@pytest.mark.parametrize('extra_env,extra_args', FORMS, ids=FORM_IDS)
def test_grouped_rows_equal_failures_plus_errors_in_every_output_form(tmp_path, extra_env, extra_args):
    rc, lines = run_grouped_sample(tmp_path, extra_env, extra_args)
    assert rc == 1
    result = next(l for l in lines if l.startswith('GATE4_GROUPS_RESULT'))
    # Collection is not affected by any form: every test is collected and counted (see the module docstring).
    assert ' collected=5 counted=5 ' in result and 'COLLECT' not in result
    failures = int(result.split(' failures=')[1].split()[0]) + int(result.split(' errors=')[1].split()[0])
    items, unsafe, rows = gr.parse_failed_rows('\n'.join(lines))
    assert failures == 4 and rows == failures and unsafe == 0
    assert not any(i.endswith('::not_a_row') for i in items)
    assert not any('\x1b' in line for line in lines)


def test_an_environment_that_changes_the_collection_output_fails_closed(tmp_path):
    # PYTEST_ADDOPTS=-v changes the --collect-only -q form; the grouped gate refuses to guess and fails with a fixed reason
    # (a safe failure: nothing is counted wrongly). Recorded here as a known form, not changed in alpha 1 R4.
    rc, lines = run_grouped_sample(tmp_path, {'PYTEST_ADDOPTS': '-v'}, [])
    assert rc != 0
    assert any(l.startswith('GATE4_GROUPS_RESULT status=FAIL reasons=COLLECT_COUNT_MISMATCH') for l in lines)


def test_output_form_is_the_short_summary_and_no_colour_options():
    assert gate4_groups.OUTPUT_FORM == ('--force-short-summary', '--color=no', '-rfE')


def test_build_cmd_carries_the_form_once_before_the_extra_arguments():
    one = gate4_groups.build_cmd(['py', '-m', 'pytest'], ['-q'], ['a.py'], 'bt', 'j.xml')
    assert one.count('--force-short-summary') == 1 and one.count('--color=no') == 1
    assert one.index('--force-short-summary') < one.index('-q') and one[-1] == 'a.py'
    two = gate4_groups.build_cmd(['py', '-m', 'pytest'], ['-q'] + list(gate4_groups.OUTPUT_FORM), ['a.py'], 'bt', 'j.xml')
    assert two.count('--force-short-summary') == 1 and two.count('--color=no') == 1


def test_output_form_args_adds_only_what_is_missing():
    assert gate4_groups.output_form_args(['-q']) == list(gate4_groups.OUTPUT_FORM)
    assert gate4_groups.output_form_args(['-q', '--color=no']) == ['--force-short-summary', '-rfE']
    assert gate4_groups.output_form_args(list(gate4_groups.OUTPUT_FORM)) == []


@pytest.mark.parametrize('name', ['unit_tests', 'webapp_tests'])
def test_local_sequential_pytest_gates_carry_the_form_and_the_ci_command_does_not(monkeypatch, name):
    gate = next(g for g in verify_all.GATES if g['name'] == name)
    monkeypatch.setattr(verify_all.gate4_groups, 'run_grouped', lambda *a, **kw: None)
    ran = []
    monkeypatch.setattr(verify_all.subprocess, 'run', lambda cmd, **kw: ran.append(cmd) or SimpleNamespace(returncode=0))
    assert verify_all.run_gate(gate, {gate4_groups.LOCAL_GATE_ENV: 'x.raw'}, verify_all.REPO_ROOT) == 0
    assert verify_all.run_gate(gate, {'CI': 'true', 'GITHUB_ACTIONS': 'true'}, verify_all.REPO_ROOT) == 0
    assert ran == [gate['cmd'] + list(gate4_groups.OUTPUT_FORM), gate['cmd']]
    for option in gate4_groups.OUTPUT_FORM:
        assert option not in gate['cmd']


def test_only_the_non_pytest_gates_and_the_collect_only_variant_are_left_alone(monkeypatch):
    ran = []
    monkeypatch.setattr(verify_all.subprocess, 'run', lambda cmd, **kw: ran.append(cmd) or SimpleNamespace(returncode=0))
    env = {gate4_groups.LOCAL_GATE_ENV: 'x.raw'}
    other = next(g for g in verify_all.GATES if g['name'] == 'fingerprint')
    collect = next(g for g in verify_all.quick_gates() if g['name'] == 'unit_tests')
    verify_all.run_gate(other, env, verify_all.REPO_ROOT)
    verify_all.run_gate(collect, env, verify_all.REPO_ROOT)
    assert ran == [other['cmd'], collect['cmd']]


def test_the_focused_step_command_carries_the_form_once(monkeypatch):
    import batch_runner
    for name in ('expect_scope', 'verify_hashes', 'final_hashes'):
        monkeypatch.setattr(batch_runner, name, lambda *a, **kw: None)
    for args in (['-q', 'scripts/tests/test_x.py'], ['-q', '--color=no', 'scripts/tests/test_x.py']):
        calls = []
        fake = SimpleNamespace(root='r', spec={'focused': {'pytest_args': args, 'limit_sec': 60}},
                               bounded=lambda *a, calls=calls: calls.append(a))
        batch_runner.Batch.step_focused(fake)
        step, cmd, limit = calls[0]
        assert step == 'FOCUSED' and limit == 60 and cmd[:2] == ['-m', 'pytest'] and cmd[-len(args):] == args
        assert cmd.count('--force-short-summary') == 1 and cmd.count('--color=no') == 1
