#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/s1_recover.py
USER-run S1 workspace preservation and recovery for a canonical runner batch (B-119 G1).

The Executor never runs this tool. The USER runs it in the fixed workspace after an S1 stop, with the
task id and the SHA-256 of the delivered prompt (.git/<TASK_ID>-prompt.txt). Base, batch branch and the
allowed paths come from the runner's own load_spec on those exact bytes; nothing is typed by hand.

  python scripts/s1_recover.py preserve --task-id T --prompt-sha256 H
  python scripts/s1_recover.py restore  --task-id T --prompt-sha256 H --preserved-oid O --plan-sha256 P
  python scripts/s1_recover.py verify   --task-id T --prompt-sha256 H --preserved-oid O

Two S1 shapes are supported; anything else stops before any write.
  UNCOMMITTED  HEAD == Base on the batch branch.
  COMMITTED    HEAD is one local commit whose parent is Base on the batch branch, with a clean index and
               worktree and no remote branch of that name (re-checked before the first restore write).
The disposition set is every path that differs between Base and HEAD, the index or the worktree (no rename
detection). Every such path must be inside the plan's allowed paths and be a regular file (or absent);
renames, conflicts, symlinks, submodules, files over 64 MiB or more than 200 paths stop.

preserve (no worktree or index change). For every path it records the Base tree entry, the index entry and
the raw worktree bytes (git hash-object -w --no-filters, so line endings are never normalised), then writes
one snapshot commit whose tree holds those blobs plus manifest.json and whose parent is HEAD, so everything
is reachable from refs/hhai/s1/<TASK_ID> and survives git gc. The commit uses a fixed identity and date, so
the same snapshot always has the same OID. The ref is created only if absent (create-only update); an
existing ref with a different OID stops (PRESERVED_REF_CONFLICT) and is never moved, overwritten or deleted
(USER decision D2, 2026-10-24). It prints the exact plan (per path RESTORE_TRACKED or DELETE_NEW with the
worktree SHA-256 and index blob), its SHA-256 and the snapshot OID; running it again on the same state
prints the same values.

restore. The USER runs it only after reading that plan; running it with the printed OID and plan SHA-256 is
the per-instance authorisation of USER decision D1 (2026-10-24) for exactly that plan, nothing wider.
Before the first write it re-derives the plan from the snapshot, checks the bindings, reads back every
preserved blob against its recorded SHA-256 (a missing or damaged object stops with nothing changed),
re-checks the remote branch for COMMITTED, and classifies each path component by component: the index
entry and the worktree must each be either as preserved or already at the Base target (a state an earlier
interrupted run of this tool can leave); anything else stops (PATH_STATE_UNEXPECTED) with nothing changed.
It then sets each remaining component to its target, detaches HEAD at Base, keeps every local branch, and
prints WORKSPACE_AT_BASE_READY only after the full post-check (also run by verify) passes. This is not a
transaction: an interrupted restore is resumed by running the same command again.

verify (read-only). HEAD == Base detached, clean index and worktree, the snapshot ref equals the OID, every
preserved blob is readable with the recorded SHA-256, and every local branch tip equals the snapshot record.

Exit codes: 0 success; 1 stopped (S1_RECOVER STOP <CODE>); 2 usage. Output never contains file contents.
"""

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import batch_runner  # noqa: E402 - the runner's own prompt parser is the reference
finally:
    sys.path.pop(0)

OID = re.compile(r'^[0-9a-f]{40}$')
HEX64 = re.compile(r'^[0-9a-f]{64}$')
ZERO = '0' * 40
REF_PREFIX = 'refs/hhai/s1/'
MAX_FILE = 64 * 1024 * 1024
MAX_PATHS = 200
MODES = ('100644', '100755')
IDENTITY = {'GIT_AUTHOR_NAME': 'HH.AI S1 preserve', 'GIT_AUTHOR_EMAIL': 's1-preserve@hhai.invalid',
            'GIT_COMMITTER_NAME': 'HH.AI S1 preserve', 'GIT_COMMITTER_EMAIL': 's1-preserve@hhai.invalid',
            'GIT_AUTHOR_DATE': '@0 +0000', 'GIT_COMMITTER_DATE': '@0 +0000'}


class Stop(Exception):
    pass


def _env(extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env['GIT_TERMINAL_PROMPT'] = '0'
    env.update(extra or {})
    return env


def git(root, *args, data=None, env=None, ok=(0,), text=True):
    try:
        p = subprocess.run(['git', '-C', str(root), *args], input=data, capture_output=True,
                           env=_env(env), timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise Stop('GIT_FAILED') from None
    if p.returncode not in ok:
        raise Stop('GIT_FAILED')
    if not text:
        return p.returncode, p.stdout
    try:
        return p.returncode, p.stdout.decode('utf-8', 'strict')
    except UnicodeDecodeError:
        raise Stop('GIT_OUTPUT_INVALID') from None


def out(root, *args, **kw):
    return git(root, *args, **kw)[1].strip()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical(obj):
    return json.dumps(obj, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


def emit(tag, value):
    print('%s=%s' % (tag, value))


# -- binding -----------------------------------------------------------------------------------------

def bind(root, task, prompt_sha):
    """Return the production spec bound to the exact prompt bytes."""
    if not batch_runner.TASK_RE.match(task or '') or not HEX64.match(prompt_sha or ''):
        raise Stop('ARGUMENT_INVALID')
    path = Path(root) / '.git' / (task + '-prompt.txt')
    try:
        meta = path.lstat()
        if not stat.S_ISREG(meta.st_mode) or meta.st_size > 2 * 1024 * 1024:
            raise Stop('PROMPT_INVALID')
        data = path.read_bytes()
    except OSError:
        raise Stop('PROMPT_MISSING') from None
    if sha256(data) != prompt_sha:
        raise Stop('PROMPT_HASH_MISMATCH')
    try:
        spec = batch_runner.load_spec(batch_runner.prompt_lines(data), task)
    except (batch_runner.Halt, UnicodeDecodeError):
        raise Stop('PROMPT_SPEC_INVALID') from None
    if spec.get('kind') != 'production':
        raise Stop('PROMPT_KIND_UNSUPPORTED')
    return {'task_id': task, 'prompt_sha256': prompt_sha, 'base_oid': spec['base_oid'],
            'branch': spec['branch'], 'allowed': batch_runner.allowed_paths(spec)}


# -- repository facts --------------------------------------------------------------------------------

def repo_state(root):
    if out(root, 'rev-parse', '--is-shallow-repository') != 'false':
        raise Stop('SHALLOW_REPO')
    head = out(root, 'rev-parse', '--verify', 'HEAD^{commit}')
    rc, branch = git(root, 'symbolic-ref', '-q', '--short', 'HEAD', ok=(0, 1))
    heads = {}
    for line in out(root, 'for-each-ref', '--format=%(refname) %(objectname)', 'refs/heads').splitlines():
        name, oid = line.rsplit(' ', 1)
        heads[name] = oid
    return head, (branch.strip() if rc == 0 else ''), heads


def status_paths(root):
    _, raw = git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=all', '--ignore-submodules=none',
                 '--no-renames', text=False)
    paths = set()
    for rec in raw.split(b'\0'):
        if not rec:
            continue
        if len(rec) < 4 or rec[2:3] != b' ':
            raise Stop('STATUS_INVALID')
        xy = rec[:2].decode('ascii')
        if 'U' in xy or xy in ('AA', 'DD'):
            raise Stop('CONFLICT_UNSUPPORTED')
        if xy[0] in 'RC' or xy[1] in 'RC':
            raise Stop('RENAME_UNSUPPORTED')
        paths.add(rec[3:].decode('utf-8'))
    return paths


def tree_entry(root, rev, path):
    raw = out(root, 'ls-tree', '-z', rev, '--', path).rstrip('\0')
    if not raw:
        return None
    meta, name = raw.split('\t', 1)
    mode, kind, oid = meta.split(' ')
    if name != path or kind != 'blob' or mode not in MODES:
        raise Stop('TREE_ENTRY_UNSUPPORTED')
    return {'mode': mode, 'oid': oid}


def index_entry(root, path):
    raw = out(root, 'ls-files', '-s', '-z', '--', path).rstrip('\0')
    if not raw:
        return None
    entries = raw.split('\0')
    if len(entries) != 1:
        raise Stop('INDEX_ENTRY_INVALID')
    meta, name = entries[0].split('\t', 1)
    mode, oid, stage = meta.split(' ')
    if name != path or stage != '0' or mode not in MODES or not OID.match(oid):
        raise Stop('INDEX_ENTRY_UNSUPPORTED')
    return {'mode': mode, 'oid': oid}


def worktree_bytes(root, path):
    file = Path(root) / path
    try:
        meta = file.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise Stop('WORKTREE_STAT_FAILED') from None
    if (not stat.S_ISREG(meta.st_mode) or meta.st_size > MAX_FILE
            or (getattr(meta, 'st_file_attributes', 0) & 0x400)):
        raise Stop('WORKTREE_ENTRY_UNSUPPORTED')
    try:
        data = file.read_bytes()
    except OSError:
        raise Stop('WORKTREE_READ_FAILED') from None
    if len(data) != meta.st_size:
        raise Stop('WORKTREE_CHANGED_DURING_READ')
    return data


def remote_branch_absent(root, branch):
    rc, _ = git(root, 'ls-remote', '--exit-code', 'origin', 'refs/heads/' + branch, ok=(0, 2))
    return rc == 2


def blob_bytes(root, oid):
    rc, data = git(root, 'cat-file', 'blob', oid, ok=(0, 128), text=False)
    if rc:
        raise Stop('SNAPSHOT_BLOB_MISSING')
    return data


# -- preserve ----------------------------------------------------------------------------------------

def classify(root, bound):
    head, branch, heads = repo_state(root)
    base = bound['base_oid']
    if branch != bound['branch']:
        raise Stop('BRANCH_MISMATCH')
    local = status_paths(root)
    if head == base:
        if not local:
            raise Stop('NOTHING_TO_PRESERVE')
        kind, committed = 'UNCOMMITTED', set()
    else:
        if out(root, 'rev-parse', '--verify', head + '^1') != base or out(root, 'rev-list', '--count', base + '..' + head) != '1':
            raise Stop('HEAD_NOT_ONE_COMMIT_ON_BASE')
        if local:
            raise Stop('COMMITTED_WITH_EXTRA_CHANGES')
        if not remote_branch_absent(root, branch):
            raise Stop('REMOTE_BRANCH_PRESENT')
        kind = 'COMMITTED'
        committed = set(p for p in out(root, 'diff', '--no-renames', '--name-only', '-z', base, head).split('\0') if p)
        if not committed:
            raise Stop('NOTHING_TO_PRESERVE')
    paths = sorted(local | committed)
    if len(paths) > MAX_PATHS:
        raise Stop('TOO_MANY_PATHS')
    if any(p not in bound['allowed'] for p in paths):
        raise Stop('PATH_OUTSIDE_PLAN')
    return head, branch, heads, kind, paths


def capture(root, base, paths):
    records = []
    for path in paths:
        data = worktree_bytes(root, path)
        rec = {'path': path, 'base': tree_entry(root, base, path), 'index': index_entry(root, path)}
        if data is None:
            rec['worktree'] = None
        else:
            oid = out(root, 'hash-object', '-w', '--no-filters', '--stdin', data=data)
            if not OID.match(oid):
                raise Stop('BLOB_WRITE_FAILED')
            rec['worktree'] = {'oid': oid, 'sha256': sha256(data), 'bytes': len(data)}
        if rec['index']:
            blob_bytes(root, rec['index']['oid'])
        rec['action'] = 'RESTORE_TRACKED' if rec['base'] is not None else 'DELETE_NEW'
        records.append(rec)
    return records


def make_plan(bound, kind, head, heads, records):
    return {'schema_version': 2, 'kind': kind, 'task_id': bound['task_id'], 'prompt_sha256': bound['prompt_sha256'],
            'base_oid': bound['base_oid'], 'branch': bound['branch'], 'head_oid': head,
            'local_heads': dict(sorted(heads.items())),
            'actions': [{'path': r['path'], 'action': r['action'],
                         'worktree_sha256': r['worktree']['sha256'] if r['worktree'] else None,
                         'index_oid': r['index']['oid'] if r['index'] else None} for r in records]}


def snapshot_commit(root, head, plan, records):
    manifest = canonical({'plan': plan, 'records': records}).encode('ascii')
    m_oid = out(root, 'hash-object', '-w', '--no-filters', '--stdin', data=manifest)
    lines = ['100644 blob %s\tmanifest.json' % m_oid]
    for i, r in enumerate(records):
        if r['worktree']:
            lines.append('100644 blob %s\tw%03d' % (r['worktree']['oid'], i))
        if r['index']:
            lines.append('100644 blob %s\ti%03d' % (r['index']['oid'], i))
    tree = out(root, 'mktree', '-z', data=('\0'.join(lines) + '\0').encode('utf-8'))
    commit = out(root, 'commit-tree', tree, '-p', head, '-m', 'HH.AI S1 preserve ' + plan['task_id'], env=IDENTITY)
    if not OID.match(tree) or not OID.match(commit):
        raise Stop('SNAPSHOT_WRITE_FAILED')
    return commit


def read_snapshot(root, oid):
    if not OID.match(oid or ''):
        raise Stop('ARGUMENT_INVALID')
    rc, raw = git(root, 'cat-file', 'blob', oid + ':manifest.json', ok=(0, 128), text=False)
    if rc:
        raise Stop('SNAPSHOT_UNREADABLE')
    try:
        doc = json.loads(raw.decode('ascii'))
        return doc['plan'], doc['records']
    except (ValueError, KeyError, TypeError):
        raise Stop('SNAPSHOT_MANIFEST_INVALID') from None


def verify_objects(root, oid, plan, records):
    """Every preserved byte must be readable before any destructive step (and again afterwards)."""
    if [r['path'] for r in records] != [a['path'] for a in plan['actions']]:
        raise Stop('SNAPSHOT_MANIFEST_INVALID')
    tree = {}
    for line in out(root, 'ls-tree', '-z', oid).split('\0'):
        if line:
            meta, name = line.split('\t', 1)
            tree[name] = meta.split(' ')[2]
    for i, (r, a) in enumerate(zip(records, plan['actions'])):
        if r['worktree']:
            if tree.get('w%03d' % i) != r['worktree']['oid'] or a['worktree_sha256'] != r['worktree']['sha256']:
                raise Stop('SNAPSHOT_MANIFEST_INVALID')
            if sha256(blob_bytes(root, r['worktree']['oid'])) != r['worktree']['sha256']:
                raise Stop('SNAPSHOT_BLOB_DAMAGED')
        if r['index']:
            if tree.get('i%03d' % i) != r['index']['oid'] or a['index_oid'] != r['index']['oid']:
                raise Stop('SNAPSHOT_MANIFEST_INVALID')
            blob_bytes(root, r['index']['oid'])
    if out(root, 'rev-parse', '--verify', oid + '^1') != plan['head_oid']:
        raise Stop('SNAPSHOT_PARENT_MISMATCH')


def cmd_preserve(root, bound):
    head, branch, heads, kind, paths = classify(root, bound)
    records = capture(root, bound['base_oid'], paths)
    plan = make_plan(bound, kind, head, heads, records)
    commit = snapshot_commit(root, head, plan, records)
    ref = REF_PREFIX + bound['task_id']
    rc, current = git(root, 'rev-parse', '-q', '--verify', ref, ok=(0, 1))
    current = current.strip() if rc == 0 else ''
    if not current:
        git(root, 'update-ref', ref, commit, ZERO)
        current = out(root, 'rev-parse', '--verify', ref)
    if current != commit:
        raise Stop('PRESERVED_REF_CONFLICT')
    stored_plan, stored = read_snapshot(root, commit)
    verify_objects(root, commit, stored_plan, stored)
    text = canonical(stored_plan)
    emit('S1_RECOVER_PLAN_JSON', text)
    emit('S1_RECOVER_PLAN_SHA256', sha256(text.encode('ascii')))
    emit('S1_PRESERVED_REF', ref)
    emit('S1_PRESERVED_OID', commit)
    print('S1_RECOVER PRESERVED kind=%s paths=%d (no worktree change; review the plan before restore)' % (kind, len(paths)))
    return 0


# -- restore / verify --------------------------------------------------------------------------------

def bound_snapshot(root, bound, oid, plan_sha=None):
    plan, records = read_snapshot(root, oid)
    if plan.get('schema_version') != 2 or plan.get('kind') not in ('UNCOMMITTED', 'COMMITTED'):
        raise Stop('SNAPSHOT_MANIFEST_INVALID')
    for key in ('task_id', 'prompt_sha256', 'base_oid', 'branch'):
        if plan.get(key) != bound[key]:
            raise Stop('SNAPSHOT_BINDING_MISMATCH')
    if plan_sha is not None and sha256(canonical(plan).encode('ascii')) != plan_sha:
        raise Stop('PLAN_HASH_MISMATCH')
    if out(root, 'rev-parse', '--verify', REF_PREFIX + bound['task_id']) != oid:
        raise Stop('PRESERVED_REF_MISMATCH')
    if any(r['path'] not in bound['allowed'] for r in records):
        raise Stop('PATH_OUTSIDE_PLAN')
    verify_objects(root, oid, plan, records)
    return plan, records


def worktree_at_target(root, r, data):
    if r['base'] is None:
        return data is None
    if data is None:
        return False
    # Same comparison git uses for a clean file: the content as Git would store it equals the Base blob.
    return out(root, 'hash-object', '--path', r['path'], '--stdin', data=data) == r['base']['oid']


def component_states(root, r):
    """('PRESERVED'|'TARGET', 'PRESERVED'|'TARGET') for (index, worktree); anything else stops."""
    idx = index_entry(root, r['path'])
    if idx == r['index']:
        i_state = 'PRESERVED'
    elif idx == r['base']:
        i_state = 'TARGET'
    else:
        raise Stop('PATH_STATE_UNEXPECTED')
    data = worktree_bytes(root, r['path'])
    if (data is None) if r['worktree'] is None else (data is not None and sha256(data) == r['worktree']['sha256']):
        w_state = 'PRESERVED'
    elif worktree_at_target(root, r, data):
        w_state = 'TARGET'
    else:
        raise Stop('PATH_STATE_UNEXPECTED')
    # The preserved and target values can coincide; prefer TARGET so nothing is rewritten needlessly.
    if i_state == 'PRESERVED' and idx == r['base']:
        i_state = 'TARGET'
    if w_state == 'PRESERVED' and worktree_at_target(root, r, data):
        w_state = 'TARGET'
    return i_state, w_state


def set_target(root, r, i_state, w_state):
    if r['base'] is not None:
        # One command for both components: it also refreshes the index stat data, so a CRLF worktree under
        # core.autocrlf=true is not reported as modified (a split --staged / --worktree restore leaves it stale).
        git(root, 'restore', '--source=' + r['base_rev'], '--staged', '--worktree', '--', r['path'])
        return
    if i_state == 'PRESERVED':
        git(root, 'update-index', '--force-remove', '--', r['path'])
    if w_state == 'PRESERVED':
        try:
            (Path(root) / r['path']).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            raise Stop('DELETE_FAILED') from None


def post_check(root, bound, oid, plan, records):
    head, branch, heads = repo_state(root)
    if head != bound['base_oid'] or branch:
        raise Stop('POSTCHECK_HEAD')
    if status_paths(root):
        raise Stop('POSTCHECK_NOT_CLEAN')
    if heads != plan['local_heads']:
        raise Stop('POSTCHECK_BRANCHES_CHANGED')
    if out(root, 'rev-parse', '--verify', REF_PREFIX + bound['task_id']) != oid:
        raise Stop('POSTCHECK_REF')
    verify_objects(root, oid, plan, records)


def cmd_restore(root, bound, oid, plan_sha):
    plan, records = bound_snapshot(root, bound, oid, plan_sha)        # includes full object read-back
    base = bound['base_oid']
    head, branch, heads = repo_state(root)
    if heads != plan['local_heads']:
        raise Stop('BRANCHES_CHANGED')
    detached_at_base = head == base and not branch
    if plan['kind'] == 'COMMITTED':
        if not ((head == plan['head_oid'] and branch == bound['branch']) or detached_at_base):
            raise Stop('HEAD_UNEXPECTED')
    elif not (head == base and branch in (bound['branch'], '')):
        raise Stop('HEAD_UNEXPECTED')
    if status_paths(root) - {r['path'] for r in records}:
        raise Stop('UNEXPECTED_CHANGE')
    for r in records:
        r['base_rev'] = base
    states = [component_states(root, r) for r in records]            # every path classified before any write
    pending = [(r, s) for r, s in zip(records, states) if s != ('TARGET', 'TARGET')]
    if plan['kind'] == 'COMMITTED' and not detached_at_base:          # re-checked before the first write
        if not remote_branch_absent(root, bound['branch']):
            raise Stop('REMOTE_BRANCH_PRESENT')
    for r, _ in pending:
        i_state, w_state = component_states(root, r)                    # re-check immediately before writing
        set_target(root, r, i_state, w_state)
        if component_states(root, r) != ('TARGET', 'TARGET'):
            raise Stop('PATH_RESTORE_INCOMPLETE')
        print('S1_RECOVER %s %s' % ('DELETED' if r['action'] == 'DELETE_NEW' else 'RESTORED', r['path']))
    if not detached_at_base:
        git(root, 'switch', '-q', '--detach', base)
    post_check(root, bound, oid, plan, records)
    emit('S1_PRESERVED_OID', oid)
    print('HEAD=%s (detached, clean)' % base)
    print('WORKSPACE_AT_BASE_READY')
    return 0


def cmd_verify(root, bound, oid):
    plan, records = bound_snapshot(root, bound, oid)
    post_check(root, bound, oid, plan, records)
    print('S1_RECOVER VERIFIED kind=%s paths=%d' % (plan['kind'], len(records)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='USER-run S1 preserve / restore / verify (B-119 G1).')
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('preserve', 'restore', 'verify'):
        p = sub.add_parser(name)
        p.add_argument('--task-id', required=True)
        p.add_argument('--prompt-sha256', required=True)
        if name != 'preserve':
            p.add_argument('--preserved-oid', required=True)
        if name == 'restore':
            p.add_argument('--plan-sha256', required=True)
    args = ap.parse_args(argv)
    root = Path.cwd()
    try:
        top = out(root, 'rev-parse', '--show-toplevel')
        if Path(top).resolve() != Path(root).resolve():
            raise Stop('NOT_REPO_ROOT')
        bound = bind(root, args.task_id, args.prompt_sha256.lower())
        if args.cmd == 'preserve':
            return cmd_preserve(root, bound)
        if args.cmd == 'restore':
            if not HEX64.match(args.plan_sha256.lower()):
                raise Stop('ARGUMENT_INVALID')
            return cmd_restore(root, bound, args.preserved_oid.lower(), args.plan_sha256.lower())
        return cmd_verify(root, bound, args.preserved_oid.lower())
    except Stop as s:
        print('S1_RECOVER STOP %s' % s)
        return 1


if __name__ == '__main__':
    sys.exit(main())
