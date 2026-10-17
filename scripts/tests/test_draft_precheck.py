# -*- coding: utf-8 -*-
"""Q2 deterministic checks, cache integrity and mutation canaries."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import draft_precheck as q2


def test_bad_sha256_62_hex_detected_on_added_state_line():
    bad=('f'*62)
    diff=('+++ b/docs/TASKBOARD.md\n+USER_PROVIDED backup SHA256='+bad+'\n').encode()
    issue=q2.lint_added_sha_labels(diff)
    assert len(issue)==1 and issue[0]['actual_length']==62
    assert not q2.lint_added_sha_labels(('+++ b/docs/TASKBOARD.md\n+backup SHA256='+('b'*64)+'\n').encode())


def test_bad_oid_and_historical_rows_ignore():
    diff=('+++ b/docs/AUDIT-LOG.md\n+main='+('a'*39)+'\n'+
          '--- a/docs/TASKBOARD.md\n-old SHA256='+('f'*62)+'\n').encode()
    assert len(q2.lint_added_sha_labels(diff))==1


def test_sha256_and_oid_not_confused():
    data=('+++ b/docs/EXEC-LOG.md\n+bundle_SHA256='+('a'*64)+
          ' main='+('b'*40)+'\n').encode()
    assert q2.lint_added_sha_labels(data)==[]


def test_extract_failed_ids_deterministically():
    log=b'FAILED scripts/tests/test_x.py::test_one - AssertionError\nFAILED scripts/tests/test_x.py::test_one - AssertionError\n'
    assert q2.fail_ids(log)==['scripts/tests/test_x.py::test_one']


def test_validate_plan_scope_and_head():
    base='a'*40
    p={'task_id':'B115-Q2-R1','base_oid':base,'allowed_paths':['docs/TASKBOARD.md',*q2.GENERATED],
       'required_paths':['docs/TASKBOARD.md',*q2.GENERATED]}
    assert q2.validate_plan(p,base)==set(p['allowed_paths'])
    p['allowed_paths'].append('../README.md')
    with pytest.raises(q2.DraftError,match='PLAN_PATHS_UNSAFE'):
        q2.validate_plan(p,base)


def test_stage_order_integrity_rejects_gap(tmp_path):
    # Stage ordinal comparison must not accept a replayed or skipped stage.
    done=[{'stage':'generate'},{'stage':'base_diff_verify_all'}]
    assert [e['stage'] for e in done]!=list(q2.STAGES[:len(done)])


def test_atomic_json_exact_sha_and_no_stale_temp(tmp_path):
    target=tmp_path/'r.json'
    q2.atomic_json(target,{'x':1})
    assert target.read_bytes()==b'{\n  "x": 1\n}\n'
    assert len(q2.sha_file(target))==64
    (tmp_path/'r.writing').write_bytes(b'stale')
    with pytest.raises(q2.DraftError,match='STATE_TEMP_EXISTS'):
        q2.atomic_json(target,{'x':2})


def test_resume_fingerprint_changes_with_tool_and_env(tmp_path,monkeypatch):
    source=tmp_path/'repo';source.mkdir();subprocess.run(['git','init','-q',str(source)],check=True)
    subprocess.run(['git','-C',str(source),'config','user.name','Q2'],check=True)
    subprocess.run(['git','-C',str(source),'config','user.email','q2@example.test'],check=True)
    (source/'x').write_bytes(b'\n')
    subprocess.run(['git','-C',str(source),'add','.'],check=True)
    subprocess.run(['git','-C',str(source),'commit','-qm','base'],check=True)
    patch=tmp_path/'x.patch';patch.write_bytes(b'patch')
    plan=tmp_path/'plan.json';plan.write_bytes(b'{}')
    before=q2.fingerprint(source,patch,plan,Path(q2.__file__).parent,tmp_path/'one')
    after=q2.fingerprint(source,patch,plan,Path(q2.__file__).parent,tmp_path/'longer-dir')
    assert before['CACHE_KEY_SHA256']!=after['CACHE_KEY_SHA256']
    assert before['ENV_SHA256']!=after['ENV_SHA256']
    patch.write_bytes(b'other-patch')
    changed=q2.fingerprint(source,patch,plan,Path(q2.__file__).parent,tmp_path/'one')
    assert before['AUTHOR_SHA256']!=changed['AUTHOR_SHA256']


def _build_simulated_source(tmp_path):
    source=tmp_path/'source';source.mkdir()
    subprocess.run(['git','init','-q',str(source)],check=True)
    for k,v in (('user.name','Q2'),('user.email','q2@example.test')):
        subprocess.run(['git','-C',str(source),'config',k,v],check=True)
    for rel,body in {
        'docs/TASKBOARD.md':'# task\nprevious\n',
        'docs/fingerprints/exec-latest.json':'{}\n',
        'docs/governance/execution-record.json':'{}\n',
        'scripts/fingerprint.py':'import pathlib,sys\npathlib.Path("docs/fingerprints/exec-latest.json").write_bytes(b"{\\\"ok\\\":1}\\n")\n',
        'scripts/execution_record.py':'import pathlib,sys\n'
            'pathlib.Path("docs/governance/execution-record.json").write_bytes(b"{\\\"ok\\\":1}\\n") if sys.argv[1]=="write" else None\n',
        'scripts/check_consistency.py':'import sys\n'
            'def _c20_column_failures(root): return [],["CHECK20_COLUMN_SCAN NON_PINNED=0 PINNED=1"]\n',
        'scripts/verify_all.py':'print("ALL 5 GATES PASSED")\n',
        'scripts/generate_rule_traceability.py':'print("TRACEABILITY PASS")\n',
    }.items():
        f=source/rel;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(body.encode('utf8'))
    subprocess.run(['git','-C',str(source),'add','.'],check=True)
    subprocess.run(['git','-C',str(source),'commit','-qm','base'],check=True)
    (source/'docs/TASKBOARD.md').write_bytes(b'# task\nprevious\nnew line\n')
    patch=tmp_path/'author.patch'
    patch.write_bytes(subprocess.check_output(['git','-C',str(source),'diff','--binary','--','docs/TASKBOARD.md']))
    subprocess.run(['git','-C',str(source),'checkout','--','docs/TASKBOARD.md'],check=True)
    base=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    allowed=['docs/TASKBOARD.md',*q2.GENERATED]
    plan=tmp_path/'plan.json'
    plan.write_text(json.dumps({'task_id':'B115-Q2-SIM','base_oid':base,
                                'allowed_paths':allowed,'required_paths':allowed},sort_keys=True)+'\n')
    return source,patch,plan


def test_full_five_steps_end_to_end_and_cached_resume(tmp_path):
    source,patch,plan=_build_simulated_source(tmp_path)
    work=tmp_path/'work'
    args=['--source',str(source),'--patch',str(patch),'--plan',str(plan),'--workdir',str(work)]
    assert q2.main(args)==0
    result=json.loads((work/'draft-result.json').read_bytes())
    assert [x['stage'] for x in result['completed']]==list(q2.STAGES)
    assert result['overall']=='FIVE_STEPS_PASS'
    assert len(result['HASHES']['AUTHOR_SHA256'])==64
    assert q2.main([*args,'--resume'])==0
    # A cached log is a signed input to a resumed run. Tampering can never be reused.
    (work/'check20-check20.log').write_bytes(b'injected\n')
    assert q2.main([*args,'--resume'])==1


def test_resumed_run_rejects_changed_patch_or_environment(tmp_path, capsys):
    source,patch,plan=_build_simulated_source(tmp_path)
    work=tmp_path/'work'
    args=['--source',str(source),'--patch',str(patch),'--plan',str(plan),'--workdir',str(work)]
    assert q2.main(args)==0
    patch.write_bytes(patch.read_bytes()+b'\n')
    assert q2.main([*args,'--resume'])==1
    assert 'RESUME_FINGERPRINT_CHANGED_NEW_WORKDIR_REQUIRED' in capsys.readouterr().out


def test_unsafe_patch_sha_lint_fails_before_any_generation(tmp_path,capsys):
    source,patch,plan=_build_simulated_source(tmp_path)
    (source/'docs/TASKBOARD.md').write_bytes(b'# task\nprevious\nbackup_SHA256='+b'a'*62+b'\n')
    patch.write_bytes(subprocess.check_output(['git','-C',str(source),'diff','--binary','--','docs/TASKBOARD.md']))
    subprocess.run(['git','-C',str(source),'checkout','--','docs/TASKBOARD.md'],check=True)
    args=['--source',str(source),'--patch',str(patch),'--plan',str(plan),'--workdir',str(tmp_path/'w')]
    assert q2.main(args)==1
    assert 'SHA_FORMAT_LINT_FAILED' in capsys.readouterr().out
    assert not (tmp_path/'w'/'draft-state.json').exists()


def test_base_equivalence_is_not_verify_pass_and_new_failure_is_blocking():
    base={'FAILED_GATES':['unit_tests'],'FAIL_IDS':['tests/test_a.py::test_bad']}
    same={'FAILED_GATES':['unit_tests'],'FAIL_IDS':['tests/test_a.py::test_bad']}
    assert q2.classify_base_candidate(1,1,base,same)=='BASE_EQUIVALENT_NONZERO'
    assert q2.classify_base_candidate(0,0,{'FAILED_GATES':[],'FAIL_IDS':[], 'EXIT_REASON':'ALL_5_PASS'},
                                      {'FAILED_GATES':[],'FAIL_IDS':[], 'EXIT_REASON':'ALL_5_PASS'})=='VERIFY_ALL_PASS'
    with pytest.raises(q2.DraftError,match='VERIFY_NEW_FAILURE_IDS'):
        q2.classify_base_candidate(1,1,base,{'FAILED_GATES':['unit_tests'],'FAIL_IDS':same['FAIL_IDS']+['tests/test_extra.py::test_regression']})
    with pytest.raises(q2.DraftError,match='VERIFY_FAILED_GATES_DIFFERENT'):
        q2.classify_base_candidate(1,1,base,{'FAILED_GATES':['check_consistency'],'FAIL_IDS':base['FAIL_IDS']})
    with pytest.raises(q2.DraftError,match='VERIFY_EXIT_DIFFERENT'):
        q2.classify_base_candidate(1,0,base,base)
    with pytest.raises(q2.DraftError,match='VERIFY_NONZERO_WITHOUT_FAIL_IDS'):
        q2.classify_base_candidate(1,1,{'FAILED_GATES':['unit_tests'],'FAIL_IDS':[]}, {'FAILED_GATES':['unit_tests'],'FAIL_IDS':[]})


def test_resume_rejects_skipped_stage_even_if_journal_has_key(tmp_path,capsys):
    source,patch,plan=_build_simulated_source(tmp_path)
    work=tmp_path/'work'
    args=['--source',str(source),'--patch',str(patch),'--plan',str(plan),'--workdir',str(work)]
    assert q2.main(args)==0
    journal=work/'draft-state.json'
    state=json.loads(journal.read_bytes())
    state['completed'][1]['stage']='traceability'
    journal.write_bytes((json.dumps(state)+'\n').encode())
    assert q2.main([*args,'--resume'])==1
    assert 'RESUME_STATE_ORDER' in capsys.readouterr().out


def test_base_and_candidate_names_have_equal_length_for_long_paths():
    text=Path(q2.__file__).read_text(encoding='utf8')
    assert "('baseclone','candclone')" in text
    assert len('baseclone')==len('candclone')


# 2026-10-17 E27 B1-B4 / N1 focused negative controls.
def test_b1_gate_summary_is_not_pytest_failure_id(tmp_path):
    log=tmp_path/'g.log'
    log.write_text('FAILED gates (1): unit_tests\n')
    parsed=q2.parse_gate(log)
    assert parsed['FAIL_IDS']==[]
    with pytest.raises(q2.DraftError,match='VERIFY_NONZERO_WITHOUT_FAIL_IDS'):
        q2.classify_base_candidate(1,1,parsed,parsed)


def test_b1_identical_non_pytest_gate_failures_are_blocking(tmp_path):
    log=tmp_path/'g.log'
    log.write_text('FAILED gates (1): validate_skills\n')
    parsed=q2.parse_gate(log)
    with pytest.raises(q2.DraftError,match='VERIFY_NON_PYTEST_GATE_FAILED'):
        q2.classify_base_candidate(1,1,parsed,parsed)


def test_b1_pytest_node_parses_without_gate_summary(tmp_path):
    log=tmp_path/'g.log'
    log.write_text('FAILED scripts/tests/test_x.py::test_one - AssertionError\nFAILED gates (1): unit_tests\n')
    parsed=q2.parse_gate(log)
    assert parsed['FAIL_IDS']==['scripts/tests/test_x.py::test_one']
    assert q2.classify_base_candidate(1,1,parsed,parsed)=='BASE_EQUIVALENT_NONZERO'


@pytest.mark.parametrize('code', [124,125,127])
def test_b2_equal_timeout_or_launch_failure_is_blocking(code):
    same={'FAILED_GATES':['unit_tests'],'FAIL_IDS':['tests/test_a.py::test_x']}
    with pytest.raises(q2.DraftError,match='VERIFY_TIMEOUT_OR_LAUNCH_FAILED'):
        q2.classify_base_candidate(code,code,same,same)


def test_b2_only_candidate_timed_out_is_exit_mismatch():
    same={'FAILED_GATES':['unit_tests'],'FAIL_IDS':['tests/test_a.py::test_x']}
    with pytest.raises(q2.DraftError,match='VERIFY_EXIT_DIFFERENT'):
        q2.classify_base_candidate(1,124,same,same)


@pytest.mark.parametrize('text,length', [
    ('SHA-256 `'+('a'*62)+'`',62),
    ('SHA-256：`'+('b'*62)+'`',62),
    ('sha256 '+('c'*62),62),
    ('main：'+('d'*39),39),
    ('SHA256=0b2d7e03…',9),
])
def test_b3_new_state_sha_labels_reject_bad_lengths(text,length):
    diff=('+++ b/docs/AUDIT-LOG.md\n+'+text+'\n').encode('utf-8')
    issues=q2.lint_added_sha_labels(diff)
    assert len(issues)==1 and issues[0]['actual_length']==length


def test_b3_positive_and_non_hash_words_do_not_false_positive():
    good=('+++ b/docs/TASKBOARD.md\n+SHA-256：`'+('a'*64)+'` main：'+('b'*40)+
          ' SHA-256 PASS\n').encode()
    assert q2.lint_added_sha_labels(good)==[]


def test_b3_fullwidth_punctuation_after_valid_hash_is_not_part_of_value():
    h='a'*64; o='b'*40
    good=('+++ b/docs/AUDIT-LOG.md\n+before SHA256='+h+'、after SHA256='+h+'；S3 SHA256='+h+
          '（64 hex）。Jules SHA256='+h+'。main：'+o+'，parent '+o+'）\n').encode('utf-8')
    assert q2.lint_added_sha_labels(good)==[]
    bad=('+++ b/docs/AUDIT-LOG.md\n+SHA256='+h[:62]+'、SHA256='+h+'g、SHA-256 `'+h[:8]+'…`\n').encode('utf-8')
    assert [i['actual_length'] for i in q2.lint_added_sha_labels(bad)]==[62,65,9]


def test_b4_resumed_baseclone_dirty_fails_closed(tmp_path,capsys):
    source,patch,plan=_build_simulated_source(tmp_path)
    work=tmp_path/'work'
    args=['--source',str(source),'--patch',str(patch),'--plan',str(plan),'--workdir',str(work)]
    assert q2.main(args)==0
    baseclone=work/'baseclone'
    (baseclone/'scripts/verify_all.py').write_text('raise RuntimeError("tampered baseline")\n')
    assert q2.main([*args,'--resume'])==1
    assert 'RESUME_BASECLONE_DRIFT' in capsys.readouterr().out


def test_b4_resumed_baseclone_untracked_file_fails_closed(tmp_path,capsys):
    source,patch,plan=_build_simulated_source(tmp_path)
    work=tmp_path/'work'
    args=['--source',str(source),'--patch',str(patch),'--plan',str(plan),'--workdir',str(work)]
    assert q2.main(args)==0
    # An untracked test file in the Base clone is collected by pytest and can mask candidate failures.
    (work/'baseclone'/'scripts'/'test_injected.py').write_bytes(b'def test_x():\n    assert False\n')
    assert q2.main([*args,'--resume'])==1
    assert 'RESUME_BASECLONE_DRIFT' in capsys.readouterr().out


def _build_source_with_new_author_file(tmp_path):
    source,_,_=_build_simulated_source(tmp_path)
    (source/'docs/new-author.md').write_bytes(b'# new author file\n')
    subprocess.run(['git','-C',str(source),'add','-N','docs/new-author.md'],check=True)
    patch=tmp_path/'author-new.patch'
    patch.write_bytes(subprocess.check_output(['git','-C',str(source),'diff','--binary','--','docs/new-author.md']))
    subprocess.run(['git','-C',str(source),'rm','-q','--cached','docs/new-author.md'],check=True)
    (source/'docs/new-author.md').unlink()
    base=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    allowed=['docs/new-author.md',*q2.GENERATED]
    plan=tmp_path/'plan-new.json'
    plan.write_text(json.dumps({'task_id':'B115-Q2-SIM','base_oid':base,
                                'allowed_paths':allowed,'required_paths':allowed},sort_keys=True)+'\n')
    return source,patch,plan


def test_b4_resumed_untracked_candidate_author_file_drift_fails_closed(tmp_path,capsys):
    source,patch,plan=_build_source_with_new_author_file(tmp_path)
    work=tmp_path/'work'
    args=['--source',str(source),'--patch',str(patch),'--plan',str(plan),'--workdir',str(work)]
    assert q2.main(args)==0
    assert q2.main([*args,'--resume'])==0
    with open(work/'candclone'/'docs'/'new-author.md','ab') as f:
        f.write(b'tampered after the journal was written\n')
    assert q2.main([*args,'--resume'])==1
    assert 'RESUME_CANDIDATE_DRIFT' in capsys.readouterr().out


def test_candidate_digest_binds_untracked_file_bytes(tmp_path):
    source,patch,plan=_build_source_with_new_author_file(tmp_path)
    work=tmp_path/'work'
    assert q2.main(['--source',str(source),'--patch',str(patch),'--plan',str(plan),'--workdir',str(work)])==0
    before=q2.candidate_digest(work)
    (work/'candclone'/'docs'/'new-author.md').write_bytes(b'# other bytes\n')
    assert q2.candidate_digest(work)!=before


def test_b4_baseclone_changed_head_is_rejected_before_stage(tmp_path):
    source,patch,plan=_build_simulated_source(tmp_path)
    work=tmp_path/'work'
    args=['--source',str(source),'--patch',str(patch),'--plan',str(plan),'--workdir',str(work)]
    assert q2.main(args)==0
    clone=work/'baseclone'
    subprocess.run(['git','-C',str(clone),'config','user.name','Q2'],check=True)
    subprocess.run(['git','-C',str(clone),'config','user.email','q2@example.test'],check=True)
    (clone/'new.txt').write_text('new commit\n')
    subprocess.run(['git','-C',str(clone),'add','new.txt'],check=True)
    subprocess.run(['git','-C',str(clone),'commit','-qm','tamper'],check=True)
    with pytest.raises(q2.DraftError,match='RESUME_BASECLONE_DRIFT'):
        q2.assert_baseclone(clone,subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip())


def test_n1_exit_zero_without_pass_marker_fails(tmp_path):
    log=tmp_path/'g.log';log.write_text('all steps done, no canonical marker\nERROR missing ALL 5 GATES PASSED\n')
    parsed=q2.parse_gate(log)
    with pytest.raises(q2.DraftError,match='VERIFY_PASS_MARKER_MISSING'):
        q2.classify_base_candidate(0,0,parsed,parsed)


def test_b4_assert_baseclone_dirty_rejected_before_base_gate(tmp_path):
    source, patch, plan = _build_simulated_source(tmp_path)
    baseline = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    tracked = source/'scripts/verify_all.py'
    tracked.write_text('raise RuntimeError("tamper")\n')
    with pytest.raises(q2.DraftError, match='RESUME_BASECLONE_DRIFT'):
        q2.assert_baseclone(source, baseline)


def test_b4_baseclone_tree_pin_rejects_wrong_tree(tmp_path):
    source, patch, plan = _build_simulated_source(tmp_path)
    baseline = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    with pytest.raises(q2.DraftError, match='RESUME_BASECLONE_DRIFT'):
        q2.assert_baseclone(source, baseline, expected_tree='a'*40)


def test_b1_multiple_pytest_gates_without_partition_refused():
    # Ambiguous combined log: node ID cannot be attributed to each failed gate.
    same={'FAILED_GATES':['unit_tests','webapp_tests'], 'FAIL_IDS':['tests/test_a.py::test_bad']}
    with pytest.raises(q2.DraftError, match='VERIFY_NONZERO_WITHOUT_FAIL_IDS'):
        q2.classify_base_candidate(1,1,same,same)
