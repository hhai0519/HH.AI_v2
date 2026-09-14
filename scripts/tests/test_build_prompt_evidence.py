#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tests/test_build_prompt_evidence.py

針對 scripts/build_prompt_evidence.py 的十項規格測試（含五項反例）：
1. 正例：解析一份含兩個 MOD 的合法 spec，欄位與內容逐字相符。
2. 正例：ANCHOR 區塊內含 # 開頭的行時，該行被當成內容而非註解。
3. 正例：唯一錨點回傳 count=1，且起始行號正確。
4. 反例：錨點在檔案中出現兩次 → exit code 1，且錯誤訊息列出兩個位置。
5. 反例：錨點不存在（count=0）→ exit code 1。
6. 反例：spec 缺少 mode 欄位 → exit code 2，錯誤訊息含行號。
7. 反例（守護 A 類錯誤）：E11 的總數必須等於 MOD 數（5 個 MOD 斷言輸出 [E11] 錨點總數: 5 且逐條清單恰為 5 行）。
8. 反例：模擬時 check_consistency 失敗 → exit code 1 且印出失敗項。
9. 正例：EXPECT 的 id_sequence 與實測相符時通過。
10. 反例（守護 D 類錯誤）：PAYLOAD 插入 ID 為 1,2,3,5（刻意缺 4），EXPECT 宣告 1-5 → exit code 1 且輸出含缺號 4。
"""

import io
import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from build_prompt_evidence import (
    parse_spec,
    verify_anchors,
    format_e11,
    format_bcd,
    simulate_and_verify,
    scan_spec_dependencies,
    format_dependency_discovery,
    main,
    SpecParseError,
)


def test_parse_spec_valid(tmp_path):
    """1. 正例：解析一份含兩個 MOD 的合法 spec，欄位與內容逐字相符。"""
    spec_text = """# 範例批次規格
HEAD: a44cc6b

=== MOD 1 ===
file: docs/TASKBOARD.md
mode: replace
--- ANCHOR ---
**最後更新**：2026-09-06，HEAD `59cea4c` 之後
--- PAYLOAD ---
**最後更新**：2026-09-06，HEAD `a44cc6b` 之後
--- END MOD ---

=== MOD 2 ===
file: docs/AUDIT-LOG.md
mode: insert_after
--- ANCHOR ---
| 59cea4c | 2026-09-06 | §4.1-1 |
--- PAYLOAD ---
| a44cc6b | 2026-09-06 | §4.1-1 | 範例列，實際使用時替換 |
--- END MOD ---

=== EXPECT ===
type: id_sequence
file: docs/TASKBOARD.md
pattern: ^\\| B-(\\d+) \\|
range: 1-65
--- END EXPECT ---
"""
    head, mods, expects = parse_spec(spec_text)
    assert head == "a44cc6b"
    assert len(mods) == 2
    assert mods[0]["id"] == "1"
    assert mods[0]["file"] == "docs/TASKBOARD.md"
    assert mods[0]["mode"] == "replace"
    assert mods[0]["anchor"] == "**最後更新**：2026-09-06，HEAD `59cea4c` 之後"
    assert mods[0]["payload"] == "**最後更新**：2026-09-06，HEAD `a44cc6b` 之後"

    assert mods[1]["id"] == "2"
    assert mods[1]["file"] == "docs/AUDIT-LOG.md"
    assert mods[1]["mode"] == "insert_after"
    assert mods[1]["anchor"] == "| 59cea4c | 2026-09-06 | §4.1-1 |"
    assert mods[1]["payload"] == "| a44cc6b | 2026-09-06 | §4.1-1 | 範例列，實際使用時替換 |"

    assert len(expects) == 1
    assert expects[0]["type"] == "id_sequence"
    assert expects[0]["file"] == "docs/TASKBOARD.md"
    assert expects[0]["pattern"] == r"^\| B-(\d+) \|"
    assert expects[0]["range"] == "1-65"


def test_anchor_with_hash_is_content():
    """2. 正例：ANCHOR 區塊內含 # 開頭的行時，該行被當成內容而非註解。"""
    spec_text = """HEAD: test123

=== MOD 1 ===
file: test.md
mode: replace
--- ANCHOR ---
# 第一級標題
## 第二級標題
--- PAYLOAD ---
# 修改後標題
--- END MOD ---
"""
    head, mods, expects = parse_spec(spec_text)
    assert len(mods) == 1
    assert mods[0]["anchor"] == "# 第一級標題\n## 第二級標題"
    assert mods[0]["payload"] == "# 修改後標題"


def test_unique_anchor_returns_count_1(tmp_path):
    """3. 正例：唯一錨點回傳 count=1，且起始行號正確。"""
    target = tmp_path / "sample.txt"
    target.write_text("line 1\nline 2\nTARGET ANCHOR LINE\nline 4\n", encoding="utf-8")

    mod = {
        "id": "1",
        "file": "sample.txt",
        "mode": "replace",
        "anchor": "TARGET ANCHOR LINE",
        "payload": "REPLACED",
    }
    ok, results = verify_anchors([mod], str(tmp_path))
    assert ok is True
    assert len(results) == 1
    assert results[0][1] == 3  # 第 3 行


def test_duplicate_anchor_exit_1_lists_positions(tmp_path, capsys):
    """4. 反例：錨點在檔案中出現兩次 → exit code 1，且錯誤訊息列出兩個位置。"""
    target = tmp_path / "dup.txt"
    target.write_text("DUPLICATE\nline 2\nDUPLICATE\nline 4\n", encoding="utf-8")

    spec_file = tmp_path / "spec.txt"
    spec_file.write_text("""HEAD: a44cc6b
=== MOD 1 ===
file: dup.txt
mode: replace
--- ANCHOR ---
DUPLICATE
--- PAYLOAD ---
NEW
--- END MOD ---
""", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        main([str(spec_file), "--check-only", "--repo-root", str(tmp_path)])
    assert excinfo.value.code == 1

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "count=2" in out
    assert "1" in out and "3" in out


def test_missing_anchor_exit_1(tmp_path, capsys):
    """5. 反例：錨點不存在（count=0）→ exit code 1。"""
    target = tmp_path / "missing.txt"
    target.write_text("line 1\nline 2\n", encoding="utf-8")

    spec_file = tmp_path / "spec.txt"
    spec_file.write_text("""HEAD: a44cc6b
=== MOD 1 ===
file: missing.txt
mode: replace
--- ANCHOR ---
NON_EXISTENT_ANCHOR
--- PAYLOAD ---
NEW
--- END MOD ---
""", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        main([str(spec_file), "--check-only", "--repo-root", str(tmp_path)])
    assert excinfo.value.code == 1

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "count=0" in out
    assert "未命中" in out


def test_missing_mode_exit_2(tmp_path, capsys):
    """6. 反例：spec 缺少 mode 欄位 → exit code 2，錯誤訊息含行號。"""
    spec_file = tmp_path / "invalid_spec.txt"
    spec_file.write_text("""HEAD: a44cc6b
=== MOD 1 ===
file: docs/TASKBOARD.md
--- ANCHOR ---
anchor text
--- PAYLOAD ---
payload text
--- END MOD ---
""", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        main([str(spec_file), "--check-only", "--repo-root", str(tmp_path)])
    assert excinfo.value.code == 2

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "mode" in out
    assert "第" in out and "行" in out


def test_e11_total_equals_mod_count(tmp_path, capsys):
    """7. 反例（守護 A 類錯誤）：E11 的總數必須等於 MOD 數。
    建構一份含 5 個 MOD 的 spec，斷言輸出 [E11] 錨點總數: 5 且逐條清單恰為 5 行。
    """
    for i in range(1, 6):
        f = tmp_path / f"file{i}.txt"
        f.write_text(f"line A\nANCHOR_{i}\nline B\n", encoding="utf-8")

    spec_lines = ["HEAD: a44cc6b"]
    for i in range(1, 6):
        spec_lines.append(f"""=== MOD {i} ===
file: file{i}.txt
mode: replace
--- ANCHOR ---
ANCHOR_{i}
--- PAYLOAD ---
PAYLOAD_{i}
--- END MOD ---""")
    spec_file = tmp_path / "spec5.txt"
    spec_file.write_text("\n".join(spec_lines), encoding="utf-8")

    ret = main([str(spec_file), "--check-only", "--repo-root", str(tmp_path)])
    assert ret == 0

    captured = capsys.readouterr()
    out = captured.out
    assert "[E11] 錨點總數: 5" in out
    mod_lines = [l for l in out.splitlines() if l.startswith("[錨點] MOD ")]
    assert len(mod_lines) == 5


def test_simulation_check_consistency_failed(tmp_path, capsys):
    """8. 反例：模擬時 check_consistency 失敗 → exit code 1 且印出失敗項。"""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    chk_py = scripts_dir / "check_consistency.py"
    chk_py.write_text("""import sys
print("CHECK 10 - 章節引用語意檢查")
print("  [FAIL] 發現未帶檔名之跨檔引用")
print("========================================")
print("總結: 通過 15 項, 失敗 1 項")
print("========================================")
sys.exit(1)
""", encoding="utf-8")

    sample_md = tmp_path / "sample.md"
    sample_md.write_text("old text\n", encoding="utf-8")

    spec_file = tmp_path / "spec.txt"
    spec_file.write_text("""HEAD: a44cc6b
=== MOD 1 ===
file: sample.md
mode: replace
--- ANCHOR ---
old text
--- PAYLOAD ---
new text
--- END MOD ---
""", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        main([str(spec_file), "--repo-root", str(tmp_path)])
    assert excinfo.value.code == 1

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "通過 15 項, 失敗 1 項" in out
    assert "[FAIL]" in out


def test_expect_id_sequence_success(tmp_path, capsys):
    """9. 正例：EXPECT 的 id_sequence 與實測相符時通過。"""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    chk_py = scripts_dir / "check_consistency.py"
    chk_py.write_text("""import sys
print("========================================")
print("總結: 通過 16 項, 失敗 0 項")
print("========================================")
sys.exit(0)
""", encoding="utf-8")

    tb = tmp_path / "TASKBOARD.md"
    tb.write_text("""| B-01 | item 1 |
| B-02 | item 2 |
| B-03 | item 3 |
""", encoding="utf-8")

    spec_file = tmp_path / "spec.txt"
    spec_file.write_text("""HEAD: a44cc6b
=== MOD 1 ===
file: TASKBOARD.md
mode: insert_after
--- ANCHOR ---
| B-03 | item 3 |
--- PAYLOAD ---
| B-04 | item 4 |
| B-05 | item 5 |
--- END MOD ---

=== EXPECT ===
type: id_sequence
file: TASKBOARD.md
pattern: ^\\| B-(\\d+) \\|
range: 1-5
--- END EXPECT ---
""", encoding="utf-8")

    ret = main([str(spec_file), "--repo-root", str(tmp_path)])
    assert ret == 0

    captured = capsys.readouterr()
    out = captured.out
    assert "[EXPECT] TASKBOARD.md" in out
    assert "宣告 1-5" in out
    assert "實測 5 個" in out
    assert "相符" in out


def test_expect_id_sequence_missing_id_exit_1(tmp_path, capsys):
    """10. 反例（守護 D 類錯誤，對應首投缺號攔截）：
    PAYLOAD 插入 ID 為 1,2,3,5（刻意缺 4），而 EXPECT 宣告 1-5。
    斷言 exit code 1，且輸出含缺號 4。
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    chk_py = scripts_dir / "check_consistency.py"
    chk_py.write_text("""import sys
print("========================================")
print("總結: 通過 16 項, 失敗 0 項")
print("========================================")
sys.exit(0)
""", encoding="utf-8")

    tb = tmp_path / "TASKBOARD.md"
    tb.write_text("""| B-01 | item 1 |
| B-02 | item 2 |
| B-03 | item 3 |
""", encoding="utf-8")

    spec_file = tmp_path / "spec_missing.txt"
    spec_file.write_text("""HEAD: a44cc6b
=== MOD 1 ===
file: TASKBOARD.md
mode: insert_after
--- ANCHOR ---
| B-03 | item 3 |
--- PAYLOAD ---
| B-05 | item 5 |
--- END MOD ---

=== EXPECT ===
type: id_sequence
file: TASKBOARD.md
pattern: ^\\| B-(\\d+) \\|
range: 1-5
--- END EXPECT ---
""", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        main([str(spec_file), "--repo-root", str(tmp_path)])
    assert excinfo.value.code == 1

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "[EXPECT] TASKBOARD.md" in out
    assert "不符" in out
    assert "缺號: [4]" in out or "4" in out


def test_bpe_impact_scan_integration_replace_mod(tmp_path):
    """B-68: EXACT_SPEC replace anchor 能調用共同 impact primitive，且僅輸出 discovery evidence（無 semantic disposition）。"""
    import subprocess
    repo = str(tmp_path)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)

    src_file = os.path.join(repo, "src.py")
    with open(src_file, "w", encoding="utf-8") as f:
        f.write('MSG = "ORIGINAL_DISPLAY_LITERAL"\n')
    subprocess.run(["git", "add", "src.py"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    mod = {
        "id": "1",
        "file": "src.py",
        "mode": "replace",
        "anchor": 'MSG = "ORIGINAL_DISPLAY_LITERAL"',
        "payload": 'MSG = "NEW_DISPLAY_LITERAL"'
    }

    discovery = scan_spec_dependencies([mod], repo)
    assert discovery["mode"] == "REQUIRED"
    assert len(discovery["results"]) == 1
    res = discovery["results"][0]
    assert res["matched_paths"] == ["src.py"]
    # 絕不自動產生 semantic disposition (UPDATE / VERIFY_ONLY / HISTORICAL_NO_CHANGE)
    assert "disposition" not in res
    for m in res.get("matches", []):
        assert "disposition" not in m

    formatted = format_dependency_discovery(discovery)
    assert "[DEPENDENCY_DISCOVERY]" in formatted
    assert "src.py" in formatted
    assert "UPDATE" not in formatted
    assert "VERIFY_ONLY" not in formatted


def test_bpe_impact_scan_create_file_not_treated_as_replace_dependency(tmp_path):
    """B-68: create_file MOD 不得被錯誤當成 replace dependency，不假造 dependency。"""
    mod = {
        "id": "1",
        "file": "new_file.py",
        "mode": "create_file",
        "anchor": None,
        "payload": "print('hello')\n"
    }

    discovery = scan_spec_dependencies([mod], str(tmp_path))
    assert discovery["mode"] == "NONE"
    assert discovery["reason"] == "No replace MODs in spec"
    assert len(discovery["results"]) == 0
