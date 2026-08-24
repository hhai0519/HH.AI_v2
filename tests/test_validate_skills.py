import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.validate_skills import validate_description, DESCRIPTION_MAX_LEN


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
