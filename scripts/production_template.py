#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repo-owned deterministic production prose template.

`prompt_builder.py auto-production --repo R --definition D --out-dir O` accepts a
normal canonical production definition with an additional `production_prose` object.
It constructs the fixed Executor prose; `prompt_builder.build` still owns ALL machine
blocks, author hashes, allowed/required paths, must-read closure and E24 dispositions.
The Macro Auditor alone authors and approves the structured goal/decisions and delivers
final bytes. Generation is never Macro PASS, E27 acceptance, or Executor authorization.
"""
import json
import re
import subprocess
import tempfile
from pathlib import Path

import prompt_builder as pb

_DISPOSITIONS = {'UPDATE', 'NO_CHANGE'}
_E27 = {'APPLICABLE_PRE_EXEC_REVIEW', 'NOT_APPLICABLE'}
_BAD = re.compile(r'<<<|BEGIN_HHAI_|END_HHAI_|\{[A-Za-z_][A-Za-z0-9_]*\}|[\x00-\x1f\x7f]')


def _single(value, label):
    pb._require(isinstance(value, str) and 1 <= len(value) <= 700 and not _BAD.search(value)
                and value == value.strip(), label + '_INVALID')
    return value


def _lines(value, label):
    pb._require(isinstance(value, list) and 1 <= len(value) <= 24, label + '_INVALID')
    return '\n'.join(f'- {_single(x, label)}' for x in value)


def _git(repo, *args):
    try:
        p = subprocess.run(['git', '-C', str(repo), *args], stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise pb.BuildError('PRODUCTION_GIT_UNAVAILABLE') from None
    pb._require(p.returncode == 0, 'PRODUCTION_GIT_UNAVAILABLE')
    return p.stdout.decode('ascii').strip()



def canonical_focused(d):
    """One deterministic focused selection for production and auditor-side winemu.

    Code/new author test paths are the source of truth, even for focused=None.
    Existing explicit test selection is preserved and -rs captures Windows skips.
    """
    changed = sorted(p for p in (set(d.get('code_files') or {}) | set(d.get('new_files') or {}))
                     if p.startswith('scripts/tests/') and p.endswith('.py'))
    old = d.get('focused')
    if not changed:
        return old
    pb._require(old is None or (isinstance(old, dict) and isinstance(old.get('pytest_args'), list)
                                and isinstance(old.get('limit_sec'), int)), 'FOCUSED_SOURCE_INVALID')
    args = list(old['pytest_args']) if old else ['-q']
    pb._require(all(isinstance(a, str) and a for a in args), 'FOCUSED_SOURCE_INVALID')
    if '-rs' not in args and '-ra' not in args:
        args.insert(1 if args and args[0] == '-q' else 0, '-rs')
    for rel in changed:
        if rel not in args:
            args.append(rel)
    return {'pytest_args': args, 'limit_sec': max(old['limit_sec'], 1800) if old else 1800}


def auto_production(repo, definition, out_dir):
    """Create production prompt; all machine-derived statements use the SAME definition as builder."""
    repo, definition, out_dir = Path(repo).resolve(), Path(definition).resolve(), Path(out_dir).resolve()
    pb._require(repo != out_dir and repo not in out_dir.parents and out_dir not in repo.parents,
                'PRODUCTION_OUT_DIR_INVALID')
    pb._require(not out_dir.exists() or (out_dir.is_dir() and not any(out_dir.iterdir())),
                'PRODUCTION_OUTPUT_EXISTS')
    pb._require(_git(repo, 'rev-parse', '--is-shallow-repository') == 'false', 'PRODUCTION_SHALLOW')
    try:
        d = json.loads(pb.read_text(definition, 'PRODUCTION_DEFINITION'))
    except ValueError:
        raise pb.BuildError('PRODUCTION_DEFINITION_JSON_INVALID') from None
    pb._require(isinstance(d, dict) and d.get('kind') == 'production' and d.get('schema_version') == 1,
                'PRODUCTION_DEFINITION_INVALID')
    # B-118 first activation: no silent false when the auditor forgets this field.
    pb._require('bundle_output' in d, 'PRODUCTION_BUNDLE_OUTPUT_REQUIRED')
    pb._require(type(d['bundle_output']) is bool, 'PRODUCTION_BUNDLE_OUTPUT_INVALID')
    pb._require(not any(k in d for k in ('start', 'substitutions', 'prose_head', 'prose_tail')),
                'PRODUCTION_FIELD_UNSUPPORTED')
    base = d.get('base_oid')
    pb._require(isinstance(base, str) and pb.batch_runner.OID_RE.fullmatch(base), 'PRODUCTION_BASE_INVALID')
    pb._require(_git(repo, 'rev-parse', 'refs/remotes/origin/main') == base,
                'PRODUCTION_BASE_DRIFT')
    branch = d.get('branch')
    pb.require_classifiable_branch(branch)
    prose = d.get('production_prose')
    pb._require(isinstance(prose, dict) and set(prose) == {
        'goal', 'scope', 'invariants', 'stops', 'e27', 'finding_disposition',
        'backlog_disposition', 'taskboard_disposition', 'audit_log_disposition',
    }, 'PRODUCTION_PROSE_SCHEMA_INVALID')
    goal = _single(prose['goal'], 'GOAL')
    scope = _lines(prose['scope'], 'SCOPE')
    invariants = _lines(prose['invariants'], 'INVARIANTS')
    stops = _lines(prose['stops'], 'STOPS')
    fd = _single(prose['finding_disposition'], 'FINDING')
    pb._require(fd == 'NONE' or re.fullmatch(r'(?:EXISTING|CURRENT|NEW) [A-G]-[0-9]+', fd),
                'FINDING_DISPOSITION_INVALID')
    for k in ('backlog_disposition', 'taskboard_disposition', 'audit_log_disposition'):
        pb._require(prose[k] in _DISPOSITIONS, 'DISPOSITION_INVALID')
    pb._require(prose['e27'] in _E27, 'E27_INVALID')
    authors = sorted(set(d.get('code_files') or {}) | set(d.get('new_files') or {}) |
                     {op.get('path') for op in (d.get('text_ops') or [])})
    pb._require(bool(authors) and all(isinstance(x, str) for x in authors), 'AUTHOR_PATHS_INVALID')
    for path in authors:
        pb.check_repo_path(path)
    changed = sorted(set(authors) | set(pb.batch_runner.GENERATED))
    pb._require(all(x in changed for x in pb.batch_runner.GENERATED), 'GENERATED_MISSING')
    # Derive the canonical focused list once, for prose and the actual runner machine block.
    d['focused'] = canonical_focused(d)
    # Use the runner's own step derivation; do not maintain a second e24/focused decision.
    preview = (pb.batch_runner.native_preview_required(changed)
               and pb.batch_runner.base_supports_native_preview(repo, base))
    steps = pb.batch_runner.derive_steps({'kind': 'production', 'e24': d.get('e24') is True,
                                          'native_preview': preview,
                                          'focused': d.get('focused'), 'bundle_output': d.get('bundle_output', False)}) + ['timing']
    cmds = '\n'.join(pb.production_runner_commands('{TASK_ID}', steps, preview))
    preview_scope = (
        ' 本批 native_preview 核准 runner 在 %TEMP% 自建隔離模擬、寫入並保留本批證據。'
        ' BASE_NOT_IN_SOURCE 時立即 S1，轉交既有輸出，禁止在 W2 fetch 或自行重跑。'
        if preview else '')
    preview_contract = '\nnative_preview_external_write: TEMP_ISOLATED_NATIVE_PREVIEW' if preview else ''
    selfcheck = d.get('auditor_selfcheck')
    declaration = ''
    if selfcheck is not None:
        pb.validate_auditor_selfcheck(selfcheck)
        declaration = ('\n審計官自檢聲明\n' +
                       pb.block('AUDITOR_SELFCHECK_JSON', json.dumps(selfcheck, ensure_ascii=False, indent=1)))
    # Both the prose and all machine data are built from one definition: never copy facts from old prompts.
    head = f'''{{TASK_ID}} — repo-owned production prose (GOAL_SPEC)

你是 Antigravity IDE Agent，僅擔任本批 Executor，不是審查官、第二意見或權限裁決者。本提示詞經 USER 任命之唯一 Macro Auditor 審核後交付；產生工具本身不授權任何 repo 操作。

一、目標與決策（由審查官結構化輸入；不得自行擴張）
TASK_ID={{TASK_ID}}；Base={{BASE_OID}}；branch={{BRANCH}}；batch_mode=GOAL_SPEC。
目標：{goal}
已裁決範圍：
{scope}
不得破壞之不變量：
{invariants}

二、確定性機器事實與權限
本批變更路徑由單一 definition 的作者檔來源自動推導，含固定 canonical 生成檔，恰為：
''' + '\n'.join('- ' + x for x in changed) + f'''
Allowed and required tracked mutation paths 均為 {{ALLOWED}}。本批不授權 main advancement、遠端 ref 刪除、破壞性 Git、憑證讀取、GitHub API 寫入、跨 session 存取、其他 task artifact 讀取、repo 外資料列舉、額外未核准寫檔。bundle_output={'true' if d.get('bundle_output') else 'false'}；僅 bundle_output=true 時，於 push 後新 bundle 階段核准在 Downloads 新增一份符合命名規範之 bundle，除本批新 S1 蒐證工具在本 repo .git 下自建唯一受限 scratch 且僅清除自己新建 scratch 外，其餘 repo 外寫入／清理仍禁止。{preview_scope}
E24={'REQUIRED' if d.get('e24') is True else 'NONE'}；E27={prose['e27']}。E27 結論不取代 Macro 最終提示詞授權；不得擅自引用任何第二意見 PASS。

三、失敗停止與開始前就緒
每個 runner 命令只執行一次、按順序，必須觀察真正結束且 exit 0 才能前進；背景執行中、排隊中或 PENDING 不等於成功。任何非零、超時、歧義、來源或工作區不符立即 S1 STOP，不自行重跑、提高 timeout、修改 gate、修改提示詞、reset、rebase、amend、stash、force push、hook bypass、刪除檔案或自行修補。S1 STOP 立即停止後續 production 步驟：新版 runner 在同一失敗命令內自動輸出 timing／回覆；若已出現 TIMING 或 EXECUTOR_REPLY_UNAVAILABLE，不得再執行 timing 或其他工具。首批 runner_update 的 apply 階段（含）以前仍可能由舊 runner 回報 S1 而無 timing，此過渡情況才准執行第五節 timing 一次；此後立即轉交並結束。成功路徑照第五節順序於最後執行 timing 一次。原 Executor 對話必須已停止且無 Queued 指令；IDE 作用中工作區必須為使用者指定的正式 workspace。Mutation 之前 fresh reread 所有規則與本批作者程式，驗證 Base、clean worktree、branch、scope、操作步驟及所有機械契約；發現規格衝突或缺件先停止。特別停止條件：
{stops}

四、動手前必讀（使用 IDE 原生檢視逐檔讀到最後一行）
{{MUST_READ}}
若 IDE 原生讀取不可行，立即 S1 NATIVE_VIEW_UNAVAILABLE，禁止以 terminal 或 Python 替代。

五、唯一 canonical runner 操作順序（各命令一次）
{cmds}

六、Executor 固定回覆與唯一終點
完成 timing 後，若 runner 印出 EXECUTOR_REPLY_BEGIN／EXECUTOR_REPLY_END 且 REPLY_SELF_CHECK=PASS，僅逐字複製兩個 marker 之間的行，並立即結束本次執行；不得額外執行任何工具、讀檔、自我驗證或寫檔。格式通過只證明可轉交，不代表 CI PASS；CI PENDING 僅可稱未查證，不得合成或更改 CI_RUN。
若 runner 印出 EXECUTOR_REPLY_UNAVAILABLE，或舊 runner 在 apply 前就發生 S1、沒有產生此區塊，則回退到本節下列原有人工逐字轉交規則，不得為補回覆再執行額外命令；僅回報原始 runner 已輸出的內容與不可用代碼。
原有回覆規則：成功時逐字轉交已有的 CI_RUN candidate、COMMIT、TIMING、STATE；若有 bundle，還須逐字轉交 BUNDLE_FILE=、ORIGIN_MAIN=、HANDOFF_TO_AUDITOR=、HANDOFF_CARD_SHA256=、HANDOFF_CARD_JSON= 或 BUNDLE FAILED <CODE>。若 CI 是 PENDING，不得自行宣稱 PASS。S1 時只逐字轉交已出現的 S1、S1_PRIMARY、S1_DETAIL、S1_EVIDENCE、S1_FULL_CAPTURE、BOUNDED、TIMING、STATE 相關行，不能補造不存在的證據，不捏造 CI Run／job ID 或 PASS。
回覆最後一行逐字為「以上是 Antigravity IDE Agent 的回覆。」

七、machine blocks（全部由 canonical builder 產生，不可修改）
'''
    tail = f'''
八、執行契約與審查處置（此段由 repo template 生成）
{declaration}
USER 常設決定（2026-10-13）：確定性作業機械化，不以放寬驗收換速度。本批 findings={fd}；E27={prose['e27']}；未核實之未來 candidate 或 post-main CI 不預先宣稱 PASS。Execution record、fingerprint 僅以 canonical generate 階段生成，不能由 Executor 仿造。

{'BEGIN_HHAI_' + 'PROMPT_MANIFEST'}
schema_version: 1
batch_mode: GOAL_SPEC
base_oid: {{BASE_OID}}
finding_disposition: {fd}
backlog_disposition: {prose['backlog_disposition']}
taskboard_disposition: {prose['taskboard_disposition']}
audit_log_disposition: {prose['audit_log_disposition']}
rules_reread_required: true
fixed_signature_required: true
destructive_git_allowed: false
{'END_HHAI_' + 'PROMPT_MANIFEST'}

{'BEGIN_HHAI_' + 'EXECUTION_CONTRACT'}
contract_version: 2
task_id: {{TASK_ID}}
base_oid: {{BASE_OID}}
main_advancement: FORBIDDEN
authorized_main_sha: NONE
remote_ref_deletion: FORBIDDEN
authorized_delete_refs: NONE
local_destructive_git: FORBIDDEN
credential_access: FORBIDDEN
environment_enumeration: FORBIDDEN
cross_session_access: FORBIDDEN
browser_github_mutation: FORBIDDEN
raw_actions_log_access: EXTERNAL_MACRO_ONLY
branch_creation: GIT_SWITCH_C
hook_bypass: FORBIDDEN
goal_pressure_policy: SAFETY_BOUNDARY_WINS
ide_ephemeral_guards_required: false
allowed_mutation_paths: {{ALLOWED}}
required_mutation_paths: {{ALLOWED}}
max_plan_revisions: 3
execution_record_required: true
external_artifact_write: {'DOWNLOADS_BUNDLE_AFTER_PUSH' if d.get('bundle_output') else 'FORBIDDEN'}{preview_contract}
{'END_HHAI_' + 'EXECUTION_CONTRACT'}
'''
    # Both authored prose files are temporary and outside tracked repo. Never modify caller's definition.
    with tempfile.TemporaryDirectory(prefix='hhai-production-prose-') as temp:
        p = Path(temp)
        (p / 'head.txt').write_bytes(head.encode('utf-8'))
        (p / 'tail.txt').write_bytes(tail.encode('utf-8'))
        generated_def = dict(d)
        generated_def.pop('production_prose', None)
        generated_def['prose_head'] = str(p / 'head.txt')
        generated_def['prose_tail'] = str(p / 'tail.txt')
        # The original relative author/e24 files must be anchored to their authoritative definition directory.
        for key in ('code_files', 'new_files'):
            if key == 'code_files':
                generated_def[key] = {k: str((definition.parent / v).resolve()) for k, v in d.get(key, {}).items()}
            else:
                generated_def[key] = {k: {**v, 'file': str((definition.parent / v['file']).resolve())}
                                      for k, v in d.get(key, {}).items()}
        if d.get('e24_evidence'):
            generated_def['e24_evidence'] = str((definition.parent / d['e24_evidence']).resolve())
        (p / 'definition.json').write_bytes((json.dumps(generated_def, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        text, authors_map, authored = pb.build(str(repo), str(p / 'definition.json'))
        return pb.write_outputs(str(out_dir), d['task_id'], text, authors_map, authored)
