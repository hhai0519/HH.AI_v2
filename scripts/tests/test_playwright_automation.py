#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tests/test_playwright_automation.py

Canonical CI unit test gate integration for playwright-automation skill (TG-MVP-07 / B-30).
Validates:
1. helpers.js removes implicit commonPorts and top-level playwright require.
2. Node test suite (skills/execution/playwright-automation/tests/helpers.test.js) executes cleanly.
3. Node test non-zero exit => pytest fail (fail-closed, no silent skip).
4. Package and plugin metadata do not advertise unsafe auto-detection.
5. No network calls or npm install required.
"""

import json
import os
import subprocess
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SKILL_DIR = os.path.join(REPO_ROOT, "skills", "execution", "playwright-automation")
HELPERS_JS_PATH = os.path.join(SKILL_DIR, "lib", "helpers.js")
TEST_JS_PATH = os.path.join(SKILL_DIR, "tests", "helpers.test.js")
PACKAGE_JSON_PATH = os.path.join(SKILL_DIR, "package.json")
PLUGIN_JSON_PATH = os.path.join(SKILL_DIR, ".claude-plugin", "plugin.json")


def test_helpers_source_invariants():
    """Verify helpers.js source code invariants: no commonPorts, lazy playwright require."""
    assert os.path.isfile(HELPERS_JS_PATH), f"helpers.js missing at {HELPERS_JS_PATH}"

    with open(HELPERS_JS_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # commonPorts sweep must be gone
    assert "commonPorts" not in content, "helpers.js must not contain 'commonPorts' fallback array"

    # Top-level playwright require must be removed (lazy-loaded inside launchBrowser)
    first_30_lines = "\n".join(content.splitlines()[:30])
    assert "require('playwright')" not in first_30_lines and 'require("playwright")' not in first_30_lines, (
        "playwright package must not be required at top-level (deferred to launchBrowser)"
    )


def test_metadata_invariants():
    """Verify package.json and plugin.json do not claim unsafe auto-detection."""
    assert os.path.isfile(PACKAGE_JSON_PATH), f"package.json missing at {PACKAGE_JSON_PATH}"
    with open(PACKAGE_JSON_PATH, "r", encoding="utf-8") as f:
        pkg = json.load(f)

    pkg_desc = pkg.get("description", "")
    assert "auto-detection" not in pkg_desc.lower(), (
        f"package.json description must not claim 'auto-detection': {pkg_desc}"
    )

    assert os.path.isfile(PLUGIN_JSON_PATH), f"plugin.json missing at {PLUGIN_JSON_PATH}"
    with open(PLUGIN_JSON_PATH, "r", encoding="utf-8") as f:
        plugin = json.load(f)

    plugin_desc = plugin.get("description", "")
    assert "auto-detects" not in plugin_desc.lower(), (
        f"plugin.json description must not claim 'auto-detects': {plugin_desc}"
    )


def test_node_helpers_test_suite_passes():
    """
    Execute Node test suite via node --test without npm install or network.
    Fail-closed: non-zero exit => test failure.
    """
    assert os.path.isfile(TEST_JS_PATH), f"helpers.test.js missing at {TEST_JS_PATH}"

    cmd = ["node", "--test", "tests/helpers.test.js"]
    proc = subprocess.run(
        cmd,
        cwd=SKILL_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )

    if proc.returncode != 0:
        pytest.fail(
            f"Node test runner failed (exit {proc.returncode}):\n"
            f"STDOUT:\n{proc.stdout}\n"
            f"STDERR:\n{proc.stderr}"
        )
