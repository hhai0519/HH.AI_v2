import os
import sys
import copy
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from fingerprint import (
    generate_fingerprint,
    compute_file_fingerprint,
    compare_fingerprints,
    verify_fingerprint,
)


def test_fingerprint_mock_repo(tmp_path):
    """1. 正例：對一個 tmp_path 假 repo 產生指紋，files 內容與手算相符。"""
    mission = tmp_path / "MISSION.md"
    mission.write_text("# Mission Title\nLine 2\nLine 3\n", encoding="utf-8")

    sop_dir = tmp_path / "SOP"
    sop_dir.mkdir()
    sop_file = sop_dir / "SOP_01.md"
    sop_file.write_text("# SOP 01\n```python\ncode\n```\n", encoding="utf-8")

    fp = generate_fingerprint(str(tmp_path))
    files = fp["files"]

    assert "MISSION.md" in files
    assert files["MISSION.md"]["lines"] == 3
    assert files["MISSION.md"]["fences"] == 0
    assert files["MISSION.md"]["headings"] == ["# Mission Title"]

    assert "SOP/SOP_01.md" in files
    assert files["SOP/SOP_01.md"]["lines"] == 4
    assert files["SOP/SOP_01.md"]["fences"] == 2
    assert files["SOP/SOP_01.md"]["headings"] == ["# SOP 01"]


def test_fingerprint_deterministic(tmp_path):
    """2. 正例：同一棵樹跑兩次，files 與 skills 完全相同。"""
    f = tmp_path / "PRINCIPLES.md"
    f.write_text("# Principles\nSome content\n", encoding="utf-8")

    fp1 = generate_fingerprint(str(tmp_path))
    fp2 = generate_fingerprint(str(tmp_path))

    assert fp1["files"] == fp2["files"]
    assert fp1["skills"] == fp2["skills"]


def test_fingerprint_detect_char_change(tmp_path):
    """3. 反例：改動任一檔案一個字元後，比對必須偵測到 sha256 不符。"""
    f = tmp_path / "PRINCIPLES.md"
    f.write_text("Hello World\n", encoding="utf-8")
    fp1 = generate_fingerprint(str(tmp_path))

    f.write_text("Hello World!\n", encoding="utf-8")
    fp2 = generate_fingerprint(str(tmp_path))

    diffs = compare_fingerprints(fp2, fp1)
    assert any("[欄位不符] PRINCIPLES.md.sha256" in d for d in diffs)


def test_fingerprint_detect_line_change(tmp_path):
    """4. 反例：把某檔案多加一行後，必須偵測到 lines 不符。"""
    f = tmp_path / "AGENTS.md"
    f.write_text("Line 1\nLine 2\n", encoding="utf-8")
    fp1 = generate_fingerprint(str(tmp_path))

    f.write_text("Line 1\nLine 2\nLine 3\n", encoding="utf-8")
    fp2 = generate_fingerprint(str(tmp_path))

    diffs = compare_fingerprints(fp2, fp1)
    assert any("[欄位不符] AGENTS.md.lines" in d for d in diffs)


def test_fingerprint_ignore_metadata_diff(tmp_path):
    """5. 反例：base_head 與 generated_at 不同但 files／skills 相同時，比對必須通過。"""
    f = tmp_path / "AGENTS.md"
    f.write_text("Line 1\n", encoding="utf-8")
    fp1 = generate_fingerprint(str(tmp_path))

    fp2 = copy.deepcopy(fp1)
    fp2["base_head"] = "different_hash"
    fp2["generated_at"] = "2099-01-01T00:00:00Z"
    fp2["schema_version"] = 99

    diffs = compare_fingerprints(fp2, fp1)
    assert len(diffs) == 0


def test_fingerprint_fences_not_at_start(tmp_path):
    """6. fences 的計算：對一份內文含有 ``` 字樣但行首不是 ``` 的檔案，fences 必須為 0。"""
    f = tmp_path / "MISSION.md"
    f.write_text("Here is an inline ``` code sample in text.\nAnother line with ``` inside.\n", encoding="utf-8")

    fp = compute_file_fingerprint(str(f))
    assert fp["fences"] == 0
