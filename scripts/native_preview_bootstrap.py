#!/usr/bin/env python3
"""Build or execute the reviewed one-time Windows G5 activation bootstrap."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile
from types import SimpleNamespace

sys.dont_write_bytecode = True
import batch_runner as br
import batch_sim as sim
import native_preview as preview
from bounded_process import run_bounded

SAFE_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sim_python_info(area):
    """Python the simulation's own venv actually uses, read as text from its pyvenv.cfg (nothing is executed)."""
    cfg = Path(area) / 'sim' / 'work' / '.venv' / 'pyvenv.cfg'
    try:
        values = {}
        for line in cfg.read_text(encoding='utf-8').splitlines():
            key, sep, value = line.partition('=')
            if sep:
                values[key.strip().lower()] = value.strip()
        home, version = values['home'], values['version_info']
    except (OSError, UnicodeDecodeError, KeyError):
        raise preview.PreviewError('BOOTSTRAP_SIM_PYTHON_UNREADABLE') from None
    if not home or re.fullmatch(r'3\.\d+\.\d+', version) is None:
        raise preview.PreviewError('BOOTSTRAP_SIM_PYTHON_UNREADABLE')
    return home, version


def activation_inputs(repo, prompt):
    task, data, spec, _ = sim.read_prompt(prompt)
    spec = br.load_spec(br.prompt_lines(data), task)
    if (spec['kind'] != 'production' or spec.get('runner_update') is not True
            or spec['start']['mode'] != 'clean' or spec.get('native_preview')
            or br.base_supports_native_preview(str(repo), spec['base_oid'])
            or not {br.RUNNER_REL, 'scripts/native_preview.py', 'scripts/native_preview_bootstrap.py'}
            <= set(spec['authors'])):
        raise preview.PreviewError('BOOTSTRAP_INPUTS_INVALID')
    return data, spec


def script(repo, prompt, patch):
    data, spec = activation_inputs(repo, prompt)
    if not SAFE_NAME.fullmatch(prompt.name) or not SAFE_NAME.fullmatch(patch.name):
        raise preview.PreviewError('BOOTSTRAP_FILE_NAME_INVALID')
    return render_script(spec['base_oid'], prompt.name, digest(data), patch.name, digest(patch.read_bytes()))


def render_script(base_oid, prompt_name, prompt_sha, patch_name, patch_sha, uv_cache=None):
    uv_cache = preview.APPROVED_UV_CACHE_DIR if uv_cache is None else uv_cache
    if re.fullmatch(r'[A-Za-z]:\\[^\x00-\x1f"\'`$;&|<>%^]+', uv_cache) is None:
        raise preview.PreviewError('BOOTSTRAP_UV_CACHE_PATH_INVALID')
    return f"""param([Parameter(Mandatory=$true)][string]$W2,
      [Parameter(Mandatory=$true)][string]$InputDir)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) {{
    throw 'WINDOWS_POWERSHELL_51_REQUIRED'
}}
$base = '{base_oid}'
$prompt = Join-Path $InputDir '{prompt_name}'
$patch = Join-Path $InputDir '{patch_name}'
if ((Get-FileHash -LiteralPath $prompt -Algorithm SHA256).Hash.ToLowerInvariant() -cne '{prompt_sha}') {{
    throw 'BOOTSTRAP_PROMPT_SHA_MISMATCH'
}}
if ((Get-FileHash -LiteralPath $patch -Algorithm SHA256).Hash.ToLowerInvariant() -cne '{patch_sha}') {{
    throw 'BOOTSTRAP_PATCH_SHA_MISMATCH'
}}
$source = (Resolve-Path -LiteralPath $W2).ProviderPath
$uvCache = '{uv_cache}'
if (!(Test-Path -LiteralPath $uvCache -PathType Container)) {{ throw 'BOOTSTRAP_UV_CACHE_MISSING' }}
$python = Join-Path $source '.venv\\Scripts\\python.exe'
if (!(Test-Path -LiteralPath $python -PathType Leaf)) {{ throw 'BOOTSTRAP_PYTHON_MISSING' }}
$physicalTemp = & $python -I -B -S -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' $env:TEMP
if ($LASTEXITCODE -ne 0) {{ throw 'BOOTSTRAP_TEMP_UNREADABLE' }}
$source = & $python -I -B -S -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' $source
if ($LASTEXITCODE -ne 0) {{ throw 'BOOTSTRAP_W2_UNREADABLE' }}
$tempRoot = [System.IO.Path]::GetFullPath($physicalTemp).TrimEnd('\\')
if (($tempRoot + '\\').StartsWith($source.TrimEnd('\\') + '\\', [StringComparison]::OrdinalIgnoreCase)) {{
    throw 'BOOTSTRAP_TEMP_OVERLAPS_W2'
}}
foreach ($name in @('GIT_DIR','GIT_WORK_TREE','GIT_COMMON_DIR','GIT_INDEX_FILE','GIT_OBJECT_DIRECTORY',
        'GIT_ALTERNATE_OBJECT_DIRECTORIES','GIT_NAMESPACE','GIT_CONFIG','GIT_CONFIG_COUNT',
        'GIT_CONFIG_PARAMETERS','GIT_CONFIG_SYSTEM','GIT_CONFIG_GLOBAL','GIT_TEMPLATE_DIR')) {{
    if ([Environment]::GetEnvironmentVariable($name, 'Process')) {{ throw 'BOOTSTRAP_GIT_ENV_OVERRIDE' }}
}}
$area = Join-Path $tempRoot ('hhai-g5-' + [Guid]::NewGuid().ToString('N').Substring(0,12))
$null = New-Item -Path $area -ItemType Directory
Write-Output ('BOOTSTRAP_EVIDENCE_DIR=' + $area)
$author = Join-Path $area 'author'
$git = (Get-Command git.exe -CommandType Application | Select-Object -First 1).Source
$emptyConfig = Join-Path $area 'empty.gitconfig'
[System.IO.File]::WriteAllBytes($emptyConfig, [byte[]]@())
$oldNoSystem = $env:GIT_CONFIG_NOSYSTEM
$oldTerminalPrompt = $env:GIT_TERMINAL_PROMPT
try {{
    $env:GIT_CONFIG_NOSYSTEM = '1'
    $env:GIT_CONFIG_GLOBAL = $emptyConfig
    $env:GIT_TERMINAL_PROMPT = '0'
    & $git -c core.autocrlf=false -c credential.helper= clone --no-checkout --template= -- https://github.com/hhai0519/HH.AI_v2.git $author
    if ($LASTEXITCODE -ne 0) {{ throw 'BOOTSTRAP_CLONE_FAILED' }}
    $remote = & $git -C $author rev-parse --verify refs/remotes/origin/main
    if ($LASTEXITCODE -ne 0) {{ throw 'BOOTSTRAP_MAIN_UNREADABLE' }}
    if ($remote.ToLowerInvariant() -cne $base) {{ throw 'BOOTSTRAP_REMOTE_MAIN_DRIFT' }}
    & $git -C $author -c core.autocrlf=false switch --detach $base
    if ($LASTEXITCODE -ne 0) {{ throw 'BOOTSTRAP_BASE_CHECKOUT_FAILED' }}
    & $git -C $author apply --check -- $patch
    if ($LASTEXITCODE -ne 0) {{ throw 'BOOTSTRAP_PATCH_CHECK_FAILED' }}
    & $git -C $author apply -- $patch
    if ($LASTEXITCODE -ne 0) {{ throw 'BOOTSTRAP_PATCH_APPLY_FAILED' }}
}} finally {{
    $env:GIT_CONFIG_NOSYSTEM = $oldNoSystem
    $env:GIT_CONFIG_GLOBAL = $null
    $env:GIT_TERMINAL_PROMPT = $oldTerminalPrompt
}}
$tool = Join-Path $author 'scripts\\native_preview_bootstrap.py'
& $python -E -B $tool run --source $source --prompt $prompt --patch $patch --workdir $area --prompt-sha256 '{prompt_sha}' --patch-sha256 '{patch_sha}'
if ($LASTEXITCODE -ne 0) {{ throw 'BOOTSTRAP_NATIVE_FAILED' }}
"""


def run(args):
    if os.name != 'nt':
        raise preview.PreviewError('BOOTSTRAP_WINDOWS_REQUIRED')
    work = Path(args.workdir).resolve()
    repo = Path(__file__).resolve().parents[1]
    if repo != work / 'author':
        raise preview.PreviewError('BOOTSTRAP_AUTHOR_CLONE_INVALID')
    data, spec = activation_inputs(repo, args.prompt)
    if digest(data) != args.prompt_sha256 or digest(args.patch.read_bytes()) != args.patch_sha256:
        raise preview.PreviewError('BOOTSTRAP_PROMPT_BINDING_INVALID')
    if br.git(str(repo), 'rev-parse', 'HEAD') != spec['base_oid']:
        raise preview.PreviewError('BOOTSTRAP_AUTHOR_BASE_DRIFT')
    if set(br.changed_paths(str(repo), spec['base_oid'])) != set(spec['authors']):
        raise preview.PreviewError('BOOTSTRAP_AUTHOR_SCOPE_DRIFT')
    for name, entry in spec['authors'].items():
        if digest((repo / name).read_bytes()) != entry['sha256']:
            raise preview.PreviewError('BOOTSTRAP_AUTHOR_BYTES_DRIFT')

    native = sim.Sim(args.source, work / 'sim', git_profile='windows', verify_source_bytes=True)
    if native.git('--no-optional-locks', '-C', native.source, 'rev-parse', 'HEAD',
                  cwd=str(work), code='BOOTSTRAP_W2_UNREADABLE') != spec['base_oid']:
        raise preview.PreviewError('BOOTSTRAP_W2_BASE_DRIFT')
    before = native.source_refs()
    try:
        # Exercise the same native implementation that future runner steps call.
        # The activation receipt is confined to this bootstrap's TEMP directory.
        def write_receipt(name, text):
            if name != 'native-preview.json':
                raise preview.PreviewError('BOOTSTRAP_RECEIPT_NAME_INVALID')
            with (work / name).open('xb') as handle:
                handle.write(text.encode('utf-8'))

        activation = SimpleNamespace(root=str(args.source.resolve()), task_id=spec['task_id'], spec=spec,
                                     prompt_bytes=data, write_new_artifact=write_receipt)
        try:
            preview.run(activation)
        except preview.PreviewError:
            if hasattr(activation, 'native_preview_evidence_dir'):
                print('BOOTSTRAP_NATIVE_EVIDENCE_DIR=' + activation.native_preview_evidence_dir)
            raise
        native_receipt = json.loads((work / 'native-preview.json').read_bytes(),
                                    object_pairs_hook=br.reject_duplicate_json_keys)
        native_area = Path(tempfile.gettempdir()).resolve() / native_receipt['temp_name']
        log = native_area / 'batch-sim.log'
        output = log.read_bytes()
        if digest(output) != native_receipt['log_sha256']:
            raise preview.PreviewError('BOOTSTRAP_LOG_HASH_MISMATCH')
        preview.checked_simulation_output(output, 0, spec)
        with (work / 'batch-sim.log').open('xb') as handle:
            handle.write(output)
        sim_home, sim_version = sim_python_info(native_area)
        print('BOOTSTRAP_SIM_PYTHON home=' + sim_home + ' version_info=' + sim_version)
        shutil.copyfile(native_area / 'sim' / 'work' / '.venv' / 'pyvenv.cfg', work / 'sim-pyvenv.cfg')

        tests_log = work / 'native-tests.log'
        tests_env = dict(native.env)
        tests_env.pop('PYTEST_ADDOPTS', None)
        tests_env.pop('PYTEST_PLUGINS', None)
        tests_env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
        tests = run_bounded([sys.executable, '-B', '-m', 'pytest', '-q', '-rs', '-o', 'addopts=',
                             '-p', 'no:cacheprovider', 'scripts/tests/test_native_preview.py'],
                            str(repo), 1200, env=tests_env,
                            merge_stderr=True, capture_path=str(tests_log))
        totals = [line for line in tests.stdout.decode('utf-8', 'replace').splitlines()
                  if re.fullmatch(r'[1-9][0-9]* passed in [0-9.]+s(?: \([0-9:]+\))?', line)]
        if (tests.launch_error or tests.timed_out or tests.returncode != 0 or len(totals) != 1
                or not tests_log.is_file() or tests_log.read_bytes() != tests.stdout):
            raise preview.PreviewError('BOOTSTRAP_TESTS_FAILED')
    finally:
        after = native.source_refs()
        if before != after:
            raise preview.PreviewError('NATIVE_PREVIEW_SOURCE_MODIFIED')

    receipt = {
        'source_dir': str(args.source.resolve()),
        'base_oid': spec['base_oid'], 'prompt_sha256': digest(data), 'patch_sha256': args.patch_sha256,
        'author_sha256': {name: entry['sha256'] for name, entry in spec['authors'].items()},
        'batch_sim_log_sha256': digest(output), 'batch_sim_exit': 0,
        'native_preview_receipt_sha256': digest((work / 'native-preview.json').read_bytes()),
        'native_preview_evidence_dir': str(native_area),
        'sim_python_home': sim_home, 'sim_python_version_info': sim_version,
        'native_tests_log_sha256': digest(tests.stdout), 'native_tests_exit': tests.returncode,
        'native_tests_summary': totals[0], 'task_id': spec['task_id'],
        'source_before_sha256': digest(repr(before).encode('utf-8')),
        'source_after_sha256': digest(repr(after).encode('utf-8')),
    }
    content = (json.dumps(receipt, sort_keys=True, ensure_ascii=True) + '\n').encode('ascii')
    with (work / 'bootstrap-receipt.json').open('xb') as handle:
        handle.write(content)
    evidence = work / 'bootstrap-evidence.zip'
    with zipfile.ZipFile(evidence, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ('bootstrap-receipt.json', 'native-preview.json', 'batch-sim.log', 'native-tests.log',
                     'sim-pyvenv.cfg'):
            archive.write(work / name, name)
    print('ONE_TIME_BOOTSTRAP_PASS RECEIPT_SHA256=' + digest(content))
    print('BOOTSTRAP_EVIDENCE_FILE=' + str(evidence))
    print('BOOTSTRAP_EVIDENCE_SHA256=' + digest(evidence.read_bytes()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    build = sub.add_parser('script')
    for name in ('repo', 'prompt', 'patch', 'out'):
        build.add_argument('--' + name, type=Path, required=True)
    execute = sub.add_parser('run')
    for name in ('source', 'prompt', 'patch', 'workdir'):
        execute.add_argument('--' + name, type=Path, required=True)
    for name in ('prompt-sha256', 'patch-sha256'):
        execute.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        if args.mode == 'script':
            content = script(args.repo, args.prompt, args.patch).encode('ascii')
            with args.out.open('xb') as handle:
                handle.write(content)
            print('BOOTSTRAP_SCRIPT_SHA256=' + digest(content))
        else:
            run(args)
    except (br.Halt, sim.SimError, preview.PreviewError) as exc:
        print('BOOTSTRAP_FAIL ' + str(exc))
        return 1
    except (OSError, ValueError, KeyError, TypeError):
        print('BOOTSTRAP_FAIL INPUT_OR_IO_ERROR')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
