#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/delivery_pack.py
Macro-side delivery package generator and delivery-reply check (B-119 G1 Q1).

The Macro Auditor builds and checks a prompt with scripts/prompt_builder.py; this tool turns the finished prompt
into what the USER receives, so no delivery block is hand-written or hand-copied:

  python scripts/delivery_pack.py build --prompt <dir>/<TASK_ID>-prompt.txt --role-code <CODE>
                                        --download-dir <C:\\...> --workspace <C:\\...> --out-dir <new dir>
  python scripts/delivery_pack.py verify-reply --pack-dir <out dir> --reply <reply text file>

build writes, create-only, into an empty or new --out-dir exactly three files:
  <TASK_ID>-prompt.txt                         the prompt bytes, unchanged (TXT backup)
  HHAI_<CODE>_<TASK_ID>_<YYMMDD-HHMM>.zip      the prompt plus SHA256SUMS.txt (primary file); the time is the
                                               Taiwan time (UTC+08:00) read from the clock at build time
  DELIVERY.txt                                 header (task, role, stamp, directories, file names and hashes),
                                               then block 1, block 2, block 3 and the hash command between markers

Block 1 is one fixed PowerShell 5.1 template that never overwrites a file: it extracts only the prompt entry from
the ZIP when the TXT is not already in the download directory, then prints PROMPT_READY only if the SHA-256 of the
file there equals the prompt SHA-256, PROMPT_MISSING when neither file is usable, and MISMATCH <hash> otherwise.
It runs no native command, so $ErrorActionPreference='Stop' covers every failure and no $LASTEXITCODE handling
exists. lint_block1 enforces this with a token allowlist taken from the template itself: only its cmdlets,
parameters, keywords, type names, members and variables, and single-quoted literals; the call operator outside the
leading "& {", dot-invocation, redirection, pipelines, double-quoted strings, here-strings, backticks, comments and
every other token fail (PS_TOKEN_NOT_ALLOWED, PS_CALL_OPERATOR_FORBIDDEN, PS_CONSTRUCT_UNSUPPORTED).
Block 3 is scripts/prompt_builder.py startup output, byte for byte.

verify-reply first rebuilds the whole package from the prompt in --pack-dir and the header of its DELIVERY.txt;
the directory must hold exactly the three files and each must equal the rebuild byte for byte (PACK_*). It then
checks the reply text the Macro is about to send:
  - no carriage return and no HTML comment (nothing can be hidden from the rendered reply);
  - every fenced code block is closed; exactly one fenced block is block 1, exactly one is block 2 and exactly one
    is block 3, each with exactly the delivered lines and nothing else, in that order; no other fenced block repeats
    any delivered line;
  - outside fenced blocks, a line naming only Executor and a line naming only 審查官 each give "<A> 至 <B> 分鐘"
    with 0 < A <= B and a non-empty 依據 after it; a line naming both roles counts for neither.

Fails closed with "DELIVERY_PACK FAIL <CODE>" and exit 1; never prints prompt or reply content.
"""

import argparse
import datetime
import hashlib
import io
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import prompt_builder  # noqa: E402 - prompt name, task binding, startup text and literal quoting
finally:
    sys.path.pop(0)

TAIWAN = datetime.timezone(datetime.timedelta(hours=8))
ROLE_RE = re.compile(r'^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$')
SAFE_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
STAMP_RE = re.compile(r'^\d{6}-\d{4}$')
SHA_UPPER_RE = re.compile(r'^[0-9A-F]{64}$')
MARKERS = ('---BLOCK1---', '---BLOCK2---', '---BLOCK3---', '---HASHCMD---', '---END---')
HEADER = ('PACK_SCHEMA', 'PACK_TASK', 'PACK_ROLE', 'PACK_STAMP', 'PACK_DOWNLOAD_DIR', 'PACK_WORKSPACE')
SUMS_NAME = 'SHA256SUMS.txt'
DELIVERY_NAME = 'DELIVERY.txt'


class PackError(Exception):
    """Fixed failure code; never carries file content."""


def _require(cond, code):
    if not cond:
        raise PackError(code)


def taiwan_stamp(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    _require(now.tzinfo is not None, 'CLOCK_NOT_AWARE')
    return now.astimezone(TAIWAN).strftime('%y%m%d-%H%M')


# -- block 1 and its token allowlist --------------------------------------------------------------------

BARE_WORDS = {w.lower() for w in ('Join-Path', 'Test-Path', 'Add-Type', 'Get-FileHash', 'if', 'else', 'try',
                                  'finally', 'Leaf', 'SHA256', 'System.IO.Compression.FileSystem')}
PARAMETERS = {p.lower() for p in ('-LiteralPath', '-PathType', '-AssemblyName', '-Algorithm', '-not', '-and', '-ceq')}
TYPES = {t.lower() for t in ('[IO.Compression.ZipFile]', '[IO.Compression.ZipFileExtensions]')}
VARIABLES = {v.lower() for v in ('$ErrorActionPreference', '$dl', '$n', '$p', '$z', '$a', '$e', '$h', '$false')}
MEMBERS = {m.lower() for m in ('::OpenRead', '::ExtractToFile', '.GetEntry', '.Dispose', '.Hash')}
TOKEN_RE = re.compile(r"\s+|''|\$[A-Za-z_]\w*|\[[A-Za-z.]+\]|::[A-Za-z]\w*|\.[A-Za-z]\w*|-[A-Za-z]+"
                      r"|[A-Za-z][\w.-]*|[{}();,=+]|.", re.S)


def _strip_literals(text):
    """Replace every single-quoted literal by '' so its contents are never read as code."""
    _require(not any(c in text for c in '"`#@|<>'), 'PS_CONSTRUCT_UNSUPPORTED')
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] == "'":
            j = i + 1
            while j < n:
                if text[j] == "'" and j + 1 < n and text[j + 1] == "'":
                    j += 2
                    continue
                if text[j] == "'":
                    break
                j += 1
            _require(j < n, 'PS_UNTERMINATED_STRING')
            out.append("''")
            i = j + 1
            continue
        out.append(text[i])
        i += 1
    return ''.join(out)


def lint_block1(text):
    """Token allowlist of the block 1 template: anything that could invoke another command or write elsewhere fails."""
    _require(text.startswith('& { ') and text.endswith(' }'), 'PS_CALL_OPERATOR_FORBIDDEN')
    body = _strip_literals(text[2:])
    _require('&' not in body, 'PS_CALL_OPERATOR_FORBIDDEN')
    for m in TOKEN_RE.finditer(body):
        tok = m.group(0)
        low = tok.lower()
        if tok.isspace() or tok == "''" or (len(tok) == 1 and tok in '{}();,=+'):
            continue
        if tok.startswith('$') and low in VARIABLES:
            continue
        if (tok.startswith('[') and low in TYPES) or (tok.startswith(('::', '.')) and low in MEMBERS):
            continue
        if tok.startswith('-') and low in PARAMETERS:
            continue
        if tok[0].isalpha() and low in BARE_WORDS:
            continue
        raise PackError('PS_TOKEN_NOT_ALLOWED')
    return True


def block1_text(download_dir, prompt_name, zip_name, sha_upper):
    _require(SAFE_NAME_RE.match(prompt_name) and SAFE_NAME_RE.match(zip_name), 'NAME_UNSAFE')
    _require(SHA_UPPER_RE.match(sha_upper) is not None, 'SHA_INVALID')
    lit = prompt_builder.ps_literal
    text = ("& { $ErrorActionPreference='Stop'; $dl=" + lit(download_dir) + "; $n=" + lit(prompt_name)
            + "; $p=Join-Path $dl $n; $z=Join-Path $dl " + lit(zip_name)
            + "; if (-not (Test-Path -LiteralPath $p) -and (Test-Path -LiteralPath $z -PathType Leaf)) "
            "{ Add-Type -AssemblyName System.IO.Compression.FileSystem; $a=[IO.Compression.ZipFile]::OpenRead($z); "
            "try { $e=$a.GetEntry($n); if ($e) { [IO.Compression.ZipFileExtensions]::ExtractToFile($e, $p, $false) } } "
            "finally { $a.Dispose() } }; if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { 'PROMPT_MISSING' } "
            "else { $h=(Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash; if ($h -ceq " + lit(sha_upper)
            + ") { 'PROMPT_READY' } else { 'MISMATCH ' + $h } } }")
    lint_block1(text)
    return text


# -- assembly (shared by build and verify-reply) ---------------------------------------------------------

def zip_bytes(prompt_name, data, stamp):
    """Deterministic ZIP: stored entries, fixed order, timestamp and attributes taken from the stamp."""
    dt = datetime.datetime.strptime(stamp, '%y%m%d-%H%M')
    sums = (hashlib.sha256(data).hexdigest() + '  ' + prompt_name + '\n').encode('ascii')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as zf:
        for name, payload in ((prompt_name, data), (SUMS_NAME, sums)):
            info = zipfile.ZipInfo(name, date_time=(dt.year, dt.month, dt.day, dt.hour, dt.minute, 0))
            info.create_system = 0
            info.external_attr = 0
            zf.writestr(info, payload)
    return buf.getvalue()


def assemble(prompt_path, role_code, download_dir, workspace, stamp):
    """Every output file as bytes, from the prompt and the five parameters only."""
    _require(ROLE_RE.match(role_code or '') is not None, 'ROLE_CODE_INVALID')
    _require(isinstance(stamp, str) and STAMP_RE.match(stamp) is not None, 'STAMP_INVALID')
    try:
        datetime.datetime.strptime(stamp, '%y%m%d-%H%M')
    except ValueError:
        raise PackError('STAMP_INVALID')
    task, data = prompt_builder.prompt_task(prompt_path)
    startup = prompt_builder.startup_lines(prompt_path, download_dir, workspace)
    dl = prompt_builder.windows_dir(download_dir, 'DOWNLOAD_DIR_INVALID')
    ws = prompt_builder.windows_dir(workspace, 'WORKSPACE_INVALID')
    prompt_name = task + '-prompt.txt'
    zip_name = 'HHAI_' + role_code + '_' + task + '_' + stamp + '.zip'
    prompt_sha = hashlib.sha256(data).hexdigest().upper()
    zdata = zip_bytes(prompt_name, data, stamp)
    zip_sha = hashlib.sha256(zdata).hexdigest().upper()
    _require(len(startup) == 7 and startup[1] == '---STARTUP---' and startup[5] == '---HASHCMD---', 'STARTUP_SHAPE')
    _require(startup[0] == 'SHA256_UPPER=' + prompt_sha, 'STARTUP_SHA_MISMATCH')
    lines = ['PACK_SCHEMA=1', 'PACK_TASK=' + task, 'PACK_ROLE=' + role_code, 'PACK_STAMP=' + stamp,
             'PACK_DOWNLOAD_DIR=' + dl, 'PACK_WORKSPACE=' + ws,
             'PACK_PROMPT=' + prompt_name + ' sha256=' + prompt_sha,
             'PACK_ZIP=' + zip_name + ' sha256=' + zip_sha,
             MARKERS[0], block1_text(dl, prompt_name, zip_name, prompt_sha),
             MARKERS[1], prompt_name + '  ' + prompt_sha, zip_name + '  ' + zip_sha,
             MARKERS[2]] + startup[2:5] + [MARKERS[3], startup[6], MARKERS[4]]
    return {prompt_name: data, zip_name: zdata, DELIVERY_NAME: ('\n'.join(lines) + '\n').encode('utf-8')}


def _write_new(path, data):
    with open(path, 'xb') as f:
        f.write(data)


def build(prompt_path, role_code, download_dir, workspace, out_dir, now=None):
    files = assemble(prompt_path, role_code, download_dir, workspace, taiwan_stamp(now))
    out = Path(out_dir)
    _require(not out.exists() or (out.is_dir() and not any(out.iterdir())), 'OUT_DIR_NOT_EMPTY')
    out.mkdir(parents=True, exist_ok=True)
    try:
        for name, data in files.items():
            _write_new(out / name, data)
    except FileExistsError:
        raise PackError('OUTPUT_EXISTS')
    zip_name = next(n for n in files if n.endswith('.zip'))
    prompt_name = next(n for n in files if n.endswith('-prompt.txt'))
    return (out / DELIVERY_NAME, zip_name, hashlib.sha256(files[zip_name]).hexdigest().upper(),
            hashlib.sha256(files[prompt_name]).hexdigest().upper())


# -- verify-reply ---------------------------------------------------------------------------------------

def parse_delivery(text):
    """Header values and the three delivered blocks, from a DELIVERY.txt of exactly the build layout."""
    _require(text.endswith('\n') and '\r' not in text, 'DELIVERY_SHAPE')
    lines = text[:-1].split('\n')
    _require(len(lines) == 20, 'DELIVERY_SHAPE')
    header = {}
    for i, key in enumerate(HEADER):
        _require(lines[i].startswith(key + '='), 'DELIVERY_SHAPE')
        header[key] = lines[i][len(key) + 1:]
    _require(header['PACK_SCHEMA'] == '1', 'DELIVERY_SHAPE')
    _require([lines[8], lines[10], lines[13], lines[17], lines[19]] == list(MARKERS), 'DELIVERY_SHAPE')
    return header, [lines[9]], lines[11:13], lines[14:17]


def rebuild_pack(pack_dir):
    """The pack directory must equal a rebuild from its own prompt and header; returns the three blocks."""
    pack = Path(pack_dir)
    try:
        names = sorted(p.name for p in pack.iterdir())
        delivery = (pack / DELIVERY_NAME).read_bytes()
        text = delivery.decode('utf-8')
    except (OSError, UnicodeDecodeError):
        raise PackError('PACK_UNREADABLE')
    header, b1, b2, b3 = parse_delivery(text)
    task = header['PACK_TASK']
    _require(prompt_builder.batch_runner.TASK_RE.match(task) is not None, 'DELIVERY_SHAPE')
    prompt_path = pack / (task + '-prompt.txt')
    expected = assemble(str(prompt_path), header['PACK_ROLE'], header['PACK_DOWNLOAD_DIR'],
                        header['PACK_WORKSPACE'], header['PACK_STAMP'])
    _require(names == sorted(expected), 'PACK_FILE_SET_MISMATCH')
    for name, data in expected.items():
        try:
            _require((pack / name).read_bytes() == data, 'PACK_REBUILD_MISMATCH')
        except OSError:
            raise PackError('PACK_UNREADABLE')
    return b1, b2, b3                              # equal to the rebuild, so block 1 is the linted template


RANGE_RE = re.compile(r'(\d+)\s*至\s*(\d+)\s*分鐘')
BASIS_RE = re.compile(r'依據[：:]\s*\S')
ROLES = ('Executor', '審查官')


def fenced_blocks(lines):
    """(start index, content lines) of every fenced block, and the indices of all lines outside fences."""
    blocks, outside, i = [], [], 0
    while i < len(lines):
        if lines[i].lstrip().startswith('```'):
            j = i + 1
            while j < len(lines) and not lines[j].lstrip().startswith('```'):
                j += 1
            _require(j < len(lines), 'REPLY_FENCE_UNCLOSED')
            _require(lines[j].strip() == '```', 'REPLY_FENCE_UNCLOSED')
            blocks.append((i, lines[i + 1:j]))
            i = j + 1
            continue
        outside.append(i)
        i += 1
    return blocks, outside


def _time_line_ok(line):
    m = RANGE_RE.search(line)
    if not m or not BASIS_RE.search(line[m.end():]):
        return False
    a, b = int(m.group(1)), int(m.group(2))
    return 0 < a <= b


def verify_reply_blocks(blocks3, reply_text):
    b1, b2, b3 = blocks3
    _require('\r' not in reply_text, 'REPLY_CR')
    _require('<!--' not in reply_text, 'REPLY_HIDDEN_CONTENT')
    lines = reply_text.split('\n')
    blocks, outside = fenced_blocks(lines)
    delivered = set(b1) | set(b2) | set(b3)
    positions = []
    for want, code in ((b1, 'REPLY_BLOCK1'), (b2, 'REPLY_BLOCK2'), (b3, 'REPLY_BLOCK3')):
        hits = [start for start, content in blocks if content == want]
        _require(len(hits) == 1, code + ('_MISSING' if not hits else '_DUPLICATED'))
        positions.append(hits[0])
    _require(positions == sorted(positions), 'REPLY_BLOCK_ORDER')
    for start, content in blocks:
        if start not in positions:
            _require(not (set(content) & delivered), 'REPLY_BLOCK_DUPLICATED')
    text_lines = [lines[i] for i in outside]
    for role, code in zip(ROLES, ('REPLY_TIME_EXECUTOR_MISSING', 'REPLY_TIME_AUDITOR_MISSING')):
        other = [r for r in ROLES if r != role][0]
        _require(any(role in l and other not in l and _time_line_ok(l) for l in text_lines), code)
    return True


def verify_reply(pack_dir, reply_text):
    return verify_reply_blocks(rebuild_pack(pack_dir), reply_text)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Macro-side delivery package generator (B-119 G1 Q1).')
    sub = parser.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build')
    b.add_argument('--prompt', required=True)
    b.add_argument('--role-code', required=True)
    b.add_argument('--download-dir', required=True)
    b.add_argument('--workspace', required=True)
    b.add_argument('--out-dir', required=True)
    v = sub.add_parser('verify-reply')
    v.add_argument('--pack-dir', required=True)
    v.add_argument('--reply', required=True)
    args = parser.parse_args(argv)
    try:
        if args.cmd == 'build':
            path, zip_name, zip_sha, prompt_sha = build(args.prompt, args.role_code, args.download_dir,
                                                        args.workspace, args.out_dir)
            print('DELIVERY_PACK BUILT ' + str(path))
            print('PACK_PROMPT_SHA256=' + prompt_sha)
            print('PACK_ZIP=' + zip_name + ' sha256=' + zip_sha)
        else:
            try:
                reply = Path(args.reply).read_bytes().decode('utf-8')
            except (OSError, UnicodeDecodeError):
                raise PackError('REPLY_UNREADABLE')
            verify_reply(args.pack_dir, reply)
            print('DELIVERY_REPLY PASS')
    except (PackError, prompt_builder.BuildError) as e:
        print('DELIVERY_PACK FAIL ' + str(e))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
