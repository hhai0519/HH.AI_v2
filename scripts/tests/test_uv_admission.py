# -*- coding: utf-8 -*-
"""F-UV-A1: mandatory precontrol requirements for offline uv admission.

All probes are synthetic/non-network; Windows reparse and PATH alias acceptance
requires independent native evidence on the final SHA.
"""
import os
import sys
import subprocess
from pathlib import Path
import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import runtime_readiness as rr


@pytest.fixture
def uv_fixture(tmp_path, monkeypatch):
    p = tmp_path
    venv = p / '.venv'
    binary = venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b'fixture only\n')
    (p / '.python-version').write_text('.'.join(map(str, sys.version_info[:2])) + '\n')
    (p / 'uv.lock').write_text('fixture uv lock')
    (p / 'pyproject.toml').write_text('[project]\nrequires-python=">=3.11"\n[tool.uv]\nrequired-version="==0.11.32"\n')
    (p / 'requirements.txt').write_text('pytest==9.1.1\ncolorama==0.4.6; sys_platform == "win32"\n')
    monkeypatch.setattr(rr.sys, 'executable', str(binary))
    monkeypatch.setattr(rr.sys, 'prefix', str(venv))
    monkeypatch.setattr(rr.sys, 'base_prefix', str(p/'base'))
    selected = {'python':str(binary),'uv':str(p/'uv'),'node':str(p/'node')}
    monkeypatch.setattr(rr.shutil, 'which', lambda name: selected.get(name))
    calls=[]
    def run_uv(uv, args, root, *, output_limit=8192):
        calls.append(tuple(args))
        if args == ['--version']:
            return 'uv 0.11.32 (3010295ae 2026-07-23 x86_64-pc-windows-msvc)'
        if args[:2] == ['lock', '--check']:
            return ''
        if args[0] == 'export':
            return "colorama==0.4.6 ; sys_platform == 'win32'\npytest==9.1.1"
        raise AssertionError(args)
    monkeypatch.setattr(rr, '_uv_call', run_uv)
    return p,binary,selected,calls


def test_live_root_has_uv_lock_and_venv_ignore():
    repo=Path(__file__).resolve().parents[2]
    assert (repo / 'uv.lock').is_file()
    assert '/.venv/' in (repo / '.gitignore').read_text()
    result=subprocess.run(['git', '-C', str(repo), 'ls-files', '--', '.venv'],
                          capture_output=True, text=True, timeout=8, check=True)
    assert not result.stdout.strip()


def test_strict_uv_precontrol_accepts_same_python_and_locked_pinset(uv_fixture):
    p,b,selected,calls=uv_fixture
    rr.uv_admission(p)
    assert ('lock','--check','--offline','--no-python-downloads') in calls
    assert any(x[0]=='export' and '--offline' in x and '--locked' in x for x in calls)
    assert not list((p / '.venv').glob('*.tmp'))


def test_missing_venv_fails_closed_without_creation(uv_fixture):
    p,b,_,calls=uv_fixture
    b.unlink()
    with pytest.raises(rr.RuntimeMismatch,match='^VENV_MISSING$'):
        rr.uv_admission(p)
    assert not b.exists()
    assert calls==[]


def test_system_path_python_mismatch_fails_before_uv(uv_fixture):
    p,b,sel,calls=uv_fixture
    sel['python']=str(p / 'system-python.exe')
    with pytest.raises(rr.RuntimeMismatch,match='^PATH_PYTHON_MISMATCH$'):
        rr.uv_admission(p)
    assert calls==[]


def test_wrong_sys_executable_fails_before_uv(uv_fixture,monkeypatch):
    p,b,sel,calls=uv_fixture
    monkeypatch.setattr(rr.sys,'executable',str(p/'outside.exe'))
    with pytest.raises(rr.RuntimeMismatch,match='^VENV_PYTHON_MISMATCH$'):
        rr.uv_admission(p)
    assert calls==[]


def test_reparse_component_fails_closed(uv_fixture, monkeypatch):
    p,b,sel,calls=uv_fixture
    original=rr._no_reparse
    def reparse(path):
        if Path(path).name=='.venv':
            raise rr.RuntimeMismatch('VENV_REPARSE_FORBIDDEN')
        return original(path)
    monkeypatch.setattr(rr,'_no_reparse',reparse)
    with pytest.raises(rr.RuntimeMismatch, match='^VENV_REPARSE_FORBIDDEN$'):
        rr.uv_admission(p)
    assert calls==[]


@pytest.mark.parametrize('text', [
    'uv 0.11.32',
    'uv 0.11.32 (x86_64-unknown-linux-gnu)',
    'uv 0.11.32 (3010295ae 2026-07-23 x86_64-pc-windows-msvc)',
    'uv 0.11.32 (x86_64-pc-windows-msvc)',
])
def test_uv_version_accepts_real_cli_formats(text):
    m = rr._UV_VER.fullmatch(text)
    assert m is not None and m.group(1) == '0.11.32'


@pytest.mark.parametrize('text', [
    'uv 0.11.32 extra', 'uv 0.11.32 (a) (b)', 'uv 0.11.32 ()', 'uv 0.11.32 (a(b))',
    'uv v0.11.32', 'uvx 0.11.32', 'uv 0.11.32\n(x86_64-unknown-linux-gnu)',
    'uv 0.11.32 (' + 'x' * 81 + ')', 'uv 0.11',
])
def test_uv_version_rejects_malformed(text):
    assert rr._UV_VER.fullmatch(text) is None


def test_old_uv_version_rejected(uv_fixture,monkeypatch):
    p,b,sel,calls=uv_fixture
    runner=rr._uv_call
    def old_uv(uv,args,root,*,output_limit=8192):
        return 'uv 0.10.0' if args==['--version'] else runner(uv,args,root,output_limit=output_limit)
    monkeypatch.setattr(rr,'_uv_call',old_uv)
    with pytest.raises(rr.RuntimeMismatch,match='^UV_VERSION_MISMATCH$'):
        rr.uv_admission(p)
    assert not any(x[:2]==('lock','--check') for x in calls)


def test_lock_stale_stops_before_export(uv_fixture,monkeypatch):
    p,b,sel,calls=uv_fixture
    runner=rr._uv_call
    def stale(uv,args,root,*,output_limit=8192):
        if args[:2]==['lock','--check']:
            raise rr.RuntimeMismatch('UV_COMMAND_NONZERO')
        return runner(uv,args,root,output_limit=output_limit)
    monkeypatch.setattr(rr,'_uv_call',stale)
    with pytest.raises(rr.RuntimeMismatch, match='^UV_COMMAND_NONZERO$'):
        rr.uv_admission(p)
    assert not any(x[0]=='export' for x in calls)


def test_export_pin_drift_fails_closed(uv_fixture,monkeypatch):
    p,b,sel,calls=uv_fixture
    runner=rr._uv_call
    def mismatch(uv,args,root,*,output_limit=8192):
        return 'pytest==9.1.1' if args[0]=='export' else runner(uv,args,root,output_limit=output_limit)
    monkeypatch.setattr(rr,'_uv_call',mismatch)
    with pytest.raises(rr.RuntimeMismatch, match='^UV_EXPORT_REQUIREMENTS_MISMATCH$'):
        rr.uv_admission(p)


def test_noncanonical_pin_is_rejected():
    with pytest.raises(rr.RuntimeMismatch,match='UV_EXPORT_PIN_INVALID'):
        rr._pin_set('pytest>=9.1.1')
    with pytest.raises(rr.RuntimeMismatch,match='UV_EXPORT_MARKER_UNSUPPORTED'):
        rr._pin_set('pytest==9.1.1 ; extra == "x"')


def test_cli_uses_strict_uv_when_lock_present(uv_fixture, monkeypatch):
    p,b,sel,calls=uv_fixture
    # The strict admission is mandatory whenever the source lock exists.
    # Do not invoke pytest/Node on this negative fixture after the missing .venv.
    b.unlink()
    with pytest.raises(rr.RuntimeMismatch,match='^VENV_MISSING$'):
        rr.check(p)
    assert calls==[]


def test_canonical_entry_has_no_sync_or_python_download():
    from scripts import production_template, prompt_builder, promotion_template
    template=Path(production_template.__file__).read_text()
    assert 'pb.production_runner_commands(' in template
    commands = []
    for preview in (False, True):
        commands.extend(prompt_builder.production_runner_commands('UV-FIXTURE', ['preflight', 'setup'], preview))
    text='\n'.join(commands)
    startup=Path(prompt_builder.__file__).read_text()
    promotion=Path(promotion_template.__file__).read_text()
    for s in (text,startup,promotion):
        assert 'uv run --offline --no-sync --no-python-downloads --python .venv' in s
        assert 'uv sync' not in s  # preparation must be separately authorized
        assert 'uv run --locked' not in s


def test_lock_missing_is_not_a_legacy_bypass(uv_fixture):
    p,b,sel,calls=uv_fixture
    (p / 'uv.lock').unlink()
    with pytest.raises(rr.RuntimeMismatch, match='^UV_LOCK_INVALID$'):
        rr.check(p)
    assert calls == []


def test_repo_lock_packages_match_unchanged_pip_pins():
    """Static cross-platform source check; runtime uv lock freshness remains mandatory."""
    import tomllib
    repo = Path(__file__).resolve().parents[2]
    lock = tomllib.loads((repo / 'uv.lock').read_text())
    project = tomllib.loads((repo / 'pyproject.toml').read_text())
    rows = {(p['name'],p['version']) for p in lock['package'] if p['name'] != project['project']['name']}
    want = {tuple(pin.split('==',1)) for pin in rr._pin_set((repo / 'requirements.txt').read_text())
            if ';' not in pin} | {tuple(pin.split(';',1)[0].split('==',1))
                                for pin in rr._pin_set((repo / 'requirements.txt').read_text())
                                if ';' in pin}
    assert rows == want
    assert project['project']['requires-python'] == '>=3.11'
    assert project['tool']['uv']['required-version'] == '==0.11.32'
    assert (repo / '.python-version').read_text().strip() == '3.14'


def test_active_rule_commands_are_uv_ready_except_explicit_transition_note():
    repo = Path(__file__).resolve().parents[2]
    relatives = ['AGENTS.md', '.agents/rules/git-and-reporting.md',
                 '.agents/rules/prompt-preflight.md', '.agents/rules/role-boundaries.md',
                 '.agents/rules/secret-output-safety.md']
    assert 'uv run --offline --no-sync --no-python-downloads --python .venv' in (repo/'AGENTS.md').read_text()
    for rel in relatives:
        content = (repo / rel).read_text(encoding='utf8')
        assert '〈PY〉' in content
        if rel != 'AGENTS.md':
            for line in content.splitlines():
                if 'python scripts/' in line:
                    assert 'uv run --offline --no-sync --no-python-downloads --python .venv' in line
    assert '本 uv 遷移批' in (repo / 'AGENTS.md').read_text()


def test_posix_symlinked_python_accepts_managed_prefix(uv_fixture, monkeypatch):
    p, binary, selected, calls = uv_fixture
    if os.name == 'nt':
        pytest.skip('POSIX uv bin/python symlink only')
    binary.unlink()
    binary.symlink_to(getattr(sys, '_base_executable', '/usr/bin/python3'))
    monkeypatch.setattr(rr.sys, 'executable', str(binary.parent/'python3'))
    (binary.parent/'python3').symlink_to('python')
    rr.uv_admission(p)
    assert calls


def test_posix_symlinked_venv_directory_fails_closed(uv_fixture):
    p,b,selected,calls = uv_fixture
    if os.name == 'nt':
        pytest.skip('POSIX fixture only')
    home = p/'.venv'
    renamed = p/'the-real-venv'
    home.rename(renamed)
    home.symlink_to(renamed, target_is_directory=True)
    with pytest.raises(rr.RuntimeMismatch, match='^VENV_REPARSE_FORBIDDEN$'):
        rr.uv_admission(p)
    assert calls == []


def test_admission_uv_call_is_cacheless_and_ignores_simulation_override(tmp_path, monkeypatch):
    """NB1: a production admission must not create a caller-chosen cache."""
    monkeypatch.setenv('HHAI_SIM_UV_CACHE_DIR', str(tmp_path / 'hostile-cache'))
    monkeypatch.setenv('UV_CACHE_DIR', str(tmp_path / 'hostile-uv-cache'))
    monkeypatch.setenv('UV_INDEX_URL', 'https://example.invalid/private')
    monkeypatch.setenv('UV_CONFIG_FILE', str(tmp_path / 'hostile-uv.toml'))
    monkeypatch.setenv('UV_NO_CACHE', '0')
    observations=[]
    def fake_run(argv, **kw):
        env = kw['env']
        observations.append((argv, env.copy()))
        assert '--no-config' in argv
        assert env['UV_OFFLINE'] == '1'
        assert env['UV_NO_CACHE'] == '1'
        assert env['UV_PYTHON_DOWNLOADS'] == 'never'
        assert 'UV_CACHE_DIR' not in env
        assert 'UV_INDEX_URL' not in env
        assert 'UV_CONFIG_FILE' not in env
        assert 'HHAI_SIM_UV_CACHE_DIR' not in env
        return subprocess.CompletedProcess(argv, 0, b'uv 0.11.32 (x86_64-unknown-linux-gnu)', b'')
    monkeypatch.setattr(rr.subprocess, 'run', fake_run)
    assert rr._uv_call('/test/uv', ['--version'], tmp_path) == 'uv 0.11.32 (x86_64-unknown-linux-gnu)'
    assert len(observations) == 1
    assert not (tmp_path / 'hostile-cache').exists()
    assert not (tmp_path / 'hostile-uv-cache').exists()


def test_admission_version_from_actual_uv_cli_is_recognized(tmp_path, monkeypatch):
    """B4: when locally available, parse uv's actual build-suffixed version."""
    uv = rr.shutil.which('uv')
    if uv is None:
        pytest.skip('uv binary not installed in sandbox')
    got = rr._uv_call(uv, ['--version'], tmp_path, output_limit=150)
    match = rr._UV_VER.fullmatch(got)
    assert match is not None and match.group(1)
