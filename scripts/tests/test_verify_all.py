import os
import sys
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import verify_all


def test_verify_all_gates_inventory():
    """C. webapp-testing suite 確實在 canonical inventory"""
    gate_names = [g["name"] for g in verify_all.GATES]
    assert "validate_skills" in gate_names
    assert "check_consistency" in gate_names
    assert "fingerprint" in gate_names
    assert "unit_tests" in gate_names
    assert "webapp_tests" in gate_names
    assert len(gate_names) == 5

    # 確認 webapp_tests 路徑正確
    webapp_gate = next(g for g in verify_all.GATES if g["name"] == "webapp_tests")
    cmd_str = " ".join(webapp_gate["cmd"])
    assert "webapp-testing" in cmd_str


def test_verify_all_success(monkeypatch):
    """A. 所有 child gate 全 PASS -> runner exit 0"""
    monkeypatch.setattr(verify_all, "run_gate", lambda gate, env, cwd: 0)
    assert verify_all.main([]) == 0


def test_verify_all_failure(monkeypatch):
    """B. 任一 child gate FAIL -> runner non-zero"""
    # 模擬第三個 gate 失敗
    def mock_run_gate(gate, env, cwd):
        if gate["name"] == "fingerprint":
            return 1
        return 0

    monkeypatch.setattr(verify_all, "run_gate", mock_run_gate)
    assert verify_all.main([]) == 1


def test_ci_workflow_uses_canonical_entrypoint():
    """D. CI workflow 不再維護另一份獨立 correctness-test list，而是直接呼叫 canonical entrypoint"""
    workflow_path = os.path.join(REPO_ROOT, ".github", "workflows", "verify.yml")
    with open(workflow_path, "r", encoding="utf-8") as f:
        text = f.read()

    # CI 必須呼叫 verify_all.py
    assert "verify_all.py" in text
    # 不得再有個別分散的測試指令列表
    assert "skills/execution/webapp-testing/tests/" not in text
