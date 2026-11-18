#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/verify_all.py

Canonical Verification Entrypoint (單一驗證權威入口)
統一管理並依序執行全專案 5 大 Correctness Gates：
  1. validate_skills   (scripts/validate_skills.py)
  2. check_consistency (scripts/check_consistency.py)
  3. fingerprint       (scripts/fingerprint.py --verify)
  4. unit_tests        (pytest scripts/tests/ -q)
  5. webapp_tests      (pytest skills/execution/webapp-testing/tests/ -q)

本工具是 PRECOMMIT（Prospective Commit）及 CI 的完整五閘門入口；POSTCOMMIT 由 scripts/gate_runner.py 的四項輕量守衛執行，並非同一集合。
任一閘門失敗即以非零 exit code 退出。
"""

import os
import sys
import subprocess
import argparse

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

GATES = [
    {
        "name": "validate_skills",
        "cmd": [sys.executable, os.path.join(REPO_ROOT, "scripts", "validate_skills.py")],
        "desc": "技能架構與 frontmatter 結構檢查",
    },
    {
        "name": "check_consistency",
        "cmd": [sys.executable, os.path.join(REPO_ROOT, "scripts", "check_consistency.py")],
        "desc": "全庫一致性檢查（含 active CHECK inventory 與規格重放）",
    },
    {
        "name": "fingerprint",
        "cmd": [sys.executable, os.path.join(REPO_ROOT, "scripts", "fingerprint.py"), "--verify"],
        "desc": "指紋檔完整性驗證",
    },
    {
        "name": "unit_tests",
        "cmd": [sys.executable, "-m", "pytest", os.path.join(REPO_ROOT, "scripts", "tests"), "-q", "--durations=25"],
        "desc": "Scripts 單元測試套件",
    },
    {
        "name": "webapp_tests",
        "cmd": [sys.executable, "-m", "pytest", os.path.join(REPO_ROOT, "skills", "execution", "webapp-testing", "tests"), "-q"],
        "desc": "Webapp 測試套件",
    },
]


def quick_gates():
    """Preview quick variant (scripts/gate_runner.py stage_gates): same five gates, but gate 4 only collects the
    test suite (import and collection errors still fail); never a substitute for the full gate 4."""
    gates = [dict(gate) for gate in GATES]
    for gate in gates:
        if gate["name"] == "unit_tests":
            gate["cmd"] = [sys.executable, "-m", "pytest", os.path.join(REPO_ROOT, "scripts", "tests"),
                           "--collect-only", "-qq"]
            gate["desc"] = "Scripts 單元測試套件（預演快速檢查：只收集不執行）"
    return gates


def run_gate(gate, env, cwd):
    print(f"\n[GATE] Running {gate['name']}: {gate['desc']}", flush=True)
    proc = subprocess.run(gate["cmd"], env=env, cwd=cwd)
    return proc.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description="Canonical Verification Runner")
    parser.add_argument("--fail-fast", action="store_true", help="任一閘門失敗時立即停止")
    parser.add_argument("--gate4-collect-only", action="store_true",
                        help="只供原生預演模擬使用：第 4 關只收集不執行；不輸出 ALL 5 GATES PASSED")
    args = parser.parse_args(argv)
    gates = quick_gates() if args.gate4_collect_only else GATES

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"

    failed = []
    for gate in gates:
        rc = run_gate(gate, env, REPO_ROOT)
        if rc != 0:
            print(f"[FAIL] Gate {gate['name']} exited with code {rc}", flush=True)
            failed.append(gate["name"])
            if args.fail_fast:
                break
        else:
            print(f"[PASS] Gate {gate['name']}", flush=True)

    print("\n" + "=" * 50)
    print("VERIFICATION SUMMARY")
    print("=" * 50)
    if failed:
        print(f"FAILED gates ({len(failed)}): {', '.join(failed)}")
        return 1
    elif args.gate4_collect_only:
        print(f"PREVIEW QUICK GATES PASSED ({len(gates)} gates; gate 4 collected only, not a full verification)")
        return 0
    else:
        print(f"ALL {len(GATES)} GATES PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(main())
