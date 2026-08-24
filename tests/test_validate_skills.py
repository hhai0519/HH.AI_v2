import pytest
from pathlib import Path
import sys

# Ensure scripts directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from validate_skills import (
    parse_frontmatter,
    validate_name,
    validate_description,
    validate_bucket_structure,
    validate_skill,
)


def test_parse_frontmatter():
    text = "---\nname: my-skill\ndescription: A test skill\n---\nBody text"
    fm, body = parse_frontmatter(text)
    assert fm == {"name": "my-skill", "description": "A test skill"}
    assert body == "Body text"

    invalid_text = "No frontmatter here"
    fm, body = parse_frontmatter(invalid_text)
    assert fm is None
    assert body == invalid_text


def test_validate_name():
    errors = []
    validate_name("valid-name-123", errors, "test/loc")
    assert errors == []

    errors = []
    validate_name("Invalid_Name", errors, "test/loc")
    assert len(errors) == 1
    assert "kebab-case" in errors[0]

    errors = []
    validate_name("-invalid-start", errors, "test/loc")
    assert len(errors) == 1

    errors = []
    validate_name("a" * 65, errors, "test/loc")
    assert len(errors) == 1
    assert "超過官方上限" in errors[0]


def test_validate_description():
    errors = []
    validate_description("Valid description without brackets", errors, "test/loc")
    assert errors == []

    errors = []
    validate_description("Description with <angle> brackets", errors, "test/loc")
    assert len(errors) == 1
    assert "角括號" in errors[0]

    errors = []
    validate_description("a" * 1025, errors, "test/loc")
    assert len(errors) == 1
    assert "超過官方上限" in errors[0]


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
