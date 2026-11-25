# -*- coding: utf-8 -*-
"""G7-b3b3-2 guards: CHECK 32, TD-106 inheritance targets, TD-107 review dates & reminder, TD-108 append-only open basis."""

import hashlib
import itertools
import json
import os
import re
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import check_consistency as cc
import taskboard_archive as ta

LEDGER_ANCHOR = ta.LEDGER_ANCHOR
V2_ANCHOR = ta.LEDGER_V2_ANCHOR
ONE_LINER_ANCHOR = ta.ONE_LINER_ANCHOR
VALID_ONE_LINER = '一句話：驗證器與狀態整理通過測試。'


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8')
    if proc.returncode != 0:
        raise RuntimeError(f'git {args}: {proc.stderr}')
    return proc.stdout.strip()


def _write_lf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace('\r\n', '\n').encode('utf-8'))


def _rec_block(task_id: str, extra_body: str = '') -> str:
    return (
        f'**批次紀錄（2026-11-24；本批 {task_id}）**：{VALID_ONE_LINER}'
        f'摘要內容。{extra_body}新增待辦：無。'
    )


def _row_line(rid: str, status: str = '待辦', title: str = '標題', notes: str = '細節內容') -> str:
    return f'| {rid} | {status} | {title} | {notes} |'


def _ledger_doc(rows_lines: list[str]) -> str:
    head = [
        '# 待辦清冊',
        '| 編號 | 來源批次紀錄 | 原標籤 | 事項 | 處置 | 依據或去處 |',
        '|---|---|---|---|---|---|',
    ]
    return '\n'.join(head + rows_lines) + '\n'


def _init_repo(
    tmp_path: Path,
    *,
    monkeypatch=None,
    board_rows: list[str] | None = None,
    ledger_rows: list[str] | None = None,
    include_v2_anchor: bool = True,
    extra_board_sections: str = '',
) -> tuple[Path, str]:
    if monkeypatch is not None:
        monkeypatch.setattr(ta, 'RECORD_ARCHIVES_MIN', 0)
        monkeypatch.setattr(ta, 'FIRST_ARCHIVE_SHA256', None)
    root = tmp_path / 'repo'
    root.mkdir(parents=True, exist_ok=True)
    _git(root, 'init', '-q')
    _git(root, 'config', 'user.name', 'B3B3-2')
    _git(root, 'config', 'user.email', 'b3b3_2@example.test')

    if board_rows is None:
        board_rows = [
            _row_line('G5', 'OPEN', '執行器', 'STEP_IN_PROGRESS 行為與重跑上限'),
            _row_line('G6', 'OPEN', 'Windows CI', '事件先後斷言與穩定性'),
            _row_line('G7', 'OPEN', '看板治理', 'G7-c 與 G7-d 後續推進'),
            _row_line('B-112', '待辦', '排程', '待辦項目細節說明'),
            _row_line('B-107', '已完成', '歷史長列', '證據提交紀錄'),
        ]
    recs = (
        [_rec_block(V2_ANCHOR), _rec_block(LEDGER_ANCHOR)]
        if include_v2_anchor
        else [_rec_block('B117-D9-GATE4-GROUPS-R2-261121'), _rec_block(LEDGER_ANCHOR)]
    )
    if ledger_rows is None:
        ledger_rows = [
            '| TD-001 | ' + LEDGER_ANCHOR + ' | lbl | 承接項 | 承接 | 原說明；承接位置：ROW:G5「STEP_IN_PROGRESS」 |',
            '| TD-002 | ' + LEDGER_ANCHOR + ' | lbl | 開放項 | 開放 | owner：G3；複查日 2026-12-15 |',
            '| TD-003 | ' + LEDGER_ANCHOR + ' | lbl | 已結項 | 結案 | 2026-11-20 已結案 |',
        ]

    board_text = '\n'.join([
        '# 任務看板',
        '## G. 治理完成線',
        '| ID | 狀態 | 項目 | 說明 |',
        '|---|---|---|---|',
        *[r for r in board_rows if r.startswith('| G')],
        '',
        '## B. 重構主線',
        '| ID | 狀態 | 項目 | 備註 |',
        '|---|---|---|---|',
        *[r for r in board_rows if not r.startswith('| G')],
        '',
        '## 看板規劃（BOARD_PLAN_MARKER_ANCHOR）',
        '目前最新批次紀錄（保留此處）：',
        *recs,
        '',
        extra_board_sections,
        '## 封存區',
        '已移到 docs/archive/TASKBOARD-ARCHIVE-0001.md',
        '| B-999 | 待辦 | archived | ARCHIVE_ONLY_ANCHOR_TEXT |',
        '',
    ])
    manifest = {
        'schema_version': 1,
        'user_keep': [],
        'archives': [],
        'record_archives': [],
    }
    _write_lf(root / 'docs' / 'TASKBOARD.md', board_text)
    _write_lf(root / 'docs' / 'TODO-LEDGER.md', _ledger_doc(ledger_rows))
    _write_lf(root / 'docs' / 'AUDIT-LOG.md', '| commit | date | rule | verdict | note |\n|---|---|---|---|---|\n')
    _write_lf(root / 'docs' / 'EXEC-LOG.md', '| commit | date | range | res | note |\n|---|---|---|---|---|\n')
    _write_lf(root / 'docs' / 'ARCHIVE-INDEX.md', '# 歸檔索引\n\n| 任務 | docs/archive/TASKBOARD-ARCHIVE-README.md |\n')
    _write_lf(root / 'docs' / 'archive' / 'TASKBOARD-ARCHIVE-README.md', '# 說明\n')
    _write_lf(root / 'docs' / 'archive' / 'TASKBOARD-ARCHIVE-MANIFEST.json', json.dumps(manifest, indent=2) + '\n')
    _write_lf(root / 'docs' / 'refactor-backlog.md', '')
    _git(root, 'add', '.')
    _git(root, 'commit', '-qm', 'base')
    oid = _git(root, 'rev-parse', 'HEAD')
    _write_lf(root / 'docs' / 'refactor-backlog.md', f'上次核對通過的 HEAD：{oid}\n')
    _git(root, 'add', 'docs/refactor-backlog.md')
    _git(root, 'commit', '-qm', 'checkpoint')
    oid2 = _git(root, 'rev-parse', 'HEAD')
    _write_lf(root / 'docs' / 'refactor-backlog.md', f'上次核對通過的 HEAD：{oid2}\n')
    return root, oid2


# ---------------------------------------------------------------------------
# 1. Deterministic itertools exhaustive transition matrix: TD-107 x TD-108
# ---------------------------------------------------------------------------

def _spec_oracle_td107_td108(
    *,
    v2_active: bool,
    old_disp: str | None,
    new_disp: str,
    basis_mutation: str,
    owner_state: str,
    date_state: str,
) -> bool:
    """Explicit specification oracle: returns True iff tuple MUST pass format+append checks."""
    # Check append-only rules when row exists in checkpoint
    if old_disp is not None:
        if old_disp == '結案':
            if new_disp != '結案' or basis_mutation != 'verbatim':
                return False
        else:
            if new_disp != old_disp and new_disp != '結案':
                return False
            if v2_active and old_disp == '開放' and new_disp == '開放':
                if basis_mutation != 'verbatim' and basis_mutation != 'append_tail':
                    return False

    # Check TD-107 / format rules on final disposition
    if new_disp == '開放':
        if v2_active:
            if owner_state != 'valid_owner':
                return False
            if date_state not in ('single_valid', 'multi_increasing', 'multi_same'):
                return False
        elif old_disp is None and owner_state == 'missing_owner':
            return False
    return True


def _build_basis(owner_state: str, date_state: str) -> str:
    owner_part = {
        'valid_owner': 'owner：G3',
        'empty_owner': 'owner：',
        'missing_owner': '負責群組待定',
    }[owner_state]
    date_part = {
        'single_valid': '複查日 2026-12-15',
        'multi_increasing': '複查日 2026-12-15；延長後複查日 2027-01-15',
        'multi_same': '複查日 2026-12-15；同日複查日 2026-12-15',
        'multi_decreasing': '複查日 2026-12-20；誤填複查日 2026-12-10',
        'missing_date': '尚無日期',
        'colon_fmt': '複查日：2026-12-15',
        'bad_suffix': '複查日 2026-12-15x',
        'dot_fmt': '複查日 2026.12.15',
        'invalid_cal': '複查日 2026-02-30',
    }[date_state]
    return f'{owner_part}；{date_part}'


@pytest.mark.parametrize('v2_active', [True, False])
def test_td107_td108_exhaustive_transition_matrix(v2_active: bool):
    old_disps = (None, '開放', '承接', '結案')
    new_disps = ('開放', '承接', '結案')
    basis_mutations = ('verbatim', 'append_tail', 'rewrite_prefix')
    owner_states = ('valid_owner', 'empty_owner', 'missing_owner')
    date_states = (
        'single_valid', 'multi_increasing', 'multi_same',
        'multi_decreasing', 'missing_date', 'colon_fmt',
        'bad_suffix', 'dot_fmt', 'invalid_cal',
    )

    checked = 0
    mismatches = []
    for old_disp, new_disp, b_mut, o_state, d_state in itertools.product(
        old_disps, new_disps, basis_mutations, owner_states, date_states
    ):
        if old_disp is None:
            new_basis = _build_basis(o_state, d_state)
            old_rows = []
            old_ids = set()
            row = {
                'id': 'TD-001', 'source': 'T1', 'label': 'L', 'item': 'I',
                'disposition': new_disp, 'basis': new_basis, 'line': 4,
            }
        else:
            if b_mut == 'verbatim':
                old_basis = _build_basis(o_state, d_state)
                new_basis = old_basis
            elif b_mut == 'append_tail':
                old_basis = _build_basis(o_state, 'single_valid')
                if d_state in ('single_valid', 'multi_increasing', 'multi_same'):
                    tail = '' if d_state == 'single_valid' else '；改期複查日 2027-01-15' if d_state == 'multi_increasing' else '；複查日 2026-12-15'
                    new_basis = old_basis + '；補記狀態' + tail
                else:
                    extra_date = {
                        'multi_decreasing': '；複查日 2026-11-01',
                        'missing_date': '',
                        'colon_fmt': '；複查日：2027-01-01',
                        'bad_suffix': '；複查日 2027-01-01x',
                        'dot_fmt': '；複查日 2027.01.01',
                        'invalid_cal': '；複查日 2026-02-30',
                    }[d_state]
                    if d_state == 'missing_date':
                        old_basis = 'owner：G3；尚無日期' if o_state == 'valid_owner' else f'{o_state}；尚無日期'
                        if o_state == 'empty_owner':
                            old_basis = 'owner：；尚無日期'
                        new_basis = old_basis + '；補記狀態'
                    else:
                        new_basis = old_basis + '；補記' + extra_date
            else:  # rewrite_prefix
                old_basis = '原始字首不可刪；' + _build_basis(o_state, d_state)
                new_basis = '已改寫字首；' + _build_basis(o_state, d_state)

            old_row = {
                'id': 'TD-001', 'source': 'T1', 'label': 'L', 'item': 'I',
                'disposition': old_disp, 'basis': old_basis, 'line': 4,
            }
            old_rows = [old_row]
            old_ids = {'TD-001'}
            row = {
                'id': 'TD-001', 'source': 'T1', 'label': 'L', 'item': 'I',
                'disposition': new_disp, 'basis': new_basis, 'line': 4,
            }

        probs = (
            ta.ledger_format_problems([row], old_ids=old_ids, v2_active=v2_active)
            + ta.ledger_append_problems([row], old_rows, v2_active=v2_active)
        )
        expected = _spec_oracle_td107_td108(
            v2_active=v2_active,
            old_disp=old_disp,
            new_disp=new_disp,
            basis_mutation=b_mut,
            owner_state=o_state,
            date_state=d_state,
        )
        actual = (len(probs) == 0)
        if actual != expected:
            mismatches.append(((v2_active, old_disp, new_disp, b_mut, o_state, d_state), expected, actual, probs))
        checked += 1

    assert checked == 972
    assert mismatches == [], f'Matrix mismatches ({len(mismatches)}): {mismatches[:5]}'


# ---------------------------------------------------------------------------
# 2. TD-106 Inheritance Markers (Positive, Negative, and Boundary Controls)
# ---------------------------------------------------------------------------

def test_td106_valid_markers_and_closed_exemption(tmp_path, monkeypatch):
    root, _ = _init_repo(
        tmp_path,
        monkeypatch=monkeypatch,
        ledger_rows=[
            '| TD-001 | ' + LEDGER_ANCHOR + ' | L | A | 承接 | 承接位置：ROW:G5 |',
            '| TD-002 | ' + LEDGER_ANCHOR + ' | L | B | 承接 | 承接位置：ROW:G6「事件先後」 |',
            '| TD-003 | ' + LEDGER_ANCHOR + ' | L | C | 承接 | 承接位置：BOARD「BOARD_PLAN_MARKER_ANCHOR」 |',
            '| TD-004 | ' + LEDGER_ANCHOR + ' | L | D | 結案 | 結案無需承接標記 |',
        ],
    )
    out = StringIO()
    assert ta.main(['check', '--repo', str(root)], out=out) == 0, out.getvalue()
    tb = (root / 'docs' / 'TASKBOARD.md').read_text(encoding='utf-8')
    rows, rprobs = ta.parse_ledger((root / 'docs' / 'TODO-LEDGER.md').read_text(encoding='utf-8'))
    assert rprobs == []
    assert ta.ledger_inherit_problems(rows, tb) == []


def test_td106_rejects_all_invalid_targets_and_syntax(tmp_path):
    extra_rec = _rec_block('B117-OTHER-261124', extra_body='ONLY_IN_BATCH_RECORD_ANCHOR。')
    slice_tbl = '| Slice | 狀態 | 目標 | 備註 |\n|---|---|---|---|\n| SL-1 | 待辦 | ok | note |\n'
    root, _ = _init_repo(tmp_path, extra_board_sections=slice_tbl + '\n' + extra_rec + '\n')
    tb = (root / 'docs' / 'TASKBOARD.md').read_text(encoding='utf-8')

    bad_cases = [
        ('missing_marker', '無結構標記', '缺少結構化'),
        ('halfwidth_colon', '承接位置:ROW:G5', '全形冒號'),
        ('bad_syntax', '承接位置：UNKNOWN:G5', '格式不符'),
        ('short_row_anchor', '承接位置：ROW:G5「A」', '錨點過短'),
        ('whitespace_row_anchor', '承接位置：ROW:G5「   」', '錨點過短'),
        ('short_board_anchor', '承接位置：BOARD「短」', '錨點過短'),
        ('whitespace_board_anchor', '承接位置：BOARD「    」', '錨點過短'),
        ('archived_section_row', '承接位置：ROW:B-999', '不在現行看板'),
        ('header_id_row', '承接位置：ROW:ID', '不在現行看板'),
        ('header_slice_row', '承接位置：ROW:Slice', '不在現行看板'),
        ('closed_row', '承接位置：ROW:B-107', '已完成／可封存／CLOSED'),
        ('missing_row_anchor_text', '承接位置：ROW:G5「不存在的片段」', '不含錨點'),
        ('anchor_only_in_record', '承接位置：BOARD「ONLY_IN_BATCH_RECORD_ANCHOR」', '不在現行看板正文'),
        ('anchor_only_in_archive', '承接位置：BOARD「ARCHIVE_ONLY_ANCHOR_TEXT」', '不在現行看板正文'),
        ('partial_multi_second_bad', '承接位置：ROW:G5；承接位置：ROW:B-999', '不在現行看板'),
    ]
    for name, basis, expected_substr in bad_cases:
        row = [{'id': 'TD-001', 'source': 'T', 'label': 'L', 'item': 'I', 'disposition': '承接', 'basis': basis, 'line': 4}]
        probs = ta.ledger_inherit_problems(row, tb)
        assert probs and any(expected_substr in p for p in probs), f'{name} failed to catch {expected_substr}: {probs}'


def test_td106_rejects_duplicate_target_row_and_gates_by_v2_anchor(tmp_path, monkeypatch):
    dup_board_rows = [
        _row_line('G5', 'OPEN', 'one', 'dup1'),
        _row_line('G5', 'OPEN', 'two', 'dup2'),
    ]
    root, _ = _init_repo(tmp_path, monkeypatch=monkeypatch, board_rows=dup_board_rows)
    tb = (root / 'docs' / 'TASKBOARD.md').read_text(encoding='utf-8')
    row = [{'id': 'TD-001', 'source': 'T', 'label': 'L', 'item': 'I', 'disposition': '承接', 'basis': '承接位置：ROW:G5', 'line': 4}]
    probs = ta.ledger_inherit_problems(row, tb)
    assert any('重複' in p for p in probs), probs

    # Without V2_ANCHOR on board or archive, v2 rules remain inactive (backward compatibility before R1 commit)
    root_pre, _ = _init_repo(
        tmp_path / 'pre_v2',
        monkeypatch=monkeypatch,
        include_v2_anchor=False,
        ledger_rows=['| TD-001 | ' + LEDGER_ANCHOR + ' | L | old | 開放 | 無日期無owner |'],
    )
    out = StringIO()
    assert ta.main(['check', '--repo', str(root_pre)], out=out) == 0, out.getvalue()

    # With V2_ANCHOR on board and broken inherit marker, `check` MUST FAIL
    _write_lf(root / 'docs' / 'TODO-LEDGER.md', _ledger_doc([
        '| TD-001 | ' + LEDGER_ANCHOR + ' | lbl | 承接項 | 承接 | 遺失承接標記 |',
        '| TD-002 | ' + LEDGER_ANCHOR + ' | lbl | 開放項 | 開放 | owner：G3；複查日 2026-12-15 |',
        '| TD-003 | ' + LEDGER_ANCHOR + ' | lbl | 已結項 | 結案 | 2026-11-20 已結案 |',
    ]))
    out_fail = StringIO()
    assert ta.main(['check', '--repo', str(root)], out=out_fail) == 1
    assert '缺少結構化「承接位置：」標記' in out_fail.getvalue()


# ---------------------------------------------------------------------------
# 3. TD-107 Review Dates, OWNER_RE, ledger-review CLI, and Zero Wall-Clock CI
# ---------------------------------------------------------------------------

def test_td107_extract_review_dates_and_owner_re():
    d, p = ta.extract_review_dates('owner：G3；複查日 2026-12-15')
    assert [x.isoformat() for x in d] == ['2026-12-15'] and p == []

    d2, p2 = ta.extract_review_dates('複查日 2026-12-01；延期複查日 2026-12-01；再延複查日 2027-01-10。')
    assert [x.isoformat() for x in d2] == ['2026-12-01', '2026-12-01', '2027-01-10'] and p2 == []

    for bad_text in (
        '複查日：2026-12-15',
        '複查日: 2026-12-15',
        '複查日 2026/12/15',
        '複查日 2026.12.15',
        '複查日 2026-12-15x',
        '複查日 2026-02-30',
        '複查日 2026-12-20；複查日 2026-12-10',
    ):
        _, bp = ta.extract_review_dates(bad_text)
        assert bp, f'Expected failure for {bad_text!r}'

    assert ta.OWNER_RE.search('owner：G3；複查日 2026-12-15')
    assert ta.OWNER_RE.search('owner: B-115')
    assert not ta.OWNER_RE.search('owner：；複查日 2026-12-15')
    assert not ta.OWNER_RE.search('myowner：G3')


def test_td107_ledger_review_cli_and_ci_clock_invariance(tmp_path, monkeypatch):
    root, _ = _init_repo(
        tmp_path,
        monkeypatch=monkeypatch,
        ledger_rows=[
            '| TD-001 | ' + LEDGER_ANCHOR + ' | L | past | 開放 | owner：G3；複查日 1999-01-01 |',
            '| TD-002 | ' + LEDGER_ANCHOR + ' | L | rescheduled | 開放 | owner：G3；複查日 1999-01-01；改期複查日 2026-11-30 |',
            '| TD-003 | ' + LEDGER_ANCHOR + ' | L | far | 開放 | owner：G3；複查日 2026-12-20 |',
            '| TD-004 | ' + LEDGER_ANCHOR + ' | L | boundary | 開放 | owner：G3；複查日 2026-12-01 |',
            '| TD-005 | ' + LEDGER_ANCHOR + ' | L | closed | 結案 | done |',
        ],
    )
    # CHECK 29 (`check`) MUST PASS despite 1999-01-01 overdue review date!
    chk_out = StringIO()
    assert ta.main(['check', '--repo', str(root)], out=chk_out) == 0, chk_out.getvalue()

    rev_out = StringIO()
    assert ta.main(['ledger-review', '--repo', str(root), '--as-of', '2026-11-24', '--warn-days', '7', '--json'], out=rev_out) == 0
    summary = json.loads(rev_out.getvalue())
    assert summary['open_total'] == 4
    assert [x['id'] for x in summary['overdue']] == ['TD-001']
    # TD-002 rescheduled to 2026-11-30 (days_until=6), TD-004 at exact boundary 2026-12-01 (days_until=7)
    assert [(x['id'], x['days_until']) for x in summary['due_soon']] == [('TD-002', 6), ('TD-004', 7)]
    assert summary['missing_review_date'] == []

    # Invalid --as-of or negative --warn-days fail closed with rc=1
    for bad_args in (
        ['ledger-review', '--repo', str(root), '--as-of', '2026-02-30'],
        ['ledger-review', '--repo', str(root), '--warn-days', '-1'],
    ):
        err_out = StringIO()
        assert ta.main(bad_args, out=err_out) == 1
        assert 'TODO_LEDGER_REVIEW FAIL' in err_out.getvalue()

    # Missing date is reported in ledger-review, and records-plan prints TODO_LEDGER_REVIEW line
    _write_lf(root / 'docs' / 'TODO-LEDGER.md', _ledger_doc([
        '| TD-001 | ' + LEDGER_ANCHOR + ' | L | nodate | 開放 | owner：G3；待排定 |',
    ]))
    txt_out = StringIO()
    assert ta.main(['ledger-review', '--repo', str(root), '--as-of', '2026-11-24'], out=txt_out) == 0
    assert 'TODO_LEDGER_MISSING_DATE id=TD-001' in txt_out.getvalue()

    plan_out = StringIO()
    ta.main(['records-plan', '--repo', str(root), '--keep', '1'], out=plan_out)
    assert 'TODO_LEDGER_REVIEW ' in plan_out.getvalue()

    # N1 boundary check: delta == 0 (due_soon, days_until=0) vs delta == -1 (overdue, days_overdue=1)
    _write_lf(root / 'docs' / 'TODO-LEDGER.md', _ledger_doc([
        '| TD-001 | ' + LEDGER_ANCHOR + ' | L | boundary_day | 開放 | owner：G3；複查日 2026-11-24 |',
    ]))
    s_eq = ta.ledger_review_summary(str(root), as_of='2026-11-24', warn_days=7)
    assert s_eq['overdue'] == []
    assert [(x['id'], x['days_until']) for x in s_eq['due_soon']] == [('TD-001', 0)]

    s_past1 = ta.ledger_review_summary(str(root), as_of='2026-11-25', warn_days=7)
    assert s_past1['due_soon'] == []
    assert [(x['id'], x['days_overdue']) for x in s_past1['overdue']] == [('TD-001', 1)]


# ---------------------------------------------------------------------------
# 3b. Verbatim split-row CLI, Concatenation Bijection & Fail-Closed Controls
# ---------------------------------------------------------------------------

def test_split_row_verbatim_cli_and_fail_closed(tmp_path, monkeypatch):
    # 1. Chunk splitting preserves every byte without leading/trailing spaces even across '. '
    spaced_body = '。 '.join(f'段落{i:03d}：驗證資料內容不變' for i in range(40))
    chunks = ta.split_row_chunks(spaced_body, 220)
    assert ''.join(chunks) == spaced_body
    assert all(1 <= len(ch) <= 220 for ch in chunks)
    assert all(ch == ch.strip() for ch in chunks)

    # 2. Dry-run vs --apply CLI on a synthetic >2500 row with '；', '。', '、', and '。 '
    sents = [f'子項{i:02d}（R2 測試）；內容片段第{i:02d}段，含驗證敘述' for i in range(1, 130)]
    long_body = '。'.join(sents[:60]) + '。 ' + '；'.join(sents[60:]) + '。'
    long_row = _row_line('B-100', '待辦', '傘狀超長任務標題', long_body)
    assert len(long_row) > ta.ROW_MAX_CHARS

    root, _ = _init_repo(
        tmp_path,
        monkeypatch=monkeypatch,
        board_rows=[
            _row_line('G5', 'OPEN', '執行器', 'STEP_IN_PROGRESS'),
            long_row,
            _row_line('B-112', '待辦', '短列', '內容小於上限'),
        ],
    )
    monkeypatch.setattr(ta, 'ROW_LEN_LEGACY_CAPS', {})
    orig_board = (root / 'docs' / 'TASKBOARD.md').read_text(encoding='utf-8')

    # Dry-run must not mutate TASKBOARD.md
    dry_out = StringIO()
    assert ta.main(['split-row', '--repo', str(root), '--id', 'B-100'], out=dry_out) == 0, dry_out.getvalue()
    assert 'TASKBOARD_SPLIT PLAN PASS id=B-100' in dry_out.getvalue()
    assert (root / 'docs' / 'TASKBOARD.md').read_text(encoding='utf-8') == orig_board

    # --apply mutates TASKBOARD.md cleanly and passes concatenation & row-length checks
    app_out = StringIO()
    assert ta.main(['split-row', '--repo', str(root), '--id', 'B-100', '--apply'], out=app_out) == 0, app_out.getvalue()
    assert 'TASKBOARD_SPLIT APPLY PASS id=B-100' in app_out.getvalue()
    new_board = (root / 'docs' / 'TASKBOARD.md').read_text(encoding='utf-8')
    assert new_board != orig_board

    ok, joined, child_ids, probs = ta.verify_split_concat(new_board, 'B-100', long_body)
    assert ok and probs == [] and joined == long_body, (ok, probs)
    assert child_ids == [f'B-100-{i}' for i in range(1, len(child_ids) + 1)]
    for row in ta._table_data_rows(new_board):
        assert len(row['text']) <= ta.ROW_MAX_CHARS
    expected_sha = hashlib.sha256(long_body.encode('utf-8')).hexdigest()
    parent_row = next(r for r in ta._table_data_rows(new_board) if r['id'] == 'B-100')
    assert expected_sha in parent_row['text']

    rl_fails, rl_infos = ta.check_row_lengths(str(root))
    assert rl_fails == [] and any('過渡例外 0 列' in i for i in rl_infos), (rl_fails, rl_infos)
    chk_fails, _ = ta.check(str(root))
    assert chk_fails == [], chk_fails

    # 3. Direct check of verify_split_concat tamper & gap detection
    tampered = new_board.replace('子項01', '子項99', 1)
    ok_t, _, _, probs_t = ta.verify_split_concat(tampered, 'B-100', long_body)
    assert not ok_t and probs_t
    gapped = '\n'.join(l for l in new_board.split('\n') if not l.startswith('| B-100-1 |'))
    ok_g, _, _, probs_g = ta.verify_split_concat(gapped, 'B-100', long_body)
    assert not ok_g and any('連續' in p for p in probs_g)

    # 4. Fail-closed CLI & helper negatives
    for bad_id in ('B-100', 'B-112', 'NO-SUCH-ID', 'bad id!'):
        bad_out = StringIO()
        assert ta.main(['split-row', '--repo', str(root), '--id', bad_id, '--apply'], out=bad_out) == 1
        assert 'TASKBOARD_SPLIT APPLY FAIL' in bad_out.getvalue()

    root_neg, _ = _init_repo(
        tmp_path / 'neg',
        monkeypatch=monkeypatch,
        board_rows=[_row_line('G5', 'OPEN', 'dup1', 'x' * 2600), _row_line('G5', 'OPEN', 'dup2', 'y')],
    )
    for bad_args in (
        ['split-row', '--repo', str(root_neg), '--id', 'G5'],
        ['split-row', '--repo', str(root_neg), '--id', 'G5', '--max-chars', '0'],
        ['split-row', '--repo', str(root_neg), '--id', 'G5', '--max-chars', '20'],
    ):
        o = StringIO()
        assert ta.main(bad_args, out=o) == 1 and 'TASKBOARD_SPLIT PLAN FAIL' in o.getvalue()

    root_col, _ = _init_repo(
        tmp_path / 'col',
        monkeypatch=monkeypatch,
        board_rows=[_row_line('G5', 'OPEN', 'over', 'x' * 2600), _row_line('G5-1', 'OPEN', 'existing_child', 'y')],
    )
    col_out = StringIO()
    assert ta.main(['split-row', '--repo', str(root_col), '--id', 'G5'], out=col_out) == 1
    assert '已存在子列 G5-1' in col_out.getvalue()

    with pytest.raises(ta.Fail):
        ta.split_row_chunks('a|b', 50)
    (root / 'docs' / 'TASKBOARD.md').write_bytes(b'\xef\xbb\xbf' + new_board.encode('utf-8'))
    bom_out = StringIO()
    assert ta.main(['split-row', '--repo', str(root), '--id', 'B-112'], out=bom_out) == 1

    # 5. Checkpoint 0a14e556 real B-100 / B-115 rows split cleanly with 100% byte identity
    real_root = Path(__file__).resolve().parents[2]
    ckpt = '0a14e5569938372362817821aee5d946946fc374'
    if (real_root / '.git').exists() and ta.resolve_commit(str(real_root), ckpt) == ckpt:
        ckpt_tb = ta.git_blob_text(str(real_root), ckpt, ta.TASKBOARD_REL)
        ckpt_rows = {r['id']: r for r in ta._table_data_rows(ckpt_tb)}
        for target_rid in ('B-100', 'B-115'):
            _, _, _, orig_b = ta.parse_row_cells(ckpt_rows[target_rid]['text'])
            p_line, c_lines, meta = ta.split_row_lines(ckpt_rows[target_rid], max_chars=ta.ROW_MAX_CHARS)
            assert meta['max_row_len'] <= ta.ROW_MAX_CHARS and len(p_line) <= ta.ROW_MAX_CHARS
            assert ''.join(ta.parse_row_cells(c)[3] for c in c_lines) == orig_b


def test_split_row_rejects_non_four_column_rows(tmp_path, monkeypatch):
    # Extra '|' inside body turns a row into 5+ cells; split-row and parse_row_cells MUST fail closed
    body_a = '甲' * 1800 + '。'
    body_b = '乙' * 1500 + '。'
    line_5col = f'| B-997 | 待辦 | **測試** | {body_a} | {body_b} |'
    line_3col = '| B-996 | 待辦 | 缺第四欄 |'

    with pytest.raises(ta.Fail, match=r'欄數須恰為 4（實得 5）'):
        ta.parse_row_cells(line_5col)
    with pytest.raises(ta.Fail, match=r'欄數須恰為 4（實得 5）'):
        ta.split_row_lines({'text': line_5col, 'line': 1, 'id': 'B-997'}, max_chars=1000)
    with pytest.raises(ta.Fail, match=r'欄數須恰為 4（實得 3）'):
        ta.parse_row_cells(line_3col)

    root_5col, _ = _init_repo(
        tmp_path,
        monkeypatch=monkeypatch,
        board_rows=[_row_line('G5', 'OPEN', '執行器', 'STEP_IN_PROGRESS'), line_5col],
    )
    tb_path = root_5col / 'docs' / 'TASKBOARD.md'
    orig_bytes = tb_path.read_bytes()

    dry_out = StringIO()
    assert ta.main(['split-row', '--repo', str(root_5col), '--id', 'B-997', '--max-chars', '1000'], out=dry_out) == 1
    assert 'TASKBOARD_SPLIT PLAN FAIL' in dry_out.getvalue() and '欄數須恰為 4（實得 5）' in dry_out.getvalue()
    assert tb_path.read_bytes() == orig_bytes

    app_out = StringIO()
    assert ta.main(['split-row', '--repo', str(root_5col), '--id', 'B-997', '--max-chars', '1000', '--apply'], out=app_out) == 1
    assert 'TASKBOARD_SPLIT APPLY FAIL' in app_out.getvalue() and '欄數須恰為 4（實得 5）' in app_out.getvalue()
    assert tb_path.read_bytes() == orig_bytes


# ---------------------------------------------------------------------------
# 4. CHECK 32 Decision Table + Non-ROW_RE Line Guard + Fail-Closed Controls
# ---------------------------------------------------------------------------

def test_check32_all_decision_table_and_fail_closed_cases(tmp_path, monkeypatch):
    # Prepare baseline repo with legacy rows B-111 (3000 chars) and B-112 (2400 chars <= 2500 at checkpoint!)
    b111_base = _row_line('B-111', '待辦', 'legacy', 'x' * 2970)
    b112_base = _row_line('B-112', '待辦', 'shrunk_before', 'x' * 2370)
    assert len(b111_base) > 2500 and len(b112_base) <= 2500
    root, oid = _init_repo(tmp_path, board_rows=[b111_base, b112_base, _row_line('B-01', '待辦', 'ok', 'y')])
    monkeypatch.setitem(ta.ROW_LEN_LEGACY_CAPS, 'B-111', 3500)  # larger static cap; effective is min(3500, old=2996)
    monkeypatch.setitem(ta.ROW_LEN_LEGACY_CAPS, 'B-112', 3500)  # already <=2500 in old, so effective is 2500

    # Case 1-6: unchanged legacy == old, shrunk legacy (>2500), shrunk legacy <= 2500, normal row == 2500 -> PASS
    row_2500 = _row_line('B-01', '待辦', 'exact2500', 'z' * (2500 - len('| B-01 | 待辦 | exact2500 |  |')))
    assert len(row_2500) == 2500
    b111_shrunk = _row_line('B-111', '待辦', 'legacy', 'x' * 2700)
    unchanged_tb = '\n'.join([
        '# 任務看板',
        '| ID | 狀態 | 項目 | 備註 |',
        '|---|---|---|---|',
        b111_base,
        b112_base,
        row_2500,
    ]) + '\n'
    _write_lf(root / 'docs' / 'TASKBOARD.md', unchanged_tb)
    fails_unchanged, infos_unchanged = ta.check_row_lengths(str(root))
    assert fails_unchanged == [] and any('過渡例外 1 列' in i for i in infos_unchanged), (fails_unchanged, infos_unchanged)

    b111_under_2500 = _row_line('B-111', '待辦', 'legacy', 'x' * 100)
    _write_lf(root / 'docs' / 'TASKBOARD.md', unchanged_tb.replace(b111_base, b111_under_2500))
    fails_u, infos_u = ta.check_row_lengths(str(root))
    assert fails_u == [] and any('過渡例外 0 列' in i for i in infos_u), (fails_u, infos_u)

    base_tb = '\n'.join([
        '# 任務看板',
        '| ID | 狀態 | 項目 | 備註 |',
        '|---|---|---|---|',
        b111_shrunk,
        b112_base,
        row_2500,
    ]) + '\n'
    _write_lf(root / 'docs' / 'TASKBOARD.md', base_tb)
    out = StringIO()
    assert ta.main(['row-length-check', '--repo', str(root)], out=out) == 0, out.getvalue()
    assert 'TASKBOARD_ROW_LENGTH CHECK PASS' in out.getvalue()

    # Case: normal row 2501 -> FAIL
    row_2501 = row_2500[:-2] + 'a |'
    assert len(row_2501) == 2501
    _write_lf(root / 'docs' / 'TASKBOARD.md', base_tb.replace(row_2500, row_2501))
    fails, _ = ta.check_row_lengths(str(root))
    assert any('超過上限 2500' in f for f in fails), fails

    # Case: legacy B-111 grew by +1 over old length (even below static_cap 3500!) -> FAIL
    b111_grew = _row_line('B-111', '待辦', 'legacy', 'x' * 2971)
    _write_lf(root / 'docs' / 'TASKBOARD.md', base_tb.replace(b111_shrunk, b111_grew))
    fails, _ = ta.check_row_lengths(str(root))
    assert any('只減不增' in f for f in fails), fails

    # Case: legacy B-112 was <= 2500 in checkpoint, cannot re-expand > 2500 -> FAIL
    b112_reexpanded = _row_line('B-112', '待辦', 'shrunk_before', 'x' * 2550)
    _write_lf(root / 'docs' / 'TASKBOARD.md', base_tb.replace(b112_base, b112_reexpanded))
    fails, _ = ta.check_row_lengths(str(root))
    assert any('超過允許上限 2500' in f for f in fails), fails

    # Case: new row added with allowlisted ID 'G6' not present in old_board -> effective_cap=2500 -> FAIL
    monkeypatch.setitem(ta.ROW_LEN_LEGACY_CAPS, 'G6', 5814)
    _write_lf(root / 'docs' / 'TASKBOARD.md', base_tb + _row_line('G6', 'OPEN', 'new', 'w' * 2600) + '\n')
    fails, _ = ta.check_row_lengths(str(root))
    assert any('G6' in f and '超過允許上限 2500' in f for f in fails), fails

    # Case: non-ROW_RE pipe line (e.g., continuation row or G4（驗證器）) > 2500 -> FAIL
    non_row_long = '|   | 待辦 | 續行繞過 | ' + ('n' * 2500) + ' |'
    _write_lf(root / 'docs' / 'TASKBOARD.md', base_tb + non_row_long + '\n')
    fails, _ = ta.check_row_lengths(str(root))
    assert any('非標準編號表格列長' in f for f in fails), fails

    # Case: duplicate row ID -> FAIL
    _write_lf(root / 'docs' / 'TASKBOARD.md', base_tb + _row_line('B-01', '待辦', 'dup', 'y') + '\n')
    fails, _ = ta.check_row_lengths(str(root))
    assert any('重複' in f for f in fails), fails

    # Fail-closed controls: bad legacy cap, BOM, CR, unresolvable checkpoint
    _write_lf(root / 'docs' / 'TASKBOARD.md', base_tb)
    (root / 'docs' / 'TASKBOARD.md').write_bytes(b'\xef\xbb\xbf' + base_tb.encode('utf-8'))
    fails, _ = ta.check_row_lengths(str(root))
    assert any('BOM' in f for f in fails), fails

    (root / 'docs' / 'TASKBOARD.md').write_bytes(base_tb.replace('\n', '\r\n').encode('utf-8'))
    fails, _ = ta.check_row_lengths(str(root))
    assert any('CR' in f for f in fails), fails

    _write_lf(root / 'docs' / 'TASKBOARD.md', base_tb)
    _write_lf(root / 'docs' / 'refactor-backlog.md', f'上次核對通過的 HEAD：{"0" * 40}\n')
    fails, _ = ta.check_row_lengths(str(root))
    assert any('無法解析' in f for f in fails), fails

    monkeypatch.setattr(ta, 'ROW_LEN_LEGACY_CAPS', {'BAD': 2500})
    fails, _ = ta.check_row_lengths(str(root))
    assert any('無效' in f for f in fails), fails


# ---------------------------------------------------------------------------
# 5. Real-Repo Candidate Verification Control (skipped safely prior to apply)
# ---------------------------------------------------------------------------

def test_real_repo_b3b3_2_post_apply_invariants():
    real_root = Path(__file__).resolve().parents[2]
    arch3 = real_root / 'docs' / 'archive' / 'TASKBOARD-ARCHIVE-0003.md'
    if not arch3.is_file():
        pytest.skip('TASKBOARD-ARCHIVE-0003.md not yet applied prior to b3b3-2')

    tb = (real_root / 'docs' / 'TASKBOARD.md').read_text(encoding='utf-8')
    rows_by_id = {r['id']: r for r in ta._table_data_rows(tb)}
    assert 'B-107' not in rows_by_id, 'B-107 row must be archived off TASKBOARD.md'
    assert 'B-107' in arch3.read_text(encoding='utf-8')
    for rid, r in rows_by_id.items():
        if ta.is_active(r['status']) or rid.startswith(('B-100', 'B-112', 'B-114', 'B-115')):
            assert not ta.ref_pattern('B-107').search(r['text']), f'Active/target row {rid} still references B-107'

    assert 'G7' in rows_by_id
    assert 'G7' in ta.ROW_LEN_LEGACY_CAPS and len(ta.ROW_LEN_LEGACY_CAPS) == 9
    assert len(rows_by_id['G7']['text']) <= ta.ROW_LEN_LEGACY_CAPS['G7']

    id_re = re.compile(r'^[A-Z][A-Z0-9]*(-[A-Z0-9]+)*$')
    expected_counts = {'B-100': 9, 'B-115': 8}
    for prefix, exp_cnt in expected_counts.items():
        matches = [r for rid, r in rows_by_id.items() if rid == prefix or rid.startswith(prefix + '-')]
        assert len(matches) == exp_cnt, f'Expected parent + {exp_cnt - 1} split subrows for {prefix}, got {[m["id"] for m in matches]}'
        for r in matches:
            assert id_re.fullmatch(r['id'])
            assert len(r['text']) <= ta.ROW_MAX_CHARS, f"{r['id']} len={len(r['text'])}"

    ckpt = '0a14e5569938372362817821aee5d946946fc374'
    cur_ckpt = ta.read_checkpoint((real_root / 'docs' / 'refactor-backlog.md').read_text(encoding='utf-8'))
    if cur_ckpt == ckpt and ta.resolve_commit(str(real_root), ckpt) == ckpt:
        ckpt_tb = ta.git_blob_text(str(real_root), ckpt, ta.TASKBOARD_REL)
        ckpt_rows = {r['id']: r['text'] for r in ta._table_data_rows(ckpt_tb)}
        assert rows_by_id['G7']['text'] == ckpt_rows['G7'], 'G7 must remain byte-identical to checkpoint'
        b107_re = re.compile(r'(?<![A-Za-z0-9-])B-107(?![0-9A-Za-z])')
        b107_repl = 'G4 封存列（docs/archive/TASKBOARD-ARCHIVE-0003.md）'
        for rid in ('B-100', 'B-115'):
            orig_body = ta.parse_row_cells(ckpt_rows[rid])[3]
            cleaned = b107_re.sub(b107_repl, orig_body)
            if rid == 'B-100':
                cleaned = cleaned.replace('parent: 604c6fe9...', 'parent: 604c6fe9beb27ec234045da89b171b1e1fedc9b5', 1)
            ok_v, joined_v, _, probs_v = ta.verify_split_concat(tb, rid, cleaned)
            assert ok_v, f'{rid} split concatenation mismatch: {probs_v}'
            parent_body = ta.parse_row_cells(rows_by_id[rid]['text'])[3]
            assert hashlib.sha256(joined_v.encode('utf-8')).hexdigest() in parent_body
            restored = joined_v.replace(b107_repl, 'B-107')
            if rid == 'B-100':
                restored = restored.replace('parent: 604c6fe9beb27ec234045da89b171b1e1fedc9b5', 'parent: 604c6fe9...', 1)
            assert restored == orig_body

    out = StringIO()
    assert ta.main(['check', '--repo', str(real_root)], out=out) == 0, out.getvalue()
    r_fails, _ = cc.check_32_taskboard_row_length_guard(str(real_root))
    assert r_fails == [], r_fails
    summary = ta.ledger_review_summary(str(real_root), as_of='2026-11-25')
    assert summary['overdue'] == []
    assert summary['missing_review_date'] == []
    assert summary['date_format_errors'] == []
