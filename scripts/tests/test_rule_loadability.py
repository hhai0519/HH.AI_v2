import json
from pathlib import Path
import re
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY_PATH = REPO_ROOT / "docs" / "governance" / "rule-registry.json"


def load_runtime_surface_policy(registry_file: Path = REGISTRY_PATH) -> dict:
    with open(registry_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    policy = data.get("runtime_surface_policy")
    assert policy is not None, "Missing 'runtime_surface_policy' in rule-registry.json"
    return policy


def validate_runtime_surface(target_repo_root: Path, policy: dict) -> list[str]:
    violations = []
    kernel_file = target_repo_root / policy["kernel_path"]
    if not kernel_file.exists():
        violations.append(f"Kernel file does not exist: {kernel_file}")
        return violations

    kernel_text = kernel_file.read_text(encoding="utf-8")
    kernel_len = len(kernel_text)

    # A. root AGENTS.md chars <= kernel_max_chars
    if kernel_len > policy["kernel_max_chars"]:
        violations.append(
            f"Kernel chars exceed limit: actual={kernel_len}, limit={policy['kernel_max_chars']}"
        )

    # D. AGENTS.md contains exactly required kernel anchors
    for anchor in policy["kernel_required_anchors"]:
        if anchor not in kernel_text:
            violations.append(f"Kernel missing required anchor: {anchor}")

    # E. AGENTS.md contains exactly one canary
    canary = policy["kernel_canary"]
    canary_count = kernel_text.count(canary)
    if canary_count != 1:
        violations.append(
            f"Kernel canary count must be exactly 1, found {canary_count} for '{canary}'"
        )

    # B. each .agents/rules/*.md <= single_rule_max_chars
    rules_dir = target_repo_root / ".agents" / "rules"
    rule_files = sorted(rules_dir.glob("*.md")) if rules_dir.exists() else []

    always_on_files = []
    trigger_always_on_pattern = re.compile(r"trigger:\s*always_on", re.IGNORECASE)

    for rule_file in rule_files:
        rule_text = rule_file.read_text(encoding="utf-8")
        rule_len = len(rule_text)
        if rule_len > policy["single_rule_max_chars"]:
            violations.append(
                f"Rule {rule_file.name} chars exceed limit: actual={rule_len}, limit={policy['single_rule_max_chars']}"
            )

        # C. prompt-preflight <= prompt_preflight_safety_target_chars
        if rule_file.name == "prompt-preflight.md":
            if rule_len > policy["prompt_preflight_safety_target_chars"]:
                violations.append(
                    f"prompt-preflight.md chars exceed safety target: actual={rule_len}, limit={policy['prompt_preflight_safety_target_chars']}"
                )

        # Check for trigger: always_on
        if trigger_always_on_pattern.search(rule_text):
            always_on_files.append((rule_file, rule_len))
            # F. all explicit trigger: always_on rules must be in allowlist
            if rule_file.name not in policy["always_on_rule_allowlist"]:
                violations.append(
                    f"Rule {rule_file.name} declares 'trigger: always_on' but is not in always_on_rule_allowlist"
                )

    # G. root AGENTS + allowlisted always-on rule char total <= always_on_total_max_chars
    aggregate_chars = kernel_len + sum(length for _, length in always_on_files)
    if aggregate_chars > policy["always_on_total_max_chars"]:
        violations.append(
            f"Always-on aggregate chars exceed limit: actual={aggregate_chars}, limit={policy['always_on_total_max_chars']}"
        )

    return violations


# ----------------------------------------------------------------------
# Compliant Repo Invariant Tests
# ----------------------------------------------------------------------

def test_runtime_surface_policy_loadability():
    """Verify runtime surface of the current repository against rule-registry.json policy."""
    policy = load_runtime_surface_policy()
    violations = validate_runtime_surface(REPO_ROOT, policy)
    assert not violations, "\n".join(violations)


def test_root_kernel_char_cap():
    policy = load_runtime_surface_policy()
    kernel_file = REPO_ROOT / policy["kernel_path"]
    text = kernel_file.read_text(encoding="utf-8")
    assert len(text) <= policy["kernel_max_chars"], f"actual={len(text)}, max={policy['kernel_max_chars']}"


def test_single_rules_within_char_cap():
    policy = load_runtime_surface_policy()
    rules_dir = REPO_ROOT / ".agents" / "rules"
    for rule_file in rules_dir.glob("*.md"):
        text = rule_file.read_text(encoding="utf-8")
        assert len(text) <= policy["single_rule_max_chars"], f"{rule_file.name} actual={len(text)}, max={policy['single_rule_max_chars']}"


def test_prompt_preflight_within_safety_target():
    policy = load_runtime_surface_policy()
    preflight_file = REPO_ROOT / ".agents" / "rules" / "prompt-preflight.md"
    text = preflight_file.read_text(encoding="utf-8")
    assert len(text) <= policy["prompt_preflight_safety_target_chars"], f"actual={len(text)}, max={policy['prompt_preflight_safety_target_chars']}"


def test_root_kernel_required_anchors():
    policy = load_runtime_surface_policy()
    kernel_file = REPO_ROOT / policy["kernel_path"]
    text = kernel_file.read_text(encoding="utf-8")
    for anchor in policy["kernel_required_anchors"]:
        assert anchor in text, f"Missing required kernel anchor: {anchor}"


def test_root_kernel_canary_exactly_once():
    policy = load_runtime_surface_policy()
    kernel_file = REPO_ROOT / policy["kernel_path"]
    text = kernel_file.read_text(encoding="utf-8")
    canary = policy["kernel_canary"]
    assert text.count(canary) == 1, f"Canary count must be 1, found {text.count(canary)}"


def test_always_on_rule_allowlist_and_aggregate_cap():
    policy = load_runtime_surface_policy()
    rules_dir = REPO_ROOT / ".agents" / "rules"
    trigger_pat = re.compile(r"trigger:\s*always_on", re.IGNORECASE)
    always_on_files = []
    for rule_file in rules_dir.glob("*.md"):
        text = rule_file.read_text(encoding="utf-8")
        if trigger_pat.search(text):
            assert rule_file.name in policy["always_on_rule_allowlist"], f"Unauthorized always-on rule: {rule_file.name}"
            always_on_files.append(len(text))

    kernel_file = REPO_ROOT / policy["kernel_path"]
    kernel_len = len(kernel_file.read_text(encoding="utf-8"))
    aggregate_chars = kernel_len + sum(always_on_files)
    assert aggregate_chars <= policy["always_on_total_max_chars"], f"aggregate actual={aggregate_chars}, limit={policy['always_on_total_max_chars']}"


# ----------------------------------------------------------------------
# Deterministic Negative Controls (Section 24 / F3)
# ----------------------------------------------------------------------

@pytest.fixture
def isolated_fixture(tmp_path):
    """Create an isolated compliant minimal fixture."""
    policy = load_runtime_surface_policy()

    # Setup directories
    repo_dir = tmp_path / "repo"
    rules_dir = repo_dir / ".agents" / "rules"
    rules_dir.mkdir(parents=True)

    # Create compliant kernel
    kernel_content = (
        "# Kernel Fixture\n"
        f"Canary: {policy['kernel_canary']}\n\n"
        + "\n".join(f"Anchor: {a}" for a in policy["kernel_required_anchors"])
        + "\n"
    )
    (repo_dir / policy["kernel_path"]).write_text(kernel_content, encoding="utf-8")

    # Create compliant rules
    (rules_dir / "prompt-preflight.md").write_text("# prompt preflight\n", encoding="utf-8")
    (rules_dir / "sample-rule.md").write_text("# sample rule\n", encoding="utf-8")

    return repo_dir, policy


def test_negative_control_compliant_fixture(isolated_fixture):
    """F. Compliant fixture must PASS."""
    repo_dir, policy = isolated_fixture
    violations = validate_runtime_surface(repo_dir, policy)
    assert violations == []


def test_negative_control_missing_canary(isolated_fixture):
    """A. Deleting canary -> FAIL."""
    repo_dir, policy = isolated_fixture
    kernel_file = repo_dir / policy["kernel_path"]
    content = kernel_file.read_text(encoding="utf-8").replace(policy["kernel_canary"], "NO_CANARY")
    kernel_file.write_text(content, encoding="utf-8")

    violations = validate_runtime_surface(repo_dir, policy)
    assert any("canary count must be exactly 1" in v.lower() for v in violations)


def test_negative_control_kernel_exceeds_cap(isolated_fixture):
    """B. Root kernel exceeds cap -> FAIL."""
    repo_dir, policy = isolated_fixture
    kernel_file = repo_dir / policy["kernel_path"]
    pad_len = policy["kernel_max_chars"] + 100
    content = kernel_file.read_text(encoding="utf-8") + ("X" * pad_len)
    kernel_file.write_text(content, encoding="utf-8")

    violations = validate_runtime_surface(repo_dir, policy)
    assert any("kernel chars exceed limit" in v.lower() for v in violations)


def test_negative_control_unauthorized_always_on(isolated_fixture):
    """C. Adding unauthorized trigger: always_on -> FAIL."""
    repo_dir, policy = isolated_fixture
    rule_file = repo_dir / ".agents" / "rules" / "unauthorized.md"
    rule_file.write_text("# Unauthorized\ntrigger: always_on\n", encoding="utf-8")

    violations = validate_runtime_surface(repo_dir, policy)
    assert any("not in always_on_rule_allowlist" in v for v in violations)


def test_negative_control_always_on_aggregate_exceeds_cap(isolated_fixture):
    """D. Always-on aggregate exceeds cap -> FAIL."""
    repo_dir, policy = isolated_fixture
    # Temporarily allow a rule in policy
    custom_policy = dict(policy)
    custom_policy["always_on_rule_allowlist"] = ["heavy.md"]
    rule_file = repo_dir / ".agents" / "rules" / "heavy.md"
    rule_file.write_text(f"# Heavy\ntrigger: always_on\n{'Y' * custom_policy['always_on_total_max_chars']}", encoding="utf-8")

    violations = validate_runtime_surface(repo_dir, custom_policy)
    assert any("always-on aggregate chars exceed limit" in v.lower() for v in violations)


def test_negative_control_missing_required_anchor(isolated_fixture):
    """E. Deleting any kernel_required_anchor -> FAIL."""
    repo_dir, policy = isolated_fixture
    kernel_file = repo_dir / policy["kernel_path"]
    target_anchor = policy["kernel_required_anchors"][0]
    content = kernel_file.read_text(encoding="utf-8").replace(target_anchor, "REMOVED_ANCHOR")
    kernel_file.write_text(content, encoding="utf-8")

    violations = validate_runtime_surface(repo_dir, policy)
    assert any(f"Kernel missing required anchor: {target_anchor}" in v for v in violations)
