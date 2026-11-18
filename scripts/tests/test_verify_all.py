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
    """Control A. verify_all child gate failure -> runner non-zero"""
    def mock_run_gate(gate, env, cwd):
        if gate["name"] == "fingerprint":
            return 1
        return 0

    monkeypatch.setattr(verify_all, "run_gate", mock_run_gate)
    assert verify_all.main([]) == 1


def test_ci_workflow_uses_canonical_entrypoint():
    """D. CI workflow 直接呼叫 canonical entrypoint，不得包含 fail-open tee pipeline"""
    workflow_path = os.path.join(REPO_ROOT, ".github", "workflows", "verify.yml")
    with open(workflow_path, "r", encoding="utf-8") as f:
        text = f.read()

    # CI 必須呼叫 verify_all.py
    assert "verify_all.py" in text
    assert "run: python3 scripts/verify_all.py" in text
    # 不得有 fail-open tee pipeline
    assert "tee" not in text
    # 不得再有個別分散的測試指令列表
    assert "skills/execution/webapp-testing/tests/" not in text


# B117 R3 — stdout visibility and slow-test diagnostics for Windows.
def test_r3_unit_test_durations_and_stdout_flush(monkeypatch, capsys):
    gate = next(g for g in verify_all.GATES if g['name'] == 'unit_tests')
    assert gate['cmd'][-1] == '--durations=25'
    seen = {}
    def child(g, env, cwd):
        seen.update(env=env)
        return 0
    original = verify_all.run_gate
    monkeypatch.setattr(verify_all, 'run_gate', child)
    assert verify_all.main([]) == 0
    assert seen['env']['PYTHONUNBUFFERED'] == '1'
    assert '[PASS] Gate' in capsys.readouterr().out
    from types import SimpleNamespace
    monkeypatch.setattr(verify_all.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=0))
    assert original(gate, {}, verify_all.REPO_ROOT) == 0
    assert '[GATE] Running unit_tests:' in capsys.readouterr().out


# X batch: preview quick mode of gate 4.
def test_x_quick_mode_only_changes_gate_4_and_never_prints_the_full_pass_line(monkeypatch, capsys):
    full = {g["name"]: g["cmd"] for g in verify_all.GATES}
    quick = {g["name"]: g["cmd"] for g in verify_all.quick_gates()}
    assert [n for n in full if full[n] != quick[n]] == ["unit_tests"]
    assert quick["unit_tests"][-2:] == ["--collect-only", "-qq"] and "--collect-only" not in " ".join(full["unit_tests"])
    seen = []
    monkeypatch.setattr(verify_all, "run_gate", lambda gate, env, cwd: seen.append((gate["name"], gate["cmd"])) or 0)
    assert verify_all.main(["--gate4-collect-only"]) == 0
    out = capsys.readouterr().out
    assert seen == [(g["name"], g["cmd"]) for g in verify_all.quick_gates()]  # main really runs the collect-only gate 4
    assert "PREVIEW QUICK GATES PASSED" in out and "ALL 5 GATES PASSED" not in out


def test_x_default_mode_is_unchanged_and_the_canonical_gate_table_is_never_mutated(monkeypatch, capsys):
    before = [(g["name"], list(g["cmd"])) for g in verify_all.GATES]
    verify_all.quick_gates()
    monkeypatch.setattr(verify_all, "run_gate", lambda gate, env, cwd: 0)
    assert verify_all.main([]) == 0
    assert "ALL 5 GATES PASSED" in capsys.readouterr().out
    assert [(g["name"], list(g["cmd"])) for g in verify_all.GATES] == before


def test_x_a_failing_quick_gate_fails_the_run(monkeypatch, capsys):
    monkeypatch.setattr(verify_all, "run_gate", lambda gate, env, cwd: 2 if gate["name"] == "unit_tests" else 0)
    assert verify_all.main(["--gate4-collect-only"]) == 1
    out = capsys.readouterr().out
    assert "FAILED gates (1): unit_tests" in out and "PREVIEW QUICK GATES PASSED" not in out
