# -*- coding: utf-8 -*-
"""C9 R3 real-Git S1 credential positive and fail-closed controls."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import c9_s1_capture_guard as c9
from test_c9_base_guard import fixture, git, snapshot

TASK = 'B119-S1-SYNTHETIC'


def encode(v):
    return (json.dumps(v, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')


def install(work, base):
    """Synthetic capture has real Git bundle HEAD but no actual recovery permission."""
    git(work, 'switch', '-qc', 'batch/historical-s1')
    (work/'s1.txt').write_text('S1 must stay safe\n')
    git(work, 'add', 's1.txt'); git(work, 'commit', '-qm', 'synthetic held S1')
    head = git(work, 'rev-parse', 'HEAD')
    git_dir = work/'.git'
    bundle_name = TASK + '-s1-unpublished.bundle'
    bundle = git_dir/bundle_name
    git(work, 'bundle', 'create', str(bundle), 'HEAD')
    records = {TASK + '-prompt.txt': b'original task prompt\n',
               TASK + '-control.json': encode({'task_id': TASK, 'halted': 'postcommit:POSTCOMMIT_NONZERO'})}
    source_files = [{'file': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                    for name, raw in records.items()]
    metadata = {'schema_version': 1, 'kind': 'S1_METADATA_ONLY', 'task_id': TASK,
                'step': 'postcommit', 's1_code': 'POSTCOMMIT_NONZERO',
                'complete_capture': False, 'files': source_files}
    records[TASK+'-s1-evidence.json'] = encode(metadata)
    records[TASK+'-s1-SHA256SUMS.txt'] = ''.join(e['sha256']+'  '+e['file']+'\n'
                            for e in source_files).encode('ascii')
    records[bundle_name] = bundle.read_bytes()
    records['git-snapshot.json'] = encode({'kind':'S1_GIT_SNAPSHOT', 'task_id': TASK,
                    'head_oid': head, 'base_oid': base, 'unpublished_commit_available': True})
    records['git-tracked-status.z'] = b''
    records['git-index.diff'] = b''
    records['git-worktree.diff'] = b''
    manifest = ''.join(hashlib.sha256(records[n]).hexdigest()+'  '+n+'\n'
                       for n in sorted(records)).encode('ascii')
    records['SHA256SUMS.txt'] = manifest
    zipbuf = io.BytesIO()
    with zipfile.ZipFile(zipbuf, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name in sorted(records):
            z.writestr(name, records[name])
    archive = zipbuf.getvalue()
    (git_dir/(TASK+'-s1-full-capture.zip')).write_bytes(archive)
    card = {'schema_version':1,'kind':'S1_FULL_CAPTURE','complete_capture':True,
            'task_id':TASK,'step':'postcommit','s1_code':'POSTCOMMIT_NONZERO',
            'base_oid':base,'head_oid':head, 'archive_file':TASK+'-s1-full-capture.zip',
            'archive_sha256': hashlib.sha256(archive).hexdigest(),
            'bundle_file':bundle_name,'manifest_sha256':hashlib.sha256(manifest).hexdigest(),
            'gate_records':'ARCHIVED','git_snapshot':'ARCHIVED',
            'publication_status':'NOT_CHECKED_NO_REMOTE_TRAFFIC',
            'archive_member_count':len(records)}
    (git_dir/(TASK+'-s1-full-capture.json')).write_bytes(encode(card))
    git(work, 'switch', '-q', 'main')
    return head


def test_valid_full_capture_bound_is_snapshot_only_and_preserves_original(tmp_path):
    origin, work, base = fixture(tmp_path)
    head = install(work, base)
    before = snapshot(work, origin)
    checked = c9.validate_capture(work, TASK, base)
    assert checked['status'] == 'SNAPSHOT_VERIFIED_ONLY' and checked['capture_head_oid'] == head
    assert checked['restoration_authorized'] is False and checked['deletion_authorized'] is False
    assert c9.assess(work, TASK, base) == {'status':'HOLD',
        'reason':'BASE_OR_LOCAL_HISTORY_OFF_HEAD_HISTORY_PRESERVE',
        'capture':'SNAPSHOT_VERIFIED_ONLY','authorization':'NONE'}
    assert snapshot(work, origin) == before


def test_when_offhead_has_been_separately_handled_result_still_not_permission(tmp_path):
    origin, work, base = fixture(tmp_path)
    install(work, base)
    git(work, 'branch', '-D', 'batch/historical-s1')  # only synthetic fixture mutation
    before = snapshot(work, origin)
    assert c9.assess(work, TASK, base)['status'] == 'SNAPSHOT_VERIFIED_ONLY'
    assert snapshot(work, origin) == before
    assert c9.main(['--repo',str(work),'--s1-task-id',TASK,'--base-oid',base]) == 1


def test_missing_capture_holds_without_creating_files(tmp_path, capsys):
    origin, work, base = fixture(tmp_path)
    before = snapshot(work, origin)
    assert c9.main(['--repo',str(work),'--s1-task-id',TASK,'--base-oid',base]) == 1
    assert 'CAPTURE_MISSING' in capsys.readouterr().out
    assert before == snapshot(work, origin)


def test_metadata_only_is_never_promoted_to_full_capture(tmp_path):
    _,work,base=fixture(tmp_path)
    (work/'.git'/(TASK+'-s1-evidence.json')).write_bytes(encode({'kind':'S1_METADATA_ONLY'}))
    with pytest.raises(c9.CaptureGuardError, match='CAPTURE_MISSING'):
        c9.validate_capture(work,TASK,base)

@pytest.mark.parametrize('name', ['archive_sha256','base_oid','head_oid', 'complete_capture',
                                  'archive_member_count', 'publication_status'])
def test_invalid_card_fields_fail_closed(tmp_path, name):
    _,work,base=fixture(tmp_path);install(work,base)
    f=work/'.git'/(TASK+'-s1-full-capture.json');c=json.loads(f.read_text());c[name]='wrong'
    f.write_bytes(encode(c))
    with pytest.raises(c9.CaptureGuardError):c9.validate_capture(work,TASK,base)


def test_archive_corruption_holds(tmp_path):
    _,work,base=fixture(tmp_path);install(work,base)
    p=work/'.git'/(TASK+'-s1-full-capture.zip');p.write_bytes(p.read_bytes()+b'corrupt')
    with pytest.raises(c9.CaptureGuardError,match='CAPTURE_ARCHIVE_SHA_MISMATCH'):
        c9.validate_capture(work,TASK,base)


def test_bundle_corruption_holds(tmp_path):
    _,work,base=fixture(tmp_path);install(work,base)
    p=work/'.git'/(TASK+'-s1-unpublished.bundle');p.write_bytes(p.read_bytes()+b'corrupt')
    with pytest.raises(c9.CaptureGuardError):c9.validate_capture(work,TASK,base)


def test_symlink_capture_is_rejected(tmp_path):
    _,work,base=fixture(tmp_path);install(work,base)
    p=work/'.git'/(TASK+'-s1-full-capture.json');target=tmp_path/'data'
    target.write_bytes(p.read_bytes());p.unlink()
    try:p.symlink_to(target)
    except OSError as exc:
        if getattr(exc, 'winerror', None) == 1314:pytest.skip('Windows symlink privilege unavailable: winerror=1314')
        raise
    with pytest.raises(c9.CaptureGuardError, match='CAPTURE_UNSAFE'):
        c9.validate_capture(work,TASK,base)


def test_duplicate_json_keys_rejected(tmp_path):
    _,work,base=fixture(tmp_path);install(work,base)
    p=work/'.git'/(TASK+'-s1-full-capture.json')
    p.write_bytes(p.read_bytes()[:-2]+b',"task_id":"spoof"}\n')
    with pytest.raises(c9.CaptureGuardError, match='CAPTURE_CARD_INVALID'):
        c9.validate_capture(work,TASK,base)


def test_bad_task_path_not_read(tmp_path):
    _,work,base=fixture(tmp_path)
    assert c9.main(['--repo',str(work),'--s1-task-id','../secret','--base-oid',base])==1


def test_remote_drift_after_artifact_validation_still_holds(tmp_path):
    origin,work,base=fixture(tmp_path);install(work,base)
    other=tmp_path/'other';subprocess.run(['git','clone','-q',str(origin),str(other)],check=True)
    git(other,'config','user.name','Test');git(other,'config','user.email','test@example.invalid')
    (other/'x.txt').write_text('drift');git(other,'add','x.txt');git(other,'commit','-qm','drift')
    git(other,'push','-q','origin','main')
    assert 'BASE_OR_LOCAL_HISTORY_' in c9.assess(work,TASK,base)['reason']


def test_no_secret_names_are_emitted(tmp_path,capsys):
    _,work,base=fixture(tmp_path);install(work,base)
    assert c9.main(['--repo',str(work),'--s1-task-id',TASK,'--base-oid',base])==1
    output=capsys.readouterr().out
    assert 's1.txt' not in output and 'S1 must stay safe' not in output


def _repack(work, transform):
    git_dir = work/'.git'
    path = git_dir/(TASK+'-s1-full-capture.zip')
    with zipfile.ZipFile(path,'r') as z:
        content = {name:z.read(name) for name in z.namelist()}
    transform(content)
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name in sorted(content):z.writestr(name,content[name])
    card_path=git_dir/(TASK+'-s1-full-capture.json')
    card=json.loads(card_path.read_text())
    card['archive_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    card_path.write_bytes(encode(card))


def test_manifest_tamper_repacked_and_card_rebound_still_fails(tmp_path):
    _,work,base=fixture(tmp_path);install(work,base)
    _repack(work, lambda d:d.__setitem__('SHA256SUMS.txt',b'not original\n'))
    with pytest.raises(c9.CaptureGuardError,match='CAPTURE_MANIFEST_INVALID'):
        c9.validate_capture(work,TASK,base)


def test_control_tamper_repacked_and_card_rebound_still_fails(tmp_path):
    _,work,base=fixture(tmp_path);install(work,base)
    def alter(d):
        d[TASK+'-control.json']=encode({'task_id':TASK,'halted':'postcommit:OTHER_CODE'})
        d['SHA256SUMS.txt']=''.join(hashlib.sha256(d[n]).hexdigest()+'  '+n+'\n'
                    for n in sorted(d) if n!='SHA256SUMS.txt').encode('ascii')
    _repack(work,alter)
    card=work/'.git'/(TASK+'-s1-full-capture.json')
    j=json.loads(card.read_text())
    # Preserve a self-consistent outer manifest hash to expose inner cross-binding.
    with zipfile.ZipFile(work/'.git'/(TASK+'-s1-full-capture.zip')) as z:
        j['manifest_sha256']=hashlib.sha256(z.read('SHA256SUMS.txt')).hexdigest()
    card.write_bytes(encode(j))
    with pytest.raises(c9.CaptureGuardError,match='CAPTURE_CONTROL_MISMATCH'):
        c9.validate_capture(work,TASK,base)


def test_git_bundle_head_claim_mismatch_holds(tmp_path):
    _,work,base=fixture(tmp_path);install(work,base)
    p=work/'.git'/(TASK+'-s1-full-capture.json');data=json.loads(p.read_text())
    data['head_oid']='b'*40;p.write_bytes(encode(data))
    with pytest.raises(c9.CaptureGuardError,match='CAPTURE_BUNDLE_HEAD_MISMATCH'):
        c9.validate_capture(work,TASK,base)


def test_zip_member_injection_even_with_outer_sha_rebound_fails(tmp_path):
    _,work,base=fixture(tmp_path);install(work,base)
    def add(d):d['../old-s1.txt']=b'unsafe'
    _repack(work,add)
    with pytest.raises(c9.CaptureGuardError,match='CAPTURE_ZIP_INVENTORY_INVALID'):
        c9.validate_capture(work,TASK,base)


def test_synthetic_s1_capture_never_returns_cli_success(tmp_path,capsys):
    _,work,base=fixture(tmp_path);install(work,base)
    for flag in (True, False):
        if flag:git(work,'branch','-D','batch/historical-s1')
        assert c9.main(['--repo',str(work),'--s1-task-id',TASK,'--base-oid',base])==1
        result=json.loads(capsys.readouterr().out.split('=',1)[1])
        assert result['authorization']=='NONE' and result['status'] in ('HOLD','SNAPSHOT_VERIFIED_ONLY')


def test_archive_member_count_contract_matches_real_producer_source():
    # This is a producer/consumer contract test, not a count-only fixture.
    import inspect
    from s1_full_capture import create_full_capture
    source = inspect.getsource(create_full_capture)
    assert "content['SHA256SUMS.txt'] = manifest" in source
    assert "'archive_member_count': len(content)" in source


def test_real_s1_full_capture_producer_crosscompatible(tmp_path):
    """Use the actual current producer, not a hand-crafted fixture/schema guess."""
    import test_s1_full_capture as producer
    root = tmp_path / 'producer_repo'
    base = producer.fixture(root)
    produced = producer.capture(root, base)
    assert produced[0].startswith('S1_FULL_CAPTURE_FILE=')
    checked = c9.validate_capture(root, producer.TASK, base)
    assert checked['status'] == 'SNAPSHOT_VERIFIED_ONLY'
    assert checked['restoration_authorized'] is False
    assert checked['deletion_authorized'] is False
    assert checked['member_count'] >= 10
