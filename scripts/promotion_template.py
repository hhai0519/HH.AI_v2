#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B-115 (9) slice 1: repo-owned promotion prose, derived from exactly two candidate facts.

`prompt_builder.py auto-promotion --candidate-oid SHA --candidate-branch BRANCH --repo R --out-dir D`
The generated prompt is only an internal draft until the Macro Auditor independently accepts
the candidate and deliberately delivers the final bytes; CLI generation is not an authorization.
No Git ref is modified; never fetches remote refs, trusts only supplied local full clone.
"""
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

import prompt_builder as pb

HEAD = '''{TASK_ID} — 同一 SHA 候選 main 晉級（零 tracked mutation）

你是 Antigravity IDE Agent，僅擔任此批 Executor，不是審查官或第二意見。唯一依據是本提示詞及 repo 現行規則，不得據此擴大權限。

一、唯一任務與授權界線
TASK_ID = {TASK_ID}；batch_mode: GOAL_SPEC；Base = {BASE_OID}；candidate = {CANDIDATE_OID}；遠端候選分支 = {BRANCH}。
本提示詞由正式審查官獨立完成此 exact-SHA 候選之 Macro PASS／ACCEPT ALL 後交付；依 USER 同一 SHA 晉級常設授權，只授權 canonical runner 將 main 快轉至 {CANDIDATE_OID}。工具生成行為不取代事前審查，任何遠端 SHA、parent、CI 或工作區漂移即 S1 STOP。
候選修改 runner: {RUNNER_CHANGED}（依 {BASE_OID}..{CANDIDATE_OID} 之實際路徑機械判定）。
候選變更檔案恰為：
{CHANGED_PATHS}

二、權限與失敗停止
每個命令只執行一次；非零、逾時、歧義立即 S1 STOP，不自行重跑或修補。已啟動或背景執行中不算完成；必須觀察 runner 命令真正結束且 exit 0 後才能進下一步。post-main PENDING 不得當作 PASS。
Allowed tracked mutation paths = NONE，Required tracked mutation paths = NONE。只能由 runner 依所綁定 SHA 完成同一 SHA 快轉；origin/main、candidate branch、parent 或 CI 不符合時須 S1 STOP。禁止手動 git/gh/API 查證補資料、push 或另建 commit；禁止 force、reset、amend、stash、delete、hook bypass、讀取其他對話／其他 task artifact 或憑證。前一 Executor 已停止且無 Queued 指令，工作區必須為 IDE 原生作用中工作區。禁止未授權 repo 外存取。

三、動手前必讀（IDE 原生檢視工具讀至結尾）
{MUST_READ}
無法讀取即 S1 NATIVE_VIEW_UNAVAILABLE，不得改用 shell 取代原生檢視。

四、唯一 runner 執行順序（各一次，不可自行增加命令）
python scripts/batch_runner.py --task-id {TASK_ID} preflight
python scripts/batch_runner.py --task-id {TASK_ID} verify
python scripts/batch_runner.py --task-id {TASK_ID} promote
python scripts/batch_runner.py --task-id {TASK_ID} postmain
python scripts/batch_runner.py --task-id {TASK_ID} timing

五、Executor 最小回覆
成功只逐字複製 runner 的 MAIN、TIMING、STATE 三行；S1 時只逐字複製已有的 S1、S1_DETAIL、TIMING、STATE 行，禁止捏造 CI Run／job ID。最後一行逐字為「以上是 Antigravity IDE Agent 的回覆。」

六、機器區塊（repo prompt_builder 產出，不得人工修改）
'''

TAIL = '''
七、Machine Manifest 與 Execution Contract
本次零 tracked mutation，不寫 TASKBOARD、AUDIT-LOG 或 refactor-backlog，不宣稱當批新裁決；finding_disposition = NONE。E24 = NONE；E27 = N/A（只做既有候選晉級）。

{MANIFEST_BEGIN}
schema_version: 1
batch_mode: GOAL_SPEC
base_oid: {BASE_OID}
finding_disposition: NONE
backlog_disposition: NO_CHANGE
taskboard_disposition: NO_CHANGE
audit_log_disposition: NO_CHANGE
rules_reread_required: true
fixed_signature_required: true
destructive_git_allowed: false
{MANIFEST_END}

{CONTRACT_BEGIN}
contract_version: 2
task_id: {TASK_ID}
base_oid: {BASE_OID}
main_advancement: EXACT_SHA
authorized_main_sha: {CANDIDATE_OID}
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
allowed_mutation_paths: NONE
required_mutation_paths: NONE
max_plan_revisions: 3
execution_record_required: false
{CONTRACT_END}
'''


def _git(repo, *args):
    try:
        result = subprocess.run(['git', '-C', str(repo), *args], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise pb.BuildError('PROMOTION_GIT_UNAVAILABLE') from None
    pb._require(result.returncode == 0, 'PROMOTION_GIT_UNAVAILABLE')
    return result.stdout


def auto_promotion(repo, candidate_oid, candidate_branch, out_dir):
    """Build a fully machine-derived draft from exact candidate oid + branch.

    The caller independently controls source/output paths. A candidate must be the sole
    child of the current origin/main and the named origin remote-tracking ref must match exactly.
    """
    pb._require(isinstance(candidate_oid, str) and pb.batch_runner.OID_RE.fullmatch(candidate_oid),
                'CANDIDATE_OID_INVALID')
    pb.require_classifiable_branch(candidate_branch)
    repo = Path(repo).resolve()
    out_dir = Path(out_dir).resolve()
    pb._require(out_dir != repo and repo not in out_dir.parents and out_dir not in repo.parents,
                'PROMOTION_OUT_DIR_INVALID')
    pb._require(_git(repo, 'rev-parse', '--is-shallow-repository').strip() == b'false', 'PROMOTION_SHALLOW')
    main = _git(repo, 'rev-parse', 'refs/remotes/origin/main').decode().strip()
    pb._require(pb.batch_runner.OID_RE.fullmatch(main) is not None, 'PROMOTION_MAIN_INVALID')
    par = _git(repo, 'rev-list', '--parents', '-n', '1', candidate_oid).decode().split()
    pb._require(len(par) == 2 and par[0] == candidate_oid and par[1] == main, 'PROMOTION_PARENT_MISMATCH')
    # Use only exact refs; do not guess nearby branches or trust a branch name without matching SHA.
    # Local-only branch tips are not evidence that a remotely pushed candidate exists.
    remote = f'refs/remotes/origin/{candidate_branch}'
    pb._require(_git_ref(repo, remote) == candidate_oid, 'PROMOTION_BRANCH_MISMATCH')
    raw = _git(repo, 'diff', '--name-only', '-z', main, candidate_oid)
    try:
        changed = raw.decode('utf-8').split('\0')[:-1]
    except UnicodeDecodeError:
        raise pb.BuildError('PROMOTION_PATH_NOT_UTF8') from None
    pb._require(bool(changed) and len(changed) == len(set(changed)), 'PROMOTION_PATHS_INVALID')
    for path in changed:
        if path not in pb.batch_runner.GENERATED:
            pb.check_repo_path(path)  # generated canonical files are valid diff facts, never author ops
    slug = candidate_branch.removeprefix('batch/').upper().replace('.', '-')
    task = 'PROMOTE-' + slug
    pb._require(pb.batch_runner.TASK_RE.fullmatch(task) is not None, 'PROMOTION_TASK_INVALID')
    # write_outputs also writes authors.json and authored/*: never overwrite any existing output.
    pb._require(not out_dir.exists() or (out_dir.is_dir() and not any(out_dir.iterdir())),
                'PROMOTION_OUTPUT_EXISTS')
    values = {'{MANIFEST_BEGIN}': 'BEGIN_HHAI_' + 'PROMPT_MANIFEST',
              '{MANIFEST_END}': 'END_HHAI_' + 'PROMPT_MANIFEST',
              '{CONTRACT_BEGIN}': 'BEGIN_HHAI_' + 'EXECUTION_CONTRACT',
              '{CONTRACT_END}': 'END_HHAI_' + 'EXECUTION_CONTRACT',
              '{CANDIDATE_OID}': candidate_oid,
              '{CHANGED_PATHS}': '\n'.join('- ' + x for x in changed),
              '{RUNNER_CHANGED}': 'YES' if 'scripts/batch_runner.py' in changed else 'NO'}
    def render(t):
        for k, v in values.items():
            t = t.replace(k, v)
        return t
    with tempfile.TemporaryDirectory(prefix='hhai-promotion-') as tmp:
        d = Path(tmp)
        (d / 'head.txt').write_bytes(render(HEAD).encode('utf-8'))
        (d / 'tail.txt').write_bytes(render(TAIL).encode('utf-8'))
        spec = {'schema_version': 1, 'task_id': task, 'kind': 'promotion', 'base_oid': main,
                'candidate_oid': candidate_oid, 'candidate_branch': candidate_branch,
                'prose_head': 'head.txt', 'prose_tail': 'tail.txt'}
        (d / 'def.json').write_bytes((json.dumps(spec, indent=2) + '\n').encode('utf-8'))
        text, authors, authored = pb.build(str(repo), str(d / 'def.json'))
        return pb.write_outputs(str(out_dir), task, text, authors, authored)


def _git_ref(repo, ref):
    try:
        return _git(repo, 'rev-parse', '--verify', ref).decode().strip()
    except pb.BuildError:
        return None
