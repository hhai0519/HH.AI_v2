"""
CHECK 17（Batch Spec 重放一致性）與 CHECK 18（audited-* tag 名實一致）的正反例測試。

依 `.claude/rules/auditor-protocol.md` §5.6：反例必須用真實輸入形狀，
不得只測邏輯。因此本檔每個測試都建立一個真的 git repo、真的 commit、
真的 tag，不使用 mock。
"""
import os
import subprocess
import sys
import tempfile

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import check_consistency as cc  # noqa: E402


def _run(cwd, *args):
    res = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True)
    assert res.returncode == 0, f"{args} failed: {res.stderr}"
    return res.stdout


def _init_repo(d):
    _run(d, "git", "init", "-q", "-b", "main")
    _run(d, "git", "config", "user.email", "t@t")
    _run(d, "git", "config", "user.name", "t")


def _write(d, rel, text):
    p = os.path.join(d, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _commit(d, msg):
    _run(d, "git", "add", "-A")
    _run(d, "git", "commit", "-q", "-m", msg)
    return _run(d, "git", "rev-parse", "--short=7", "HEAD").strip()


SPEC_TMPL = """HEAD: {base}

=== MOD 1 ===
file: docs/T.md
mode: replace
--- ANCHOR ---
{anchor}
--- PAYLOAD ---
{payload}
--- END MOD ---
"""


# ----------------------------- CHECK 17 -----------------------------

def test_17_no_spec_is_skipped_not_failed():
    """沒有規格的一般維護 commit 必須跳過，不得強迫產生虛假規格。"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "A\n")
        _commit(d, "c1")
        _write(d, "docs/T.md", "B\n")
        _commit(d, "c2")
        fails, infos = cc.check_17_spec_replay(d)
        assert fails == []
        assert any("跳過重放" in i for i in infos)


def test_17_faithful_replay_passes():
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "A\nB\nC\n")
        base = _commit(d, "c1")
        _write(d, "docs/T.md", "A\nZ\nC\n")
        _write(d, "docs/batches/%s-x.spec.txt" % base,
               SPEC_TMPL.format(base=base, anchor="B", payload="Z"))
        _commit(d, "c2")
        fails, infos = cc.check_17_spec_replay(d)
        assert fails == [], fails
        assert any("逐位元相符" in i for i in infos)


def test_17_glyph_substitution_fails():
    """10f7e31 的真實事故形狀：規格說寫『的』，實際 commit 是日文假名。"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "A\nB\nC\n")
        base = _commit(d, "c1")
        _write(d, "docs/T.md", "A\n衝突の成因\nC\n")   # 實際：日文 の
        _write(d, "docs/batches/%s-x.spec.txt" % base,
               SPEC_TMPL.format(base=base, anchor="B", payload="衝突的成因"))
        _commit(d, "c2")
        fails, _ = cc.check_17_spec_replay(d)
        assert any("位元組不一致" in f for f in fails), fails


def test_17_stray_blank_line_fails():
    """多一個空行也必須 FAIL——四項標準驗證都看不到這種差異。"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "A\nB\nC\n")
        base = _commit(d, "c1")
        _write(d, "docs/T.md", "A\nZ\n\nC\n")
        _write(d, "docs/batches/%s-x.spec.txt" % base,
               SPEC_TMPL.format(base=base, anchor="B", payload="Z"))
        _commit(d, "c2")
        fails, _ = cc.check_17_spec_replay(d)
        assert any("位元組不一致" in f for f in fails), fails


def test_17_undeclared_file_change_fails():
    """規格未宣告卻被修改的檔案必須被抓到。"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "A\nB\nC\n")
        _write(d, "docs/OTHER.md", "keep\n")
        base = _commit(d, "c1")
        _write(d, "docs/T.md", "A\nZ\nC\n")
        _write(d, "docs/OTHER.md", "smuggled\n")
        _write(d, "docs/batches/%s-x.spec.txt" % base,
               SPEC_TMPL.format(base=base, anchor="B", payload="Z"))
        _commit(d, "c2")
        fails, _ = cc.check_17_spec_replay(d)
        assert any("規格未宣告卻被修改的檔案" in f and "docs/OTHER.md" in f
                   for f in fails), fails


EXEC_LOG_HEADER = (
    "# 執行者檢查紀錄\n\n"
    "| 批次 commit | 日期 | 檢查範圍 | 結果 | 攔截紀錄 |\n"
    "|---|---|---|---|---|\n"
)


def test_17_fingerprint_generated_artifact_replacement_passes():
    """TEST A: fingerprint snapshot 允許 JSON replacement/deletions，CHECK 17 不得報錯。"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "A\nB\nC\n")
        _write(d, "docs/fingerprints/exec-latest.json", '{\n  "lines": 3,\n  "sha256": "old"\n}\n')
        base = _commit(d, "c1")
        _write(d, "docs/T.md", "A\nZ\nC\n")
        # 更新 fingerprint JSON，產生 replacement/deletions 行
        _write(d, "docs/fingerprints/exec-latest.json", '{\n  "lines": 3,\n  "sha256": "new"\n}\n')
        _write(d, "docs/batches/%s-x.spec.txt" % base,
               SPEC_TMPL.format(base=base, anchor="B", payload="Z"))
        _commit(d, "c2")
        fails, infos = cc.check_17_spec_replay(d)
        assert fails == [], fails
        assert any("fingerprint artifact integrity delegated" in i for i in infos)


def test_17_exec_log_legal_transition_passes():
    """TEST B: EXEC-LOG 合法 transition：parent 最後一列『本批』，child 回填 parent hash 並追加新『本批』。"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "A\nB\nC\n")
        _write(d, "docs/EXEC-LOG.md", EXEC_LOG_HEADER +
               "| BOOTSTRAP | 2026-09-05 | 建立 | 通過 | 無 |\n"
               "| 本批 | 2026-09-11 | 範圍 | 通過 | 紀錄 |\n")
        base = _commit(d, "c1")
        _write(d, "docs/T.md", "A\nZ\nC\n")
        _write(d, "docs/EXEC-LOG.md", EXEC_LOG_HEADER +
               "| BOOTSTRAP | 2026-09-05 | 建立 | 通過 | 無 |\n"
               f"| {base[:7]} | 2026-09-11 | 範圍 | 通過 | 紀錄 |\n"
               "| 本批 | 2026-09-11 | 新範圍 | 通過 | 無 |\n")
        _write(d, "docs/batches/%s-x.spec.txt" % base,
               SPEC_TMPL.format(base=base, anchor="B", payload="Z"))
        _commit(d, "c2")
        fails, infos = cc.check_17_spec_replay(d)
        assert fails == [], fails
        assert any("docs/EXEC-LOG.md 狀態流轉驗證通過" in i for i in infos)


def test_17_exec_log_old_row_edit_fails():
    """TEST C: EXEC-LOG 任意舊 row 改寫必須 FAIL。"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "A\nB\nC\n")
        _write(d, "docs/EXEC-LOG.md", EXEC_LOG_HEADER +
               "| BOOTSTRAP | 2026-09-05 | 建立 | 通過 | 無 |\n"
               "| 本批 | 2026-09-11 | 範圍 | 通過 | 紀錄 |\n")
        base = _commit(d, "c1")
        _write(d, "docs/T.md", "A\nZ\nC\n")
        # 修改了 BOOTSTRAP 那一列的內容
        _write(d, "docs/EXEC-LOG.md", EXEC_LOG_HEADER +
               "| BOOTSTRAP | 2026-09-05 | 遭竄改 | 通過 | 無 |\n"
               f"| {base[:7]} | 2026-09-11 | 範圍 | 通過 | 紀錄 |\n"
               "| 本批 | 2026-09-11 | 新範圍 | 通過 | 無 |\n")
        _write(d, "docs/batches/%s-x.spec.txt" % base,
               SPEC_TMPL.format(base=base, anchor="B", payload="Z"))
        _commit(d, "c2")
        fails, _ = cc.check_17_spec_replay(d)
        assert any("歷史資料列遭修改" in f for f in fails), fails


def test_17_exec_log_old_row_delete_fails():
    """TEST D: EXEC-LOG 舊 row 刪除必須 FAIL。"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "A\nB\nC\n")
        _write(d, "docs/EXEC-LOG.md", EXEC_LOG_HEADER +
               "| BOOTSTRAP | 2026-09-05 | 建立 | 通過 | 無 |\n"
               "| 本批 | 2026-09-11 | 範圍 | 通過 | 紀錄 |\n")
        base = _commit(d, "c1")
        _write(d, "docs/T.md", "A\nZ\nC\n")
        # 刪除了 BOOTSTRAP 列
        _write(d, "docs/EXEC-LOG.md", EXEC_LOG_HEADER +
               f"| {base[:7]} | 2026-09-11 | 範圍 | 通過 | 紀錄 |\n"
               "| 本批 | 2026-09-11 | 新範圍 | 通過 | 無 |\n")
        _write(d, "docs/batches/%s-x.spec.txt" % base,
               SPEC_TMPL.format(base=base, anchor="B", payload="Z"))
        _commit(d, "c2")
        fails, _ = cc.check_17_spec_replay(d)
        assert any("既有資料列遭刪除" in f for f in fails), fails


def test_17_exec_log_wrong_commit_backfill_fails():
    """TEST E: 『本批』回填錯誤 commit identity 必須 FAIL。"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "A\nB\nC\n")
        _write(d, "docs/EXEC-LOG.md", EXEC_LOG_HEADER +
               "| BOOTSTRAP | 2026-09-05 | 建立 | 通過 | 無 |\n"
               "| 本批 | 2026-09-11 | 範圍 | 通過 | 紀錄 |\n")
        base = _commit(d, "c1")
        _write(d, "docs/T.md", "A\nZ\nC\n")
        # 回填錯誤 hash deadbee
        _write(d, "docs/EXEC-LOG.md", EXEC_LOG_HEADER +
               "| BOOTSTRAP | 2026-09-05 | 建立 | 通過 | 無 |\n"
               "| deadbee | 2026-09-11 | 範圍 | 通過 | 紀錄 |\n"
               "| 本批 | 2026-09-11 | 新範圍 | 通過 | 無 |\n")
        _write(d, "docs/batches/%s-x.spec.txt" % base,
               SPEC_TMPL.format(base=base, anchor="B", payload="Z"))
        _commit(d, "c2")
        fails, _ = cc.check_17_spec_replay(d)
        assert any("上一批『本批』回填之 commit identity" in f for f in fails), fails


def test_17_exec_log_concrete_hash_append_passes():
    """TEST F: parent 已是具體 hash 時純 append 必須 PASS。"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "A\nB\nC\n")
        _write(d, "docs/EXEC-LOG.md", EXEC_LOG_HEADER +
               "| BOOTSTRAP | 2026-09-05 | 建立 | 通過 | 無 |\n"
               "| a1b2c3d | 2026-09-11 | 範圍 | 通過 | 紀錄 |\n")
        base = _commit(d, "c1")
        _write(d, "docs/T.md", "A\nZ\nC\n")
        _write(d, "docs/EXEC-LOG.md", EXEC_LOG_HEADER +
               "| BOOTSTRAP | 2026-09-05 | 建立 | 通過 | 無 |\n"
               "| a1b2c3d | 2026-09-11 | 範圍 | 通過 | 紀錄 |\n"
               "| 本批 | 2026-09-11 | 新範圍 | 通過 | 無 |\n")
        _write(d, "docs/batches/%s-x.spec.txt" % base,
               SPEC_TMPL.format(base=base, anchor="B", payload="Z"))
        _commit(d, "c2")
        fails, infos = cc.check_17_spec_replay(d)
        assert fails == [], fails
        assert any("docs/EXEC-LOG.md 狀態流轉驗證通過" in i for i in infos)


def test_17_normal_spec_with_fingerprint_and_exec_log_passes():
    """TEST G: normal spec + fingerprint update + EXEC-LOG 合法 transition 整合測試。"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "A\nB\nC\n")
        _write(d, "docs/fingerprints/exec-latest.json", '{\n  "lines": 3\n}\n')
        _write(d, "docs/EXEC-LOG.md", EXEC_LOG_HEADER +
               "| BOOTSTRAP | 2026-09-05 | 建立 | 通過 | 無 |\n"
               "| 本批 | 2026-09-11 | 範圍 | 通過 | 紀錄 |\n")
        base = _commit(d, "c1")
        _write(d, "docs/T.md", "A\nZ\nC\n")
        _write(d, "docs/fingerprints/exec-latest.json", '{\n  "lines": 4\n}\n')
        _write(d, "docs/EXEC-LOG.md", EXEC_LOG_HEADER +
               "| BOOTSTRAP | 2026-09-05 | 建立 | 通過 | 無 |\n"
               f"| {base[:7]} | 2026-09-11 | 範圍 | 通過 | 紀錄 |\n"
               "| 本批 | 2026-09-11 | 新範圍 | 通過 | 無 |\n")
        _write(d, "docs/batches/%s-x.spec.txt" % base,
               SPEC_TMPL.format(base=base, anchor="B", payload="Z"))
        _commit(d, "c2")
        fails, infos = cc.check_17_spec_replay(d)
        assert fails == [], fails
        assert any("逐位元相符" in i for i in infos)
        assert any("fingerprint artifact integrity delegated" in i for i in infos)
        assert any("docs/EXEC-LOG.md 狀態流轉驗證通過" in i for i in infos)


def test_17_unresolvable_base_fails():
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "A\nB\nC\n")
        _commit(d, "c1")
        _write(d, "docs/T.md", "A\nZ\nC\n")
        _write(d, "docs/batches/deadbee-x.spec.txt",
               SPEC_TMPL.format(base="deadbee", anchor="B", payload="Z"))
        _commit(d, "c2")
        fails, _ = cc.check_17_spec_replay(d)
        assert any("無法解析為 commit" in f for f in fails), fails


def test_17_base_resolving_to_wrong_commit_fails():
    """規格宣告的 base 是真實 commit，但不是本 commit 的 parent。"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "A\nB\nC\n")
        grand = _commit(d, "c1")
        _write(d, "docs/OTHER.md", "x\n")
        _commit(d, "c2")                     # 這一個才是 parent
        _write(d, "docs/T.md", "A\nZ\nC\n")
        _write(d, "docs/batches/%s-x.spec.txt" % grand,
               SPEC_TMPL.format(base=grand, anchor="B", payload="Z"))
        _commit(d, "c3")
        fails, _ = cc.check_17_spec_replay(d)
        assert any("不是同一個 commit" in f for f in fails), fails


def test_17_misleading_prefix_base_fails():
    """
    舊實作用 startswith 做 commit identity，單一字元的 base 只要
    剛好是 parent hash 的開頭就會被判為相符。commit identity 必須走
    git rev-parse 解析，而不是字串前綴。
    """
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "A\nB\nC\n")
        parent = _commit(d, "c1")
        _write(d, "docs/T.md", "A\nZ\nC\n")
        _write(d, "docs/batches/p-x.spec.txt",
               SPEC_TMPL.format(base=parent[0], anchor="B", payload="Z"))
        _commit(d, "c2")
        fails, _ = cc.check_17_spec_replay(d)
        assert any("無法解析為 commit" in f or "不是同一個 commit" in f
                   for f in fails), fails


def test_17_crlf_vs_lf_fails():
    """
    同樣的文字內容，規格重放出 LF，實際 commit 是 CRLF。
    若取 blob 時用 text=True，Python 的 universal newline 會把兩者
    正規化成同一個字串，這個差異就看不見了。逐位元比對必須抓到。
    """
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _run(d, "git", "config", "core.autocrlf", "false")
        _write(d, "docs/T.md", "A\nB\nC\n")
        base = _commit(d, "c1")
        # 實際 commit 寫成 CRLF；規格重放出來的是 LF
        with open(os.path.join(d, "docs/T.md"), "wb") as f:
            f.write(b"A\r\nZ\r\nC\r\n")
        _write(d, "docs/batches/%s-x.spec.txt" % base,
               SPEC_TMPL.format(base=base, anchor="B", payload="Z"))
        _commit(d, "c2")
        fails, _ = cc.check_17_spec_replay(d)
        assert any("位元組不一致" in f for f in fails), fails


def _make_create_spec(base, file, payload):
    return (
        f"HEAD: {base}\n\n"
        f"=== MOD 1 ===\n"
        f"file: {file}\n"
        f"mode: create_file\n"
        f"--- PAYLOAD ---\n"
        f"{payload}\n"
        "--- END " + "MOD ---\n"
    )


def test_17_create_file_replay_pass():
    """TEST 1: normal spec + create_file -> replay PASS"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "init\n")
        base = _commit(d, "c1")
        _write(d, "docs/NEW.md", "hello world\n")
        _write(d, f"docs/batches/{base}-create.spec.txt",
               _make_create_spec(base, "docs/NEW.md", "hello world\n"))
        _commit(d, "c2")
        fails, infos = cc.check_17_spec_replay(d)
        assert fails == [], fails
        assert any("docs/NEW.md 重放逐位元相符" in i for i in infos), infos


def test_17_create_file_payload_mismatch_fails():
    """TEST 2: create_file actual HEAD bytes 與 payload 不同 -> FAIL"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "init\n")
        base = _commit(d, "c1")
        _write(d, "docs/NEW.md", "actual content\n")
        _write(d, f"docs/batches/{base}-create.spec.txt",
               _make_create_spec(base, "docs/NEW.md", "expected content\n"))
        _commit(d, "c2")
        fails, _ = cc.check_17_spec_replay(d)
        assert any("重放結果與實際 commit 的位元組不一致" in f for f in fails), fails


def test_17_create_file_missing_in_head_fails():
    """TEST 3: spec 宣告 create_file，但 HEAD 沒有 file -> FAIL"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "init\n")
        base = _commit(d, "c1")
        _write(d, f"docs/batches/{base}-create.spec.txt",
               _make_create_spec(base, "docs/NEW.md", "content\n"))
        _commit(d, "c2")
        fails, _ = cc.check_17_spec_replay(d)
        assert any("docs/NEW.md:0  本 commit 中不存在" in f for f in fails), fails


def test_17_create_file_parent_already_exists_fails():
    """TEST 4: parent 已存在 target -> FAIL"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/NEW.md", "already exists\n")
        base = _commit(d, "c1")
        _write(d, "docs/NEW.md", "overwritten\n")
        _write(d, f"docs/batches/{base}-create.spec.txt",
               _make_create_spec(base, "docs/NEW.md", "overwritten\n"))
        _commit(d, "c2")
        fails, _ = cc.check_17_spec_replay(d)
        assert any("create_file 目標檔案在 parent commit 已存在" in f for f in fails), fails


def test_17_create_file_undeclared_new_file_fails_scope():
    """TEST 5: HEAD 多一個未宣告新檔 -> scope FAIL"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "init\n")
        base = _commit(d, "c1")
        _write(d, "docs/NEW.md", "hello\n")
        _write(d, "docs/SMUGGLED.md", "sneaky\n")
        _write(d, f"docs/batches/{base}-create.spec.txt",
               _make_create_spec(base, "docs/NEW.md", "hello\n"))
        _commit(d, "c2")
        fails, _ = cc.check_17_spec_replay(d)
        assert any("規格未宣告卻被修改的檔案" in f and "docs/SMUGGLED.md" in f for f in fails), fails


def test_17_bootstrap_spec_mismatch_fails_replay():
    """TEST 6: spec filename 含 `-BOOTSTRAP.spec.txt` 但 replay 不正確 -> 必須 FAIL"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "A\nB\nC\n")
        base = _commit(d, "c1")
        _write(d, "docs/T.md", "A\nWRONG\nC\n")
        _write(d, f"docs/batches/{base}-fake-BOOTSTRAP.spec.txt",
               _make_create_spec(base, "docs/T.md", "Z").replace("mode: create_file", "mode: replace\n--- ANCHOR ---\nB"))
        _commit(d, "c2")
        fails, infos = cc.check_17_spec_replay(d)
        # 證明不再被跳過，而是正常重放且失敗！
        assert any("重放結果與實際 commit 的位元組不一致" in f for f in fails), fails
        assert not any("跳過重放" in i for i in infos), infos


def test_17_bootstrap_spec_correct_passes_normal_replay():
    """TEST 7: spec filename 含 BOOTSTRAP，但 spec 正確 -> 按 normal replay PASS（不是 skip PASS）"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "A\nB\nC\n")
        base = _commit(d, "c1")
        _write(d, "docs/T.md", "A\nZ\nC\n")
        _write(d, f"docs/batches/{base}-valid-BOOTSTRAP.spec.txt",
               _make_create_spec(base, "docs/T.md", "Z").replace("mode: create_file", "mode: replace\n--- ANCHOR ---\nB"))
        _commit(d, "c2")
        fails, infos = cc.check_17_spec_replay(d)
        assert fails == [], fails
        assert any("docs/T.md 重放逐位元相符" in i for i in infos), infos
        assert not any("跳過重放" in i for i in infos), infos


def test_17_two_specs_one_commit_fails():
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "docs/T.md", "A\nB\nC\n")
        base = _commit(d, "c1")
        _write(d, "docs/T.md", "A\nZ\nC\n")
        _write(d, "docs/batches/%s-a.spec.txt" % base,
               SPEC_TMPL.format(base=base, anchor="B", payload="Z"))
        _write(d, "docs/batches/%s-b.spec.txt" % base,
               SPEC_TMPL.format(base=base, anchor="B", payload="Z"))
        _commit(d, "c2")
        fails, _ = cc.check_17_spec_replay(d)
        assert any("只允許一份規格" in f for f in fails), fails


# ----------------------------- CHECK 18 -----------------------------

def test_18_correct_tag_passes():
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "a.md", "A\n")
        c1 = _commit(d, "c1")
        _write(d, "a.md", "B\n")
        _commit(d, "c2")
        _run(d, "git", "tag", "audited-%s" % c1, c1)
        fails, _ = cc.check_18_tag_integrity(d)
        assert fails == [], fails


def test_18_tag_pointing_at_head_fails():
    """真實事故形狀：`git tag audited-<hash>` 漏掉第二個參數。"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "a.md", "A\n")
        c1 = _commit(d, "c1")
        _write(d, "a.md", "B\n")
        _commit(d, "c2")
        _run(d, "git", "tag", "audited-%s" % c1)   # 漏掉目標 commit
        fails, _ = cc.check_18_tag_integrity(d)
        assert any("與名稱不符" in f for f in fails), fails


def test_18_named_hash_not_a_commit_fails():
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "a.md", "A\n")
        _commit(d, "c1")
        _run(d, "git", "tag", "audited-deadbee")
        fails, _ = cc.check_18_tag_integrity(d)
        assert any("無法解析為 commit" in f for f in fails), fails


def test_18_repaired_tag_left_in_exemption_list_fails():
    """豁免清單不會自己過期，必須由一次紅燈強迫清掉。"""
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "a.md", "A\n")
        c1 = _commit(d, "c1")
        _write(d, "a.md", "B\n")
        _commit(d, "c2")
        tag = "audited-%s" % c1
        _run(d, "git", "tag", tag, c1)
        orig = cc.KNOWN_BAD_TAGS
        try:
            cc.KNOWN_BAD_TAGS = {tag}
            fails, _ = cc.check_18_tag_integrity(d)
        finally:
            cc.KNOWN_BAD_TAGS = orig
        assert any("已修復但仍留在 KNOWN_BAD_TAGS" in f for f in fails), fails


def test_18_unreachable_but_existing_commit_fails():
    """
    tag 名稱與 target 完全吻合，commit 物件也還在 object database 裡，
    但它在一條已經離開的 side branch 上，由目前 HEAD 到不了。
    `git cat-file -e` 會說「存在」，那不是「本分支可達」。
    """
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "a.md", "A\n")
        _commit(d, "c1")
        _run(d, "git", "checkout", "-q", "-b", "side")
        _write(d, "a.md", "side\n")
        side = _commit(d, "side-commit")
        _run(d, "git", "tag", "audited-%s" % side, side)
        _run(d, "git", "checkout", "-q", "main")
        _write(d, "a.md", "main\n")
        _commit(d, "c2")
        _run(d, "git", "branch", "-q", "-D", "side")
        # 物件仍在：cat-file 找得到
        assert subprocess.run(["git", "cat-file", "-e", side + "^{commit}"],
                              cwd=d).returncode == 0
        fails, _ = cc.check_18_tag_integrity(d)
        assert any("無法由目前 HEAD 到達" in f for f in fails), fails


def test_18_head_identity_failure_does_not_fail_open(monkeypatch):
    """
    HEAD 的 commit identity 解析不出來時，不得略過可達性驗證直接放行。
    環境異常必須是 FAIL，不是自動通過。
    """
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "a.md", "A\n")
        c1 = _commit(d, "c1")
        _run(d, "git", "tag", "audited-%s" % c1, c1)

        real = cc._resolve_commit

        def fake(root_dir, rev):
            if rev == "HEAD":
                return None
            return real(root_dir, rev)

        monkeypatch.setattr(cc, "_resolve_commit", fake)
        fails, _ = cc.check_18_tag_integrity(d)
        assert any("無法把 HEAD 解析為 commit OID" in f for f in fails), fails


def test_18_no_tags_is_skipped():
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        _write(d, "a.md", "A\n")
        _commit(d, "c1")
        fails, infos = cc.check_18_tag_integrity(d)
        assert fails == []
        assert any("無 audited-* tag" in i for i in infos)


def test_18_known_bad_list_matches_repo_reality():
    """
    KNOWN_BAD_TAGS 只能縮短不得加長。本測試把清單釘在實際 repo 上：
    清單中的每個 tag 都必須存在於本 repo，否則代表有人隨手加了項目。
    """
    out = subprocess.run(["git", "tag", "-l", "audited-*"], cwd=REPO_ROOT,
                         capture_output=True, text=True).stdout
    existing = {t.strip() for t in out.splitlines() if t.strip()}
    if not existing:
        pytest.skip("此 clone 未取得 tag")
    unknown = cc.KNOWN_BAD_TAGS - existing
    assert unknown == set(), f"KNOWN_BAD_TAGS 中有 repo 不存在的 tag: {unknown}"
