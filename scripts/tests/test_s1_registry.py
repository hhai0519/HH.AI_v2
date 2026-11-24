# -*- coding: utf-8 -*-
"""B-117 beta-1 (D8 / TD-101): positive and negative controls for scripts/s1_registry.py and CHECK 31."""
import copy
import json
from pathlib import Path
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
    assert data['by_status'] == {'fixed': 16, 'planned': 6, 'unplanned': 1, 'accepted': 2}
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
    new_doc = copy.deepcopy(base_doc)
    new_doc['causes'][0]['tasks'].append('B117-SAMPLE-R2-261121')
    new_doc['causes'][0]['confirmed'] = True
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
