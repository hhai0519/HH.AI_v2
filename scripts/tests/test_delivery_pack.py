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


# ---- pre-execution sequence of a native_preview production (PRESTART.txt) ------------------------------------

REAL_WS = 'C:\\Users\\HH.AI_260806\\Desktop\\HH.AI_v2_W2'
REAL_BASE = '87734aba2619244032c65199686e9dbfe5fe2004'
# The four blocks exactly as delivered and run before this tool generated them; only Base and workspace vary.
PROVEN = {
    'A': "& { $ErrorActionPreference='Stop'; if (-not ($PSVersionTable.PSVersion.Major -eq 5 -and $PSVersionTable.PSVersion.Minor -eq 1)) { throw 'POWERSHELL_51_REQUIRED' }; $p=@(Get-Process | Where-Object { $_.ProcessName -like '*Antigravity*' }); if ($p.Count -ne 0) { $p | ForEach-Object { 'STILL_RUNNING ' + $_.ProcessName + ' ' + $_.Id }; throw 'ANTIGRAVITY_NOT_CLOSED' }; 'ANTIGRAVITY_CLOSED' }",
    'B': "& { $ErrorActionPreference='Stop'; if (-not ($PSVersionTable.PSVersion.Major -eq 5 -and $PSVersionTable.PSVersion.Minor -eq 1)) { throw 'POWERSHELL_51_REQUIRED' }; $ws='C:\\Users\\HH.AI_260806\\Desktop\\HH.AI_v2_W2'; $base='87734aba2619244032c65199686e9dbfe5fe2004'; $h=@(git -C $ws --no-optional-locks rev-parse HEAD); if ($LASTEXITCODE -ne 0) { throw 'W2_REVPARSE_FAILED' }; if ($h[0].Trim() -ne $base) { 'W2_HEAD=' + $h[0]; throw 'W2_HEAD_MISMATCH' }; $s=@(git -C $ws --no-optional-locks status --porcelain --untracked-files=all); if ($LASTEXITCODE -ne 0) { throw 'W2_STATUS_FAILED' }; if ($s.Count -ne 0) { $s | Select-Object -First 20; throw 'W2_NOT_CLEAN' }; 'W2_READY_AT_BASE' }",
    'B-R': "& { $ErrorActionPreference='Stop'; if (-not ($PSVersionTable.PSVersion.Major -eq 5 -and $PSVersionTable.PSVersion.Minor -eq 1)) { throw 'POWERSHELL_51_REQUIRED' }; $ws='C:\\Users\\HH.AI_260806\\Desktop\\HH.AI_v2_W2'; $base='87734aba2619244032c65199686e9dbfe5fe2004'; git -C $ws --no-optional-locks cat-file -e ($base + '^{commit}'); if ($LASTEXITCODE -ne 0) { throw 'BASE_NOT_IN_W2' }; $s=@(git -C $ws --no-optional-locks status --porcelain --untracked-files=all); if ($LASTEXITCODE -ne 0) { throw 'W2_STATUS_FAILED' }; if ($s.Count -ne 0) { $s | Select-Object -First 20; throw 'W2_NOT_CLEAN' }; git -C $ws switch --detach $base; if ($LASTEXITCODE -ne 0) { throw 'W2_SWITCH_FAILED' }; 'W2_SWITCHED_TO_BASE_RERUN_B' }",
    'C': "& { $ErrorActionPreference='Stop'; if (-not ($PSVersionTable.PSVersion.Major -eq 5 -and $PSVersionTable.PSVersion.Minor -eq 1)) { throw 'POWERSHELL_51_REQUIRED' }; $ws='C:\\Users\\HH.AI_260806\\Desktop\\HH.AI_v2_W2'; $py=Join-Path $ws '.venv\\Scripts\\python.exe'; if (-not (Test-Path -LiteralPath $py -PathType Leaf)) { throw 'W2_PYTHON_MISSING' }; $code='import os,sys,time;from pathlib import Path;sys.path.insert(0,os.path.join(sys.argv[1],''scripts''));import batch_sim as b;r=Path(sys.argv[1]);snap=lambda:tuple((p.relative_to(r).as_posix(),)+(lambda s:(s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns))(os.lstat(p)) for p in b._source_paths(r));a=snap();time.sleep(int(sys.argv[2]));c=snap();print(''GIT_IDLE_OK'' if a==c else ''GIT_IDLE_CHANGED'');sys.exit(0 if a==c else 3)'; & $py -B -c $code $ws 210; if ($LASTEXITCODE -ne 0) { throw 'GIT_IDLE_CHECK_FAILED' } }",
}
OTHER_BASE = '0123456789abcdef0123456789abcdef01234567'


def _native(monkeypatch, native=True, kind='production', base=OTHER_BASE):
    real = dp.prompt_builder.batch_runner.load_spec

    def fake(lines, task):
        spec = dict(real(lines, task))
        spec.update({'kind': kind, 'native_preview': native, 'base_oid': base})
        return spec
    monkeypatch.setattr(dp.prompt_builder.batch_runner, 'load_spec', fake)


@pytest.fixture
def native_pack(tmp_path, prompt, monkeypatch):
    out = tmp_path / 'native'
    _native(monkeypatch)
    _build(prompt, out)
    return out


def _pre(pack):
    return (pack / 'PRESTART.txt').read_bytes().decode('utf-8')[:-1].split('\n')


def test_prestart_blocks_equal_the_proven_text_byte_for_byte():
    assert dp.prestart_blocks(REAL_BASE, REAL_WS) == PROVEN


def test_prestart_base_and_workspace_are_the_only_variable_parts():
    other = dp.prestart_blocks(OTHER_BASE, 'C:\\Users\\U\\Desktop\\W')
    for name, text in PROVEN.items():
        expect = text.replace(REAL_BASE, OTHER_BASE).replace(REAL_WS, 'C:\\Users\\U\\Desktop\\W')
        assert other[name] == expect, name
    assert REAL_BASE not in dp.prestart_blocks(OTHER_BASE, REAL_WS)['A'] + dp.prestart_blocks(OTHER_BASE, REAL_WS)['C']
    assert dp.prestart_blocks(OTHER_BASE, REAL_WS)['B'].count(OTHER_BASE) == 1
    assert dp.prestart_blocks(OTHER_BASE, REAL_WS)['B-R'].count(OTHER_BASE) == 1


@pytest.mark.parametrize('base', ['', 'abc', REAL_BASE.upper(), REAL_BASE[:39], REAL_BASE + '0', REAL_BASE[:39] + "'",
                                  REAL_BASE[:39] + 'g', None])
def test_prestart_rejects_a_base_that_is_not_a_full_lowercase_oid(base):
    assert _code(dp.prestart_blocks, base, REAL_WS) == 'BASE_INVALID'


@pytest.mark.parametrize('ws', ['Users\\U', "C:\\Users\\U'x", 'C:\\Users\\U V', 'C:/Users/U', 'C:\\Users\\$x'])
def test_prestart_rejects_a_workspace_that_is_not_one_literal_token(ws):
    assert _code(dp.prestart_blocks, REAL_BASE, ws) == 'WORKSPACE_INVALID'


def test_prestart_lines_hold_the_whole_sequence_in_order():
    text = '\n'.join(dp.prestart_lines(REAL_BASE, REAL_WS))
    order = [PROVEN['A'], PROVEN['B'], 'W2_HEAD_MISMATCH', PROVEN['B-R'], 'Antigravity IDE.exe', 'git.autorefresh',
             'git.autofetch', PROVEN['C'], '不要動分支選擇器', 'STEP_PASS']
    at = [text.index(x) for x in order]
    assert at == sorted(at) and len(set(at)) == len(at)
    assert text.count('```powershell') == 4 and text.count('\n```\n') == 4
    assert 'C:\\Users\\HH.AI_260806\\AppData\\Local\\Programs\\Antigravity IDE\\Antigravity IDE.exe' in text
    assert '本批 Base：`' + REAL_BASE + '`' in text


def test_a_production_without_native_preview_gets_no_prestart_file(tmp_path, prompt, monkeypatch):
    out = tmp_path / 'plain-native-false'
    _native(monkeypatch, native=False)
    _build(prompt, out)
    assert sorted(p.name for p in out.iterdir()) == sorted([TASK + '-prompt.txt', 'DELIVERY.txt',
                                                             next(out.glob('*.zip')).name])


@pytest.mark.parametrize('spec,expect', [
    ({'kind': 'production', 'native_preview': True, 'base_oid': OTHER_BASE}, (True, OTHER_BASE)),
    ({'kind': 'production', 'native_preview': False, 'base_oid': OTHER_BASE}, (False, OTHER_BASE)),
    ({'kind': 'production', 'base_oid': OTHER_BASE}, (False, OTHER_BASE)),
    ({'kind': 'production', 'native_preview': 1, 'base_oid': OTHER_BASE}, (False, OTHER_BASE)),
    ({'kind': 'promotion', 'native_preview': True, 'base_oid': OTHER_BASE}, (False, OTHER_BASE)),
    ({'kind': 'readonly', 'native_preview': True}, (False, None)),
])
def test_the_sequence_applies_only_to_a_production_declaring_native_preview_true(prompt, monkeypatch, spec, expect):
    monkeypatch.setattr(dp.prompt_builder.batch_runner, 'load_spec', lambda lines, task: dict(spec))
    assert dp.prestart_spec(str(prompt)) == expect


def test_an_unreadable_spec_fails_the_build_closed(tmp_path, prompt, monkeypatch):
    def boom(lines, task):
        raise dp.prompt_builder.batch_runner.Halt('SPEC_X')
    monkeypatch.setattr(dp.prompt_builder.batch_runner, 'load_spec', boom)
    assert _code(dp.prestart_spec, str(prompt)) == 'PRESTART_SPEC_SPEC_X'


def test_a_native_preview_production_gets_a_fourth_file_bound_to_the_prompt_base_and_workspace(native_pack):
    names = sorted(p.name for p in native_pack.iterdir())
    assert names == sorted([TASK + '-prompt.txt', 'DELIVERY.txt', 'PRESTART.txt', next(native_pack.glob('*.zip')).name])
    assert _pre(native_pack) == dp.prestart_lines(OTHER_BASE, WS)
    assert dp.rebuild_pack(str(native_pack))                              # the extra file is part of the rebuild


def test_build_prints_the_prestart_hash_only_when_the_file_exists(tmp_path, prompt, monkeypatch, capsys):
    _native(monkeypatch)
    assert dp.main(['build', '--prompt', str(prompt), '--role-code', ROLE, '--download-dir', DL, '--workspace', WS,
                    '--out-dir', str(tmp_path / 'cli1')]) == 0
    out = capsys.readouterr().out
    pre = (tmp_path / 'cli1' / 'PRESTART.txt').read_bytes()
    assert 'PACK_PRESTART=PRESTART.txt sha256=' + hashlib.sha256(pre).hexdigest().upper() in out
    _native(monkeypatch, native=False)
    assert dp.main(['build', '--prompt', str(prompt), '--role-code', ROLE, '--download-dir', DL, '--workspace', WS,
                    '--out-dir', str(tmp_path / 'cli2')]) == 0
    assert 'PACK_PRESTART' not in capsys.readouterr().out


def _native_reply(pack, mutate=None, **kw):
    b1, b2, b3 = _blocks(pack)
    pre = _pre(pack)
    times = ['  - Executor 30 至 40 分鐘。依據：同類批實測。', '  - 審查官 25 至 45 分鐘。依據：候選 diff 與 raw log 審查。']
    parts = {'b1': ['**區塊一**', '```powershell'] + b1 + ['```'], 'b2': ['**區塊二**', '```text'] + b2 + ['```'],
             'pre': list(pre), 'b3': ['**區塊三**', '```text'] + b3 + ['```'], 'time': ['- **預估時間**：'] + times}
    order = kw.get('order', ['b1', 'b2', 'pre', 'b3', 'time'])
    if mutate:
        mutate(parts)
    lines = ['## 交付']
    for k in order:
        lines += parts[k]
    return '\n'.join(lines + [kw.get('after', '')]) + '\n'


def test_verify_reply_accepts_the_prestart_between_block1_and_block3_with_block2_on_either_side(native_pack):
    assert dp.verify_reply(str(native_pack), _native_reply(native_pack)) is True
    assert dp.verify_reply(str(native_pack), _native_reply(native_pack, order=['b1', 'pre', 'b2', 'b3', 'time'])) is True


def _drop(parts):
    del parts['pre'][3:6]


def _alter_block(parts):
    i = next(i for i, l in enumerate(parts['pre']) if "W2_READY_AT_BASE'" in l)
    parts['pre'][i] = parts['pre'][i].replace("W2_READY_AT_BASE'", "W2_READY_AT_BASE.'")


def _alter_prose(parts):
    parts['pre'] = [l.replace('不要動分支選擇器', '可以動分支選擇器') for l in parts['pre']]


def _split(parts):
    parts['pre'] = parts['pre'][:10] + ['補充一行'] + parts['pre'][10:]


def test_verify_reply_fails_closed_on_a_missing_altered_split_duplicated_or_misplaced_prestart(native_pack):
    run = lambda text: _code(dp.verify_reply, str(native_pack), text)
    assert run(_native_reply(native_pack, lambda p: p.update(pre=[]))) == 'REPLY_PRESTART_MISSING'
    assert run(_native_reply(native_pack, _drop)) == 'REPLY_PRESTART_MISSING'
    assert run(_native_reply(native_pack, _alter_block)) == 'REPLY_PRESTART_MISSING'
    assert run(_native_reply(native_pack, _alter_prose)) == 'REPLY_PRESTART_MISSING'
    assert run(_native_reply(native_pack, _split)) == 'REPLY_PRESTART_MISSING'
    assert run(_native_reply(native_pack, after='\n'.join(_pre(native_pack)))) == 'REPLY_PRESTART_DUPLICATED'
    assert run(_native_reply(native_pack, order=['pre', 'b1', 'b2', 'b3', 'time'])) == 'REPLY_PRESTART_ORDER'
    assert run(_native_reply(native_pack, order=['b1', 'b2', 'b3', 'pre', 'time'])) == 'REPLY_PRESTART_ORDER'


def test_verify_reply_rejects_a_copy_of_a_prestart_block_in_another_fence(native_pack):
    block_b = next(l for l in _pre(native_pack) if "W2_READY_AT_BASE'" in l)
    text = _native_reply(native_pack, after='```text\n' + block_b + '\n```')
    assert _code(dp.verify_reply, str(native_pack), text) == 'REPLY_BLOCK_DUPLICATED'
    text = _native_reply(native_pack, after='```text\n' + block_b + '\nRemove-Item x\n```')
    assert _code(dp.verify_reply, str(native_pack), text) == 'REPLY_BLOCK_DUPLICATED'


@pytest.mark.parametrize('marker', ["'ANTIGRAVITY_CLOSED'", "'W2_READY_AT_BASE'", "'W2_SWITCHED_TO_BASE_RERUN_B'",
                                    "'GIT_IDLE_CHECK_FAILED'"])
def test_verify_reply_rejects_a_copy_of_any_prestart_block_in_another_fence(native_pack, marker):
    block = next(l for l in _pre(native_pack) if l.startswith('& {') and marker in l)
    text = _native_reply(native_pack, after='```text\n' + block + '\n```')
    assert _code(dp.verify_reply, str(native_pack), text) == 'REPLY_BLOCK_DUPLICATED'


def test_block_c_idle_code_runs_against_this_repos_batch_sim_on_a_stable_tree(tmp_path):
    # Block C imports batch_sim from the workspace and walks its tree; run the exact code in a copy of the scripts
    # (never the live repo root, whose files other tests may touch) so a renamed _source_paths fails here.
    scripts = Path(__file__).resolve().parents[1]
    (tmp_path / 'scripts').mkdir()
    for f in scripts.glob('*.py'):
        shutil.copy2(f, tmp_path / 'scripts' / f.name)
    r = subprocess.run([sys.executable, '-B', '-c', dp.IDLE_CODE, str(tmp_path), '0'], capture_output=True,
                       text=True, encoding='utf-8', cwd=str(tmp_path))
    assert (r.returncode, r.stdout) == (0, 'GIT_IDLE_OK\n')

def test_a_pack_without_prestart_still_verifies_exactly_as_before(pack):
    assert not (pack / 'PRESTART.txt').exists()
    assert dp.verify_reply(str(pack), _reply(pack)) is True


@pytest.mark.parametrize('name', ['missing', 'altered_base', 'altered_text', 'extra_bytes', 'planted_on_plain_pack'])
def test_verify_reply_rejects_a_prestart_file_that_is_not_the_rebuild(tmp_path, prompt, monkeypatch, name):
    if name == 'planted_on_plain_pack':
        out = tmp_path / 'plain'
        _build(prompt, out)
        (out / 'PRESTART.txt').write_bytes(b'x\n')
        assert _code(dp.verify_reply, str(out), _reply(out)) == 'PACK_FILE_SET_MISMATCH'
        return
    out = tmp_path / 'native2'
    _native(monkeypatch)
    _build(prompt, out)
    reply = _native_reply(out)
    p = out / 'PRESTART.txt'
    if name == 'missing':
        p.unlink()
    elif name == 'altered_base':
        p.write_bytes(p.read_bytes().replace(OTHER_BASE.encode(), REAL_BASE.encode()))
    elif name == 'altered_text':
        p.write_bytes(p.read_bytes().replace('一律停止'.encode(), '可以繼續'.encode()))
    else:
        p.write_bytes(p.read_bytes() + b'\n')
    want = 'PACK_FILE_SET_MISMATCH' if name == 'missing' else 'PACK_REBUILD_MISMATCH'
    assert _code(dp.verify_reply, str(out), reply) == want


def test_verify_reply_cli_checks_the_prestart_without_printing_content(tmp_path, native_pack, capsys):
    r = tmp_path / 'R.txt'
    r.write_bytes(_native_reply(native_pack).encode('utf-8'))
    assert dp.main(['verify-reply', '--pack-dir', str(native_pack), '--reply', str(r)]) == 0
    assert capsys.readouterr().out.strip() == 'DELIVERY_REPLY PASS'
    r.write_bytes(_native_reply(native_pack, lambda p: p.update(pre=[])).encode('utf-8'))
    assert dp.main(['verify-reply', '--pack-dir', str(native_pack), '--reply', str(r)]) == 1
    assert capsys.readouterr().out.strip() == 'DELIVERY_PACK FAIL REPLY_PRESTART_MISSING'


def test_prestart_text_is_pinned_line_by_line():
    fence = lambda text: ['```powershell', text, '```']
    expect = (['**執行前固定順序**：以下步驟依序執行，每個區塊只執行一次；任一區塊不是預期輸出就停止並回報。',
               '本批 Base：`' + REAL_BASE + '`（區塊 B 與 B-R 已代入）。',
               '### 關閉 Antigravity IDE，再執行區塊 A（預期輸出 `ANTIGRAVITY_CLOSED`）'] + fence(PROVEN['A'])
              + ['### 區塊 B（預期輸出 `W2_READY_AT_BASE`）'] + fence(PROVEN['B'])
              + ['只有輸出 `W2_HEAD_MISMATCH`（並顯示 `W2_HEAD=…`）時，才執行下面的區塊 B-R（預期輸出 '
                 '`W2_SWITCHED_TO_BASE_RERUN_B`），然後重跑區塊 B。其他錯誤（`W2_NOT_CLEAN`、`W2_STATUS_FAILED` 等）'
                 '一律停止並回報，不要用 B-R。'] + fence(PROVEN['B-R'])
              + ['### 開啟 IDE 並等待',
                 '1. 只以 `C:\\Users\\HH.AI_260806\\AppData\\Local\\Programs\\Antigravity IDE\\Antigravity IDE.exe` 開啟 '
                 'Antigravity IDE，開啟 `' + REAL_WS + '` 工作區。',
                 '2. 確認使用者層級（不是工作區層級）的 Git 自動刷新（`git.autorefresh`）與自動 fetch（`git.autofetch`）仍為關閉。',
                 '3. 等約 1 分鐘，再執行區塊 C。',
                 '### 區塊 C（預期輸出 `GIT_IDLE_OK`，約 210 秒）'] + fence(PROVEN['C'])
              + ['輸出 `GIT_IDLE_CHANGED` 或 `GIT_IDLE_CHECK_FAILED` 就停止並回報，不要啟動 Executor。',
                 '### 新的 Agent 對話',
                 '- 開新對話；**不要動分支選擇器**（runner 只檢查 HEAD＝Base 與工作區乾淨，不檢查分支）。',
                 '- 貼上區塊三的文字，一字不改。之後每個 runner 步驟必須等到 IDE 顯示該命令已結束且 exit 0、'
                 '輸出含 `STEP_PASS <步驟名>` 才算完成，期間不得呼叫下一步。'])
    assert dp.prestart_lines(REAL_BASE, REAL_WS) == expect
