import os, sys
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from build_prompt_evidence import parse_spec, apply_mod_to_text, SpecParseError

END_MOD = "--- END " + "MOD ---"

def test_create_file_parse_pass():
    """A. create_file spec parse = PASS"""
    spec_text = f"""HEAD: 1234567

=== MOD 1 ===
file: docs/new_feature.txt
mode: create_file
--- PAYLOAD ---
This is a new file.
Line 2.
{END_MOD}
"""
    head, mods, expects = parse_spec(spec_text)
    assert head == "1234567"
    assert len(mods) == 1
    assert mods[0]["file"] == "docs/new_feature.txt"
    assert mods[0]["mode"] == "create_file"
    assert mods[0]["anchor"] == ""
    assert mods[0]["payload"] == "This is a new file.\nLine 2."


def test_create_file_with_empty_anchor_parse_pass():
    spec_text = f"""HEAD: 1234567

=== MOD 1 ===
file: docs/new_feature.txt
mode: create_file
--- ANCHOR ---
--- PAYLOAD ---
Content
{END_MOD}
"""
    head, mods, expects = parse_spec(spec_text)
    assert mods[0]["anchor"] == ""
    assert mods[0]["payload"] == "Content"


def test_create_file_non_empty_anchor_fails():
    """D. create_file 非空 illegal anchor = FAIL"""
    spec_text = f"""HEAD: 1234567

=== MOD 1 ===
file: docs/new_feature.txt
mode: create_file
--- ANCHOR ---
illegal anchor
--- PAYLOAD ---
Content
{END_MOD}
"""
    with pytest.raises(SpecParseError, match="create_file 的 ANCHOR 必須為空"):
        parse_spec(spec_text)


def test_duplicate_create_file_same_path_fails():
    """F. duplicate create_file same path = FAIL"""
    spec_text = f"""HEAD: 1234567

=== MOD 1 ===
file: docs/dup.txt
mode: create_file
--- PAYLOAD ---
File 1
{END_MOD}

=== MOD 2 ===
file: docs/dup.txt
mode: create_file
--- PAYLOAD ---
File 2
{END_MOD}
"""
    with pytest.raises(SpecParseError, match="不得重複 create_file 或混用不同模式"):
        parse_spec(spec_text)


def test_create_file_mixed_mode_same_path_fails():
    spec_text = f"""HEAD: 1234567

=== MOD 1 ===
file: docs/mixed.txt
mode: create_file
--- PAYLOAD ---
File 1
{END_MOD}

=== MOD 2 ===
file: docs/mixed.txt
mode: replace
--- ANCHOR ---
File 1
--- PAYLOAD ---
File 2
{END_MOD}
"""
    with pytest.raises(SpecParseError, match="不得重複 create_file 或混用不同模式"):
        parse_spec(spec_text)


def test_apply_create_file_parent_absent_pass():
    """B. create_file target parent 不存在 = PASS & E. 完整 payload bytes 正確"""
    mod = {
        "id": "1",
        "file": "docs/new.txt",
        "mode": "create_file",
        "anchor": "",
        "payload": "hello\nworld\n"
    }
    result = apply_mod_to_text(None, mod)
    assert result == "hello\nworld\n"
    assert result.encode("utf-8") == b"hello\nworld\n"


def test_apply_create_file_parent_exists_fails():
    """C. create_file target parent 已存在 = FAIL"""
    mod = {
        "id": "1",
        "file": "docs/existing.txt",
        "mode": "create_file",
        "anchor": "",
        "payload": "hello\nworld\n"
    }
    with pytest.raises(ValueError, match="create_file 目標檔案在 base 已存在"):
        apply_mod_to_text("existing content", mod)


def test_existing_modes_regression_pass():
    """G. existing modes regression：insert_after / insert_before / replace 全部仍 PASS"""
    rep_mod = {"id": "1", "file": "f", "mode": "replace", "anchor": "B", "payload": "Z"}
    assert apply_mod_to_text("A\nB\nC", rep_mod) == "A\nZ\nC"

    after_mod = {"id": "2", "file": "f", "mode": "insert_after", "anchor": "B", "payload": "X"}
    assert apply_mod_to_text("A\nB\nC", after_mod) == "A\nB\nX\nC"

    before_mod = {"id": "3", "file": "f", "mode": "insert_before", "anchor": "B", "payload": "Y"}
    assert apply_mod_to_text("A\nB\nC", before_mod) == "A\nY\nB\nC"
