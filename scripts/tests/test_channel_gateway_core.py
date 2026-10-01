#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tests/test_channel_gateway_core.py

Canonical CI unit test gate integration for Channel Gateway pure control core.
Validates:
A. runtime/channel-gateway/package.json exists with zero dependencies and zero devDependencies.
B. runtime/channel-gateway/package-lock.json exists with zero third-party packages.
C. test-policy.json schema and zero-unregistered-skips enforcement.
D. .nvmrc and package.json engines / test script consistency.
E. Dynamic discovery of runtime/channel-gateway/tests/*.test.js test suites.
F. Per-file and combined Node test runner execution via TAP reporter.
G. Node.js built-in SQLite smoke contract (DatabaseSync, in-memory, no ExperimentalWarning).
H. Negative policy canary tests ensuring TAP parser and skip registry fail closed.
"""

import json
import os
import re
import subprocess
import sys
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GATEWAY_DIR = os.path.join(REPO_ROOT, "runtime", "channel-gateway")
PACKAGE_JSON_PATH = os.path.join(GATEWAY_DIR, "package.json")
PACKAGE_LOCK_PATH = os.path.join(GATEWAY_DIR, "package-lock.json")
TEST_POLICY_PATH = os.path.join(GATEWAY_DIR, "test-policy.json")
NVMRC_PATH = os.path.join(REPO_ROOT, ".nvmrc")
TESTS_DIR = os.path.join(GATEWAY_DIR, "tests")


def discover_gateway_test_files() -> list[str]:
    """Dynamically discover all regular *.test.js files in TESTS_DIR in deterministic sorted order."""
    if not os.path.isdir(TESTS_DIR):
        raise AssertionError(f"Gateway tests directory missing: {TESTS_DIR}")

    files = []
    for entry in os.listdir(TESTS_DIR):
        full_path = os.path.join(TESTS_DIR, entry)
        if os.path.isfile(full_path) and entry.endswith(".test.js"):
            files.append(os.path.abspath(full_path))

    files.sort()
    if len(files) == 0:
        raise AssertionError(f"No .test.js files found in {TESTS_DIR}")
    return files


def load_gateway_test_policy() -> dict:
    """Strictly load and validate runtime/channel-gateway/test-policy.json."""
    if not os.path.isfile(TEST_POLICY_PATH):
        raise AssertionError(f"test-policy.json missing at {TEST_POLICY_PATH}")

    with open(TEST_POLICY_PATH, "r", encoding="utf-8") as f:
        policy = json.load(f)

    if not isinstance(policy, dict):
        raise AssertionError("test-policy.json must be a JSON object")

    allowed_top_keys = {"schemaVersion", "approvedSkips"}
    actual_top_keys = set(policy.keys())
    if actual_top_keys != allowed_top_keys:
        raise AssertionError(
            f"test-policy.json top-level keys mismatch. Expected {allowed_top_keys}, got {actual_top_keys}"
        )

    if policy.get("schemaVersion") != 1:
        raise AssertionError(f"test-policy.json schemaVersion must be 1, got {policy.get('schemaVersion')}")

    approved_skips = policy.get("approvedSkips")
    if not isinstance(approved_skips, list):
        raise AssertionError("approvedSkips must be a list")

    allowed_entry_keys = {"platform", "testName", "reasonPrefix"}
    seen_entries = set()

    for idx, entry in enumerate(approved_skips):
        if not isinstance(entry, dict):
            raise AssertionError(f"approvedSkips[{idx}] must be a dict")
        entry_keys = set(entry.keys())
        if entry_keys != allowed_entry_keys:
            raise AssertionError(
                f"approvedSkips[{idx}] keys mismatch. Expected {allowed_entry_keys}, got {entry_keys}"
            )
        for key in allowed_entry_keys:
            val = entry.get(key)
            if not isinstance(val, str) or not val.strip():
                raise AssertionError(f"approvedSkips[{idx}].{key} must be a non-empty string, got {val!r}")

        entry_tuple = (entry["platform"], entry["testName"], entry["reasonPrefix"])
        if entry_tuple in seen_entries:
            raise AssertionError(f"Duplicate approvedSkips entry detected: {entry_tuple}")
        seen_entries.add(entry_tuple)

    return policy


def parse_node_tap_skips(tap_output: str) -> tuple[dict, list[dict]]:
    """
    Parse Node TAP output summary and individual skipped test lines.
    Fails closed if TAP summary lacks skipped or todo count, or if parsed count != summary count.
    """
    m_tests = re.search(r"^#\s+tests\s+(\d+)", tap_output, re.MULTILINE)
    m_pass = re.search(r"^#\s+pass\s+(\d+)", tap_output, re.MULTILINE)
    m_fail = re.search(r"^#\s+fail\s+(\d+)", tap_output, re.MULTILINE)
    m_cancelled = re.search(r"^#\s+cancelled\s+(\d+)", tap_output, re.MULTILINE)
    m_skipped = re.search(r"^#\s+skipped\s+(\d+)", tap_output, re.MULTILINE)
    m_todo = re.search(r"^#\s+todo\s+(\d+)", tap_output, re.MULTILINE)

    if not m_skipped:
        raise AssertionError("TAP summary missing '# skipped N' line (FAIL-CLOSED)")
    if not m_todo:
        raise AssertionError("TAP summary missing '# todo N' line (FAIL-CLOSED)")

    summary = {
        "tests": int(m_tests.group(1)) if m_tests else None,
        "pass": int(m_pass.group(1)) if m_pass else None,
        "fail": int(m_fail.group(1)) if m_fail else 0,
        "cancelled": int(m_cancelled.group(1)) if m_cancelled else 0,
        "skipped": int(m_skipped.group(1)),
        "todo": int(m_todo.group(1)),
    }

    skip_pattern = re.compile(
        r"^(?:ok|not ok)\s+\d+\s+-\s+(?P<name>.+?)\s+#\s*SKIP(?:\s+(?P<reason>.*))?$",
        re.MULTILINE
    )
    parsed_skips = []
    for match in skip_pattern.finditer(tap_output):
        test_name = match.group("name").strip()
        reason = (match.group("reason") or "").strip()
        parsed_skips.append({"testName": test_name, "reason": reason})

    if len(parsed_skips) != summary["skipped"]:
        raise AssertionError(
            f"TAP summary skipped count ({summary['skipped']}) does not match parsed individual skip count ({len(parsed_skips)}) (FAIL-CLOSED)"
        )

    return summary, parsed_skips


def assert_registered_skips(tap_output: str, policy: dict, current_platform: str = sys.platform):
    """
    Enforce ZERO UNREGISTERED SKIPS policy:
    1. fail == 0, cancelled == 0, todo == 0.
    2. Every skipped test must match an approved entry in test-policy.json for current_platform.
    """
    summary, skips = parse_node_tap_skips(tap_output)

    if summary["fail"] > 0:
        raise AssertionError(f"TAP reported fail > 0: {summary['fail']}")
    if summary["cancelled"] > 0:
        raise AssertionError(f"TAP reported cancelled > 0: {summary['cancelled']}")
    if summary["todo"] > 0:
        raise AssertionError(f"TAP reported todo > 0: {summary['todo']}")

    approved_for_platform = [
        entry for entry in policy.get("approvedSkips", [])
        if entry.get("platform") == current_platform
    ]

    for skip in skips:
        matched = False
        for approved in approved_for_platform:
            if approved["testName"] == skip["testName"] and skip["reason"].startswith(approved["reasonPrefix"]):
                matched = True
                break
        if not matched:
            raise AssertionError(
                f"Unregistered skip on platform '{current_platform}': "
                f"testName='{skip['testName']}', reason='{skip['reason']}'"
            )


TIMING_MARKER_PREFIX = "KNOWN_FOLDER_BRIDGE_MS="
STRICT_TIMING_REGEX = re.compile(r"^(?:#\s*)?KNOWN_FOLDER_BRIDGE_MS=(\d+)$")


def parse_and_validate_timing_markers(tap_output: str) -> list[int]:
    r"""
    Parse and validate KNOWN_FOLDER_BRIDGE_MS timing markers from captured stdout.
    Strict fail-closed grammar:
    - If any line contains KNOWN_FOLDER_BRIDGE_MS=, the complete logical line must match:
      ^(?:#\s*)?KNOWN_FOLDER_BRIDGE_MS=(\d+)$
    - Otherwise raises AssertionError (FAIL CLOSED).
    - Returns list of parsed non-negative integer millisecond values.
    """
    markers = []
    for line in tap_output.splitlines():
        trimmed = line.strip()
        if TIMING_MARKER_PREFIX in trimmed:
            m = STRICT_TIMING_REGEX.match(trimmed)
            if not m:
                raise AssertionError(
                    f"Malformed or contaminated KNOWN_FOLDER_BRIDGE_MS line (FAIL-CLOSED): {trimmed!r}"
                )
            val = int(m.group(1))
            markers.append(val)
    return markers


def get_expected_timing_marker_count(test_file: str | None, current_platform: str) -> int:
    """
    Returns the expected number of timing markers:
    - On non-win32 platforms: 0
    - On win32:
      - If test_file is None (combined runner): 1
      - If test_file basename is 'local-config-loader.test.js': 1
      - For every other test_file: 0
    """
    if current_platform != "win32":
        return 0
    if test_file is None:
        return 1
    if os.path.basename(test_file) == "local-config-loader.test.js":
        return 1
    return 0


def assert_timing_marker_count(markers: list[int], test_file: str | None, current_platform: str):
    """
    Pure validation helper asserting exact expected timing marker count for platform and suite.
    """
    expected = get_expected_timing_marker_count(test_file, current_platform)
    if len(markers) != expected:
        suite_desc = os.path.basename(test_file) if test_file else "combined"
        raise AssertionError(
            f"Expected {expected} timing marker(s) for '{suite_desc}' on platform '{current_platform}', "
            f"got {len(markers)}: {markers} (FAIL-CLOSED)"
        )


def forward_timing_markers(markers: list[int]):
    """
    Re-emit ONLY normalized KNOWN_FOLDER_BRIDGE_MS=<integer> lines.
    Never re-emit surrounding successful Node TAP stdout/stderr.
    """
    for val in markers:
        print(f"KNOWN_FOLDER_BRIDGE_MS={val}")


CREDM_MARKER_NAMES = [
    "CREDM_SYN_WRITE_MS",
    "CREDM_PROV_READ_EXISTING_MS",
    "CREDM_SYN_DEL_MS",
    "CREDM_PROV_READ_MISSING_MS",
]
CREDM_MARKER_NAMES_SET = set(CREDM_MARKER_NAMES)


def parse_credman_timing_markers(tap_output: str) -> list[tuple[str, int]]:
    r"""
    Parse and validate CREDM timing markers from captured stdout.
    Strict fail-closed grammar:
    - Any line containing 'CREDM_' must match optional TAP '# ' prefix + exact marker name + '=' + digits.
    - Rejects negative, fraction, suffix text, duplicate, unknown CREDM marker, contaminated line.
    - Returns list of (marker_name, int_val).
    """
    parsed = []
    seen = set()
    for line in tap_output.splitlines():
        trimmed = line.strip()
        if "CREDM_" in trimmed:
            m = re.match(r"^(?:#\s*)?([A-Za-z0-9_]+)=(\S.*)$", trimmed)
            if not m:
                raise AssertionError(f"Contaminated or malformed CREDM line (FAIL-CLOSED): {trimmed!r}")
            name = m.group(1)
            val_str = m.group(2)
            if name not in CREDM_MARKER_NAMES_SET:
                raise AssertionError(f"Unknown CREDM marker (FAIL-CLOSED): {name!r}")
            if not re.match(r"^\d+$", val_str):
                raise AssertionError(f"Invalid CREDM marker value (FAIL-CLOSED): {val_str!r} on line {trimmed!r}")
            if name in seen:
                raise AssertionError(f"Duplicate CREDM marker (FAIL-CLOSED): {name!r}")
            seen.add(name)
            parsed.append((name, int(val_str)))
    return parsed


def is_credman_target_suite(test_file: str | None) -> bool:
    if test_file is None:
        return False
    return os.path.basename(test_file) == "windows-credential-manager-provider.test.js"


def get_expected_credman_timing_marker_count(test_file: str | None, current_platform: str) -> int:
    """
    Returns the expected number of CREDM timing markers:
    - On non-win32 platforms: 0
    - On win32:
      - If test_file is None (combined runner): 4
      - If test_file basename is 'windows-credential-manager-provider.test.js': 4
      - For every other test_file: 0
    """
    if current_platform != "win32":
        return 0
    if test_file is None or is_credman_target_suite(test_file):
        return 4
    return 0


def assert_credman_timing_marker_count(
    markers: list[tuple[str, int]],
    test_file: str | None,
    current_platform: str,
    node_succeeded: bool = True
):
    """
    Asserts exact expected CREDM timing markers for platform and suite.
    - If node_succeeded is False: do not require all 4 markers, but still reject on non-win32 or non-target.
    - If node_succeeded is True:
      - On non-win32 or non-target: count must be 0.
      - On win32 target or combined: count must be 4, and each of the 4 CREDM names must appear exactly once.
    """
    if current_platform != "win32" or (test_file is not None and not is_credman_target_suite(test_file)):
        if len(markers) != 0:
            suite_desc = os.path.basename(test_file) if test_file else "combined"
            raise AssertionError(
                f"Expected 0 CREDM marker(s) for '{suite_desc}' on platform '{current_platform}', "
                f"got {len(markers)} (FAIL-CLOSED)"
            )
        return

    if node_succeeded:
        if len(markers) != 4:
            suite_desc = os.path.basename(test_file) if test_file else "combined"
            raise AssertionError(
                f"Expected 4 CREDM marker(s) for '{suite_desc}' on platform '{current_platform}', "
                f"got {len(markers)} (FAIL-CLOSED)"
            )
        marker_names = [name for name, _ in markers]
        if set(marker_names) != CREDM_MARKER_NAMES_SET:
            raise AssertionError(
                f"CREDM markers missing or incorrect: expected {CREDM_MARKER_NAMES}, got {marker_names} (FAIL-CLOSED)"
            )


def forward_credman_timing_markers(markers: list[tuple[str, int]]):
    """
    Re-emit ONLY normalized CREDM_<NAME>=<integer> lines.
    Never re-emit surrounding successful Node TAP stdout/stderr.
    """
    for name, val in markers:
        print(f"{name}={val}")


EXPECTED_PROBE_CELLS = [
    (r, env, cmd)
    for r in (1, 2, 3)
    for env in ("STRIPPED", "STRIPPED_PLUS_OS", "INHERITED")
    for cmd in ("NOOP", "ADDTYPE")
]

PROBE_LINE_REGEX = re.compile(
    r"^PROBE round=([123]) env=(STRIPPED|STRIPPED_PLUS_OS|INHERITED) cmd=(NOOP|ADDTYPE) ms=(\d+) status=(-?\d+|null) timedout=([01])$"
)


def parse_and_validate_credman_ab_probe(output_text: str) -> list[str]:
    """
    Parse and validate the 18-cell hosted A/B/C probe stdout.
    Fail-closed requirements:
    - Exactly 18 nonblank lines.
    - Each line matches exact grammar.
    - Matrix matches exact sequence of EXPECTED_PROBE_CELLS.
    - No missing, duplicate, reordered, or extra lines.
    - Returns list of normalized probe lines.
    """
    nonblank_lines = [line.strip() for line in output_text.splitlines() if line.strip()]
    if len(nonblank_lines) != 18:
        raise AssertionError(
            f"Hosted A/B/C probe output must have exactly 18 nonblank lines, got {len(nonblank_lines)} (FAIL-CLOSED)"
        )

    parsed_lines = []
    for idx, line in enumerate(nonblank_lines):
        m = PROBE_LINE_REGEX.match(line)
        if not m:
            raise AssertionError(f"Hosted A/B/C probe line {idx + 1} malformed (FAIL-CLOSED): {line!r}")
        r = int(m.group(1))
        env = m.group(2)
        cmd = m.group(3)
        expected_cell = EXPECTED_PROBE_CELLS[idx]
        actual_cell = (r, env, cmd)
        if actual_cell != expected_cell:
            raise AssertionError(
                f"Hosted A/B/C probe cell mismatch at line {idx + 1}: expected {expected_cell}, got {actual_cell} (FAIL-CLOSED)"
            )
        parsed_lines.append(line)

    return parsed_lines


def run_and_validate_credman_ab_probe(repo_root: str = REPO_ROOT):
    """
    Execute hosted credman A/B/C probe once on Windows after individual Test J.
    Top-level probe process must exit 0.
    Capture stdout and validate 18 lines.
    Forward all 18 normalized PROBE lines to pytest stdout.
    """
    probe_rel = "runtime/channel-gateway/tests/credman-env-ab-probe.js"
    res = subprocess.run(
        ["node", probe_rel],
        cwd=repo_root,
        capture_output=True,
        encoding="utf-8",
        errors="replace"
    )
    if res.returncode != 0:
        raise AssertionError(
            f"Hosted A/B/C probe process failed with exit code {res.returncode}:\n"
            f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
        )
    parsed_lines = parse_and_validate_credman_ab_probe(res.stdout)
    for line in parsed_lines:
        print(line)


DISCOVERED_TEST_FILES = discover_gateway_test_files()


def test_channel_gateway_package_json_zero_dependencies():
    """Requirement A: package.json exists, is private, and has zero dependencies."""
    assert os.path.isfile(PACKAGE_JSON_PATH), f"package.json missing at {PACKAGE_JSON_PATH}"

    with open(PACKAGE_JSON_PATH, "r", encoding="utf-8") as f:
        pkg = json.load(f)

    assert pkg.get("private") is True, "package.json must have private: true"

    deps = pkg.get("dependencies", {})
    assert len(deps) == 0, f"dependencies must be empty/absent, found: {deps}"

    dev_deps = pkg.get("devDependencies", {})
    assert len(dev_deps) == 0, f"devDependencies must be empty/absent, found: {dev_deps}"


def test_channel_gateway_package_lock_exists():
    """Requirement B: package-lock.json exists and contains no third-party packages."""
    assert os.path.isfile(PACKAGE_LOCK_PATH), f"package-lock.json missing at {PACKAGE_LOCK_PATH}"

    with open(PACKAGE_LOCK_PATH, "r", encoding="utf-8") as f:
        lock = json.load(f)

    packages = lock.get("packages", {})
    non_root_packages = [k for k in packages.keys() if k != ""]
    assert len(non_root_packages) == 0, f"package-lock.json must not have dependencies: {non_root_packages}"


def test_channel_gateway_test_policy_schema():
    """Requirement C: test-policy.json strictly complies with approved skips schema."""
    policy = load_gateway_test_policy()
    assert policy.get("schemaVersion") == 1
    assert isinstance(policy.get("approvedSkips"), list)


def test_channel_gateway_nvmrc_and_engines_consistency():
    """Requirement D: Verify .nvmrc exists and is exact 24.21.0, and package.json engines / test script."""
    assert os.path.isfile(NVMRC_PATH), f".nvmrc missing at {NVMRC_PATH}"
    with open(NVMRC_PATH, "r", encoding="utf-8") as f:
        nvmrc_content = f.read().strip()
    assert nvmrc_content == "24.21.0", f".nvmrc must be exact 24.21.0, got: {nvmrc_content!r}"

    with open(PACKAGE_JSON_PATH, "r", encoding="utf-8") as f:
        pkg = json.load(f)

    engines = pkg.get("engines", {})
    assert engines.get("node") == ">=24.15.0 <25", f"package.json engines.node must be '>=24.15.0 <25', got {engines}"

    test_script = pkg.get("scripts", {}).get("test", "")
    assert test_script == 'node --test --test-reporter=tap "tests/*.test.js"', (
        f"package.json scripts.test must be automatic quoted glob, got: {test_script!r}"
    )
    assert "channel-control.test.js" not in test_script
    assert "durable-state-store.test.js" not in test_script


def test_channel_gateway_discovery_contract():
    """Requirement E: Dynamic discovery finds regular .test.js files deterministically."""
    files = discover_gateway_test_files()
    assert len(files) >= 1, "At least 1 test file must be discovered"
    for path in files:
        assert os.path.isfile(path), f"Discovered path must be a regular file: {path}"
        assert path.endswith(".test.js"), f"Discovered file must have .test.js extension: {path}"


@pytest.mark.parametrize("test_file", DISCOVERED_TEST_FILES, ids=[os.path.basename(f) for f in DISCOVERED_TEST_FILES])
def test_channel_gateway_individual_test_file(test_file):
    """Requirement F: Run each discovered test suite via Node TAP runner and verify zero unregistered skips."""
    assert os.path.isfile(test_file), f"Test file missing: {test_file}"
    rel_path = os.path.relpath(test_file, REPO_ROOT).replace("\\", "/")

    res = subprocess.run(
        ["node", "--test", "--test-reporter=tap", rel_path],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace"
    )

    markers = parse_and_validate_timing_markers(res.stdout)
    forward_timing_markers(markers)

    credm_markers = parse_credman_timing_markers(res.stdout)
    if is_credman_target_suite(test_file):
        forward_credman_timing_markers(credm_markers)

    if sys.platform == "win32" and is_credman_target_suite(test_file):
        run_and_validate_credman_ab_probe()

    assert res.returncode == 0, (
        f"{os.path.basename(test_file)} failed with code {res.returncode}:\n"
        f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )

    assert_timing_marker_count(markers, test_file, current_platform=sys.platform)
    assert_credman_timing_marker_count(credm_markers, test_file, current_platform=sys.platform, node_succeeded=True)

    policy = load_gateway_test_policy()
    assert_registered_skips(res.stdout, policy)


def test_channel_gateway_combined_node_test_runner():
    """Requirement F: Run all discovered test suites together and verify zero unregistered skips."""
    files = discover_gateway_test_files()
    rel_paths = [os.path.relpath(p, REPO_ROOT).replace("\\", "/") for p in files]

    cmd = ["node", "--test", "--test-reporter=tap"] + rel_paths
    res = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace"
    )

    markers = parse_and_validate_timing_markers(res.stdout)
    forward_timing_markers(markers)

    credm_markers = parse_credman_timing_markers(res.stdout)
    # RAW LOG POLICY: For combined runner, validate the four but DO NOT forward the second set.

    assert res.returncode == 0, (
        f"Combined node --test failed with code {res.returncode}:\n"
        f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )

    assert_timing_marker_count(markers, None, current_platform=sys.platform)
    assert_credman_timing_marker_count(credm_markers, None, current_platform=sys.platform, node_succeeded=True)

    policy = load_gateway_test_policy()
    assert_registered_skips(res.stdout, policy)


def test_channel_gateway_node_sqlite_smoke():
    """Requirement G: Verify Node.js semver major=24 (>=24.15.0 <25), node:sqlite load, and zero ExperimentalWarning."""
    ver_res = subprocess.run(["node", "--version"], capture_output=True, text=True, check=False)
    assert ver_res.returncode == 0, f"node --version failed: {ver_res.stderr}"
    raw_ver = ver_res.stdout.strip().lstrip("v")
    parts = [int(p) for p in raw_ver.split(".")]
    assert parts[0] == 24, f"Node major version must be 24, got: {parts[0]}"
    assert tuple(parts[:3]) >= (24, 15, 0), f"Node version must be >= 24.15.0, got: {raw_ver}"
    assert tuple(parts[:3]) < (25, 0, 0), f"Node version must be < 25.0.0, got: {raw_ver}"

    smoke_script = (
        "const { DatabaseSync } = require('node:sqlite');\n"
        "if (!DatabaseSync) { throw new Error('DatabaseSync missing'); }\n"
        "const db = new DatabaseSync(':memory:');\n"
        "const row = db.prepare('SELECT sqlite_version() AS v').get();\n"
        "if (!row || !row.v) { throw new Error('Query failed'); }\n"
        "db.close();\n"
    )
    smoke_res = subprocess.run(
        ["node", "-e", smoke_script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False
    )
    assert smoke_res.returncode == 0, f"node:sqlite smoke failed: {smoke_res.stderr}\nstdout: {smoke_res.stdout}"
    assert "ExperimentalWarning" not in smoke_res.stderr, (
        f"node:sqlite emitted ExperimentalWarning: {smoke_res.stderr}"
    )


def test_canary_a_registered_windows_skip_passes():
    """Requirement H (Canary A): registered Windows skip passes under win32 platform."""
    policy = load_gateway_test_policy()
    tap = (
        "TAP version 13\n"
        "ok 1 - normal test\n"
        "ok 2 - LocalConfigLoader - 9. repo-external symlink resolving into repo rejected 或 capability-aware skip # SKIP Symlink creation not permitted in this environment (EPERM)\n"
        "1..2\n"
        "# tests 2\n"
        "# suites 0\n"
        "# pass 1\n"
        "# fail 0\n"
        "# cancelled 0\n"
        "# skipped 1\n"
        "# todo 0\n"
    )
    assert_registered_skips(tap, policy, current_platform="win32")


def test_canary_b_unknown_test_skip_fails():
    """Requirement H (Canary B): unknown test skip fails closed."""
    policy = load_gateway_test_policy()
    tap = (
        "TAP version 13\n"
        "ok 1 - normal test\n"
        "ok 2 - UnregisteredSuite - 1. unknown test # SKIP Symlink creation not permitted in this environment\n"
        "1..2\n"
        "# tests 2\n"
        "# suites 0\n"
        "# pass 1\n"
        "# fail 0\n"
        "# cancelled 0\n"
        "# skipped 1\n"
        "# todo 0\n"
    )
    with pytest.raises(AssertionError, match="Unregistered skip"):
        assert_registered_skips(tap, policy, current_platform="win32")


def test_canary_c_known_test_unknown_reason_fails():
    """Requirement H (Canary C): known test with unapproved reason fails closed."""
    policy = load_gateway_test_policy()
    tap = (
        "TAP version 13\n"
        "ok 1 - normal test\n"
        "ok 2 - LocalConfigLoader - 9. repo-external symlink resolving into repo rejected 或 capability-aware skip # SKIP Unapproved random reason\n"
        "1..2\n"
        "# tests 2\n"
        "# suites 0\n"
        "# pass 1\n"
        "# fail 0\n"
        "# cancelled 0\n"
        "# skipped 1\n"
        "# todo 0\n"
    )
    with pytest.raises(AssertionError, match="Unregistered skip"):
        assert_registered_skips(tap, policy, current_platform="win32")


def test_canary_d_known_windows_skip_on_linux_fails():
    """Requirement H (Canary D): known Windows skip evaluated under linux platform fails closed."""
    policy = load_gateway_test_policy()
    tap = (
        "TAP version 13\n"
        "ok 1 - normal test\n"
        "ok 2 - LocalConfigLoader - 9. repo-external symlink resolving into repo rejected 或 capability-aware skip # SKIP Symlink creation not permitted in this environment (EPERM)\n"
        "1..2\n"
        "# tests 2\n"
        "# suites 0\n"
        "# pass 1\n"
        "# fail 0\n"
        "# cancelled 0\n"
        "# skipped 1\n"
        "# todo 0\n"
    )
    with pytest.raises(AssertionError, match="Unregistered skip on platform 'linux'"):
        assert_registered_skips(tap, policy, current_platform="linux")


def test_canary_e_summary_skip_count_mismatch_fails():
    """Requirement H (Canary E): summary skipped count mismatch with parsed entries fails closed."""
    policy = load_gateway_test_policy()
    tap = (
        "TAP version 13\n"
        "ok 1 - normal test\n"
        "ok 2 - LocalConfigLoader - 9. repo-external symlink resolving into repo rejected 或 capability-aware skip # SKIP Symlink creation not permitted in this environment (EPERM)\n"
        "1..2\n"
        "# tests 2\n"
        "# suites 0\n"
        "# pass 1\n"
        "# fail 0\n"
        "# cancelled 0\n"
        "# skipped 2\n"
        "# todo 0\n"
    )
    with pytest.raises(AssertionError, match="does not match parsed individual skip count"):
        assert_registered_skips(tap, policy, current_platform="win32")


def test_canary_f_todo_greater_than_zero_fails():
    """Requirement H (Canary F): todo count > 0 fails closed."""
    policy = load_gateway_test_policy()
    tap = (
        "TAP version 13\n"
        "ok 1 - normal test\n"
        "1..1\n"
        "# tests 1\n"
        "# suites 0\n"
        "# pass 1\n"
        "# fail 0\n"
        "# cancelled 0\n"
        "# skipped 0\n"
        "# todo 1\n"
    )
    with pytest.raises(AssertionError, match="todo > 0"):
        assert_registered_skips(tap, policy, current_platform="win32")


def test_t9_retirement_structural_guard():
    """Requirement I: Deterministic T9 retirement structural anti-resurrection guard."""
    core_dir = os.path.join(GATEWAY_DIR, "core")
    tests_dir = os.path.join(GATEWAY_DIR, "tests")

    retired_core_modules = [
        "durable-state-store.js",
        "channel-state-recovery.js",
        "channel-state-persistence.js",
    ]
    for mod in retired_core_modules:
        path = os.path.join(core_dir, mod)
        assert not os.path.exists(path), f"Retired core module must not exist: {path}"

    retired_test_files = [
        "durable-state-store.test.js",
        "channel-state-recovery.test.js",
        "channel-state-persistence.test.js",
    ]
    for t_file in retired_test_files:
        path = os.path.join(tests_dir, t_file)
        assert not os.path.exists(path), f"Retired test file must not exist: {path}"

    with open(TEST_POLICY_PATH, "r", encoding="utf-8") as f:
        policy_content = f.read()
    assert "DurableStateStore" not in policy_content, "test-policy.json must not contain 'DurableStateStore'"

    retired_import_targets = [
        "./durable-state-store",
        "./channel-state-recovery",
        "./channel-state-persistence",
    ]

    for fname in os.listdir(core_dir):
        if fname.endswith(".js"):
            fpath = os.path.join(core_dir, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            for target in retired_import_targets:
                assert target not in content, f"Active core module {fname} must not reference {target}"
            assert "channel-gateway-state.json" not in content, (
                f"Active core module {fname} must not reference 'channel-gateway-state.json'"
            )

    for fname in os.listdir(tests_dir):
        if fname.endswith(".js"):
            fpath = os.path.join(tests_dir, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            for target in retired_import_targets:
                assert target not in content, f"Gateway test {fname} must not import {target}"


def test_channel_gateway_sqlite_gitignore_protection():
    """Requirement J: Verify .gitignore contains SQLite patterns and does not ignore tracked source files."""
    gitignore_path = os.path.join(REPO_ROOT, ".gitignore")
    assert os.path.isfile(gitignore_path), f".gitignore missing at {gitignore_path}"
    with open(gitignore_path, "r", encoding="utf-8") as f:
        gitignore_content = f.read()

    required_patterns = ["*.sqlite3", "*.sqlite3-wal", "*.sqlite3-shm"]
    for pat in required_patterns:
        assert pat in gitignore_content, f".gitignore missing pattern {pat}"

    # Negative canary: verify tracked source and test files are not ignored by git
    tracked_sample_files = [
        "runtime/channel-gateway/core/sqlite-state-repository.js",
        "runtime/channel-gateway/tests/sqlite-state-repository.test.js",
        "runtime/channel-gateway/adapters/telegram-inbound-adapter.js",
        "runtime/channel-gateway/tests/telegram-inbound-adapter.test.js",
    ]
    for rel_f in tracked_sample_files:
        res = subprocess.run(
            ["git", "check-ignore", "-q", rel_f],
            cwd=REPO_ROOT,
            check=False
        )
        assert res.returncode == 1, f"Tracked file {rel_f} must NOT be ignored by .gitignore (check-ignore exit 1 expected)"

    # Positive check: verify a runtime sqlite3 file is ignored
    res_pos = subprocess.run(
        ["git", "check-ignore", "-q", "runtime/channel-gateway/state/channel-gateway-state.sqlite3"],
        cwd=REPO_ROOT,
        check=False
    )
    assert res_pos.returncode == 0, "Runtime sqlite3 file must be ignored by .gitignore (check-ignore exit 0 expected)"


# ==========================================
# K. Layer 2 Timing Marker Canaries (Synthetic & Platform-Injected)
# ==========================================

def test_canary_timing_marker_valid_parsing():
    """Canary: valid timing marker parsing from plain and TAP comment lines."""
    tap = (
        "TAP version 13\n"
        "# KNOWN_FOLDER_BRIDGE_MS=250\n"
        "ok 1 - test\n"
        "KNOWN_FOLDER_BRIDGE_MS=0\n"
    )
    markers = parse_and_validate_timing_markers(tap)
    assert markers == [250, 0]


def test_canary_c3_path_suffixed_timing_marker_rejected():
    """Canary C3: path-suffixed timing marker rejected fail-closed."""
    tap = "ok 1 - test\nKNOWN_FOLDER_BRIDGE_MS=12 C:\\synthetic\\path\n"
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        parse_and_validate_timing_markers(tap)


def test_canary_c4_negative_timing_value_rejected():
    """Canary C4: negative timing value rejected fail-closed."""
    tap = "ok 1 - test\nKNOWN_FOLDER_BRIDGE_MS=-1\n"
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        parse_and_validate_timing_markers(tap)


def test_canary_c5_fractional_timing_value_rejected():
    """Canary C5: fractional timing value rejected fail-closed."""
    tap = "ok 1 - test\nKNOWN_FOLDER_BRIDGE_MS=1.5\n"
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        parse_and_validate_timing_markers(tap)


def test_canary_malformed_marker_trailing_text_rejected():
    """Canary: malformed timing marker with extra payload rejected fail-closed."""
    tap = "ok 1 - test\nKNOWN_FOLDER_BRIDGE_MS=12 extra\n"
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        parse_and_validate_timing_markers(tap)


def test_canary_c6_windows_expected_one_marker_absent_fails():
    """Canary C6: Windows expected-one with marker absent fails closed (platform injected)."""
    assert get_expected_timing_marker_count("local-config-loader.test.js", current_platform="win32") == 1
    assert get_expected_timing_marker_count(None, current_platform="win32") == 1

    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        assert_timing_marker_count([], "local-config-loader.test.js", current_platform="win32")
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        assert_timing_marker_count([], None, current_platform="win32")


def test_canary_c7_non_windows_expected_zero_injected_marker_fails():
    """Canary C7: non-Windows expected-zero with injected marker fails closed (platform injected)."""
    assert get_expected_timing_marker_count("local-config-loader.test.js", current_platform="linux") == 0
    assert get_expected_timing_marker_count(None, current_platform="linux") == 0

    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        assert_timing_marker_count([42], "local-config-loader.test.js", current_platform="linux")
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        assert_timing_marker_count([42], None, current_platform="linux")


def test_canary_non_target_individual_suite_zero_behavior():
    """Canary: non-target individual suite expects zero markers even on win32 (platform injected)."""
    assert get_expected_timing_marker_count("sqlite-state-repository.test.js", current_platform="win32") == 0
    assert_timing_marker_count([], "sqlite-state-repository.test.js", current_platform="win32")
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        assert_timing_marker_count([42], "sqlite-state-repository.test.js", current_platform="win32")


def test_credman_timing_marker_parser_canaries():
    """Canary: pure parser tests for CREDM timing markers."""
    # 1. Valid four markers pass
    valid_tap = (
        "CREDM_SYN_WRITE_MS=120\n"
        "CREDM_PROV_READ_EXISTING_MS=350\n"
        "CREDM_SYN_DEL_MS=85\n"
        "CREDM_PROV_READ_MISSING_MS=40\n"
    )
    markers = parse_credman_timing_markers(valid_tap)
    assert len(markers) == 4
    assert_credman_timing_marker_count(
        markers, "windows-credential-manager-provider.test.js", current_platform="win32", node_succeeded=True
    )
    assert_credman_timing_marker_count(
        markers, None, current_platform="win32", node_succeeded=True
    )

    # 2. Optional TAP prefix passes
    tap_prefix = (
        "# CREDM_SYN_WRITE_MS=120\n"
        "# CREDM_PROV_READ_EXISTING_MS=350\n"
        "# CREDM_SYN_DEL_MS=85\n"
        "# CREDM_PROV_READ_MISSING_MS=40\n"
    )
    markers_tap = parse_credman_timing_markers(tap_prefix)
    assert len(markers_tap) == 4

    # 3. Negative rejected
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        parse_credman_timing_markers("CREDM_SYN_WRITE_MS=-10\n")

    # 4. Fraction rejected
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        parse_credman_timing_markers("CREDM_SYN_WRITE_MS=12.5\n")

    # 5. Trailing text rejected
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        parse_credman_timing_markers("CREDM_SYN_WRITE_MS=100 trailing text\n")

    # 6. Duplicate rejected
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        parse_credman_timing_markers("CREDM_SYN_WRITE_MS=100\nCREDM_SYN_WRITE_MS=200\n")

    # 7. Missing marker rejected for successful Windows target
    incomplete = [
        ("CREDM_SYN_WRITE_MS", 100),
        ("CREDM_PROV_READ_EXISTING_MS", 200),
        ("CREDM_SYN_DEL_MS", 50),
    ]
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        assert_credman_timing_marker_count(
            incomplete, "windows-credential-manager-provider.test.js", current_platform="win32", node_succeeded=True
        )

    # 8. Unknown marker rejected
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        parse_credman_timing_markers("CREDM_UNKNOWN_FOO_MS=100\n")

    # 9. Markers on successful non-target rejected
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        assert_credman_timing_marker_count(
            markers, "local-config-loader.test.js", current_platform="win32", node_succeeded=True
        )

    # 10. Non-win32 expected zero
    assert get_expected_credman_timing_marker_count("windows-credential-manager-provider.test.js", current_platform="linux") == 0
    assert_credman_timing_marker_count(
        [], "windows-credential-manager-provider.test.js", current_platform="linux", node_succeeded=True
    )
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        assert_credman_timing_marker_count(
            markers, "windows-credential-manager-provider.test.js", current_platform="linux", node_succeeded=True
        )


def test_credman_ab_probe_parser_canaries():
    """Canary: pure parser tests for hosted A/B/C probe."""
    # 1. Valid exact 18-cell matrix passes & STRIPPED_PLUS_OS accepted
    valid_lines = [
        f"PROBE round={r} env={e} cmd={c} ms=100 status=0 timedout=0"
        for r, e, c in EXPECTED_PROBE_CELLS
    ]
    valid_text = "\n".join(valid_lines)
    parsed = parse_and_validate_credman_ab_probe(valid_text)
    assert len(parsed) == 18

    # 2. Reordered matrix fails
    reordered = list(valid_lines)
    reordered[0], reordered[1] = reordered[1], reordered[0]
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        parse_and_validate_credman_ab_probe("\n".join(reordered))

    # 3. Missing fails
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        parse_and_validate_credman_ab_probe("\n".join(valid_lines[:17]))

    # 4. Duplicate fails
    dup_lines = valid_lines[:17] + [valid_lines[0]]
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        parse_and_validate_credman_ab_probe("\n".join(dup_lines))

    # 5. Extra line fails
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        parse_and_validate_credman_ab_probe("\n".join(valid_lines + [valid_lines[0]]))

    # 6. Malformed fails
    malformed = list(valid_lines)
    malformed[0] = "MALFORMED line"
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        parse_and_validate_credman_ab_probe("\n".join(malformed))

    # 7. Integer-or-null status accepted
    null_status = list(valid_lines)
    null_status[1] = "PROBE round=1 env=STRIPPED cmd=ADDTYPE ms=120000 status=null timedout=1"
    parsed_null = parse_and_validate_credman_ab_probe("\n".join(null_status))
    assert len(parsed_null) == 18

    neg_status = list(valid_lines)
    neg_status[1] = "PROBE round=1 env=STRIPPED cmd=ADDTYPE ms=250 status=-1 timedout=0"
    parsed_neg = parse_and_validate_credman_ab_probe("\n".join(neg_status))
    assert len(parsed_neg) == 18

    # 8. Timedout 0/1 accepted (tested in null_status above and valid_lines)

    # 9. Invalid timedout rejected
    invalid_to = list(valid_lines)
    invalid_to[0] = "PROBE round=1 env=STRIPPED cmd=NOOP ms=100 status=0 timedout=2"
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        parse_and_validate_credman_ab_probe("\n".join(invalid_to))

    invalid_to_bool = list(valid_lines)
    invalid_to_bool[0] = "PROBE round=1 env=STRIPPED cmd=NOOP ms=100 status=0 timedout=false"
    with pytest.raises(AssertionError, match="FAIL-CLOSED"):
        parse_and_validate_credman_ab_probe("\n".join(invalid_to_bool))
