import io
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import taskboard_archive as ta
from check_consistency import check_29_taskboard_archive_guard, repo_root

TASK = "B117-TEST-ARCHIVE-R1-261117"


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True).stdout.decode("utf-8").strip()


def write(root, rel, text):
    path = os.path.join(str(root), *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(text.encode("utf-8"))


def read(root, rel):
    with open(os.path.join(str(root), *rel.split("/")), "rb") as handle:
        return handle.read().decode("utf-8")


def board_text(evidence_oid):
    return (
        "# 任務看板\n\n"
        "## B. 重構主線\n\n"
        "| ID | 狀態 | 標題 |\n|---|---|---|\n"
        "| B-01 | 可封存 | 舊列一 |\n"
        "| B-02 | 可封存 | 舊列二，仍被 B-05 引用 |\n"
        "| B-03 | 已完成 | 有證據的列 %s |\n"
        "| B-04 | 已完成 | 沒有證據也不是舊列 |\n"
        "| B-05 | 待辦 | 引用 B-02 |\n"
        "| B-06 | 可封存 | 舊列六 |\n"
        "\n## 封存區\n\n（目前為空）\n" % evidence_oid)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(ta, "LEGACY_IDS", frozenset({"B-01", "B-02", "B-06"}))
    monkeypatch.setattr(ta, "LEGACY_BATCH", TASK)
    monkeypatch.setattr(ta, "FIRST_ARCHIVE_ENTRIES", 3)
    monkeypatch.setattr(ta, "FIRST_ARCHIVE_SHA256", None)  # 尚未寫成；apply_ok 之後才釘定
    monkeypatch.setattr(ta, "RECORD_ARCHIVES_MIN", 0)  # 本檔測看板列封存；批次紀錄封存見 test_taskboard_records.py
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    # Windows git profiles default to core.autocrlf=true, which would turn checked-out fixture files into CRLF.
    git(root, "config", "core.autocrlf", "false")
    write(root, "seed.txt", "seed\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "seed")
    c1 = git(root, "rev-parse", "HEAD")
    write(root, "docs/TASKBOARD.md", board_text(c1))
    write(root, "docs/AUDIT-LOG.md", "| 檢查點 | 日期 | 依據 | 摘要 |\n|---|---|---|---|\n| %s | 2026-11-17 | 核對 B-03 | **核對通過** |\n" % c1)
    write(root, "docs/ARCHIVE-INDEX.md", "# 歸檔索引\n\n| 任務 | docs/archive/TASKBOARD-ARCHIVE-README.md |\n")
    write(root, "docs/archive/TASKBOARD-ARCHIVE-README.md", "# 說明\n")
    write(root, "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json", '{\n "schema_version": 1,\n "user_keep": [],\n "archives": []\n}\n')
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "state")
    c2 = git(root, "rev-parse", "HEAD")
    write(root, "docs/refactor-backlog.md", "上次核對通過的 HEAD：%s\n" % c2)
    return {"root": root, "c1": c1, "c2": c2, "mp": monkeypatch}


def run(args):
    out = io.StringIO()
    code = ta.main(args, out=out)
    return code, out.getvalue()


def apply_ok(repo, ids=("B-01", "B-03", "B-06")):
    args = ["apply", "--repo", str(repo["root"]), "--task-id", TASK, "--checkpoint-oid", repo["c2"]]
    for rid in ids:
        args += ["--entry", rid]
    code, out = run(args)
    assert code == 0, out
    # 第一個封存檔寫成後即固定：把它的 SHA-256 釘進工具常數（正式 repo 的值在 scripts/taskboard_archive.py）
    repo["mp"].setattr(ta, "FIRST_ARCHIVE_SHA256", ta.sha256_text(read(repo["root"], "docs/archive/TASKBOARD-ARCHIVE-0001.md")))
    repo["mp"].setattr(ta, "FIRST_ARCHIVE_ENTRIES", len(ids))
    # 封存是移動：封存區仍要指向封存目錄（本批的 TASKBOARD 文字由批次作者寫）
    text = read(repo["root"], "docs/TASKBOARD.md")
    write(repo["root"], "docs/TASKBOARD.md", text.replace("（目前為空）", "已移到 docs/archive/TASKBOARD-ARCHIVE-0001.md"))
    return out


def fails_of(repo):
    fails, _ = ta.check(str(repo["root"]))
    return fails


def test_pinned_legacy_set_and_decision_are_fixed():
    # 模組級常數在 fixture 之外讀取，才是正式固定清單
    import importlib
    fresh = importlib.reload(ta)
    assert len(fresh.LEGACY_IDS) == 31
    assert fresh.LEGACY_DECISION == "USER-2026-11-17-G7B-D1"
    assert {"B-06", "B-125", "B-60", "B-121"} & fresh.LEGACY_IDS == {"B-06"}


def test_plan_reports_eligible_and_holds(repo):
    code, out = run(["plan", "--repo", str(repo["root"])])
    assert code == 0
    lines = {l.split()[1]: l for l in out.splitlines()}
    assert "ELIGIBLE USER_CONFIRMED_LEGACY" in lines["B-01"]
    assert "ELIGIBLE MACRO_PASS_ANCESTOR" in lines["B-03"]
    assert "HOLD NO_EVIDENCE" in lines["B-04"]
    assert "HOLD ACTIVE_REF:B-05" in lines["B-02"]
    assert "B-05" not in lines  # 待辦列本身不是封存對象


def test_plan_prints_the_context_of_each_active_reference(repo):
    code, out = run(["plan", "--repo", str(repo["root"])])
    assert code == 0
    refs = [l for l in out.splitlines() if l.startswith("REF_CONTEXT ")]
    assert len(refs) == 1  # 只有 B-02 被進行中列 B-05 引用
    assert refs[0].startswith("REF_CONTEXT B-02<-B-05 line=") and "引用 B-02" in refs[0]
    assert not any(l.startswith("REF_CONTEXT B-01") for l in out.splitlines())


def test_plan_reference_context_is_cut_to_30_characters_each_side(repo):
    root = repo["root"]
    left, right = "甲" * 45, "乙" * 45
    write(root, "docs/TASKBOARD.md", read(root, "docs/TASKBOARD.md").replace("| B-05 | 待辦 | 引用 B-02 |", "| B-05 | 待辦 | %s B-02 %s |" % (left, right)))
    _, out = run(["plan", "--repo", str(root)])
    ref = [l for l in out.splitlines() if l.startswith("REF_CONTEXT B-02<-B-05")][0]
    assert ref.endswith("…" + "甲" * 29 + " B-02 " + "乙" * 29 + "…")
    assert "甲" * 31 not in ref and "乙" * 31 not in ref


def test_plan_prints_no_context_for_references_from_rows_that_are_not_active(repo):
    root = repo["root"]
    write(root, "docs/TASKBOARD.md", read(root, "docs/TASKBOARD.md").replace("| B-06 | 可封存 | 舊列六 |", "| B-06 | 可封存 | 舊列六 |\n| B-07 | 已完成 | 提到 B-01 但已完成 |"))
    _, out = run(["plan", "--repo", str(root)])
    assert not any(l.startswith("REF_CONTEXT B-01<-") for l in out.splitlines())
    assert "ELIGIBLE USER_CONFIRMED_LEGACY" in [l for l in out.splitlines() if l.startswith("PLAN B-01")][0]


def test_ref_context_returns_empty_when_the_row_is_not_named():
    assert ta.ref_context("沒有任何列編號", "B-02") == ""
    assert ta.ref_context("B-020 與 XB-02 不算", "B-02") == ""


def test_plan_holds_user_keep_and_ambiguous_ids(repo):
    root = repo["root"]
    write(root, "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json", '{"schema_version": 1, "user_keep": ["B-01"], "archives": []}\n')
    write(root, "docs/TASKBOARD.md", read(root, "docs/TASKBOARD.md").replace("| B-06 | 可封存 | 舊列六 |", "| B-06 | 可封存 | 舊列六 |\n| B-06 | 可封存 | 重複 |"))
    _, out = run(["plan", "--repo", str(root)])
    assert "B-01 line=" in out and "HOLD USER_KEEP" in out.split("B-01 ")[1].splitlines()[0]
    assert "AMBIGUOUS_ID" in out


def test_apply_moves_rows_verbatim_and_check_passes(repo):
    root = repo["root"]
    before = read(root, "docs/TASKBOARD.md")
    apply_ok(repo)
    after = read(root, "docs/TASKBOARD.md")
    for rid in ("B-01", "B-03", "B-06"):
        assert "| %s |" % rid not in after
    archive = read(root, "docs/archive/TASKBOARD-ARCHIVE-0001.md")
    for line in before.split("\n"):
        if line.startswith(("| B-01 |", "| B-03 |", "| B-06 |")):
            assert "\n````text\n%s\n````\n" % line in archive
    manifest = json.loads(read(root, "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json"))
    entries = manifest["archives"][0]["entries"]
    assert [e["id"] for e in entries] == ["B-01", "B-03", "B-06"]
    assert entries[1]["basis"] == "MACRO_PASS_ANCESTOR" and entries[1]["evidence_commit"] == repo["c1"]
    assert entries[0]["basis"] == "USER_CONFIRMED_LEGACY" and entries[0]["user_decision"] == "USER-2026-11-17-G7B-D1"
    assert fails_of(repo) == []
    code, out = run(["check", "--repo", str(root)])
    assert code == 0 and "TASKBOARD_ARCHIVE CHECK PASS" in out


@pytest.mark.parametrize("ids,reason", [
    (("B-02",), "ACTIVE_REF"),
    (("B-04",), "NO_EVIDENCE"),
    (("B-05",), "不是可封存狀態"),
    (("B-99",), "不是可封存狀態"),
    (("B-01", "B-01"), "重複"),
])
def test_apply_refuses_ineligible_rows_without_touching_files(repo, ids, reason):
    root = repo["root"]
    snapshot = {rel: read(root, rel) for rel in ("docs/TASKBOARD.md", "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json")}
    args = ["apply", "--repo", str(root), "--task-id", TASK, "--checkpoint-oid", repo["c2"]]
    for rid in ids:
        args += ["--entry", rid]
    code, out = run(args)
    assert code == 1 and "APPLY FAIL" in out and reason in out
    assert {rel: read(root, rel) for rel in snapshot} == snapshot
    assert not os.path.exists(os.path.join(str(root), "docs", "archive", "TASKBOARD-ARCHIVE-0001.md"))


def test_apply_refuses_wrong_evidence_and_bad_checkpoint(repo):
    root = repo["root"]
    code, out = run(["apply", "--repo", str(root), "--task-id", TASK, "--checkpoint-oid", repo["c2"], "--entry", "B-03:" + repo["c2"]])
    assert code == 1 and "evidence" in out
    code, out = run(["apply", "--repo", str(root), "--task-id", TASK, "--checkpoint-oid", "0" * 40, "--entry", "B-01"])
    assert code == 1 and "checkpoint" in out
    code, out = run(["apply", "--repo", str(root), "--task-id", "", "--checkpoint-oid", repo["c2"]])
    assert code == 1


def mutate(repo, rel, old, new):
    text = read(repo["root"], rel)
    assert old in text
    write(repo["root"], rel, text.replace(old, new, 1))


ARCHIVE = "docs/archive/TASKBOARD-ARCHIVE-0001.md"
MANIFEST = "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json"


def test_negative_archive_text_changed(repo):
    apply_ok(repo)
    mutate(repo, ARCHIVE, "舊列一", "舊列一（被改）")
    assert any("SHA-256" in f or "file_sha256" in f for f in fails_of(repo))


def test_negative_manifest_hash_changed(repo):
    apply_ok(repo)
    manifest = json.loads(read(repo["root"], MANIFEST))
    manifest["archives"][0]["entries"][0]["row_sha256"] = "0" * 64
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))
    assert any("SHA-256" in f for f in fails_of(repo))


def test_negative_row_returned_to_board(repo):
    apply_ok(repo)
    mutate(repo, "docs/TASKBOARD.md", "| B-05 | 待辦 |", "| B-01 | 可封存 | 舊列一 |\n| B-05 | 待辦 |")
    assert any("看板仍有同 ID" in f for f in fails_of(repo))


def test_negative_legacy_id_outside_fixed_list(repo, monkeypatch):
    apply_ok(repo)
    monkeypatch.setattr(ta, "LEGACY_IDS", frozenset({"B-02"}))
    assert any("USER_CONFIRMED_LEGACY 只限固定清單" in f for f in fails_of(repo))


def test_negative_legacy_wrong_decision_or_evidence(repo):
    apply_ok(repo)
    manifest = json.loads(read(repo["root"], MANIFEST))
    manifest["archives"][0]["entries"][0]["user_decision"] = "USER-OTHER"
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))
    assert any("只限固定清單" in f for f in fails_of(repo))


def test_negative_evidence_without_macro_pass(repo):
    apply_ok(repo)
    write(repo["root"], "docs/AUDIT-LOG.md", "| 檢查點 | 日期 |\n|---|---|\n| %s | 2026-11-17 | 未通過 |\n" % repo["c1"])
    assert any("EVIDENCE_NO_MACRO_PASS" in f for f in fails_of(repo))


def test_negative_evidence_not_in_row_text(repo):
    apply_ok(repo)
    manifest = json.loads(read(repo["root"], MANIFEST))
    manifest["archives"][0]["entries"][1]["evidence_commit"] = repo["c2"]
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))
    assert any("EVIDENCE_NOT_IN_ROW" in f for f in fails_of(repo))


def test_negative_evidence_not_an_ancestor_of_checkpoint(repo):
    root = repo["root"]
    git(root, "checkout", "-q", "--orphan", "other")
    git(root, "rm", "-rfq", "--cached", ".")
    write(root, "other.txt", "x\n")
    git(root, "add", "other.txt")
    git(root, "commit", "-q", "-m", "orphan")
    stray = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "-q", "-f", "master" if "master" in git(root, "branch", "--list", "master") else "main")
    write(root, "docs/TASKBOARD.md", read(root, "docs/TASKBOARD.md").replace(repo["c1"], stray))
    write(root, "docs/AUDIT-LOG.md", read(root, "docs/AUDIT-LOG.md") + "| %s | 2026-11-17 | y B-03 | **核對通過** |\n" % stray)
    code, out = run(["apply", "--repo", str(root), "--task-id", TASK, "--checkpoint-oid", repo["c2"], "--entry", "B-03"])
    assert code == 1  # 工具在封存前就拒絕：證據不是 checkpoint 的祖先，視為沒有證據
    assert "NO_EVIDENCE" in out


def test_negative_user_keep_contains_archived_id(repo):
    apply_ok(repo)
    manifest = json.loads(read(repo["root"], MANIFEST))
    manifest["user_keep"] = ["B-06"]
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))
    assert any("USER 標記保留" in f for f in fails_of(repo))


def test_negative_archive_with_crlf_or_bom(repo):
    apply_ok(repo)
    text = read(repo["root"], ARCHIVE)
    with open(os.path.join(str(repo["root"]), *ARCHIVE.split("/")), "wb") as handle:
        handle.write(text.replace("\n", "\r\n").encode("utf-8"))
    assert any("CR" in f for f in fails_of(repo))
    with open(os.path.join(str(repo["root"]), *ARCHIVE.split("/")), "wb") as handle:
        handle.write(b"\xef\xbb\xbf" + text.encode("utf-8"))
    assert any("BOM" in f for f in fails_of(repo))


def test_negative_entry_count_or_fields_mismatch(repo):
    apply_ok(repo)
    manifest = json.loads(read(repo["root"], MANIFEST))
    entry = manifest["archives"][0]["entries"].pop()
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))
    assert any("列數" in f for f in fails_of(repo))
    manifest["archives"][0]["entries"].append(dict(entry, extra="x"))
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))
    assert any("欄位必須恰為" in f for f in fails_of(repo))


def test_negative_duplicate_id_in_two_archives(repo):
    apply_ok(repo)
    manifest = json.loads(read(repo["root"], MANIFEST))
    second = json.loads(json.dumps(manifest["archives"][0]))
    second["file"] = "docs/archive/TASKBOARD-ARCHIVE-0002.md"
    rows = ta.parse_archive_rows(read(repo["root"], ARCHIVE))
    by_id = {e["id"]: r for e, r in zip(second["entries"], rows)}
    text = ta.render_archive(2, second, by_id)
    write(repo["root"], second["file"], text)
    second["file_sha256"] = ta.sha256_text(text)
    manifest["archives"].append(second)
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))
    assert any("重複封存" in f for f in fails_of(repo))


def test_negative_regenerated_text_differs(repo):
    apply_ok(repo)
    text = read(repo["root"], ARCHIVE).replace("- 封存時狀態：可封存", "- 封存時狀態：已完成", 1)
    write(repo["root"], ARCHIVE, text)
    manifest = json.loads(read(repo["root"], MANIFEST))
    manifest["archives"][0]["file_sha256"] = ta.sha256_text(text)
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))
    assert any("重新產生的結果不一致" in f for f in fails_of(repo))


@pytest.mark.parametrize("rel,old,new,needle", [
    ("docs/ARCHIVE-INDEX.md", "docs/archive/TASKBOARD-ARCHIVE-", "docs/archive/other/", "ARCHIVE-INDEX"),
    ("docs/TASKBOARD.md", "已移到 docs/archive/TASKBOARD-ARCHIVE-0001.md", "已移走", "封存區"),
])
def test_negative_pointers_must_be_reachable_both_ways(repo, rel, old, new, needle):
    apply_ok(repo)
    mutate(repo, rel, old, new)
    assert any(needle in f for f in fails_of(repo))


def test_negative_missing_readme_manifest_and_audit_log(repo):
    apply_ok(repo)
    os.remove(os.path.join(str(repo["root"]), "docs", "archive", "TASKBOARD-ARCHIVE-README.md"))
    assert any("README.md 不存在" in f for f in fails_of(repo))
    os.remove(os.path.join(str(repo["root"]), "docs", "AUDIT-LOG.md"))
    assert any("AUDIT-LOG.md" in f for f in fails_of(repo))
    os.remove(os.path.join(str(repo["root"]), "docs", "archive", "TASKBOARD-ARCHIVE-MANIFEST.json"))
    assert any("MANIFEST.json" in f for f in fails_of(repo))


def test_negative_checkpoint_line_missing_or_unresolvable(repo):
    apply_ok(repo)
    write(repo["root"], "docs/refactor-backlog.md", "沒有 checkpoint\n")
    assert any("上次核對通過的 HEAD" in f for f in fails_of(repo))
    write(repo["root"], "docs/refactor-backlog.md", "上次核對通過的 HEAD：%s\n" % ("a" * 40))
    assert any("無法解析" in f for f in fails_of(repo))


def test_check_without_git_is_fail_closed_for_evidence_entries(repo, tmp_path):
    apply_ok(repo)
    copy = tmp_path / "nogit"
    for current, _, files in os.walk(str(repo["root"])):
        if os.sep + ".git" in current + os.sep:
            continue
        for name in files:
            rel = os.path.relpath(os.path.join(current, name), str(repo["root"])).replace(os.sep, "/")
            write(copy, rel, read(repo["root"], rel))
    fails, _ = ta.check(str(copy))
    assert fails and any("無法解析" in f or "git" in f for f in fails)


@pytest.mark.parametrize("error", [subprocess.TimeoutExpired(cmd="git", timeout=60), OSError("no git")])
def test_git_timeout_or_launch_failure_is_a_fail_not_a_pass(repo, monkeypatch, error):
    apply_ok(repo)

    def broken(*args, **kwargs):
        raise error

    monkeypatch.setattr(ta.subprocess, "run", broken)
    assert any("git 無法執行" in f for f in fails_of(repo))


def test_evidence_must_be_a_full_commit_in_the_row(repo):
    root = repo["root"]
    write(root, "docs/TASKBOARD.md", read(root, "docs/TASKBOARD.md").replace(repo["c1"], repo["c1"][:7]))
    code, out = run(["plan", "--repo", str(root)])
    assert code == 0 and "PLAN B-03" in out
    assert [l for l in out.splitlines() if l.startswith("PLAN B-03")][0].endswith("HOLD NO_EVIDENCE")


def test_negative_pass_row_must_name_the_archived_row(repo):
    apply_ok(repo)
    write(repo["root"], "docs/AUDIT-LOG.md", "| 檢查點 | 日期 | 依據 | 摘要 |\n|---|---|---|---|\n| %s | 2026-11-17 | 核對 B-30 | **核對通過** |\n" % repo["c1"])
    assert any("EVIDENCE_PASS_ROW_DOES_NOT_NAME_ROW" in f for f in fails_of(repo))


def test_plan_holds_when_the_pass_row_names_another_row(repo):
    write(repo["root"], "docs/AUDIT-LOG.md", "| 檢查點 | 日期 | 依據 | 摘要 |\n|---|---|---|---|\n| %s | 2026-11-17 | 核對 B-30 | **核對通過** |\n" % repo["c1"])
    code, out = run(["plan", "--repo", str(repo["root"])])
    assert [l for l in out.splitlines() if l.startswith("PLAN B-03")][0].endswith("HOLD NO_EVIDENCE")


@pytest.mark.parametrize("row_id,text,named", [
    ("B-03", "核對 B-03 完成", True), ("B-03", "核對 B03 完成", True), ("B-03", "核對 B-031", False),
    ("B-03", "核對 XB-03", False), ("B-3", "核對 B-30", False), ("TG-MVP-01A", "TG-MVP-01A、TG-MVP-01B", True),
    ("TG-MVP-01B", "TG-MVP-01A 完成", False),
])
def test_id_named_uses_id_boundaries(row_id, text, named):
    assert ta.id_named(row_id, text) is named


def test_short_audit_hashes_count_only_when_they_resolve_to_the_oid(repo):
    root = repo["root"]
    short, unknown = repo["c1"][:7], "abcdef1"
    rows = ta.audit_pass_rows(
        "| 檢查點 | 日期 | 依據 | 摘要 |\n|---|---|---|---|\n| %s | 2026-11-17 | 核對 B-03 | **核對通過** |\n"
        "| %s | 2026-11-17 | 核對 B-03 | **核對通過** |\n| %s | 2026-11-17 | 核對 B-03 | 未通過 |\n" % (short, unknown, repo["c2"][:7]))
    assert [token for token, _ in rows] == [short, unknown]
    assert "B-03" in ta.pass_text_for(str(root), repo["c1"], rows)
    assert ta.pass_text_for(str(root), repo["c2"], rows) == ""
    assert ta.pass_text_for(str(root), "a" * 40, rows) == ""


@pytest.mark.parametrize("resolved", ["other", None])
def test_short_prefix_token_is_rejected_when_rev_parse_does_not_return_the_oid(repo, monkeypatch, resolved):
    short = repo["c1"][:7]
    rows = [(short, "| %s | x B-03 | **核對通過** |" % short)]
    answer = repo["c2"] if resolved == "other" else None
    monkeypatch.setattr(ta, "resolve_commit", lambda root, token: answer)
    assert ta.pass_text_for(str(repo["root"]), repo["c1"], rows) == ""


def test_full_audit_hashes_are_matched_without_calling_git(repo, monkeypatch):
    rows = [(repo["c1"], "| %s | x B-03 | **核對通過** |" % repo["c1"])]

    def no_git(*args, **kwargs):
        raise AssertionError("git must not be called for a full 40-digit pass row")

    monkeypatch.setattr(ta, "resolve_commit", no_git)
    assert "B-03" in ta.pass_text_for("/nonexistent", repo["c1"], rows)


def test_negative_first_archive_is_pinned(repo):
    apply_ok(repo)
    manifest = json.loads(read(repo["root"], MANIFEST))
    archive = manifest["archives"][0]
    dropped = archive["entries"].pop(0)
    rows = ta.parse_archive_rows(read(repo["root"], ARCHIVE))
    kept = {e["id"]: r for e, r in zip([dropped] + archive["entries"], rows) if e["id"] != dropped["id"]}
    text = ta.render_archive(1, archive, kept)
    archive["file_sha256"] = ta.sha256_text(text)
    write(repo["root"], ARCHIVE, text)
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))
    assert any("第一個封存檔已固定" in f for f in fails_of(repo))


def test_negative_emptying_the_manifest_cannot_remove_the_pinned_first_archive(repo):
    apply_ok(repo)
    write(repo["root"], MANIFEST, '{\n "schema_version": 1,\n "user_keep": [],\n "archives": []\n}\n')
    os.remove(os.path.join(str(repo["root"]), *ARCHIVE.split("/")))
    assert any("第一個封存檔已固定，不得移除或清空" in f for f in fails_of(repo))


def test_legacy_basis_is_refused_after_the_first_archive(repo):
    apply_ok(repo, ids=("B-01", "B-03"))
    code, out = run(["apply", "--repo", str(repo["root"]), "--task-id", TASK, "--checkpoint-oid", repo["c2"], "--entry", "B-06"])
    assert code == 1 and "NO_EVIDENCE" in out


def test_negative_legacy_entry_outside_the_first_archive(repo):
    apply_ok(repo, ids=("B-01", "B-03"))
    root = repo["root"]
    board = read(root, "docs/TASKBOARD.md")
    row = [l for l in board.split("\n") if l.startswith("| B-06 |")][0]
    manifest = json.loads(read(root, MANIFEST))
    entry = {"id": "B-06", "section": "B. 重構主線", "source_line": 1, "status_at_archive": "可封存", "basis": ta.BASIS_LEGACY,
             "evidence_commit": None, "user_decision": ta.LEGACY_DECISION, "row_sha256": ta.sha256_text(row), "row_bytes": len(row.encode("utf-8"))}
    second = {"file": "docs/archive/TASKBOARD-ARCHIVE-0002.md", "batch": "B117-X", "checkpoint_oid": repo["c2"], "file_sha256": "", "entries": [entry]}
    text = ta.render_archive(2, second, {"B-06": row})
    second["file_sha256"] = ta.sha256_text(text)
    manifest["archives"].append(second)
    write(root, "docs/archive/TASKBOARD-ARCHIVE-0002.md", text)
    write(root, MANIFEST, ta.dump_manifest(manifest))
    write(root, "docs/TASKBOARD.md", board.replace(row + "\n", ""))
    assert any("只能出現在第一個封存檔" in f for f in fails_of(repo))


@pytest.mark.parametrize("field,value", [
    ("id", ["B-01"]), ("row_bytes", "5"), ("source_line", True), ("row_sha256", "xyz"),
    ("evidence_commit", "abc"), ("section", None),
])
def test_negative_entry_field_types_fail_without_a_traceback(repo, field, value):
    apply_ok(repo)
    manifest = json.loads(read(repo["root"], MANIFEST))
    manifest["archives"][0]["entries"][0][field] = value
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))
    fails = fails_of(repo)
    assert any("欄位型別不符" in f for f in fails)
    assert not any("內部錯誤" in f for f in fails)


def test_negative_archive_level_field_types_fail(repo):
    apply_ok(repo)
    manifest = json.loads(read(repo["root"], MANIFEST))
    manifest["archives"][0]["file_sha256"] = 5
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))
    assert any("格式不符" in f for f in fails_of(repo))


def test_unexpected_exception_becomes_a_fail_line(repo, monkeypatch):
    apply_ok(repo)

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(ta, "read_checkpoint", boom)
    assert any("內部錯誤" in f for f in fails_of(repo))


def test_plan_reports_unexpected_exception_as_a_fail_line(repo, monkeypatch):
    def boom(*args, **kwargs):
        raise KeyError("x")

    monkeypatch.setattr(ta, "evaluate", boom)
    code, out = run(["plan", "--repo", str(repo["root"])])
    assert code == 1 and "PLAN FAIL" in out and "Traceback" not in out


def test_negative_same_id_back_on_the_board_with_loose_spacing(repo):
    apply_ok(repo)
    write(repo["root"], "docs/TASKBOARD.md", read(repo["root"], "docs/TASKBOARD.md").replace("\n## 封存區", "\n|  B-06 | 待辦 | 重新開啟 | x |\n\n## 封存區"))
    assert any("看板仍有同 ID 的列" in f for f in fails_of(repo))


def test_cli_plan_and_check_exit_codes(repo):
    code, out = run(["plan", "--repo", str(repo["root"])])
    assert code == 0 and out.startswith("PLAN ")
    code, out = run(["check", "--repo", str(repo["root"])])
    assert code == 1 and "TASKBOARD_ARCHIVE CHECK FAIL" in out  # 封存區尚未指向封存目錄
    code, out = run(["plan", "--repo", str(repo["root"]) + "-missing"])
    assert code == 1 and "PLAN FAIL" in out


def test_real_repo_check_29_passes():
    fails, infos = check_29_taskboard_archive_guard(repo_root)
    assert fails == []
    assert any("封存列" in i for i in infos)


# --- G7-b3b1：看板列與清單的只增不減（checkpoint 看板上的列不得消失；archives 只追加；user_keep 不減） ---------

MANIFEST = "docs/archive/TASKBOARD-ARCHIVE-MANIFEST.json"


def commit_as_checkpoint(repo, message):
    git(repo["root"], "add", "-A")
    git(repo["root"], "commit", "-q", "-m", message)
    c = git(repo["root"], "rev-parse", "HEAD")
    write(repo["root"], "docs/refactor-backlog.md", "上次核對通過的 HEAD：%s\n" % c)
    return c


def test_g7b3b1_a_row_removed_without_archiving_is_a_fail(repo):
    text = read(repo["root"], "docs/TASKBOARD.md")
    write(repo["root"], "docs/TASKBOARD.md", text.replace("| B-04 | 已完成 | 沒有證據也不是舊列 |\n", ""))
    got = fails_of(repo)
    assert any("列消失" in f and "B-04" in f for f in got), got


def test_g7b3b1_archived_rows_and_rows_with_loose_spacing_are_not_reported(repo):
    apply_ok(repo)
    text = read(repo["root"], "docs/TASKBOARD.md")
    write(repo["root"], "docs/TASKBOARD.md", text.replace("| B-04 | 已完成 |", "|  B-04  | 已完成 |"))
    assert not any("列消失" in f for f in fails_of(repo))


def test_g7b3b1_header_row_id_is_tracked_like_any_other_row(repo):
    # 表頭「| ID | 狀態 |」符合列的格式；整張表被刪掉時也會被擋下（真實看板的表頭寫法）
    text = read(repo["root"], "docs/TASKBOARD.md")
    write(repo["root"], "docs/TASKBOARD.md", text.replace("| ID | 狀態 | 標題 |\n", ""))
    assert any("列消失" in f and "ID：" in f for f in fails_of(repo))


def test_g7b3b1_archives_list_must_extend_the_checkpoint_list(repo):
    apply_ok(repo)
    commit_as_checkpoint(repo, "first archive")
    assert fails_of(repo) == []
    manifest = json.loads(read(repo["root"], MANIFEST))
    manifest["archives"][0]["batch"] = manifest["archives"][0]["batch"] + "-X"
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))
    got = fails_of(repo)
    assert any("archives 不是 checkpoint" in f for f in got), got


def test_g7b3b1_user_keep_can_grow_but_not_shrink(repo):
    manifest = json.loads(read(repo["root"], MANIFEST))
    manifest["user_keep"] = ["B-05"]
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))
    commit_as_checkpoint(repo, "user keep")
    manifest["user_keep"] = ["B-05", "B-04"]
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))
    assert not any("user_keep 少了" in f for f in fails_of(repo))
    manifest["user_keep"] = ["B-04"]
    write(repo["root"], MANIFEST, ta.dump_manifest(manifest))
    assert any("user_keep 少了 B-05" in f for f in fails_of(repo))


@pytest.mark.parametrize("bad", [
    '{"schema_version": 1, "archives": []}',
    '{"schema_version": 1, "user_keep": []}',
    '{"schema_version": 1, "user_keep": {}, "archives": []}',
])
def test_g7b3b1_checkpoint_manifest_without_both_arrays_is_a_fail(repo, bad):
    good = read(repo["root"], MANIFEST)
    write(repo["root"], MANIFEST, bad)
    commit_as_checkpoint(repo, "bad manifest at checkpoint")
    write(repo["root"], MANIFEST, good)
    assert any("缺少 archives 或 user_keep 陣列" in f for f in fails_of(repo))
