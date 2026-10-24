# -*- coding: utf-8 -*-
"""B-119 G1 Q1 delivery package: create-only build, deterministic ZIP, block 1 behaviour in a real PowerShell,
native-command exit lint and the delivery-reply check. Files are written and compared as bytes."""
import datetime
import hashlib
import io
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import delivery_pack as dp  # noqa: E402
import prompt_builder as pb  # noqa: E402
from test_prompt_builder import TASK, _definition, repo  # noqa: E402,F401 - reuse the real-prompt fixture

DL = 'C:\\Users\\U\\Downloads'
WS = 'C:\\Users\\U\\Desktop\\HH.AI_v2'
ROLE = 'AUD-UNIT-261024'
NOW = datetime.datetime(2026, 10, 24, 9, 28, tzinfo=datetime.timezone.utc)      # 17:28 in Taiwan


@pytest.fixture
def prompt(tmp_path, repo):  # noqa: F811
    root, base = repo
    out = tmp_path / 'built'
    assert pb.main(['build', '--repo', root, '--definition', _definition(tmp_path, base), '--out-dir', str(out)]) == 0
    return out / (TASK + '-prompt.txt')


def _build(prompt, out, now=NOW, **kw):
    args = dict(role_code=ROLE, download_dir=DL, workspace=WS)
    args.update(kw)
    return dp.build(str(prompt), args['role_code'], args['download_dir'], args['workspace'], str(out), now=now)


def _code(fn, *a, **kw):
    with pytest.raises((dp.PackError, pb.BuildError)) as e:
        fn(*a, **kw)
    return str(e.value)


# ---- build -------------------------------------------------------------------------------------------------

def test_build_writes_prompt_zip_and_delivery_bound_to_the_prompt_bytes(tmp_path, prompt):
    out = tmp_path / 'pack'
    delivery, zip_name, zip_sha, prompt_sha = _build(prompt, out)
    data = prompt.read_bytes()
    assert sorted(p.name for p in out.iterdir()) == sorted([TASK + '-prompt.txt', zip_name, 'DELIVERY.txt'])
    assert zip_name == 'HHAI_' + ROLE + '_' + TASK + '_261024-1728.zip'
    assert (out / (TASK + '-prompt.txt')).read_bytes() == data
    assert prompt_sha == hashlib.sha256(data).hexdigest().upper()
    zdata = (out / zip_name).read_bytes()
    assert zip_sha == hashlib.sha256(zdata).hexdigest().upper()
    with zipfile.ZipFile(io.BytesIO(zdata)) as zf:
        assert zf.namelist() == [TASK + '-prompt.txt', 'SHA256SUMS.txt']
        assert zf.read(TASK + '-prompt.txt') == data
        assert zf.read('SHA256SUMS.txt') == (hashlib.sha256(data).hexdigest() + '  ' + TASK + '-prompt.txt\n').encode()
    header, block1, block2, block3 = dp.parse_delivery(delivery.read_bytes().decode('utf-8'))
    assert header == {'PACK_SCHEMA': '1', 'PACK_TASK': TASK, 'PACK_ROLE': ROLE, 'PACK_STAMP': '261024-1728',
                      'PACK_DOWNLOAD_DIR': DL, 'PACK_WORKSPACE': WS}
    block1 = block1[0]
    assert dp.rebuild_pack(str(out)) == ([block1], block2, block3)
    assert block2 == [TASK + '-prompt.txt  ' + prompt_sha, zip_name + '  ' + zip_sha]
    assert block3 == pb.startup_lines(str(prompt), DL, WS)[2:5]
    assert ("'" + prompt_sha + "'") in block1 and ("'" + zip_name + "'") in block1 and ("'" + DL + "'") in block1


def test_build_is_deterministic_for_the_same_clock(tmp_path, prompt):
    _build(prompt, tmp_path / 'one')
    _build(prompt, tmp_path / 'two')
    for name in os.listdir(tmp_path / 'one'):
        assert (tmp_path / 'one' / name).read_bytes() == (tmp_path / 'two' / name).read_bytes()


def test_build_refuses_a_non_empty_out_dir_and_never_overwrites(tmp_path, prompt):
    out = tmp_path / 'pack'
    out.mkdir()
    (out / 'SHA256SUMS.txt').write_bytes(b'keep me\n')
    assert _code(_build, prompt, out) == 'OUT_DIR_NOT_EMPTY'
    assert sorted(os.listdir(out)) == ['SHA256SUMS.txt'] and (out / 'SHA256SUMS.txt').read_bytes() == b'keep me\n'


@pytest.mark.parametrize('role', ['', 'aud-claude', 'AUD CLAUDE', 'AUD_CLAUDE', 'AUD-', '-AUD', 'AUD--X', 'AUD/X'])
def test_build_rejects_an_unsafe_role_code_without_writing(tmp_path, prompt, role):
    assert _code(_build, prompt, tmp_path / 'pack', role_code=role) == 'ROLE_CODE_INVALID'
    assert not (tmp_path / 'pack').exists()


@pytest.mark.parametrize('download', ['C:\\Users\\U V\\Downloads', "C:\\Users\\U'x", 'Users\\U', 'C:/Users/U'])
def test_build_rejects_a_download_dir_that_is_not_one_literal_token(tmp_path, prompt, download):
    assert _code(_build, prompt, tmp_path / 'pack', download_dir=download) == 'DOWNLOAD_DIR_INVALID'
    assert not (tmp_path / 'pack').exists()


def test_build_rejects_a_prompt_whose_name_and_task_differ(tmp_path, prompt):
    renamed = tmp_path / 'OTHER-TASK-261024-prompt.txt'
    renamed.write_bytes(prompt.read_bytes())
    assert _code(_build, renamed, tmp_path / 'pack') == 'PROMPT_TASK_MISMATCH'
    assert not (tmp_path / 'pack').exists()


def test_taiwan_stamp_is_utc_plus_8_and_refuses_a_naive_clock():
    assert dp.taiwan_stamp(datetime.datetime(2026, 10, 24, 16, 5, tzinfo=datetime.timezone.utc)) == '261025-0005'
    assert dp.taiwan_stamp(NOW) == '261024-1728'
    assert _code(dp.taiwan_stamp, datetime.datetime(2026, 10, 24, 9, 28)) == 'CLOCK_NOT_AWARE'


@pytest.mark.parametrize('kw,code', [
    (dict(prompt_name='a b.txt'), 'NAME_UNSAFE'), (dict(zip_name="x'.zip"), 'NAME_UNSAFE'),
    (dict(sha_upper='a' * 64), 'SHA_INVALID'), (dict(sha_upper='A' * 63), 'SHA_INVALID'),
])
def test_block1_rejects_unsafe_names_and_hashes(kw, code):
    args = dict(download_dir=DL, prompt_name='T-prompt.txt', zip_name='Z.zip', sha_upper='A' * 64)
    args.update(kw)
    assert _code(dp.block1_text, **args) == code


# ---- block 1 token allowlist (Q1 $LASTEXITCODE: block 1 runs no native command) ----------------------------

BLOCK1 = dp.block1_text(DL, 'T-prompt.txt', 'Z.zip', 'A' * 64)


def test_lint_accepts_the_block1_template_exactly_as_generated():
    assert dp.lint_block1(BLOCK1) is True


@pytest.mark.parametrize('text,code', [
    ("& { & 'git' status }", 'PS_CALL_OPERATOR_FORBIDDEN'),                       # quoted native command
    ("& { $cmd='git'; & $cmd status }", 'PS_CALL_OPERATOR_FORBIDDEN'),             # command held in a variable
    ("& { ./git.exe status }", 'PS_TOKEN_NOT_ALLOWED'),                             # path invocation
    ("& { . 'x.ps1' }", 'PS_TOKEN_NOT_ALLOWED'),                                    # dot-sourcing
    ("& { git status; $saved=$LASTEXITCODE; 'DONE' }", 'PS_TOKEN_NOT_ALLOWED'),     # exit code only recorded
    ("& { git status; if ($LASTEXITCODE -ne 0) { 'ignored' }; 'DONE' }", 'PS_TOKEN_NOT_ALLOWED'),
    ("& { Fake-Native argument }", 'PS_TOKEN_NOT_ALLOWED'),                          # Verb-Noun shape is not enough
    ("& { Start-Process x }", 'PS_TOKEN_NOT_ALLOWED'),
    ("& { [IO.File]::WriteAllText('x', 'y') }", 'PS_TOKEN_NOT_ALLOWED'),            # other .NET writer
    ("& { [IO.File]::OpenRead('x') }", 'PS_TOKEN_NOT_ALLOWED'),                   # allowed member, other type
    ("& { $p.Delete() }", 'PS_TOKEN_NOT_ALLOWED'),                                  # other member
    ("& { $h=(git rev-parse HEAD) }", 'PS_TOKEN_NOT_ALLOWED'),                      # native inside a subexpression
    (BLOCK1.replace('$e, $p, $false', '$e, $p, $true'), 'PS_TOKEN_NOT_ALLOWED'),    # overwrite flag
    ("git status", 'PS_CALL_OPERATOR_FORBIDDEN'),                                   # not a script block
    ("& { 'x' > f }", 'PS_CONSTRUCT_UNSUPPORTED'),                                  # redirection writes a file
    ("& { Get-Item x | git y }", 'PS_CONSTRUCT_UNSUPPORTED'),                        # pipeline
    ('& { Write-Output "$(git status)" }', 'PS_CONSTRUCT_UNSUPPORTED'),             # expanding string
    ("& { 'a' `\n; git x }", 'PS_CONSTRUCT_UNSUPPORTED'),                            # backtick
    ("& { 'a' # git x }", 'PS_CONSTRUCT_UNSUPPORTED'),                               # comment
    ("& { $s=@'\ngit x\n'@ }", 'PS_CONSTRUCT_UNSUPPORTED'),                         # here-string
    ("& { Write-Output 'unterminated }", 'PS_UNTERMINATED_STRING'),
])
def test_lint_rejects_every_form_outside_the_template_vocabulary(text, code):
    assert _code(dp.lint_block1, text) == code


# ---- verify-reply ------------------------------------------------------------------------------------------

@pytest.fixture
def pack(tmp_path, prompt):
    out = tmp_path / 'pack'
    _build(prompt, out)
    return out


def _blocks(pack):
    _, b1, b2, b3 = dp.parse_delivery((pack / 'DELIVERY.txt').read_bytes().decode('utf-8'))
    return b1, b2, b3


def _reply(pack, times=None, before='', after=''):
    b1, b2, b3 = _blocks(pack)
    times = times if times is not None else [
        '  - Executor 30 至 40 分鐘。依據：同類工具批 R3 實測 27 分鐘。',
        '  - 審查官 25 至 45 分鐘。依據：候選 diff 與 raw log 審查。']
    parts = ['## 交付', before, '**區塊一**', '```powershell'] + b1 + ['```', '**區塊二**', '```text'] + b2 + ['```',
             '**區塊三**', '```text'] + b3 + ['```', '- **預估時間**：'] + times + [after]
    return '\n'.join(parts) + '\n'


def test_verify_reply_accepts_the_exact_delivered_blocks_and_both_time_ranges(pack):
    assert dp.verify_reply(str(pack), _reply(pack)) is True


def test_verify_reply_cli_reports_pass_and_fail_without_content(tmp_path, pack, capsys):
    r = tmp_path / 'R.txt'
    r.write_bytes(_reply(pack).encode('utf-8'))
    assert dp.main(['verify-reply', '--pack-dir', str(pack), '--reply', str(r)]) == 0
    assert capsys.readouterr().out.strip() == 'DELIVERY_REPLY PASS'
    r.write_bytes(b'nothing\n')
    assert dp.main(['verify-reply', '--pack-dir', str(pack), '--reply', str(r)]) == 1
    assert capsys.readouterr().out.strip() == 'DELIVERY_PACK FAIL REPLY_BLOCK1_MISSING'


def _reply_cases(pack):
    b1, b2, b3 = _blocks(pack)
    good = _reply(pack)
    fence = lambda lines: '\n'.join(['```text'] + lines + ['```'])
    return [
        ('hidden in HTML comment', '<!--\n' + good + '-->\n', 'REPLY_HIDDEN_CONTENT'),
        ('extra command in block 1', good.replace(b1[0] + '\n```', b1[0] + "\nSet-Content x y\n```", 1),
         'REPLY_BLOCK1_MISSING'),
        ('block 1 altered', good.replace('PROMPT_READY', 'PROMPT_READY.', 1), 'REPLY_BLOCK1_MISSING'),
        ('block 1 delivered twice', _reply(pack, after='```powershell\n' + b1[0] + '\n```'), 'REPLY_BLOCK1_DUPLICATED'),
        ('modified copy elsewhere', _reply(pack, after=fence([b3[1], 'Remove-Item x'])), 'REPLY_BLOCK_DUPLICATED'),
        ('block 2 line missing', good.replace(b2[1] + '\n', '', 1), 'REPLY_BLOCK2_MISSING'),
        ('block 2 split in two fences', good.replace(b2[0] + '\n', b2[0] + '\n```\n```text\n', 1),
         'REPLY_BLOCK2_MISSING'),
        ('block 3 altered', good.replace('--sha256 ', '--sha256  ', 1), 'REPLY_BLOCK3_MISSING'),
        ('blocks out of order', _reply(pack, before=fence(b3)).replace('```text\n' + '\n'.join(b3) + '\n```\n- **預估',
                                                                    '- **預估', 1), 'REPLY_BLOCK_ORDER'),
        ('unclosed fence', good + '```text\nx\n', 'REPLY_FENCE_UNCLOSED'),
        ('fence closed by another opener', good + '```text\nx\n```text\n', 'REPLY_FENCE_UNCLOSED'),
        ('one combined time line', _reply(pack, times=['- Executor 與審查官合計 30 至 40 分鐘。依據：合計估算。']),
         'REPLY_TIME_EXECUTOR_MISSING'),
        ('auditor missing', _reply(pack, times=['  - Executor 30 至 40 分鐘。依據：實測。']), 'REPLY_TIME_AUDITOR_MISSING'),
        ('executor in words', _reply(pack, times=['- Executor 三十分鐘。依據：x', '- 審查官 1 至 2 分鐘。依據：y']),
         'REPLY_TIME_EXECUTOR_MISSING'),
        ('reversed range', _reply(pack, times=['- Executor 40 至 30 分鐘。依據：x', '- 審查官 1 至 2 分鐘。依據：y']),
         'REPLY_TIME_EXECUTOR_MISSING'),
        ('zero', _reply(pack, times=['- Executor 0 至 30 分鐘。依據：x', '- 審查官 1 至 2 分鐘。依據：y']),
         'REPLY_TIME_EXECUTOR_MISSING'),
        ('empty basis', _reply(pack, times=['- Executor 1 至 2 分鐘。依據：x', '- 審查官 1 至 2 分鐘。依據：  ']),
         'REPLY_TIME_AUDITOR_MISSING'),
        ('time only inside a fence', _reply(pack, times=['- Executor 1 至 2 分鐘。依據：x'],
                                             after=fence(['審查官 1 至 2 分鐘。依據：y'])), 'REPLY_TIME_AUDITOR_MISSING'),
        ('carriage return', good.replace('\n', '\r\n', 1), 'REPLY_CR'),
    ]


def test_verify_reply_fails_closed_on_every_hidden_altered_or_missing_part(pack):
    for name, text, code in _reply_cases(pack):
        assert _code(dp.verify_reply, str(pack), text) == code, name


def _tamper_delivery(pack, old, new):
    p = pack / 'DELIVERY.txt'
    text = p.read_bytes().decode('utf-8')
    assert text.count(old) >= 1
    p.write_bytes(text.replace(old, new, 1).encode('utf-8'))


@pytest.mark.parametrize('name', ['task', 'role', 'stamp', 'zip_hash', 'block1_overwrite', 'hashcmd', 'zip_bytes',
                                  'prompt_bytes', 'extra_file', 'shape'])
def test_verify_reply_rebuilds_the_pack_and_rejects_any_tampering(pack, name):
    reply = _reply(pack)                                       # the reply a Macro would send for the genuine pack
    zip_path = next(pack.glob('*.zip'))
    if name == 'task':
        _tamper_delivery(pack, 'PACK_TASK=' + TASK, 'PACK_TASK=OTHER-TASK-261024')
    elif name == 'role':
        _tamper_delivery(pack, 'PACK_ROLE=' + ROLE, 'PACK_ROLE=AUD-OTHER')
    elif name == 'stamp':
        _tamper_delivery(pack, 'PACK_STAMP=261024-1728', 'PACK_STAMP=261024-1729')
    elif name == 'zip_hash':
        text = (pack / 'DELIVERY.txt').read_bytes().decode('utf-8')
        sha = text.split('PACK_ZIP=')[1].split('sha256=')[1].split('\n')[0]
        _tamper_delivery(pack, 'sha256=' + sha, 'sha256=' + '0' * 64)
    elif name == 'block1_overwrite':
        _tamper_delivery(pack, '$e, $p, $false', '$e, $p, $true')
    elif name == 'hashcmd':
        _tamper_delivery(pack, 'Get-FileHash -Algorithm SHA256 -LiteralPath', 'Get-FileHash -Algorithm MD5 -LiteralPath')
    elif name == 'zip_bytes':
        zip_path.write_bytes(zip_path.read_bytes() + b'\0')
    elif name == 'prompt_bytes':
        p = pack / (TASK + '-prompt.txt')
        p.write_bytes(p.read_bytes() + b'\n')
    elif name == 'extra_file':
        (pack / 'notes.txt').write_bytes(b'x\n')
    else:
        _tamper_delivery(pack, '---HASHCMD---\n', '')
    expect = {'task': 'PROMPT_UNREADABLE',                    # no prompt of that task in the pack
              'role': 'PACK_FILE_SET_MISMATCH', 'stamp': 'PACK_FILE_SET_MISMATCH',   # rebuilt ZIP name differs
              'extra_file': 'PACK_FILE_SET_MISMATCH', 'shape': 'DELIVERY_SHAPE'}
    assert _code(dp.verify_reply, str(pack), reply) == expect.get(name, 'PACK_REBUILD_MISMATCH'), name


# ---- block 1 in a real PowerShell (Windows PowerShell 5.1 on Windows) ----------------------------------------

def _powershell():
    if os.name == 'nt':
        exe = shutil.which('powershell.exe')
        assert exe, 'Windows PowerShell must be present on Windows'          # never a skip on Windows
        return exe
    exe = os.environ.get('HHAI_TEST_POWERSHELL')
    if not exe:
        pytest.skip('block 1 runs in a real PowerShell only on Windows or with HHAI_TEST_POWERSHELL')
    return exe


def _run_block(exe, block):
    import base64
    encoded = base64.b64encode(block.encode('utf-16-le')).decode('ascii')       # no stdin echo, no script policy
    env = {k: v for k, v in os.environ.items() if k.upper() != 'PSMODULEPATH'}  # never a PowerShell 7 module path
    p = subprocess.run([exe, '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], stdin=subprocess.DEVNULL,
                       capture_output=True, timeout=120, env=env)
    lines = [l.strip() for l in p.stdout.decode('utf-8', 'replace').splitlines() if l.strip()]
    return p.returncode, lines


@pytest.mark.parametrize('case', ['ZIP_ONLY', 'TXT_ONLY', 'BOTH', 'NONE', 'BAD_TXT', 'TAMPERED_ZIP'])
def test_block1_in_powershell_never_overwrites_and_prints_one_verdict(tmp_path, prompt, case):
    exe = _powershell()
    pack = tmp_path / 'pack'
    _, zip_name, _, prompt_sha = _build(prompt, pack)
    dl = tmp_path / 'dl'
    dl.mkdir()
    name, data = TASK + '-prompt.txt', prompt.read_bytes()
    (dl / 'SHA256SUMS.txt').write_bytes(b'unrelated earlier file\n')
    if case in ('ZIP_ONLY', 'BOTH', 'BAD_TXT'):
        shutil.copy(pack / zip_name, dl / zip_name)
    if case in ('TXT_ONLY', 'BOTH'):
        shutil.copy(pack / name, dl / name)
    if case == 'BAD_TXT':
        (dl / name).write_bytes(b'stale bytes\n')
    if case == 'TAMPERED_ZIP':
        (dl / zip_name).write_bytes(dp.zip_bytes(name, b'tampered\n', '261024-1728'))
    block = dp.block1_text(str(dl), name, zip_name, prompt_sha)
    code, lines = _run_block(exe, block)
    expect = {'ZIP_ONLY': 'PROMPT_READY', 'TXT_ONLY': 'PROMPT_READY', 'BOTH': 'PROMPT_READY', 'NONE': 'PROMPT_MISSING',
              'BAD_TXT': 'MISMATCH ' + hashlib.sha256(b'stale bytes\n').hexdigest().upper(),
              'TAMPERED_ZIP': 'MISMATCH ' + hashlib.sha256(b'tampered\n').hexdigest().upper()}[case]
    assert code == 0 and lines == [expect], (code, lines)
    assert (dl / 'SHA256SUMS.txt').read_bytes() == b'unrelated earlier file\n'      # never extracted over
    if case in ('ZIP_ONLY', 'TXT_ONLY', 'BOTH'):
        assert (dl / name).read_bytes() == data
    if case == 'BAD_TXT':
        assert (dl / name).read_bytes() == b'stale bytes\n'                           # existing file kept as is
    if case == 'NONE':
        assert not (dl / name).exists()


@pytest.mark.parametrize('flag', ['$false', '$true'])
def test_block1_second_layer_never_overwrites_a_file_created_after_the_first_check(tmp_path, prompt, flag):
    """Deterministic injection between Test-Path and ExtractToFile: a wrapper creates the target inside Add-Type.
    The delivered template ($false) keeps the file and stops without a verdict; the $true mutant overwrites it."""
    exe = _powershell()
    pack = tmp_path / 'pack'
    _, zip_name, _, prompt_sha = _build(prompt, pack)
    dl = tmp_path / 'dl'
    dl.mkdir()
    shutil.copy(pack / zip_name, dl / zip_name)
    target = dl / (TASK + '-prompt.txt')
    prelude = ("function Add-Type { param([string]$AssemblyName) [IO.File]::WriteAllText("
               + pb.ps_literal(str(target)) + ", 'SENTINEL'); "
               "Microsoft.PowerShell.Utility\\Add-Type -AssemblyName $AssemblyName }; ")
    block = dp.block1_text(str(dl), target.name, zip_name, prompt_sha).replace('$e, $p, $false', '$e, $p, ' + flag)
    code, lines = _run_block(exe, prelude + block)
    if flag == '$false':
        assert target.read_bytes() == b'SENTINEL' and code != 0 and not any('PROMPT_READY' in l for l in lines)
    else:                                                  # proves the injection reaches the second layer
        assert target.read_bytes() == prompt.read_bytes() and code == 0 and lines == ['PROMPT_READY']


def test_block1_stops_on_an_unreadable_zip_without_a_verdict_or_a_file(tmp_path, prompt):
    exe = _powershell()
    pack = tmp_path / 'pack'
    _, zip_name, _, prompt_sha = _build(prompt, pack)
    dl = tmp_path / 'dl'
    dl.mkdir()
    (dl / zip_name).write_bytes(b'not a zip archive\n')
    code, lines = _run_block(exe, dp.block1_text(str(dl), TASK + '-prompt.txt', zip_name, prompt_sha))
    assert code != 0 and not any(l.startswith(('PROMPT_', 'MISMATCH')) for l in lines), (code, lines)
    assert sorted(p.name for p in dl.iterdir()) == [zip_name]
