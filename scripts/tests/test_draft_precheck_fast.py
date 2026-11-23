# -*- coding: utf-8 -*-
"""Alpha 2 (D3 / TD-115): tests and E27 failure controls for scripts/draft_precheck.py --fast.

Commitment -> test table (E27):
  F1 --fast runs 5 fast stages, emits FAST_PRECHECK PASS, writes fast-result.json only   test_f1_*
  F2 Anti-substitution: replaces_full_precheck=False, no draft-state/draft-result,
     --fast --resume rejected, and --resume on fast workdir fails closed                test_f2_*
  F3 Real-repo binding & pre-apply guards enforced in --fast mode                        test_f3_*
  F4 Stage failures (as_if, traceability, check20) fail closed with FAST_PRECHECK FAIL   test_f4_*
  F5 fast_validate: validate_skills, focused binding, pytest collect, pure-state N/A     test_f5_*
  F6 --fast never creates baseclone, never runs verify_all, checks SOURCE_MODIFIED       test_f6_*
  F7 End-to-end --fast on real-repo fixture (REAL collect & NOT_APPLICABLE pure-state)   test_f7_*
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import draft_precheck as q2


def _build_fast_sim_source(tmp_path, *, real_repo=False):
    source = tmp_path / 'source'
    source.mkdir()
    subprocess.run(['git', 'init', '-q', str(source)], check=True)
    for k, v in (('user.name', 'Q2'), ('user.email', 'q2@example.test')):
        subprocess.run(['git', '-C', str(source), 'config', k, v], check=True)
    files = {
        'docs/TASKBOARD.md': '# task\nprevious\n',
        'docs/fingerprints/exec-latest.json': '{}\n',
        'docs/governance/execution-record.json': '{}\n',
        'scripts/fingerprint.py': (
            'import pathlib, sys\n'
            'pathlib.Path("docs/fingerprints/exec-latest.json").write_bytes(b"{\\"ok\\":1}\\n")\n'
        ),
        'scripts/execution_record.py': (
            'import pathlib, sys\n'
            'pathlib.Path("docs/governance/execution-record.json").write_bytes(b"{\\"ok\\":1}\\n") '
            'if sys.argv[1] == "write" else None\n'
        ),
        'scripts/check_consistency.py': (
            'def _c20_column_failures(root):\n'
            '    return [], ["CHECK20_COLUMN_SCAN NON_PINNED=0 PINNED=1"]\n'
        ),
        'scripts/verify_all.py': (
            'raise AssertionError("verify_all.py must never be invoked in --fast mode")\n'
        ),
        'scripts/generate_rule_traceability.py': 'print("TRACEABILITY PASS")\n',
    }
    if real_repo:
        files['scripts/batch_sim.py'] = '# real repo marker\n'
        files['scripts/validate_skills.py'] = 'print("SKILLS PASS")\n'
        files['scripts/tests/test_sample.py'] = 'def test_ok():\n    assert True\n'
    for rel, body in files.items():
        target = source / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body.encode('utf-8'))
    subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(source), 'commit', '-qm', 'base'], check=True)
    base = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()

    (source / 'docs/TASKBOARD.md').write_bytes(b'# task\nprevious\nchanged\n')
    patch = tmp_path / 'author.patch'
    patch.write_bytes(subprocess.check_output(['git', '-C', str(source), 'diff', '--binary', '--', 'docs/TASKBOARD.md']))
    subprocess.run(['git', '-C', str(source), 'checkout', '--', 'docs/TASKBOARD.md'], check=True)

    plan = tmp_path / 'plan.json'
    pj = {
        'task_id': 'B117-FAST-TEST-261123',
        'base_oid': base,
        'allowed_paths': ['docs/TASKBOARD.md', *q2.GENERATED],
        'required_paths': ['docs/TASKBOARD.md', *q2.GENERATED],
    }
    plan.write_bytes((json.dumps(pj, sort_keys=True) + '\n').encode('utf-8'))
    return source, patch, plan, base


def test_f1_fast_mode_synthetic_pass_and_output_contract(tmp_path, capsys):
    source, patch, plan, base = _build_fast_sim_source(tmp_path)
    work = tmp_path / 'work_fast'
    rc = q2.main(['--fast', '--source', str(source), '--patch', str(patch),
                  '--plan', str(plan), '--workdir', str(work)])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'FAST_PRECHECK STEP generate PASS' in out
    assert 'FAST_PRECHECK STEP fast_validate SYNTHETIC_MINI_REPO_ONLY' in out
    assert 'FAST_PRECHECK PASS' in out
    assert 'DRAFT_PRECHECK RESULT' not in out
    assert 'SIX_STEPS_PASS' not in out

    fast_json = work / 'fast-result.json'
    assert fast_json.is_file()
    data = json.loads(fast_json.read_bytes())
    assert data['schema_version'] == 1
    assert data['mode'] == 'FAST_ONLY_NOT_FULL_PRECHECK'
    assert data['replaces_full_precheck'] is False
    assert data['overall'] == 'FAST_PRECHECK_PASS'
    assert data['skipped_full_stages'] == ['base_diff_verify_all', 'winemu_base_diff']
    assert data['FAST_VALIDATE'] == 'SYNTHETIC'
    assert [s['stage'] for s in data['completed']] == list(q2.FAST_STAGES)
    assert isinstance(data['elapsed_sec'], float) and data['elapsed_sec'] >= 0.0
    assert ('FAST_RESULT_JSON_SHA256=' + q2.sha_file(fast_json)) in out
    assert 'FAST_ELAPSED_SEC=' in out
    assert 'BASE_OID=' + base in out


def test_f2_anti_substitution_and_resume_guards(tmp_path, capsys):
    source, patch, plan, _ = _build_fast_sim_source(tmp_path)
    work = tmp_path / 'work_fast'
    assert q2.main(['--fast', '--source', str(source), '--patch', str(patch),
                    '--plan', str(plan), '--workdir', str(work)]) == 0
    capsys.readouterr()

    # Neither full-precheck state nor full-precheck result may be created by --fast.
    assert not (work / 'draft-result.json').exists()
    assert not (work / 'draft-state.json').exists()

    # Full-precheck --resume on a --fast workdir must fail closed.
    assert q2.main(['--resume', '--source', str(source), '--patch', str(patch),
                    '--plan', str(plan), '--workdir', str(work)]) == 1
    assert 'DRAFT_PRECHECK FAIL RESUME_STATE_MISSING' in capsys.readouterr().out

    # --fast --resume combination must always fail closed before cloning.
    work2 = tmp_path / 'work_fast_resume'
    assert q2.main(['--fast', '--resume', '--source', str(source), '--patch', str(patch),
                    '--plan', str(plan), '--workdir', str(work2)]) == 1
    assert 'FAST_PRECHECK FAIL FAST_RESUME_NOT_ALLOWED' in capsys.readouterr().out
    assert not (work2 / 'fast-result.json').exists()
    assert not (work2 / 'draft-result.json').exists()


@pytest.mark.parametrize('guard,setup_kind', [
    ('WINEMU_BINDING_REQUIRED', 'missing_binding'),
    ('PATCH_WHITESPACE', 'whitespace'),
    ('SHA_FORMAT_LINT_FAILED', 'short_sha'),
    ('NEWLINE_DIFF_LINT_FAILED', 'new_py_newline'),
    ('AUTHOR_TARGET_PARENT_DIRECTORY_MISSING', 'missing_parent'),
    ('AUTHOR_SCOPE_MISMATCH', 'undeclared_file'),
])
def test_f3_pre_apply_and_binding_guards_enforced_in_fast_mode(tmp_path, capsys, guard, setup_kind):
    source, patch, plan, base = _build_fast_sim_source(tmp_path, real_repo=(setup_kind == 'missing_binding'))
    if setup_kind == 'whitespace':
        (source / 'docs/TASKBOARD.md').write_bytes(b'# task\nprevious\ntrailing  \n')
        patch.write_bytes(subprocess.check_output(['git', '-C', str(source), 'diff', '--binary', '--', 'docs/TASKBOARD.md']))
        subprocess.run(['git', '-C', str(source), 'checkout', '--', 'docs/TASKBOARD.md'], check=True)
    elif setup_kind == 'short_sha':
        (source / 'docs/TASKBOARD.md').write_bytes(b'# task\nprevious\nSHA256=' + b'a' * 62 + b'\n')
        patch.write_bytes(subprocess.check_output(['git', '-C', str(source), 'diff', '--binary', '--', 'docs/TASKBOARD.md']))
        subprocess.run(['git', '-C', str(source), 'checkout', '--', 'docs/TASKBOARD.md'], check=True)
    elif setup_kind == 'new_py_newline':
        p = json.loads(plan.read_bytes())
        p['allowed_paths'] = sorted(['docs/TASKBOARD.md', 'scripts/added_bad.py', *q2.GENERATED])
        p['required_paths'] = p['allowed_paths']
        plan.write_bytes((json.dumps(p, sort_keys=True) + '\n').encode('utf-8'))
        (source / 'scripts/added_bad.py').write_bytes(b"open('x', 'w').write('a')\n")
        subprocess.run(['git', '-C', str(source), 'add', '-N', 'scripts/added_bad.py'], check=True)
        (source / 'docs/TASKBOARD.md').write_bytes(b'# task\nprevious\nchanged\n')
        patch.write_bytes(subprocess.check_output(['git', '-C', str(source), 'diff', '--binary']))
        subprocess.run(['git', '-C', str(source), 'reset', '-q', '--', 'scripts/added_bad.py'], check=True)
        (source / 'scripts/added_bad.py').unlink()
        subprocess.run(['git', '-C', str(source), 'checkout', '--', 'docs/TASKBOARD.md'], check=True)
    elif setup_kind == 'missing_parent':
        (source / 'newdir').mkdir()
        (source / 'newdir/x.md').write_bytes(b'added\n')
        subprocess.run(['git', '-C', str(source), 'add', '-N', 'newdir/x.md'], check=True)
        patch.write_bytes(subprocess.check_output(['git', '-C', str(source), 'diff', '--binary']))
        subprocess.run(['git', '-C', str(source), 'reset', '-q'], check=True)
        (source / 'newdir/x.md').unlink()
        (source / 'newdir').rmdir()
        p = json.loads(plan.read_bytes())
        p['allowed_paths'] = sorted(['newdir/x.md', *q2.GENERATED])
        p['required_paths'] = p['allowed_paths']
        plan.write_bytes((json.dumps(p, sort_keys=True) + '\n').encode('utf-8'))
    elif setup_kind == 'undeclared_file':
        (source / 'docs/extra.md').write_bytes(b'extra\n')
        subprocess.run(['git', '-C', str(source), 'add', '-N', 'docs/extra.md'], check=True)
        patch.write_bytes(subprocess.check_output(['git', '-C', str(source), 'diff', '--binary']))
        subprocess.run(['git', '-C', str(source), 'reset', '-q'], check=True)
        (source / 'docs/extra.md').unlink()

    work = tmp_path / ('work_' + guard)
    assert q2.main(['--fast', '--source', str(source), '--patch', str(patch),
                    '--plan', str(plan), '--workdir', str(work)]) == 1
    assert ('FAST_PRECHECK FAIL ' + guard) in capsys.readouterr().out
    assert not (work / 'fast-result.json').exists()
    assert not (work / 'draft-result.json').exists()


@pytest.mark.parametrize('failing_script,body,expected_code', [
    ('scripts/check_consistency.py', 'import sys\nsys.exit(1)\n', 'AS_IF_NONZERO'),
    ('scripts/generate_rule_traceability.py', 'import sys\nsys.exit(1)\n', 'TRACEABILITY_STALE'),
    ('scripts/check_consistency.py',
     'def _c20_column_failures(root):\n    return ["BAD_COLS"], []\n', 'CHECK20_NONZERO'),
])
def test_f4_fast_stages_fail_closed(tmp_path, capsys, failing_script, body, expected_code):
    source, patch, plan, _ = _build_fast_sim_source(tmp_path)
    (source / failing_script).write_bytes(body.encode('utf-8'))
    subprocess.run(['git', '-C', str(source), 'add', failing_script], check=True)
    subprocess.run(['git', '-C', str(source), 'commit', '-qm', 'fail-stage'], check=True)
    base = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    pj = json.loads(plan.read_bytes())
    pj['base_oid'] = base
    plan.write_bytes((json.dumps(pj, sort_keys=True) + '\n').encode('utf-8'))

    work = tmp_path / 'work'
    assert q2.main(['--fast', '--source', str(source), '--patch', str(patch),
                    '--plan', str(plan), '--workdir', str(work)]) == 1
    assert ('FAST_PRECHECK FAIL ' + expected_code) in capsys.readouterr().out
    assert not (work / 'fast-result.json').exists()


def _setup_fast_validate_real(tmp_path, monkeypatch, *, allowed_paths, focused_tests=(), skills_rc=0,
                              collect_rc=0, collect_stdout=b''):
    work = tmp_path / 'w'
    cand = work / 'candclone'
    (cand / 'scripts' / 'tests').mkdir(parents=True)
    for rel in [*allowed_paths, *focused_tests]:
        target = cand / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'# file\n')
    base = 'b' * 40
    d = {
        'task_id': 'B117-FV-TEST-261123',
        'base_oid': base,
        'kind': 'production',
        'code_files': {rel: rel for rel in focused_tests} if focused_tests else {},
        'new_files': {},
        'focused': {'pytest_args': ['-q', '-rs', *focused_tests], 'limit_sec': 1800} if focused_tests else None,
    }
    def_path = work / 'def.json'
    def_path.write_bytes(json.dumps(d).encode('utf-8'))
    plan_path = work / 'plan.json'
    plan_path.write_bytes(json.dumps({
        'task_id': 'B117-FV-TEST-261123',
        'base_oid': base,
        'allowed_paths': list(allowed_paths),
        'required_paths': list(allowed_paths),
    }).encode('utf-8'))
    prompt_path = work / 'prompt.txt'
    prompt_path.write_bytes(b'fast validate prompt\n')
    import production_template
    spec = {
        'kind': 'production',
        'base_oid': base,
        'task_id': 'B117-FV-TEST-261123',
        'focused': production_template.canonical_focused(d),
        'authors': {p: {'source': {'kind': 'base'}} for p in allowed_paths if p not in q2.GENERATED},
    }
    monkeypatch.setattr(q2.batch_runner, 'prompt_lines', lambda b: [])
    monkeypatch.setattr(q2.batch_runner, 'load_spec', lambda lines, task: spec)
    recorded_cmds = []

    def fake_cmd(args, cwd, *, timeout=240, log=None, env=None):
        recorded_cmds.append((list(args), env))
        if 'scripts/validate_skills.py' in args:
            out = b'SKILLS\n'
            if log:
                Path(log).write_bytes(out)
            return skills_rc, out
        if '--collect-only' in args:
            if log:
                Path(log).write_bytes(collect_stdout)
            return collect_rc, collect_stdout
        raise AssertionError(f'Unexpected subprocess in fast_validate_stage: {args}')

    monkeypatch.setattr(q2, 'cmd', fake_cmd)
    return work, def_path, prompt_path, plan_path, base, recorded_cmds


def test_f5_fast_validate_skills_and_collect_controls(tmp_path, monkeypatch):
    # 1. validate_skills non-zero fails closed
    w, d, pr, pl, base, _ = _setup_fast_validate_real(
        tmp_path / 'skills_fail', monkeypatch,
        allowed_paths=['scripts/tests/test_sample.py', *q2.GENERATED],
        focused_tests=['scripts/tests/test_sample.py'],
        skills_rc=1,
    )
    with pytest.raises(q2.DraftError, match='FAST_VALIDATE_SKILLS_NONZERO'):
        q2.fast_validate_stage(w, d, pr, pl, base, synthetic=False, timeout=60)

    # 2. broken test collection fails closed
    w, d, pr, pl, base, _ = _setup_fast_validate_real(
        tmp_path / 'collect_fail', monkeypatch,
        allowed_paths=['scripts/tests/test_sample.py', *q2.GENERATED],
        focused_tests=['scripts/tests/test_sample.py'],
        collect_rc=2, collect_stdout=b'SyntaxError\n',
    )
    with pytest.raises(q2.DraftError, match='FAST_COLLECT_NONZERO'):
        q2.fast_validate_stage(w, d, pr, pl, base, synthetic=False, timeout=60)

    # 3. one valid file + one empty test file -> FAST_COLLECT_EMPTY
    w, d, pr, pl, base, _ = _setup_fast_validate_real(
        tmp_path / 'empty_file', monkeypatch,
        allowed_paths=['scripts/tests/test_a.py', 'scripts/tests/test_empty.py', *q2.GENERATED],
        focused_tests=['scripts/tests/test_a.py', 'scripts/tests/test_empty.py'],
        collect_rc=0,
        collect_stdout=b'scripts/tests/test_a.py::test_one\n\n1 test collected in 0.1s\n',
    )
    with pytest.raises(q2.DraftError, match='FAST_COLLECT_EMPTY'):
        q2.fast_validate_stage(w, d, pr, pl, base, synthetic=False, timeout=60)

    # 4. valid focused collection with Windows backslashes + PYTEST_ADDOPTS stripped
    monkeypatch.setenv('PYTEST_ADDOPTS', '-k nothing')
    w, d, pr, pl, base, calls = _setup_fast_validate_real(
        tmp_path / 'ok', monkeypatch,
        allowed_paths=['scripts/tests/test_a.py', *q2.GENERATED],
        focused_tests=['scripts/tests/test_a.py'],
        collect_rc=0,
        collect_stdout=(
            b'scripts\\tests\\test_a.py::test_one\n'
            b'scripts\\tests\\test_a.py::test_two[x::y]\n\n'
            b'2 tests collected in 0.1s\n'
        ),
    )
    res = q2.fast_validate_stage(w, d, pr, pl, base, synthetic=False, timeout=60)
    assert res['STATUS'] == 'PASS'
    assert res['COLLECTED_TOTAL'] == 2
    assert res['COLLECTED_BY_FILE'] == {'scripts/tests/test_a.py': 2}
    collect_call_args, collect_env = calls[1]
    assert '--collect-only' in collect_call_args and '-q' in collect_call_args
    assert 'PYTEST_ADDOPTS' not in collect_env

    # 5. pure-state batch returns NOT_APPLICABLE_NO_FOCUSED without invoking pytest
    w, d, pr, pl, base, calls = _setup_fast_validate_real(
        tmp_path / 'pure', monkeypatch,
        allowed_paths=['docs/TASKBOARD.md', *q2.GENERATED],
        focused_tests=[],
    )
    res = q2.fast_validate_stage(w, d, pr, pl, base, synthetic=False, timeout=60)
    assert res['STATUS'] == 'NOT_APPLICABLE_NO_FOCUSED'
    assert res['COLLECT'] == 'NOT_APPLICABLE_NO_FOCUSED'
    assert len(calls) == 1  # validate_skills only, no pytest invocation

    # 6. code path with focused=None fails WINEMU_FOCUSED_REQUIRED_FOR_CODE
    w, d, pr, pl, base, _ = _setup_fast_validate_real(
        tmp_path / 'code_no_focus', monkeypatch,
        allowed_paths=['scripts/draft_precheck.py', *q2.GENERATED],
        focused_tests=[],
    )
    with pytest.raises(q2.DraftError, match='WINEMU_FOCUSED_REQUIRED_FOR_CODE'):
        q2.fast_validate_stage(w, d, pr, pl, base, synthetic=False, timeout=60)


def test_f6_fast_mode_uses_single_clone_no_verify_all_and_guards_source(tmp_path, capsys, monkeypatch):
    source, patch, plan, _ = _build_fast_sim_source(tmp_path)
    work = tmp_path / 'work'
    real_verify = q2.verify_stage

    def mutate_source_once(repo, stage, result_dir, *, timeout):
        if stage == 'check20':
            (source / 'dirty.tmp').write_bytes(b'dirty\n')
        return real_verify(repo, stage, result_dir, timeout=timeout)

    monkeypatch.setattr(q2, 'verify_stage', mutate_source_once)
    assert q2.main(['--fast', '--source', str(source), '--patch', str(patch),
                    '--plan', str(plan), '--workdir', str(work)]) == 1
    assert 'FAST_PRECHECK FAIL SOURCE_MODIFIED' in capsys.readouterr().out
    assert not (work / 'fast-result.json').exists()
    assert (work / 'candclone').exists()
    assert not (work / 'baseclone').exists()
    (source / 'dirty.tmp').unlink()


def test_f7_fast_mode_real_repo_end_to_end_collect_and_pure_state(tmp_path, capsys, monkeypatch):
    # 1. Code/test batch with real pytest --collect-only -q on a real-repo-shaped source
    s1 = tmp_path / 'real_code'
    s1.mkdir()
    source1, _, plan1, base1 = _build_fast_sim_source(s1, real_repo=True)
    # Create patch modifying scripts/tests/test_sample.py
    (source1 / 'scripts/tests/test_sample.py').write_bytes(
        b'def test_ok():\n    assert True\n\ndef test_second():\n    assert 1 == 1\n'
    )
    patch1 = s1 / 'code.patch'
    patch1.write_bytes(subprocess.check_output(
        ['git', '-C', str(source1), 'diff', '--binary', '--', 'scripts/tests/test_sample.py']
    ))
    subprocess.run(['git', '-C', str(source1), 'checkout', '--', 'scripts/tests/test_sample.py'], check=True)
    allowed1 = ['scripts/tests/test_sample.py', *q2.GENERATED]
    plan1.write_bytes((json.dumps({
        'task_id': 'B117-REAL-CODE-261123',
        'base_oid': base1,
        'allowed_paths': allowed1,
        'required_paths': allowed1,
    }, sort_keys=True) + '\n').encode('utf-8'))
    d1 = {
        'task_id': 'B117-REAL-CODE-261123',
        'base_oid': base1,
        'kind': 'production',
        'code_files': {'scripts/tests/test_sample.py': 'sample'},
        'new_files': {},
        'focused': None,
    }
    def1 = s1 / 'def.json'
    def1.write_bytes(json.dumps(d1).encode('utf-8'))
    prompt1 = s1 / 'prompt.txt'
    prompt1.write_bytes(b'real fast code prompt\n')
    import production_template
    spec1 = {
        'kind': 'production',
        'base_oid': base1,
        'task_id': 'B117-REAL-CODE-261123',
        'focused': production_template.canonical_focused(d1),
        'authors': {'scripts/tests/test_sample.py': {'source': {'kind': 'base'}}},
    }
    monkeypatch.setattr(q2.batch_runner, 'prompt_lines', lambda b: [])
    monkeypatch.setattr(q2.batch_runner, 'load_spec', lambda lines, task: spec1)

    work1 = s1 / 'work_fast'
    assert q2.main(['--fast', '--source', str(source1), '--patch', str(patch1),
                    '--plan', str(plan1), '--definition', str(def1), '--prompt', str(prompt1),
                    '--workdir', str(work1)]) == 0
    out1 = capsys.readouterr().out
    assert 'FAST_PRECHECK STEP fast_validate PASS' in out1
    assert 'FAST_PRECHECK PASS' in out1
    data1 = json.loads((work1 / 'fast-result.json').read_bytes())
    assert data1['FAST_VALIDATE'] == 'REAL'
    fv1 = data1['completed'][-1]['details']
    assert fv1['COLLECT'] == 'PASS' and fv1['COLLECTED_TOTAL'] == 2
    assert fv1['COLLECTED_BY_FILE'] == {'scripts/tests/test_sample.py': 2}
    assert not (work1 / 'draft-result.json').exists()

    # 2. Pure-state batch (focused=None, docs-only) on real-repo-shaped source
    s2 = tmp_path / 'real_pure'
    s2.mkdir()
    source2, patch2, plan2, base2 = _build_fast_sim_source(s2, real_repo=True)
    d2 = {'task_id': 'B117-FAST-TEST-261123', 'base_oid': base2, 'kind': 'production',
          'code_files': {}, 'new_files': {}, 'focused': None}
    def2 = s2 / 'def.json'
    def2.write_bytes(json.dumps(d2).encode('utf-8'))
    prompt2 = s2 / 'prompt.txt'
    prompt2.write_bytes(b'real fast pure prompt\n')
    spec2 = {'kind': 'production', 'base_oid': base2, 'task_id': 'B117-FAST-TEST-261123',
             'focused': None, 'authors': {'docs/TASKBOARD.md': {'source': {'kind': 'ops'}}}}
    monkeypatch.setattr(q2.batch_runner, 'load_spec', lambda lines, task: spec2)

    work2 = s2 / 'work_fast'
    assert q2.main(['--fast', '--source', str(source2), '--patch', str(patch2),
                    '--plan', str(plan2), '--definition', str(def2), '--prompt', str(prompt2),
                    '--workdir', str(work2)]) == 0
    out2 = capsys.readouterr().out
    assert 'FAST_PRECHECK STEP fast_validate NOT_APPLICABLE_NO_FOCUSED' in out2
    data2 = json.loads((work2 / 'fast-result.json').read_bytes())
    assert data2['FAST_VALIDATE'] == 'NOT_APPLICABLE'
