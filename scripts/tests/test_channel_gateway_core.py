#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tests/test_channel_gateway_core.py

Canonical CI unit test gate integration for Channel Gateway pure control core.
Validates:
A. runtime/channel-gateway/package.json exists with zero dependencies and zero devDependencies.
B. runtime/channel-gateway/package-lock.json exists.
C. Subprocess execution of Node built-in test runner for channel-control, account-registry,
   account-switch, and data-location-config test suites.
D. No network, no npm install, no service startup.
E. Cross-platform compatibility on Windows and Linux CI (explicit file paths).
"""

import json
import os
import subprocess
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GATEWAY_DIR = os.path.join(REPO_ROOT, "runtime", "channel-gateway")
PACKAGE_JSON_PATH = os.path.join(GATEWAY_DIR, "package.json")
PACKAGE_LOCK_PATH = os.path.join(GATEWAY_DIR, "package-lock.json")
CONTROL_TEST_PATH = os.path.join(GATEWAY_DIR, "tests", "channel-control.test.js")
REGISTRY_TEST_PATH = os.path.join(GATEWAY_DIR, "tests", "account-registry.test.js")
ACCOUNT_SWITCH_TEST_PATH = os.path.join(GATEWAY_DIR, "tests", "account-switch.test.js")
DATA_LOCATION_CONFIG_TEST_PATH = os.path.join(GATEWAY_DIR, "tests", "data-location-config.test.js")
LOCAL_CONFIG_LOADER_TEST_PATH = os.path.join(GATEWAY_DIR, "tests", "local-config-loader.test.js")


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
    # In npm lockfileVersion 3, packages only has "" (the root project) when zero deps
    non_root_packages = [k for k in packages.keys() if k != ""]
    assert len(non_root_packages) == 0, f"package-lock.json must not have dependencies: {non_root_packages}"


def test_channel_gateway_node_tests_channel_control():
    """Requirement C: Run channel-control.test.js via Node test runner."""
    assert os.path.isfile(CONTROL_TEST_PATH), f"Test file missing: {CONTROL_TEST_PATH}"

    res = subprocess.run(
        ["node", "--test", os.path.relpath(CONTROL_TEST_PATH, REPO_ROOT).replace("\\", "/")],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace"
    )
    assert res.returncode == 0, (
        f"channel-control.test.js failed with code {res.returncode}:\n"
        f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )
    assert "fail 0" in res.stdout


def test_channel_gateway_node_tests_account_registry():
    """Requirement C: Run account-registry.test.js via Node test runner."""
    assert os.path.isfile(REGISTRY_TEST_PATH), f"Test file missing: {REGISTRY_TEST_PATH}"

    res = subprocess.run(
        ["node", "--test", os.path.relpath(REGISTRY_TEST_PATH, REPO_ROOT).replace("\\", "/")],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace"
    )
    assert res.returncode == 0, (
        f"account-registry.test.js failed with code {res.returncode}:\n"
        f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )
    assert "fail 0" in res.stdout


def test_channel_gateway_node_tests_account_switch():
    """Requirement C: Run account-switch.test.js via Node test runner."""
    assert os.path.isfile(ACCOUNT_SWITCH_TEST_PATH), f"Test file missing: {ACCOUNT_SWITCH_TEST_PATH}"

    res = subprocess.run(
        ["node", "--test", os.path.relpath(ACCOUNT_SWITCH_TEST_PATH, REPO_ROOT).replace("\\", "/")],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace"
    )
    assert res.returncode == 0, (
        f"account-switch.test.js failed with code {res.returncode}:\n"
        f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )
    assert "fail 0" in res.stdout


def test_channel_gateway_node_tests_data_location_config():
    """Requirement C: Run data-location-config.test.js via Node test runner."""
    assert os.path.isfile(DATA_LOCATION_CONFIG_TEST_PATH), f"Test file missing: {DATA_LOCATION_CONFIG_TEST_PATH}"

    res = subprocess.run(
        ["node", "--test", os.path.relpath(DATA_LOCATION_CONFIG_TEST_PATH, REPO_ROOT).replace("\\", "/")],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace"
    )
    assert res.returncode == 0, (
        f"data-location-config.test.js failed with code {res.returncode}:\n"
        f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )
    assert "fail 0" in res.stdout


def test_channel_gateway_node_tests_local_config_loader():
    """Requirement C: Run local-config-loader.test.js via Node test runner."""
    assert os.path.isfile(LOCAL_CONFIG_LOADER_TEST_PATH), f"Test file missing: {LOCAL_CONFIG_LOADER_TEST_PATH}"

    res = subprocess.run(
        ["node", "--test", os.path.relpath(LOCAL_CONFIG_LOADER_TEST_PATH, REPO_ROOT).replace("\\", "/")],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace"
    )
    assert res.returncode == 0, (
        f"local-config-loader.test.js failed with code {res.returncode}:\n"
        f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )
    assert "fail 0" in res.stdout


def test_channel_gateway_combined_node_test_runner():
    """Requirement C & E: Run all Channel Gateway test files together with explicit paths."""
    rel_control = os.path.relpath(CONTROL_TEST_PATH, REPO_ROOT).replace("\\", "/")
    rel_registry = os.path.relpath(REGISTRY_TEST_PATH, REPO_ROOT).replace("\\", "/")
    rel_switch = os.path.relpath(ACCOUNT_SWITCH_TEST_PATH, REPO_ROOT).replace("\\", "/")
    rel_location = os.path.relpath(DATA_LOCATION_CONFIG_TEST_PATH, REPO_ROOT).replace("\\", "/")
    rel_loader = os.path.relpath(LOCAL_CONFIG_LOADER_TEST_PATH, REPO_ROOT).replace("\\", "/")

    res = subprocess.run(
        ["node", "--test", rel_control, rel_registry, rel_switch, rel_location, rel_loader],
        cwd=REPO_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace"
    )
    assert res.returncode == 0, (
        f"Combined node --test failed with code {res.returncode}:\n"
        f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )
    assert "fail 0" in res.stdout



