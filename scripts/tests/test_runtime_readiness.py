# -*- coding: utf-8 -*-
"""G5 fail-closed version-source controls; no git mutation or package install."""
import json
import os
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import runtime_readiness as rr  # noqa: E402
import batch_runner as br  # noqa: E402


def fixture(tmp_path):
    (tmp_path / 'requirements.txt').write_text('pytest==9.1.1\n', encoding='utf-8')
    (tmp_path / '.nvmrc').write_text('24.21.0\n', encoding='utf-8')
    pkg = tmp_path / 'runtime' / 'channel-gateway' / 'package.json'
    pkg.parent.mkdir(parents=True)
    pkg.write_text(json.dumps({'engines': {'node': '>=24.15.0 <25'}}), encoding='utf-8')
    return tmp_path


def simulate(monkeypatch, py='pytest 9.1.1', node='v24.21.0', path='C:/Tools/node.exe'):
    calls = []
    monkeypatch.setattr(rr.shutil, 'which', lambda name: path)
    def invoke(argv, **kwargs):
        calls.append(tuple(argv))
        return py if argv[1:] == ['-m', 'pytest', '--version'] else node
    monkeypatch.setattr(rr, '_invoke', invoke)
    return calls


def test_current_pinned_versions_accept(monkeypatch, tmp_path):
    f = fixture(tmp_path)
    calls = simulate(monkeypatch)
    value = rr.check(f)
    assert value['pytest'] == '9.1.1' and value['node'] == 'v24.21.0'
    assert calls[0] == (sys.executable, '-m', 'pytest', '--version')
    assert calls[1] == ('C:/Tools/node.exe', '--version')


@pytest.mark.parametrize('py,node,path,kind', [
    ('pytest 9.0.2', 'v24.21.0', 'C:/Tools/node.exe', 'PYTEST_MISMATCH'),
    ('no module named pytest', 'v24.21.0', 'C:/Tools/node.exe', 'PYTEST_MISMATCH'),
    ('pytest 9.1.1', 'v24.20.9', 'C:/Tools/node.exe', 'NODE_RANGE_MISMATCH'),
    ('pytest 9.1.1', 'v26.12.1', 'C:/Tools/node.exe', 'NODE_RANGE_MISMATCH'),
    ('pytest 9.1.1', 'v24.21.0', None, 'NODE_MISSING'),
    ('pytest 9.1.1', 'v24.21.0', 'C:/WindowsApps/node.exe', 'NODE_ALIAS_FORBIDDEN'),
    ('pytest 9.1.1', 'bad', 'C:/Tools/node.exe', 'NODE_VERSION_INVALID'),
])
def test_runtime_negative(monkeypatch,tmp_path,py,node,path,kind):
    f=fixture(tmp_path)
    simulate(monkeypatch,py,node,path)
    with pytest.raises(rr.RuntimeMismatch) as e:
        rr.check(f)
    assert str(e.value)==kind


def test_multiple_python_path_uses_running_interpreter(monkeypatch,tmp_path):
    f=fixture(tmp_path)
    monkeypatch.setenv('PATH','C:/WindowsApps;C:/Python315;C:/Toolchain')
    calls=simulate(monkeypatch)
    rr.check(f)
    assert calls[0][0]==sys.executable  # never chooses arbitrary PATH python


@pytest.mark.parametrize('invalid', [
    '>=24.15.0 || >=26.0.0', '^24.15.0', '>=24.15.0 <N', '*', '',
])
def test_unknown_engine_ranges_fail_closed(monkeypatch,tmp_path,invalid):
    f=fixture(tmp_path)
    p=f/'runtime/channel-gateway/package.json'
    p.write_text(json.dumps({'engines':{'node':invalid}}),encoding='utf-8')
    simulate(monkeypatch)
    with pytest.raises(rr.RuntimeMismatch) as e:
        rr.check(f)
    assert str(e.value)=='ENGINES_UNSUPPORTED'


def test_future_upper_bound_removed_supports_node26(monkeypatch,tmp_path):
    f=fixture(tmp_path)
    (f/'runtime/channel-gateway/package.json').write_text(
        json.dumps({'engines':{'node':'>=24.15.0'}}),encoding='utf-8')
    simulate(monkeypatch,node='v26.12.1')
    assert rr.check(f)['node']=='v26.12.1'


def test_missing_pytest_pin_and_malformed_nvmrc(monkeypatch,tmp_path):
    f=fixture(tmp_path)
    simulate(monkeypatch)
    (f/'requirements.txt').write_text('pytest>=9\n',encoding='utf-8')
    with pytest.raises(rr.RuntimeMismatch,match='PYTEST_PIN_INVALID'):
        rr.check(f)
    (f/'requirements.txt').write_text('pytest==9.1.1\n',encoding='utf-8')
    (f/'.nvmrc').write_text('24',encoding='utf-8')
    with pytest.raises(rr.RuntimeMismatch,match='NVMRC_INVALID'):
        rr.check(f)


def test_runner_precontrol_is_before_any_control_artifact(monkeypatch,tmp_path):
    # Main routes a precontrol runtime failure to S1 without creating control.
    root=tmp_path
    (root/'scripts').mkdir()
    (root/'.git').mkdir()
    (root/'scripts/batch_runner.py').write_text('# synthetic\n')
    calls=[]
    class FakeBatch:
        def __init__(self,root,task_id):
            self.root,self.task_id=root,task_id
            self.spec={'kind':'production','e24':False,'focused':None,'base_oid':'a'*40,
                       'start':{'mode':'clean'},'branch':'batch/test'}
            self.prompt_bytes=b'proof'
        def write_new_artifact(self,*args):
            calls.append('write')
            raise AssertionError('runtime mismatch may not create a control')
    monkeypatch.setattr(br,'Batch',FakeBatch)
    monkeypatch.setattr(br,'load_control',lambda batch: None)
    monkeypatch.setattr(br.Path,'cwd',lambda:root)
    monkeypatch.setattr(br,'__file__',str(root/'scripts/batch_runner.py'))
    monkeypatch.setattr(br,'precontrol_start_guard',lambda batch: (_ for _ in ()).throw(br.Halt('RUNTIME_MISMATCH')))
    assert br.main(['--task-id','G5-SYNTHETIC','preflight'])==1
    assert calls==[]
    assert not list((root/'.git').iterdir())


def test_python_store_alias_is_rejected(monkeypatch,tmp_path):
    f=fixture(tmp_path)
    simulate(monkeypatch)
    monkeypatch.setattr(rr.sys,'executable',r'C:\Users\who\AppData\Local\Microsoft\WindowsApps\python.exe')
    with pytest.raises(rr.RuntimeMismatch,match='PYTHON_ALIAS_FORBIDDEN'):
        rr.check(f)


def test_install_manager_active_python_without_pytest_rejected(monkeypatch,tmp_path):
    f=fixture(tmp_path)
    calls=simulate(monkeypatch,py='No module named pytest')
    monkeypatch.setattr(rr.sys,'executable',r'C:\Users\who\AppData\Local\Python\bin\python.exe')
    with pytest.raises(rr.RuntimeMismatch,match='PYTEST_MISMATCH'):
        rr.check(f)
    assert calls[0][0].endswith('Python\\bin\\python.exe')


def test_pytest_plugin_and_pycache_are_disabled(monkeypatch):
    seen=[]
    class Result:
        returncode=0
        stdout=b'pytest 9.1.1\n'
        stderr=b''
    def runner(*args,**kw):
        seen.append(kw)
        return Result()
    monkeypatch.setattr(rr.subprocess,'run',runner)
    assert rr._invoke([sys.executable,'-m','pytest','--version']) == 'pytest 9.1.1'
    assert seen[0]['env']['PYTHONDONTWRITEBYTECODE'] == '1'
    assert seen[0]['env']['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] == '1'


def test_extra_pytest_plugin_does_not_make_pin_ambiguous(tmp_path):
    f=fixture(tmp_path)
    (f/'requirements.txt').write_text('pytest==9.1.1\npytest-cov==6.0.0\n',encoding='utf-8')
    assert rr._pins(f)[0] == '9.1.1'


def test_missing_pytest_reports_fixed_reason_without_leaking_stderr(monkeypatch):
    class Missing:
        returncode=1
        stdout=b''
        stderr=b'C:\\Python315\\python.exe: No module named pytest\\n'
    monkeypatch.setattr(rr.subprocess,'run',lambda *args,**kwargs: Missing())
    with pytest.raises(rr.RuntimeMismatch,match='^PYTEST_UNAVAILABLE$'):
        rr._invoke([sys.executable,'-m','pytest','--version'],pytest_probe=True)
    with pytest.raises(rr.RuntimeMismatch,match='^PROCESS_NONZERO$'):
        rr._invoke(['node','--version'])

def test_other_pytest_nonzero_not_falsely_called_missing(monkeypatch):
    class Failure:
        returncode=2
        stdout=b''
        stderr=b'import error from plugins\n'
    monkeypatch.setattr(rr.subprocess,'run',lambda *args,**kwargs: Failure())
    with pytest.raises(rr.RuntimeMismatch,match='^PROCESS_NONZERO$'):
        rr._invoke([sys.executable,'-m','pytest','--version'],pytest_probe=True)
