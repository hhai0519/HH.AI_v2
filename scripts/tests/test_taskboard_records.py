import io
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import history_guard as hg
import taskboard_archive as ta

TASK = "B117-TEST-RECORDS-R1-261118"
# 固定 commit 時間：兩個內容相同的測試 repo 才會得到相同的 commit id（封存檔標頭含 checkpoint），確定性測試不隨秒數飄動
FIXED_DATE = "2026-01-01T00:00:00+00:00"
BOARD_TAIL = "\n## 封存區\n\n已移到 docs/archive/TASKBOARD-ARCHIVE-0001.md\n"


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", *args],
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


def rec(number, pad=0):
    """第 number 則批次紀錄（number 越大越舊）。"""
    return "**第 %d 批（2026-11-%02d；本批 B117-T%d-R1-2611%02d）**：%s" % (number, 20 - number, number, 20 - number, "字" * pad)


def make_board(parts):
    return "# 任務看板\n\n**C7_STATUS_LINT_ACTIVE**：啟用。\n\n" + "\n".join(parts) + "\n" + BOARD_TAIL


def tid(number):
    return "B117-T%d-R1-2611%02d" % (number, 20 - number)


def build_repo(tmp_path, monkeypatch, board, name="repo"):
    monkeypatch.setattr(ta, "RECORD_ARCHIVES_MIN", 0)  # 尚未寫成；寫成後才釘定
    monkeypatch.setattr(ta, "FIRST_ARCHIVE_SHA256", None)  # 本檔只測批次紀錄，不涉及看板列的第一個封存檔
    root = tmp_path / name
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "core.autocrlf", "false")
    write(root, "docs/TASKBOARD.md", board)
    write(root, "docs/AUDIT-LOG.md", "| 檢查點 | 日期 |\n|---|---|\n")
    write(root, "docs/ARCHIVE-INDEX.md", "# 歸檔索引\n\n| 任務 | docs/archive/TASKBOARD-ARCHIVE-README.md |\n")
    write(root, "docs/archive/TASKBOARD-ARCHIVE-README.md", "# 說明\n")
    write(root, "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json", '{\n "schema_version": 1,\n "user_keep": [],\n "archives": []\n}\n')
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "state")
    c1 = git(root, "rev-parse", "HEAD")
    write(root, "docs/refactor-backlog.md", "上次核對通過的 HEAD：%s\n" % c1)
    return {"root": root, "c1": c1}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    # 五則：第 1 則最新；第 3 則有兩行續行；第 4、5 則相鄰（中間沒有空白行）
    parts = [rec(1, 40) + "\n", rec(2, 20) + "\n", rec(3, 10) + "\n續行甲\n續行乙\n", rec(4) + "\n" + rec(5, 5), ]
    board = make_board(parts)
    out = build_repo(tmp_path, monkeypatch, board)
    out["mp"] = monkeypatch
    return out


def run(args):
    out = io.StringIO()
    code = ta.main(args, out=out)
    return code, out.getvalue()


def apply_args(repo, keep, take, task=TASK, allow="auto"):
    """allow="auto"：fixture 的第 3 則是多行單元，搬得到它（take ≥ 3）時一律點名；其餘情況不點名。"""
    if allow == "auto":
        allow = [tid(3)] if take >= 3 else []
    args = ["records-apply", "--repo", str(repo["root"]), "--task-id", task, "--checkpoint-oid", repo["c1"],
            "--keep", str(keep), "--take", str(take)]
    for name in allow:
        args += ["--allow-multiline", name]
    return args


def apply_ok(repo, keep=2, take=2):
    code, out = run(apply_args(repo, keep, take))
    assert code == 0, out
    repo["mp"].setattr(ta, "RECORD_ARCHIVES_MIN", 1)
    return out


def fails_of(repo):
    fails, _ = ta.check(str(repo["root"]))
    return fails


def mutate(repo, rel, old, new):
    text = read(repo["root"], rel)
    assert old in text
    write(repo["root"], rel, text.replace(old, new, 1))


def test_units_follow_blank_lines_and_next_record():
    text = make_board([rec(1) + "\n", rec(2) + "\n續行\n", rec(3) + "\n" + rec(4)])
    units = ta.record_units(text)
    assert [u["task_id"] for u in units] == [tid(1), tid(2), tid(3), tid(4)]
    assert [len(u["lines"]) for u in units] == [1, 2, 1, 1]
    assert [u["start"] for u in units] == [5, 7, 10, 11]


def test_inventory_numbers_are_printed_by_the_tool(repo):
    code, out = run(["records-plan", "--repo", str(repo["root"]), "--keep", "2"])
    assert code == 0
    units = ta.record_units(read(repo["root"], "docs/TASKBOARD.md"))
    sizes = [ta.unit_bytes(u["lines"]) for u in units]
    assert "RECORDS_INVENTORY count=5 total_bytes=%d over_3072=0 max_bytes=%d max_task=%s" % (
        sum(sizes), max(sizes), tid(1)) in out
    assert out.count(" KEEP\n") == 2 and out.count(" MOVE\n") == 3
    assert "RECORDS_SUMMARY keep=2 movable=3 movable_bytes=%d" % sum(sizes[2:]) in out


def test_inventory_counts_units_over_the_byte_threshold(tmp_path, monkeypatch):
    board = make_board([rec(1, 1200) + "\n", rec(2, 1100) + "\n", rec(3, 1) + "\n"])  # 每個中文字 3 位元組：3600、3300、小
    out = build_repo(tmp_path, monkeypatch, board)
    code, text = run(["records-plan", "--repo", str(out["root"]), "--keep", "1"])
    assert code == 0 and "over_3072=2" in text


def test_apply_moves_the_oldest_units_verbatim_and_check_passes(repo):
    before = read(repo["root"], "docs/TASKBOARD.md")
    units = ta.record_units(before)
    apply_ok(repo, keep=2, take=2)
    after = read(repo["root"], "docs/TASKBOARD.md")
    remaining = ta.record_units(after)
    assert [u["task_id"] for u in remaining] == [tid(1), tid(2), tid(3)]
    archive = read(repo["root"], "docs/archive/TASKBOARD-RECORDS-0001.md")
    for unit in units[3:]:
        assert ta.unit_text(unit["lines"]) in archive
    assert archive.index(tid(4)) < archive.index(tid(5))  # 看板順序（新→舊）
    manifest = json.loads(read(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json"))
    entry = manifest["record_archives"][0]["entries"][0]
    assert entry["task_id"] == tid(4) and entry["source_line"] == units[3]["start"]
    assert fails_of(repo) == []


def test_apply_moves_a_multi_line_unit_whole_and_keeps_blank_line_rhythm(repo):
    apply_ok(repo, keep=2, take=3)
    after = read(repo["root"], "docs/TASKBOARD.md")
    assert "續行甲" not in after and "續行乙" not in after
    assert "續行甲\n續行乙" in read(repo["root"], "docs/archive/TASKBOARD-RECORDS-0001.md")
    assert "\n\n\n" not in after  # 沒有累積多餘空白行
    assert fails_of(repo) == []


def test_apply_is_deterministic_same_inputs_same_bytes(tmp_path, monkeypatch):
    parts = [rec(1, 40) + "\n", rec(2, 20) + "\n", rec(3, 10) + "\n續行\n", rec(4) + "\n" + rec(5, 5)]
    shas = []
    for name in ("a", "b"):
        out = build_repo(tmp_path, monkeypatch, make_board(parts), name)
        code, text = run(["records-apply", "--repo", str(out["root"]), "--task-id", TASK, "--checkpoint-oid", out["c1"], "--keep", "1", "--take", "3",
                           "--allow-multiline", tid(3)])
        assert code == 0, text
        shas.append((read(out["root"], "docs/archive/TASKBOARD-RECORDS-0001.md").encode("utf-8"),
                     read(out["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json"),
                     read(out["root"], "docs/TASKBOARD.md"), text.split(" file_sha256=")[1].strip()))
    assert shas[0] == shas[1]
    assert ta.sha256_text(shas[0][0].decode("utf-8")) == shas[0][3]
    first = ta.record_units(make_board(parts))
    archive = {"batch": TASK, "checkpoint_oid": "0" * 40, "keep": 1,
               "entries": [{"task_id": u["task_id"], "source_line": u["start"], "line_count": len(u["lines"])} for u in first[1:]]}
    by_id = {u["task_id"]: u["lines"] for u in first}
    assert ta.render_records_archive(1, archive, by_id) == ta.render_records_archive(1, archive, by_id)
    assert "\r" not in shas[0][0].decode("utf-8")


@pytest.mark.parametrize("keep,take", [(0, 1), (-1, 1), (2, 0), (2, -1), (5, 1), (6, 1), (2, 4), (4, 2)])
def test_apply_refuses_bad_keep_or_take_without_touching_files(repo, keep, take):
    before = {rel: read(repo["root"], rel) for rel in ("docs/TASKBOARD.md", "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json")}
    code, out = run(apply_args(repo, keep, take))
    assert code == 1 and "TASKBOARD_RECORDS APPLY FAIL" in out
    assert {rel: read(repo["root"], rel) for rel in before} == before
    assert not os.path.exists(os.path.join(str(repo["root"]), "docs", "archive", "TASKBOARD-RECORDS-0001.md"))


def test_plan_also_refuses_keep_below_one(repo):
    code, out = run(["records-plan", "--repo", str(repo["root"]), "--keep", "0"])
    assert code == 1 and "TASKBOARD_RECORDS PLAN FAIL" in out and "RECORD " not in out


@pytest.mark.parametrize("keep,take,left", [(1, 4, [1]), (2, 3, [1, 2]), (4, 1, [1, 2, 3, 4])])
def test_boundary_keep_one_keep_many_and_one_move(repo, keep, take, left):
    apply_ok(repo, keep=keep, take=take)
    assert [u["task_id"] for u in ta.record_units(read(repo["root"], "docs/TASKBOARD.md"))] == [tid(n) for n in left]
    assert fails_of(repo) == []


def test_only_one_record_on_the_board_has_nothing_to_move(tmp_path, monkeypatch):
    out = build_repo(tmp_path, monkeypatch, make_board([rec(1, 3) + "\n"]))
    code, text = run(["records-apply", "--repo", str(out["root"]), "--task-id", TASK, "--checkpoint-oid", out["c1"], "--keep", "1", "--take", "1"])
    assert code == 1 and "沒有可搬的紀錄" in text


def test_apply_refuses_a_changed_board_or_unresolvable_checkpoint(repo):
    write(repo["root"], "docs/TASKBOARD.md", read(repo["root"], "docs/TASKBOARD.md") + "多出一行\n")
    code, out = run(apply_args(repo, 2, 1))
    assert code == 1 and "看板與 checkpoint 的看板不同" in out
    code, out = run(["records-apply", "--repo", str(repo["root"]), "--task-id", TASK, "--checkpoint-oid", "f" * 40, "--keep", "2", "--take", "1"])
    assert code == 1 and "checkpoint-oid" in out


def test_apply_refuses_fence_text_and_duplicate_task_ids(tmp_path, monkeypatch):
    out = build_repo(tmp_path, monkeypatch, make_board([rec(1) + "\n", rec(2) + "\n````\n", rec(3) + "\n"]))
    code, text = run(["records-apply", "--repo", str(out["root"]), "--task-id", TASK, "--checkpoint-oid", out["c1"], "--keep", "1", "--take", "2",
                     "--allow-multiline", tid(2)])
    assert code == 1 and "四個反引號" in text
    out = build_repo(tmp_path, monkeypatch, make_board([rec(1) + "\n", rec(1) + "\n", rec(2) + "\n"]), "dup")
    code, text = run(["records-apply", "--repo", str(out["root"]), "--task-id", TASK, "--checkpoint-oid", out["c1"], "--keep", "1", "--take", "1"])
    assert code == 1 and "重複" in text


def test_check_without_any_record_archive_passes_when_floor_is_zero(repo):
    assert fails_of(repo) == []


def test_floor_makes_removing_every_record_archive_a_fail(repo):
    apply_ok(repo)
    write(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json", '{\n "schema_version": 1,\n "user_keep": [],\n "archives": []\n}\n')
    assert any("不得移除" in f for f in fails_of(repo))


def test_negative_archive_text_changed(repo):
    apply_ok(repo)
    mutate(repo, "docs/archive/TASKBOARD-RECORDS-0001.md", "封存不是刪除", "封存就是刪除")
    assert any("file_sha256 與封存檔不符" in f for f in fails_of(repo))


def test_negative_unit_text_changed_with_consistent_hashes_is_caught_by_git(repo):
    """作者把封存檔、清單雜湊一起改成「一致」，仍須被 git 在 checkpoint 的原文比對抓到。"""
    apply_ok(repo, keep=2, take=3)
    path = "docs/archive/TASKBOARD-RECORDS-0001.md"
    mutate(repo, path, "續行甲", "續行被改")
    text = read(repo["root"], path)
    manifest = json.loads(read(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json"))
    archive = manifest["record_archives"][0]
    units = ta.parse_records_archive(text)
    for entry, lines in zip(archive["entries"], units):
        entry["unit_sha256"] = ta.sha256_text(ta.unit_text(lines))
        entry["unit_bytes"] = ta.unit_bytes(lines)
    archive["file_sha256"] = ta.sha256_text(text)
    write(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json", ta.dump_manifest(manifest))
    fails = fails_of(repo)
    assert any("與 git 在 checkpoint" in f and tid(3) in f for f in fails), fails
    assert not any("file_sha256" in f or "SHA-256" in f for f in fails)


def test_negative_manifest_unit_hash_or_line_count_changed(repo):
    apply_ok(repo, keep=2, take=3)
    mutate(repo, "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json", '"line_count": 3', '"line_count": 2')
    assert any("SHA-256、位元組數或行數不符" in f for f in fails_of(repo))


def test_negative_wrong_source_line_is_caught_by_git(repo):
    apply_ok(repo)
    manifest = json.loads(read(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json"))
    manifest["record_archives"][0]["entries"][0]["source_line"] += 1
    write(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json", ta.dump_manifest(manifest))
    assert any("與 git 在 checkpoint" in f or "遞增" in f for f in fails_of(repo))


def test_negative_record_returned_to_the_board(repo):
    apply_ok(repo)
    text = read(repo["root"], "docs/TASKBOARD.md")
    write(repo["root"], "docs/TASKBOARD.md", text.replace(BOARD_TAIL, "\n" + rec(5, 5) + "\n" + BOARD_TAIL))
    assert any("看板仍有同一則批次紀錄" in f and tid(5) in f for f in fails_of(repo))


def test_negative_board_must_keep_at_least_one_record(repo):
    apply_ok(repo)
    text = read(repo["root"], "docs/TASKBOARD.md")
    kept = [u for u in ta.record_units(text)]
    for unit in kept:
        text = text.replace(ta.unit_text(unit["lines"]), "")
    write(repo["root"], "docs/TASKBOARD.md", text)
    assert any("至少要保留 1 則" in f for f in fails_of(repo))


def test_negative_checkpoint_not_an_ancestor_or_unresolvable(repo):
    apply_ok(repo)
    write(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json",
          read(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json").replace(repo["c1"], "a" * 40))
    assert any("無法解析或不是" in f for f in fails_of(repo))
    git(repo["root"], "commit", "-q", "--allow-empty", "-m", "later")
    later = git(repo["root"], "rev-parse", "HEAD")
    git(repo["root"], "checkout", "-q", "--orphan", "other")
    git(repo["root"], "commit", "-q", "--allow-empty", "-m", "other root")
    other = git(repo["root"], "rev-parse", "HEAD")
    manifest = json.loads(read(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json"))
    manifest["record_archives"][0]["checkpoint_oid"] = other
    write(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json", ta.dump_manifest(manifest))
    write(repo["root"], "docs/refactor-backlog.md", "上次核對通過的 HEAD：%s\n" % later)
    git(repo["root"], "checkout", "-q", later)
    assert any("無法解析或不是" in f or "checkpoint" in f for f in fails_of(repo))


def test_negative_duplicate_task_id_in_two_record_archives(repo):
    apply_ok(repo, keep=2, take=1)
    manifest = json.loads(read(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json"))
    first = manifest["record_archives"][0]
    second = json.loads(json.dumps(first))
    second["file"] = "docs/archive/TASKBOARD-RECORDS-0002.md"
    manifest["record_archives"].append(second)
    write(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json", ta.dump_manifest(manifest))
    write(repo["root"], second["file"], read(repo["root"], first["file"]).replace("批次紀錄封存 0001", "批次紀錄封存 0002"))
    assert any("重複封存" in f for f in fails_of(repo))


def test_second_apply_numbers_the_next_archive_and_both_verify(repo):
    apply_ok(repo, keep=3, take=1)
    # 第二次要在新的 checkpoint 上做：提交第一次的結果，再以新 commit 為 checkpoint
    git(repo["root"], "add", "-A")
    git(repo["root"], "commit", "-q", "-m", "first records archive")
    c2 = git(repo["root"], "rev-parse", "HEAD")
    write(repo["root"], "docs/refactor-backlog.md", "上次核對通過的 HEAD：%s\n" % c2)
    code, out = run(["records-apply", "--repo", str(repo["root"]), "--task-id", TASK + "-2", "--checkpoint-oid", c2, "--keep", "2", "--take", "1"])
    assert code == 0, out
    assert "TASKBOARD-RECORDS-0002.md" in out
    assert fails_of(repo) == []
    ids = [e["task_id"] for a in json.loads(read(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json"))["record_archives"] for e in a["entries"]]
    assert ids == [tid(5), tid(3)] or ids == [tid(4), tid(3)] or len(ids) == 2


@pytest.mark.parametrize("field,value", [("keep", 0), ("keep", "2"), ("file", "docs/archive/TASKBOARD-RECORDS-0009.md"),
                                          ("checkpoint_oid", "xyz"), ("file_sha256", "abc"), ("entries", [])])
def test_negative_archive_level_fields(repo, field, value):
    apply_ok(repo)
    manifest = json.loads(read(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json"))
    manifest["record_archives"][0][field] = value
    write(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json", ta.dump_manifest(manifest))
    fails = fails_of(repo)
    assert fails and not any("Traceback" in f or "內部錯誤" in f for f in fails)


def test_negative_entry_fields_and_archive_keys(repo):
    apply_ok(repo)
    manifest = json.loads(read(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json"))
    manifest["record_archives"][0]["entries"][0]["unit_bytes"] = "7"
    write(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json", ta.dump_manifest(manifest))
    assert any("欄位型別不符" in f for f in fails_of(repo))
    manifest["record_archives"][0]["entries"][0]["unit_bytes"] = 7
    manifest["record_archives"][0]["extra"] = 1
    write(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json", ta.dump_manifest(manifest))
    assert any("欄位必須恰為" in f for f in fails_of(repo))
    manifest["record_archives"] = {}
    write(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json", ta.dump_manifest(manifest))
    assert any("必須是陣列" in f for f in fails_of(repo))


def test_negative_archive_with_crlf_or_broken_fence(repo):
    apply_ok(repo)
    path = "docs/archive/TASKBOARD-RECORDS-0001.md"
    text = read(repo["root"], path)
    with open(os.path.join(str(repo["root"]), *path.split("/")), "wb") as handle:
        handle.write(text.replace("\n", "\r\n").encode("utf-8"))
    assert any("CR" in f for f in fails_of(repo))
    write(repo["root"], path, text.replace("\n````\n", "\n", 1))
    assert fails_of(repo)


def test_negative_unit_first_line_is_not_that_task(repo):
    apply_ok(repo)
    manifest = json.loads(read(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json"))
    manifest["record_archives"][0]["entries"][0]["task_id"] = "B117-OTHER-R1-261101"
    write(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json", ta.dump_manifest(manifest))
    assert any("首行不是該 TASK_ID" in f for f in fails_of(repo))


def test_check_without_git_is_fail_closed_for_record_archives(repo, monkeypatch):
    apply_ok(repo)

    def broken(*args, **kwargs):
        raise OSError("no git")
    monkeypatch.setattr(ta.subprocess, "run", broken)
    fails = fails_of(repo)
    assert fails and not any("PASS" in f for f in fails)


def test_cli_exit_codes_and_check_29_entry_point(repo):
    code, out = run(["records-plan", "--repo", str(repo["root"]), "--keep", "2"])
    assert code == 0 and "RECORDS_INVENTORY" in out
    code, out = run(apply_args(repo, 2, 2))
    assert code == 0 and "TASKBOARD_RECORDS APPLY PASS entries=2 file=docs/archive/TASKBOARD-RECORDS-0001.md file_sha256=" in out
    repo["mp"].setattr(ta, "RECORD_ARCHIVES_MIN", 1)
    fails, infos = ta.check(str(repo["root"]))
    assert fails == [] and any("批次紀錄封存檔 1 個、封存 2 則" in i for i in infos)
    code, out = run(["check", "--repo", str(repo["root"])])
    assert code == 0 and out.splitlines()[-1] == "TASKBOARD_ARCHIVE CHECK PASS"


def test_unexpected_exception_in_records_check_becomes_a_fail_line(repo, monkeypatch):
    apply_ok(repo)

    def boom(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(ta, "check_records", boom)
    fails = fails_of(repo)
    assert fails == ["CHECK 29 內部錯誤（RuntimeError）"]


def test_records_regex_is_the_same_object_the_c7_guard_uses():
    assert ta.C7_RECORD is hg.C7_RECORD


def test_c7_accepts_a_new_record_after_archiving_at_each_boundary(repo):
    """SO #4：保留 1 則、保留 N 則時，新紀錄插在舊首筆之前仍符合 C7；保留 0 則時 C7 會擋（所以工具拒絕）。"""
    base_board = read(repo["root"], "docs/TASKBOARD.md")
    new_record = "**本批（2026-11-18；本批 B117-NEW-R1-261118）**：新紀錄。"
    for keep, take in ((1, 4), (3, 2), (4, 1)):
        base_files = {"docs/TASKBOARD.md": base_board}
        out = build_repo(repo["root"].parent, repo["mp"], base_board, "c7_%d" % keep)
        extra = ["--allow-multiline", tid(3)] if take >= 3 else []
        code, text = run(["records-apply", "--repo", str(out["root"]), "--task-id", TASK, "--checkpoint-oid", out["c1"], "--keep", str(keep), "--take", str(take)] + extra)
        assert code == 0, text
        board = read(out["root"], "docs/TASKBOARD.md")
        first = ta.record_units(board)[0]
        target = board.replace(first["lines"][0], new_record + "\n\n" + first["lines"][0], 1)
        target = target.replace("**C7_STATUS_LINT_ACTIVE**：啟用。", "**C7_STATUS_LINT_ACTIVE**：啟用。\n\n**最後更新**：2026-11-18；新。", 1)
        base_files = {"docs/TASKBOARD.md": base_board.replace("**C7_STATUS_LINT_ACTIVE**：啟用。", "**C7_STATUS_LINT_ACTIVE**：啟用。\n\n**最後更新**：2026-11-17；舊。", 1)}
        codes = [f.code for f in hg.check_c7_state_lint(base_files, {"docs/TASKBOARD.md": target}, "B117-OLD-R1-261117", "B117-NEW-R1-261118")]
        assert codes == [], (keep, codes)
    # keep=0（工具拒絕的情況）：舊紀錄全搬走，新紀錄之後沒有舊首筆，C7 擋下
    only_new = make_board([new_record + "\n"]).replace("**C7_STATUS_LINT_ACTIVE**：啟用。", "**C7_STATUS_LINT_ACTIVE**：啟用。\n\n**最後更新**：2026-11-18；新。", 1)
    codes = [f.code for f in hg.check_c7_state_lint(base_files, {"docs/TASKBOARD.md": only_new}, "B117-OLD-R1-261117", "B117-NEW-R1-261118")]
    assert "C7_RECORD_ORDER" in codes


MANIFEST = "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json"


def rewrite_archive(repo, edit):
    """改清單後，把封存檔與 file_sha256 依清單重新產生，讓「只有被改的那一項」不一致。"""
    manifest = json.loads(read(repo["root"], MANIFEST))
    archive = manifest["record_archives"][0]
    path = archive["file"]
    by_id = {e["task_id"]: lines for e, lines in zip(archive["entries"], ta.parse_records_archive(read(repo["root"], path)))}
    edit(archive)
    text = ta.render_records_archive(1, archive, by_id)
    archive["file_sha256"] = ta.sha256_text(text)
    write(repo["root"], path, text)
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))


def test_apply_checkpoint_must_be_the_backlog_checkpoint_or_its_ancestor(repo):
    git(repo["root"], "checkout", "-q", "--orphan", "other")
    git(repo["root"], "commit", "-q", "-m", "other root with the same board")
    other = git(repo["root"], "rev-parse", "HEAD")
    git(repo["root"], "checkout", "-q", "-f", repo["c1"])
    code, out = run(["records-apply", "--repo", str(repo["root"]), "--task-id", TASK, "--checkpoint-oid", other, "--keep", "2", "--take", "1"])
    assert code == 1 and "祖先" in out


def test_negative_duplicate_task_id_on_the_board(repo):
    apply_ok(repo)
    text = read(repo["root"], "docs/TASKBOARD.md")
    write(repo["root"], "docs/TASKBOARD.md", text.replace(BOARD_TAIL, "\n" + rec(1, 40) + "\n" + BOARD_TAIL))
    assert any("TASK_ID 重複" in f for f in fails_of(repo))


def test_negative_entries_out_of_board_order_even_when_everything_else_is_consistent(repo):
    apply_ok(repo, keep=1, take=3)
    rewrite_archive(repo, lambda archive: archive["entries"].reverse())
    fails = fails_of(repo)
    assert any("遞增" in f for f in fails) and not any("git 在 checkpoint" in f or "SHA-256" in f for f in fails), fails


def test_negative_archive_header_text_changed_with_a_matching_sha_is_a_regeneration_mismatch(repo):
    apply_ok(repo)
    path = "docs/archive/TASKBOARD-RECORDS-0001.md"
    manifest = json.loads(read(repo["root"], MANIFEST))
    text = read(repo["root"], path).replace("封存不是刪除", "封存即刪除", 1)
    manifest["record_archives"][0]["file_sha256"] = ta.sha256_text(text)
    write(repo["root"], path, text)
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))
    fails = fails_of(repo)
    assert any("重新產生的結果不一致" in f for f in fails) and not any("file_sha256 與封存檔不符" in f for f in fails), fails


def test_negative_manifest_keep_below_one_with_a_regenerated_archive(repo):
    apply_ok(repo)
    rewrite_archive(repo, lambda archive: archive.__setitem__("keep", 0))
    fails = fails_of(repo)
    assert any("keep（須 ≥ 1）" in f for f in fails), fails


def test_negative_entry_with_an_extra_key_only(repo):
    apply_ok(repo)
    rewrite_archive(repo, lambda archive: archive["entries"][0].__setitem__("note", "x"))
    assert any("欄位必須恰為" in f for f in fails_of(repo))


def test_negative_archive_with_more_blocks_than_entries(repo):
    apply_ok(repo)
    manifest = json.loads(read(repo["root"], MANIFEST))
    path = "docs/archive/TASKBOARD-RECORDS-0001.md"
    text = read(repo["root"], path) + "\n````text\n多出來的一則\n````\n"
    manifest["record_archives"][0]["file_sha256"] = ta.sha256_text(text)
    write(repo["root"], path, text)
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))
    assert any("封存檔則數" in f for f in fails_of(repo))


def test_negative_archive_with_an_empty_fence(repo):
    apply_ok(repo)
    manifest = json.loads(read(repo["root"], MANIFEST))
    path = "docs/archive/TASKBOARD-RECORDS-0001.md"
    text = read(repo["root"], path) + "\n````text\n````\n"
    manifest["record_archives"][0]["file_sha256"] = ta.sha256_text(text)
    write(repo["root"], path, text)
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))
    assert any("圍欄結構錯誤" in f for f in fails_of(repo))


def test_negative_checkpoint_commit_without_a_taskboard_is_a_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(ta, "RECORD_ARCHIVES_MIN", 0)
    monkeypatch.setattr(ta, "FIRST_ARCHIVE_SHA256", None)
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "core.autocrlf", "false")
    write(root, "seed.txt", "seed\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "seed without a board")
    seed = git(root, "rev-parse", "HEAD")
    parts = [rec(1, 40) + "\n", rec(2, 20) + "\n", rec(3, 10) + "\n"]
    write(root, "docs/TASKBOARD.md", make_board(parts))
    write(root, "docs/AUDIT-LOG.md", "| 檢查點 | 日期 |\n|---|---|\n")
    write(root, "docs/ARCHIVE-INDEX.md", "# 歸檔索引\n\n| 任務 | docs/archive/TASKBOARD-ARCHIVE-README.md |\n")
    write(root, "docs/archive/TASKBOARD-ARCHIVE-README.md", "# 說明\n")
    write(root, MANIFEST, '{\n "schema_version": 1,\n "user_keep": [],\n "archives": []\n}\n')
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "board")
    c1 = git(root, "rev-parse", "HEAD")
    write(root, "docs/refactor-backlog.md", "上次核對通過的 HEAD：%s\n" % c1)
    code, out = run(["records-apply", "--repo", str(root), "--task-id", TASK, "--checkpoint-oid", c1, "--keep", "1", "--take", "1"])
    assert code == 0, out
    monkeypatch.setattr(ta, "RECORD_ARCHIVES_MIN", 1)
    assert ta.check(str(root))[0] == []
    state = {"root": root}
    rewrite_archive(state, lambda archive: archive.__setitem__("checkpoint_oid", seed))
    assert any("git 讀不到" in f for f in ta.check(str(root))[0])


def test_negative_archive_file_name_out_of_sequence_even_when_the_manifest_agrees(repo):
    apply_ok(repo)
    manifest = json.loads(read(repo["root"], MANIFEST))
    old = manifest["record_archives"][0]["file"]
    new = "docs/archive/TASKBOARD-RECORDS-0002.md"
    write(repo["root"], new, read(repo["root"], old))
    os.remove(os.path.join(str(repo["root"]), *old.split("/")))
    manifest["record_archives"][0]["file"] = new
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))
    assert any("file 必須是 docs/archive/TASKBOARD-RECORDS-0001.md" in f for f in fails_of(repo))


# ---- G7-b3a2：O1 紀錄消失、O2 多行單元點名、O4 只增不減、看板上限、--keep 必填 ----

def second_apply(repo, keep=2, take=1):
    """第一次（keep=3,take=1）提交後，以新 commit 為 checkpoint 做第二次；回傳第二次之前的 checkpoint。"""
    apply_ok(repo, keep=3, take=1)
    git(repo["root"], "add", "-A")
    git(repo["root"], "commit", "-q", "-m", "first records archive")
    c2 = git(repo["root"], "rev-parse", "HEAD")
    write(repo["root"], "docs/refactor-backlog.md", "上次核對通過的 HEAD：%s\n" % c2)
    code, out = run(["records-apply", "--repo", str(repo["root"]), "--task-id", TASK + "-2", "--checkpoint-oid", c2,
                     "--keep", str(keep), "--take", str(take)])
    assert code == 0, out
    repo["mp"].setattr(ta, "RECORD_ARCHIVES_MIN", 2)
    return c2


def test_o1_a_record_deleted_without_archiving_is_a_fail(repo):
    apply_ok(repo)
    assert fails_of(repo) == []
    text = read(repo["root"], "docs/TASKBOARD.md")
    unit = ta.record_units(text)[1]  # 保留的第 2 則：不封存就刪掉
    write(repo["root"], "docs/TASKBOARD.md", text.replace(ta.unit_text(unit["lines"]) + "\n", "", 1))
    assert any("紀錄消失" in f and unit["task_id"] in f for f in fails_of(repo))


def test_o1_a_record_in_an_archive_or_on_the_board_is_not_reported(repo):
    apply_ok(repo, keep=2, take=3)
    assert not any("紀錄消失" in f for f in fails_of(repo))


def test_o1_check_is_fail_closed_when_the_checkpoint_board_cannot_be_read(repo):
    apply_ok(repo)
    write(repo["root"], "docs/refactor-backlog.md", "上次核對通過的 HEAD：%s\n" % ("b" * 40))
    assert fails_of(repo) != []


def test_o4_record_archives_only_grow_a_rewritten_first_archive_is_a_fail(repo):
    second_apply(repo)
    assert fails_of(repo) == []
    manifest = json.loads(read(repo["root"], MANIFEST))
    assert len(manifest["record_archives"]) == 2

    def edit(archive):
        archive["batch"] = archive["batch"] + "-X"  # 自洽重產（SHA 與內容一致）但改寫了既有封存檔
    rewrite_archive(repo, edit)
    got = fails_of(repo)
    assert any("追加" in f for f in got)
    assert not any("與 git 在 checkpoint" in f for f in got)  # 其餘核對都過：只有只增不減擋得住


def test_o4_a_shorter_record_archives_list_than_the_checkpoint_is_a_fail(repo):
    c2 = second_apply(repo)
    git(repo["root"], "add", "-A")
    git(repo["root"], "commit", "-q", "-m", "second records archive")
    c3 = git(repo["root"], "rev-parse", "HEAD")
    write(repo["root"], "docs/refactor-backlog.md", "上次核對通過的 HEAD：%s\n" % c3)
    assert fails_of(repo) == []
    manifest = json.loads(read(repo["root"], MANIFEST))
    manifest["record_archives"] = manifest["record_archives"][:1]
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))
    got = fails_of(repo)
    assert any("追加" in f for f in got)
    assert c2 != c3


def test_o4_a_missing_key_at_the_checkpoint_counts_as_an_empty_list(repo):
    apply_ok(repo)  # checkpoint c1 的 manifest 沒有 record_archives 鍵
    assert "record_archives" not in json.loads(git(repo["root"], "show", "%s:%s" % (repo["c1"], MANIFEST)))
    assert fails_of(repo) == []


def test_o4_the_checkpoint_manifest_that_is_not_json_is_a_fail(repo):
    apply_ok(repo)
    good = read(repo["root"], MANIFEST)
    write(repo["root"], MANIFEST, "{ not json")
    git(repo["root"], "add", "-A")
    git(repo["root"], "commit", "-q", "-m", "bad manifest at checkpoint")
    c = git(repo["root"], "rev-parse", "HEAD")
    write(repo["root"], MANIFEST, good)
    write(repo["root"], "docs/refactor-backlog.md", "上次核對通過的 HEAD：%s\n" % c)
    assert any("不是合法 JSON" in f for f in fails_of(repo))


def test_floor_is_two_in_the_real_constant():
    import importlib
    fresh = importlib.reload(ta)
    assert fresh.RECORD_ARCHIVES_MIN == 2 and fresh.RECORDS_ON_BOARD_MAX == 6


def test_ceiling_seven_records_on_the_board_is_a_fail_and_six_passes(tmp_path, monkeypatch):
    six = build_repo(tmp_path, monkeypatch, make_board([rec(n) + "\n" for n in range(1, 7)]), "six")
    assert not any("超過上限" in f for f in ta.check(str(six["root"]))[0])
    seven = build_repo(tmp_path, monkeypatch, make_board([rec(n) + "\n" for n in range(1, 8)]), "seven")
    assert any("超過上限 6 則" in f for f in ta.check(str(seven["root"]))[0])


def test_o2_multi_line_unit_is_refused_without_naming_and_files_are_untouched(repo):
    before = {rel: read(repo["root"], rel) for rel in ("docs/TASKBOARD.md", MANIFEST)}
    code, out = run(apply_args(repo, 2, 3, allow=[]))
    assert code == 1 and "多行單元" in out and tid(3) in out and "--allow-multiline" in out
    assert {rel: read(repo["root"], rel) for rel in before} == before
    assert not os.path.exists(os.path.join(str(repo["root"]), "docs", "archive", "TASKBOARD-RECORDS-0001.md"))


def test_o2_naming_makes_the_same_move_succeed(repo):
    code, out = run(apply_args(repo, 2, 3, allow=[tid(3)]))
    assert code == 0, out


@pytest.mark.parametrize("allow", [
    ["B117-NOPE-R1-261118"],        # 不存在
    ["B117-T1-R1-261119"],          # 存在但不搬（保留中）
    [tid(4)],                       # 搬，但是單行
    [tid(3), tid(3)],               # 點名重複
])
def test_o2_bad_names_are_refused(repo, allow):
    code, out = run(apply_args(repo, 2, 3, allow=allow))
    assert code == 1 and "APPLY FAIL" in out
    assert not os.path.exists(os.path.join(str(repo["root"]), "docs", "archive", "TASKBOARD-RECORDS-0001.md"))


def test_o2_naming_a_multi_line_unit_that_is_kept_is_refused(repo):
    code, out = run(apply_args(repo, 2, 2, allow=[tid(3)]))  # take=2 只搬第 4、5 則；第 3 則是多行但不在搬移範圍
    assert code == 1 and "不是本次要搬的多行單元" in out


def test_o2_records_plan_prints_the_first_40_chars_of_every_line_of_multi_line_units(tmp_path, monkeypatch):
    long_line = "續" * 60
    out = build_repo(tmp_path, monkeypatch, make_board([rec(1) + "\n", rec(2) + "\n" + long_line + "\n短續行\n", rec(3) + "\n"]), "mlplan")
    code, text = run(["records-plan", "--repo", str(out["root"]), "--keep", "1"])
    assert code == 0
    lines = [l for l in text.splitlines() if l.startswith("  MULTILINE ")]
    assert len(lines) == 3 and all(l.split()[2].startswith("L") for l in lines)
    assert ("續" * 40) in lines[1] and ("續" * 41) not in lines[1] and "短續行" in lines[2]
    assert "MULTILINE %s" % tid(1) not in text  # 單行單元不印


def test_keep_is_required_for_both_records_commands(repo):
    with pytest.raises(SystemExit):
        run(["records-plan", "--repo", str(repo["root"])])
    with pytest.raises(SystemExit):
        run(["records-apply", "--repo", str(repo["root"]), "--task-id", TASK, "--checkpoint-oid", repo["c1"], "--take", "1"])
