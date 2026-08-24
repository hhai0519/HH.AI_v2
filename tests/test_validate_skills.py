import sys
from pathlib import Path

# Add project root directory to sys.path so scripts can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from scripts.validate_skills import validate_name, NAME_MAX_LEN


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
