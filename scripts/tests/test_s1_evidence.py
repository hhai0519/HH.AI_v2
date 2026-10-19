# -*- coding: utf-8 -*-
"""B-119 G1 S1 metadata-only receipt positive and fail-closed controls."""
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from s1_evidence import EvidenceError, create_metadata  # noqa: E402
import batch_runner as runner  # noqa: E402

TASK = 'UNIT-S1-EVIDENCE-261019'
CODE = 'PRECOMMIT_NONZERO'
STEP = 'precommit'


def repo(tmp_path):
    (tmp_path / '.git').mkdir()
    control = {'task_id': TASK, 'halted': STEP + ':' + CODE, 'done': ['preflight']}
    (tmp_path / '.git' / (TASK + '-control.json')).write_text(json.dumps(control), encoding='utf-8')
    (tmp_path / '.git' / (TASK + '-prompt.txt')).write_bytes(b'contains secret PROMPT; do not print\n')
    (tmp_path / '.git' / (TASK + '-bounded-precommit.txt')).write_bytes(b'secret raw contents should NOT be printed\n')
    return tmp_path


def go(root, validate=None):
    return create_metadata(root, TASK, STEP, CODE, validate_artifact=validate or (lambda rel: None))


def assert_no_public_raw(lines):
    assert not any('secret' in x for x in lines)
    assert len(lines) == 3
    assert lines[2].startswith('S1_EVIDENCE_JSON=')


def test_metadata_manifest_exact_bytes_and_external_card(tmp_path):
    root = repo(tmp_path)
    output = go(root)
    assert_no_public_raw(output)
    p = json.loads(output[2].split('=', 1)[1])
    assert p['kind'] == 'S1_METADATA_ONLY'
    assert p['complete_capture'] is False
    assert p['unpublished_commit_bundle'] == p['git_snapshot'] == p['gate_records'] == 'NOT_COLLECTED'
    names = [r['file'] for r in p['files']]
    assert names == [TASK+'-prompt.txt', TASK+'-control.json', TASK+'-bounded-precommit.txt']
    b = (root/'.git'/(TASK+'-s1-SHA256SUMS.txt')).read_bytes()
    assert b and b'\r' not in b and b.endswith(b'\n')
    assert b == ''.join(r['sha256']+'  '+r['file']+'\n' for r in p['files']).encode('ascii')
    card = (root/'.git'/(TASK+'-s1-evidence.json')).read_bytes()
    assert hashlib.sha256(card).hexdigest() in output[0]
    assert hashlib.sha256(b).hexdigest() in output[1]
    assert card.decode('ascii').strip() == output[2].split('=',1)[1]
    assert (root/'.git'/(TASK+'-bounded-precommit.txt')).read_bytes().startswith(b'secret raw')


def test_rerun_cannot_overwrite_previous_evidence(tmp_path):
    root = repo(tmp_path)
    go(root)
    original = (root/'.git'/(TASK+'-s1-evidence.json')).read_bytes()
    with pytest.raises(FileExistsError):
        go(root)
    assert (root/'.git'/(TASK+'-s1-evidence.json')).read_bytes() == original


def test_tainted_control_or_wrong_task_fails_without_evidence(tmp_path):
    root = repo(tmp_path)
    c = root/'.git'/(TASK+'-control.json')
    c.write_text('{"task_id":"'+TASK+'","halted":"precommit:SUCCESS"}')
    with pytest.raises(EvidenceError, match='CONTROL_MISMATCH'):
        go(root)
    assert not (root/'.git'/(TASK+'-s1-evidence.json')).exists()
    c.write_text('{"task_id":"'+TASK+'","halted":"'+STEP+':'+CODE+'","halted":"'+STEP+':'+CODE+'"}')
    with pytest.raises(ValueError, match='duplicate'):
        go(root)


@pytest.mark.parametrize('bad', ['symlink', 'hardlink', 'directory', 'missing'])
def test_unsafe_capture_fails_no_ready(tmp_path, bad):
    root = repo(tmp_path)
    target = root/'.git'/(TASK+'-bounded-precommit.txt')
    if bad == 'symlink':
        target.unlink()
        try:
            target.symlink_to(root/'.git'/(TASK+'-prompt.txt'))
        except (OSError, NotImplementedError):
            pytest.skip('symlink unsupported')
    elif bad == 'hardlink':
        os.link(str(target), str(root/'linked.txt'))
    elif bad == 'directory':
        target.unlink()
        target.mkdir()
    elif bad == 'missing':
        target.unlink()
        (root/'.git'/(TASK+'-control.json')).unlink()
    with pytest.raises(EvidenceError):
        go(root)
    assert not (root/'.git'/(TASK+'-s1-evidence.json')).exists()


def test_guard_rejects_task_escape_without_read(tmp_path):
    root = repo(tmp_path)
    def reject(rel):
        if rel.endswith('control.json'):
            raise EvidenceError('ARTIFACT_PATH_GUARD_FAILED')
    with pytest.raises(EvidenceError):
        go(root, validate=reject)
    assert not (root/'.git'/(TASK+'-s1-evidence.json')).exists()


def test_partial_write_retains_original_and_no_ready(tmp_path, monkeypatch):
    root = repo(tmp_path)
    original = (root/'.git'/(TASK+'-control.json')).read_bytes()
    fn = __import__('s1_evidence')
    before = fn._create_once
    count = []
    def fail_second(directory, name, payload):
        count.append(name)
        if len(count) == 2:
            raise OSError('simulated interrupted disk write')
        return before(directory, name, payload)
    monkeypatch.setattr(fn, '_create_once', fail_second)
    with pytest.raises(OSError):
        go(root)
    assert (root/'.git'/(TASK+'-control.json')).read_bytes() == original
    assert (root/'.git'/(TASK+'-s1-evidence.json')).exists()
    assert not (root/'.git'/(TASK+'-s1-SHA256SUMS.txt')).exists()


def test_runner_preserves_primary_S1_if_evidence_fails(monkeypatch, capsys):
    class MockBatch:
        root = '/no/such/location'
        task_id = TASK
        def artifact(self, suffix):
            raise EvidenceError('blocked')
    runner.report_halt(runner.Halt(CODE), STEP)
    runner.report_s1_metadata(MockBatch(), STEP, runner.Halt(CODE))
    out = capsys.readouterr().out
    assert ('S1 '+CODE+' | step '+STEP) in out
    assert 'S1_EVIDENCE_STATUS=UNAVAILABLE' in out
    assert 'S1_EVIDENCE_FILE=' not in out


def test_runner_artifact_guard_exact_task_prefix(tmp_path, monkeypatch, capsys):
    root = repo(tmp_path)
    seen = []
    class MockBatch:
        task_id = TASK
        def __init__(self, root):
            self.root = str(root)
        def artifact(self, suffix):
            # A duplicated task prefix is not an exact source path.
            assert not suffix.startswith(TASK + '-'), suffix
            seen.append(suffix)
            return '.git/' + TASK + '-' + suffix
    runner.report_s1_metadata(MockBatch(root), STEP, runner.Halt(CODE))
    assert 'S1_EVIDENCE_JSON=' in capsys.readouterr().out
    assert 'control.json' in seen and 'prompt.txt' in seen
    assert 's1-evidence.json' in seen and 's1-SHA256SUMS.txt' in seen


def test_runner_artifact_guard_halt_keeps_primary_s1(tmp_path, capsys):
    root = repo(tmp_path)  # valid .git: guard must actually execute
    calls = []
    class BrokenBatch:
        task_id = TASK
        def __init__(self, root):
            self.root = str(root)
        def artifact(self, suffix):
            calls.append(suffix)
            raise runner.Halt('ARTIFACT_PATH_GUARD_FAILED')
    runner.report_halt(runner.Halt(CODE), STEP)
    runner.report_s1_metadata(BrokenBatch(root), STEP, runner.Halt(CODE))
    output = capsys.readouterr().out
    assert calls == ['prompt.txt']  # the actual guard, not a missing .git, failed
    assert output.splitlines() == [
        'S1 '+CODE+' | step '+STEP,
        'S1_EVIDENCE_STATUS=UNAVAILABLE',
    ]
    assert (root/'.git'/(TASK+'-control.json')).is_file()


def test_cross_task_artifact_is_never_enumerated(tmp_path):
    root = repo(tmp_path)
    # An existing historical S1 belongs to another task and is forbidden input.
    historical = root/'.git'/'B119-N7N8-POSTMAIN-STATE-R1-261018-bounded-postcommit.txt'
    historical.write_bytes(b'historical sensitive data kept as-is')
    output = go(root)
    p = json.loads(output[2].split('=', 1)[1])
    assert all(TASK in entry['file'] for entry in p['files'])
    assert b'historical sensitive data kept as-is' == historical.read_bytes()
    assert 'historical sensitive data' not in str(output)


def test_staged_native_bounded_capture_in_manifest(tmp_path):
    """Use the real Batch.bounded producer; its stage name is STAGED."""
    root = repo(tmp_path)
    (root/'.git'/(TASK+'-control.json')).write_text(json.dumps({
        'task_id': TASK, 'halted': 'stage:STAGED_NONZERO', 'done': ['preflight']}), encoding='utf-8')
    class Emitter:
        task_id = TASK
        def __init__(self,root):self.root = str(root)
        def artifact(self, suffix):
            return '.git/' + TASK + '-' + suffix
    with pytest.raises(runner.Halt, match='STAGED_NONZERO'):
        runner.Batch.bounded(Emitter(root), 'STAGED', ['-c', 'import sys;sys.stdout.write("raw staged capture\n");sys.exit(7)'], 15)
    staged = root/'.git'/(TASK+'-bounded-staged.txt')
    assert staged.is_file()
    lines = create_metadata(root, TASK, 'stage', 'STAGED_NONZERO', validate_artifact=lambda _: None)
    payload = json.loads(lines[2].split('=',1)[1])
    assert TASK+'-bounded-staged.txt' in [r['file'] for r in payload['files']]
    assert (TASK+'-bounded-staged.txt') in (root/'.git'/(TASK+'-s1-SHA256SUMS.txt')).read_text()


@pytest.mark.parametrize('target,change', [('json','whitespace'),('manifest','hex')])
def test_final_readback_must_bind_both_exact_output_bytes(tmp_path, monkeypatch, target, change):
    """A concurrent write after initial _create_once readback must cancel READY."""
    root = repo(tmp_path)
    import s1_evidence as se
    original_read = se._guarded_bytes
    jname = TASK+'-s1-evidence.json'
    mname = TASK+'-s1-SHA256SUMS.txt'
    mutated = []
    def before_final(directory,name):
        if name == jname and not mutated and (directory/mname).is_file():
            path = directory/(jname if target == 'json' else mname)
            raw = path.read_bytes()
            if target == 'json':
                path.write_bytes(b' ' + raw) # valid JSON, changed bytes
            else:
                first = b'0' if raw[:1] != b'0' else b'1'
                path.write_bytes(first + raw[1:]) # still valid hex manifest
            mutated.append(True)
        return original_read(directory,name)
    monkeypatch.setattr(se,'_guarded_bytes',before_final)
    with pytest.raises(EvidenceError,match='FINAL_BYTES_MISMATCH'):
        go(root)
    assert mutated == [True]
    assert (root/'.git'/(TASK+'-control.json')).is_file()
    assert (root/'.git'/(TASK+'-s1-evidence.json')).is_file()
    assert (root/'.git'/(TASK+'-s1-SHA256SUMS.txt')).is_file()


def test_handler_final_drift_keeps_s1_and_never_claims_ready(tmp_path,monkeypatch,capsys):
    root=repo(tmp_path)
    import s1_evidence as se
    read=se._guarded_bytes
    j=TASK+'-s1-evidence.json';m=TASK+'-s1-SHA256SUMS.txt'
    seen=[]
    def drift(directory,name):
        if name==j and not seen and (directory/m).exists():
            (directory/m).write_bytes(b'0' + (directory/m).read_bytes()[1:])
            seen.append(True)
        return read(directory,name)
    monkeypatch.setattr(se,'_guarded_bytes',drift)
    class Current:
        task_id=TASK
        def __init__(self,root):self.root=str(root)
        def artifact(self,suffix):return '.git/'+TASK+'-'+suffix
    runner.report_halt(runner.Halt(CODE), STEP)
    runner.report_s1_metadata(Current(root),STEP,runner.Halt(CODE))
    lines=capsys.readouterr().out.splitlines()
    assert lines==['S1 '+CODE+' | step '+STEP,'S1_EVIDENCE_STATUS=UNAVAILABLE']
    assert seen==[True]
