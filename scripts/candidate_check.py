#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/candidate_check.py
審查官端候選 commit 機械核對（B-115 C2 變更帳；USER 2026-10-25 D-C2-2 丙）。

  python scripts/candidate_check.py --prompt <TASK_ID>-prompt.txt --candidate <40 碼 commit SHA> [--repo .]

以交付的 production 提示詞（batch_runner.load_spec）為唯一依據，對已 fetch 的候選 commit 依序核對：
  REFS       refs/remotes/origin/main 等於 Base；refs/remotes/origin/<提示詞分支> 等於候選
  PARENT     候選的唯一 parent 是 Base
  SCOPE      Base→候選的異動路徑集合恰等於 allowed_paths（作者檔＋兩個生成檔）；每個路徑在候選的 mode 必須是
             一般檔案（100644 或 100755），且等於 Base 的 mode（新檔為 100644）；symlink、submodule 或只改 mode
             都 FAIL，即使 Base 本身就是 symlink
  LEDGER     以 runner 自己的 build_authors（Base blob 或提示詞新檔區塊，依序套用提示詞的 ops，每個錨點須恰好
             出現一次，結果須等於作者雜湊）重建每個作者檔，候選 blob 必須與重建結果逐位元組相同。狀態檔的 ops
             即 prompt_builder 事前宣告的 text_ops（STATE_FILE_REQUIRES_TEXT_OPS），所以「授權帳不變、實際多改
             一處」或「授權帳列了、實際沒改」都會 FAIL
  GENERATED  在暫存的 --shared clone 檢出候選，執行候選自己的 execution_record verify、fingerprint --verify
             與 check_consistency（與 CI 相同的判定器），三者都必須 exit 0；暫存 clone 用完即刪，不寫入 --repo

輸出固定代碼行，不輸出檔案內容；exit 0＝PASS、1＝FAIL。只讀 --repo（不 fetch、不改 ref、不改 index 或工作樹），
Executor 不執行。所有 Git 呼叫（含 runner 的 build_authors）與三個判定器，都在移除全部 GIT_* 環境變數後執行，
以免 GIT_INDEX_FILE、GIT_DIR、GIT_WORK_TREE 等繼承變數把讀寫導回 --repo；暫存 clone 以 best-effort 刪除。
限制：CI raw log 不在本工具範圍，仍由審查官讀取；GENERATED 使用候選自己的判定器，判定器本身的修改由 E27 與審查負責。
"""

import argparse
import contextlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import batch_runner  # noqa: E402
import prompt_builder  # noqa: E402

OID = re.compile(r'[0-9a-f]{40}')
GENERATED_COMMANDS = (
    ('EXECUTION_RECORD', ['scripts/execution_record.py', 'verify']),
    ('FINGERPRINT', ['scripts/fingerprint.py', '--verify']),
    ('CONSISTENCY', ['scripts/check_consistency.py']),
)


REGULAR_MODES = ('100644', '100755')


@contextlib.contextmanager
def clean_git_environment():
    """在範圍內移除所有 GIT_* 與 AS_IF_COMMITTED 環境變數（離開時還原），讓本工具與 runner 的 Git 呼叫都不被導向。"""
    saved = {k: v for k, v in os.environ.items() if k.startswith('GIT_') or k == 'AS_IF_COMMITTED'}
    for key in saved:
        del os.environ[key]
    try:
        yield
    finally:
        for key in [k for k in os.environ if k.startswith('GIT_') or k == 'AS_IF_COMMITTED']:
            del os.environ[key]
        os.environ.update(saved)


class CheckError(Exception):
    """固定失敗代碼；不帶檔案內容。"""


def _require(cond, code):
    if not cond:
        raise CheckError(code)


def _git(repo, *args):
    proc = subprocess.run(['git', *args], cwd=repo, stdin=subprocess.DEVNULL, capture_output=True, timeout=300)
    return proc.returncode, proc.stdout


def _rev(repo, ref, code):
    rc, out = _git(repo, 'rev-parse', '--verify', '--quiet', ref + '^{commit}')
    oid = out.decode('ascii', 'replace').strip()
    _require(rc == 0 and OID.fullmatch(oid), code)
    return oid


def _blob(repo, rev, path):
    rc, out = _git(repo, 'cat-file', 'blob', rev + ':' + path)
    _require(rc == 0, 'CANDIDATE_BLOB_UNREADABLE')
    return out


def _mode(repo, rev, path):
    """rev 中 path 的 tree mode；不存在回傳 None。"""
    rc, out = _git(repo, 'ls-tree', '-z', rev, '--', path)
    _require(rc == 0, 'TREE_UNREADABLE')
    if not out:
        return None
    return out.split(b' ', 1)[0].decode('ascii', 'replace')


def run_generated(repo, candidate):
    """在暫存 --shared clone 檢出候選，執行候選自己的三個判定器。"""
    with clean_git_environment():
        _run_generated(repo, candidate)


def _run_generated(repo, candidate):
    with tempfile.TemporaryDirectory(prefix='hhai-candidate-check-', ignore_cleanup_errors=True) as tmp:
        clone = os.path.join(tmp, 'c')
        rc, _ = _git(repo, 'clone', '--quiet', '--shared', '--no-checkout', repo, clone)
        _require(rc == 0, 'GENERATED_CLONE_FAILED')
        rc, _ = _git(clone, 'checkout', '--quiet', '--detach', candidate)
        _require(rc == 0, 'GENERATED_CHECKOUT_FAILED')
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        for name, args in GENERATED_COMMANDS:
            try:
                proc = subprocess.run([sys.executable, *args], cwd=clone, env=env, stdin=subprocess.DEVNULL,
                                      capture_output=True, timeout=1200)
            except (subprocess.TimeoutExpired, OSError):
                raise CheckError('GENERATED_' + name + '_FAILED')
            _require(proc.returncode == 0, 'GENERATED_' + name + '_FAILED')


def check_candidate(repo, prompt_path, candidate, generated=run_generated):
    """回傳 (task, 路徑數, op 數, 作者檔數)。任何不符即 CheckError。"""
    with clean_git_environment():
        return _check_candidate(repo, prompt_path, candidate, generated)


def _check_candidate(repo, prompt_path, candidate, generated):
    _require(isinstance(candidate, str) and OID.fullmatch(candidate), 'CANDIDATE_SHA_INVALID')
    task, data = prompt_builder.prompt_task(prompt_path)
    lines = batch_runner.prompt_lines(data)
    try:
        spec = batch_runner.load_spec(lines, task)
    except batch_runner.Halt:
        raise CheckError('PROMPT_SPEC_INVALID')
    _require(spec['kind'] == 'production', 'KIND_NOT_SUPPORTED')
    base = spec['base_oid']

    _require(_rev(repo, candidate, 'CANDIDATE_UNAVAILABLE') == candidate, 'CANDIDATE_UNAVAILABLE')
    _require(_rev(repo, 'refs/remotes/origin/main', 'ORIGIN_MAIN_UNAVAILABLE') == base, 'ORIGIN_MAIN_NOT_BASE')
    _require(_rev(repo, 'refs/remotes/origin/' + spec['branch'], 'BRANCH_REF_UNAVAILABLE') == candidate,
             'BRANCH_REF_NOT_CANDIDATE')
    rc, out = _git(repo, 'rev-list', '--parents', '-n', '1', candidate)
    _require(rc == 0 and out.decode('ascii', 'replace').split()[1:] == [base], 'PARENT_NOT_BASE')

    rc, out = _git(repo, 'diff', '--name-only', '-z', '--no-renames', base, candidate)
    _require(rc == 0, 'DIFF_UNREADABLE')
    changed = sorted(p for p in out.decode('utf-8', 'replace').split('\0') if p)
    allowed = batch_runner.allowed_paths(spec)
    _require(changed == allowed, 'SCOPE_MISMATCH')
    for path in changed:
        mode = _mode(repo, candidate, path)
        _require(mode in REGULAR_MODES and mode == (_mode(repo, base, path) or '100644'), 'MODE_MISMATCH')

    kinds = {entry['source']['kind'] for entry in spec['authors'].values()}
    _require(kinds <= {'base', 'block'}, 'SOURCE_KIND_UNSUPPORTED')
    try:
        texts = batch_runner.build_authors(repo, spec, lines)
    except batch_runner.Halt as exc:
        raise CheckError('LEDGER_' + str(exc))
    for path in sorted(texts):
        _require(_blob(repo, candidate, path) == texts[path].encode('utf-8'), 'LEDGER_MISMATCH')

    generated(repo, candidate)
    return task, len(changed), len(spec['ops']), len(texts)


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Macro-side candidate commit check (B-115 C2).')
    parser.add_argument('--prompt', required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--repo', default='.')
    args = parser.parse_args(argv)
    repo = os.path.abspath(args.repo)
    try:
        task, paths, ops, authors = check_candidate(repo, args.prompt, args.candidate)
    except (CheckError, prompt_builder.BuildError) as exc:
        print('CANDIDATE_CHECK FAIL ' + str(exc))
        return 1
    print('CANDIDATE_CHECK TASK=' + task + ' CANDIDATE=' + args.candidate)
    print('CANDIDATE_CHECK REFS=PASS PARENT=PASS')
    print('CANDIDATE_CHECK SCOPE=PASS PATHS=' + str(paths))
    print('CANDIDATE_CHECK LEDGER=PASS OPS=' + str(ops) + ' AUTHORS=' + str(authors))
    print('CANDIDATE_CHECK GENERATED=PASS')
    print('CANDIDATE_CHECK RESULT=PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
