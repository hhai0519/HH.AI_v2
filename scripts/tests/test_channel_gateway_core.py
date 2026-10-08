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
Every child process started by this referee runs through scripts/bounded_process.py:
a timeout terminates the whole process tree and fails the test (B-107 slice 2).
"""

import ast
import base64
import json
import os
import re
import sys
import types
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GATEWAY_DIR = os.path.join(REPO_ROOT, "runtime", "channel-gateway")
PACKAGE_JSON_PATH = os.path.join(GATEWAY_DIR, "package.json")
PACKAGE_LOCK_PATH = os.path.join(GATEWAY_DIR, "package-lock.json")
TEST_POLICY_PATH = os.path.join(GATEWAY_DIR, "test-policy.json")
NVMRC_PATH = os.path.join(REPO_ROOT, ".nvmrc")
TESTS_DIR = os.path.join(GATEWAY_DIR, "tests")

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from scripts.bounded_process import run_bounded  # noqa: E402

# Time limits for child processes started by this referee. Observed Windows CI durations:
# longest single suite about 20 s, combined run about 45 s.
NODE_TEST_FILE_TIMEOUT_SEC = 300
NODE_COMBINED_TIMEOUT_SEC = 600
SHORT_COMMAND_TIMEOUT_SEC = 120


def _universal_newlines(data: bytes) -> str:
    return data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def run_bounded_text(cmd: list[str], timeout: int) -> types.SimpleNamespace:
    """Run cmd from REPO_ROOT with a time limit and whole-tree termination; a timeout or launch error fails."""
    res = run_bounded(cmd, cwd=REPO_ROOT, timeout=timeout)
    stdout = _universal_newlines(res.stdout)
    stderr = _universal_newlines(res.stderr)
    assert res.launch_error is None, f"{cmd[0]} could not be started: {res.launch_error}"
    assert not res.timed_out, (
        f"{' '.join(cmd[:3])} exceeded {timeout}s; process tree {res.kill_status}\n"
        f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
    )
    return types.SimpleNamespace(returncode=res.returncode, stdout=stdout, stderr=stderr)


def find_unbounded_process_calls(source: str) -> list[str]:
    """Return direct process-launch references that bypass run_bounded (subprocess.*, os.system, os.popen)."""
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) else [])
            if "subprocess" in names:
                hits.append((node.lineno, "import subprocess"))
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "subprocess" or (node.value.id == "os" and node.attr in ("system", "popen")):
                hits.append((node.lineno, f"{node.value.id}.{node.attr}"))
    return [f"line {n}: {what}" for n, what in sorted(hits)]


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


CREDM_MARKER_KEYS = [
    "CREDM_SYN_WRITE_MS",
    "CREDM_PROV_READ_EXISTING_MS",
    "CREDM_SYN_DEL_MS",
    "CREDM_PROV_READ_MISSING_MS",
]
CREDM_PROVIDER_MAX_MS = 15000
CREDM_LINE_REGEX = re.compile(r"^(?:#\s*)?([A-Za-z0-9_]+)=(.*)$")
STRICT_INT_REGEX = re.compile(r"^\d+$")


def parse_and_validate_credman_timing_markers(tap_output: str, expect_markers: bool) -> dict[str, int]:
    r"""
    Parse and validate CREDM timing markers from captured stdout/TAP.
    - If expect_markers is True:
        - Must contain exact four markers, each exactly once.
        - Any unknown CREDM_* marker -> AssertionError (FAIL CLOSED).
        - Any duplicate marker -> AssertionError (FAIL CLOSED).
        - Any malformed line containing CREDM_ -> AssertionError (FAIL CLOSED).
        - Any negative / non-integer value -> AssertionError (FAIL CLOSED).
        - CREDM_PROV_READ_EXISTING_MS <= 15000, else AssertionError.
        - CREDM_PROV_READ_MISSING_MS <= 15000, else AssertionError.
    - If expect_markers is False:
        - Must contain zero CREDM markers. Any CREDM line -> AssertionError (FAIL CLOSED).
    Returns dict mapping marker key to integer value.
    """
    found_markers = {}
    for line in tap_output.splitlines():
        trimmed = line.strip()
        if "CREDM_" in trimmed:
            m = CREDM_LINE_REGEX.match(trimmed)
            if not m:
                raise AssertionError(f"Malformed CREDM line (FAIL-CLOSED): {trimmed!r}")
            key, val_str = m.group(1), m.group(2)
            if not key.startswith("CREDM_"):
                raise AssertionError(f"Malformed CREDM key prefix (FAIL-CLOSED): {trimmed!r}")
            if key not in CREDM_MARKER_KEYS:
                raise AssertionError(f"Unknown CREDM marker key '{key}' (FAIL-CLOSED)")
            if not STRICT_INT_REGEX.match(val_str):
                raise AssertionError(f"Malformed or negative CREDM value '{val_str}' for '{key}' (FAIL-CLOSED)")
            if key in found_markers:
                raise AssertionError(f"Duplicate CREDM marker '{key}' (FAIL-CLOSED)")
            found_markers[key] = int(val_str)

    if not expect_markers:
        if found_markers:
            raise AssertionError(f"Expected zero CREDM markers, got {list(found_markers.keys())} (FAIL-CLOSED)")
        return found_markers

    for expected_key in CREDM_MARKER_KEYS:
        if expected_key not in found_markers:
            raise AssertionError(f"Missing required CREDM marker '{expected_key}' (FAIL-CLOSED)")

    read_existing = found_markers["CREDM_PROV_READ_EXISTING_MS"]
    if read_existing > CREDM_PROVIDER_MAX_MS:
        raise AssertionError(
            f"CREDM_PROV_READ_EXISTING_MS ({read_existing}ms) exceeded threshold {CREDM_PROVIDER_MAX_MS}ms (FAIL-CLOSED)"
        )

    read_missing = found_markers["CREDM_PROV_READ_MISSING_MS"]
    if read_missing > CREDM_PROVIDER_MAX_MS:
        raise AssertionError(
            f"CREDM_PROV_READ_MISSING_MS ({read_missing}ms) exceeded threshold {CREDM_PROVIDER_MAX_MS}ms (FAIL-CLOSED)"
        )

    return found_markers


def should_expect_credman_markers(test_file: str | None, current_platform: str) -> bool:
    """
    Returns True if exact four CREDM markers are expected for the suite and platform:
    - On non-win32 platforms: False
    - On win32:
      - If test_file is None (combined runner): True
      - If test_file basename is 'windows-credential-manager-provider.test.js': True
      - For every other test_file: False
    """
    if current_platform != "win32":
        return False
    if test_file is None:
        return True
    return os.path.basename(test_file) == "windows-credential-manager-provider.test.js"


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

    res = run_bounded_text(["node", "--test", "--test-reporter=tap", rel_path], NODE_TEST_FILE_TIMEOUT_SEC)

    markers = parse_and_validate_timing_markers(res.stdout)
    forward_timing_markers(markers)

    expect_credman = should_expect_credman_markers(test_file, current_platform=sys.platform)
    credman_markers = parse_and_validate_credman_timing_markers(res.stdout, expect_markers=expect_credman)
    if sys.platform == "win32" and os.path.basename(test_file) == "windows-credential-manager-provider.test.js":
        for k in CREDM_MARKER_KEYS:
            print(f"{k}={credman_markers[k]}")

    assert res.returncode == 0, (
        f"{os.path.basename(test_file)} failed with code {res.returncode}:\n"
        f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )

    assert_timing_marker_count(markers, test_file, current_platform=sys.platform)

    policy = load_gateway_test_policy()
    assert_registered_skips(res.stdout, policy)


def test_channel_gateway_combined_node_test_runner():
    """Requirement F: Run all discovered test suites together and verify zero unregistered skips."""
    files = discover_gateway_test_files()
    rel_paths = [os.path.relpath(p, REPO_ROOT).replace("\\", "/") for p in files]

    cmd = ["node", "--test", "--test-reporter=tap"] + rel_paths
    res = run_bounded_text(cmd, NODE_COMBINED_TIMEOUT_SEC)

    markers = parse_and_validate_timing_markers(res.stdout)
    forward_timing_markers(markers)

    expect_credman = should_expect_credman_markers(None, current_platform=sys.platform)
    parse_and_validate_credman_timing_markers(res.stdout, expect_markers=expect_credman)

    assert res.returncode == 0, (
        f"Combined node --test failed with code {res.returncode}:\n"
        f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )

    assert_timing_marker_count(markers, None, current_platform=sys.platform)

    policy = load_gateway_test_policy()
    assert_registered_skips(res.stdout, policy)


def test_channel_gateway_node_sqlite_smoke():
    """Requirement G: Verify Node.js semver major=24 (>=24.15.0 <25), node:sqlite load, and zero ExperimentalWarning."""
    ver_res = run_bounded_text(["node", "--version"], SHORT_COMMAND_TIMEOUT_SEC)
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
    smoke_res = run_bounded_text(["node", "-e", smoke_script], SHORT_COMMAND_TIMEOUT_SEC)
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
        res = run_bounded_text(["git", "check-ignore", "-q", rel_f], SHORT_COMMAND_TIMEOUT_SEC)
        assert res.returncode == 1, f"Tracked file {rel_f} must NOT be ignored by .gitignore (check-ignore exit 1 expected)"

    # Positive check: verify a runtime sqlite3 file is ignored
    res_pos = run_bounded_text(
        ["git", "check-ignore", "-q", "runtime/channel-gateway/state/channel-gateway-state.sqlite3"],
        SHORT_COMMAND_TIMEOUT_SEC,
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
    """
    Parser canary suite covering all required cases:
    - valid four PASS
    - missing FAIL
    - duplicate FAIL
    - malformed FAIL
    - negative FAIL
    - unknown CREDM marker FAIL
    - read-existing 15000 PASS
    - read-existing 15001 FAIL
    - read-missing 15000 PASS
    - read-missing 15001 FAIL
    - synthetic write >15000 PASS
    - synthetic delete >15000 PASS
    - expected-zero + zero PASS
    - expected-zero + marker present FAIL
    """
    base_tap = (
        "ok 1 - test\n"
        "CREDM_SYN_WRITE_MS=120\n"
        "CREDM_PROV_READ_EXISTING_MS=350\n"
        "CREDM_SYN_DEL_MS=85\n"
        "CREDM_PROV_READ_MISSING_MS=210\n"
    )

    # 1. valid four PASS
    parsed = parse_and_validate_credman_timing_markers(base_tap, expect_markers=True)
    assert parsed == {
        "CREDM_SYN_WRITE_MS": 120,
        "CREDM_PROV_READ_EXISTING_MS": 350,
        "CREDM_SYN_DEL_MS": 85,
        "CREDM_PROV_READ_MISSING_MS": 210,
    }

    # 2. missing FAIL
    missing_tap = (
        "CREDM_SYN_WRITE_MS=120\n"
        "CREDM_PROV_READ_EXISTING_MS=350\n"
        "CREDM_SYN_DEL_MS=85\n"
    )
    with pytest.raises(AssertionError, match="Missing required CREDM marker"):
        parse_and_validate_credman_timing_markers(missing_tap, expect_markers=True)

    # 3. duplicate FAIL
    dup_tap = base_tap + "CREDM_SYN_WRITE_MS=99\n"
    with pytest.raises(AssertionError, match="Duplicate CREDM marker"):
        parse_and_validate_credman_timing_markers(dup_tap, expect_markers=True)

    # 4. malformed FAIL
    malformed_tap = base_tap.replace("CREDM_SYN_WRITE_MS=120", "CREDM_SYN_WRITE_MS=not_a_number")
    with pytest.raises(AssertionError, match="Malformed or negative CREDM value"):
        parse_and_validate_credman_timing_markers(malformed_tap, expect_markers=True)

    # 5. negative FAIL
    neg_tap = base_tap.replace("CREDM_SYN_WRITE_MS=120", "CREDM_SYN_WRITE_MS=-10")
    with pytest.raises(AssertionError, match="Malformed or negative CREDM value"):
        parse_and_validate_credman_timing_markers(neg_tap, expect_markers=True)

    # 6. unknown CREDM marker FAIL
    unk_tap = base_tap + "CREDM_UNKNOWN_MS=100\n"
    with pytest.raises(AssertionError, match="Unknown CREDM marker key"):
        parse_and_validate_credman_timing_markers(unk_tap, expect_markers=True)

    # 7. read-existing 15000 PASS
    p_15000 = base_tap.replace("CREDM_PROV_READ_EXISTING_MS=350", "CREDM_PROV_READ_EXISTING_MS=15000")
    res_15000 = parse_and_validate_credman_timing_markers(p_15000, expect_markers=True)
    assert res_15000["CREDM_PROV_READ_EXISTING_MS"] == 15000

    # 8. read-existing 15001 FAIL
    f_15001 = base_tap.replace("CREDM_PROV_READ_EXISTING_MS=350", "CREDM_PROV_READ_EXISTING_MS=15001")
    with pytest.raises(AssertionError, match="CREDM_PROV_READ_EXISTING_MS.*exceeded threshold"):
        parse_and_validate_credman_timing_markers(f_15001, expect_markers=True)

    # 9. read-missing 15000 PASS
    pm_15000 = base_tap.replace("CREDM_PROV_READ_MISSING_MS=210", "CREDM_PROV_READ_MISSING_MS=15000")
    res_m15000 = parse_and_validate_credman_timing_markers(pm_15000, expect_markers=True)
    assert res_m15000["CREDM_PROV_READ_MISSING_MS"] == 15000

    # 10. read-missing 15001 FAIL
    fm_15001 = base_tap.replace("CREDM_PROV_READ_MISSING_MS=210", "CREDM_PROV_READ_MISSING_MS=15001")
    with pytest.raises(AssertionError, match="CREDM_PROV_READ_MISSING_MS.*exceeded threshold"):
        parse_and_validate_credman_timing_markers(fm_15001, expect_markers=True)

    # 11. synthetic write >15000 PASS
    sw_large = base_tap.replace("CREDM_SYN_WRITE_MS=120", "CREDM_SYN_WRITE_MS=25000")
    res_sw = parse_and_validate_credman_timing_markers(sw_large, expect_markers=True)
    assert res_sw["CREDM_SYN_WRITE_MS"] == 25000

    # 12. synthetic delete >15000 PASS
    sd_large = base_tap.replace("CREDM_SYN_DEL_MS=85", "CREDM_SYN_DEL_MS=30000")
    res_sd = parse_and_validate_credman_timing_markers(sd_large, expect_markers=True)
    assert res_sd["CREDM_SYN_DEL_MS"] == 30000

    # 13. expected-zero + zero PASS
    zero_tap = "ok 1 - test without credman\n# tests 1\n"
    res_zero = parse_and_validate_credman_timing_markers(zero_tap, expect_markers=False)
    assert res_zero == {}

    # 14. expected-zero + marker present FAIL
    with pytest.raises(AssertionError, match="Expected zero CREDM markers"):
        parse_and_validate_credman_timing_markers(base_tap, expect_markers=False)


def test_windows_gateway_powershell_bridges_have_no_external_cmdlets():
    """
    Mechanical authority: Gateway production PowerShell bridges have no external cmdlets.
    Requires Windows platform (skips on non-Windows).
    Uses Windows PowerShell 5.1 exact executable and -EncodedCommand.
    Validates exact set:
    - runtime/channel-gateway/bin/windows-credential-manager-access.ps1
    - runtime/channel-gateway/bin/windows-credential-manager-read.ps1
    - runtime/channel-gateway/bin/windows-known-folder-resolve.ps1
    Deterministic controls:
    - New-Object -> FAIL
    - Add-Type -> FAIL
    - Local function definition + invocation -> PASS
    """
    if sys.platform != "win32":
        pytest.skip("PowerShell bridge AST verification requires Windows platform")

    bin_dir = os.path.join(GATEWAY_DIR, "bin")
    actual_ps1_files = sorted([
        os.path.relpath(os.path.join(bin_dir, f), REPO_ROOT).replace("\\", "/")
        for f in os.listdir(bin_dir)
        if f.endswith(".ps1")
    ])
    expected_ps1_files = sorted([
        "runtime/channel-gateway/bin/windows-credential-manager-access.ps1",
        "runtime/channel-gateway/bin/windows-credential-manager-read.ps1",
        "runtime/channel-gateway/bin/windows-known-folder-resolve.ps1",
    ])
    assert actual_ps1_files == expected_ps1_files, (
        f"Production bridge exact set mismatch: expected {expected_ps1_files}, got {actual_ps1_files} (FAIL-CLOSED)"
    )

    ps_code = """
$PSModuleAutoLoadingPreference = 'None'
$ErrorActionPreference = 'Stop'

function Analyze-Code([string]$name, [string]$code) {
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($code, [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) {
        return $false
    }
    $functionDefs = $ast.FindAll({ $args[0] -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)
    $localFns = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($fn in $functionDefs) {
        [void]$localFns.Add($fn.Name)
    }
    $commandNodes = $ast.FindAll({ $args[0] -is [System.Management.Automation.Language.CommandAst] }, $true)
    foreach ($cmd in $commandNodes) {
        $cmdName = $cmd.GetCommandName()
        if ([string]::IsNullOrWhiteSpace($cmdName)) {
            return $false
        }
        if (-not $localFns.Contains($cmdName)) {
            return $false
        }
    }
    return $true
}

$bridges = @(
    'runtime/channel-gateway/bin/windows-credential-manager-access.ps1',
    'runtime/channel-gateway/bin/windows-credential-manager-read.ps1',
    'runtime/channel-gateway/bin/windows-known-folder-resolve.ps1'
)

foreach ($b in $bridges) {
    if (-not [System.IO.File]::Exists($b)) {
        [Console]::Error.WriteLine([string]::Concat('MISSING_FILE: ', $b))
        exit 10
    }
    $code = [System.IO.File]::ReadAllText($b)
    if (-not (Analyze-Code $b $code)) {
        [Console]::Error.WriteLine([string]::Concat('FAIL_BRIDGE: ', $b))
        exit 11
    }
}

# Deterministic controls
# Control 1: New-Object should fail
if (Analyze-Code 'ctl_new_object' '$x = New-Object System.Object') {
    [Console]::Error.WriteLine('CONTROL_FAILED: New-Object unexpectedly passed')
    exit 21
}

# Control 2: Add-Type should fail
if (Analyze-Code 'ctl_add_type' 'Add-Type "public class X {}"') {
    [Console]::Error.WriteLine('CONTROL_FAILED: Add-Type unexpectedly passed')
    exit 22
}

# Control 3: Local function definition + invocation should pass
if (-not (Analyze-Code 'ctl_local_fn' 'function My-Local { 42 }; My-Local')) {
    [Console]::Error.WriteLine('CONTROL_FAILED: local function unexpectedly failed')
    exit 23
}

exit 0
"""

    b64 = base64.b64encode(ps_code.encode("utf-16le")).decode("ascii")
    system_root = os.environ.get("SystemRoot", "C:\\Windows")
    powershell_path = os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    assert os.path.isfile(powershell_path), f"Windows PowerShell executable missing: {powershell_path}"

    res = run_bounded_text([
        powershell_path,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-EncodedCommand", b64
    ], SHORT_COMMAND_TIMEOUT_SEC)

    assert res.returncode == 0, (
        f"PowerShell AST verification failed (code {res.returncode}):\n"
        f"STDOUT: {res.stdout}\nSTDERR: {res.stderr}"
    )


# ==========================================
# L. Bounded child-process canaries (B-107 slice 2)
# ==========================================

def test_bounded_child_timeout_fails_closed():
    """A child that outlives its limit must fail the referee instead of hanging it."""
    with pytest.raises(AssertionError, match="exceeded 2s; process tree TREE_SIGNALLED"):
        run_bounded_text([sys.executable, "-c", "import time; time.sleep(60)"], 2)


def test_referee_child_processes_are_bounded():
    """Structural guard: this referee starts child processes only through run_bounded."""
    with open(os.path.abspath(__file__), "r", encoding="utf-8") as f:
        assert find_unbounded_process_calls(f.read()) == []
    unbounded = (
        "import subprocess\n"
        "import os\n"
        "subprocess.run(['node', '--version'])\n"
        "os.system('node --version')\n"
    )
    assert find_unbounded_process_calls(unbounded) == [
        "line 1: import subprocess", "line 3: subprocess.run", "line 4: os.system"]
