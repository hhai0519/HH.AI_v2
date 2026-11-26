# -*- coding: utf-8 -*-
"""B-117 beta-1 (D8 / TD-101): positive and negative controls for scripts/s1_registry.py and CHECK 31."""
import copy
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

import s1_registry as reg  # noqa: E402


def _make_doc():
    return {
        'schema': 2,
        'updated': '2026-11-23',
        'about': 'S1 根因登記檔（schema 2）；規範見 docs/ops/d8-s1-registry.md。',
        'classes': {
            'precedence': ['A', 'B', 'D', 'C', 'E', 'F'],
            'rule': '依根因機制而非發生平台分類，優先序 A -> B -> D -> C -> E -> F。',
            'definitions': {
                'A': {'label': '時序', 'description': '牆鐘或競態'},
                'B': {'label': '預算', 'description': '第 4 關總時限'},
                'D': {'label': '輸出形式', 'description': '終端輸出隨環境變動'},
                'C': {'label': '跨平台', 'description': 'Windows 換行、編碼或路徑'},
                'E': {'label': '流程節奏', 'description': '准入與步驟時序'},
                'F': {'label': '未明', 'description': '外部網路或未明根因'},
                'UNCLASSIFIED': {'label': '未分類', 'description': '暫定草稿'},
            },
        },
        'causes': [
            {
                'id': 'S1C-001',
                'title': 'Sample cause one',
                'tasks': ['B117-SAMPLE-R1-261120'],
                'status': 'planned',
                'class': 'C',
                'plannedIn': 'B-117 G6',
                'watch': ['precommit:PRECOMMIT_NONZERO'],
                'evidence': 'sample evidence 1',
                'by': 'AUD-TEST',
                'verified': {'by': 'AUD-TEST', 'date': '2026-11-15', 'basis': 'repo main'},
                'confirmed': False,
                'todoIds': ['TD-001'],
            },
        ],
    }


def _git_init_repo(tmp_path: Path, *, commit_registry: bool = False, initial_doc=None):
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.name', 'Test'], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.email', 'test@example.test'], check=True)
    docs = repo / 'docs'
    (docs / 'governance').mkdir(parents=True)
    (docs / 'TODO-LEDGER.md').write_bytes(
        (
            '# 清冊\n'
            '| 編號 | 來源批次紀錄 | 原標籤 | 事項 | 處置 | 依據或去處 |\n'
            '|---|---|---|---|---|---|\n'
            '| TD-001 | T-1 | — | item 1 | 開放 | owner: B-117 |\n'
            '| TD-002 | T-2 | — | item 2 | 承接 | G6 |\n'
        ).encode('utf-8')
    )
    (docs / 'refactor-backlog.md').write_bytes(b'# backlog\n### 5.1 \n')
    if commit_registry:
        doc = initial_doc if initial_doc is not None else _make_doc()
        (docs / 'governance' / 's1-registry.json').write_bytes(
            (json.dumps(doc, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        )
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), 'commit', '-qm', 'base'], check=True)
    cp_oid = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    (docs / 'refactor-backlog.md').write_bytes(
        f'# backlog\n### 5.1 \n上次核對通過的 HEAD：{cp_oid}\n'.encode('utf-8')
    )
    if not commit_registry:
        doc = initial_doc if initial_doc is not None else _make_doc()
        (docs / 'governance' / 's1-registry.json').write_bytes(
            (json.dumps(doc, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        )
    return repo, cp_oid


def _write_doc(repo: Path, doc: dict) -> None:
    (repo / 'docs' / 'governance' / 's1-registry.json').write_bytes(
        (json.dumps(doc, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    )


def test_real_repo_registry_passes_check_and_summary():
    """Real migrated repo s1-registry.json passes check() and produces expected counts."""
    cand_reg = REPO_ROOT / 'docs' / 'governance' / 's1-registry.json'
    if not cand_reg.is_file():
        pytest.skip('docs/governance/s1-registry.json not present in Base prior to apply')
    fails, infos = reg.check(str(REPO_ROOT))
    assert fails == [], fails
    assert any('causes=25' in info for info in infos)
    data = reg.summary(str(REPO_ROOT), as_of='2026-11-23', compare_checkpoint=False)
    assert data['schema'] == 2
    assert data['total'] == 25
    assert data['confirmed_true'] == 4
    assert data['confirmed_false'] == 21
    assert data['by_status'] == {'fixed': 17, 'planned': 5, 'unplanned': 1, 'accepted': 2}
    reg_doc = json.loads(cand_reg.read_bytes().decode('utf-8'))
    s23 = next(c for c in reg_doc['causes'] if c['id'] == 'S1C-023')
    assert s23['status'] == 'fixed' and s23['reverseVerification']['status'] == 'not_injectable'
    assert {k: v['causes'] for k, v in data['by_class'].items()} == {
        'A': 7, 'B': 2, 'C': 8, 'D': 1, 'E': 5, 'F': 2,
    }
    assert data['unclassified'] == {'count': 0, 'ids': []}


def test_bootstrap_when_checkpoint_lacks_registry_passes_with_info(tmp_path):
    repo, _ = _git_init_repo(tmp_path, commit_registry=False)
    fails, infos = reg.check(str(repo))
    assert fails == [], fails
    assert any('略過歷史遞增比對' in i for i in infos)


def test_monotonic_allows_append_task_addition_and_confirm_promotion(tmp_path):
    base_doc = _make_doc()
    repo, _ = _git_init_repo(tmp_path, commit_registry=True, initial_doc=base_doc)
    _sample_rv_test_file(repo)
    new_doc = copy.deepcopy(base_doc)
    new_doc['causes'][0]['tasks'].append('B117-SAMPLE-R2-261121')
    new_doc['causes'][0]['confirmed'] = True
    rv2 = _valid_injectable_rv(['scripts/tests/test_sample_rv.py::test_alpha'])
    rv2['fixTask'] = 'B117-TWO-FIX-261123'
    new_doc['causes'].append({
        'id': 'S1C-002',
        'title': 'Fixed sample two',
        'tasks': ['B117-TWO-R1-261122'],
        'status': 'fixed',
        'class': 'D',
        'fixedIn': 'B117-TWO-FIX-261123',
        'fixedCommit': '1234567abcdef',
        'watch': ['push:CANDIDATE_CI_NOT_PASS'],
        'evidence': 'ci log',
        'by': 'AUD-TEST',
        'verified': {'by': 'AUD-TEST', 'date': '2026-11-22', 'basis': 'main'},
        'confirmed': True,
        'todoIds': ['TD-002'],
        'reverseVerification': rv2,
    })
    _write_doc(repo, new_doc)
    fails, infos = reg.check(str(repo))
    assert fails == [], fails
    assert any('只增不減比對完成' in i for i in infos)


def test_fail_closed_on_missing_bom_crlf_invalid_json(tmp_path):
    repo, _ = _git_init_repo(tmp_path, commit_registry=False)
    target = repo / 'docs' / 'governance' / 's1-registry.json'

    target.unlink()
    fails, _ = reg.check(str(repo))
    assert fails and '無法讀取' in fails[0]

    target.write_bytes(b'\xef\xbb\xbf{}')
    with pytest.raises(reg.RegistryError, match='含 UTF-8 BOM'):
        reg.read_text_lf(str(repo), reg.REGISTRY_REL)
    fails, _ = reg.check(str(repo))
    assert fails and '含 UTF-8 BOM' in fails[0] and 'JSON 解析失敗' not in fails[0]

    ledger = repo / 'docs' / 'TODO-LEDGER.md'
    orig_ledger = ledger.read_bytes()
    ledger.write_bytes(b'\xef\xbb\xbf' + orig_ledger)
    with pytest.raises(reg.RegistryError, match='含 UTF-8 BOM'):
        reg.read_text_lf(str(repo), reg.LEDGER_REL)
    fails_ledger, _ = reg.check(str(repo))
    assert fails_ledger and '含 UTF-8 BOM' in fails_ledger[0]
    ledger.write_bytes(orig_ledger)

    target.write_bytes(b'{\r\n}\r\n')
    fails, _ = reg.check(str(repo))
    assert fails and 'CR' in fails[0]

    target.write_bytes(b'{bad json\n')
    fails, _ = reg.check(str(repo))
    assert fails and 'JSON 解析失敗' in fails[0]


@pytest.mark.parametrize('mutator,expected_substr', [
    (lambda d: d.update({'schema': 1}), 'schema 必須為整數 2'),
    (lambda d: d.update({'schema': True}), 'schema 必須為整數 2'),
    (lambda d: d.update({'schema': '2'}), 'schema 必須為整數 2'),
    (lambda d: d.update({'schema': 2.0}), 'schema 必須為整數 2'),
    (lambda d: d.update({'extraKey': 1}), '未授權頂層欄位'),
    (lambda d: d.update({'updated': '2026-02-30'}), '不是合法日期'),
    (lambda d: d.update({'about': '格式見 app/MAINTENANCE.md'}), 'app/MAINTENANCE.md'),
    (lambda d: d.update({'about': '沒有指引路徑'}), 'docs/ops/d8-s1-registry.md'),
    (lambda d: d['classes'].update({'precedence': ['A', 'B', 'C', 'D', 'E', 'F']}), 'precedence'),
    (lambda d: d['classes']['definitions'].pop('UNCLASSIFIED'), '缺少類別定義'),
    (lambda d: d.update({'causes': []}), '非空陣列'),
])
def test_top_level_and_classes_validation_negative(tmp_path, mutator, expected_substr):
    repo, _ = _git_init_repo(tmp_path, commit_registry=False)
    doc = _make_doc()
    mutator(doc)
    _write_doc(repo, doc)
    fails, _ = reg.check(str(repo))
    assert any(expected_substr in f for f in fails), fails


@pytest.mark.parametrize('mutator,expected_substr', [
    (lambda c: c.update({'id': 'S1C-002'}), '依序無缺號為 S1C-001'),
    (lambda c: c.update({'class': 'G'}), 'class 必須為'),
    (lambda c: c.update({'class': 'C 暫定欄位'}), 'class 必須為'),
    (lambda c: c.update({'status': 'unknown'}), 'status 必須為'),
    (lambda c: c.update({'status': 'fixed'}), '必填 fixedIn'),
    (lambda c: c.update({'status': 'fixed', 'fixedIn': 'B1', 'fixedCommit': 'BADHEX!'}), 'fixedCommit'),
    (lambda c: c.pop('plannedIn'), '必填 plannedIn'),
    (lambda c: c.update({'status': 'unplanned'}), '必填合法 followUp 物件'),
    (lambda c: c.update({'followUp': 'bare string'}), '含非空 plannedIn 與 note 之物件'),
    (lambda c: c.update({'followUp': {'plannedIn': 'G6'}}), '含非空 plannedIn 與 note 之物件'),
    (lambda c: c.update({'status': 'accepted'}), '必填 reason'),
    (lambda c: c.update({'confirmed': 'false'}), '必須為布林值'),
    (lambda c: c.update({'watch': []}), 'watch 必須為非空陣列'),
    (lambda c: c.update({'watch': ['precommit:bad_lower']}), 'watch 項目格式不符'),
    (lambda c: c.update({'fixedBy': {'NONEXISTENT-TASK': 'R1'}}), 'fixedBy 之鍵必須全部屬於 tasks'),
    (lambda c: c.update({'outcomes': {'NONEXISTENT-TASK': 'PASS'}}), 'outcomes 之鍵必須全部屬於 tasks'),
    (lambda c: c.update({'distinctFrom': ['S1C-001'], 'distinctBy': 'AUD'}), '不得指向自己'),
    (lambda c: c.update({'distinctFrom': ['S1C-999'], 'distinctBy': 'AUD'}), '不存在的編號'),
    (lambda c: c.update({'todoIds': ['TD-999']}), '找不到編號：TD-999'),
    (lambda c: c.update({'todoIds': ['TD-001', 'TD-001']}), 'todoIds 不得重複'),
    (lambda c: c.update({'foo': 1}), '含有未定義欄位：foo'),
    (lambda c: c['verified'].update({'date': '2026-13-01'}), 'verified.date 不是合法日期'),
    (lambda c: c['verified'].pop('date'), 'verified.date 格式必須為 YYYY-MM-DD'),
    (lambda c: c.update({'tasks': ['B117-SAMPLE-R1-261120', 'B117-SAMPLE-R1-261120']}), 'tasks 不得重複'),
])
def test_per_cause_validation_negative(tmp_path, mutator, expected_substr):
    repo, _ = _git_init_repo(tmp_path, commit_registry=False)
    doc = _make_doc()
    mutator(doc['causes'][0])
    _write_doc(repo, doc)
    fails, _ = reg.check(str(repo))
    assert any(expected_substr in f for f in fails), fails


def test_monotonic_rejects_deleted_cause_retracted_task_and_confirmed_regression(tmp_path):
    base_doc = _make_doc()
    base_doc['causes'][0]['confirmed'] = True
    base_doc['causes'].append({
        'id': 'S1C-002',
        'title': 'Second',
        'tasks': ['T-A', 'T-B'],
        'status': 'accepted',
        'class': 'E',
        'reason': 'accepted risk',
        'watch': ['apply:APPLY_FAIL'],
        'evidence': 'ev',
        'by': 'AUD',
        'verified': {'by': 'AUD', 'date': '2026-11-20', 'basis': 'main'},
        'confirmed': False,
    })
    repo, _ = _git_init_repo(tmp_path, commit_registry=True, initial_doc=base_doc)

    # 1. Delete S1C-002 -> FAIL
    d1 = copy.deepcopy(base_doc)
    d1['causes'].pop()
    _write_doc(repo, d1)
    fails1, _ = reg.check(str(repo))
    assert any('不得刪除或撤回' in f and 'S1C-002' in f for f in fails1), fails1

    # 2. Retract T-B from S1C-002.tasks -> FAIL
    d2 = copy.deepcopy(base_doc)
    d2['causes'][1]['tasks'] = ['T-A']
    _write_doc(repo, d2)
    fails2, _ = reg.check(str(repo))
    assert any('不得撤回既有 TASK_ID：T-B' in f for f in fails2), fails2

    # 3. Regress S1C-001 confirmed true -> false -> FAIL
    d3 = copy.deepcopy(base_doc)
    d3['causes'][0]['confirmed'] = False
    _write_doc(repo, d3)
    fails3, _ = reg.check(str(repo))
    assert any('confirmed 不得由 true 退回' in f and 'S1C-001' in f for f in fails3), fails3


def test_broken_checkpoint_fails_closed(tmp_path):
    repo, _ = _git_init_repo(tmp_path, commit_registry=False)
    (repo / 'docs' / 'refactor-backlog.md').write_bytes(
        ('# backlog\n### 5.1 \n上次核對通過的 HEAD：' + '0' * 40 + '\n').encode('utf-8')
    )
    fails, _ = reg.check(str(repo))
    assert any('無法於 git 解析為 commit' in f for f in fails), fails


def test_distinct_from_requires_distinct_by(tmp_path):
    repo, _ = _git_init_repo(tmp_path, commit_registry=False)
    doc = _make_doc()
    second = copy.deepcopy(doc['causes'][0])
    second['id'] = 'S1C-002'
    second['tasks'] = ['B117-SAMPLE-R2-261121']
    doc['causes'][0]['distinctFrom'] = ['S1C-002']
    doc['causes'].append(second)
    _write_doc(repo, doc)
    fails, _ = reg.check(str(repo))
    assert len(fails) == 1 and 'distinctFrom 非空時必填 distinctBy' in fails[0], fails

    doc['causes'][0]['distinctBy'] = '   '
    _write_doc(repo, doc)
    fails_blank, _ = reg.check(str(repo))
    assert len(fails_blank) == 1 and 'distinctFrom 非空時必填 distinctBy' in fails_blank[0], fails_blank


def test_checkpoint_tree_unreadable_fails_closed(tmp_path, monkeypatch):
    repo, cp_oid = _git_init_repo(tmp_path, commit_registry=False)
    orig_git = reg._git

    def fake_git(root, *args):
        if args[:2] == ('cat-file', '-e'):
            return 1, '', 'fatal: bad tree object'
        return orig_git(root, *args)

    monkeypatch.setattr(reg, '_git', fake_git)
    with pytest.raises(reg.RegistryError, match='無法讀取 checkpoint'):
        reg.read_checkpoint_registry(str(repo), cp_oid)
    fails, infos = reg.check(str(repo))
    assert any('無法讀取 checkpoint' in f for f in fails), fails
    assert not any('ABSENT_AT_' in i for i in infos), infos


def test_duplicate_or_missing_checkpoint_line_fails_closed(tmp_path):
    repo, cp_oid = _git_init_repo(tmp_path, commit_registry=False)
    backlog = repo / 'docs' / 'refactor-backlog.md'

    backlog.write_bytes(
        (
            '# backlog\n### 5.1 \n'
            f'上次核對通過的 HEAD：{cp_oid}\n'
            f'上次核對通過的 HEAD：{cp_oid}\n'
        ).encode('utf-8')
    )
    fails_dup, _ = reg.check(str(repo))
    assert any('必須恰有一行 40 碼 hex（找到 2）' in f for f in fails_dup), fails_dup

    backlog.write_bytes(b'# backlog\n### 5.1 \n')
    fails_zero, _ = reg.check(str(repo))
    assert any('必須恰有一行 40 碼 hex（找到 0）' in f for f in fails_zero), fails_zero


def test_summary_excludes_unclassified_tracks_class_changes_and_deterministic_7d_warnings(tmp_path):
    base_doc = _make_doc()
    base_doc['causes'][0]['confirmed'] = True
    repo, _ = _git_init_repo(tmp_path, commit_registry=True, initial_doc=base_doc)

    cur_doc = copy.deepcopy(base_doc)
    cur_doc['causes'][0]['class'] = 'D'  # C -> D class change!
    cur_doc['causes'].append({
        'id': 'S1C-002',
        'title': 'Fixed old issue',
        'tasks': ['T-FIXED'],
        'status': 'fixed',
        'class': 'A',
        'fixedIn': 'B117-FIX',
        'fixedCommit': 'abcdef1',
        'watch': ['precommit:TIMEOUT'],
        'evidence': 'ev',
        'by': 'AUD',
        'verified': {'by': 'AUD', 'date': '2026-10-01', 'basis': 'main'},
        'confirmed': True,
        'reverseVerification': {
            'fixTask': 'B117-FIX',
            'injectable': False,
            'status': 'not_injectable',
            'notInjectableReason': 'legacy summary test fixture',
        },
    })
    cur_doc['causes'].append({
        'id': 'S1C-003',
        'title': 'Draft pending classification',
        'tasks': ['T-DRAFT'],
        'status': 'unplanned',
        'class': 'UNCLASSIFIED',
        'followUp': {'plannedIn': 'pending triage', 'note': 'awaiting review'},
        'watch': ['push:CI_FAIL'],
        'evidence': 'ev',
        'by': 'RUNNER',
        'verified': {'by': 'AUD', 'date': '2026-11-16', 'basis': 'main'},
        'confirmed': False,
    })
    _write_doc(repo, cur_doc)

    # Boundary: S1C-001 verified=2026-11-15, S1C-003 verified=2026-11-16
    # At 2026-11-22 (age=7 for S1C-001, age=6 for S1C-003): NONE stale! Fixed S1C-002 ignored!
    s_day7 = reg.summary(str(repo), as_of='2026-11-22')
    assert s_day7['stale_unfixed_7d'] == []
    assert s_day7['by_class']['A']['causes'] == 1
    assert s_day7['by_class']['D']['causes'] == 1
    assert s_day7['unclassified'] == {'count': 1, 'ids': ['S1C-003']}
    assert s_day7['checkpoint_compared'] is True
    assert s_day7['class_changes'] == [{'id': 'S1C-001', 'from': 'C', 'to': 'D'}]

    # At 2026-11-23 (age=8 for S1C-001, age=7 for S1C-003): S1C-001 stale ONLY!
    s_day8 = reg.summary(str(repo), as_of='2026-11-23')
    assert [x['id'] for x in s_day8['stale_unfixed_7d']] == ['S1C-001']
    assert s_day8['stale_unfixed_7d'][0]['age_days'] == 8

    # CHECK 31 must STILL PASS regardless of stale 7-day unfixed causes (deterministic CI)
    fails, _ = reg.check(str(repo))
    assert fails == [], fails


def test_cli_check_and_summary_outputs(tmp_path, capsys):
    repo, _ = _git_init_repo(tmp_path, commit_registry=True)
    assert reg.main(['check', '--repo', str(repo)]) == 0
    out_chk = capsys.readouterr().out
    assert 'S1_REGISTRY CHECK PASS' in out_chk

    assert reg.main(['summary', '--repo', str(repo), '--as-of', '2026-11-23']) == 0
    out_sum = capsys.readouterr().out
    assert 'S1_REGISTRY_SUMMARY total=1 confirmed=0/1' in out_sum
    assert 'S1_STALE_7D id=S1C-001 status=planned verified=2026-11-15 age_days=8' in out_sum


# --- Beta 2 (D4): reverseVerification schema, AST nodeid check, monotonic guard & CLI ---

def _sample_rv_test_file(repo: Path, rel: str = 'scripts/tests/test_sample_rv.py') -> Path:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(
        (
            '# -*- coding: utf-8 -*-\n'
            'def test_alpha():\n'
            '    assert True\n\n'
            'class TestSuite:\n'
            '    def test_beta(self):\n'
            '        assert True\n'
        ).encode('utf-8')
    )
    return p


def _valid_injectable_rv(nodeids=None):
    return {
        'fixTask': 'B117-BETA2-FIX-261124',
        'injectable': True,
        'injectionMethod': 'env delay injection',
        'oldResult': 'FAIL',
        'oldOutputSha256': 'a' * 64,
        'newResult': 'PASS',
        'newOutputSha256': 'b' * 64,
        'mutantResult': 'FAIL',
        'mutantOutputSha256': 'c' * 64,
        'regressionTests': nodeids or ['scripts/tests/test_sample_rv.py::test_alpha'],
    }


def test_d4_reverse_verification_injectable_and_not_injectable_valid(tmp_path):
    doc = _make_doc()
    doc['causes'][0]['reverseVerification'] = _valid_injectable_rv([
        'scripts/tests/test_sample_rv.py::test_alpha',
        'scripts/tests/test_sample_rv.py::TestSuite::test_beta',
    ])
    doc['causes'].append({
        'id': 'S1C-002',
        'title': 'Not injectable sample',
        'tasks': ['B117-NOTINJ-261124'],
        'status': 'planned',
        'class': 'F',
        'plannedIn': 'B-117',
        'watch': ['ci:TIMEOUT'],
        'evidence': 'external runner',
        'by': 'AUD',
        'verified': {'by': 'AUD', 'date': '2026-11-24', 'basis': 'main'},
        'confirmed': False,
        'reverseVerification': {
            'fixTask': 'B117-NOTINJ-261124',
            'injectable': False,
            'status': 'not_injectable',
            'notInjectableReason': 'external platform runner failure',
        },
    })
    repo, _ = _git_init_repo(tmp_path, commit_registry=False, initial_doc=doc)
    _sample_rv_test_file(repo)
    fails, _ = reg.check(str(repo))
    assert fails == [], fails


def test_d4_reverse_verification_rejects_invalid_fields_and_missing_ast_nodeids(tmp_path):
    base_doc = _make_doc()
    repo, _ = _git_init_repo(tmp_path, commit_registry=False, initial_doc=base_doc)
    _sample_rv_test_file(repo)

    bad_variants = [
        {**_valid_injectable_rv(), 'oldResult': 'PASS'},
        {**_valid_injectable_rv(), 'newResult': 'FAIL'},
        {**_valid_injectable_rv(), 'mutantResult': 'PASS'},
        {**_valid_injectable_rv(), 'oldOutputSha256': 'a' * 63},
        {**_valid_injectable_rv(), 'extraField': 1},
        {**_valid_injectable_rv(), 'regressionTests': []},
        {**_valid_injectable_rv(), 'regressionTests': ['scripts/tests/test_sample_rv.py::test_alpha', 'scripts/tests/test_sample_rv.py::test_alpha']},
        {**_valid_injectable_rv(), 'regressionTests': ['scripts/tests/test_sample_rv.py::missing_fn']},
        {**_valid_injectable_rv(), 'regressionTests': ['scripts/tests/test_sample_rv.py::TestSuite::missing_meth']},
        {**_valid_injectable_rv(), 'regressionTests': ['scripts/tests/nonexistent.py::test_alpha']},
        {'fixTask': 'B117-X-261124', 'injectable': False, 'status': 'wrong', 'notInjectableReason': 'why'},
        {'fixTask': 'B117-X-261124', 'injectable': False, 'status': 'not_injectable', 'notInjectableReason': ''},
    ]
    for rv in bad_variants:
        d = copy.deepcopy(base_doc)
        d['causes'][0]['reverseVerification'] = rv
        _write_doc(repo, d)
        fails, _ = reg.check(str(repo))
        assert fails, f'expected failure for {rv!r}'

    # Direct validate_doc check ensures duplicate regressionTests message fires cleanly (catches S11)
    d_dup = copy.deepcopy(base_doc)
    d_dup['causes'][0]['reverseVerification'] = _valid_injectable_rv([
        'scripts/tests/test_sample_rv.py::test_alpha',
        'scripts/tests/test_sample_rv.py::test_alpha',
    ])
    dup_fails = reg.validate_doc(d_dup, {'TD-001', 'TD-002'}, root_dir=str(repo))
    assert any('不得重複' in f for f in dup_fails), dup_fails

    # BOM / CR / syntax error in referenced regression test file also fails closed (BOM msg catches S7)
    bad_file = repo / 'scripts' / 'tests' / 'test_bad_rv.py'
    bad_file.write_bytes(b'\xef\xbb\xbfdef test_ok():\n    pass\n')
    d_bom = copy.deepcopy(base_doc)
    d_bom['causes'][0]['reverseVerification'] = _valid_injectable_rv(['scripts/tests/test_bad_rv.py::test_ok'])
    _write_doc(repo, d_bom)
    bom_fails, _ = reg.check(str(repo))
    assert any('UTF-8 BOM' in f for f in bom_fails), bom_fails

    bad_file.write_bytes(b'def test_ok():\r\n    pass\r\n')
    assert any('CRLF' in f or 'CR' in f for f in reg.check(str(repo))[0])

    bad_file.write_bytes(b'def broken(:\n    pass\n')
    assert any('解析失敗' in f for f in reg.check(str(repo))[0])


def test_d4_reverse_verification_rejects_symlink_test_path(tmp_path, monkeypatch):
    repo, _ = _git_init_repo(tmp_path, commit_registry=False, initial_doc=_make_doc())
    _sample_rv_test_file(repo)

    # First exercise deterministic lstat symlink guard across Windows and POSIX (catches S6)
    orig_lstat = os.lstat

    def fake_lstat(path):
        if str(path).replace('\\', '/').endswith('scripts/tests/test_sample_rv.py'):
            return type('_SymStat', (), {'st_mode': stat.S_IFLNK | 0o777, 'st_file_attributes': 0})()
        return orig_lstat(path)

    monkeypatch.setattr(reg.os, 'lstat', fake_lstat)
    doc = _make_doc()
    doc['causes'][0]['reverseVerification'] = _valid_injectable_rv(['scripts/tests/test_sample_rv.py::test_alpha'])
    _write_doc(repo, doc)
    sym_fails, _ = reg.check(str(repo))
    assert any('symlink' in f for f in sym_fails), sym_fails
    monkeypatch.undo()

    # Also test real OS symlink when platform grants privilege
    real_target = repo / 'real_target.py'
    real_target.write_bytes(b'def test_alpha():\n    pass\n')
    link_path = repo / 'scripts' / 'tests' / 'test_link_rv.py'
    try:
        os.symlink(str(real_target), str(link_path))
    except OSError:
        return
    doc2 = _make_doc()
    doc2['causes'][0]['reverseVerification'] = _valid_injectable_rv(['scripts/tests/test_link_rv.py::test_alpha'])
    _write_doc(repo, doc2)
    real_sym_fails, _ = reg.check(str(repo))
    assert any('symlink' in f for f in real_sym_fails), real_sym_fails


def test_d4_reverse_verification_monotonic_forbids_deletion_or_downgrade():
    prior = _make_doc()
    prior['causes'][0]['reverseVerification'] = _valid_injectable_rv()

    deleted = copy.deepcopy(prior)
    del deleted['causes'][0]['reverseVerification']
    assert any('reverseVerification' in f for f in reg.check_monotonic(prior, deleted))

    downgraded = copy.deepcopy(prior)
    downgraded['causes'][0]['reverseVerification'] = {
        'fixTask': 'B117-BETA2-FIX-261124',
        'injectable': False,
        'status': 'not_injectable',
        'notInjectableReason': 'downgraded',
    }
    assert any('injectable' in f for f in reg.check_monotonic(prior, downgraded))


def test_d4_cli_reverse_verify_modes_create_once_and_fail_closed(tmp_path, capsys):
    repo = tmp_path / 'rvrepo'
    _sample_rv_test_file(repo)
    out_file = tmp_path / 'rv.json'

    old_cmd = json.dumps([sys.executable, '-c', 'print("OLD_SECRET_MARKER"); raise SystemExit(1)'])
    new_cmd = json.dumps([sys.executable, '-c', 'print("NEW_SECRET_MARKER")'])
    mut_cmd = json.dumps([sys.executable, '-c', 'import sys; sys.stderr.write("MUT_ERR\\n"); raise SystemExit(2)'])

    rc = reg.main([
        'reverse-verify',
        '--repo', str(repo),
        '--fix-task', 'B117-BETA2-FIX-261124',
        '--regression-test', 'scripts/tests/test_sample_rv.py::test_alpha',
        '--injection-method', 'deterministic fault',
        '--old-cmd', old_cmd,
        '--new-cmd', new_cmd,
        '--mutant-cmd', mut_cmd,
        '--out', str(out_file),
    ])
    stdout = capsys.readouterr().out
    assert rc == 0
    assert 'S1_REVERSE_VERIFY PASS fix_task=B117-BETA2-FIX-261124 injectable=true' in stdout
    # Raw child stdout/stderr must never echo to terminal
    for secret in ('OLD_SECRET_MARKER', 'NEW_SECRET_MARKER', 'MUT_ERR'):
        assert secret not in stdout

    saved = out_file.read_bytes()
    assert not saved.startswith(b'\xef\xbb\xbf') and b'\r' not in saved
    parsed = json.loads(saved.decode('utf-8'))
    assert parsed['oldResult'] == 'FAIL' and parsed['newResult'] == 'PASS' and parsed['mutantResult'] == 'FAIL'

    # Create-once refuses overwriting existing --out file
    assert reg.main([
        'reverse-verify', '--repo', str(repo), '--fix-task', 'B117-BETA2-FIX-261124',
        '--not-injectable', '--reason', 'cannot inject', '--out', str(out_file),
    ]) == 1
    assert 'OUT_EXISTS' in capsys.readouterr().out

    # --not-injectable --json works cleanly
    assert reg.main([
        'reverse-verify', '--repo', str(repo), '--fix-task', 'B117-BETA2-FIX-261124',
        '--not-injectable', '--reason', 'platform ci flake', '--json',
    ]) == 0
    ni = json.loads(capsys.readouterr().out)
    assert ni['status'] == 'not_injectable' and ni['injectable'] is False

    # Surviving mutant fails closed
    rc_mut = reg.main([
        'reverse-verify', '--repo', str(repo), '--fix-task', 'B117-BETA2-FIX-261124',
        '--regression-test', 'scripts/tests/test_sample_rv.py::test_alpha',
        '--injection-method', 'fault',
        '--old-cmd', old_cmd, '--new-cmd', new_cmd, '--mutant-cmd', new_cmd,
    ])
    assert rc_mut == 1
    assert 'MUTANT_SURVIVED' in capsys.readouterr().out

    # Non-existent nodeid fails before executing commands
    rc_ast = reg.main([
        'reverse-verify', '--repo', str(repo), '--fix-task', 'B117-BETA2-FIX-261124',
        '--regression-test', 'scripts/tests/test_sample_rv.py::does_not_exist',
        '--injection-method', 'fault',
        '--old-cmd', new_cmd, '--new-cmd', new_cmd, '--mutant-cmd', new_cmd,
    ])
    assert rc_ast == 1
    assert 'AST_NODEID_INVALID' in capsys.readouterr().out

    # Passing old_cmd fails closed with OLD_DID_NOT_FAIL and never writes --out (catches S9)
    old_pass_out = tmp_path / 'rv_old_pass.json'
    rc_old_pass = reg.main([
        'reverse-verify', '--repo', str(repo), '--fix-task', 'B117-BETA2-FIX-261124',
        '--regression-test', 'scripts/tests/test_sample_rv.py::test_alpha',
        '--injection-method', 'fault',
        '--old-cmd', new_cmd, '--new-cmd', new_cmd, '--mutant-cmd', mut_cmd,
        '--out', str(old_pass_out),
    ])
    assert rc_old_pass == 1
    assert 'OLD_DID_NOT_FAIL' in capsys.readouterr().out
    assert not old_pass_out.exists()


def test_d4_transition_to_fixed_requires_reverse_verification_and_fix_task_match(tmp_path):
    # Base doc with S1C-001 planned and historical S1C-002 already fixed without RV
    base_doc = _make_doc()
    base_doc['causes'].append({
        'id': 'S1C-002',
        'title': 'Historical fixed cause',
        'tasks': ['B117-HIST-261110'],
        'status': 'fixed',
        'class': 'C',
        'fixedIn': 'B117-HIST-FIX-261111',
        'fixedCommit': '1234567abcdef',
        'watch': ['precommit:GATE4'],
        'evidence': 'hist',
        'by': 'AUD-TEST',
        'verified': {'by': 'AUD-TEST', 'date': '2026-11-11', 'basis': 'main'},
        'confirmed': True,
    })
    repo, _ = _git_init_repo(tmp_path, commit_registry=True, initial_doc=base_doc)
    _sample_rv_test_file(repo)

    # Exempt historical fixed cause remains allowed without RV when unchanged
    _write_doc(repo, base_doc)
    assert reg.check(str(repo))[0] == []

    # Transitioning S1C-001 planned -> fixed WITHOUT reverseVerification must FAIL (B2)
    no_rv = copy.deepcopy(base_doc)
    no_rv['causes'][0]['status'] = 'fixed'
    no_rv['causes'][0]['fixedIn'] = 'B117-FAKE-FIX-261125'
    no_rv['causes'][0]['fixedCommit'] = 'a' * 40
    _write_doc(repo, no_rv)
    fails_no_rv, _ = reg.check(str(repo))
    assert any('必須附帶合法 reverseVerification' in f for f in fails_no_rv), fails_no_rv

    # Transitioning planned -> fixed WITH mismatched fixTask != fixedIn must FAIL
    bad_ft = copy.deepcopy(no_rv)
    bad_ft['causes'][0]['reverseVerification'] = _valid_injectable_rv()  # fixTask='B117-BETA2-FIX-261124'
    _write_doc(repo, bad_ft)
    fails_ft, _ = reg.check(str(repo))
    assert any('fixTask' in f and 'fixedIn' in f for f in fails_ft), fails_ft

    # Adding new fixed cause without RV must ALSO FAIL
    added_no_rv = copy.deepcopy(base_doc)
    added_no_rv['causes'].append({
        'id': 'S1C-003',
        'title': 'Added fixed without RV',
        'tasks': ['B117-NEW-261124'],
        'status': 'fixed',
        'class': 'A',
        'fixedIn': 'B117-NEW-FIX-261124',
        'fixedCommit': 'b' * 40,
        'watch': ['precommit:PRECOMMIT_NONZERO'],
        'evidence': 'new',
        'by': 'AUD-TEST',
        'verified': {'by': 'AUD-TEST', 'date': '2026-11-24', 'basis': 'main'},
        'confirmed': True,
    })
    _write_doc(repo, added_no_rv)
    fails_add, _ = reg.check(str(repo))
    assert any('S1C-003' in f and '必須附帶合法 reverseVerification' in f for f in fails_add), fails_add

    # Both injectable and not_injectable with fixTask == fixedIn PASS
    ok_inj = copy.deepcopy(no_rv)
    rv_ok = _valid_injectable_rv(['scripts/tests/test_sample_rv.py::test_alpha'])
    rv_ok['fixTask'] = 'B117-FAKE-FIX-261125'
    ok_inj['causes'][0]['reverseVerification'] = rv_ok
    _write_doc(repo, ok_inj)
    assert reg.check(str(repo))[0] == []

    ok_ni = copy.deepcopy(no_rv)
    ok_ni['causes'][0]['reverseVerification'] = {
        'fixTask': 'B117-FAKE-FIX-261125',
        'injectable': False,
        'status': 'not_injectable',
        'notInjectableReason': 'external ci outage',
    }
    _write_doc(repo, ok_ni)
    assert reg.check(str(repo))[0] == []


def test_d4_reverse_verification_monotonic_locks_fix_task_tests_and_shas():
    prior = _make_doc()
    prior['causes'][0]['status'] = 'fixed'
    prior['causes'][0]['fixedIn'] = 'B117-BETA2-FIX-261124'
    prior['causes'][0]['fixedCommit'] = 'a' * 40
    prior['causes'][0].pop('plannedIn', None)
    prior['causes'][0]['reverseVerification'] = _valid_injectable_rv([
        'scripts/tests/test_sample_rv.py::test_alpha',
        'scripts/tests/test_sample_rv.py::TestSuite::test_beta',
    ])

    # Superset regressionTests is allowed
    expanded = copy.deepcopy(prior)
    expanded['causes'][0]['reverseVerification']['regressionTests'].append('scripts/tests/test_sample_rv.py::test_gamma')
    assert reg.check_monotonic(prior, expanded) == []

    # Shrinking regressionTests is blocked (N2)
    shrunk = copy.deepcopy(prior)
    shrunk['causes'][0]['reverseVerification']['regressionTests'] = ['scripts/tests/test_sample_rv.py::test_alpha']
    assert any('regressionTests 不得縮減' in f for f in reg.check_monotonic(prior, shrunk))

    # Changing fixTask when remaining fixed is blocked (N2)
    changed_ft = copy.deepcopy(prior)
    changed_ft['causes'][0]['reverseVerification']['fixTask'] = 'B117-OTHER-FIX-261125'
    assert any('reverseVerification.fixTask' in f and '不得變更' in f for f in reg.check_monotonic(prior, changed_ft))

    # Changing fixTask or SHAs when reopening (fixed -> planned) is also blocked
    reopened_bad_ft = copy.deepcopy(prior)
    reopened_bad_ft['causes'][0]['status'] = 'planned'
    reopened_bad_ft['causes'][0]['plannedIn'] = 'B117-REOPEN-261125'
    reopened_bad_ft['causes'][0].pop('fixedIn', None)
    reopened_bad_ft['causes'][0].pop('fixedCommit', None)
    reopened_bad_ft['causes'][0]['reverseVerification']['fixTask'] = 'B117-OTHER-FIX-261125'
    assert any('reverseVerification.fixTask' in f and '不得變更' in f for f in reg.check_monotonic(prior, reopened_bad_ft))

    # Changing any of the 3 output SHAs when remaining fixed or reopening is blocked (N2)
    for sha_k in ('oldOutputSha256', 'newOutputSha256', 'mutantOutputSha256'):
        changed_sha = copy.deepcopy(prior)
        changed_sha['causes'][0]['reverseVerification'][sha_k] = 'f' * 64
        assert any(sha_k in f and '不得變更' in f for f in reg.check_monotonic(prior, changed_sha)), sha_k
        reopened_bad_sha = copy.deepcopy(prior)
        reopened_bad_sha['causes'][0]['status'] = 'planned'
        reopened_bad_sha['causes'][0]['plannedIn'] = 'B117-REOPEN-261125'
        reopened_bad_sha['causes'][0].pop('fixedIn', None)
        reopened_bad_sha['causes'][0].pop('fixedCommit', None)
        reopened_bad_sha['causes'][0]['reverseVerification'][sha_k] = 'f' * 64
        assert any(sha_k in f and '不得變更' in f for f in reg.check_monotonic(prior, reopened_bad_sha)), sha_k


def test_d4_reopened_cause_refix_allows_new_rv_and_enforces_b2_and_regression_subset():
    base_doc = _make_doc()
    s1 = copy.deepcopy(base_doc)
    c1 = s1['causes'][0]
    c1['status'] = 'fixed'
    c1['fixedIn'] = 'B117-FIX-X-R1-261125'
    c1['fixedCommit'] = 'a' * 40
    c1.pop('plannedIn', None)
    rv_x = _valid_injectable_rv(['scripts/tests/test_sample_rv.py::test_alpha'])
    rv_x['fixTask'] = 'B117-FIX-X-R1-261125'
    c1['reverseVerification'] = rv_x
    assert reg.check_monotonic(base_doc, s1) == []

    # Reopen (fixed -> planned) preserving RV passes
    s2 = copy.deepcopy(s1)
    c2 = s2['causes'][0]
    c2['status'] = 'planned'
    c2['plannedIn'] = 'B117-FIX-Y'
    c2.pop('fixedIn', None)
    c2.pop('fixedCommit', None)
    assert reg.check_monotonic(s1, s2) == []

    # Re-fix in Y while keeping stale fixTask=X is rejected by B2 (fixTask == fixedIn)
    s3_stale = copy.deepcopy(s2)
    c3_stale = s3_stale['causes'][0]
    c3_stale['status'] = 'fixed'
    c3_stale['fixedIn'] = 'B117-FIX-Y-R1-261128'
    c3_stale['fixedCommit'] = 'b' * 40
    c3_stale.pop('plannedIn', None)
    fails_stale = reg.check_monotonic(s2, s3_stale)
    assert any('fixTask' in f and 'fixedIn' in f for f in fails_stale), fails_stale

    # Re-fix in Y with updated fixTask=Y, updated 3 SHAs, and superset regressionTests passes
    s3_ok = copy.deepcopy(s3_stale)
    s3_ok['causes'][0]['reverseVerification'] = {
        'fixTask': 'B117-FIX-Y-R1-261128',
        'injectable': True,
        'injectionMethod': 'new fault injection',
        'oldResult': 'FAIL',
        'oldOutputSha256': 'd' * 64,
        'newResult': 'PASS',
        'newOutputSha256': 'e' * 64,
        'mutantResult': 'FAIL',
        'mutantOutputSha256': 'f' * 64,
        'regressionTests': [
            'scripts/tests/test_sample_rv.py::test_alpha',
            'scripts/tests/test_sample_rv.py::TestSuite::test_beta',
        ],
    }
    assert reg.check_monotonic(s2, s3_ok) == []

    # Re-fix in Y cannot shrink prior regressionTests, downgrade injectable, or delete RV
    s3_shrunk = copy.deepcopy(s3_ok)
    s3_shrunk['causes'][0]['reverseVerification']['regressionTests'] = [
        'scripts/tests/test_sample_rv.py::TestSuite::test_beta',
    ]
    assert any('regressionTests 不得縮減' in f for f in reg.check_monotonic(s2, s3_shrunk))

    s3_downgraded = copy.deepcopy(s3_ok)
    s3_downgraded['causes'][0]['reverseVerification'] = {
        'fixTask': 'B117-FIX-Y-R1-261128',
        'injectable': False,
        'status': 'not_injectable',
        'notInjectableReason': 'downgraded during refix',
    }
    assert any('injectable' in f for f in reg.check_monotonic(s2, s3_downgraded))

    s3_deleted = copy.deepcopy(s3_ok)
    del s3_deleted['causes'][0]['reverseVerification']
    assert any('reverseVerification 已建立' in f for f in reg.check_monotonic(s2, s3_deleted))

    # Not-injectable -> reopen -> re-fix in Y also matches SO's so_reopen_conflict workflow
    ni_1 = copy.deepcopy(base_doc)
    ni_1['causes'][0]['status'] = 'fixed'
    ni_1['causes'][0]['fixedIn'] = 'B117-FIX-X-R1-261125'
    ni_1['causes'][0]['fixedCommit'] = 'a' * 40
    ni_1['causes'][0].pop('plannedIn', None)
    ni_1['causes'][0]['reverseVerification'] = {
        'fixTask': 'B117-FIX-X-R1-261125',
        'injectable': False,
        'status': 'not_injectable',
        'notInjectableReason': 'demo',
    }
    ni_2 = copy.deepcopy(ni_1)
    ni_2['causes'][0]['status'] = 'planned'
    ni_2['causes'][0]['plannedIn'] = 'B117-FIX-Y'
    ni_2['causes'][0].pop('fixedIn', None)
    ni_2['causes'][0].pop('fixedCommit', None)
    assert reg.check_monotonic(ni_1, ni_2) == []

    ni_3_ok = copy.deepcopy(ni_2)
    ni_3_ok['causes'][0]['status'] = 'fixed'
    ni_3_ok['causes'][0]['fixedIn'] = 'B117-FIX-Y-R1-261128'
    ni_3_ok['causes'][0]['fixedCommit'] = 'b' * 40
    ni_3_ok['causes'][0].pop('plannedIn', None)
    ni_3_ok['causes'][0]['reverseVerification']['fixTask'] = 'B117-FIX-Y-R1-261128'
    assert reg.check_monotonic(ni_2, ni_3_ok) == []

    ni_3_stale = copy.deepcopy(ni_3_ok)
    ni_3_stale['causes'][0]['reverseVerification']['fixTask'] = 'B117-FIX-X-R1-261125'
    assert any('fixTask' in f and 'fixedIn' in f for f in reg.check_monotonic(ni_2, ni_3_stale))


def test_d4_inbatch_refix_stale_fix_task_rejected():
    base_doc = _make_doc()
    prior_inj = copy.deepcopy(base_doc)
    c0 = prior_inj['causes'][0]
    c0['status'] = 'fixed'
    c0['fixedIn'] = 'B117-FIX-X-R1-261125'
    c0['fixedCommit'] = 'a' * 40
    c0.pop('plannedIn', None)
    rv_x = _valid_injectable_rv(['scripts/tests/test_sample_rv.py::test_alpha'])
    rv_x['fixTask'] = 'B117-FIX-X-R1-261125'
    c0['reverseVerification'] = rv_x

    cur_inj_stale = copy.deepcopy(prior_inj)
    cur_inj_stale['causes'][0]['fixedIn'] = 'B117-FIX-Z-R1-261129'
    cur_inj_stale['causes'][0]['fixedCommit'] = 'c' * 40
    fails_inj = reg.check_monotonic(prior_inj, cur_inj_stale)
    assert any('fixTask' in f and 'fixedIn' in f for f in fails_inj), fails_inj

    prior_ni = copy.deepcopy(prior_inj)
    prior_ni['causes'][0]['reverseVerification'] = {
        'fixTask': 'B117-FIX-X-R1-261125',
        'injectable': False,
        'status': 'not_injectable',
        'notInjectableReason': 'demo X',
    }
    cur_ni_stale = copy.deepcopy(prior_ni)
    cur_ni_stale['causes'][0]['fixedIn'] = 'B117-FIX-Z-R1-261129'
    cur_ni_stale['causes'][0]['fixedCommit'] = 'c' * 40
    fails_ni = reg.check_monotonic(prior_ni, cur_ni_stale)
    assert any('fixTask' in f and 'fixedIn' in f for f in fails_ni), fails_ni


def test_d4_inbatch_refix_new_rv_with_superset_tests_passes_and_keeps_guards():
    base_doc = _make_doc()
    prior_inj = copy.deepcopy(base_doc)
    c0 = prior_inj['causes'][0]
    c0['status'] = 'fixed'
    c0['fixedIn'] = 'B117-FIX-X-R1-261125'
    c0['fixedCommit'] = 'a' * 40
    c0.pop('plannedIn', None)
    rv_x = _valid_injectable_rv(['scripts/tests/test_sample_rv.py::test_alpha'])
    rv_x['fixTask'] = 'B117-FIX-X-R1-261125'
    c0['reverseVerification'] = rv_x

    cur_ok = copy.deepcopy(prior_inj)
    cur_ok['causes'][0]['fixedIn'] = 'B117-FIX-Z-R1-261129'
    cur_ok['causes'][0]['fixedCommit'] = 'c' * 40
    cur_ok['causes'][0]['reverseVerification'] = {
        'fixTask': 'B117-FIX-Z-R1-261129',
        'injectable': True,
        'injectionMethod': 'in-batch refix fault injection',
        'oldResult': 'FAIL',
        'oldOutputSha256': 'd' * 64,
        'newResult': 'PASS',
        'newOutputSha256': 'e' * 64,
        'mutantResult': 'FAIL',
        'mutantOutputSha256': 'f' * 64,
        'regressionTests': [
            'scripts/tests/test_sample_rv.py::test_alpha',
            'scripts/tests/test_sample_rv.py::TestSuite::test_beta',
        ],
    }
    assert reg.check_monotonic(prior_inj, cur_ok) == []

    prior_ni = copy.deepcopy(prior_inj)
    prior_ni['causes'][0]['reverseVerification'] = {
        'fixTask': 'B117-FIX-X-R1-261125',
        'injectable': False,
        'status': 'not_injectable',
        'notInjectableReason': 'demo X',
    }
    cur_ni_ok = copy.deepcopy(prior_ni)
    cur_ni_ok['causes'][0]['fixedIn'] = 'B117-FIX-Z-R1-261129'
    cur_ni_ok['causes'][0]['fixedCommit'] = 'c' * 40
    cur_ni_ok['causes'][0]['reverseVerification'] = {
        'fixTask': 'B117-FIX-Z-R1-261129',
        'injectable': False,
        'status': 'not_injectable',
        'notInjectableReason': 'demo Z',
    }
    assert reg.check_monotonic(prior_ni, cur_ni_ok) == []

    cur_shrunk = copy.deepcopy(cur_ok)
    cur_shrunk['causes'][0]['reverseVerification']['regressionTests'] = [
        'scripts/tests/test_sample_rv.py::TestSuite::test_beta',
    ]
    assert any('regressionTests 不得縮減' in f for f in reg.check_monotonic(prior_inj, cur_shrunk))

    cur_downgraded = copy.deepcopy(cur_ok)
    cur_downgraded['causes'][0]['reverseVerification'] = {
        'fixTask': 'B117-FIX-Z-R1-261129',
        'injectable': False,
        'status': 'not_injectable',
        'notInjectableReason': 'downgraded on in-batch refix',
    }
    assert any('injectable' in f for f in reg.check_monotonic(prior_inj, cur_downgraded))

    cur_deleted = copy.deepcopy(cur_ok)
    del cur_deleted['causes'][0]['reverseVerification']
    assert any('reverseVerification 已建立' in f for f in reg.check_monotonic(prior_inj, cur_deleted))


def test_d4_inbatch_refix_historical_fixed_without_rv_requires_rv():
    base_doc = _make_doc()
    prior_hist = copy.deepcopy(base_doc)
    c0 = prior_hist['causes'][0]
    c0['status'] = 'fixed'
    c0['fixedIn'] = 'B117-FIX-X-R1-261125'
    c0['fixedCommit'] = 'a' * 40
    c0.pop('plannedIn', None)
    c0.pop('reverseVerification', None)

    same_hist = copy.deepcopy(prior_hist)
    assert reg.check_monotonic(prior_hist, same_hist) == []

    cur_no_rv = copy.deepcopy(prior_hist)
    cur_no_rv['causes'][0]['fixedIn'] = 'B117-FIX-Z-R1-261129'
    cur_no_rv['causes'][0]['fixedCommit'] = 'c' * 40
    fails_no_rv = reg.check_monotonic(prior_hist, cur_no_rv)
    assert any('必須附帶合法 reverseVerification' in f for f in fails_no_rv), fails_no_rv

    cur_bad_ft = copy.deepcopy(cur_no_rv)
    rv_bad = _valid_injectable_rv(['scripts/tests/test_sample_rv.py::test_alpha'])
    rv_bad['fixTask'] = 'B117-FIX-X-R1-261125'
    cur_bad_ft['causes'][0]['reverseVerification'] = rv_bad
    fails_bad_ft = reg.check_monotonic(prior_hist, cur_bad_ft)
    assert any('fixTask' in f and 'fixedIn' in f for f in fails_bad_ft), fails_bad_ft

    cur_ok_inj = copy.deepcopy(cur_no_rv)
    rv_z = _valid_injectable_rv(['scripts/tests/test_sample_rv.py::test_alpha'])
    rv_z['fixTask'] = 'B117-FIX-Z-R1-261129'
    cur_ok_inj['causes'][0]['reverseVerification'] = rv_z
    assert reg.check_monotonic(prior_hist, cur_ok_inj) == []

    cur_ok_ni = copy.deepcopy(cur_no_rv)
    cur_ok_ni['causes'][0]['reverseVerification'] = {
        'fixTask': 'B117-FIX-Z-R1-261129',
        'injectable': False,
        'status': 'not_injectable',
        'notInjectableReason': 'historical refix non-injectable',
    }
    assert reg.check_monotonic(prior_hist, cur_ok_ni) == []


def test_d4_same_fixed_in_fixed_to_fixed_still_locks_fix_task_and_shas():
    base_doc = _make_doc()
    prior = copy.deepcopy(base_doc)
    c0 = prior['causes'][0]
    c0['status'] = 'fixed'
    c0['fixedIn'] = 'B117-FIX-X-R1-261125'
    c0['fixedCommit'] = 'a' * 40
    c0.pop('plannedIn', None)
    rv_x = _valid_injectable_rv(['scripts/tests/test_sample_rv.py::test_alpha'])
    rv_x['fixTask'] = 'B117-FIX-X-R1-261125'
    c0['reverseVerification'] = rv_x

    bad_ft = copy.deepcopy(prior)
    bad_ft['causes'][0]['reverseVerification']['fixTask'] = 'B117-FIX-Z-R1-261129'
    fails_ft = reg.check_monotonic(prior, bad_ft)
    assert any('reverseVerification.fixTask' in f and '不得變更' in f for f in fails_ft), fails_ft

    for sha_k in ('oldOutputSha256', 'newOutputSha256', 'mutantOutputSha256'):
        bad_sha = copy.deepcopy(prior)
        bad_sha['causes'][0]['reverseVerification'][sha_k] = 'f' * 64
        fails_sha = reg.check_monotonic(prior, bad_sha)
        assert any(sha_k in f and '不得變更' in f for f in fails_sha), (sha_k, fails_sha)
