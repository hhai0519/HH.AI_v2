import os
import sys
import subprocess
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from anchor import extract_anchor

ANCHOR_PY = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "anchor.py"))


def test_anchor_unique_positive(tmp_path):
    """1. 正例：唯一錨點回傳 count == 1、exit code 0、原文逐字相符。"""
    f = tmp_path / "test.txt"
    f.write_text("line one\nunique anchor line\nline three\n", encoding="utf-8")

    # 測試內部函式
    data = extract_anchor(str(f), 2, 2)
    assert data["count"] == 1
    assert data["text"] == "unique anchor line"

    # 測試 CLI
    res = subprocess.run([sys.executable, ANCHOR_PY, str(f), "2", "2"], capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0
    assert "count: 1" in res.stdout
    assert "unique anchor line" in res.stdout


def test_anchor_duplicate_negative(tmp_path):
    """2. 反例：在檔案中重複兩次的字串，count == 2 且 exit code 1。"""
    f = tmp_path / "test.txt"
    f.write_text("duplicate line\nother\nduplicate line\n", encoding="utf-8")

    data = extract_anchor(str(f), 1, 1)
    assert data["count"] == 2

    res = subprocess.run([sys.executable, ANCHOR_PY, str(f), "1", "1"], capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 1
    assert "錨點不唯一（count=2）" in res.stderr


def test_anchor_out_of_bounds_negative(tmp_path):
    """3. 反例：行號越界時 exit code 2。"""
    f = tmp_path / "test.txt"
    f.write_text("line one\nline two\n", encoding="utf-8")

    res = subprocess.run([sys.executable, ANCHOR_PY, str(f), "1", "10"], capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 2
    assert "越界" in res.stderr

    res_zero = subprocess.run([sys.executable, ANCHOR_PY, str(f), "0", "1"], capture_output=True, text=True, encoding="utf-8")
    assert res_zero.returncode == 2

    res_reverse = subprocess.run([sys.executable, ANCHOR_PY, str(f), "2", "1"], capture_output=True, text=True, encoding="utf-8")
    assert res_reverse.returncode == 2


def test_anchor_no_trailing_newline(tmp_path):
    """4. 原文不得被補上尾端換行（切片後接回的字串，末尾不應多出 \\n）。"""
    f = tmp_path / "test.txt"
    f.write_text("line one\nline two\nline three\n", encoding="utf-8")

    data = extract_anchor(str(f), 1, 2)
    assert data["text"] == "line one\nline two"
    assert not data["text"].endswith("\n")
