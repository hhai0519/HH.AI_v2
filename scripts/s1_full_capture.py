#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B-119 G1: best-effort non-destructive local S1 capture; no deletion/network.

All binary evidence remains inside task-local .git artifacts. Only an exact-byte
verified, self-contained capture may be advertised as FULL_READY. An S1 before
an unpublished commit cannot satisfy the §9 bundle requirement and is INCOMPLETE.
The authoritative S1 cause is printed by batch_runner *before* invoking this.
"""
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path

from s1_evidence import EvidenceError, _guarded_bytes, _create_once, _reject_duplicate, TASK

SHA = re.compile(r'^[a-f0-9]{40}$')
RAW = re.compile(r'^[a-zA-Z0-9_-]+-local-gates\.txt\.(?:precommit|staged|postcommit)-run[1-9][0-9]*-gate[1-9][0-9]*\.raw$')
STAGES = ('focused', 'precommit', 'staged', 'postcommit')
MAX_ONE = 64 * 1024 * 1024
MAX_BUNDLE = 128 * 1024 * 1024
MAX_TOTAL = 192 * 1024 * 1024


class FullCaptureError(Exception):
    pass


def _git(root, *args, binary=False):
    """No remote traffic, no optional index lock, no command line shell or hooks."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0'})
    cmd = ['git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
           '-c', 'diff.external=', '-c', 'core.pager=cat', *args]
    try:
        cp = subprocess.run(cmd, cwd=str(root), env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise FullCaptureError('S1_CAPTURE_GIT_UNAVAILABLE') from e
    if cp.returncode != 0 or len(cp.stdout) > MAX_ONE:
        raise FullCaptureError('S1_CAPTURE_GIT_NONZERO')
    return cp.stdout if binary else cp.stdout.decode('utf-8', 'strict').strip()


def _guarded_large_bytes(directory, name, limit):
    """Exact guarded read for large bundle/zip outputs, rejecting inode swaps."""
    if '/' in name or '\\' in name or name in ('.', '..'):
        raise FullCaptureError('S1_CAPTURE_PATH_UNSAFE')
    path = directory / name
    try:
        st = path.lstat()
        if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > limit
                or (getattr(st, 'st_file_attributes', 0) & 0x400)):
            raise FullCaptureError('S1_CAPTURE_OUTPUT_UNSAFE')
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, 'rb') as f:
            opened = os.fstat(f.fileno())
            if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or
                    (opened.st_dev, opened.st_ino) != (st.st_dev, st.st_ino)):
                raise FullCaptureError('S1_CAPTURE_OUTPUT_CHANGED')
            data = f.read(limit+1)
            after = os.fstat(f.fileno())
            if len(data) != st.st_size or len(data) > limit or after.st_size != st.st_size:
                raise FullCaptureError('S1_CAPTURE_OUTPUT_CHANGED')
            return data
    except OSError as e:
        raise FullCaptureError('S1_CAPTURE_OUTPUT_UNAVAILABLE') from e


def _source(root, task, name, validate_artifact):
    if not name.startswith(task + '-'):
        raise FullCaptureError('S1_CAPTURE_TASK_MISMATCH')
    validate_artifact('.git/' + name)
    return _guarded_bytes(root, name)


def _read_task_artifacts(git_dir, task, validate_artifact):
    """Fixed producers + exact RAW_EVIDENCE_FILE sidecars, never enumerate .git."""
    names = [task + '-prompt.txt', task + '-control.json', task + '-s1-evidence.json',
             task + '-s1-SHA256SUMS.txt']
    for stage in STAGES:
        name = task + '-bounded-' + stage + '.txt'
        if os.path.lexists(git_dir / name):
            names.append(name)
    gates = task + '-local-gates.txt'
    if os.path.lexists(git_dir / gates):
        names.append(gates)
        data = _source(git_dir, task, gates, validate_artifact)
        try:
            lines = data.decode('utf-8', 'strict').splitlines()
        except UnicodeError as e:
            raise FullCaptureError('S1_CAPTURE_GATE_LOG_INVALID') from e
        seen = set()
        for line in lines:
            if line.startswith('RAW_EVIDENCE_FILE: '):
                name = line[len('RAW_EVIDENCE_FILE: '):]
                if (not RAW.fullmatch(name) or not name.startswith(task + '-')
                        or name in seen):
                    raise FullCaptureError('S1_CAPTURE_GATE_SIDECAR_INVALID')
                seen.add(name)
                names.append(name)
    results = {}
    if len(set(names)) != len(names) or len(names) > 80:
        raise FullCaptureError('S1_CAPTURE_DUPLICATE_OR_EXCESS')
    for name in names:
        results[name] = _source(git_dir, task, name, validate_artifact)
    return results


def _validate_gate_log(task, files, stage, code):
    """Verify native gate_runner record structure, not its success result.

    A S1 gate may fail; the required evidence is a complete FAIL/COMPLETE record
    and its exact raw sidecars, not EXIT_CODE: 0. Fail closed for truncated gates.
    """
    gate_name = task + '-local-gates.txt'
    # Push has no bounded-push producer. It may fail during fetch, push or
    # candidate CI, *after* PRECOMMIT / STAGED / POSTCOMMIT have completed.
    # Bind completeness to the actual native producers, never a fictitious file.
    required_bounded = ('precommit', 'staged', 'postcommit') if stage == 'push' else (stage,)
    for required in required_bounded:
        bounded = task + '-bounded-' + required + '.txt'
        if bounded not in files or not files[bounded]:
            raise FullCaptureError('S1_CAPTURE_CURRENT_BOUNDED_INCOMPLETE')
    if stage not in ('precommit', 'staged', 'postcommit', 'push'):
        return
    if gate_name not in files or not files[gate_name]:
        raise FullCaptureError('S1_CAPTURE_GATE_LOG_INCOMPLETE')
    try:
        raw_text = files[gate_name].decode('utf-8', 'strict')
    except UnicodeError as e:
        raise FullCaptureError('S1_CAPTURE_GATE_LOG_INCOMPLETE') from e
    if not raw_text.endswith('\n'):
        raise FullCaptureError('S1_CAPTURE_GATE_LOG_INCOMPLETE')
    lines = raw_text.splitlines()
    stage_up = stage.upper()
    start_pattern = re.compile(r'^=== (' + '|'.join(('PRECOMMIT','STAGED','POSTCOMMIT')) + r') RUN ([1-9][0-9]*) START ===$')
    starts = [(i, m.group(1), int(m.group(2))) for i,line in enumerate(lines)
              if (m := start_pattern.fullmatch(line))]
    required_gate_stages = ('PRECOMMIT','STAGED','POSTCOMMIT') if stage == 'push' else (stage_up,)
    if any(not any(name == item for _,name,_ in starts) for item in required_gate_stages):
        raise FullCaptureError('S1_CAPTURE_GATE_STAGE_MISSING')
    # Parse all run records, in producer order. Every gate requires exactly one
    # RAW sidecar and exit marker and must end with native final marker.
    idx = 0
    current_run = {}
    while idx < len(lines):
        m = start_pattern.fullmatch(lines[idx]);
        if not m: raise FullCaptureError('S1_CAPTURE_GATE_STRUCTURE_INVALID')
        stg, num = m.group(1), int(m.group(2))
        if num != current_run.get(stg, 0) + 1:
            raise FullCaptureError('S1_CAPTURE_GATE_STRUCTURE_INVALID')
        current_run[stg] = num
        idx += 1
        gate = 0
        while idx < len(lines):
            if lines[idx] == f'=== {stg} RUN {num} COMPLETE ===':
                if gate == 0: raise FullCaptureError('S1_CAPTURE_GATE_STRUCTURE_INVALID')
                idx += 1
                break
            mt = re.fullmatch(r'=== '+stg+r' RUN '+str(num)+r' FAILED AT GATE ([1-9][0-9]*) ===', lines[idx])
            if mt:
                if int(mt.group(1)) != gate or gate == 0:
                    raise FullCaptureError('S1_CAPTURE_GATE_STRUCTURE_INVALID')
                idx += 1
                break
            mt = re.fullmatch(r'=== '+stg+r' RUN '+str(num)+r' GATE ([1-9][0-9]*): .+ ===',lines[idx])
            if not mt or int(mt.group(1)) != gate + 1:
                raise FullCaptureError('S1_CAPTURE_GATE_STRUCTURE_INVALID')
            gate += 1; idx += 1
            sidecar = f'{task}-local-gates.txt.{stg.lower()}-run{num}-gate{gate}.raw'
            if idx >= len(lines) or lines[idx] != 'RAW_EVIDENCE_FILE: '+sidecar or sidecar not in files:
                raise FullCaptureError('S1_CAPTURE_GATE_RAW_MISSING')
            idx += 1
            while idx < len(lines) and (lines[idx].startswith('> ') or lines[idx].startswith('TREE_KILL: ')):
                idx += 1
            if idx >= len(lines) or not re.fullmatch(r'EXIT_CODE: (?:-?[0-9]+|TIMEOUT|LAUNCH_FAILED)', lines[idx]):
                raise FullCaptureError('S1_CAPTURE_GATE_EXIT_MISSING')
            exitcode = lines[idx][11:]; idx += 1
            if exitcode != '0':
                if idx >= len(lines) or lines[idx] != f'=== {stg} RUN {num} FAILED AT GATE {gate} ===':
                    raise FullCaptureError('S1_CAPTURE_GATE_STRUCTURE_INVALID')
                idx += 1
                break
        else:
            raise FullCaptureError('S1_CAPTURE_GATE_STRUCTURE_INVALID')
    # A complete gate transcript for the current stage is required, even on failure.
    # Earlier producer logs are optional, but any present run must be well formed.
    if any(item not in current_run for item in required_gate_stages):
        raise FullCaptureError('S1_CAPTURE_GATE_STAGE_MISSING')


def _snapshot_equal(first, second):
    return first[0] == second[0] and first[1] == second[1]


def _snapshot(root, task, base, expected_branch):
    """Require two stable snapshots of HEAD, index, worktree and untracked.

    Further comparison immediately before FULL_READY rejects mid-capture drift.
    """
    def collect():
        head = _git(root, 'rev-parse', '--verify', 'HEAD')
        branch = _git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD')
        parent = _git(root, 'rev-parse', '--verify', 'HEAD^') if head != base else None
        if (not SHA.fullmatch(head) or not SHA.fullmatch(base) or
                (parent is not None and parent != base) or branch != expected_branch):
            raise FullCaptureError('S1_CAPTURE_GIT_IDENTITY_UNSAFE')
        untracked = _git(root, 'ls-files', '--others', '--exclude-standard', '-z', binary=True)
        status = _git(root, 'status', '--porcelain=v1', '--untracked-files=no', '-z', binary=True)
        staged = _git(root, 'diff', '--cached', '--binary', '--no-ext-diff', binary=True)
        unstaged = _git(root, 'diff', '--binary', '--no-ext-diff', binary=True)
        index = _git(root, 'ls-files', '--stage', '-z', binary=True)
        if _git(root, 'rev-parse', '--verify', 'HEAD') != head or _git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD') != branch:
            raise FullCaptureError('S1_CAPTURE_GIT_DRIFT')
        return (head, branch, parent, untracked, status, staged, unstaged, index)
    first = collect()
    second = collect()
    if first != second:
        raise FullCaptureError('S1_CAPTURE_GIT_DRIFT')
    head, branch, parent, untracked, status, staged, unstaged, index = second
    meta = {'kind': 'S1_GIT_SNAPSHOT', 'task_id': task, 'base_oid': base,
            'head_oid': head, 'head_parent': parent, 'branch': branch,
            'unpublished_commit_available': head != base,
            'tracked_status_sha256': hashlib.sha256(status).hexdigest(),
            'index_sha256': hashlib.sha256(index).hexdigest()}
    if untracked:
        meta['untracked_state'] = 'NOT_COLLECTED'
    return meta, {'git-snapshot.json': (json.dumps(meta, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii'),
                  'git-tracked-status.z': status, 'git-index.diff': staged,
                  'git-worktree.diff': unstaged}


def _produce_bundle(root, task, head, git_dir, validate_artifact):
    """Build privately, verify captured bytes, publish using O_EXCL only.

    A peer's creation of the final path, even during git bundle create, cannot
    be replaced. All verification and ZIP capture bind to the same raw bytes.
    """
    name = task + '-s1-unpublished.bundle'
    validate_artifact('.git/' + name)
    path = git_dir / name
    if os.path.lexists(path):
        raise FullCaptureError('S1_CAPTURE_BUNDLE_EXISTS')
    # A private self-created scratch directory only under THIS task's .git root
    # is allowed. TemporaryDirectory removes only files it just created.
    # Historic S1 artifacts, other task files and pre-existing outputs remain untouched.
    with tempfile.TemporaryDirectory(prefix='hhai-s1-bundle-', dir=str(git_dir)) as temp:
        staging = Path(temp) / 'captured.bundle'
        _git(root, 'bundle', 'create', str(staging), 'HEAD')
        raw = staging.read_bytes() if staging.stat().st_size <= MAX_BUNDLE else None
        if not raw or len(raw) > MAX_BUNDLE:
            raise FullCaptureError('S1_CAPTURE_BUNDLE_UNSAFE')
        staged_sha = hashlib.sha256(raw).hexdigest()
        # Real native verification and real import, both on this captured file.
        _git(root, 'bundle', 'verify', str(staging))
        lines = _git(root, 'bundle', 'list-heads', str(staging)).splitlines()
        if not any(line.split()[:1] == [head] for line in lines):
            raise FullCaptureError('S1_CAPTURE_BUNDLE_IDENTITY')
        if _guarded_large_bytes(Path(temp), 'captured.bundle', MAX_BUNDLE) != raw:
            raise FullCaptureError('S1_CAPTURE_BUNDLE_SOURCE_DRIFT')
        bare = Path(temp)/'check.git'
        _git(root, 'init', '-q', '--bare', str(bare))
        # HEAD is the only allowed outgoing branch of this full-history bundle.
        _git(bare, 'fetch', str(staging), 'HEAD:refs/heads/checked')
        if _git(bare, 'rev-parse', 'refs/heads/checked') != head:
            raise FullCaptureError('S1_CAPTURE_BUNDLE_IMPORT_MISMATCH')
        if _guarded_large_bytes(Path(temp), 'captured.bundle', MAX_BUNDLE) != raw:
            raise FullCaptureError('S1_CAPTURE_BUNDLE_SOURCE_DRIFT')
        # No-replace publication: peer sentinel survives intact and raises.
        try:
            fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_BINARY',0),0o600)
            with os.fdopen(fd,'wb') as out:
                out.write(raw);out.flush();os.fsync(out.fileno())
        except FileExistsError as e:
            raise FullCaptureError('S1_CAPTURE_BUNDLE_EXISTS') from e
        if _guarded_large_bytes(git_dir, name, MAX_BUNDLE) != raw:
            raise FullCaptureError('S1_CAPTURE_BUNDLE_FINAL_DRIFT')
        # Digest was derived from verified/imported bytes; there is no second
        # independent buffer that can silently replace the ZIP member.
        assert hashlib.sha256(raw).hexdigest() == staged_sha
        return name, raw


def create_full_capture(root, task, base, branch, step, code, *, validate_artifact):
    """Return three bounded status lines only for an exact-byte-verified FULL_READY."""
    if not TASK.fullmatch(task) or not SHA.fullmatch(base) or not re.fullmatch(r'batch/[a-z0-9._-]+', branch) or not re.fullmatch(r'[a-z][a-z0-9_-]*', step) or not re.fullmatch(r'[A-Z][A-Z0-9_]*', code):
        raise FullCaptureError('S1_CAPTURE_ARGUMENT_INVALID')
    root = Path(root)
    git_dir = root / '.git'
    if not git_dir.is_dir() or git_dir.is_symlink():
        raise FullCaptureError('S1_CAPTURE_GITDIR_UNSAFE')
    files = _read_task_artifacts(git_dir, task, validate_artifact)
    try:
        control = json.loads(files[task+'-control.json'].decode('utf-8'), object_pairs_hook=_reject_duplicate)
        original = json.loads(files[task+'-s1-evidence.json'].decode('ascii'), object_pairs_hook=_reject_duplicate)
    except (UnicodeError, ValueError) as e:
        raise FullCaptureError('S1_CAPTURE_CONTROL_INVALID') from e
    if (control.get('task_id') != task or control.get('halted') != step+':'+code or
            original.get('task_id') != task or original.get('kind') != 'S1_METADATA_ONLY'):
        raise FullCaptureError('S1_CAPTURE_CONTROL_DRIFT')
    # Do not amplify a forged, stale, or concurrently edited METADATA_ONLY card.
    entries = original.get('files')
    if (original.get('complete_capture') is not False or not isinstance(entries, list)
            or not entries or len(entries) > 10):
        raise FullCaptureError('S1_CAPTURE_METADATA_UNTRUSTED')
    allowed_sources = {task+'-prompt.txt',task+'-control.json'}
    allowed_sources.update(task+'-bounded-'+stage+'.txt' for stage in STAGES)
    seen = set()
    for ent in entries:
        if not isinstance(ent, dict) or set(ent) != {'file','bytes','sha256'}:
            raise FullCaptureError('S1_CAPTURE_METADATA_UNTRUSTED')
        fname = ent['file']
        if (not isinstance(fname,str) or fname not in allowed_sources or fname in seen
                or fname not in files or type(ent['bytes']) is not int
                or ent['bytes'] != len(files[fname])
                or not isinstance(ent['sha256'],str)
                or ent['sha256'] != hashlib.sha256(files[fname]).hexdigest()):
            raise FullCaptureError('S1_CAPTURE_METADATA_SOURCE_DRIFT')
        seen.add(fname)
    metadata_manifest = ''.join(ent['sha256']+'  '+ent['file']+'\n' for ent in entries).encode('ascii')
    if metadata_manifest != files[task+'-s1-SHA256SUMS.txt']:
        raise FullCaptureError('S1_CAPTURE_METADATA_MANIFEST_DRIFT')
    try:
        _validate_gate_log(task, files, step, code)
    except FullCaptureError as err:
        if err.args and err.args[0].startswith(('S1_CAPTURE_CURRENT_BOUNDED','S1_CAPTURE_GATE_')):
            return ['S1_FULL_CAPTURE_STATUS=INCOMPLETE_GATE_EVIDENCE']
        raise
    snap, binary = _snapshot(root, task, base, branch)
    if snap.get('untracked_state') == 'NOT_COLLECTED':
        return ['S1_FULL_CAPTURE_STATUS=INCOMPLETE_UNTRACKED_FILES']
    if not snap['unpublished_commit_available']:
        return ['S1_FULL_CAPTURE_STATUS=INCOMPLETE_NO_UNPUBLISHED_COMMIT']
    if (code in ('PRECOMMIT_NONZERO', 'PRECOMMIT_TIMEOUT', 'PRECOMMIT_COMPLETION_UNPROVEN',
                 'STAGED_NONZERO', 'STAGED_TIMEOUT', 'STAGED_COMPLETION_UNPROVEN',
                 'POSTCOMMIT_NONZERO', 'POSTCOMMIT_TIMEOUT', 'POSTCOMMIT_COMPLETION_UNPROVEN')
            and task + '-local-gates.txt' not in files):
        return ['S1_FULL_CAPTURE_STATUS=INCOMPLETE_GATE_LOG']
    bundle_name, bundle_raw = _produce_bundle(root, task, snap['head_oid'], git_dir, validate_artifact)
    content = {name: raw for name,raw in files.items()}
    content.update(binary)
    content[bundle_name] = bundle_raw
    names = sorted(content)
    if sum(len(content[n]) for n in names) > MAX_TOTAL:
        raise FullCaptureError('S1_CAPTURE_TOTAL_TOO_LARGE')
    manifest = ''.join(hashlib.sha256(content[n]).hexdigest()+'  '+n+'\n' for n in names).encode('ascii')
    content['SHA256SUMS.txt'] = manifest
    name = task + '-s1-full-capture.zip'
    validate_artifact('.git/' + name)
    target = git_dir / name
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
    with os.fdopen(fd, 'wb') as out:
        with zipfile.ZipFile(out, mode='w', compression=zipfile.ZIP_DEFLATED, compresslevel=2) as z:
            for entry in sorted(content):
                z.writestr(entry, content[entry])
        out.flush()
        os.fsync(out.fileno())
    archive = _guarded_large_bytes(git_dir, name, MAX_TOTAL)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        if z.testzip() is not None or z.namelist() != sorted(content) or any(z.read(n) != content[n] for n in content):
            raise FullCaptureError('S1_CAPTURE_ARCHIVE_VERIFY_FAILED')
    # Bind post-production Git snapshot to the originally packaged observations.
    later_snap, later_binary = _snapshot(root, task, base, branch)
    if not _snapshot_equal((snap, binary), (later_snap, later_binary)):
        raise FullCaptureError('S1_CAPTURE_GIT_DRIFT')
    if later_snap.get('untracked_state') == 'NOT_COLLECTED':
        raise FullCaptureError('S1_CAPTURE_UNTRACKED_DRIFT')
    if _guarded_large_bytes(git_dir, bundle_name, MAX_BUNDLE) != bundle_raw:
        raise FullCaptureError('S1_CAPTURE_BUNDLE_FINAL_DRIFT')
    # Sources are immutable for this evidence claim; later drift cancels READY.
    for src_name, src_raw in files.items():
        if _source(git_dir, task, src_name, validate_artifact) != src_raw:
            raise FullCaptureError('S1_CAPTURE_SOURCE_DRIFT')
    zip_sha = hashlib.sha256(archive).hexdigest()
    card = {'schema_version': 1, 'kind': 'S1_FULL_CAPTURE', 'complete_capture': True,
            'task_id': task, 'step': step, 's1_code': code, 'base_oid': base,
            'head_oid': snap['head_oid'], 'archive_file': name, 'archive_sha256': zip_sha,
            'bundle_file': bundle_name, 'manifest_sha256': hashlib.sha256(manifest).hexdigest(),
            'gate_records': 'ARCHIVED', 'git_snapshot': 'ARCHIVED',
            'unpublished_commit_bundle': 'LOCAL_HEAD_ARCHIVED_PUBLICATION_NOT_CHECKED',
            'publication_status': 'NOT_CHECKED_NO_REMOTE_TRAFFIC', 'archive_member_count': len(content)}
    raw = (json.dumps(card, sort_keys=True, separators=(',', ':'))+'\n').encode('ascii')
    cname = task+'-s1-full-capture.json'
    validate_artifact('.git/'+cname)
    card_sha = _create_once(git_dir, cname, raw)
    final_archive = _guarded_large_bytes(git_dir, name, MAX_TOTAL)
    if (_guarded_bytes(git_dir, cname) != raw or final_archive != archive
            or _guarded_large_bytes(git_dir, bundle_name, MAX_BUNDLE) != bundle_raw
            or hashlib.sha256(final_archive).hexdigest() != zip_sha):
        raise FullCaptureError('S1_CAPTURE_FINAL_BYTES_DRIFT')
    last_snap, last_binary = _snapshot(root, task, base, branch)
    if not _snapshot_equal((snap, binary), (last_snap, last_binary)):
        raise FullCaptureError('S1_CAPTURE_GIT_DRIFT')
    return ['S1_FULL_CAPTURE_FILE=.git/'+name+' sha256='+zip_sha,
            'S1_FULL_CAPTURE_CARD=.git/'+cname+' sha256='+card_sha,
            'S1_FULL_CAPTURE_JSON='+raw.decode('ascii').rstrip('\n')]
