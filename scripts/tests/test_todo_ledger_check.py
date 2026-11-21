"""待辦清冊機械檢查（B-117 G7-b3b3-3）：清冊格式、清冊只增不減、批次紀錄「新增待辦」宣告對帳、records-apply 搬移前對帳。

每個測試名稱對應提示詞「承諾對測試」表的一列（E27）；故障注入反例以 test_probe_* 命名。
"""
import io
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import taskboard_archive as ta

TASK = "B117-TEST-LEDGER-R1-261121"
FIXED_DATE = "2026-01-01T00:00:00+00:00"
HEADER = "| 編號 | 來源批次紀錄 | 原標籤 | 事項 | 處置 | 依據或去處 |\n|---|---|---|---|---|---|\n"


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True,
        env=dict(os.environ, GIT_AUTHOR_DATE=FIXED_DATE, GIT_COMMITTER_DATE=FIXED_DATE)).stdout.decode("utf-8").strip()


def write(root, rel, text):
    path = os.path.join(str(root), *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(text.encode("utf-8"))


def read(root, rel):
    with open(os.path.join(str(root), *rel.split("/")), "rb") as handle:
        return handle.read().decode("utf-8")


def tid(number):
    return "B117-T%d-R1-2611%02d" % (number, 20 - number)


def rec(number, clause=None, pad=0):
    """第 number 則批次紀錄（number 越大越舊）；clause 為「新增待辦」之後的宣告內容（None 表示不寫宣告句）。"""
    text = "**第 %d 批（2026-11-%02d；本批 %s）**：%s" % (number, 20 - number, tid(number), "字" * pad)
    if clause is not None:
        text += "新增待辦：%s。" % clause
    return text


def row(number, source, disposition="承接", basis="看板 G7 列承接", item="事項"):
    return "| TD-%03d | %s | 標籤%d | %s%d | %s | %s |\n" % (number, source, number, item, number, disposition, basis)


def ledger(rows):
    return "# 待辦清冊\n\n" + HEADER + "".join(rows)


BOARD_TAIL = "\n## 封存區\n\n已移到 docs/archive/TASKBOARD-ARCHIVE-0001.md\n"
# 看板：tid(1)、tid(2) 較新（受管），tid(3) 是錨點，tid(4)、tid(5) 較舊（舊紀錄）
DEFAULT_BOARD = [rec(1, "TD-004"), rec(2, "無"), rec(3), rec(4), rec(5)]
DEFAULT_LEDGER = [row(1, tid(5)), row(2, tid(4), "開放", "owner G7；複查日 2026-12-01"), row(3, tid(4), "結案", "b 批結案"), row(4, tid(1))]


def make_board(parts):
    return "# 任務看板\n\n**C7_STATUS_LINT_ACTIVE**：啟用。\n\n" + "\n\n".join(parts) + "\n" + BOARD_TAIL


def build(tmp_path, monkeypatch, board=None, rows=None, anchor=None, name="repo"):
    monkeypatch.setattr(ta, "RECORD_ARCHIVES_MIN", 0)
    monkeypatch.setattr(ta, "FIRST_ARCHIVE_SHA256", None)
    monkeypatch.setattr(ta, "LEDGER_ANCHOR", anchor if anchor is not None else tid(3))
    root = tmp_path / name
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "core.autocrlf", "false")
    write(root, "docs/TASKBOARD.md", make_board(board if board is not None else DEFAULT_BOARD))
    write(root, "docs/AUDIT-LOG.md", "| 檢查點 | 日期 |\n|---|---|\n")
    write(root, "docs/ARCHIVE-INDEX.md", "# 歸檔索引\n\n| 任務 | docs/archive/TASKBOARD-ARCHIVE-README.md |\n")
    write(root, "docs/archive/TASKBOARD-ARCHIVE-README.md", "# 說明\n")
    write(root, "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json", '{\n "schema_version": 1,\n "user_keep": [],\n "archives": []\n}\n')
    write(root, "docs/TODO-LEDGER.md", ledger(rows if rows is not None else DEFAULT_LEDGER))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "state")
    c1 = git(root, "rev-parse", "HEAD")
    write(root, "docs/refactor-backlog.md", "上次核對通過的 HEAD：%s\n" % c1)
    return {"root": root, "c1": c1, "mp": monkeypatch}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    return build(tmp_path, monkeypatch)


def fails_of(repo):
    fails, _ = ta.check(str(repo["root"]))
    return fails


def ledger_fails(repo):
    return fails_of(repo)


def edit(repo, rel, old, new):
    text = read(repo["root"], rel)
    assert old in text
    write(repo["root"], rel, text.replace(old, new, 1))


def run(args):
    out = io.StringIO()
    return ta.main(args, out=out), out.getvalue()


def apply_args(repo, keep, take, no_new=(), allow=()):
    args = ["records-apply", "--repo", str(repo["root"]), "--task-id", TASK, "--checkpoint-oid", repo["c1"],
            "--keep", str(keep), "--take", str(take)]
    for name in no_new:
        args += ["--no-new-todos", name]
    for name in allow:
        args += ["--allow-multiline", name]
    return args


def snapshot(repo):
    return {rel: read(repo["root"], rel) for rel in ("docs/TASKBOARD.md", "docs/TODO-LEDGER.md", "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json")}


# ---- 基準：全部合規時 CHECK 29 通過 ----------------------------------------------------------------

def test_a_consistent_board_and_ledger_pass(repo):
    assert fails_of(repo) == []


# ---- 清冊格式（承諾 C1）------------------------------------------------------------------------------

def test_format_gap_in_numbering_is_a_fail(repo):
    edit(repo, "docs/TODO-LEDGER.md", "| TD-003 |", "| TD-005 |")
    assert any("應為 TD-003" in f for f in ledger_fails(repo))


def test_format_duplicate_id_is_a_fail(repo):
    edit(repo, "docs/TODO-LEDGER.md", "| TD-004 |", "| TD-003 |")
    assert any("應為 TD-004" in f for f in ledger_fails(repo))


def test_format_unknown_disposition_is_a_fail(repo):
    edit(repo, "docs/TODO-LEDGER.md", "| 承接 |", "| 暫緩 |")
    assert any("處置須為" in f for f in ledger_fails(repo))


def test_format_empty_cell_is_a_fail(repo):
    edit(repo, "docs/TODO-LEDGER.md", "| 看板 G7 列承接 |", "|  |")
    assert any("不得為空" in f for f in ledger_fails(repo))


def test_format_wrong_cell_count_is_a_fail(repo):
    edit(repo, "docs/TODO-LEDGER.md", "| 標籤1 |", "| 標籤1 | 多一欄 |")
    assert any("欄數" in f for f in ledger_fails(repo))


def test_format_row_without_td_number_shape_is_a_fail(repo):
    edit(repo, "docs/TODO-LEDGER.md", "| TD-001 |", "| TD1 |")
    assert any("TD-nnn" in f for f in ledger_fails(repo))


def test_format_a_new_open_row_needs_an_owner_but_old_rows_are_not_retroactive(tmp_path, monkeypatch):
    # checkpoint 的清冊有一個沒寫 owner 的舊開放列：不追溯
    repo = build(tmp_path, monkeypatch, rows=[row(1, tid(5), "開放", "沒寫負責人"), row(2, tid(4)), row(3, tid(4)), row(4, tid(1))])
    assert fails_of(repo) == []
    write(repo["root"], "docs/TODO-LEDGER.md", read(repo["root"], "docs/TODO-LEDGER.md") + row(5, tid(1), "開放", "沒寫負責人"))
    edit(repo, "docs/TASKBOARD.md", "新增待辦：TD-004。", "新增待辦：TD-004、TD-005。")
    assert any("TD-005" in f and "owner" in f for f in ledger_fails(repo))


# ---- 清冊只增不減（承諾 C2）---------------------------------------------------------------------------

def test_append_only_adding_a_row_with_a_new_record_is_allowed(repo):
    write(repo["root"], "docs/TODO-LEDGER.md", read(repo["root"], "docs/TODO-LEDGER.md") + row(5, tid(0), "承接"))
    edit(repo, "docs/TASKBOARD.md", "**第 1 批", rec(0, "TD-005") + "\n\n**第 1 批")
    assert fails_of(repo) == []


def test_append_only_deleting_a_row_is_a_fail(repo):
    edit(repo, "docs/TODO-LEDGER.md", row(4, tid(1)), "")
    assert any("TD-004" in f and ("消失" in f or "應為" in f or "不一致" in f) for f in ledger_fails(repo))


def test_append_only_deleting_a_middle_row_is_a_fail(repo):
    edit(repo, "docs/TODO-LEDGER.md", row(2, tid(4), "開放", "owner G7；複查日 2026-12-01"), "")
    assert ledger_fails(repo)


def test_append_only_rewriting_source_label_or_item_is_a_fail(repo):
    edit(repo, "docs/TODO-LEDGER.md", "標籤1", "改過的標籤")
    edit(repo, "docs/TODO-LEDGER.md", "事項1", "改過的事項")
    fails = ledger_fails(repo)
    assert any("TD-001" in f and "label" in f for f in fails)
    assert any("TD-001" in f and "item" in f for f in fails)


def test_append_only_changing_the_source_is_a_fail(repo):
    edit(repo, "docs/TODO-LEDGER.md", "| TD-001 | %s |" % tid(5), "| TD-001 | %s |" % tid(4))
    assert any("TD-001" in f and "source" in f for f in ledger_fails(repo))


def test_append_only_open_or_carried_may_become_closed(repo):
    edit(repo, "docs/TODO-LEDGER.md", "| 開放 | owner G7；複查日 2026-12-01 |", "| 結案 | 某批結案 |")
    edit(repo, "docs/TODO-LEDGER.md", "| 承接 | 看板 G7 列承接 |", "| 結案 | 某批結案 |")
    assert fails_of(repo) == []


def test_append_only_carried_to_open_or_closed_to_open_is_a_fail(repo):
    edit(repo, "docs/TODO-LEDGER.md", "| TD-001 | %s | 標籤1 | 事項1 | 承接 |" % tid(5), "| TD-001 | %s | 標籤1 | 事項1 | 開放 |" % tid(5))
    edit(repo, "docs/TODO-LEDGER.md", "| 結案 | b 批結案 |", "| 開放 | owner X |")
    fails = ledger_fails(repo)
    assert any("TD-001" in f and "處置只能" in f for f in fails)
    assert any("TD-003" in f and "逐字不變" in f for f in fails)


def test_append_only_closed_row_text_changed_is_a_fail(repo):
    edit(repo, "docs/TODO-LEDGER.md", "b 批結案", "改寫的依據")
    assert any("TD-003" in f and "逐字不變" in f for f in ledger_fails(repo))


# ---- 新增待辦宣告對帳（承諾 C3）-----------------------------------------------------------------------

def test_declaration_missing_clause_is_a_fail(tmp_path, monkeypatch):
    repo = build(tmp_path, monkeypatch, board=[rec(1), rec(2, "無"), rec(3), rec(4), rec(5)])
    assert any(tid(1) in f and "找到 0 句" in f for f in ledger_fails(repo))


def test_declaration_two_clauses_is_a_fail(tmp_path, monkeypatch):
    repo = build(tmp_path, monkeypatch, board=[rec(1, "TD-004") + "新增待辦：無。", rec(2, "無"), rec(3), rec(4), rec(5)])
    assert any(tid(1) in f and "找到 2 句" in f for f in ledger_fails(repo))


def test_declaration_none_while_the_ledger_has_rows_for_it_is_a_fail(tmp_path, monkeypatch):
    repo = build(tmp_path, monkeypatch, board=[rec(1, "無"), rec(2, "無"), rec(3), rec(4), rec(5)])
    assert any(tid(1) in f and "宣告與清冊不一致" in f for f in ledger_fails(repo))


def test_declaration_listing_an_unknown_number_is_a_fail(repo):
    edit(repo, "docs/TASKBOARD.md", "新增待辦：TD-004。", "新增待辦：TD-004、TD-099。")
    assert any("TD-099" in f and "不存在" in f for f in ledger_fails(repo))


def test_declaration_listing_a_number_owned_by_another_record_is_a_fail(repo):
    edit(repo, "docs/TASKBOARD.md", "新增待辦：無。", "新增待辦：TD-001。")
    assert any(tid(2) in f and "宣告與清冊不一致" in f for f in ledger_fails(repo))


def test_declaration_ledger_row_not_listed_is_a_fail(repo):
    write(repo["root"], "docs/TODO-LEDGER.md", read(repo["root"], "docs/TODO-LEDGER.md") + row(5, tid(1), "承接"))
    assert any(tid(1) in f and "宣告與清冊不一致" in f for f in ledger_fails(repo))


def test_declaration_duplicate_or_malformed_numbers_are_a_fail(repo):
    edit(repo, "docs/TASKBOARD.md", "新增待辦：TD-004。", "新增待辦：TD-004、TD-004。")
    assert any("編號重複" in f for f in ledger_fails(repo))
    edit(repo, "docs/TASKBOARD.md", "新增待辦：TD-004、TD-004。", "新增待辦：（一）。")
    assert any("編號格式不符" in f for f in ledger_fails(repo))


def test_declaration_applies_only_to_records_newer_than_the_anchor(repo):
    # tid(4)、tid(5) 在錨點之前，沒有宣告句也不報
    assert not any(tid(4) in f or tid(5) in f for f in fails_of(repo))


def test_declaration_rule_is_inactive_until_the_anchor_exists(tmp_path, monkeypatch):
    repo = build(tmp_path, monkeypatch, anchor="B117-NOT-ON-THE-BOARD-R1-261101")
    (repo["root"] / "docs" / "TODO-LEDGER.md").unlink()  # 規則未生效：連清冊檔都不看
    assert fails_of(repo) == []


def test_declaration_when_the_anchor_is_archived_every_board_record_is_subject(tmp_path, monkeypatch):
    repo = build(tmp_path, monkeypatch, board=[rec(1, "TD-004"), rec(2, "無"), rec(3), rec(4), rec(5)], anchor=tid(5))
    code, out = run(apply_args(repo, keep=4, take=1))
    assert code == 0, out
    git(repo["root"], "add", "-A")
    git(repo["root"], "commit", "-q", "-m", "apply")
    write(repo["root"], "docs/refactor-backlog.md", "上次核對通過的 HEAD：%s\n" % git(repo["root"], "rev-parse", "HEAD"))
    repo["mp"].setattr(ta, "RECORD_ARCHIVES_MIN", 1)
    fails = fails_of(repo)
    # 錨點已封存：看板上留下的全部紀錄都受管；tid(3)、tid(4) 沒有宣告句 → FAIL，tid(1)、tid(2) 合規 → 不報
    assert any(tid(4) in f and "找到 0 句" in f for f in fails)
    assert any(tid(3) in f and "找到 0 句" in f for f in fails)
    assert not any(tid(1) in f or tid(2) in f for f in fails)


# ---- records-apply 搬移前對帳（承諾 C4）---------------------------------------------------------------

def test_apply_moves_old_records_that_have_ledger_rows_even_when_their_todos_are_open(repo):
    # tid(5) 的 TD-001 是「承接」、tid(4) 的 TD-002 是「開放」：未結案編號不擋搬移（只擋「沒有編號」）
    code, out = run(apply_args(repo, keep=3, take=2))
    assert code == 0, out
    assert tid(4) not in read(repo["root"], "docs/TASKBOARD.md")


def test_apply_refuses_an_old_record_without_ledger_rows_and_touches_nothing(tmp_path, monkeypatch):
    repo = build(tmp_path, monkeypatch, rows=[row(1, tid(4)), row(2, tid(1))],
                 board=[rec(1, "TD-002"), rec(2, "無"), rec(3), rec(4), rec(5)])
    before = snapshot(repo)
    code, out = run(apply_args(repo, keep=4, take=1))
    assert code == 1 and tid(5) in out and "沒有來源為它的列" in out
    assert snapshot(repo) == before


def test_apply_no_new_todos_names_the_old_record_explicitly(tmp_path, monkeypatch):
    repo = build(tmp_path, monkeypatch, rows=[row(1, tid(4)), row(2, tid(1))],
                 board=[rec(1, "TD-002"), rec(2, "無"), rec(3), rec(4), rec(5)])
    code, out = run(apply_args(repo, keep=4, take=1, no_new=[tid(5)]))
    assert code == 0, out


def test_apply_no_new_todos_is_refused_when_the_record_already_has_ledger_rows(repo):
    code, out = run(apply_args(repo, keep=4, take=1, no_new=[tid(5)]))
    assert code == 1 and "不得再聲明沒有待辦" in out


def test_apply_no_new_todos_is_refused_for_a_record_that_is_not_moved_or_is_subject(repo):
    code, out = run(apply_args(repo, keep=4, take=1, no_new=[tid(1)]))
    assert code == 1 and "不是本次要搬的舊紀錄" in out
    code, out = run(apply_args(repo, keep=4, take=1, no_new=[tid(5), tid(5)]))
    assert code == 1 and "點名重複" in out


def test_apply_refuses_a_subject_record_with_a_wrong_declaration(tmp_path, monkeypatch):
    # 受管紀錄 tid(1) 位於最舊：把錨點設在最舊之後，使它成為搬移對象
    repo = build(tmp_path, monkeypatch, board=[rec(1, "無"), rec(2, "無")], rows=[row(1, tid(1))], anchor=tid(2))
    before = snapshot(repo)
    code, out = run(apply_args(repo, keep=1, take=1, no_new=[]))
    # take=1 搬走最舊的 tid(2)（錨點本身，舊紀錄）：沒有清冊列且未點名 → 拒絕
    assert code == 1 and tid(2) in out
    assert snapshot(repo) == before


def test_apply_refuses_a_subject_record_whose_declaration_disagrees_with_the_ledger(tmp_path, monkeypatch):
    repo = build(tmp_path, monkeypatch, board=[rec(1, "無"), rec(2, "無"), rec(3)], rows=[row(1, tid(2))], anchor=tid(3))
    before = snapshot(repo)
    code, out = run(apply_args(repo, keep=1, take=2))
    assert code == 1 and "宣告與清冊不一致" in out
    assert snapshot(repo) == before


def test_apply_refuses_when_the_ledger_is_malformed(repo):
    edit(repo, "docs/TODO-LEDGER.md", "| 承接 |", "| 暫緩 |")
    before = snapshot(repo)
    code, out = run(apply_args(repo, keep=3, take=2))
    assert code == 1 and "清冊格式不符" in out
    assert snapshot(repo) == before


def test_apply_without_an_active_anchor_behaves_as_before_and_refuses_the_flag(tmp_path, monkeypatch):
    repo = build(tmp_path, monkeypatch, anchor="B117-NOT-ON-THE-BOARD-R1-261101")
    code, out = run(apply_args(repo, keep=3, take=2, no_new=[tid(5)]))
    assert code == 1 and "尚未在看板或封存檔" in out
    code, out = run(apply_args(repo, keep=3, take=2))
    assert code == 0, out


# ---- 證據探針的故障注入反例（E27 b）：探針失敗、無法判定時結果必為失敗 --------------------------------

def test_probe_missing_ledger_file_is_a_fail_when_the_rule_is_active(repo):
    os.remove(os.path.join(str(repo["root"]), "docs", "TODO-LEDGER.md"))
    assert any("TODO-LEDGER.md" in f for f in fails_of(repo))


def test_probe_checkpoint_ledger_unreadable_by_git_is_a_fail(repo, monkeypatch):
    real = ta.git_blob_text

    def broken(root, oid, rel):
        if rel == ta.LEDGER_REL:
            raise ta.Fail("git 讀不到 %s:%s" % (oid[:7], rel))
        return real(root, oid, rel)

    monkeypatch.setattr(ta, "git_blob_text", broken)
    assert any("git 讀不到" in f for f in ledger_fails(repo))


def test_probe_checkpoint_ledger_malformed_is_a_fail_not_a_baseline(tmp_path, monkeypatch):
    repo = build(tmp_path, monkeypatch, rows=[row(1, tid(5)), "| TD-002 | 只有兩欄 |\n", row(3, tid(4)), row(4, tid(1))])
    assert any("無法作為只增不減的基準" in f for f in ledger_fails(repo))


def test_probe_checkpoint_commit_without_a_ledger_is_a_fail(tmp_path, monkeypatch):
    repo = build(tmp_path, monkeypatch)
    git(repo["root"], "rm", "-q", "docs/TODO-LEDGER.md")
    git(repo["root"], "commit", "-q", "-m", "no ledger")
    c2 = git(repo["root"], "rev-parse", "HEAD")
    write(repo["root"], "docs/refactor-backlog.md", "上次核對通過的 HEAD：%s\n" % c2)
    write(repo["root"], "docs/TODO-LEDGER.md", ledger(DEFAULT_LEDGER))
    assert any("git 讀不到" in f for f in ledger_fails(repo))


def test_probe_unexpected_exception_in_the_ledger_check_becomes_a_fail_line(repo, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("probe")

    monkeypatch.setattr(ta, "parse_ledger", boom)
    fails = fails_of(repo)
    assert fails and any("內部錯誤" in f for f in fails)


def test_probe_a_ledger_with_crlf_is_a_fail(repo):
    path = os.path.join(str(repo["root"]), "docs", "TODO-LEDGER.md")
    data = read(repo["root"], "docs/TODO-LEDGER.md").replace("\n", "\r\n").encode("utf-8")
    with open(path, "wb") as handle:
        handle.write(data)
    assert any("CR" in f for f in ledger_fails(repo))


def test_probe_unparseable_apply_gate_input_is_a_refusal(repo, monkeypatch):
    monkeypatch.setattr(ta, "read_text", lambda root, rel: (_ for _ in ()).throw(ta.Fail("%s 無法讀取" % rel)) if rel == ta.LEDGER_REL else open(os.path.join(root, *rel.split("/")), encoding="utf-8").read())
    code, out = run(apply_args(repo, keep=3, take=2))
    assert code == 1 and "無法讀取" in out


def test_format_variant_row_is_not_silently_ignored(repo):
    edit(repo, "docs/TODO-LEDGER.md", row(4, tid(1)),
         row(4, tid(1)) + "|TD-005 | %s | 標籤5 | 事項5 | 開放 | owner G7 |\n" % tid(2))
    assert fails_of(repo)


def test_format_variant_row_with_leading_whitespace_is_not_silently_ignored(repo):
    edit(repo, "docs/TODO-LEDGER.md", row(4, tid(1)),
         row(4, tid(1)) + " | TD-005 | %s | 標籤5 | 事項5 | 開放 | owner G7 |\n" % tid(2))
    assert fails_of(repo)


def test_probe_checkpoint_that_is_a_tree_oid_is_a_fail(repo):
    tree = git(repo["root"], "rev-parse", repo["c1"] + "^{tree}")
    tb = read(repo["root"], "docs/TASKBOARD.md")
    out = ta.check_ledger(str(repo["root"]), ta.record_units(tb), set(), "上次核對通過的 HEAD：%s\n" % tree)
    assert any("無法解析" in f for f in out)


# ---- 真實清冊守門：repo 內的 docs/TODO-LEDGER.md 本身必須合規 ------------------------------------------

def test_the_real_ledger_parses_is_contiguous_and_has_no_format_problem():
    path = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "TODO-LEDGER.md")
    with open(path, "rb") as handle:
        text = handle.read().decode("utf-8")
    rows, problems = ta.parse_ledger(text)
    assert problems == [] and len(rows) >= 94
    assert ta.ledger_format_problems(rows) == []
