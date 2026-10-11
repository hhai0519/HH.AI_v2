#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/state_edit.py
Canonical writer for the registered state files (B-107 G4 slice 3b).

The four state files (docs/TASKBOARD.md, docs/refactor-backlog.md, docs/AUDIT-LOG.md, docs/EXEC-LOG.md) are
changed outside runner batches only through this tool (.agents/rules/governance-gate-integrity.md section 5,
second layer). It edits text with the same operations as the Macro prompt builder and the canonical runner
and binds every write to the content it was planned against.

Usage (from the repository root):
  python scripts/state_edit.py seal  --task-id <TASK_ID> --prompt-sha256 <P>
  python scripts/state_edit.py apply --task-id <TASK_ID> --prompt-sha256 <P> --plan-sha256 <Q>
  <P> is the prompt SHA-256 delivered with the task (the value prompt_intake.py was given); <Q> is the plan
  SHA-256 that seal printed. Both come from outside the files they check and are never recomputed from them;
  if either is not available, stop and report instead of deriving it from the file.

Inputs and outputs (all inside .git, named by the task):
  .git/<TASK_ID>-prompt.txt       the task prompt (created by scripts/prompt_intake.py); it must pass the
                                  governance preflight and its execution contract decides which paths this
                                  task may change (allowed_mutation_paths).
  .git/<TASK_ID>-state-ops.json   written by the task: {"schema_version": 1, "task_id": ..., "files":
                                  [{"path": <state file>, "ops": [...]}]}; an op is
                                  {"type": "replace", "old", "new"} | {"type": "replace_line", "prefix", "new"} |
                                  {"type": "insert_after_line", "prefix", "text"}.
  .git/<TASK_ID>-state-plan.json  created once by seal (never overwritten): the prompt SHA-256 and, for every
                                  file, its path, the ops, before_sha256 (the file as seal read it) and
                                  after_sha256 (the result). seal prints the SHA-256 of the plan file.

Bindings: seal and apply require the task prompt to hash to <P> (a prompt replaced after delivery, even a well
formed one of the same task, stops: STATE_PROMPT_SHA_MISMATCH); apply requires the plan file to hash to <Q>
before it reads anything from it (a plan with a removed entry or swapped hashes stops: STATE_PLAN_SHA_MISMATCH)
and the plan to name <P>. Boundary: the two values protect the files between delivery, seal and apply against
any change made without also changing the values given on the command line; they cannot stop an operator who
deliberately passes values of forged files. That case is a rule violation outside this tool's reach; the
Macro's exact-SHA review of the resulting commit compares the actual changes with the prompt.

seal reads the current files, applies the ops in order to the intermediate text (each op through
prompt_builder.text_op and batch_runner.apply_ops, so an anchor or a line prefix must match exactly once in the
text as it is at that op) and records both hashes. It never writes a tracked file.

apply uses only the sealed plan. It first classifies every file, then writes:
  current == after_sha256   ALREADY_APPLIED: nothing is written and no op is run again (the file must still
                            follow the byte rule).
  current == before_sha256  the ops are run again; the result must hash to after_sha256, else it stops.
  anything else             STATE_CONFLICT: it stops; the plan is never re-sealed against the new content.
Every run repeats every safety check (path, link and hard-link check through batch_runner.author_target,
regular file, writable, allowed path, task prompt) whatever the hashes say. Nothing is written unless every
file passed. The truth for a rerun is the files' hashes, never an earlier run's output, so a rerun after an
interrupted apply completes the remaining files and reports the finished ones as ALREADY_APPLIED.

Byte rule: a file is its raw bytes. Source and result must be UTF-8 without any carriage return and end with a
newline; the result may not hold more lines with trailing whitespace than the source already had (an existing
line is kept as it is, no new one is added). Hashes are SHA-256 of the raw bytes; nothing is normalised, so a
differently encoded file can never count as already applied.

Single-file write: the new bytes go to an exclusively created temporary file in the same directory
(.<name>.<TASK_ID>.state-edit.tmp), are flushed to disk, take the file's permission bits and then replace the
file with os.replace. A failure removes only the temporary file this run created; an existing temporary file
of that name (for example left by an interrupted run) stops the tool (STATE_TEMP_EXISTS) and is never removed
by it. The replace is atomic for the file name on the same file system; it is not a durability guarantee across
a power loss.

Several files are not one transaction: a failure after the first replace leaves earlier files written. The tool
prints one STATE_EDIT line per file as it is written, but a forced termination may print nothing; rerun apply
to finish. Single-writer assumption: nothing else changes the files while the tool runs; the checks are not
concurrency isolation.

The tool grants no role permission: which content a task may write (for example a Macro verdict or the
checkpoint) is decided by the role rules and the task prompt, not by this tool.

Exit codes: 0 done, 1 stopped ("S1 <CODE>" on one line; no file content is ever printed), 2 usage.
"""

import argparse
import hashlib
import json
import os
import stat
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))
try:
    import batch_runner  # noqa: E402 - path, link and anchor rules of the canonical runner
    import prompt_builder  # noqa: E402 - the text operation types of the Macro prompt builder
    from scripts.governance_preflight import verify_current_task_prompt, verify_task_artifact_path  # noqa: E402
    from scripts.validate_prompt_manifest import validate_prompt_manifest, validate_execution_contract  # noqa: E402
finally:
    sys.path.pop(0)
    sys.path.pop(0)

SCHEMA_VERSION = 1
STATE_FILES = ('docs/TASKBOARD.md', 'docs/refactor-backlog.md', 'docs/AUDIT-LOG.md', 'docs/EXEC-LOG.md')
OP_FIELDS = {'replace': ('old', 'new'), 'replace_line': ('prefix', 'new'), 'insert_after_line': ('prefix', 'text')}
SHA256_LEN = 64


class Stop(Exception):
    """A fail-closed stop; str() is a fixed code."""


def _require(cond, code):
    if not cond:
        raise Stop(code)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _is_sha256(value):
    return isinstance(value, str) and len(value) == SHA256_LEN and all(c in '0123456789abcdef' for c in value)


def clean_text(data, code):
    """The byte rule for one file: UTF-8, no carriage return, ends with a newline."""
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        raise Stop(code + '_NOT_UTF8')
    _require('\r' not in text, code + '_CR')
    _require(text.endswith('\n'), code + '_TRAILING_NEWLINE')
    return text


def trailing_whitespace_lines(text):
    return Counter(line for line in text.split('\n') if line != line.rstrip())


def check_result(source_text, result):
    """The result follows the byte rule and adds no line with trailing whitespace."""
    text = clean_text(result, 'STATE_RESULT')
    _require(not (trailing_whitespace_lines(text) - trailing_whitespace_lines(source_text)), 'STATE_RESULT_TRAILING_WHITESPACE')


def task_scope(root, task_id, prompt_sha):
    """Allowed state files of this task: the registered list intersected with the prompt's allowed paths.

    The prompt must be the delivered one (its bytes hash to prompt_sha) and pass the governance preflight.
    """
    try:
        with open(root / '.git' / (task_id + '-prompt.txt'), 'rb') as f:
            delivered = sha256_bytes(f.read()) == prompt_sha
    except OSError:
        raise Stop('STATE_TASK_PROMPT_INVALID')
    _require(delivered, 'STATE_PROMPT_SHA_MISMATCH')
    ok, _, prompt_text, _ = verify_current_task_prompt(str(root), task_id)
    _require(ok, 'STATE_TASK_PROMPT_INVALID')
    m_ok, _, manifest = validate_prompt_manifest(prompt_text)
    c_ok, _, contract = validate_execution_contract(prompt_text, manifest)
    _require(m_ok and c_ok, 'STATE_TASK_PROMPT_INVALID')
    raw = str(contract.get('allowed_mutation_paths', '')).strip()
    allowed = set() if raw in ('', 'NONE') else {p.strip() for p in raw.split(';') if p.strip()}
    return allowed & set(STATE_FILES)


def artifact(root, task_id, suffix):
    rel = '.git/' + task_id + '-' + suffix
    ok, _ = verify_task_artifact_path(str(root), task_id, rel)
    _require(ok, 'STATE_ARTIFACT_PATH_INVALID')
    return root / rel


def read_json(path, code):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise Stop(code + '_MISSING')
    except (OSError, ValueError, UnicodeDecodeError):
        raise Stop(code + '_INVALID')


def check_ops(ops):
    _require(isinstance(ops, list) and ops, 'STATE_OPS_INVALID')
    for op in ops:
        _require(isinstance(op, dict) and op.get('type') in OP_FIELDS, 'STATE_OPS_INVALID')
        fields = OP_FIELDS[op['type']]
        _require(set(op) == {'type'} | set(fields), 'STATE_OPS_INVALID')
        _require(all(isinstance(op[f], str) for f in fields) and op[fields[0]], 'STATE_OPS_INVALID')


def check_files(files, scope):
    _require(isinstance(files, list) and files, 'STATE_OPS_INVALID')
    paths = [f.get('path') if isinstance(f, dict) else None for f in files]
    _require(all(isinstance(p, str) for p in paths) and len(set(paths)) == len(paths), 'STATE_OPS_INVALID')
    for p in paths:
        _require(p in STATE_FILES, 'STATE_PATH_NOT_REGISTERED')
        _require(p in scope, 'STATE_PATH_NOT_ALLOWED')


def target_of(root, path):
    """Safe, existing, regular, single-link, writable state file (repeated on every run)."""
    _require(batch_runner.safe_author_path(path), 'STATE_PATH_NOT_REGISTERED')
    try:
        target = batch_runner.author_target(str(root), path)
    except batch_runner.Halt as h:
        raise Stop('STATE_TARGET_UNSAFE' if str(h) == 'AUTHOR_PATH_UNSAFE_TARGET' else 'STATE_TARGET_MISSING')
    _require(os.path.lexists(target), 'STATE_TARGET_MISSING')
    try:
        writable = os.access(target, os.W_OK)
    except (OSError, ValueError):
        writable = False
    _require(writable, 'STATE_TARGET_READONLY')
    return target


def read_target(target):
    try:
        with open(target, 'rb') as f:
            return f.read()
    except OSError:
        raise Stop('STATE_TARGET_UNREADABLE')


def run_ops(path, text, ops):
    """Apply ops in order to the intermediate text with the builder's op types and the runner's anchor rule."""
    texts = {path: text}
    for op in ops:
        try:
            rop = prompt_builder.text_op(texts, dict(op, path=path), {})
            batch_runner.apply_ops(texts, [rop])
        except (prompt_builder.BuildError, batch_runner.Halt):
            raise Stop('STATE_OP_ANCHOR_INVALID')
    return texts[path]


def seal(root, task_id, prompt_sha):
    scope = task_scope(root, task_id, prompt_sha)
    ops_doc = read_json(artifact(root, task_id, 'state-ops.json'), 'STATE_OPS')
    plan_path = artifact(root, task_id, 'state-plan.json')
    _require(not os.path.lexists(plan_path), 'STATE_PLAN_EXISTS')
    _require(isinstance(ops_doc, dict) and ops_doc.get('schema_version') == SCHEMA_VERSION
             and ops_doc.get('task_id') == task_id and set(ops_doc) == {'schema_version', 'task_id', 'files'},
             'STATE_OPS_INVALID')
    files = ops_doc['files']
    check_files(files, scope)
    planned = []
    for entry in sorted(files, key=lambda f: f['path']):
        _require(set(entry) == {'path', 'ops'}, 'STATE_OPS_INVALID')
        check_ops(entry['ops'])
        target = target_of(root, entry['path'])
        data = read_target(target)
        text = clean_text(data, 'STATE_SOURCE')
        result = run_ops(entry['path'], text, entry['ops']).encode('utf-8')
        check_result(text, result)
        _require(result != data, 'STATE_RESULT_UNCHANGED')
        planned.append({'path': entry['path'], 'before_sha256': sha256_bytes(data),
                        'after_sha256': sha256_bytes(result), 'ops': entry['ops']})
    plan = {'schema_version': SCHEMA_VERSION, 'task_id': task_id, 'prompt_sha256': prompt_sha, 'files': planned}
    plan_bytes = (json.dumps(plan, ensure_ascii=False, indent=1) + '\n').encode('utf-8')
    try:
        with open(plan_path, 'xb') as f:
            f.write(plan_bytes)
    except FileExistsError:
        raise Stop('STATE_PLAN_EXISTS')
    except OSError:
        raise Stop('STATE_PLAN_WRITE_FAILED')
    for p in planned:
        print('STATE_EDIT SEALED ' + p['path'] + ' before=' + p['before_sha256'] + ' after=' + p['after_sha256'])
    print('STATE_EDIT PLAN sha256=' + sha256_bytes(plan_bytes))
    print('STATE_EDIT RESULT sealed=' + str(len(planned)))


def read_plan(root, task_id, plan_sha):
    """The sealed plan, only after its bytes hash to the value seal printed."""
    path = artifact(root, task_id, 'state-plan.json')
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except FileNotFoundError:
        raise Stop('STATE_PLAN_MISSING')
    except OSError:
        raise Stop('STATE_PLAN_INVALID')
    _require(sha256_bytes(data) == plan_sha, 'STATE_PLAN_SHA_MISMATCH')
    try:
        return json.loads(data.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise Stop('STATE_PLAN_INVALID')


def classify(root, task_id, prompt_sha, plan_sha):
    """Every check for every file before any write; returns [(path, target, new_bytes or None)]."""
    scope = task_scope(root, task_id, prompt_sha)
    plan = read_plan(root, task_id, plan_sha)
    _require(isinstance(plan, dict) and plan.get('schema_version') == SCHEMA_VERSION
             and plan.get('task_id') == task_id
             and set(plan) == {'schema_version', 'task_id', 'prompt_sha256', 'files'}, 'STATE_PLAN_INVALID')
    _require(plan['prompt_sha256'] == prompt_sha, 'STATE_PROMPT_SHA_MISMATCH')
    files = plan['files']
    check_files(files, scope)
    out = []
    for entry in files:
        _require(set(entry) == {'path', 'before_sha256', 'after_sha256', 'ops'}
                 and _is_sha256(entry['before_sha256']) and _is_sha256(entry['after_sha256'])
                 and entry['before_sha256'] != entry['after_sha256'], 'STATE_PLAN_INVALID')
        check_ops(entry['ops'])
        target = target_of(root, entry['path'])
        data = read_target(target)
        current = sha256_bytes(data)
        if current == entry['after_sha256']:
            clean_text(data, 'STATE_SOURCE')
            out.append((entry['path'], target, None))
            continue
        _require(current == entry['before_sha256'], 'STATE_CONFLICT')
        source = clean_text(data, 'STATE_SOURCE')
        result = run_ops(entry['path'], source, entry['ops']).encode('utf-8')
        _require(sha256_bytes(result) == entry['after_sha256'], 'STATE_RESULT_MISMATCH')
        check_result(source, result)
        out.append((entry['path'], target, result))
    return out


def replace_file(target, data, task_id):
    """Exclusive temporary file in the same directory, flushed, same permission bits, then os.replace."""
    directory, name = os.path.split(target)
    tmp = os.path.join(directory, '.' + name + '.' + task_id + '.state-edit.tmp')
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
    except FileExistsError:
        raise Stop('STATE_TEMP_EXISTS')
    except OSError:
        raise Stop('STATE_WRITE_FAILED')
    created = True
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, stat.S_IMODE(os.lstat(target).st_mode))
        os.replace(tmp, target)
        created = False
    except OSError:
        raise Stop('STATE_WRITE_FAILED')
    finally:
        if created:
            try:
                os.remove(tmp)
            except OSError:
                pass


def apply(root, task_id, prompt_sha, plan_sha):
    plan = classify(root, task_id, prompt_sha, plan_sha)
    written = already = 0
    for path, target, data in plan:
        if data is None:
            already += 1
            print('STATE_EDIT ALREADY_APPLIED ' + path)
            continue
        target_of(root, path)
        replace_file(target, data, task_id)
        written += 1
        print('STATE_EDIT WRITTEN ' + path)
    print('STATE_EDIT RESULT written=' + str(written) + ' already=' + str(already))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Canonical writer for the registered state files (B-107).')
    parser.add_argument('command', choices=('seal', 'apply'))
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--prompt-sha256', required=True)
    parser.add_argument('--plan-sha256')
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        print('S1 USAGE')
        return 2
    if not batch_runner.TASK_RE.match(args.task_id):
        print('S1 STATE_TASK_ID_INVALID')
        return 2
    prompt_sha = args.prompt_sha256.lower()
    plan_sha = (args.plan_sha256 or '').lower()
    if not _is_sha256(prompt_sha) or (args.command == 'apply') != _is_sha256(plan_sha) \
            or (args.command == 'seal' and args.plan_sha256 is not None):
        print('S1 USAGE')
        return 2
    try:
        _require(Path.cwd().resolve() == ROOT, 'STATE_WORKING_DIRECTORY_MISMATCH')
        if args.command == 'seal':
            seal(ROOT, args.task_id, prompt_sha)
        else:
            apply(ROOT, args.task_id, prompt_sha, plan_sha)
    except Stop as s:
        print('S1 ' + str(s))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
