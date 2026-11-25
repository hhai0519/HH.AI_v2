# -*- coding: utf-8 -*-
"""TD-133: Exhaustive D4/N2 state transition matrix tests for scripts/s1_registry.check_monotonic (52 rows)."""
import copy
import itertools
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

import s1_registry as sr  # noqa: E402

X_TASK = 'B117-FIX-X-R1-261125'
Z_TASK = 'B117-FIX-Z-R1-261129'
T1_NODE = 'scripts/tests/test_s1_registry.py::test_d4_inbatch_refix_stale_fix_task_rejected'
T2_NODE = 'scripts/tests/test_s1_registry.py::test_d4_same_fixed_in_fixed_to_fixed_still_locks_fix_task_and_shas'


def _load_repo_registry() -> dict:
    return json.loads((REPO_ROOT / 'docs' / 'governance' / 's1-registry.json').read_bytes().decode('utf-8'))


def _rv(fix_task: str, sha_char: str, tests: list[str]) -> dict:
    return {
        'fixTask': fix_task,
        'injectable': True,
        'injectionMethod': 'matrix',
        'oldResult': 'FAIL',
        'oldOutputSha256': sha_char * 64,
        'newResult': 'PASS',
        'newOutputSha256': chr(ord(sha_char) + 1) * 64,
        'mutantResult': 'FAIL',
        'mutantOutputSha256': chr(ord(sha_char) + 2) * 64,
        'regressionTests': list(tests),
    }


def _set_state(cause: dict, status: str, fixed_in: str | None, rv: dict | None) -> None:
    for key in ('fixedIn', 'fixedCommit', 'reverseVerification'):
        cause.pop(key, None)
    cause['status'] = status
    if status == 'fixed':
        cause['fixedIn'] = fixed_in
        cause['fixedCommit'] = ('a' if fixed_in == X_TASK else 'c') * 40
    else:
        cause['fixedIn'] = None
    if rv is not None:
        cause['reverseVerification'] = rv


PRIORS = {
    'absent': None,
    'planned': ('planned', None, None),
    'planned+RVx': ('planned', None, _rv(X_TASK, 'a', [T1_NODE])),
    'fixedX': ('fixed', X_TASK, None),
    'fixedX+RVx': ('fixed', X_TASK, _rv(X_TASK, 'a', [T1_NODE])),
}
CUR_STATUSES = [
    ('planned', None),
    ('fixed', X_TASK),
    ('fixed', Z_TASK),
]
CUR_RVS = ['none', 'keep', 'newSHA_sameTask', 'task=fixedIn_newSHA', 'task=X_newSHA']


def _build_pair(base_doc: dict, target_cid: str, prior_key: str, cur_status: str, cur_fixed_in: str | None, rv_key: str):
    prior_doc = copy.deepcopy(base_doc)
    cur_doc = copy.deepcopy(base_doc)
    prior_state = PRIORS[prior_key]
    if prior_state is None:
        prior_doc['causes'] = [c for c in prior_doc['causes'] if c['id'] != target_cid]
        prior_rv = None
    else:
        _set_state(next(c for c in prior_doc['causes'] if c['id'] == target_cid), *prior_state)
        prior_rv = prior_state[2]

    if rv_key == 'none':
        cur_rv = None
    elif rv_key == 'keep':
        if prior_rv is None:
            return None
        cur_rv = copy.deepcopy(prior_rv)
    elif rv_key == 'newSHA_sameTask':
        if prior_rv is None:
            return None
        cur_rv = _rv(prior_rv['fixTask'], 'd', [T1_NODE, T2_NODE])
    elif rv_key == 'task=fixedIn_newSHA':
        if cur_fixed_in is None:
            return None
        cur_rv = _rv(cur_fixed_in, 'd', [T1_NODE, T2_NODE])
    else:
        cur_rv = _rv(X_TASK, 'd', [T1_NODE, T2_NODE])

    _set_state(next(c for c in cur_doc['causes'] if c['id'] == target_cid), cur_status, cur_fixed_in, cur_rv)
    return prior_doc, cur_doc, prior_state, prior_rv, cur_rv


def _expected_spec(prior_state, prior_rv, cur_status: str, cur_fixed_in: str | None, cur_rv: dict | None) -> tuple[bool, str]:
    is_fix_event = cur_status == 'fixed' and (
        prior_state is None or prior_state[0] != 'fixed' or prior_state[1] != cur_fixed_in
    )
    if prior_rv is not None and cur_rv is None:
        return False, 'RV deleted'
    if is_fix_event:
        if cur_rv is None:
            return False, 'fix event without RV'
        if cur_rv['fixTask'] != cur_fixed_in:
            return False, 'fix event fixTask != fixedIn'
        return True, 'fix event ok'
    if prior_rv is not None and cur_rv is not None:
        same = all(
            cur_rv.get(k) == prior_rv.get(k)
            for k in ('fixTask', 'oldOutputSha256', 'newOutputSha256', 'mutantOutputSha256')
        )
        return (True, 'locked unchanged') if same else (False, 'locked field changed')
    return True, 'no constraint'


def _all_cases() -> list[tuple[str, str, str | None, str]]:
    base_doc = _load_repo_registry()
    target_cid = next(c for c in base_doc['causes'] if c['status'] == 'planned')['id']
    cases = []
    for prior_key, (cur_status, cur_fixed_in), rv_key in itertools.product(PRIORS, CUR_STATUSES, CUR_RVS):
        built = _build_pair(base_doc, target_cid, prior_key, cur_status, cur_fixed_in, rv_key)
        if built is not None:
            cases.append((prior_key, cur_status, cur_fixed_in, rv_key))
    return cases


_ALL_CASES = _all_cases()
_CASE_IDS = [f'{pk}__{cs}_{fi or "none"}__{rvk}' for pk, cs, fi, rvk in _ALL_CASES]


def test_matrix_case_count_is_exact_52() -> None:
    assert len(_ALL_CASES) == 52


@pytest.mark.parametrize('prior_key,cur_status,cur_fixed_in,rv_key', _ALL_CASES, ids=_CASE_IDS)
def test_s1_registry_check_monotonic_transition_matrix(prior_key: str, cur_status: str, cur_fixed_in: str | None, rv_key: str) -> None:
    base_doc = _load_repo_registry()
    target_cid = next(c for c in base_doc['causes'] if c['status'] == 'planned')['id']
    built = _build_pair(base_doc, target_cid, prior_key, cur_status, cur_fixed_in, rv_key)
    assert built is not None
    prior_doc, cur_doc, prior_state, prior_rv, cur_rv = built
    exp_ok, why = _expected_spec(prior_state, prior_rv, cur_status, cur_fixed_in, cur_rv)
    fails = [f for f in sr.check_monotonic(prior_doc, cur_doc) if target_cid in f]
    assert (not fails) == exp_ok, (
        f'mismatch for {prior_key} -> ({cur_status}, {cur_fixed_in}, {rv_key}): '
        f'expected {"PASS" if exp_ok else "FAIL"} ({why}), fails={fails}'
    )


def test_matrix_covers_key_regression_scenarios() -> None:
    base_doc = _load_repo_registry()
    target_cid = next(c for c in base_doc['causes'] if c['status'] == 'planned')['id']
    key_scenarios = [
        # beta-2 R3 B1: in-batch refix with stale fixTask=X must FAIL
        ('fixedX+RVx', 'fixed', Z_TASK, 'newSHA_sameTask', False),
        # in-batch refix with valid new RV fixTask=Z must PASS
        ('fixedX+RVx', 'fixed', Z_TASK, 'task=fixedIn_newSHA', True),
        # beta-2 R2 N1: reopen (planned+RVx) -> fixed with matching new RV must PASS
        ('planned+RVx', 'fixed', Z_TASK, 'task=fixedIn_newSHA', True),
        # same fixedIn fixed -> fixed must lock fixTask & SHAs (new SHA must FAIL)
        ('fixedX+RVx', 'fixed', X_TASK, 'newSHA_sameTask', False),
        # deleting existing RV must always FAIL
        ('fixedX+RVx', 'planned', None, 'none', False),
        # beta-2 R1 B2: planned -> fixed without RV must FAIL
        ('planned', 'fixed', X_TASK, 'none', False),
    ]
    for pk, cs, cfi, rvk, expected_ok in key_scenarios:
        assert (pk, cs, cfi, rvk) in _ALL_CASES
        built = _build_pair(base_doc, target_cid, pk, cs, cfi, rvk)
        assert built is not None
        prior_doc, cur_doc, prior_state, prior_rv, cur_rv = built
        spec_ok, _ = _expected_spec(prior_state, prior_rv, cs, cfi, cur_rv)
        assert spec_ok is expected_ok
        fails = [f for f in sr.check_monotonic(prior_doc, cur_doc) if target_cid in f]
        assert (not fails) is expected_ok


def test_spec_uses_real_repo_registry_cause_and_existing_nodes() -> None:
    base_doc = _load_repo_registry()
    planned_causes = [c for c in base_doc['causes'] if c['status'] == 'planned']
    assert len(planned_causes) >= 1
    reg_test_src = (REPO_ROOT / 'scripts' / 'tests' / 'test_s1_registry.py').read_bytes().decode('utf-8')
    for node in (T1_NODE, T2_NODE):
        fn_name = node.split('::')[-1]
        assert f'def {fn_name}(' in reg_test_src
