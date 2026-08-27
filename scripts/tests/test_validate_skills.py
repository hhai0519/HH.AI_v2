import pytest
from pathlib import Path
import sys

# Ensure scripts directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validate_skills import (
    parse_frontmatter,
    validate_name,
    validate_description,
    validate_bucket_structure,
    validate_skill,
    NAME_MAX_LEN,
    DESCRIPTION_MAX_LEN
)


# ==========================================
# parse_frontmatter tests
# ==========================================
def test_parse_frontmatter_valid():
    text = (
        "---\n"
        "name: test-skill\n"
        "description: A test skill description\n"
        "---\n"
        "Body content goes here.\n"
    )
    fm, body = parse_frontmatter(text)
    assert fm == {
        "name": "test-skill",
        "description": "A test skill description"
    }
    assert body == "Body content goes here.\n"

def test_parse_frontmatter_quoted_values_and_spaces():
    text = (
        "---\n"
        'name: "quoted-name"  \n'
        "description: 'quoted description'\n"
        "---\n"
        "Body\n"
    )
    fm, body = parse_frontmatter(text)
    assert fm == {
        "name": "quoted-name",
        "description": "quoted description"
    }
    assert body == "Body\n"

def test_parse_frontmatter_comments_and_blank_lines():
    text = (
        "---\n"
        "# This is a comment\n"
        "name: test-skill\n"
        "\n"
        "  # Indented comment\n"
        "description: Description\n"
        "---\n"
        "Body\n"
    )
    fm, body = parse_frontmatter(text)
    assert fm == {
        "name": "test-skill",
        "description": "Description"
    }

def test_parse_frontmatter_colon_in_value():
    text = (
        "---\n"
        "name: test-skill\n"
        "description: See https://example.com for details\n"
        "---\n"
        "Body\n"
    )
    fm, body = parse_frontmatter(text)
    assert fm == {
        "name": "test-skill",
        "description": "See https://example.com for details"
    }

def test_parse_frontmatter_no_frontmatter():
    text = "Just normal body text without frontmatter."
    fm, body = parse_frontmatter(text)
    assert fm is None
    assert body == text

def test_parse_frontmatter_unclosed_frontmatter():
    text = "---\nname: test-skill\ndescription: missing end delimiter"
    fm, body = parse_frontmatter(text)
    assert fm is None
    assert body == text

def test_parse_frontmatter_indented_lines_and_no_colon_lines():
    text = (
        "---\n"
        "name: test-skill\n"
        "  indented_key: value\n"
        "invalid_line_without_colon\n"
        "description: Description\n"
        "---\n"
        "Body\n"
    )
    fm, body = parse_frontmatter(text)
    assert fm == {
        "name": "test-skill",
        "description": "Description"
    }

def test_parse_frontmatter_body_containing_dashes():
    text = (
        "---\n"
        "name: test-skill\n"
        "description: Skill description\n"
        "---\n"
        "Line 1\n"
        "---\n"
        "Line 2\n"
    )
    fm, body = parse_frontmatter(text)
    assert fm == {
        "name": "test-skill",
        "description": "Skill description"
    }
    assert body == "Line 1\n---\nLine 2\n"


# ==========================================
# validate_name tests
# ==========================================
def test_validate_name_valid():
    """Test valid kebab-case names."""
    valid_names = [
        "my-skill",
        "skill123",
        "a",
        "a1-b2-c3",
        "a" * NAME_MAX_LEN,
    ]
    for name in valid_names:
        errors = []
        validate_name(name, errors, "test/location")
        assert errors == [], f"Expected no errors for valid name '{name}', but got: {errors}"

def test_validate_name_invalid_characters():
    """Test names with invalid characters (uppercase, underscores, spaces, symbols)."""
    invalid_cases = [
        ("My-Skill", "不符合 kebab-case"),
        ("my_skill", "不符合 kebab-case"),
        ("my skill", "不符合 kebab-case"),
        ("skill!", "不符合 kebab-case"),
        ("技能-skill", "不符合 kebab-case"),
    ]
    for name, expected_msg in invalid_cases:
        errors = []
        validate_name(name, errors, "test/location")
        assert len(errors) >= 1
        assert any(expected_msg in err for err in errors), f"Expected '{expected_msg}' in errors for '{name}', got {errors}"

def test_validate_name_hyphen_rules():
    """Test hyphen placement rules (leading, trailing, consecutive)."""
    hyphen_cases = [
        "-start-with-hyphen",
        "end-with-hyphen-",
        "consecutive--hyphens",
        "-both-",
        "--",
    ]
    for name in hyphen_cases:
        errors = []
        validate_name(name, errors, "test/location")
        assert len(errors) >= 1
        assert any("不能開頭/結尾是連字號，或包含連續連字號" in err for err in errors), f"Expected hyphen error for '{name}', got {errors}"

def test_validate_name_length_limit():
    """Test name length limit boundary cases."""
    exact_max = "a" * NAME_MAX_LEN
    errors = []
    validate_name(exact_max, errors, "test/location")
    assert errors == []

    over_max = "a" * (NAME_MAX_LEN + 1)
    errors = []
    validate_name(over_max, errors, "test/location")
    assert len(errors) == 1
    assert f"長度 {NAME_MAX_LEN + 1} 超過官方上限 {NAME_MAX_LEN} 字元" in errors[0]

def test_validate_name_multiple_errors_and_location():
    """Test location formatting in error messages and multiple triggered errors."""
    location = "orchestration/my-skill"
    # Starting with hyphen and exceeding length limit
    invalid_name = "-" + "a" * NAME_MAX_LEN
    errors = []
    validate_name(invalid_name, errors, location)
    assert len(errors) == 2
    assert f"[{location}]" in errors[0]
    assert f"[{location}]" in errors[1]
    assert "不能開頭/結尾是連字號" in errors[0]
    assert "超過官方上限" in errors[1]


# ==========================================
# validate_description tests
# ==========================================
def test_validate_description_valid():
    errors = []
    location = "test/skill"
    desc = "This is a valid description."
    validate_description(desc, errors, location)
    assert errors == []

def test_validate_description_contains_less_than():
    errors = []
    location = "test/skill"
    desc = "Description with < angle bracket"
    validate_description(desc, errors, location)
    assert len(errors) == 1
    assert f"[{location}] description 不能包含角括號 < 或 >" in errors[0]

def test_validate_description_contains_greater_than():
    errors = []
    location = "test/skill"
    desc = "Description with > angle bracket"
    validate_description(desc, errors, location)
    assert len(errors) == 1
    assert f"[{location}] description 不能包含角括號 < 或 >" in errors[0]

def test_validate_description_contains_both_brackets():
    errors = []
    location = "test/skill"
    desc = "Description with < and > angle brackets"
    validate_description(desc, errors, location)
    assert len(errors) == 1
    assert f"[{location}] description 不能包含角括號 < 或 >" in errors[0]

def test_validate_description_exact_max_length():
    errors = []
    location = "test/skill"
    desc = "a" * DESCRIPTION_MAX_LEN
    validate_description(desc, errors, location)
    assert errors == []

def test_validate_description_exceeds_max_length():
    errors = []
    location = "test/skill"
    over_len = DESCRIPTION_MAX_LEN + 1
    desc = "a" * over_len
    validate_description(desc, errors, location)
    assert len(errors) == 1
    assert f"[{location}] description 長度 {over_len} 超過官方上限 {DESCRIPTION_MAX_LEN} 字元" in errors[0]

def test_validate_description_multiple_errors():
    errors = []
    location = "test/skill"
    over_len = DESCRIPTION_MAX_LEN + 5
    desc = "<" + ("a" * (over_len - 1))
    validate_description(desc, errors, location)
    assert len(errors) == 2
    assert f"[{location}] description 不能包含角括號 < 或 >" in errors[0]
    assert f"[{location}] description 長度 {over_len} 超過官方上限 {DESCRIPTION_MAX_LEN} 字元" in errors[1]


# ==========================================
# validate_bucket_structure tests
# ==========================================
def test_validate_bucket_structure(tmp_path):
    errors = []
    warnings = []
    invalid_bucket = tmp_path / "invalid_bucket"
    invalid_bucket.mkdir()
    is_valid, _ = validate_bucket_structure(invalid_bucket, errors, warnings)
    assert not is_valid
    assert len(errors) == 1

    errors = []
    warnings = []
    valid_bucket = tmp_path / "orchestration"
    valid_bucket.mkdir()
    (valid_bucket / "README.md").write_text("README content", encoding="utf-8")
    (valid_bucket / "AGENTS.md").write_text("AGENTS content", encoding="utf-8")
    is_valid, readme_text = validate_bucket_structure(valid_bucket, errors, warnings)
    assert is_valid
    assert readme_text == "README content"
    assert errors == []
    assert warnings == []


# ==========================================
# validate_skill tests
# ==========================================
def test_validate_skill(tmp_path):
    bucket_dir = tmp_path / "orchestration"
    bucket_dir.mkdir()
    skill_dir = bucket_dir / "my-skill"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\nname: my-skill\ndescription: Test description\n---\nSkill content",
        encoding="utf-8",
    )

    seen_names = {}
    errors = []
    warnings = []

    validate_skill(
        "orchestration",
        skill_dir,
        "my-skill in README",
        seen_names,
        errors,
        warnings,
    )

    assert errors == []
    assert warnings == []
    assert seen_names["my-skill"] == "orchestration/my-skill"
