import json
import os
import sys
import subprocess
import hashlib
import pytest

# Ensure scripts dir is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from check_consistency import (
    check_27_secret_guidance_guard,
    c27_split_units,
    run_checks,
    repo_root,
)


@pytest.fixture
def tmp_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    gov = root / "docs" / "governance"
    gov.mkdir(parents=True)
    skills = root / "skills" / "sample-skill"
    skills.mkdir(parents=True)

    inv = {
        "schema_version": 1,
        "entries": [
            {
                "id": "mock-secret-item",
                "legacy_names": ["MOCK_LEGACY_NAME", "OLD_ENV_TOKEN"]
            }
        ]
    }
    with open(gov / "secret-inventory.json", "w", encoding="utf-8") as f:
        json.dump(inv, f, indent=2)

    exc = {
        "schema_version": 1,
        "description": "test exceptions",
        "exceptions": []
    }
    with open(gov / "secret-guidance-exceptions.json", "w", encoding="utf-8") as f:
        json.dump(exc, f, indent=2)

    board = (
        "# TASKBOARD\n\n"
        "| SEC-04 | 進行中 | In progress task |\n"
        "| SEC-DONE | 已完成 | Finished task |\n"
    )
    with open(root / "docs" / "TASKBOARD.md", "w", encoding="utf-8") as f:
        f.write(board)

    with open(root / "docs" / "mcp-environment-guide.md", "w", encoding="utf-8") as f:
        f.write("# MCP Environment Guide\nNormal text without persistent secrets.\n")

    with open(skills / "SKILL.md", "w", encoding="utf-8") as f:
        f.write("# Sample Skill\nNormal text without secrets.\n")

    subprocess.run(["git", "init"], cwd=str(root), capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=str(root), capture_output=True, check=True)
    return root


def git_add_all(root):
    subprocess.run(["git", "add", "."], cwd=str(root), capture_output=True, check=True)


# T1 未列管命中：區塊內有「User 層級環境變數」與「金鑰」→ 失敗訊息含「未列管」
def test_t1_unlisted_flagged_user_level_and_key(tmp_repo):
    skill_file = tmp_repo / "skills" / "sample-skill" / "SKILL.md"
    skill_file.write_text("# Sample Skill\n請將金鑰存於 User 層級環境變數中。\n", encoding="utf-8")
    git_add_all(tmp_repo)

    fails, infos = check_27_secret_guidance_guard(str(tmp_repo))
    assert len(fails) > 0
    assert any("未列管" in f for f in fails)


# T2 跨段落：同一標題區塊內，一段只有 SetEnvironmentVariable(名稱, 值, 'User')，另一段表格列出 inventory 舊名稱 → 命中
def test_t2_cross_paragraph_set_env_and_legacy_name(tmp_repo):
    guide_file = tmp_repo / "docs" / "mcp-environment-guide.md"
    content = (
        "## Setup Guide\n\n"
        "[System.Environment]::SetEnvironmentVariable('FOO', 'BAR', 'User')\n\n"
        "| Variable | Description |\n"
        "| MOCK_LEGACY_NAME | token description |\n"
    )
    guide_file.write_text(content, encoding="utf-8")
    git_add_all(tmp_repo)

    fails, infos = check_27_secret_guidance_guard(str(tmp_repo))
    assert len(fails) > 0
    assert any("未列管" in f for f in fails)


# T3 表格：區塊標頭寫「設在 Windows User 層級」之表格，資料列含舊名稱 → 命中
def test_t3_table_user_level_heading_and_legacy_name(tmp_repo):
    skill_file = tmp_repo / "skills" / "sample-skill" / "SKILL.md"
    content = (
        "## Configuration\n\n"
        "| Server | 前置需求 | 需要的環境變數（設在 Windows User 層級） |\n"
        "| mock-srv | Node.js | MOCK_LEGACY_NAME |\n"
    )
    skill_file.write_text(content, encoding="utf-8")
    git_add_all(tmp_repo)

    fails, infos = check_27_secret_guidance_guard(str(tmp_repo))
    assert len(fails) > 0
    assert any("未列管" in f for f in fails)


# T4 .env.local 單一真實來源：同一區塊內一段表格列出 .env.local 與憑證名稱、另一段寫「使 .env.local 成為單一真實來源」→ 命中
def test_t4_dotenv_local_single_source_of_truth(tmp_repo):
    guide_file = tmp_repo / "docs" / "mcp-environment-guide.md"
    content = (
        "### 憑證管理\n\n"
        "| File | Key |\n"
        "| .env.local | OLD_ENV_TOKEN |\n\n"
        "建議使 .env.local 成為單一真實來源。\n"
    )
    guide_file.write_text(content, encoding="utf-8")
    git_add_all(tmp_repo)

    fails, infos = check_27_secret_guidance_guard(str(tmp_repo))
    assert len(fails) > 0
    assert any("未列管" in f for f in fails)


# T5 已列管：例外之 unit_sha256 以 c27_split_units 取得之區塊全文計算 → 無失敗；隨後改動該區塊一字 → 失敗
def test_t5_exception_listed_and_unit_hash_tamper(tmp_repo):
    skill_file = tmp_repo / "skills" / "sample-skill" / "SKILL.md"
    block_text = "# Sample Skill\n請將金鑰存於 User 層級環境變數中。"
    skill_file.write_text(block_text + "\n", encoding="utf-8")
    git_add_all(tmp_repo)

    units = c27_split_units(skill_file.read_text(encoding="utf-8"))
    assert len(units) == 1
    start_line, heading, unit_text = units[0]
    unit_digest = hashlib.sha256(unit_text.encode("utf-8")).hexdigest()

    exc_file = tmp_repo / "docs" / "governance" / "secret-guidance-exceptions.json"
    exc_data = {
        "schema_version": 1,
        "exceptions": [
            {
                "path": "skills/sample-skill/SKILL.md",
                "heading": heading,
                "unit_sha256": unit_digest,
                "kind": "TRANSITIONAL_GUIDANCE",
                "owner": "SEC-04",
                "reason": "Test exception",
                "removal_condition": "Removed in next slice"
            }
        ]
    }
    with open(exc_file, "w", encoding="utf-8") as f:
        json.dump(exc_data, f, indent=2)

    fails, infos = check_27_secret_guidance_guard(str(tmp_repo))
    assert len(fails) == 0

    # Tamper with one character
    skill_file.write_text("# Sample Skill\n請將金鑰存於 User 層級環境變數中！\n", encoding="utf-8")
    git_add_all(tmp_repo)

    fails2, _ = check_27_secret_guidance_guard(str(tmp_repo))
    assert len(fails2) > 0


# T6 同檔複製：把已列管區塊在同檔複製一份 → 失敗訊息含「一對一」
def test_t6_duplicate_unit_in_same_file(tmp_repo):
    skill_file = tmp_repo / "skills" / "sample-skill" / "SKILL.md"
    unit = "# Sample Skill\n請將金鑰存於 User 層級環境變數中。"
    skill_file.write_text(f"{unit}\n\n{unit}\n", encoding="utf-8")
    git_add_all(tmp_repo)

    units = c27_split_units(unit)
    unit_digest = hashlib.sha256(units[0][2].encode("utf-8")).hexdigest()

    exc_file = tmp_repo / "docs" / "governance" / "secret-guidance-exceptions.json"
    exc_data = {
        "schema_version": 1,
        "exceptions": [
            {
                "path": "skills/sample-skill/SKILL.md",
                "heading": "# Sample Skill",
                "unit_sha256": unit_digest,
                "kind": "TRANSITIONAL_GUIDANCE",
                "owner": "SEC-04",
                "reason": "Test exception",
                "removal_condition": "Test condition"
            }
        ]
    }
    with open(exc_file, "w", encoding="utf-8") as f:
        json.dump(exc_data, f, indent=2)

    fails, _ = check_27_secret_guidance_guard(str(tmp_repo))
    assert any("一對一" in f for f in fails)


# T7 重複例外條目 → 失敗訊息含「重複」；T8 heading 不符 → 失敗訊息含「heading」
def test_t7_duplicate_exception_entries(tmp_repo):
    skill_file = tmp_repo / "skills" / "sample-skill" / "SKILL.md"
    unit = "# Sample Skill\n請將金鑰存於 User 層級環境變數中。"
    skill_file.write_text(unit + "\n", encoding="utf-8")
    git_add_all(tmp_repo)

    units = c27_split_units(unit)
    unit_digest = hashlib.sha256(units[0][2].encode("utf-8")).hexdigest()

    exc_entry = {
        "path": "skills/sample-skill/SKILL.md",
        "heading": "# Sample Skill",
        "unit_sha256": unit_digest,
        "kind": "TRANSITIONAL_GUIDANCE",
        "owner": "SEC-04",
        "reason": "Test",
        "removal_condition": "Test"
    }

    exc_file = tmp_repo / "docs" / "governance" / "secret-guidance-exceptions.json"
    exc_data = {
        "schema_version": 1,
        "exceptions": [exc_entry, exc_entry]
    }
    with open(exc_file, "w", encoding="utf-8") as f:
        json.dump(exc_data, f, indent=2)

    fails, _ = check_27_secret_guidance_guard(str(tmp_repo))
    assert any("重複" in f for f in fails)


def test_t8_mismatched_heading(tmp_repo):
    skill_file = tmp_repo / "skills" / "sample-skill" / "SKILL.md"
    unit = "# Sample Skill\n請將金鑰存於 User 層級環境變數中。"
    skill_file.write_text(unit + "\n", encoding="utf-8")
    git_add_all(tmp_repo)

    units = c27_split_units(unit)
    unit_digest = hashlib.sha256(units[0][2].encode("utf-8")).hexdigest()

    exc_file = tmp_repo / "docs" / "governance" / "secret-guidance-exceptions.json"
    exc_data = {
        "schema_version": 1,
        "exceptions": [
            {
                "path": "skills/sample-skill/SKILL.md",
                "heading": "# Wrong Heading",
                "unit_sha256": unit_digest,
                "kind": "TRANSITIONAL_GUIDANCE",
                "owner": "SEC-04",
                "reason": "Test",
                "removal_condition": "Test"
            }
        ]
    }
    with open(exc_file, "w", encoding="utf-8") as f:
        json.dump(exc_data, f, indent=2)

    fails, _ = check_27_secret_guidance_guard(str(tmp_repo))
    assert any("heading" in f for f in fails)


# T9 owner 不存在於看板 → 失敗；owner 狀態為「已完成」→ 失敗訊息含「已完成」
def test_t9_owner_nonexistent_and_owner_completed(tmp_repo):
    skill_file = tmp_repo / "skills" / "sample-skill" / "SKILL.md"
    unit = "# Sample Skill\n請將金鑰存於 User 層級環境變數中。"
    skill_file.write_text(unit + "\n", encoding="utf-8")
    git_add_all(tmp_repo)

    units = c27_split_units(unit)
    unit_digest = hashlib.sha256(units[0][2].encode("utf-8")).hexdigest()

    exc_file = tmp_repo / "docs" / "governance" / "secret-guidance-exceptions.json"

    # Nonexistent owner
    exc_data = {
        "schema_version": 1,
        "exceptions": [
            {
                "path": "skills/sample-skill/SKILL.md",
                "heading": "# Sample Skill",
                "unit_sha256": unit_digest,
                "kind": "TRANSITIONAL_GUIDANCE",
                "owner": "SEC-NONEXISTENT",
                "reason": "Test",
                "removal_condition": "Test"
            }
        ]
    }
    with open(exc_file, "w", encoding="utf-8") as f:
        json.dump(exc_data, f, indent=2)

    fails_ne, _ = check_27_secret_guidance_guard(str(tmp_repo))
    assert any("不存在或不唯一" in f for f in fails_ne)

    # Completed owner
    exc_data["exceptions"][0]["owner"] = "SEC-DONE"
    with open(exc_file, "w", encoding="utf-8") as f:
        json.dump(exc_data, f, indent=2)

    fails_done, _ = check_27_secret_guidance_guard(str(tmp_repo))
    assert any("已完成" in f for f in fails_done)


# T10 例外缺欄位、kind 不合法、unit_sha256 非 64 位小寫 hex → 各自失敗
def test_t10_exception_schema_validation(tmp_repo):
    exc_file = tmp_repo / "docs" / "governance" / "secret-guidance-exceptions.json"

    # Missing field
    with open(exc_file, "w", encoding="utf-8") as f:
        json.dump({
            "schema_version": 1,
            "exceptions": [{"path": "skills/sample-skill/SKILL.md", "heading": "h"}]
        }, f)
    fails, _ = check_27_secret_guidance_guard(str(tmp_repo))
    assert any("缺少必要欄位" in f for f in fails)

    # Invalid kind
    with open(exc_file, "w", encoding="utf-8") as f:
        json.dump({
            "schema_version": 1,
            "exceptions": [{
                "path": "skills/sample-skill/SKILL.md",
                "heading": "h",
                "unit_sha256": "a" * 64,
                "kind": "INVALID_KIND",
                "owner": "SEC-04",
                "reason": "r",
                "removal_condition": "c"
            }]
        }, f)
    fails, _ = check_27_secret_guidance_guard(str(tmp_repo))
    assert any("kind 不合法" in f for f in fails)

    # Non 64-char lowercase hex unit_sha256
    with open(exc_file, "w", encoding="utf-8") as f:
        json.dump({
            "schema_version": 1,
            "exceptions": [{
                "path": "skills/sample-skill/SKILL.md",
                "heading": "h",
                "unit_sha256": "A" * 64,
                "kind": "TRANSITIONAL_GUIDANCE",
                "owner": "SEC-04",
                "reason": "r",
                "removal_condition": "c"
            }]
        }, f)
    fails, _ = check_27_secret_guidance_guard(str(tmp_repo))
    assert any("unit_sha256 格式錯誤" in f for f in fails)

    # Empty owner/reason/removal_condition
    with open(exc_file, "w", encoding="utf-8") as f:
        json.dump({
            "schema_version": 1,
            "exceptions": [{
                "path": "skills/sample-skill/SKILL.md",
                "heading": "h",
                "unit_sha256": "a" * 64,
                "kind": "TRANSITIONAL_GUIDANCE",
                "owner": "  ",
                "reason": "r",
                "removal_condition": "c"
            }]
        }, f)
    fails, _ = check_27_secret_guidance_guard(str(tmp_repo))
    assert any("為空" in f for f in fails)


# T11 fail-closed（每項各自失敗且不得無失敗）：inventory 缺失；inventory 畸形 JSON；例外檔缺失；例外檔畸形 JSON；TASKBOARD 缺失；目錄不是 Git repo（git ls-files 失敗）；範圍內 .md 為非 UTF-8 位元組
def test_t11_fail_closed_inputs(tmp_repo, tmp_path):
    inv_file = tmp_repo / "docs" / "governance" / "secret-inventory.json"
    exc_file = tmp_repo / "docs" / "governance" / "secret-guidance-exceptions.json"
    taskboard = tmp_repo / "docs" / "TASKBOARD.md"

    # 1. inventory missing
    inv_backup = inv_file.read_text(encoding="utf-8")
    inv_file.unlink()
    fails, _ = check_27_secret_guidance_guard(str(tmp_repo))
    assert len(fails) > 0
    inv_file.write_text(inv_backup, encoding="utf-8")

    # 2. inventory malformed
    inv_file.write_text("{malformed json", encoding="utf-8")
    fails, _ = check_27_secret_guidance_guard(str(tmp_repo))
    assert len(fails) > 0
    inv_file.write_text(inv_backup, encoding="utf-8")

    # 3. exceptions missing
    exc_backup = exc_file.read_text(encoding="utf-8")
    exc_file.unlink()
    fails, _ = check_27_secret_guidance_guard(str(tmp_repo))
    assert len(fails) > 0
    exc_file.write_text(exc_backup, encoding="utf-8")

    # 4. exceptions malformed
    exc_file.write_text("{malformed", encoding="utf-8")
    fails, _ = check_27_secret_guidance_guard(str(tmp_repo))
    assert len(fails) > 0
    exc_file.write_text(exc_backup, encoding="utf-8")

    # 5. taskboard missing
    board_backup = taskboard.read_text(encoding="utf-8")
    taskboard.unlink()
    fails, _ = check_27_secret_guidance_guard(str(tmp_repo))
    assert len(fails) > 0
    taskboard.write_text(board_backup, encoding="utf-8")

    # 6. not a git repo (create outside tmp_repo)
    not_git = tmp_path / "not_git"
    not_git.mkdir()
    (not_git / "docs" / "governance").mkdir(parents=True)
    (not_git / "docs" / "governance" / "secret-inventory.json").write_text(inv_backup, encoding="utf-8")
    (not_git / "docs" / "governance" / "secret-guidance-exceptions.json").write_text(exc_backup, encoding="utf-8")
    (not_git / "docs" / "TASKBOARD.md").write_text(board_backup, encoding="utf-8")
    fails, _ = check_27_secret_guidance_guard(str(not_git))
    assert len(fails) > 0
    assert any("git ls-files" in f for f in fails)

    # 7. non-UTF-8 bytes in markdown
    bad_md = tmp_repo / "skills" / "sample-skill" / "bad.md"
    bad_md.write_bytes(b"\xff\xfe\x00\x00invalid")
    git_add_all(tmp_repo)
    fails, _ = check_27_secret_guidance_guard(str(tmp_repo))
    assert any("無法讀取或解碼" in f for f in fails)
    bad_md.unlink()
    git_add_all(tmp_repo)


# T12 不命中：只寫執行期需含舊名稱之環境變數（無持久存放指示）；skills/deprecated/ 下之違規文字；描述存入 Windows Credential Manager → 皆無失敗
def test_t12_unflagged_cases(tmp_repo):
    # 1. runtime only
    skill_file = tmp_repo / "skills" / "sample-skill" / "SKILL.md"
    skill_file.write_text("# Runtime Use\n執行期須傳入包含 MOCK_LEGACY_NAME 之環境變數以供認證。\n", encoding="utf-8")

    # 2. deprecated directory
    dep_dir = tmp_repo / "skills" / "deprecated" / "legacy-skill"
    dep_dir.mkdir(parents=True)
    (dep_dir / "SKILL.md").write_text("# Deprecated\n請在環境變數或 .env 中設定金鑰。\n", encoding="utf-8")

    # 3. Windows Credential Manager guidance
    guide_file = tmp_repo / "docs" / "mcp-environment-guide.md"
    guide_file.write_text("# Guide\n受管金鑰依 ADR-0027 存入 Windows Credential Manager Generic Credential。\n", encoding="utf-8")

    git_add_all(tmp_repo)
    fails, infos = check_27_secret_guidance_guard(str(tmp_repo))
    assert len(fails) == 0


# T13 接線：以 monkeypatch 使 check_27_secret_guidance_guard 回傳一筆失敗時，run_checks([]) 以 SystemExit 結束且 code == 1，輸出含「CHECK 27」；對真實 repo 呼叫 check_27_secret_guidance_guard() 回傳零失敗
def test_t13_run_checks_wiring_and_real_repo_pass(monkeypatch, capsys):
    def mock_guard_fail(root=None):
        return ["mock check 27 failure"], []

    monkeypatch.setattr("check_consistency.check_27_secret_guidance_guard", mock_guard_fail)

    with pytest.raises(SystemExit) as exc_info:
        run_checks([])

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "CHECK 27: 受管金鑰持久存放指引守衛" in captured.out
    assert "mock check 27 failure" in captured.out

    # Real repo returns zero failures
    real_fails, real_infos = check_27_secret_guidance_guard()
    assert len(real_fails) == 0
    assert any("列管例外 6 筆" in info for info in real_infos)
