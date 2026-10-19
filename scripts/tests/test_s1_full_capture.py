# -*- coding: utf-8 -*-
"""G1 complete S1 evidence: real Git bundle and exact gate sidecar capture."""
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from s1_evidence import create_metadata  # noqa: E402
from s1_full_capture import create_full_capture, FullCaptureError  # noqa: E402
import gate_runner  # noqa: E402

TASK='UNIT-S1-FULL-CAPTURE-261019'


def git(root,*args):
    r=subprocess.run(['git',*args],cwd=root,capture_output=True,text=True,timeout=30)
    assert r.returncode==0,(args,r.stderr)
    return r.stdout.strip()


def fixture(root, committed=True):
    root.mkdir()
    git(root,'init','-q','-b','main');git(root,'config','user.name','Isolated Tester');git(root,'config','user.email','tests@example.invalid')
    (root/'file.txt').write_bytes(b'BASE\n')
    git(root,'add','file.txt');git(root,'commit','-qm','Base')
    base=git(root,'rev-parse','HEAD')
    git(root,'switch','-qc','batch/unit-s1-capture')
    if committed:
        (root/'file.txt').write_bytes(b'CANDIDATE\n');git(root,'add','file.txt');git(root,'commit','-qm','candidate')
    d=root/'.git'
    (d/(TASK+'-prompt.txt')).write_bytes(b'private prompt do not print\n')
    (d/(TASK+'-control.json')).write_text(json.dumps({'task_id':TASK,'halted':'postcommit:POSTCOMMIT_NONZERO','done':['preflight']}))
    (d/(TASK+'-bounded-postcommit.txt')).write_bytes(b'raw sensitive POSTCOMMIT output\n')
    gate_log = d/(TASK+'-local-gates.txt')
    code=gate_runner.run_stage(str(root),'POSTCOMMIT',[[sys.executable,'-c',"print('synthetic test gate'); raise SystemExit(5)"]],str(gate_log),timeout=30)
    assert code==5
    lines=create_metadata(root,TASK,'postcommit','POSTCOMMIT_NONZERO',validate_artifact=lambda rel:None)
    assert lines[0].startswith('S1_EVIDENCE_FILE=')
    return base


def capture(root,base):
    return create_full_capture(root,TASK,base,'batch/unit-s1-capture','postcommit','POSTCOMMIT_NONZERO',validate_artifact=lambda rel:None)


def test_valid_full_bundle_and_archive_roundtrip(tmp_path):
    root=tmp_path/'repo';base=fixture(root)
    result=capture(root,base)
    assert len(result)==3 and result[0].startswith('S1_FULL_CAPTURE_FILE=')
    assert 'raw sensitive' not in str(result) and 'private prompt' not in str(result)
    card=json.loads(result[2].split('=',1)[1]);assert card['complete_capture'] is True
    assert card['base_oid']==base and card['head_oid']==git(root,'rev-parse','HEAD')
    archive=root/'.git'/card['archive_file']
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==card['archive_sha256']
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert z.read(TASK+'-bounded-postcommit.txt')==b'raw sensitive POSTCOMMIT output\n'
        assert z.read(TASK+'-prompt.txt').startswith(b'private prompt')
        manifest=z.read('SHA256SUMS.txt').decode('ascii')
        for line in manifest.splitlines():
            h,name=line.split('  ')
            assert hashlib.sha256(z.read(name)).hexdigest()==h
        bundle=root/'.git'/card['bundle_file']
        assert z.read(card['bundle_file'])==bundle.read_bytes()
        assert git(root,'bundle','list-heads',str(bundle)).startswith(card['head_oid'])


def test_bundle_imported_in_fresh_bare_repository(tmp_path):
    root=tmp_path/'repo';base=fixture(root)
    card=json.loads(capture(root,base)[2].split('=',1)[1])
    bundle=root/'.git'/card['bundle_file']
    bare=tmp_path/'fresh.git';subprocess.run(['git','init','-q','--bare',str(bare)],check=True)
    p=subprocess.run(['git','-C',str(bare),'fetch',str(bundle),'HEAD:refs/heads/captured'],capture_output=True,text=True)
    assert p.returncode==0,p.stderr
    assert subprocess.check_output(['git','-C',str(bare),'rev-parse','refs/heads/captured'],text=True).strip()==card['head_oid']


def test_final_zip_byte_mutation_cancels_full_ready(tmp_path,monkeypatch):
    root=tmp_path/'repo';base=fixture(root)
    import s1_full_capture as mod
    original=mod._create_once
    def drift(git_dir,name,data):
        result=original(git_dir,name,data)
        target=git_dir/(TASK+'-s1-full-capture.zip')
        with target.open('ab') as f:f.write(b'UNEXPECTED')
        return result
    monkeypatch.setattr(mod,'_create_once',drift)
    with pytest.raises(FullCaptureError,match='FINAL_BYTES_DRIFT'):
        capture(root,base)
    assert (root/'.git'/(TASK+'-control.json')).exists()


@pytest.mark.parametrize('target', ['json','manifest'])
def test_stale_metadata_never_promotes_to_full_ready(tmp_path,target):
    root=tmp_path/'repo';base=fixture(root);d=root/'.git'
    if target=='manifest':
        path=d/(TASK+'-s1-SHA256SUMS.txt');raw=path.read_bytes()
        path.write_bytes((b'0' if raw[:1]!=b'0' else b'1')+raw[1:])
    else:
        path=d/(TASK+'-s1-evidence.json')
        obj=json.loads(path.read_text());obj['files'][0]['sha256']='0'*64
        path.write_text(json.dumps(obj)+'\n')
    with pytest.raises(FullCaptureError,match='METADATA_'):
        capture(root,base)
    assert not (d/(TASK+'-s1-full-capture.zip')).exists()


def test_no_unpublished_commit_must_not_claim_complete(tmp_path):
    root=tmp_path/'repo';base=fixture(root,committed=False)
    assert capture(root,base)==['S1_FULL_CAPTURE_STATUS=INCOMPLETE_NO_UNPUBLISHED_COMMIT']
    assert not (root/'.git'/(TASK+'-s1-full-capture.zip')).exists()


def test_missing_gate_log_never_full_ready(tmp_path):
    root=tmp_path/'repo';base=fixture(root);d=root/'.git'
    (d/(TASK+'-local-gates.txt')).unlink()
    assert capture(root,base)==['S1_FULL_CAPTURE_STATUS=INCOMPLETE_GATE_EVIDENCE']
    assert not (d/(TASK+'-s1-full-capture.zip')).exists()


def test_gate_log_raw_sidecar_is_included_exactly(tmp_path):
    root=tmp_path/'repo';base=fixture(root);d=root/'.git'
    side=TASK+'-local-gates.txt.postcommit-run1-gate1.raw'
    assert (d/side).is_file()
    expected=(d/side).read_bytes()
    r=capture(root,base);card=json.loads(r[2].split('=',1)[1]);assert r[0].startswith('S1_FULL_CAPTURE_FILE=')
    with zipfile.ZipFile(d/card['archive_file']) as z:assert z.read(side)==expected


def test_missing_gate_sidecar_fails_closed_with_no_full_ready(tmp_path):
    root=tmp_path/'repo';base=fixture(root);d=root/'.git'
    original=(d/(TASK+'-local-gates.txt')).read_text()
    (d/(TASK+'-local-gates.txt')).write_text(original.replace('RAW_EVIDENCE_FILE: ', 'RAW_EVIDENCE_FILE: WRONG-',1))
    with pytest.raises(FullCaptureError,match='SIDECAR_INVALID'):capture(root,base)
    assert not (d/(TASK+'-s1-full-capture.zip')).exists()


def test_invalid_raw_sidecar_name_rejected_before_reads(tmp_path):
    root=tmp_path/'repo';base=fixture(root);d=root/'.git'
    (d/(TASK+'-local-gates.txt')).write_text('RAW_EVIDENCE_FILE: ../../outside.txt\n')
    with pytest.raises(FullCaptureError,match='SIDECAR_INVALID'):capture(root,base)
    assert not (d/(TASK+'-s1-full-capture.zip')).exists()


def test_branch_mismatch_never_claims_full_ready(tmp_path):
    root=tmp_path/'repo';base=fixture(root)
    with pytest.raises(FullCaptureError,match='IDENTITY_UNSAFE'):
        create_full_capture(root,TASK,base,'batch/foreign','postcommit','POSTCOMMIT_NONZERO',validate_artifact=lambda _:None)


def test_untracked_files_never_claim_full_snapshot(tmp_path):
    root=tmp_path/'repo';base=fixture(root)
    (root/'untracked-secret.txt').write_text('private')
    assert capture(root,base)==['S1_FULL_CAPTURE_STATUS=INCOMPLETE_UNTRACKED_FILES']


def test_rerun_does_not_overwrite_bundle_or_original(tmp_path):
    root=tmp_path/'repo';base=fixture(root);first=capture(root,base)
    archive=first[0];d=root/'.git';raw=(d/(TASK+'-s1-full-capture.zip')).read_bytes()
    with pytest.raises(FullCaptureError,match='BUNDLE_EXISTS'):capture(root,base)
    assert (d/(TASK+'-s1-full-capture.zip')).read_bytes()==raw
    assert (d/(TASK+'-control.json')).is_file()


def test_wrapper_does_not_hide_original_halt(tmp_path,capsys):
    import batch_runner
    class B:
        def __init__(self,root,base):self.root=str(root);self.task_id=TASK;self.spec={'base_oid':base,'branch':'batch/unit-s1-capture'}
        def artifact(self,suffix):return '.git/'+self.task_id+'-'+suffix
    root=tmp_path/'repo';base=fixture(root,committed=False)
    batch_runner.report_halt(batch_runner.Halt('POSTCOMMIT_NONZERO'),'postcommit')
    batch_runner.report_s1_full_capture(B(root,base),'postcommit',batch_runner.Halt('POSTCOMMIT_NONZERO'))
    ls=capsys.readouterr().out.splitlines()
    assert ls[-2:]==['S1 POSTCOMMIT_NONZERO | step postcommit','S1_FULL_CAPTURE_STATUS=INCOMPLETE_NO_UNPUBLISHED_COMMIT']


def test_empty_native_gate_log_must_not_claim_full(tmp_path):
    root=tmp_path/'repo';base=fixture(root);d=root/'.git'
    (d/(TASK+'-local-gates.txt')).write_bytes(b'')
    assert capture(root,base)==['S1_FULL_CAPTURE_STATUS=INCOMPLETE_GATE_EVIDENCE']


def test_current_stage_bounded_missing_even_honest_receipt_never_full(tmp_path):
    root=tmp_path/'repo';base=fixture(root);d=root/'.git'
    (d/(TASK+'-bounded-postcommit.txt')).unlink()
    for nm in (TASK+'-s1-evidence.json', TASK+'-s1-SHA256SUMS.txt'):
        (d/nm).unlink()
    create_metadata(root,TASK,'postcommit','POSTCOMMIT_NONZERO',validate_artifact=lambda _:None)
    assert capture(root,base)==['S1_FULL_CAPTURE_STATUS=INCOMPLETE_GATE_EVIDENCE']


def test_peer_created_bundle_after_precheck_is_not_overwritten(tmp_path, monkeypatch):
    root=tmp_path/'repo';base=fixture(root);d=root/'.git'
    import s1_full_capture as mod
    actual=mod._git
    sentinel=b'EXISTING_EVIDENCE_DO_NOT_REPLACE\n'
    created=[False]
    def raced(repo,*args,**kwargs):
        result=actual(repo,*args,**kwargs)
        if args[:2]==('bundle','create') and not created[0]:
            with (d/(TASK+'-s1-unpublished.bundle')).open('xb') as f:f.write(sentinel)
            created[0]=True
        return result
    monkeypatch.setattr(mod,'_git',raced)
    with pytest.raises(FullCaptureError,match='BUNDLE_EXISTS'):
        capture(root,base)
    assert created==[True]
    assert (d/(TASK+'-s1-unpublished.bundle')).read_bytes()==sentinel
    assert not (d/(TASK+'-s1-full-capture.zip')).exists()


def test_bundle_mutation_between_verify_and_bytes_cancels_ready(tmp_path, monkeypatch):
    root=tmp_path/'repo';base=fixture(root)
    import s1_full_capture as mod
    actual=mod._git
    injected=[False]
    def raced(repo,*args,**kwargs):
        result=actual(repo,*args,**kwargs)
        if args[:2]==('bundle','list-heads') and not injected[0]:
            Path(args[2]).write_bytes(b'INVALID_BUNDLE_AFTER_VERIFY\n')
            injected[0]=True
        return result
    monkeypatch.setattr(mod,'_git',raced)
    with pytest.raises(FullCaptureError,match='BUNDLE_SOURCE_DRIFT'):
        capture(root,base)
    assert injected==[True]


def test_worktree_modification_between_status_and_diff_cancels_ready(tmp_path,monkeypatch):
    root=tmp_path/'repo';base=fixture(root)
    import s1_full_capture as mod
    actual=mod._git;injected=[False]
    def raced(repo,*args,**kwargs):
        result=actual(repo,*args,**kwargs)
        if args[:1]==('status',) and not injected[0]:
            (root/'file.txt').write_bytes(b'CONCURRENT_WORKTREE_DRIFT\n')
            injected[0]=True
        return result
    monkeypatch.setattr(mod,'_git',raced)
    with pytest.raises(FullCaptureError,match='GIT_DRIFT'):
        capture(root,base)
    assert injected==[True]


def test_untracked_added_after_first_read_cancels_ready(tmp_path,monkeypatch):
    root=tmp_path/'repo';base=fixture(root)
    import s1_full_capture as mod
    actual=mod._git;injected=[False]
    def raced(repo,*args,**kwargs):
        result=actual(repo,*args,**kwargs)
        if args[:1]==('ls-files',) and '--others' in args and not injected[0]:
            (root/'concurrent-untracked.txt').write_bytes(b'NOT_IN_SNAPSHOT\n')
            injected[0]=True
        return result
    monkeypatch.setattr(mod,'_git',raced)
    with pytest.raises(FullCaptureError,match='GIT_DRIFT'):
        capture(root,base)
    assert injected==[True]


def test_final_bundle_mutation_between_card_and_ready_rejected(tmp_path,monkeypatch):
    root=tmp_path/'repo';base=fixture(root);d=root/'.git'
    import s1_full_capture as mod
    actual=mod._create_once
    def raced(git_dir,name,raw):
        result=actual(git_dir,name,raw)
        (d/(TASK+'-s1-unpublished.bundle')).write_bytes(b'INVALID_AFTER_CARD\n')
        return result
    monkeypatch.setattr(mod,'_create_once',raced)
    with pytest.raises(FullCaptureError,match='FINAL_BYTES_DRIFT'):
        capture(root,base)


def test_gate_log_truncated_producer_record_not_complete(tmp_path):
    root=tmp_path/'repo';base=fixture(root);d=root/'.git'
    f=d/(TASK+'-local-gates.txt');b=f.read_bytes()
    f.write_bytes(b.split(b'EXIT_CODE:')[0])
    assert capture(root,base)==['S1_FULL_CAPTURE_STATUS=INCOMPLETE_GATE_EVIDENCE']


def test_git_index_changes_between_collects_cancel_full(tmp_path,monkeypatch):
    root=tmp_path/'repo';base=fixture(root)
    import s1_full_capture as mod
    actual=mod._git;injected=[False]
    def raced(repo,*args,**kwargs):
        result=actual(repo,*args,**kwargs)
        if args[:2]==('ls-files','--stage') and not injected[0]:
            (root/'file.txt').write_bytes(b'CONCURRENT_INDEX_DRIFT\n')
            git(root,'add','file.txt')
            injected[0]=True
        return result
    monkeypatch.setattr(mod,'_git',raced)
    with pytest.raises(FullCaptureError,match='GIT_DRIFT'):
        capture(root,base)
    assert injected==[True]


def test_bundle_scratch_only_under_own_git_and_self_cleanup(tmp_path, monkeypatch):
    root=tmp_path/'repo';base=fixture(root)
    import s1_full_capture as mod
    actual=mod.tempfile.TemporaryDirectory
    observed=[]
    def constrained(*args, **kwargs):
        assert Path(kwargs['dir']).resolve() == (root/'.git').resolve()
        result=actual(*args, **kwargs)
        observed.append(Path(result.name))
        return result
    monkeypatch.setattr(mod.tempfile,'TemporaryDirectory',constrained)
    result=capture(root,base)
    assert result[0].startswith('S1_FULL_CAPTURE_FILE=')
    assert len(observed)==1
    assert not observed[0].exists()


def _fixture_push(root):
    base=fixture(root)
    d=root/'.git'
    for stage in ('PRECOMMIT','STAGED'):
        command=[[sys.executable,'-c',"print('native producer gate')"]]
        assert gate_runner.run_stage(str(root),stage,command,str(d/(TASK+'-local-gates.txt')),timeout=30)==0
        (d/(TASK+'-bounded-'+stage.lower()+'.txt')).write_bytes(b'native bounded '+stage.encode('ascii')+b'\n')
    (d/(TASK+'-control.json')).write_text(json.dumps({'task_id':TASK,'halted':'push:PUSH_FAILED','done':['preflight','precommit','stage','postcommit']}))
    for name in (TASK+'-s1-evidence.json',TASK+'-s1-SHA256SUMS.txt'):
        (d/name).unlink()
    create_metadata(root,TASK,'push','PUSH_FAILED',validate_artifact=lambda _:None)
    return base


def test_push_failure_uses_native_prior_gate_producers_without_fictitious_bounded_push(tmp_path):
    root=tmp_path/'repo';base=_fixture_push(root)
    result=create_full_capture(root,TASK,base,'batch/unit-s1-capture','push','PUSH_FAILED',validate_artifact=lambda _:None)
    assert result[0].startswith('S1_FULL_CAPTURE_FILE=')
    card=json.loads(result[2].split('=',1)[1])
    with zipfile.ZipFile(root/'.git'/card['archive_file']) as z:
        assert TASK+'-bounded-push.txt' not in z.namelist()
        for stage in ('precommit','staged','postcommit'):
            assert TASK+'-bounded-'+stage+'.txt' in z.namelist()


def test_push_missing_real_prior_bounded_is_incomplete(tmp_path):
    root=tmp_path/'repo';base=_fixture_push(root)
    (root/'.git'/(TASK+'-bounded-staged.txt')).unlink()
    # Honest metadata must be reconstructed when a producer output is absent.
    for name in (TASK+'-s1-evidence.json',TASK+'-s1-SHA256SUMS.txt'):
        (root/'.git'/name).unlink()
    create_metadata(root,TASK,'push','PUSH_FAILED',validate_artifact=lambda _:None)
    assert create_full_capture(root,TASK,base,'batch/unit-s1-capture','push','PUSH_FAILED',validate_artifact=lambda _:None)==['S1_FULL_CAPTURE_STATUS=INCOMPLETE_GATE_EVIDENCE']
