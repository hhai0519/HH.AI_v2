# -*- coding: utf-8 -*-
"""B-117 beta-2 (TD-008): unit & integration tests for scripts/cap_count.py."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

import cap_count as cc  # noqa: E402


ANCHOR_TASK = cc.CAP2_ANCHOR_TASK


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def _commit(repo: Path, files: dict, msg: str, task_id: str | None = None) -> str:
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content if isinstance(content, bytes) else content.encode('utf-8'))
    if task_id is not None:
        rec = repo / 'docs' / 'governance' / 'execution-record.json'
        rec.parent.mkdir(parents=True, exist_ok=True)
        rec.write_bytes((json.dumps({'task_id': task_id}, sort_keys=True) + '\n').encode('utf-8'))
    subprocess.run(['git', '-C', str(repo), 'add', '-A'], check=True)
    subprocess.run(['git', '-C', str(repo), 'commit', '-qm', msg], check=True)
    return _git(repo, 'rev-parse', 'HEAD')


def _init_repo(tmp_path: Path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'core.autocrlf', 'false'], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.name', 'Test'], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.email', 'test@example.test'], check=True)

    anchor_oid = _commit(repo, {'scripts/base.py': b'# base\n'}, 'anchor', task_id=ANCHOR_TASK)
    return repo, anchor_oid


def _write_docs(repo: Path, *, freeze_line: str, audit_rows: list[str], exec_rows: list[str] | None = None, reg_causes: list[dict] | None = None):
    docs = repo / 'docs'
    (docs / 'governance').mkdir(parents=True, exist_ok=True)
    (docs / 'TASKBOARD.md').write_bytes((f'# 看板\n\n{freeze_line}\n').encode('utf-8'))
    audit = [
        '# 稽核',
        '',
        '| 批次 commit | 日期 | 觸發條款 | 結論摘要 | 失效檢討 |',
        '|---|---|---|---|---|',
        *audit_rows,
        '',
        '## CI 歷史事故歸檔專區',
        '| IGNORED | 1 | 2 | 3 | 4 |',
    ]
    (docs / 'AUDIT-LOG.md').write_bytes(('\n'.join(audit) + '\n').encode('utf-8'))
    if exec_rows is not None:
        execlog = [
            '# EXEC-LOG',
            '| 批次 commit | 日期 | 內容 |',
            '|---|---|---|',
            *exec_rows,
        ]
        (docs / 'EXEC-LOG.md').write_bytes(('\n'.join(execlog) + '\n').encode('utf-8'))
    if reg_causes is not None:
        (docs / 'governance' / 's1-registry.json').write_bytes(
            (json.dumps({'schema': 2, 'causes': reg_causes}, ensure_ascii=False) + '\n').encode('utf-8')
        )


def test_real_repo_cap_count_d6_and_cap2():
    if not (REPO_ROOT / '.git').exists() or not (REPO_ROOT / 'docs' / 'AUDIT-LOG.md').is_file():
        pytest.skip('requires full repository checkout')
    res = cc.compute_all(str(REPO_ROOT), mode='all')
    assert res['d6']['source'] == 'repo'
    assert res['d6']['target'] == 20
    assert res['cap2']['source'] == 'repo'
    assert res['cap2']['target'] == 20
    assert res['cap2']['anchor_task'] == ANCHOR_TASK
    assert cc.main(['--repo', str(REPO_ROOT), '--mode', 'all']) == 0


def test_count_d6_series_s1_reset_readonly_unverified_and_nonzero_ci_tolerance(tmp_path, capsys):
    repo, anchor_oid = _init_repo(tmp_path)
    c1 = _commit(repo, {'docs/a.md': b'1\n'}, 't1', task_id='B117-TEST-T1-261120')
    c_s1 = _commit(repo, {'docs/d.md': b'4\n'}, 's1fix', task_id='B117-TEST-S1-261122')
    c2 = _commit(repo, {'docs/e.md': b'5\n'}, 't2', task_id='B117-TEST-T2-261123')
    c_ro = _commit(repo, {'docs/b.md': b'2\n'}, 'ro', task_id='READONLY-B117-PROBE-261123')
    c_pend = _commit(repo, {'docs/c.md': b'3\n'}, 'pend', task_id='B117-TEST-PEND-261123')
    c3 = _commit(repo, {'docs/f.md': b'6\n'}, 't3', task_id='B117-TEST-T3-261124')

    rows = [
        f'| {anchor_oid} | 2026-11-15 | §4.1；{ANCHOR_TASK} | POST-MAIN VERIFIED | ok |',
        f'| {c1} | 2026-11-20 | §4.1；B117-TEST-T1-261120 | POST-MAIN VERIFIED | ok |',
        f'| {c_s1} | 2026-11-22 | §4.1；B117-TEST-S1-261122 | POST-MAIN VERIFIED | s1 |',
        f'| {c2} | 2026-11-23 | §4.1；B117-TEST-T2-261123 | POST-MAIN VERIFIED | ok |',
        f'| {c_ro} | 2026-11-23 | §4.1；READONLY-B117-PROBE-261123 只讀批 | POST-MAIN VERIFIED | ok |',
        f'| {c_pend} | 2026-11-23 | §4.1；B117-TEST-PEND-261123 | CANDIDATE_PENDING | wait |',
        f'| {c3} | 2026-11-24 | §4.1；B117-TEST-T3-261124 | POST-MAIN VERIFIED | ok |',
    ]
    causes = [{'id': 'S1C-001', 'tasks': ['PROMOTE-B117-TEST-S1-261122'], 'status': 'planned'}]
    freeze_match = f'**治理凍結**：USER 2026-11-20 決定；連續無 S1 批數 2/20；最後歸零：B117-TEST-S1-261122（S1）；起算：{ANCHOR_TASK}（不含）'
    _write_docs(repo, freeze_line=freeze_match, audit_rows=rows, reg_causes=causes)

    d6 = cc.count_d6(str(repo))
    assert d6['count'] == 2
    assert d6['declared'] == 2
    assert d6['match'] is True
    assert d6['counted_tasks'] == ['B117-TEST-T2-261123', 'B117-TEST-T3-261124']
    assert d6['repo_resets'] == ['B117-TEST-S1-261122']

    # Dashboard mismatch (declared=1 vs repo=2) still exits 0 and reports match=NO
    freeze_mismatch = f'**治理凍結**：USER 2026-11-20 決定；連續無 S1 批數 1/20；最後歸零：B117-TEST-S1-261122（S1）；起算：{ANCHOR_TASK}（不含）'
    _write_docs(repo, freeze_line=freeze_mismatch, audit_rows=rows, reg_causes=causes)
    rc = cc.main(['--repo', str(repo), '--mode', 'd6'])
    out = capsys.readouterr().out
    assert rc == 0
    assert 'CAP_COUNT_D6 source=repo count=2 target=20 declared=1 match=NO ' in out


def test_d6_anchor_fallbacks_fixedcommit_execlog_and_unresolved(tmp_path):
    repo, anchor_oid = _init_repo(tmp_path)
    c_fix = _commit(repo, {'docs/f1.md': b'1\n'}, 'fix', task_id='B117-FIX-R1-261122')
    c_next = _commit(repo, {'docs/f2.md': b'2\n'}, 'next', task_id='B117-NEXT-R1-261123')
    rows = [
        f'| {anchor_oid} | 2026-11-15 | §4.1；{ANCHOR_TASK} | POST-MAIN VERIFIED | a |',
        f'| {c_fix} | 2026-11-22 | §4.1；B117-FIX-R1-261122 | POST-MAIN VERIFIED | fix |',
        f'| {c_next} | 2026-11-23 | §4.1；B117-NEXT-R1-261123 | POST-MAIN VERIFIED | n |',
    ]
    # 1. Resolved via s1-registry fixedCommit (inclusive at c_fix -> count 2)
    freeze = '**治理凍結**：USER 2026-11-20 決定；連續無 S1 批數 2/20；最後歸零：B117-UNMERGED-S1-261122（CI）；起算：B117-UNMERGED-S1-261122（不含）'
    causes = [{'id': 'S1C-001', 'tasks': ['B117-UNMERGED-S1-261122'], 'fixedCommit': c_fix}]
    _write_docs(repo, freeze_line=freeze, audit_rows=rows, reg_causes=causes)
    d6_fc = cc.count_d6(str(repo))
    assert d6_fc['count'] == 2 and d6_fc['match'] is True

    # 2. Resolved via EXEC-LOG base_oid -> AUDIT-LOG row whose parent == base_oid
    exec_rows = [f'| {anchor_oid} | 2026-11-22 | B117-UNMERGED-S1-261122：attempt |']
    _write_docs(repo, freeze_line=freeze, audit_rows=rows, exec_rows=exec_rows, reg_causes=[])
    d6_el = cc.count_d6(str(repo))
    assert d6_el['count'] == 2 and d6_el['counted_commits'] == [c_fix, c_next]

    # 3. Unresolved start_after fails closed
    _write_docs(repo, freeze_line=freeze, audit_rows=rows, exec_rows=[], reg_causes=[])
    with pytest.raises(cc.CapCountError) as exc_info:
        cc.count_d6(str(repo))
    assert exc_info.value.code == 'START_AFTER_UNRESOLVED'


def test_cap2_product_prefixes_resets_and_non_product_ignored(tmp_path):
    repo, anchor_oid = _init_repo(tmp_path)
    p1 = _commit(repo, {'runtime/a.js': b'1\n'}, 'p1', task_id='B117-P1-261120')
    g1 = _commit(repo, {'scripts/helper.py': b'1\n'}, 'g1', task_id='B117-G1-261120')
    p2 = _commit(repo, {'SOP/guide.md': b'1\n'}, 'p2', task_id='B117-P2-261121')
    p3 = _commit(repo, {'skills/sk.md': b'1\n'}, 'p3', task_id='B117-P3-261122')
    p4 = _commit(repo, {'shared/s.js': b'1\n'}, 'p4', task_id='B117-P4-261123')
    p5 = _commit(repo, {'templates/t.md': b'1\n'}, 'p5', task_id='B117-P5-261123')
    p6 = _commit(repo, {'runtime/b.js': b'2\n'}, 'p6', task_id='B117-P6-261124')

    rows = [
        f'| {anchor_oid} | 2026-11-15 | §4.1；{ANCHOR_TASK} | POST-MAIN VERIFIED | ok |',
        f'| {p1} | 2026-11-20 | §4.1；B117-P1-261120 | POST-MAIN VERIFIED | ok |',
        f'| {g1} | 2026-11-20 | §4.1；B117-G1-261120 | POST-MAIN VERIFIED | CAP_RESET=S1:B117-G1-261120 ignored |',
        f'| {p2} | 2026-11-21 | §4.1；B117-P2-261121 | POST-MAIN VERIFIED | ok |',
        f'| {p3} | 2026-11-22 | §4.1；B117-P3-261122 | POST-MAIN VERIFIED | CAP_RESET=ERROR_INTO_MAIN:B117-P3-261122 |',
        f'| {p4} | 2026-11-23 | §4.1；B117-P4-261123 | POST-MAIN VERIFIED | ok |',
        f'| {p5} | 2026-11-23 | §4.1；B117-P5-261123 | POST-MAIN VERIFIED | CAP_RESET=PATCH_BATCH:B117-P5-261123 |',
        f'| {p6} | 2026-11-24 | §4.1；B117-P6-261124 | POST-MAIN VERIFIED | ok |',
    ]
    freeze = f'**治理凍結**：USER 2026-11-20 決定；連續無 S1 批數 6/20；最後歸零：{ANCHOR_TASK}（OK）；起算：{ANCHOR_TASK}（不含）'
    _write_docs(repo, freeze_line=freeze, audit_rows=rows)

    cap2 = cc.count_cap2(str(repo))
    assert cap2['product_batches_total'] == 6
    assert cap2['count'] == 1
    assert cap2['counted_product_tasks'] == ['B117-P6-261124']
    assert len(cap2['resets_applied']) == 2
    assert cap2['resets_ignored_non_product'] == [{'reason': 'S1', 'task': 'B117-G1-261120'}]


def test_fail_closed_on_bom_cr_non_first_parent_and_from_git_vs_worktree(tmp_path):
    repo, anchor_oid = _init_repo(tmp_path)
    c1 = _commit(repo, {'docs/x.md': b'1\n'}, 'c1', task_id='B117-C1-261122')
    rows = [
        f'| {anchor_oid} | 2026-11-15 | §4.1；{ANCHOR_TASK} | POST-MAIN VERIFIED | a |',
        f'| {c1} | 2026-11-22 | §4.1；B117-C1-261122 | POST-MAIN VERIFIED | ok |',
    ]
    freeze_1 = f'**治理凍結**：USER 2026-11-20 決定；連續無 S1 批數 1/20；最後歸零：{ANCHOR_TASK}（OK）；起算：{ANCHOR_TASK}（不含）'
    _write_docs(repo, freeze_line=freeze_1, audit_rows=rows)
    _commit(repo, {}, 'commit docs', task_id='B117-DOCS-261122')

    # Uncommitted worktree change (declared=9) is visible by default, ignored with --from-git
    freeze_9 = f'**治理凍結**：USER 2026-11-20 決定；連續無 S1 批數 9/20；最後歸零：{ANCHOR_TASK}（OK）；起算：{ANCHOR_TASK}（不含）'
    (repo / 'docs' / 'TASKBOARD.md').write_bytes((f'# 看板\n\n{freeze_9}\n').encode('utf-8'))
    assert cc.count_d6(str(repo))['declared'] == 9
    assert cc.count_d6(str(repo), use_git=True)['declared'] == 1

    # BOM rejected
    (repo / 'docs' / 'TASKBOARD.md').write_bytes(b'\xef\xbb\xbf' + f'# 看板\n\n{freeze_1}\n'.encode('utf-8'))
    assert cc.main(['--repo', str(repo), '--mode', 'd6']) == 1

    # CR rejected
    (repo / 'docs' / 'TASKBOARD.md').write_bytes((f'# 看板\n\n{freeze_1}\n').encode('utf-8'))
    al_raw = (repo / 'docs' / 'AUDIT-LOG.md').read_bytes().replace(b'\n', b'\r\n')
    (repo / 'docs' / 'AUDIT-LOG.md').write_bytes(al_raw)
    assert cc.main(['--repo', str(repo), '--mode', 'd6']) == 1

    # Side-branch (non first-parent) commit fails closed
    (repo / 'docs' / 'AUDIT-LOG.md').write_bytes(al_raw.replace(b'\r\n', b'\n'))
    main_head = _git(repo, 'rev-parse', 'HEAD')
    subprocess.run(['git', '-C', str(repo), 'checkout', '-qb', 'side', anchor_oid], check=True)
    side_oid = _commit(repo, {'docs/side.md': b's\n'}, 'side', task_id=None)
    # Reattach cleanly on main branch and merge side with --no-ff
    subprocess.run(['git', '-C', str(repo), 'checkout', '-B', 'main', main_head], check=True)
    subprocess.run(['git', '-C', str(repo), 'merge', '--no-ff', '-qm', 'merge side', 'side'], check=True)
    rows.append(f'| {side_oid} | 2026-11-23 | §4.1；B117-SIDE-261123 | POST-MAIN VERIFIED | side |')
    _write_docs(repo, freeze_line=freeze_1, audit_rows=rows)
    with pytest.raises(cc.CapCountError) as exc_info:
        cc.count_d6(str(repo))
    assert exc_info.value.code == 'D6_ROW_NOT_FIRST_PARENT'


def test_d6_start_after_row_in_audit_log_is_exclusive(tmp_path):
    repo, anchor_oid = _init_repo(tmp_path)
    c_start = _commit(repo, {'docs/s.md': b'0\n'}, 'start', task_id='B117-START-R1-261121')
    c_after = _commit(repo, {'docs/a.md': b'1\n'}, 'after', task_id='B117-AFTER-R1-261122')
    rows = [
        f'| {anchor_oid} | 2026-11-15 | §4.1；{ANCHOR_TASK} | POST-MAIN VERIFIED | a |',
        f'| {c_start} | 2026-11-21 | §4.1；B117-START-R1-261121 | POST-MAIN VERIFIED | s |',
        f'| {c_after} | 2026-11-22 | §4.1；B117-AFTER-R1-261122 | POST-MAIN VERIFIED | ok |',
    ]
    freeze = '**治理凍結**：USER 2026-11-20 決定；連續無 S1 批數 1/20；最後歸零：B117-START-R1-261121（CI）；起算：B117-START-R1-261121（不含）'
    _write_docs(repo, freeze_line=freeze, audit_rows=rows, reg_causes=[])
    d6 = cc.count_d6(str(repo))
    assert d6['count'] == 1
    assert d6['counted_tasks'] == ['B117-AFTER-R1-261122']
    assert d6['match'] is True


def test_d6_halted_unmerged_s1_resets_before_registering_batch_and_flags_reset_mismatch(tmp_path, capsys):
    # Steady-state scenario: parent already has s1-registry.json; H halts without main commit;
    # clean batch B registers H -> H resets streak before B, so count=1 (not 2), and forgot reset triggers reset_mismatch.
    repo, anchor_oid = _init_repo(tmp_path)
    c_start = _commit(repo, {'docs/s.md': b'0\n'}, 'start', task_id='B117-START-R1-261121')
    _write_docs(
        repo,
        freeze_line='**治理凍結**：USER 2026-11-20 決定；連續無 S1 批數 0/20；最後歸零：B117-START-R1-261121（S1）；起算：B117-START-R1-261121（不含）',
        audit_rows=[
            f'| {anchor_oid} | 2026-11-15 | §4.1；{ANCHOR_TASK} | POST-MAIN VERIFIED | a |',
            f'| {c_start} | 2026-11-21 | §4.1；B117-START-R1-261121 | POST-MAIN VERIFIED | s |',
        ],
        reg_causes=[{'id': 'S1C-001', 'tasks': ['B117-START-R1-261121']}],
    )
    _commit(repo, {}, 'seed reg', task_id='B117-SEED-261121')

    c_a = _commit(repo, {'docs/a.md': b'1\n'}, 'A', task_id='B117-CLEAN-A-261122')
    # H halted at precommit on 261122/261123 (no main commit); registered during clean batch B
    rows_b = [
        f'| {anchor_oid} | 2026-11-15 | §4.1；{ANCHOR_TASK} | POST-MAIN VERIFIED | a |',
        f'| {c_start} | 2026-11-21 | §4.1；B117-START-R1-261121 | POST-MAIN VERIFIED | s |',
        f'| {c_a} | 2026-11-22 | §4.1；B117-CLEAN-A-261122 | POST-MAIN VERIFIED | ok |',
    ]
    c_b = _commit(
        repo,
        {
            'docs/b.md': b'2\n',
            'docs/governance/s1-registry.json': json.dumps({
                'schema': 2,
                'causes': [
                    {'id': 'S1C-001', 'tasks': ['B117-START-R1-261121']},
                    {'id': 'S1C-002', 'tasks': ['B117-HALTED-H-261123']},
                ],
            }) + '\n',
        },
        'B registers H',
        task_id='B117-CLEAN-B-261124',
    )
    rows_b.append(f'| {c_b} | 2026-11-24 | §4.1；B117-CLEAN-B-261124 | POST-MAIN VERIFIED | reg H |')
    _write_docs(
        repo,
        freeze_line='**治理凍結**：USER 2026-11-20 決定；連續無 S1 批數 2/20；最後歸零：B117-START-R1-261121（S1）；起算：B117-START-R1-261121（不含）',
        audit_rows=rows_b,
        reg_causes=[
            {'id': 'S1C-001', 'tasks': ['B117-START-R1-261121']},
            {'id': 'S1C-002', 'tasks': ['B117-HALTED-H-261123']},
        ],
    )
    d6_bad = cc.count_d6(str(repo))
    assert d6_bad['count'] == 1
    assert d6_bad['counted_tasks'] == ['B117-CLEAN-B-261124']
    assert d6_bad['repo_resets'] == ['B117-HALTED-H-261123']
    assert d6_bad['match'] is False
    assert d6_bad['reset_mismatch'] == {'declared': 'B117-START-R1-261121', 'observed': 'B117-HALTED-H-261123'}

    # Even if declared=1 by accident while last_reset still names START, match stays False with reset_mismatch=
    _write_docs(
        repo,
        freeze_line='**治理凍結**：USER 2026-11-20 決定；連續無 S1 批數 1/20；最後歸零：B117-START-R1-261121（S1）；起算：B117-START-R1-261121（不含）',
        audit_rows=rows_b,
        reg_causes=[
            {'id': 'S1C-001', 'tasks': ['B117-START-R1-261121']},
            {'id': 'S1C-002', 'tasks': ['B117-HALTED-H-261123']},
        ],
    )
    rc = cc.main(['--repo', str(repo), '--mode', 'd6'])
    out = capsys.readouterr().out
    assert rc == 0
    assert 'match=NO' in out
    assert 'reset_mismatch=declared:B117-START-R1-261121,observed:B117-HALTED-H-261123' in out

    # Fixing last_reset to B117-HALTED-H-261123 yields match=True
    _write_docs(
        repo,
        freeze_line='**治理凍結**：USER 2026-11-20 決定；連續無 S1 批數 1/20；最後歸零：B117-HALTED-H-261123（S1）；起算：B117-START-R1-261121（不含）',
        audit_rows=rows_b,
        reg_causes=[
            {'id': 'S1C-001', 'tasks': ['B117-START-R1-261121']},
            {'id': 'S1C-002', 'tasks': ['B117-HALTED-H-261123']},
        ],
    )
    d6_ok = cc.count_d6(str(repo))
    assert d6_ok['count'] == 1 and d6_ok['match'] is True and d6_ok['reset_mismatch'] is None


def test_d6_registry_import_point_historical_causes_do_not_reset(tmp_path):
    # Mimic beta-1 (4a401422): initial s1-registry import brings historical unmerged S1 <= start_after; must not false-reset.
    repo, anchor_oid = _init_repo(tmp_path)
    c_start = _commit(repo, {'docs/s.md': b'0\n'}, 'start', task_id='B117-START-R1-261122')
    c_after1 = _commit(repo, {'docs/a.md': b'1\n'}, 'after1', task_id='B117-A1-261123')
    c_import = _commit(
        repo,
        {
            'docs/governance/s1-registry.json': json.dumps({
                'schema': 2,
                'causes': [
                    {'id': 'S1C-001', 'tasks': ['B117-OLD-UNMERGED-261121']},
                    {'id': 'S1C-002', 'tasks': ['B117-START-R1-261122']},
                ],
            }) + '\n',
        },
        'import reg',
        task_id='B117-BETA1-REG-261124',
    )
    rows = [
        f'| {anchor_oid} | 2026-11-15 | §4.1；{ANCHOR_TASK} | POST-MAIN VERIFIED | a |',
        f'| {c_start} | 2026-11-22 | §4.1；B117-START-R1-261122 | POST-MAIN VERIFIED | s |',
        f'| {c_after1} | 2026-11-23 | §4.1；B117-A1-261123 | POST-MAIN VERIFIED | ok |',
        f'| {c_import} | 2026-11-24 | §4.1；B117-BETA1-REG-261124 | POST-MAIN VERIFIED | imp |',
    ]
    _write_docs(
        repo,
        freeze_line='**治理凍結**：USER 2026-11-20 決定；連續無 S1 批數 2/20；最後歸零：B117-START-R1-261122（S1）；起算：B117-START-R1-261122（不含）',
        audit_rows=rows,
        reg_causes=[
            {'id': 'S1C-001', 'tasks': ['B117-OLD-UNMERGED-261121']},
            {'id': 'S1C-002', 'tasks': ['B117-START-R1-261122']},
        ],
    )
    d6 = cc.count_d6(str(repo))
    assert d6['count'] == 2
    assert d6['repo_resets'] == []
    assert d6['match'] is True


def test_d6_uncommitted_worktree_halted_s1_resets_to_zero(tmp_path):
    repo, anchor_oid = _init_repo(tmp_path)
    c1 = _commit(repo, {'docs/a.md': b'1\n'}, 'c1', task_id='B117-C1-261122')
    rows = [
        f'| {anchor_oid} | 2026-11-15 | §4.1；{ANCHOR_TASK} | POST-MAIN VERIFIED | a |',
        f'| {c1} | 2026-11-22 | §4.1；B117-C1-261122 | POST-MAIN VERIFIED | ok |',
    ]
    _write_docs(
        repo,
        freeze_line=f'**治理凍結**：USER 2026-11-20 決定；連續無 S1 批數 1/20；最後歸零：{ANCHOR_TASK}（OK）；起算：{ANCHOR_TASK}（不含）',
        audit_rows=rows,
        reg_causes=[],
    )
    _commit(repo, {}, 'sync', task_id='B117-SYNC-261123')

    # Uncommitted worktree registration of a halted S1 must reset worktree count to 0 (--from-git stays 1)
    _write_docs(
        repo,
        freeze_line=f'**治理凍結**：USER 2026-11-20 決定；連續無 S1 批數 1/20；最後歸零：{ANCHOR_TASK}（OK）；起算：{ANCHOR_TASK}（不含）',
        audit_rows=rows,
        reg_causes=[{'id': 'S1C-001', 'tasks': ['B117-NEW-HALT-261124']}],
    )
    d6_wt = cc.count_d6(str(repo))
    assert d6_wt['count'] == 0 and d6_wt['match'] is False
    assert d6_wt['repo_resets'] == ['B117-NEW-HALT-261124']
    assert cc.count_d6(str(repo), use_git=True)['count'] == 1


def test_d6_committed_audit_row_task_excluded_from_registry_diff_resets(tmp_path):
    # Part A: Historical committed batch retroactively added to s1-registry in a later commit must NOT re-reset (kills B1e).
    (tmp_path / 'hist').mkdir()
    repo_a, anchor_a = _init_repo(tmp_path / 'hist')
    c_old = _commit(repo_a, {'docs/old.md': b'old\n'}, 'old', task_id='B117-OLD-COMMITTED-261119')
    c_start = _commit(repo_a, {'docs/s.md': b'0\n'}, 'start', task_id='B117-START-R1-261121')
    _write_docs(
        repo_a,
        freeze_line='**治理凍結**：USER 2026-11-20 決定；連續無 S1 批數 0/20；最後歸零：B117-START-R1-261121（S1）；起算：B117-START-R1-261121（不含）',
        audit_rows=[
            f'| {anchor_a} | 2026-11-15 | §4.1；{ANCHOR_TASK} | POST-MAIN VERIFIED | a |',
            f'| {c_old} | 2026-11-19 | §4.1；B117-OLD-COMMITTED-261119 | POST-MAIN VERIFIED | old |',
            f'| {c_start} | 2026-11-21 | §4.1；B117-START-R1-261121 | POST-MAIN VERIFIED | s |',
        ],
        reg_causes=[{'id': 'S1C-001', 'tasks': ['B117-START-R1-261121']}],
    )
    _commit(repo_a, {}, 'seed reg', task_id='B117-SEED-261121')

    c_clean1 = _commit(repo_a, {'docs/c1.md': b'1\n'}, 'clean1', task_id='B117-CLEAN-1-261122')
    c_reg = _commit(
        repo_a,
        {
            'docs/c2.md': b'2\n',
            'docs/governance/s1-registry.json': json.dumps({
                'schema': 2,
                'causes': [
                    {'id': 'S1C-001', 'tasks': ['B117-START-R1-261121']},
                    {'id': 'S1C-002', 'tasks': ['B117-OLD-COMMITTED-261119']},
                ],
            }) + '\n',
        },
        'clean2 retroactively registers B117-OLD-COMMITTED-261119',
        task_id='B117-CLEAN-2-REG-261123',
    )
    _write_docs(
        repo_a,
        freeze_line='**治理凍結**：USER 2026-11-20 決定；連續無 S1 批數 2/20；最後歸零：B117-START-R1-261121（S1）；起算：B117-START-R1-261121（不含）',
        audit_rows=[
            f'| {anchor_a} | 2026-11-15 | §4.1；{ANCHOR_TASK} | POST-MAIN VERIFIED | a |',
            f'| {c_old} | 2026-11-19 | §4.1；B117-OLD-COMMITTED-261119 | POST-MAIN VERIFIED | old |',
            f'| {c_start} | 2026-11-21 | §4.1；B117-START-R1-261121 | POST-MAIN VERIFIED | s |',
            f'| {c_clean1} | 2026-11-22 | §4.1；B117-CLEAN-1-261122 | POST-MAIN VERIFIED | ok1 |',
            f'| {c_reg} | 2026-11-23 | §4.1；B117-CLEAN-2-REG-261123 | POST-MAIN VERIFIED | ok2 |',
        ],
        reg_causes=[
            {'id': 'S1C-001', 'tasks': ['B117-START-R1-261121']},
            {'id': 'S1C-002', 'tasks': ['B117-OLD-COMMITTED-261119']},
        ],
    )
    d6_a = cc.count_d6(str(repo_a))
    assert d6_a['count'] == 2, d6_a
    assert d6_a['counted_tasks'] == ['B117-CLEAN-1-261122', 'B117-CLEAN-2-REG-261123'], d6_a
    assert d6_a['repo_resets'] == [], d6_a
    assert d6_a['match'] is True and d6_a['reset_mismatch'] is None, d6_a

    # Part B: Batch with its own POST-MAIN VERIFIED row in window added to s1-registry later resets ONCE at its own row.
    (tmp_path / 'inwin').mkdir()
    repo_b, anchor_b = _init_repo(tmp_path / 'inwin')
    c_start_b = _commit(repo_b, {'docs/s.md': b'0\n'}, 'start', task_id='B117-START-R1-261121')
    _write_docs(
        repo_b,
        freeze_line='**治理凍結**：USER 2026-11-20 決定；連續無 S1 批數 0/20；最後歸零：B117-START-R1-261121（S1）；起算：B117-START-R1-261121（不含）',
        audit_rows=[
            f'| {anchor_b} | 2026-11-15 | §4.1；{ANCHOR_TASK} | POST-MAIN VERIFIED | a |',
            f'| {c_start_b} | 2026-11-21 | §4.1；B117-START-R1-261121 | POST-MAIN VERIFIED | s |',
        ],
        reg_causes=[{'id': 'S1C-001', 'tasks': ['B117-START-R1-261121']}],
    )
    _commit(repo_b, {}, 'seed reg', task_id='B117-SEED-261121')
    c_own = _commit(repo_b, {'docs/own.md': b'o\n'}, 'own s1', task_id='B117-OWN-S1-261122')
    c_clean1_b = _commit(repo_b, {'docs/c1.md': b'1\n'}, 'clean1', task_id='B117-CLEAN-1-261123')
    c_reg_b = _commit(
        repo_b,
        {
            'docs/c2.md': b'2\n',
            'docs/governance/s1-registry.json': json.dumps({
                'schema': 2,
                'causes': [
                    {'id': 'S1C-001', 'tasks': ['B117-START-R1-261121']},
                    {'id': 'S1C-002', 'tasks': ['B117-OWN-S1-261122']},
                ],
            }) + '\n',
        },
        'register B117-OWN-S1-261122 in later commit',
        task_id='B117-CLEAN-2-REG-261124',
    )
    _write_docs(
        repo_b,
        freeze_line='**治理凍結**：USER 2026-11-20 決定；連續無 S1 批數 2/20；最後歸零：B117-OWN-S1-261122（S1）；起算：B117-START-R1-261121（不含）',
        audit_rows=[
            f'| {anchor_b} | 2026-11-15 | §4.1；{ANCHOR_TASK} | POST-MAIN VERIFIED | a |',
            f'| {c_start_b} | 2026-11-21 | §4.1；B117-START-R1-261121 | POST-MAIN VERIFIED | s |',
            f'| {c_own} | 2026-11-22 | §4.1；B117-OWN-S1-261122 | POST-MAIN VERIFIED | own |',
            f'| {c_clean1_b} | 2026-11-23 | §4.1；B117-CLEAN-1-261123 | POST-MAIN VERIFIED | ok1 |',
            f'| {c_reg_b} | 2026-11-24 | §4.1；B117-CLEAN-2-REG-261124 | POST-MAIN VERIFIED | ok2 |',
        ],
        reg_causes=[
            {'id': 'S1C-001', 'tasks': ['B117-START-R1-261121']},
            {'id': 'S1C-002', 'tasks': ['B117-OWN-S1-261122']},
        ],
    )
    d6_b = cc.count_d6(str(repo_b))
    assert d6_b['count'] == 2, d6_b
    assert d6_b['counted_tasks'] == ['B117-CLEAN-1-261123', 'B117-CLEAN-2-REG-261124'], d6_b
    assert d6_b['repo_resets'] == ['B117-OWN-S1-261122'], d6_b
    assert d6_b['match'] is True and d6_b['reset_mismatch'] is None, d6_b
