from pathlib import Path
import pytest

MAX_RULE_CHARS = 12000
SAFETY_TARGET_CHARS = 9500

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RULES_DIR = REPO_ROOT / ".agents" / "rules"


def test_rule_files_within_loadability_limit():
    """All rules in .agents/rules/*.md must not exceed Antigravity IDE UI limit of 12,000 Unicode characters."""
    rule_files = sorted(RULES_DIR.glob("*.md"))
    assert len(rule_files) > 0, f"No rule files found in {RULES_DIR}"

    violations = []
    for rule_path in rule_files:
        text = rule_path.read_text(encoding="utf-8")
        char_count = len(text)
        if char_count > MAX_RULE_CHARS:
            violations.append(
                f"Rule file {rule_path.relative_to(REPO_ROOT)} exceeded loadability limit: "
                f"actual chars={char_count}, limit={MAX_RULE_CHARS}"
            )

    assert not violations, "\n".join(violations)


def test_prompt_preflight_within_safety_target():
    """prompt-preflight.md must satisfy the batch design safety target of <= 9,500 characters."""
    target_file = RULES_DIR / "prompt-preflight.md"
    assert target_file.exists(), f"Target rule file {target_file} does not exist"
    text = target_file.read_text(encoding="utf-8")
    char_count = len(text)
    assert char_count <= SAFETY_TARGET_CHARS, (
        f"Rule file {target_file.relative_to(REPO_ROOT)} exceeded safety target: "
        f"actual chars={char_count}, limit={SAFETY_TARGET_CHARS}"
    )
