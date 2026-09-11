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

保證 Local、Prospective Commit、Post-commit 與 CI 執行完全一致的閘門集合。
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
        "desc": "全庫一致性檢查（含 CHECK 1-18 與規格重放）",
    },
    {
        "name": "fingerprint",
        "cmd": [sys.executable, os.path.join(REPO_ROOT, "scripts", "fingerprint.py"), "--verify"],
        "desc": "指紋檔完整性驗證",
    },
    {
        "name": "unit_tests",
        "cmd": [sys.executable, "-m", "pytest", os.path.join(REPO_ROOT, "scripts", "tests"), "-q"],
        "desc": "Scripts 單元測試套件",
    },
    {
        "name": "webapp_tests",
        "cmd": [sys.executable, "-m", "pytest", os.path.join(REPO_ROOT, "skills", "execution", "webapp-testing", "tests"), "-q"],
        "desc": "Webapp 測試套件",
    },
]


def run_gate(gate, env, cwd):
    print(f"\n[GATE] Running {gate['name']}: {gate['desc']}")
    proc = subprocess.run(gate["cmd"], env=env, cwd=cwd)
    return proc.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description="Canonical Verification Runner")
    parser.add_argument("--fail-fast", action="store_true", help="任一閘門失敗時立即停止")
    args = parser.parse_args(argv)

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    failed = []
    for gate in GATES:
        rc = run_gate(gate, env, REPO_ROOT)
        if rc != 0:
            print(f"[FAIL] Gate {gate['name']} exited with code {rc}")
            failed.append(gate["name"])
            if args.fail_fast:
                break
        else:
            print(f"[PASS] Gate {gate['name']}")

    print("\n" + "=" * 50)
    print("VERIFICATION SUMMARY")
    print("=" * 50)
    if failed:
        print(f"FAILED gates ({len(failed)}): {', '.join(failed)}")
        return 1
    else:
        print(f"ALL {len(GATES)} GATES PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(main())
