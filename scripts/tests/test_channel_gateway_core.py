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
    assert res.returncode == 0, (
        f"{os.path.basename(test_file)} failed with code {res.returncode}:\n"
        f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )

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
    assert res.returncode == 0, (
        f"Combined node --test failed with code {res.returncode}:\n"
        f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )

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
