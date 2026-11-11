"""G5 source and rehearsal controls, using real Git and synthetic runner results."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import batch_runner as br
import batch_sim as sim
import native_preview as preview


def git(repo, *args):
    cmd = ['git', '--no-optional-locks', '-C', str(repo), *args]
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    result = subprocess.run(cmd, capture_output=True, check=True, env=env, timeout=60)
    return result.stdout.decode('utf-8').strip()


@pytest.fixture
def source(tmp_path):
    repo = tmp_path / 'w2'
    repo.mkdir()
    git(repo, 'init', '-q', '--template=', '-b', 'main')
    git(repo, 'config', 'user.name', 'Fixture')
    git(repo, 'config', 'user.email', 'fixture@example.invalid')
    git(repo, 'config', 'core.autocrlf', 'false')
    (repo / '.gitignore').write_bytes(b'__pycache__/\n')
    (repo / 'module.py').write_bytes(b'VALUE = 1\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'fixture')
    return repo


@pytest.mark.parametrize('paths,expected', [
    (['docs/TASKBOARD.md'], False),
    (['README.md'], False),
    (['scripts/build.py'], True),
    (['Scripts/build.py'], True),
    (['docs/taskboard.md'], True),
    (['docs/fingerprints/spoof.json'], True),
    (['docs/governance/Execution-record.json'], True),
    (['scripts/exec-latest.json'], True),
    (['docs/archive/docs/governance/execution-record.json'], True),
])
def test_plan_trigger_is_exact_and_independent_of_e24_and_focused(paths, expected):
    assert br.native_preview_required(paths + list(br.GENERATED)) is expected
    spec = {'kind': 'production', 'e24': False, 'focused': None, 'native_preview': expected}
    assert br.derive_steps(spec)[:2] == ['preflight', 'native_preview' if expected else 'setup']
    if expected:
        assert br.derive_steps(spec)[2] == 'setup'


def test_base_runner_support_is_a_committed_feature():
    assert br.runner_declares_native_preview(b"PRODUCTION_STEPS = ('preflight', 'setup')\n") is False
    assert br.runner_declares_native_preview(
        b"PRODUCTION_STEPS = ('preflight', 'native_preview', 'setup')\n"
    ) is True
    with pytest.raises(br.Halt, match='NATIVE_PREVIEW_BASE_STEPS_INVALID'):
        br.runner_declares_native_preview(b"PRODUCTION_STEPS = get_steps()\n")


def test_comparator_does_not_refresh_stale_index_and_sees_ignored_output(tmp_path, source):
    index = source / '.git/index'
    before = index.read_bytes()
    # A same-content rewrite invalidates the cached stat data without changing its contents.
    module = source / 'module.py'
    st = module.stat()
    os.utime(module, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    rehearsal = sim.Sim(source, tmp_path / 'sim', verify_source_bytes=True)
    snapshot = rehearsal.source_refs()
    assert index.read_bytes() == before
    assert rehearsal.source_refs() == snapshot
    assert index.read_bytes() == before
    (source / '__pycache__').mkdir()
    (source / '__pycache__/unexpected.pyc').write_bytes(b'ignored fixture')
    assert rehearsal.source_refs() != snapshot


def test_comparator_includes_actual_index_bytes(tmp_path, source):
    rehearsal = sim.Sim(source, tmp_path / 'sim', verify_source_bytes=True)
    snapshot = rehearsal.source_refs()
    git(source, 'update-index', '--assume-unchanged', 'module.py')
    assert dict(rehearsal.source_refs()[1])['.git/index'] != dict(snapshot[1])['.git/index']


def test_missing_base_stops_without_source_mutation(tmp_path, source):
    rehearsal = sim.Sim(source, tmp_path / 'sim', verify_source_bytes=True)
    snapshot = rehearsal.source_refs()
    with pytest.raises(sim.SimError, match='^BASE_NOT_IN_SOURCE$'):
        rehearsal.make_origin('9' * 40)
    assert rehearsal.source_refs() == snapshot
    assert not (source / '.git/FETCH_HEAD').exists()
    assert not Path(rehearsal.work).exists()


def test_environment_flag_alone_cannot_skip_preview(tmp_path, source, monkeypatch):
    monkeypatch.setenv(preview.SIM_ROOT, str(tmp_path))
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', str(tmp_path / 'isolated-gitconfig'))
    with pytest.raises(preview.PreviewError, match='NATIVE_PREVIEW_SIM_IDENTITY'):
        preview.simulated_worktree(source, git(source, 'rev-parse', 'HEAD'))


def test_local_simulation_topology_then_changed_push_url(tmp_path, source, monkeypatch):
    base = git(source, 'rev-parse', 'HEAD')
    rehearsal = sim.Sim(source, tmp_path / 'sim', verify_source_bytes=True)
    rehearsal.make_origin(base)
    monkeypatch.setenv(preview.SIM_ROOT, str(rehearsal.workdir))
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', str(rehearsal.gitconfig))
    assert preview.simulated_worktree(rehearsal.work, base)
    git(rehearsal.work, 'config', 'remote.origin.pushurl', 'https://example.invalid/other')
    with pytest.raises(preview.PreviewError, match='NATIVE_PREVIEW_SIM_IDENTITY'):
        preview.simulated_worktree(rehearsal.work, base)


def test_source_python_uses_no_bytecode(tmp_path, source):
    before = sim.Sim(source, tmp_path / 'sim', verify_source_bytes=True).source_refs()
    subprocess.run([sys.executable, '-B', '-c', 'import module'], cwd=source, env=br.child_env(),
                   check=True, capture_output=True, timeout=30)
    assert not (source / '__pycache__').exists()
    assert sim.Sim(source, tmp_path / 'sim2', verify_source_bytes=True).source_refs() == before


def test_preview_rejects_forged_pass_missing_step_and_nonzero():
    spec = {'kind': 'production', 'native_preview': True, 'e24': False, 'focused': None}
    marker = b'BATCH_SIM PASS production locale=utf8 git_profile=windows\n'
    output = b''.join(f'BATCH_SIM STEP {step} rc=0\n'.encode('ascii')
                      for step in (*sim.production_steps(spec), 'push')) + marker
    preview.checked_simulation_output(output, 0, spec)
    for invalid in (marker, output + marker, output.replace(b'BATCH_SIM STEP native_preview rc=0\n', b'')):
        with pytest.raises(preview.PreviewError, match='NATIVE_PREVIEW_LOG_INVALID'):
            preview.checked_simulation_output(invalid, 0, spec)
    with pytest.raises(preview.PreviewError, match='NATIVE_PREVIEW_NONZERO'):
        preview.checked_simulation_output(output, 1, spec)
    with pytest.raises(preview.PreviewError, match='^BASE_NOT_IN_SOURCE$'):
        preview.checked_simulation_output(b'BATCH_SIM FAIL BASE_NOT_IN_SOURCE\n', 1, spec)


def test_setup_needs_existing_bound_simulator_log(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    monkeypatch.delenv(preview.SIM_ROOT, raising=False)
    monkeypatch.setattr(preview.tempfile, 'gettempdir', lambda: str(tmp_path))
    spec = {'kind': 'production', 'native_preview': True, 'e24': False, 'focused': None, 'base_oid': 'a' * 40}
    output = ''.join(f'BATCH_SIM STEP {step} rc=0\n' for step in (*sim.production_steps(spec), 'push'))
    output += 'BATCH_SIM PASS production locale=utf8 git_profile=windows\n'
    directory = tmp_path / 'hhai-g5-abcdefgh'
    directory.mkdir()
    log = directory / 'batch-sim.log'
    log.write_bytes(output.encode('ascii'))
    batch = SimpleNamespace(root=str(tmp_path), task_id='FIXTURE', spec=spec, prompt_bytes=b'fixture',
                            artifact=lambda suffix: suffix)
    (tmp_path / 'native-preview.json').write_bytes(json.dumps({
        'base_oid': spec['base_oid'], 'task_id': batch.task_id, 'prompt_sha256': br.sha256_bytes(batch.prompt_bytes),
        'status': 'PASS', 'log_sha256': br.sha256_bytes(log.read_bytes()),
        'source_snapshot_sha256': 'b' * 64, 'temp_name': directory.name,
    }).encode('ascii'))
    preview.require_receipt(batch)
    other = SimpleNamespace(**{**vars(batch), 'prompt_bytes': b'other prompt'})
    with pytest.raises(preview.PreviewError, match='NATIVE_PREVIEW_RECEIPT_INVALID'):
        preview.require_receipt(other)
    receipt_path = tmp_path / 'native-preview.json'
    good_receipt, good_log = receipt_path.read_bytes(), log.read_bytes()
    forged = good_log.replace(b'BATCH_SIM STEP push rc=0\n', b'')
    log.write_bytes(forged)
    receipt_path.write_bytes(good_receipt.replace(br.sha256_bytes(good_log).encode(), br.sha256_bytes(forged).encode()))
    with pytest.raises(preview.PreviewError, match='^NATIVE_PREVIEW_(RECEIPT|LOG)_INVALID$'):
        preview.require_receipt(batch)
    log.write_bytes(good_log)
    receipt_path.write_bytes(good_receipt)
    log.unlink()
    with pytest.raises(preview.PreviewError, match='NATIVE_PREVIEW_RECEIPT_INVALID'):
        preview.require_receipt(batch)


@pytest.mark.parametrize('failure,code', [
    ('success', None),
    ('timeout', 'NATIVE_PREVIEW_TIMEOUT'),
    ('launch', 'NATIVE_PREVIEW_LAUNCH_FAILED'),
    ('missing_log', 'NATIVE_PREVIEW_LOG_INVALID'),
    ('source_change', 'NATIVE_PREVIEW_SOURCE_MODIFIED'),
])
def test_preview_lifecycle_checks_source_on_every_exit(tmp_path, source, monkeypatch, failure, code):
    from types import SimpleNamespace
    from bounded_process import BoundedResult, KILL_NOT_NEEDED

    monkeypatch.delenv(preview.SIM_ROOT, raising=False)
    monkeypatch.setattr(preview, 'os', SimpleNamespace(name='nt', environ=os.environ, path=os.path))
    monkeypatch.setattr(preview.tempfile, 'gettempdir', lambda: str(tmp_path))
    cache = tmp_path / 'approved-uv-cache'
    cache.mkdir()
    monkeypatch.setattr(preview, 'APPROVED_UV_CACHE_DIR', str(cache))
    monkeypatch.setattr(preview, 'cache_satisfies_lock', lambda *args: None)
    spec = {'kind': 'production', 'native_preview': True, 'e24': False, 'focused': None,
            'base_oid': git(source, 'rev-parse', 'HEAD'), 'start': {'mode': 'clean'}}
    output = ''.join(f'BATCH_SIM STEP {step} rc=0\n' for step in (*sim.production_steps(spec), 'push'))
    output += 'BATCH_SIM PASS production locale=utf8 git_profile=windows\n'
    receipts = {}
    batch = SimpleNamespace(root=str(source), task_id='FIXTURE', spec=spec, prompt_bytes=b'fixture',
                            write_new_artifact=lambda name, content: receipts.update({name: content}))

    def simulate(command, cwd, limit, **kwargs):
        assert command[1] == '-B' and kwargs['env']['PYTHONDONTWRITEBYTECODE'] == '1'
        # Absolute, module-adjacent simulator: never the cwd-relative copy in the source workspace.
        assert command[2] == str(Path(preview.__file__).resolve().parent / 'batch_sim.py')
        assert Path(command[2]).is_absolute()
        # The approved cache reaches the simulator explicitly; its own default is never the source.
        assert command.count('--uv-cache-dir') == 1
        assert command[command.index('--uv-cache-dir') + 1] == str(cache.resolve())
        if failure == 'source_change':
            (source / '__pycache__').mkdir()
        if failure != 'missing_log':
            Path(kwargs['capture_path']).write_bytes(output.encode('ascii'))
        return BoundedResult(0, failure == 'timeout', 'OSError' if failure == 'launch' else None,
                             output.encode('ascii'), b'', KILL_NOT_NEEDED)

    monkeypatch.setattr(preview, 'run_bounded', simulate)
    if code:
        with pytest.raises(preview.PreviewError, match='^' + code + '$'):
            preview.run(batch)
        assert not receipts
        assert Path(batch.native_preview_evidence_dir).is_dir()
    else:
        preview.run(batch)
        assert 'native-preview.json' in receipts
        assert Path(batch.native_preview_evidence_dir).is_dir()


def test_macro_declaration_requires_every_current_check():
    import prompt_builder as builder

    declaration = {f'E{i}': 'PASS — verified fixture' for i in range(1, 28)}
    builder.validate_auditor_selfcheck(declaration)
    declaration.pop('E14')
    with pytest.raises(builder.BuildError, match='AUDITOR_SELFCHECK_INCOMPLETE'):
        builder.validate_auditor_selfcheck(declaration)
    declaration['E14'] = 'NOT_ESTABLISHED — fixture'
    with pytest.raises(builder.BuildError, match='AUDITOR_SELFCHECK_INVALID'):
        builder.validate_auditor_selfcheck(declaration)


def test_adopt_preview_copies_only_current_hash_bound_files(tmp_path, source):
    base = git(source, 'rev-parse', 'HEAD')
    rehearsal = sim.Sim(source, tmp_path / 'sim', verify_source_bytes=True)
    rehearsal.make_origin(base)
    rehearsal.git('switch', '-q', '-c', sim.START_BRANCH)
    content = b'VALUE = 2\n'
    (source / 'module.py').write_bytes(content)
    before = rehearsal.source_refs()
    spec = {'start': {'start_branch': 'batch/adopt-fixture', 'adopt_hashes': {
        'module.py': br.sha256_bytes(content)}}}
    rehearsal.adopt_source(spec)
    assert (Path(rehearsal.work) / 'module.py').read_bytes() == content
    assert git(rehearsal.work, 'branch', '--show-current') == 'batch/adopt-fixture'
    assert rehearsal.source_refs() == before


def test_adopt_preview_rejects_input_hash_drift(tmp_path, source):
    base = git(source, 'rev-parse', 'HEAD')
    rehearsal = sim.Sim(source, tmp_path / 'sim', verify_source_bytes=True)
    rehearsal.make_origin(base)
    spec = {'start': {'start_branch': 'batch/adopt-fixture', 'adopt_hashes': {
        'module.py': '0' * 64}}}
    with pytest.raises(sim.SimError, match='^ADOPT_SOURCE_HASH_MISMATCH$'):
        rehearsal.adopt_source(spec)


def test_real_batch_constructor_rejects_missing_preview_flag(tmp_path, source, monkeypatch):
    (source / '.git/FIXTURE-prompt.txt').write_bytes(b'fixture')
    spec = {'kind': 'production', 'base_oid': 'a' * 40, 'authors': {'scripts/tool.py': {}}}
    monkeypatch.setattr(br, 'load_spec', lambda *args: spec)
    monkeypatch.setattr(br, 'base_supports_native_preview', lambda *args: True)
    with pytest.raises(br.Halt, match='^NATIVE_PREVIEW_SPEC_MISMATCH$'):
        br.Batch(str(source), 'FIXTURE')
    spec['native_preview'] = True
    assert br.Batch(str(source), 'FIXTURE').spec['native_preview'] is True


def test_setup_checks_receipt_before_any_fetch(tmp_path, monkeypatch):
    from types import SimpleNamespace

    def no_command(*args, **kwargs):
        raise AssertionError('setup ran a command before the receipt check')

    def invalid(batch):
        raise preview.PreviewError('NATIVE_PREVIEW_RECEIPT_INVALID')

    monkeypatch.setattr(br, 'run', no_command)
    monkeypatch.setattr(br, 'git', no_command)
    monkeypatch.setattr(preview, 'require_receipt', invalid)
    batch = SimpleNamespace(root=str(tmp_path), spec={'native_preview': True, 'base_oid': 'a' * 40, 'branch': 'batch/x'})
    with pytest.raises(br.Halt, match='^NATIVE_PREVIEW_RECEIPT_INVALID$'):
        br.Batch.step_setup(batch)


def test_legacy_preapply_exception_expires_once_base_declares_preview(tmp_path, monkeypatch):
    from types import SimpleNamespace

    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts' / 'batch_runner.py').write_bytes(b'new runner\n')
    steps = ['preflight', 'setup', 'e24', 'apply', 'generate']
    spec = {'kind': 'production', 'runner_update': True, 'base_oid': 'a' * 40,
            'authors': {br.RUNNER_REL: {'sha256': br.sha256_bytes(b'new runner\n')}}}
    batch = SimpleNamespace(root=str(tmp_path), spec=spec)
    for base, allowed in ((b"PRODUCTION_STEPS = ('preflight', 'setup', 'e24', 'apply', 'generate')\n", True),
                          (b"PRODUCTION_STEPS = ('preflight', 'native_preview', 'setup', 'e24', 'apply', 'generate')\n", False)):
        monkeypatch.setattr(br, 'git_bytes', lambda root, *args, blob=base: blob)
        control = {'done': steps, 'halted': None, 'runner_sha256': br.sha256_bytes(base)}
        assert br._legacy_preapply_record_allowed(batch, control, 'apply', steps) is allowed


@pytest.mark.parametrize('kind', ['empty', 'relative', 'missing', 'file', 'inside_workspace', 'workspace_itself',
                                  'workspace_parent'])
def test_invalid_uv_cache_stops_before_any_simulation_or_temp_area(tmp_path, source, monkeypatch, kind):
    from types import SimpleNamespace

    monkeypatch.delenv(preview.SIM_ROOT, raising=False)
    monkeypatch.setattr(preview, 'os', SimpleNamespace(name='nt', environ=os.environ, path=os.path))
    temp = tmp_path / 'temp'
    temp.mkdir()
    monkeypatch.setattr(preview.tempfile, 'gettempdir', lambda: str(temp))
    (tmp_path / 'a-file').write_bytes(b'not a directory')
    (source / 'cache-inside').mkdir()
    # The working directory is a valid directory unrelated to the workspace: an empty value (which a path
    # object would turn into '.') and a relative spelling must still be refused for being unrecorded.
    elsewhere = tmp_path / 'elsewhere'
    (elsewhere / 'uv-cache').mkdir(parents=True)
    monkeypatch.chdir(elsewhere)
    values = {'empty': '', 'relative': 'uv-cache', 'missing': str(tmp_path / 'absent'),
              'file': str(tmp_path / 'a-file'), 'inside_workspace': str(source / 'cache-inside'),
              'workspace_itself': str(source), 'workspace_parent': str(tmp_path)}
    monkeypatch.setattr(preview, 'APPROVED_UV_CACHE_DIR', values[kind])

    def no_simulation(*args, **kwargs):
        raise AssertionError('the simulator ran without an approved uv cache')

    monkeypatch.setattr(preview, 'run_bounded', no_simulation)
    spec = {'kind': 'production', 'native_preview': True, 'e24': False, 'focused': None,
            'base_oid': git(source, 'rev-parse', 'HEAD'), 'start': {'mode': 'clean'}}
    batch = SimpleNamespace(root=str(source), task_id='FIXTURE', spec=spec, prompt_bytes=b'fixture',
                            write_new_artifact=lambda name, content: None)
    with pytest.raises(preview.PreviewError, match='^NATIVE_PREVIEW_UV_CACHE_INVALID$'):
        preview.run(batch)
    assert not list(temp.iterdir())
    assert not hasattr(batch, 'native_preview_evidence_dir')


def test_simulated_worktree_needs_no_uv_cache(tmp_path, source, monkeypatch):
    from types import SimpleNamespace

    base = git(source, 'rev-parse', 'HEAD')
    rehearsal = sim.Sim(source, tmp_path / 'sim', verify_source_bytes=True)
    rehearsal.make_origin(base)
    monkeypatch.setenv(preview.SIM_ROOT, str(rehearsal.workdir))
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', str(rehearsal.gitconfig))
    monkeypatch.setattr(preview, 'APPROVED_UV_CACHE_DIR', str(tmp_path / 'absent'))
    batch = SimpleNamespace(root=str(rehearsal.work), spec={'base_oid': base})
    preview.run(batch)


@pytest.mark.parametrize('code', ['NATIVE_PREVIEW_UV_CACHE_INVALID', 'NATIVE_PREVIEW_UV_CACHE_INCOMPLETE',
                                  'NATIVE_PREVIEW_NONZERO', 'BASE_NOT_IN_SOURCE'])
def test_runner_reports_preview_stop_codes_unchanged(monkeypatch, code):
    from types import SimpleNamespace
    import validate_prompt_manifest as manifest

    contract = {'native_preview_external_write': 'TEMP_ISOLATED_NATIVE_PREVIEW'}
    monkeypatch.setattr(manifest, 'parse_execution_contract_block', lambda text: (True, None, contract))

    def stop(batch):
        raise preview.PreviewError(code)

    monkeypatch.setattr(preview, 'run', stop)
    batch = SimpleNamespace(prompt_bytes=b'fixture')
    with pytest.raises(br.Halt) as info:
        br.Batch.step_native_preview(batch)
    assert str(info.value) == code


def _bootstrap_module():
    import native_preview_bootstrap as bootstrap
    return bootstrap


def test_approved_uv_cache_is_the_one_recorded_hhai_toolchain_directory():
    assert preview.APPROVED_UV_CACHE_DIR == 'C:\\Users\\HH.AI_260806\\hhai-toolchain\\uv-cache'
    assert not hasattr(preview, 'UV_CACHE_ENV')


def test_bootstrap_script_bakes_in_the_recorded_cache_and_takes_no_cache_input():
    bootstrap = _bootstrap_module()
    text = bootstrap.render_script('a' * 40, 'task-prompt.txt', 'b' * 64, 'author.patch', 'c' * 64)
    assert "$uvCache = 'C:\\Users\\HH.AI_260806\\hhai-toolchain\\uv-cache'" in text
    assert "if (!(Test-Path -LiteralPath $uvCache -PathType Container)) { throw 'BOOTSTRAP_UV_CACHE_MISSING' }" in text
    assert 'UvCacheDir' not in text and '--uv-cache-dir' not in text
    assert text.index('BOOTSTRAP_UV_CACHE_MISSING') < text.index('$area = ')
    for hostile in ("C:\\x'; calc; '", 'C:\\x$env:TEMP', 'relative\\cache', 'C:\\x\nC:\\y', ''):
        with pytest.raises(preview.PreviewError, match='^BOOTSTRAP_UV_CACHE_PATH_INVALID$'):
            bootstrap.render_script('a' * 40, 'task-prompt.txt', 'b' * 64, 'author.patch', 'c' * 64, hostile)


def test_bootstrap_run_takes_no_cache_argument(monkeypatch, capsys):
    bootstrap = _bootstrap_module()
    monkeypatch.setattr(sys, 'argv', ['native_preview_bootstrap.py', 'run', '--source', 's', '--prompt', 'p',
                                      '--patch', 'q', '--workdir', 'w', '--prompt-sha256', 'a', '--patch-sha256', 'b',
                                      '--uv-cache-dir', 'C:\\elsewhere'])
    with pytest.raises(SystemExit) as info:
        bootstrap.main()
    assert info.value.code == 2


@pytest.fixture
def locked_source(source):
    (source / 'pyproject.toml').write_bytes(b'[project]\nname = "fixture"\nversion = "0"\n')
    (source / 'uv.lock').write_bytes(b'version = 1\n')
    (source / '.python-version').write_bytes(b'3.13\n')
    git(source, 'add', '.')
    git(source, 'commit', '-qm', 'locked fixture')
    return source


def _fake_uv(monkeypatch, stdout=b'Would create project environment at x\nWould install 3 packages\n', returncode=0,
             timed_out=False, launch_error=None, seen=None):
    from bounded_process import BoundedResult, KILL_NOT_NEEDED

    monkeypatch.setattr(preview.shutil, 'which', lambda name: '/fixture/uv')

    def run(command, cwd, limit, **kwargs):
        if seen is not None:
            seen.update(command=command, cwd=cwd, limit=limit, env=kwargs['env'], merge=kwargs['merge_stderr'],
                        files=sorted(p.name for p in Path(command[-1]).iterdir()),
                        pin=(Path(command[-1]) / '.python-version').read_bytes())
        return BoundedResult(returncode, timed_out, launch_error, stdout, b'', KILL_NOT_NEEDED)

    monkeypatch.setattr(preview, 'run_bounded', run)


def test_cache_check_dry_runs_the_base_lock_offline_from_a_throwaway_copy(tmp_path, locked_source, monkeypatch):
    base = git(locked_source, 'rev-parse', 'HEAD')
    cache = tmp_path / 'approved-uv-cache'
    cache.mkdir()
    monkeypatch.setenv('UV_CACHE_DIR', str(tmp_path / 'hostile'))
    monkeypatch.setenv('UV_INDEX_URL', 'https://example.invalid/simple')
    seen = {}
    _fake_uv(monkeypatch, seen=seen)
    before = sim.Sim(locked_source, tmp_path / 'sim', verify_source_bytes=True).source_refs()
    preview.cache_satisfies_lock(locked_source, base, cache)
    command = seen['command']
    assert command[:2] == ['/fixture/uv', '--no-config']
    for flag in ('--locked', '--offline', '--no-python-downloads', '--dry-run'):
        assert flag in command
    assert command[command.index('--python') + 1] == '3.13'
    project = Path(command[command.index('--project') + 1])
    assert project != locked_source and not project.exists()
    assert seen['cwd'] == str(project) and seen['merge'] is True and seen['limit'] == preview.UV_CHECK_TIMEOUT
    assert seen['files'] == ['.python-version', 'pyproject.toml', 'uv.lock']
    assert seen['pin'] == b'3.13\n'
    env = seen['env']
    assert env['UV_CACHE_DIR'] == str(cache) and env['UV_OFFLINE'] == '1' and env['UV_PYTHON_DOWNLOADS'] == 'never'
    assert 'UV_INDEX_URL' not in env
    assert sim.Sim(locked_source, tmp_path / 'sim2', verify_source_bytes=True).source_refs() == before


@pytest.mark.parametrize('case', ['download', 'nonzero', 'timeout', 'launch'])
def test_cache_check_refuses_incomplete_cache_even_when_uv_exits_zero(tmp_path, locked_source, monkeypatch, case):
    base = git(locked_source, 'rev-parse', 'HEAD')
    cache = tmp_path / 'approved-uv-cache'
    cache.mkdir()
    options = {
        'download': dict(stdout=b'Resolved 11 packages in 3ms\nWould download 7 packages\nWould install 10 packages\n'),
        'nonzero': dict(returncode=2),
        'timeout': dict(returncode=0, timed_out=True),
        'launch': dict(returncode=0, launch_error='OSError'),
    }[case]
    _fake_uv(monkeypatch, **options)
    with pytest.raises(preview.PreviewError, match='^NATIVE_PREVIEW_UV_CACHE_INCOMPLETE$'):
        preview.cache_satisfies_lock(locked_source, base, cache)


def test_cache_check_needs_uv_and_a_committed_lock_and_pin(tmp_path, locked_source, monkeypatch):
    base = git(locked_source, 'rev-parse', 'HEAD')
    cache = tmp_path / 'approved-uv-cache'
    cache.mkdir()
    _fake_uv(monkeypatch)  # a runner that would succeed: without uv on PATH the check must still refuse
    monkeypatch.setattr(preview.shutil, 'which', lambda name: None)
    with pytest.raises(preview.PreviewError, match='^NATIVE_PREVIEW_UV_CACHE_INCOMPLETE$'):
        preview.cache_satisfies_lock(locked_source, base, cache)
    _fake_uv(monkeypatch)
    preview.cache_satisfies_lock(locked_source, base, cache)
    (locked_source / '.python-version').write_bytes(b'latest\n')
    git(locked_source, 'commit', '-qam', 'bad pin')
    with pytest.raises(preview.PreviewError, match='^NATIVE_PREVIEW_UV_CACHE_INCOMPLETE$'):
        preview.cache_satisfies_lock(locked_source, git(locked_source, 'rev-parse', 'HEAD'), cache)
    with pytest.raises(preview.PreviewError, match='^NATIVE_PREVIEW_UV_CACHE_INCOMPLETE$'):
        preview.cache_satisfies_lock(source_without_lock(tmp_path), git(source_without_lock(tmp_path), 'rev-parse', 'HEAD'), cache)


def source_without_lock(tmp_path):
    repo = tmp_path / 'no-lock'
    if not repo.exists():
        repo.mkdir()
        git(repo, 'init', '-q', '--template=', '-b', 'main')
        git(repo, 'config', 'user.name', 'Fixture')
        git(repo, 'config', 'user.email', 'fixture@example.invalid')
        (repo / 'module.py').write_bytes(b'VALUE = 1\n')
        git(repo, 'add', '.')
        git(repo, 'commit', '-qm', 'fixture')
    return repo


def test_incomplete_cache_stops_before_any_temp_area_or_simulation(tmp_path, source, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.delenv(preview.SIM_ROOT, raising=False)
    monkeypatch.setattr(preview, 'os', SimpleNamespace(name='nt', environ=os.environ, path=os.path))
    temp = tmp_path / 'temp'
    temp.mkdir()
    monkeypatch.setattr(preview.tempfile, 'gettempdir', lambda: str(temp))
    cache = tmp_path / 'approved-uv-cache'
    cache.mkdir()
    monkeypatch.setattr(preview, 'APPROVED_UV_CACHE_DIR', str(cache))
    base = git(source, 'rev-parse', 'HEAD')
    calls = []

    def incomplete(workspace, oid, approved):
        calls.append((Path(workspace), oid, approved))
        raise preview.PreviewError('NATIVE_PREVIEW_UV_CACHE_INCOMPLETE')

    monkeypatch.setattr(preview, 'cache_satisfies_lock', incomplete)
    monkeypatch.setattr(preview, 'run_bounded', lambda *a, **k: pytest.fail('simulator ran'))
    batch = SimpleNamespace(root=str(source), task_id='FIXTURE', prompt_bytes=b'fixture',
                            spec={'kind': 'production', 'native_preview': True, 'base_oid': base,
                                  'start': {'mode': 'clean'}},
                            write_new_artifact=lambda name, content: None)
    with pytest.raises(preview.PreviewError, match='^NATIVE_PREVIEW_UV_CACHE_INCOMPLETE$'):
        preview.run(batch)
    assert calls == [(source.resolve(), base, cache.resolve())]
    assert not list(temp.iterdir())
    assert not hasattr(batch, 'native_preview_evidence_dir')


def _preflight_batch(tmp_path, monkeypatch, spec):
    from types import SimpleNamespace

    (tmp_path / 'scripts').mkdir(exist_ok=True)
    (tmp_path / 'scripts' / 'batch_runner.py').write_bytes(b'runner\n')
    monkeypatch.setattr(br, 'git', lambda *args, **kwargs: 'blob')
    monkeypatch.setattr(br, 'git_blob_sha1', lambda data: 'blob')
    monkeypatch.setattr(br, 'run', lambda *args, **kwargs: '')
    monkeypatch.setattr(br, 'check_must_read', lambda *args: None)
    monkeypatch.setattr(br, 'derive_must_read', lambda *args: [])
    monkeypatch.setattr(br, 'check_must_read_worktree', lambda *args: None)
    batch = SimpleNamespace(root=str(tmp_path), spec=spec, prompt_rel='p', task_id='FIXTURE', lines=[])
    batch.check_native_preview_cache = lambda: br.Batch.check_native_preview_cache(batch)
    return batch


@pytest.mark.parametrize('code', ['NATIVE_PREVIEW_UV_CACHE_INVALID', 'NATIVE_PREVIEW_UV_CACHE_INCOMPLETE'])
def test_runner_preflight_stops_on_missing_or_incomplete_cache_before_preview(tmp_path, monkeypatch, code):
    batch = _preflight_batch(tmp_path, monkeypatch, {'kind': 'production', 'native_preview': True, 'base_oid': 'a' * 40})
    monkeypatch.setattr(preview, 'simulated_worktree', lambda root, base: False)

    def refuse(workspace, base):
        raise preview.PreviewError(code)

    monkeypatch.setattr(preview, 'require_uv_cache', refuse)
    with pytest.raises(br.Halt) as info:
        br.Batch.step_preflight(batch)
    assert str(info.value) == code


def test_runner_preflight_checks_cache_only_for_real_native_preview_batches(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(preview, 'require_uv_cache', lambda workspace, base: seen.append(base))
    for spec, simulated, expected in (
            ({'kind': 'production', 'native_preview': True, 'base_oid': 'a' * 40}, False, ['a' * 40]),
            ({'kind': 'production', 'native_preview': True, 'base_oid': 'a' * 40}, True, []),
            ({'kind': 'production', 'native_preview': False, 'base_oid': 'a' * 40}, False, []),
            ({'kind': 'production', 'base_oid': 'a' * 40}, False, []),
            ({'kind': 'promotion', 'native_preview': True, 'base_oid': 'a' * 40}, False, [])):
        seen.clear()
        monkeypatch.setattr(preview, 'simulated_worktree', lambda root, base, flag=simulated: flag)
        br.Batch.step_preflight(_preflight_batch(tmp_path, monkeypatch, spec))
        assert seen == expected


def test_bootstrap_reports_the_python_the_simulation_venv_uses(tmp_path):
    bootstrap = _bootstrap_module()
    cfg = tmp_path / 'sim' / 'work' / '.venv' / 'pyvenv.cfg'
    cfg.parent.mkdir(parents=True)
    cfg.write_text('home = C:\\Users\\x\\AppData\\Local\\Python\\pythoncore-3.14-64\nuv = 0.11.32\n'
                   'version_info = 3.14.7\n', encoding='utf-8', newline='\n')
    assert bootstrap.sim_python_info(tmp_path) == ('C:\\Users\\x\\AppData\\Local\\Python\\pythoncore-3.14-64', '3.14.7')
    for text in ('uv = 0.11.32\n', 'home = x\n', 'home = \nversion_info = 3.14.7\n', 'home = x\nversion_info = latest\n'):
        cfg.write_text(text, encoding='utf-8', newline='\n')
        with pytest.raises(preview.PreviewError, match='^BOOTSTRAP_SIM_PYTHON_UNREADABLE$'):
            bootstrap.sim_python_info(tmp_path)
    cfg.unlink()
    with pytest.raises(preview.PreviewError, match='^BOOTSTRAP_SIM_PYTHON_UNREADABLE$'):
        bootstrap.sim_python_info(tmp_path)


def test_bootstrap_run_reports_and_records_the_simulation_python(tmp_path, monkeypatch, capsys):
    import json
    import zipfile
    from types import SimpleNamespace

    from bounded_process import BoundedResult, KILL_NOT_NEEDED

    bootstrap = _bootstrap_module()
    work = tmp_path / 'work'
    repo = work / 'author'
    (repo / 'scripts').mkdir(parents=True)
    (repo / 'module.py').write_bytes(b'VALUE = 1\n')
    source = tmp_path / 'w2'
    source.mkdir()
    prompt = tmp_path / 'task-prompt.txt'
    prompt.write_bytes(b'prompt\n')
    patch = tmp_path / 'author.patch'
    patch.write_bytes(b'patch\n')
    base = 'a' * 40
    spec = {'base_oid': base, 'task_id': 'FIXTURE', 'authors': {'module.py': {'sha256': bootstrap.digest(b'VALUE = 1\n')}}}
    temp = tmp_path / 'temp'
    temp.mkdir()
    area = temp / 'hhai-g5-fixture'
    cfg = area / 'sim' / 'work' / '.venv' / 'pyvenv.cfg'
    cfg.parent.mkdir(parents=True)
    cfg_text = 'home = C:\\Python314\nversion_info = 3.14.7\n'
    cfg.write_text(cfg_text, encoding='utf-8', newline='\n')
    log = b'BATCH_SIM PASS fixture\n'
    (area / 'batch-sim.log').write_bytes(log)

    class FakeSim:
        def __init__(self, *args, **kwargs):
            self.source = str(source)
            self.env = {}

        def git(self, *args, **kwargs):
            return base

        def source_refs(self):
            return {'refs': 'same'}

    def fake_preview_run(activation):
        activation.write_new_artifact('native-preview.json', json.dumps(
            {'temp_name': area.name, 'log_sha256': bootstrap.digest(log)}))

    def fake_bounded(command, cwd, limit, **kwargs):
        stdout = b'55 passed in 3.00s\n'
        Path(kwargs['capture_path']).write_bytes(stdout)
        return BoundedResult(0, False, None, stdout, b'', KILL_NOT_NEEDED)

    monkeypatch.setattr(bootstrap, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(bootstrap, '__file__', str(repo / 'scripts' / 'native_preview_bootstrap.py'))
    monkeypatch.setattr(bootstrap, 'activation_inputs', lambda repo_dir, prompt_path: (prompt.read_bytes(), spec))
    monkeypatch.setattr(bootstrap.br, 'git', lambda *args, **kwargs: base)
    monkeypatch.setattr(bootstrap.br, 'changed_paths', lambda *args, **kwargs: ['module.py'])
    monkeypatch.setattr(bootstrap.sim, 'Sim', FakeSim)
    monkeypatch.setattr(bootstrap.preview, 'run', fake_preview_run)
    monkeypatch.setattr(bootstrap.preview, 'checked_simulation_output', lambda *args, **kwargs: None)
    monkeypatch.setattr(bootstrap.tempfile, 'gettempdir', lambda: str(temp))
    monkeypatch.setattr(bootstrap, 'run_bounded', fake_bounded)
    args = SimpleNamespace(source=source, prompt=prompt, patch=patch, workdir=work,
                           prompt_sha256=bootstrap.digest(prompt.read_bytes()),
                           patch_sha256=bootstrap.digest(patch.read_bytes()))
    bootstrap.run(args)
    out = capsys.readouterr().out
    assert 'BOOTSTRAP_SIM_PYTHON home=C:\\Python314 version_info=3.14.7\n' in out
    assert (work / 'sim-pyvenv.cfg').read_text(encoding='utf-8') == cfg_text
    receipt = json.loads((work / 'bootstrap-receipt.json').read_bytes())
    assert receipt['sim_python_home'] == 'C:\\Python314' and receipt['sim_python_version_info'] == '3.14.7'
    with zipfile.ZipFile(work / 'bootstrap-evidence.zip') as archive:
        assert 'sim-pyvenv.cfg' in archive.namelist()
