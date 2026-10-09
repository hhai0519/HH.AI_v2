#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/prompt_builder.py
Macro-side prompt builder for canonical runner batches (B-115).

The Macro Auditor writes a batch definition (JSON) plus the final author files and prose; this tool
turns them into the delivered prompt deterministically, so specs, unique-anchor ops, hashes and the
start-up text are never hand-written. It produces what scripts/batch_runner.py consumes and never
executes a batch itself.

Usage:
  python scripts/prompt_builder.py build   --repo <repo> --definition <def.json> --out-dir <dir>
  python scripts/prompt_builder.py check   --repo <repo> --prompt <dir>/<TASK_ID>-prompt.txt
  python scripts/prompt_builder.py startup --prompt <file> --download-dir <dir> --workspace <dir>

Definition (all paths relative to the definition file):
  task_id, kind ("production" | "promotion"), base_oid, prose_head, prose_tail,
  substitutions {TOKEN: file}           optional; each TOKEN must occur in the prose exactly once
  production: branch, commit_message, e24 (bool), runner_update (bool, optional), focused (object|null),
    start (optional) {mode: "adopt", start_branch, adopt_hashes {repo_path: sha256}} resumes from the verified
                                         worktree of a stopped batch; omitted means a clean start
    code_files {repo_path: file}        full final text; ops are derived against the Base blob
    new_files {repo_path: {file, block}} file content carried in a prompt block
    text_ops [{path, type, ...}]         type replace {old,new} | replace_line {prefix,new} |
                                         insert_after_line {prefix,text}; prefixes must match one line
    e24_evidence (file, when e24), verify_only [paths], historical [paths or prefixes ending in '/']
  promotion: candidate_oid, candidate_branch
  Placeholders {TASK_ID} {BASE_OID} {BASE7} {BRANCH} {ALLOWED} are expanded in prose and text_ops (never in
  code_files or new_files, which are carried verbatim).

Guarantees (fail closed with "PROMPT_BUILDER FAIL <CODE>" and exit 1):
- Ops are applied with the runner's own algorithm (batch_runner.apply_ops) and the result must equal the
  declared final text of every code file; author hashes are LF SHA-256 of that result.
- The assembled prompt is parsed with batch_runner.load_spec (the runner's validator), every machine block
  occurs exactly once, no carriage return, no placeholder or substitution token is left.
- Every E24 hit outside the allowed scope needs an explicit VERIFY_ONLY or HISTORICAL disposition.
- The same inputs always produce the same bytes.
- After assembly the runner's own build_authors reconstructs every author file from the prompt; the result must
  equal the authored texts and hashes (RUNNER_REBUILD_MISMATCH otherwise).
- Every path is a safe repository-relative POSIX path (no drive letter, colon, backslash, absolute, '.', '..',
  empty segment, .git or generated path) and belongs to exactly one source category (code_files, new_files or
  text_ops); this is checked before anything is written, and outputs must stay inside --out-dir.
- startup accepts only drive-absolute Windows directories made of letters, digits, '.', '_', '-' and backslash so every path is a
  single literal token; the hash command uses -LiteralPath with a PowerShell single-quoted literal.
- check creates its copy exclusively, keeps it open while the tools run and removes it only if it is still the
  same file with the same bytes; an existing identical copy is used and never removed.
"""

import argparse
import difflib
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
    import batch_runner  # noqa: E402 - the runner's own parser and op algorithm are the reference
finally:
    sys.path.pop(0)

PLACEHOLDERS = ('{TASK_ID}', '{BASE_OID}', '{BASE7}', '{BRANCH}', '{ALLOWED}')
RESERVED_BLOCKS = ('BATCH_SPEC_JSON', 'PLAN_JSON', 'ALLOWED_SCOPE_JSON', 'E24_EVIDENCE_JSON')
CHECK_TIMEOUT = 300


class BuildError(Exception):
    """Fixed failure code; never carries file content."""


def _require(cond, code):
    if not cond:
        raise BuildError(code)


def sha256_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def read_text(path, code):
    try:
        data = Path(path).read_bytes()
    except OSError:
        raise BuildError(code + '_UNREADABLE')
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        raise BuildError(code + '_NOT_UTF8')
    _require('\r' not in text, code + '_CRLF')
    return text


def base_blob(repo, base, path):
    r = subprocess.run(['git', '-C', repo, 'cat-file', 'blob', base + ':' + path], stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120)
    _require(r.returncode == 0, 'BASE_BLOB_UNREADABLE')
    try:
        text = r.stdout.decode('utf-8')
    except UnicodeDecodeError:
        raise BuildError('BASE_BLOB_NOT_UTF8')
    _require('\r' not in text, 'BASE_BLOB_CRLF')
    return text


def check_clean_text(text, code):
    """Final author text: LF only, one trailing newline, no trailing whitespace on any line."""
    _require(text.endswith('\n') and not text.endswith('\n\n'), code + '_TRAILING_NEWLINE')
    _require(all(line == line.rstrip() for line in text.split('\n')), code + '_TRAILING_WHITESPACE')


def derive_ops(path, base_text, target):
    """Unique-anchor replacements that turn base_text into target when applied in order."""
    b = target.splitlines(keepends=True)
    cur = base_text
    ops = []
    while cur != target:
        a = cur.splitlines(keepends=True)
        groups = list(difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_grouped_opcodes(0))
        _require(groups, 'OPS_DERIVATION_FAILED')
        g = groups[0]
        i1, i2, j1, j2 = g[0][1], g[-1][2], g[0][3], g[-1][4]
        ctx = 1
        while True:
            lo, hi = max(0, i1 - ctx), min(len(a), i2 + ctx)
            old = ''.join(a[lo:hi])
            if old and cur.count(old) == 1:
                break
            _require(lo > 0 or hi < len(a), 'OPS_ANCHOR_NOT_FOUND')
            ctx += 1
        new = ''.join(a[lo:i1]) + ''.join(b[j1:j2]) + ''.join(a[i2:hi])
        ops.append({'path': path, 'old': old, 'new': new})
        cur = cur.replace(old, new)
        _require(len(ops) < 500, 'OPS_LIMIT')
    return ops


SAFE_SEGMENT = re.compile(r'^[A-Za-z0-9_.][A-Za-z0-9._-]*$')
WINDOWS_DEVICE = re.compile(r'^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(\.|$)', re.IGNORECASE)


def check_repo_path(path):
    """Repository-relative POSIX path only: no drive, colon, backslash, absolute, '.'/'..' or empty segment, no segment
    that Windows would rename (trailing dot) or treat as a device (CON, NUL, ...), not .git and not a generated path."""
    _require(isinstance(path, str) and path and len(path) <= 300, 'PATH_INVALID')
    parts = path.split('/')
    _require(all(SAFE_SEGMENT.match(seg) and not seg.endswith('.') and not WINDOWS_DEVICE.match(seg) for seg in parts),
             'PATH_INVALID')
    _require(parts[0].lower() != '.git' and path not in batch_runner.GENERATED, 'PATH_INVALID')
    return path


def expand(text, values):
    for token, value in values.items():
        text = text.replace(token, value)
    return text


def single_line(text, prefix, code):
    hits = [line for line in text.split('\n') if line.startswith(prefix)]
    _require(len(hits) == 1, code)
    return hits[0]


def text_op(texts, op, values):
    path, kind = op.get('path'), op.get('type')
    _require(isinstance(path, str) and path in texts, 'TEXT_OP_PATH_INVALID')
    cur = texts[path]
    if kind == 'replace':
        old, new = expand(op['old'], values), expand(op['new'], values)
    elif kind == 'replace_line':
        old = single_line(cur, expand(op['prefix'], values), 'TEXT_OP_LINE_NOT_UNIQUE')
        new = expand(op['new'], values)
        _require('\n' not in new, 'TEXT_OP_NEWLINE_IN_LINE')
    elif kind == 'insert_after_line':
        line = single_line(cur, expand(op['prefix'], values), 'TEXT_OP_LINE_NOT_UNIQUE')
        old, new = line + '\n', line + '\n' + expand(op['text'], values) + '\n'
    else:
        raise BuildError('TEXT_OP_TYPE_INVALID')
    _require(old and '\r' not in new, 'TEXT_OP_INVALID')
    _require(cur.count(old) == 1, 'TEXT_OP_ANCHOR_NOT_UNIQUE')
    return {'path': path, 'old': old, 'new': new}


def block(name, body):
    _require('\r' not in body, 'BLOCK_CRLF')
    return '<<<BEGIN ' + name + '>>>\n' + body + '\n<<<END ' + name + '>>>\n'


def dispositions(raw, allowed, verify_only, historical):
    out = dict(raw)
    out['results'] = []
    for r in raw.get('results', []):
        disp = {}
        for p in r.get('matched_paths', []):
            if p in allowed:
                disp[p] = 'UPDATE'
            elif p in verify_only:
                disp[p] = 'VERIFY_ONLY'
            elif any(p == h or (h.endswith('/') and p.startswith(h)) for h in historical):
                disp[p] = 'HISTORICAL_NO_CHANGE'
            else:
                raise BuildError('E24_UNDISPOSITIONED')
        out['results'].append(dict(r, dispositions=disp))
    return out


def start_spec(start, author_paths):
    """Clean start by default; adopt (resume from a stopped batch's verified worktree) when declared."""
    if start is None:
        return {'mode': 'clean'}
    _require(isinstance(start, dict) and start.get('mode') == 'adopt' and set(start) == {'mode', 'start_branch', 'adopt_hashes'},
             'START_INVALID')
    adopt = start['adopt_hashes']
    _require(isinstance(adopt, dict) and adopt and set(adopt) <= author_paths, 'START_INVALID')
    for path in adopt:
        check_repo_path(path)
    return {'mode': 'adopt', 'start_branch': start['start_branch'], 'adopt_hashes': dict(sorted(adopt.items()))}


def build(repo, definition_path):
    """Return (prompt_text, authors {path: sha256}, authored {path: text})."""
    base_dir = Path(definition_path).resolve().parent
    try:
        d = json.loads(read_text(definition_path, 'DEFINITION'))
    except ValueError:
        raise BuildError('DEFINITION_JSON_INVALID')
    _require(isinstance(d, dict) and d.get('schema_version') == 1, 'DEFINITION_SCHEMA_INVALID')
    task, kind, base = d.get('task_id'), d.get('kind'), d.get('base_oid')
    _require(isinstance(task, str) and batch_runner.TASK_RE.match(task), 'TASK_ID_INVALID')
    _require(isinstance(base, str) and batch_runner.OID_RE.match(base), 'BASE_OID_INVALID')
    branch = d.get('branch') if kind == 'production' else d.get('candidate_branch')
    values = {'{TASK_ID}': task, '{BASE_OID}': base, '{BASE7}': base[:7], '{BRANCH}': str(branch)}

    authors, authored, ops, extra_blocks = {}, {}, [], []
    if kind == 'production':
        code_files, new_files = d.get('code_files') or {}, d.get('new_files') or {}
        op_paths = {op.get('path') for op in d.get('text_ops') or []}
        for path in list(code_files) + list(new_files) + sorted(op_paths, key=str):
            check_repo_path(path)
        # One source category per path: overlapping categories would make the declared final text ambiguous.
        _require(not (set(code_files) & set(new_files)) and not (set(code_files) & op_paths)
                 and not (set(new_files) & op_paths), 'SOURCE_CATEGORY_OVERLAP')
        texts = {}
        for path, rel in sorted(code_files.items()):
            target = read_text(base_dir / rel, 'CODE_FILE')
            check_clean_text(target, 'CODE_FILE')
            texts[path] = base_blob(repo, base, path)
            ops.extend(derive_ops(path, texts[path], target))
            texts[path] = target
        for op in d.get('text_ops') or []:
            if op.get('path') not in texts:
                texts[op.get('path')] = base_blob(repo, base, op.get('path'))
        allowed_preview = sorted(set(texts) | set(d.get('new_files') or {}) | set(batch_runner.GENERATED))
        values['{ALLOWED}'] = ';'.join(allowed_preview)
        for op in d.get('text_ops') or []:
            o = text_op(texts, op, values)
            ops.append(o)
            texts[o['path']] = texts[o['path']].replace(o['old'], o['new'])
        # Reference application: replay all ops on the Base blobs with the runner's own algorithm.
        replay = {p: base_blob(repo, base, p) for p in texts}
        replay = batch_runner.apply_ops(replay, ops) if ops else replay
        _require(replay == texts, 'REPLAY_MISMATCH')
        for path, rel in code_files.items():
            _require(texts[path] == read_text(base_dir / rel, 'CODE_FILE'), 'CODE_FILE_NOT_FINAL')
        for path, text in texts.items():
            authors[path] = {'source': {'kind': 'base'}, 'sha256': sha256_text(text)}
            authored[path] = text
        for path, nf in sorted((d.get('new_files') or {}).items()):
            name = nf.get('block')
            _require(isinstance(name, str) and batch_runner.BLOCK_RE.match(name) and name not in RESERVED_BLOCKS,
                     'NEW_FILE_BLOCK_INVALID')
            text = read_text(base_dir / nf['file'], 'NEW_FILE')
            check_clean_text(text, 'NEW_FILE')
            _require(not any(l.startswith('<<<BEGIN ') or l.startswith('<<<END ') for l in text.split('\n')),
                     'NEW_FILE_BLOCK_MARKER')
            authors[path] = {'source': {'kind': 'block', 'name': name}, 'sha256': sha256_text(text)}
            authored[path] = text
            extra_blocks.append((name, text[:-1]))
        allowed = sorted(set(authors) | set(batch_runner.GENERATED))
        _require(allowed == allowed_preview, 'ALLOWED_SCOPE_DRIFT')
        spec = {'schema_version': 1, 'task_id': task, 'kind': 'production', 'base_oid': base, 'branch': branch,
                'commit_message': d.get('commit_message'), 'e24': d.get('e24')}
        if d.get('runner_update'):
            spec['runner_update'] = True
        spec.update({'focused': d.get('focused'), 'start': start_spec(d.get('start'), set(authors)),
                     'authors': dict(sorted(authors.items())), 'ops': ops})
        machine = [block('BATCH_SPEC_JSON', json.dumps(spec, ensure_ascii=False, indent=1)), '\n',
                   block('PLAN_JSON', json.dumps({'task_id': task, 'base_oid': base, 'allowed_paths': allowed,
                                                  'required_paths': allowed, 'max_plan_revisions': 3,
                                                  'revision_count': 0, 'plan_origin': 'EXTERNAL_MACRO_PROMPT'},
                                                 indent=1)), '\n']
        if d.get('e24') is True:
            raw = json.loads(read_text(base_dir / d['e24_evidence'], 'E24_EVIDENCE'))
            _require(raw.get('base_oid') == base and raw.get('mode') == 'REQUIRED', 'E24_EVIDENCE_BINDING')
            ev = dispositions(raw, set(allowed), set(d.get('verify_only') or []), list(d.get('historical') or []))
            machine += [block('ALLOWED_SCOPE_JSON', json.dumps({'schema_version': 1, 'allowed_scope': allowed}, indent=1)),
                        '\n', block('E24_EVIDENCE_JSON', json.dumps(ev, ensure_ascii=False, indent=1)), '\n']
        for name, body in extra_blocks:
            machine += [block(name, body), '\n']
    elif kind == 'promotion':
        values['{ALLOWED}'] = 'NONE'
        spec = {'schema_version': 1, 'task_id': task, 'kind': 'promotion', 'base_oid': base,
                'candidate_oid': d.get('candidate_oid'), 'candidate_branch': d.get('candidate_branch')}
        machine = [block('BATCH_SPEC_JSON', json.dumps(spec, indent=1)), '\n']
    else:
        raise BuildError('KIND_INVALID')

    head = expand(read_text(base_dir / d['prose_head'], 'PROSE'), values).rstrip('\n') + '\n'
    tail = expand(read_text(base_dir / d['prose_tail'], 'PROSE'), values)
    for token, rel in sorted((d.get('substitutions') or {}).items()):
        _require(token.startswith('{') and token.endswith('}') and token not in PLACEHOLDERS, 'SUBSTITUTION_TOKEN_INVALID')
        _require((head + tail).count(token) == 1, 'SUBSTITUTION_TOKEN_COUNT')
        value = read_text(base_dir / rel, 'SUBSTITUTION').strip()
        head, tail = head.replace(token, value), tail.replace(token, value)
    # Only prose is expanded; new-file blocks are verbatim and may legitimately contain placeholder text.
    _require(not any(t in head + tail for t in PLACEHOLDERS), 'PLACEHOLDER_LEFT')
    text = head + '\n' + ''.join(machine) + tail
    _require('\r' not in text, 'PROMPT_CRLF')
    lines = batch_runner.prompt_lines(text.encode('utf-8'))
    names = list(RESERVED_BLOCKS[:2]) + (list(RESERVED_BLOCKS[2:]) if spec.get('e24') else []) + [n for n, _ in extra_blocks]
    for name in names if kind == 'production' else ['BATCH_SPEC_JSON']:
        _require(lines.count('<<<BEGIN ' + name + '>>>') == 1 and lines.count('<<<END ' + name + '>>>') == 1,
                 'BLOCK_COUNT_INVALID')
    try:
        spec_loaded = batch_runner.load_spec(lines, task)
    except batch_runner.Halt as h:
        raise BuildError('RUNNER_SPEC_REJECTED_' + str(h))
    if kind == 'production':
        # Reference reconstruction: the runner's own build_authors on the assembled prompt must give exactly
        # the authored texts and hashes (catches anything the per-op replay cannot see).
        try:
            rebuilt = batch_runner.build_authors(repo, spec_loaded, lines)
        except batch_runner.Halt as h:
            raise BuildError('RUNNER_REBUILD_FAILED_' + str(h))
        _require(rebuilt == authored, 'RUNNER_REBUILD_MISMATCH')   # author hashes are derived from authored
    return text, {p: e['sha256'] for p, e in sorted(authors.items())}, authored


def write_outputs(out_dir, task, text, authors, authored):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    prompt_path = out / (task + '-prompt.txt')
    prompt_path.write_bytes(text.encode('utf-8'))
    (out / 'authors.json').write_bytes((json.dumps(authors, indent=1) + '\n').encode('utf-8'))
    root = (out / 'authored').resolve()
    for path, content in authored.items():
        target = out / 'authored' / check_repo_path(path)
        _require(root in target.resolve().parents, 'OUTPUT_PATH_ESCAPE')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode('utf-8'))
    return prompt_path


def prompt_task(prompt_path):
    name = Path(prompt_path).name
    _require(name.endswith('-prompt.txt'), 'PROMPT_NAME_INVALID')
    task = name[:-len('-prompt.txt')]
    _require(batch_runner.TASK_RE.match(task), 'PROMPT_NAME_INVALID')
    try:
        data = Path(prompt_path).read_bytes()
        spec = json.loads(batch_runner.extract_block(batch_runner.prompt_lines(data), 'BATCH_SPEC_JSON'))
    except (OSError, ValueError, batch_runner.Halt):
        raise BuildError('PROMPT_UNREADABLE')
    _require(isinstance(spec, dict) and spec.get('task_id') == task, 'PROMPT_TASK_MISMATCH')
    return task, data


def windows_dir(path, code):
    """Drive-absolute Windows directory made only of letters, digits and . _ - \\ (no space, quote, $, backtick,
    control or other shell-significant character), so it is one literal token in PowerShell and cmd alike."""
    _require(isinstance(path, str) and re.match(r'^[A-Za-z]:\\', path) is not None, code)
    _require(all(ch.isalnum() or ch in '._-\\' for ch in path[2:]), code)
    _require('\\\\' not in path[2:] and '\\..' not in path + '\\' and '\\.\\' not in path + '\\', code)
    return path.rstrip('\\')


def ps_literal(text):
    """PowerShell single-quoted literal (no expansion of $ or backtick)."""
    return "'" + text.replace("'", "''") + "'"


def startup_lines(prompt_path, download_dir, workspace):
    task, data = prompt_task(prompt_path)
    sha = hashlib.sha256(data).hexdigest()
    source = windows_dir(download_dir, 'DOWNLOAD_DIR_INVALID') + '\\' + Path(prompt_path).name
    workspace = windows_dir(workspace, 'WORKSPACE_INVALID')
    return [
        'SHA256_UPPER=' + sha.upper(),
        '---STARTUP---',
        '請執行 HH.AI_v2 批次 ' + task + '。作用中工作區須為 ' + workspace + '；在該 repo 根目錄只執行下列一行命令一次，一字不改：',
        'python scripts/prompt_intake.py --task-id ' + task + ' --source ' + source + ' --sha256 ' + sha,
        '命令成功後，以 IDE 原生檢視工具從第一行讀到最後一行 .git/' + task + '-prompt.txt，並完全依其指示執行；'
        '命令失敗則停止並原樣回報輸出，不得重試或修改命令。',
        '---HASHCMD---',
        'Get-FileHash -Algorithm SHA256 -LiteralPath ' + ps_literal(source),
    ]


def still_owned(target, owned, data):
    """True only if the name still refers to the regular file this call created, holding exactly data.

    Never blocks and never reads more than len(data) + 1 bytes. Layers: lstat must show a regular file (rejects a
    symlink, FIFO, device or directory even where O_NOFOLLOW / O_NONBLOCK do not exist, as on Windows); the open is
    non-blocking and does not follow links where the platform supports it (covers a swap after the lstat); identity
    is compared from two descriptors (the same stat source on every platform) before any byte is read.
    """
    try:
        if not stat.S_ISREG(os.lstat(target).st_mode):
            return False
        fd2 = os.open(str(target), os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0)
                      | getattr(os, 'O_NOFOLLOW', 0))
    except OSError:
        return False
    try:
        st = os.fstat(fd2)
        if (st.st_dev, st.st_ino) != owned:          # the held descriptor keeps this identity a regular file
            return False
        got, limit = [], len(data) + 1
        while limit > 0:
            chunk = os.read(fd2, limit)
            if not chunk:
                break
            got.append(chunk)
            limit -= len(chunk)
        return b''.join(got) == data
    except OSError:
        return False
    finally:
        os.close(fd2)


def check(repo, prompt_path, runner=subprocess.run):
    """Run the standalone validator and the bound governance preflight on the exact prompt bytes."""
    task, data = prompt_task(prompt_path)
    target = Path(repo) / '.git' / (task + '-prompt.txt')
    owned, fd = None, None
    try:
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o644)
    except FileExistsError:
        # An existing copy is used only if it is a regular file with exactly these bytes; it is never removed.
        _require(not os.path.islink(target) and target.is_file() and target.read_bytes() == data, 'CHECK_TARGET_DIFFERS')
    except OSError:
        raise BuildError('CHECK_TARGET_UNWRITABLE')
    else:
        # The descriptor stays open until clean-up, so the file identity cannot be freed and reused meanwhile.
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            st = os.fstat(fd)
            owned = (st.st_dev, st.st_ino)
        except OSError:
            os.close(fd)
            raise BuildError('CHECK_TARGET_UNWRITABLE')
    try:
        rel = '.git/' + task + '-prompt.txt'
        py = sys.executable
        for args in ([py, 'scripts/validate_prompt_manifest.py', '--file', rel, '--require-contract'],
                     [py, 'scripts/governance_preflight.py', '--task-id', task, '--prompt-file', rel]):
            try:
                r = runner(args, cwd=repo, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=CHECK_TIMEOUT)
            except (OSError, subprocess.TimeoutExpired):
                raise BuildError('CHECK_COMMAND_FAILED')
            _require(r.returncode == 0, 'CHECK_' + ('MANIFEST' if 'validate' in args[1] else 'PREFLIGHT') + '_FAILED')
    finally:
        if owned is not None:
            # Remove only the copy this call created: same file identity and still these bytes. A replaced or
            # altered file is left in place and reported (residual: no atomic compare-and-delete in the OS API).
            try:
                same = still_owned(target, owned, data)
            finally:
                os.close(fd)
            if not same:
                raise BuildError('CHECK_COPY_REPLACED')
            target.unlink()
    return task


def main(argv=None):
    parser = argparse.ArgumentParser(description='Macro-side prompt builder (B-115).')
    sub = parser.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build')
    b.add_argument('--repo', required=True)
    b.add_argument('--definition', required=True)
    b.add_argument('--out-dir', required=True)
    c = sub.add_parser('check')
    c.add_argument('--repo', required=True)
    c.add_argument('--prompt', required=True)
    s = sub.add_parser('startup')
    s.add_argument('--prompt', required=True)
    s.add_argument('--download-dir', required=True)
    s.add_argument('--workspace', required=True)
    args = parser.parse_args(argv)
    try:
        if args.cmd == 'build':
            text, authors, authored = build(args.repo, args.definition)
            task = json.loads(batch_runner.extract_block(batch_runner.prompt_lines(text.encode('utf-8')),
                                                         'BATCH_SPEC_JSON'))['task_id']
            path = write_outputs(args.out_dir, task, text, authors, authored)
            print('PROMPT_BUILDER BUILT ' + str(path) + ' sha256=' + hashlib.sha256(text.encode('utf-8')).hexdigest())
        elif args.cmd == 'check':
            print('PROMPT_BUILDER CHECK PASS ' + check(args.repo, args.prompt))
        else:
            print('\n'.join(startup_lines(args.prompt, args.download_dir, args.workspace)))
    except BuildError as e:
        print('PROMPT_BUILDER FAIL ' + str(e))
        return 1
    except (KeyError, TypeError, AttributeError):
        print('PROMPT_BUILDER FAIL DEFINITION_INVALID')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
