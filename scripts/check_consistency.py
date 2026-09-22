"""
用途：全庫一致性檢查，與 scripts/validate_skills.py 並列執行

檢查項目：
  CHECK 1 — 控制字元
  CHECK 2 — Markdown 圍欄配對
  CHECK 3 — Markdown 相對連結有效性
  CHECK 4 — 三層 README 完整性
  CHECK 5 — SOP_00A 路由目標存在性
  CHECK 6 — skills/ 底下不得殘留舊分層路徑
  CHECK 7 — 技能數與索引條目數一致
  CHECK 8 — 任務看板當前狀態 Metadata 純度
  CHECK 9 — 交接區 HEAD 審計狀態與合法範圍
  CHECK 10 — §X.Y 章節引用有效性
  CHECK 11 — §6.1 清單與自檢清單 E 節項目對應
  CHECK 12 — AUDIT-LOG 審查紀錄歷史有效性與 Pending Range 相容性
  CHECK 13 — 檔尾換行符
  CHECK 14 — 繁體中文環境下的簡體字與日文字元偵測
  CHECK 15 — 交接區 §5.1 的 commit hash 語境衝突
  CHECK 16 — 執行者檢查紀錄（EXEC-LOG）落後偵測
  CHECK 17 — Batch Spec 重放一致性
  CHECK 18 — audited-* tag 名實一致
  CHECK 19 — ADR-0013 §2C UTF-8 BOM 污染偵測
  CHECK 20 — 跨檔案規則追溯矩陣守衛 (Rule Traceability Matrix Guard)
  CHECK 21 — 機密防護與輸出安全守衛 (Secret Leak Guard)
  CHECK 22 — CI 供應鏈可重現性守衛 (CI Supply-Chain Reproducibility Guard)
  CHECK 23 — 傳輸能力與合約一致性守衛 (Transport Capability / Contract Exclusivity Guard)
  CHECK 24 — 活動狀態投影漂移守衛 (Active State Projection Drift Guard)
  CHECK 25 — 機械治理 v1 完整性守衛 (Mechanical Governance v1 Integrity Guard)
  CHECK 26 — M2 計畫與執行重放暨證據完整性守衛 (M2 Plan-vs-Actual / Evidence Integrity Replay Guard)

本腳本的檢查項來自 2026-08-29 的一次全庫實測掃描，每一項都曾實際命中過真實缺陷，不是憑空設計。
新增檢查項時，必須先確認該檢查在當前 repo 的誤報率，誤報多的檢查會讓人習慣忽略輸出。
允許清單中的每一筆都必須附理由。

實作注意事項（皆為 2026-08-29 首次執行時實際踩到的錯誤）：
  - special_trigger_routes 的值是相對於 repo 根目錄的路徑，不是相對於 SOP/
  - tags 的值是檔名陣列，不是單一字串
  - CHECK 3 必須追蹤 ``` 圍欄狀態，否則 code block 內的正規表示式
    會被誤判為 Markdown 連結。允許清單只用於「確實是連結但確實該保留」，
    解析錯誤要修解析，不得加例外繞過
"""

import os
import sys
import re
import json

sys.stdout.reconfigure(encoding='utf-8')
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def run_checks(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    as_if_committed = "--as-if-committed" in argv
    if as_if_committed:
        print("[MODE] 啟用 --as-if-committed 本地 commit 拓撲預演模式")
    total_checks = 26
    passed = 0
    failed = 0
    
    # ---------------------------------------------------------
    # CHECK 1: 控制字元
    # ---------------------------------------------------------
    print("CHECK 1 - 控制字元")
    c1_fails, _ = check_1_control_chars(repo_root)
    if len(c1_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c1_fails)} 命中")
        for fail in c1_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 2: Markdown 圍欄配對
    # ---------------------------------------------------------
    print("\nCHECK 2 - Markdown 圍欄配對")
    c2_fails, _ = check_2_markdown_fences(repo_root)
    if len(c2_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c2_fails)} 命中")
        for fail in c2_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 3: Markdown 相對連結有效性
    # ---------------------------------------------------------
    print("\nCHECK 3 - Markdown 相對連結有效性")
    c3_fails, c3_infos = check_3_markdown_links(repo_root)
    for info in c3_infos:
        print(f"  [INFO] {info}")

    if len(c3_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c3_fails)} 命中")
        for fail in c3_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 4: 三層 README 完整性
    # ---------------------------------------------------------
    print("\nCHECK 4 - 三層 README 完整性")
    c4_fails = []
    skills_dir = os.path.join(repo_root, "skills")
    skills = []
    
    for bucket in os.listdir(skills_dir):
        bucket_path = os.path.join(skills_dir, bucket)
        if os.path.isdir(bucket_path):
            for name in os.listdir(bucket_path):
                skill_path = os.path.join(bucket_path, name)
                if os.path.isdir(skill_path) and os.path.exists(os.path.join(skill_path, "SKILL.md")):
                    skills.append((bucket, name))
                    
    root_readme_path = os.path.join(repo_root, "README.md")
    skills_readme_path = os.path.join(skills_dir, "README.md")
    
    root_readme = ""
    if os.path.exists(root_readme_path):
        with open(root_readme_path, "r", encoding="utf-8") as f:
            root_readme = f.read()
            
    skills_readme = ""
    if os.path.exists(skills_readme_path):
        with open(skills_readme_path, "r", encoding="utf-8") as f:
            skills_readme = f.read()
            
    for bucket, name in skills:
        bucket_readme_path = os.path.join(skills_dir, bucket, "README.md")
        bucket_readme = ""
        if os.path.exists(bucket_readme_path):
            with open(bucket_readme_path, "r", encoding="utf-8") as f:
                bucket_readme = f.read()
                
        if f"/{bucket}/{name}/" not in root_readme:
            c4_fails.append(f"README.md:0  未收錄技能 {bucket}/{name}")
        if f"./{bucket}/{name}/" not in skills_readme:
            c4_fails.append(f"skills/README.md:0  未收錄技能 {bucket}/{name}")
        if f"{name}/" not in bucket_readme:
            c4_fails.append(f"skills/{bucket}/README.md:0  未收錄技能 {name}")

    if len(c4_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c4_fails)} 命中")
        for fail in c4_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 5: SOP_00A 路由目標存在性
    # ---------------------------------------------------------
    print("\nCHECK 5 - SOP_00A 路由目標存在性")
    c5_fails, c5_infos = check_5_sop_routes(repo_root)
    for info in c5_infos:
        print(f"  [INFO] {info}")
    if len(c5_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c5_fails)} 命中")
        for fail in c5_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 6: skills/ 底下不得殘留舊分層路徑
    # ---------------------------------------------------------
    print("\nCHECK 6 - skills/ 底下不得殘留舊分層路徑")
    c6_fails, c6_infos = check_6_old_hierarchy_paths(repo_root)
    for info in c6_infos:
        print(f"  [INFO] {info}")
    if len(c6_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c6_fails)} 命中")
        for fail in c6_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 7: 技能數與索引條目數一致
    # ---------------------------------------------------------
    print("\nCHECK 7 - 技能數與索引條目數一致")
    c7_fails = []
    
    index_count = 0
    if os.path.exists(skills_readme_path):
        with open(skills_readme_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("| **["):
                    index_count += 1
                    
    skill_count = len(skills)
    
    if index_count == skill_count:
        print("  [PASS] 命中 0 差異")
        passed += 1
    else:
        c7_fails.append(f"skills/README.md:0  技能數 ({skill_count}) 與索引條目數 ({index_count}) 不一致")
        print(f"  [FAIL] {len(c7_fails)} 命中")
        for fail in c7_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 8: 任務看板當前狀態 Metadata 純度
    # ---------------------------------------------------------
    print("\nCHECK 8 - 任務看板當前狀態 Metadata 純度")
    c8_fails, c8_infos = check_8_taskboard_head(repo_root, as_if_committed=as_if_committed)
    for info in c8_infos:
        print(f"  [INFO] {info}")
    if len(c8_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c8_fails)} 命中")
        for fail in c8_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 9: 交接區 HEAD 審計狀態與合法範圍
    # ---------------------------------------------------------
    print("\nCHECK 9 - 交接區 HEAD 審計狀態與合法範圍")
    c9_fails, c9_infos = check_9_handover_head(repo_root, as_if_committed=as_if_committed)
    for info in c9_infos:
        print(f"  [INFO] {info}")
    if len(c9_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c9_fails)} 命中")
        for fail in c9_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 10: §X.Y 章節引用有效性
    # ---------------------------------------------------------
    print("\nCHECK 10 - §X.Y 章節引用有效性")
    c10_fails, c10_infos = check_10_section_refs(repo_root)
    for info in c10_infos:
        print(f"  [INFO] {info}")
    if len(c10_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c10_fails)} 命中")
        for fail in c10_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 11: §6.1 清單與自檢清單 E 節項目對應
    # ---------------------------------------------------------
    print("\nCHECK 11 - §6.1 清單與自檢清單 E 節項目對應")
    c11_fails, c11_infos = check_11_selftest_correspondence(repo_root)
    for info in c11_infos:
        print(f"  [INFO] {info}")
    if len(c11_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c11_fails)} 命中")
        for fail in c11_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 12: AUDIT-LOG 審查紀錄歷史有效性與 Pending Range 相容性
    # ---------------------------------------------------------
    print("\nCHECK 12 - AUDIT-LOG 審查紀錄歷史有效性與 Pending Range 相容性")
    c12_fails, c12_infos = check_12_audit_log_cadence(repo_root)
    for info in c12_infos:
        print(f"  [INFO] {info}")
    if len(c12_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c12_fails)} 命中")
        for fail in c12_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 13: 檔尾換行符
    # ---------------------------------------------------------
    print("\nCHECK 13 - 檔尾換行符")
    c13_fails, c13_infos = check_13_trailing_newline(repo_root, strict=False)
    for line in format_check_13_summary(c13_fails, c13_infos):
        print(line)
    if len(c13_fails) == 0:
        passed += 1
    else:
        failed += 1

    # ---------------------------------------------------------
    # CHECK 14: 繁體中文環境下的簡體字與日文字元偵測
    # ---------------------------------------------------------
    print("\nCHECK 14 - 繁體中文環境下的簡體字與日文字元偵測")
    c14_fails, c14_infos = check_14_simplified_chinese(repo_root)
    for info in c14_infos:
        print(f"  [INFO] {info}")
    if len(c14_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c14_fails)} 命中")
        for fail in c14_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 15: 交接區 §5.1 的 commit hash 語境衝突
    # ---------------------------------------------------------
    print("\nCHECK 15 - 交接區 §5.1 的 commit hash 語境衝突")
    c15_fails, c15_infos = check_15_context_conflict(repo_root)
    for info in c15_infos:
        print(f"  [INFO] {info}")
    if len(c15_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c15_fails)} 命中")
        for fail in c15_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 16: 執行者檢查紀錄落後
    # ---------------------------------------------------------
    print("\nCHECK 16 - 執行者檢查紀錄落後")
    c16_fails, c16_infos = check_16_exec_log_cadence(repo_root)
    for info in c16_infos:
        print(f"  [INFO] {info}")
    if len(c16_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c16_fails)} 命中")
        for fail in c16_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # ---------------------------------------------------------
    # CHECK 17: Batch Spec 重放一致性
    # ---------------------------------------------------------
    print("\nCHECK 17 - Batch Spec 重放一致性")
    c17_fails, c17_infos = check_17_spec_replay(repo_root)
    for info in c17_infos:
        print(f"  [INFO] {info}")
    if len(c17_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c17_fails)} 命中")
        for fail in c17_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 18: audited-* tag 名實一致
    # ---------------------------------------------------------
    print("\nCHECK 18 - audited-* tag 名實一致")
    c18_fails, c18_infos = check_18_tag_integrity(repo_root)
    for info in c18_infos:
        print(f"  [INFO] {info}")
    if len(c18_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c18_fails)} 命中")
        for fail in c18_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 19: UTF-8 BOM 偵測
    # ---------------------------------------------------------
    print("\nCHECK 19 - UTF-8 BOM 偵測")
    c19_fails, c19_infos = check_19_utf8_bom(repo_root)
    for info in c19_infos:
        print(f"  [INFO] {info}")
    if len(c19_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c19_fails)} 命中")
        for fail in c19_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 20: Markdown 表格連續性
    # ---------------------------------------------------------
    print("\nCHECK 20 - Markdown 表格連續性")
    c20_fails, c20_infos = check_20_markdown_table_continuity(repo_root)
    for info in c20_infos:
        print(f"  [INFO] {info}")
    if len(c20_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c20_fails)} 命中")
        for fail in c20_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 21: 機密防護與輸出安全守衛
    # ---------------------------------------------------------
    print("\nCHECK 21: 機密防護與輸出安全守衛")
    c21_fails, c21_infos = check_21_secret_leak_guard(repo_root)
    for info in c21_infos:
        print(f"  [INFO] {info}")
    if len(c21_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c21_fails)} 命中")
        for fail in c21_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 22: CI 供應鏈可重現性守衛
    # ---------------------------------------------------------
    print("\nCHECK 22: CI 供應鏈可重現性守衛")
    c22_fails, c22_infos = check_22_ci_supply_chain(repo_root)
    for info in c22_infos:
        print(f"  [INFO] {info}")
    if len(c22_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c22_fails)} 命中")
        for fail in c22_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 23: 傳輸能力與合約一致性守衛
    # ---------------------------------------------------------
    print("\nCHECK 23: 傳輸能力與合約一致性守衛")
    c23_fails, c23_infos = check_23_transport_exclusivity_guard(repo_root)
    for info in c23_infos:
        print(f"  [INFO] {info}")
    if len(c23_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c23_fails)} 命中")
        for fail in c23_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 24: 活動狀態投影漂移守衛
    # ---------------------------------------------------------
    print("\nCHECK 24: 活動狀態投影漂移守衛")
    c24_fails, c24_infos = check_24_active_state_projection_guard(repo_root)
    for info in c24_infos:
        print(f"  [INFO] {info}")
    if len(c24_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c24_fails)} 命中")
        for fail in c24_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 25: 機械治理 v1 完整性守衛
    # ---------------------------------------------------------
    print("\nCHECK 25: 機械治理 v1 完整性守衛")
    c25_fails, c25_infos = check_25_mechanical_governance(repo_root)
    for info in c25_infos:
        print(f"  [INFO] {info}")
    if len(c25_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c25_fails)} 命中")
        for fail in c25_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 26: M2 計畫與執行重放暨證據完整性守衛
    # ---------------------------------------------------------
    print("\nCHECK 26: M2 計畫與執行重放暨證據完整性守衛")
    c26_fails, c26_infos = check_26_plan_actual_evidence_integrity(repo_root, as_if_committed=as_if_committed)
    for info in c26_infos:
        print(f"  [INFO] {info}")
    if len(c26_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c26_fails)} 命中")
        for fail in c26_fails:
            print(f"    {fail}")
        failed += 1

    # 總結
    # ---------------------------------------------------------
    print(f"\n========================================")
    print(f"總結: 通過 {passed} 項, 失敗 {failed} 項")
    print(f"========================================")
    
    if failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)



import subprocess

def get_git_heads(root, as_if_committed=False):
    env_head = os.environ.get("GIT_HEAD")
    env_prev = os.environ.get("GIT_HEAD_PREV")
    env_prev2 = os.environ.get("GIT_HEAD_PREV2")
    head = None
    prev = None
    prev2 = None
    try:
        if as_if_committed:
            head = "candidate"
            res_prev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True)
            if res_prev.returncode == 0:
                prev = res_prev.stdout.strip()
            res_prev2 = subprocess.run(["git", "rev-parse", "--short", "HEAD~1"], cwd=root, capture_output=True, text=True)
            if res_prev2.returncode == 0:
                prev2 = res_prev2.stdout.strip()
        else:
            res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True)
            if res.returncode == 0:
                head = res.stdout.strip()
            res2 = subprocess.run(["git", "rev-parse", "--short", "HEAD~1"], cwd=root, capture_output=True, text=True)
            if res2.returncode == 0:
                prev = res2.stdout.strip()
            res3 = subprocess.run(["git", "rev-parse", "--short", "HEAD~2"], cwd=root, capture_output=True, text=True)
            if res3.returncode == 0:
                prev2 = res3.stdout.strip()
    except Exception:
        pass
    if env_head:
        head = env_head
    if env_prev:
        prev = env_prev
    if env_prev2:
        prev2 = env_prev2
    return head, prev, prev2

def hashes_match(h1, h2):
    if not h1 or not h2:
        return False
    h1, h2 = h1.lower(), h2.lower()
    return h1 == h2 or h1.startswith(h2) or h2.startswith(h1)


def parse_macro_audit_verdict(summary: str) -> tuple[bool, str]:
    """
    Anchored structured verdict parser for Macro audit summary in AUDIT-LOG.md (B-109 M2 / CHECK 9).
    Returns (is_pass, canonical_verdict_str).

    Accepts:
    - Anchored canonical prefix '**核對通過' (e.g. '**核對通過**', '**核對通過（MACRO AUDIT = PASS...', '**核對通過。...')
    - Historical valid prefixes without markdown bold: '核對通過', '核對批' (for early historical rows)

    Explicitly rejects:
    - Any summary starting with '**核對不通過' or '核對不通過'
    - Any summary starting with '**Machine PASS' or 'Machine PASS'
    - Any summary starting with '**HOLD' or 'HOLD'
    - Any summary starting with '**NEEDS' or 'NEEDS'
    - Any arbitrary text containing 'PASS' or '通過' without anchored canonical prefix
    """
    if not isinstance(summary, str):
        return False, "INVALID_TYPE"
    s = summary.strip()

    # Explicitly reject non-pass indicators at start
    non_pass_prefixes = [
        "**核對不通過",
        "核對不通過",
        "**Machine PASS",
        "Machine PASS",
        "**HOLD",
        "HOLD",
        "**NEEDS",
        "NEEDS",
        "**內容核對通過，但 CI failure",
    ]
    for p in non_pass_prefixes:
        if s.startswith(p):
            return False, "HOLD_OR_REJECT"

    # Match canonical PASS prefixes
    if s.startswith("**核對通過"):
        if not s.startswith("**核對通過不通過"):
            return True, "PASS"

    # Historical entries in early AUDIT-LOG (before markdown bold was standardized)
    if s.startswith("核對通過") or s.startswith("核對批"):
        if not s.startswith("核對通過不通過"):
            return True, "PASS"

    return False, "NON_PASS"



# Known pending migration routes registry (exact key + exact target + rationale)
KNOWN_PENDING_MIGRATIONS = {
    "$$自動化_微型模型$$": {
        "target": "PENDING_MIGRATION:skills/agents/autoresearch-agent/SKILL.md",
        "task": "F-06",
        "rationale": "微型模型自動化研究 Agent 尚未遷移至 skills/agents/",
    },
    "$$LINE連線$$": {
        "target": "PENDING_MIGRATION:skills/platform/line-bot-zero-delay/SKILL.md",
        "task": "F-06",
        "rationale": "LINE Bot zero delay 尚未遷移至 skills/platform/",
    },
    "$$LINE連線: <自訂名稱>$$": {
        "target": "PENDING_MIGRATION:skills/platform/line-bot-zero-delay/SKILL.md",
        "task": "F-06",
        "rationale": "LINE Bot zero delay 帶參數路由尚未遷移至 skills/platform/",
    },
    "$$TG連線$$": {
        "target": "PENDING_MIGRATION:skills/platform/telegram-bot-cdp-bridge/SKILL.md",
        "task": "F-06",
        "rationale": "Telegram Bot CDP bridge 尚未遷移至 skills/platform/",
    },
}


def check_1_control_chars(root_dir=None):
    """CHECK 1 — 控制字元檢查。"""
    if root_dir is None:
        root_dir = repo_root
    fails = []
    infos = []
    for root, dirs, files in os.walk(root_dir):
        if any(p in root for p in [".git", "node_modules", "__pycache__", ".venv"]):
            continue
        for file in files:
            if file.endswith(".md") or file.endswith(".json"):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        for i, line in enumerate(f):
                            if chr(27) in line:
                                rel_path = os.path.relpath(filepath, root_dir).replace("\\", "/")
                                fails.append(f"{rel_path}:{i+1}  找到 ESC 控制字元")
                except Exception as e:
                    rel_path = os.path.relpath(filepath, root_dir).replace("\\", "/")
                    fails.append(f"{rel_path}:0  檔案讀取失敗: {e}")
    return fails, infos


def check_2_markdown_fences(root_dir=None):
    """CHECK 2 — Markdown 圍欄配對檢查。"""
    if root_dir is None:
        root_dir = repo_root
    fails = []
    infos = []
    for root, dirs, files in os.walk(root_dir):
        if any(p in root for p in [".git", "node_modules", "__pycache__", ".venv"]):
            continue
        for file in files:
            if file.endswith(".md"):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        lines = f.read().splitlines()
                        fence_count = sum(1 for l in lines if l.strip().startswith("```"))
                        if fence_count % 2 != 0:
                            rel_path = os.path.relpath(filepath, root_dir).replace("\\", "/")
                            fails.append(f"{rel_path}:0  圍欄數為奇數 ({fence_count})")
                except Exception as e:
                    rel_path = os.path.relpath(filepath, root_dir).replace("\\", "/")
                    fails.append(f"{rel_path}:0  檔案讀取失敗: {e}")
    return fails, infos


def check_5_sop_routes(root_dir=None):
    """CHECK 5 — SOP_00A 路由目標存在性與 PENDING_MIGRATION 白名單驗證。"""
    if root_dir is None:
        root_dir = repo_root
    fails = []
    infos = []
    sop_index_path = os.path.join(root_dir, "SOP", "SOP_00A_Master_Index.json")

    if not os.path.exists(sop_index_path):
        fails.append("SOP/SOP_00A_Master_Index.json:0  檔案不存在")
        return fails, infos

    try:
        with open(sop_index_path, "r", encoding="utf-8") as f:
            sop_data = json.load(f)

        routes = sop_data.get("special_trigger_routes", {})
        for key, val in routes.items():
            target = val.split("#")[0]
            if target.startswith("PENDING_MIGRATION:"):
                reg_entry = KNOWN_PENDING_MIGRATIONS.get(key)
                if reg_entry and reg_entry["target"] == target:
                    infos.append(f"略過已知未遷移路由: {key} -> {val} ({reg_entry['task']}: {reg_entry['rationale']})")
                    continue
                else:
                    fails.append(f"SOP/SOP_00A_Master_Index.json:0  未註冊的 PENDING_MIGRATION 路由: {key} -> {val}")
                    continue
            target_abs = os.path.normpath(os.path.join(root_dir, target))
            if not os.path.exists(target_abs):
                fails.append(f"SOP/SOP_00A_Master_Index.json:0  路由目標不存在: {val}")

        tags = sop_data.get("tags", {})
        seen_sop = set()
        for key, val_list in tags.items():
            for fname in val_list:
                if fname in seen_sop:
                    continue
                seen_sop.add(fname)
                target_abs = os.path.join(root_dir, "SOP", fname)
                if not os.path.exists(target_abs):
                    fails.append(f"SOP/SOP_00A_Master_Index.json:0  SOP 檔案不存在: {fname} (tag: {key})")
    except Exception as e:
        fails.append(f"SOP/SOP_00A_Master_Index.json:0  解析錯誤: {e}")

    return fails, infos


def check_6_old_hierarchy_paths(root_dir=None):
    """CHECK 6 — skills/ 底下不得殘留舊分層路徑。"""
    if root_dir is None:
        root_dir = repo_root
    fails = []
    infos = []
    skills_dir = os.path.join(root_dir, "skills")
    old_paths = ["01_Orchestrators", "02_Cognitive", "03_Execution", "05_Actions"]

    if not os.path.exists(skills_dir):
        return fails, infos

    for root, dirs, files in os.walk(skills_dir):
        if any(p in root for p in [".git", ".venv", "node_modules"]):
            continue
        for file in files:
            if file.endswith(".md"):
                filepath = os.path.join(root, file)
                rel_fp = os.path.relpath(filepath, root_dir).replace("\\", "/")

                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        lines = f.read().splitlines()
                        for i, line in enumerate(lines):
                            for op in old_paths:
                                if op in line:
                                    # Narrow contextual exception: only the known historical runtime migration note in json-to-flex-renderer
                                    if (rel_fp == "skills/platform/json-to-flex-renderer/SKILL.md" and
                                        "skills/03_Execution/line-bot-zero-delay/line-bot-project/" in line):
                                        context = "".join(lines[max(0, i-2):min(len(lines), i+3)])
                                        if "舊專案" in context and ("尚未遷移" in context or "runtime" in context):
                                            infos.append(f"略過已知殘留: {rel_fp}:{i+1} (原因: runtime 層尚未遷移，遷移完成後必須更新；見 docs/TASKBOARD.md F-06)")
                                            continue
                                    fails.append(f"{rel_fp}:{i+1}  殘留舊路徑: {op}")
                except Exception as e:
                    fails.append(f"{rel_fp}:0  檔案讀取失敗: {e}")

    return fails, infos


def format_check_13_summary(fails, infos):
    """回傳 CHECK 13 格式化輸出文字行清單，供 run_checks 與測試共同使用。"""
    lines = []
    for info in infos:
        lines.append(f"  [INFO] {info}")
    if len(fails) == 0:
        if len(infos) > 0:
            lines.append(f"  [ADVISORY] {len(infos)} observations (non-blocking by design)")
        else:
            lines.append("  [PASS] 0 命中")
    else:
        lines.append(f"  [FAIL] {len(fails)} 命中")
        for fail in fails:
            lines.append(f"    {fail}")
    return lines


def check_3_markdown_links(root_dir=None):
    """CHECK 3 — Markdown 相對連結有效性與本機路徑防護。"""
    if root_dir is None:
        root_dir = repo_root
    c3_fails = []
    c3_infos = []
    md_link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
    allowed_c3 = [
        ("skills/execution/playwright-automation/README.md", "skills/playwright-skill/API_REFERENCE.md")
    ]

    for root, dirs, files in os.walk(root_dir):
        if ".git" in root or ".venv" in root or "node_modules" in root:
            continue
        for file in files:
            if file.endswith(".md"):
                filepath = os.path.join(root, file)
                rel_fp = os.path.relpath(filepath, root_dir).replace("\\", "/")
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                        in_fence = False
                        for i, line in enumerate(lines):
                            if line.strip().startswith("```"):
                                in_fence = not in_fence
                                continue
                            if in_fence:
                                continue

                            no_inline = re.sub(r'`[^`]*`', '', line)
                            matches = md_link_pattern.findall(no_inline)

                            for text, link in matches:
                                if link.startswith("http") or link.startswith("mailto:") or "<" in link or ">" in link:
                                    continue
                                if link.startswith("file://") or re.match(r'^[a-zA-Z]:[/\\]', link) or link.startswith("/Users/") or link.startswith("/home/"):
                                    c3_fails.append(f"{rel_fp}:{i+1}  不得使用本機絕對路徑連結: {link}")
                                    continue
                                if link.startswith("#"):
                                    continue

                                target = link.split('#')[0]
                                if not target:
                                    continue

                                target_abs = os.path.normpath(os.path.join(root, target))
                                if not os.path.exists(target_abs):
                                    is_allowed = False
                                    for fp_match, link_match in allowed_c3:
                                        if rel_fp == fp_match and target == link_match:
                                            is_allowed = True
                                            c3_infos.append(f"略過已知失效連結: {rel_fp}:{i+1} -> {link} (原因: vendored 上游原文，依 ADR-0018 不改寫)")
                                            break
                                    if not is_allowed:
                                        c3_fails.append(f"{rel_fp}:{i+1}  目標不存在: {link}")
                except Exception as e:
                    c3_fails.append(f"{rel_fp}:0  檔案讀取失敗: {e}")
    return c3_fails, c3_infos


def check_8_taskboard_metadata_purity(root_dir=None, git_head=None, git_prev=None, git_prev2=None, as_if_committed=False):
    """CHECK 8 — 任務看板當前狀態 Metadata 純度、ACTIVE_MACRO_AUDITOR 與 NEXT_WORK 結構。

    驗證 TASKBOARD.md 的『最後更新』標記為活動看板狀態標記：
    1. 存在唯一的『最後更新』標記。
    2. 包含有效日期 (YYYY-MM-DD) 與當前工作階段/狀態描述。
    3. 不得包含 Git HEAD、checkpoint、commit、pending range (..) 或任何 commit hash。
       Git 與審計狀態單一事實來源由 Git HEAD、AUDIT-LOG 與交接區 §5.1 擁有，
       防止將 Git truth 重新複製回看板產生第二事實來源。

    驗證 TASKBOARD.md 的『NEXT_WORK』指標結構：
    1. 恰好存在一個『**NEXT_WORK**』標記。
    2. 值只能為合法 task ID 或 NONE。
    3. pointer 本身不得保存 Git HEAD、checkpoint、commit hash、commit range 或 CI run ID。
    4. 若為 task ID，必須在 TASKBOARD 恰好存在一列任務定義。
    5. 不得指向已完成或可封存的任務。
    6. 若為 NONE，TASKBOARD 不得仍存在待辦、進行中或待裁決之 active work。

    驗證 TASKBOARD.md 的『ACTIVE_MACRO_AUDITOR』指標結構：
    1. 恰好存在一個『**ACTIVE_MACRO_AUDITOR**』標記。
    2. 值不得為空。
    3. marker 本身不得包含 Git truth（HEAD、checkpoint、commit、commit range、commit hash 或 CI run ID）。
    """
    if root_dir is None: root_dir = repo_root
    fails = []
    infos = []
    tb_path = os.path.join(root_dir, "docs", "TASKBOARD.md")
    if not os.path.exists(tb_path):
        fails.append("docs/TASKBOARD.md:0  檔案不存在")
        return fails, infos
    try:
        with open(tb_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        fails.append(f"docs/TASKBOARD.md:0  讀取失敗: {e}")
        return fails, infos

    # ---------------------------------------------------------
    # Part 1: 最後更新標記檢驗
    # ---------------------------------------------------------
    markers = []
    for idx, line in enumerate(lines, 1):
        if "**最後更新**：" in line:
            markers.append((idx, line.strip()))

    if len(markers) == 0:
        fails.append("docs/TASKBOARD.md:0  未找到『最後更新』標記")
    elif len(markers) > 1:
        fails.append(f"docs/TASKBOARD.md: 找到多個『最後更新』標記 (共 {len(markers)} 個)")
    else:
        line_no, marker_text = markers[0]
        payload = marker_text.split("**最後更新**：", 1)[1].strip()

        # 1. 必須包含有效日期 (YYYY-MM-DD)
        if not re.search(r"\b\d{4}-\d{2}-\d{2}\b", payload):
            fails.append(f"docs/TASKBOARD.md:{line_no}  『最後更新』標記缺少有效日期 (格式: YYYY-MM-DD)")

        # 2. 必須包含工作階段或當前狀態描述
        desc = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", payload).strip(" ，,、\t")
        if not desc:
            fails.append(f"docs/TASKBOARD.md:{line_no}  『最後更新』標記缺少工作階段或當前狀態描述")

        # 3. 不得包含 Git HEAD / commit / checkpoint / range
        if re.search(r"\bHEAD\b", payload, re.IGNORECASE):
            fails.append(f"docs/TASKBOARD.md:{line_no}  『最後更新』標記不得包含 HEAD 關鍵字 (違反 Metadata Purity，Git truth 由 Git/AUDIT-LOG/§5.1 擁有)")

        if re.search(r"\b(checkpoint|commit)\b", payload, re.IGNORECASE):
            fails.append(f"docs/TASKBOARD.md:{line_no}  『最後更新』標記不得包含 checkpoint/commit 關鍵字")

        if ".." in payload:
            fails.append(f"docs/TASKBOARD.md:{line_no}  『最後更新』標記不得包含 commit range (..)")

        # 4. 不得保存 7-40 位的十六進位 commit hash (反引號包住或純英數 hex)
        hex_in_backticks = re.findall(r"`([0-9a-fA-F]{7,40})`", payload)
        bare_hex_hashes = re.findall(r"\b(?=[0-9a-fA-F]*[a-fA-F])([0-9a-fA-F]{7,40})\b", payload)
        all_found_hashes = set(hex_in_backticks + bare_hex_hashes)
        if all_found_hashes:
            fails.append(f"docs/TASKBOARD.md:{line_no}  『最後更新』標記不得保存 Git commit hash: {', '.join(sorted(all_found_hashes))}")

    # ---------------------------------------------------------
    # Part 2: NEXT_WORK 指標結構檢驗
    # ---------------------------------------------------------
    nw_markers = []
    for idx, line in enumerate(lines, 1):
        m = re.match(r"^\s*(?:[-*]\s*)?\*\*NEXT_WORK\*\*[:：]\s*(.*?)\s*$", line)
        if m:
            nw_markers.append((idx, line.strip(), m.group(1).strip()))

    if len(nw_markers) == 0:
        fails.append("docs/TASKBOARD.md:0  未找到『NEXT_WORK』標記")
    elif len(nw_markers) > 1:
        fails.append(f"docs/TASKBOARD.md: 找到多個『NEXT_WORK』標記 (共 {len(nw_markers)} 個)")
    else:
        nw_line_no, nw_line_text, raw_payload = nw_markers[0]
        nw_payload = raw_payload.strip()

        # 5. pointer 本身不得保存 Git HEAD、checkpoint、commit hash、CI run ID、range
        if re.search(r"\bHEAD\b", nw_payload, re.IGNORECASE):
            fails.append(f"docs/TASKBOARD.md:{nw_line_no}  『NEXT_WORK』標記不得包含 HEAD 關鍵字")
        if re.search(r"\b(checkpoint|commit)\b", nw_payload, re.IGNORECASE):
            fails.append(f"docs/TASKBOARD.md:{nw_line_no}  『NEXT_WORK』標記不得包含 checkpoint/commit 關鍵字")
        if ".." in nw_payload:
            fails.append(f"docs/TASKBOARD.md:{nw_line_no}  『NEXT_WORK』標記不得包含 commit range (..)")
        if re.search(r"\bRun\s*#?\d+\b", nw_payload, re.IGNORECASE):
            fails.append(f"docs/TASKBOARD.md:{nw_line_no}  『NEXT_WORK』標記不得包含 CI run ID")
        hex_hashes = re.findall(r"`([0-9a-fA-F]{7,40})`", nw_payload) + re.findall(r"\b(?=[0-9a-fA-F]*[a-fA-F])([0-9a-fA-F]{7,40})\b", nw_payload)
        if hex_hashes:
            fails.append(f"docs/TASKBOARD.md:{nw_line_no}  『NEXT_WORK』標記不得保存 Git commit hash")

        # 解析 TASKBOARD 中所有任務資料列（正規任務 ID 格式：^[A-G]-\d{2,}$）
        task_rows = {}
        all_active_tasks = []
        ALLOWED_ACTIVE_STATUSES = {"待辦", "進行中", "待裁決"}
        for idx, line in enumerate(lines, 1):
            line_s = line.strip()
            if not line_s.startswith("|"):
                continue
            parts = [p.strip() for p in line_s.split("|")]
            if len(parts) >= 3:
                tid = parts[1]
                status = parts[2]
                if tid in ("ID", "---", "#", "事故編號") or set(tid) <= {"-", ":", " "}:
                    continue
                if re.match(r"^[A-G]-\d{2,}$", tid):
                    task_rows.setdefault(tid, []).append((idx, status, line_s))
                    clean_st = status.strip("` \t")
                    if clean_st in ALLOWED_ACTIVE_STATUSES or any(
                        clean_st.startswith(f"{act} ")
                        or clean_st.startswith(f"{act}/")
                        or clean_st.startswith(f"{act}（")
                        or clean_st.startswith(f"{act}(")
                        for act in ALLOWED_ACTIVE_STATUSES
                    ):
                        all_active_tasks.append(tid)

        clean_payload = nw_payload.strip("` \t")

        # 2. 值只能為合法 task ID (格式: ^[A-G]-\d{2,}$) 或 NONE
        if clean_payload == "NONE":
            # 6. NEXT_WORK = NONE 時，TASKBOARD 不得仍存在待辦、進行中、待裁決 active work
            if all_active_tasks:
                fails.append(f"docs/TASKBOARD.md:{nw_line_no}  NEXT_WORK 為 NONE 但任務看板仍存在 active work (共 {len(all_active_tasks)} 項: {', '.join(all_active_tasks[:5])})")
            else:
                infos.append(f"docs/TASKBOARD.md:{nw_line_no}  NEXT_WORK = NONE (看板無 active work)")
        else:
            # 檢查 task ID 命名空間格式（嚴格限制為 HH.AI_v2 正式 task namespace A-G）
            if not re.match(r"^[A-G]-\d{2,}$", clean_payload):
                fails.append(f"docs/TASKBOARD.md:{nw_line_no}  『NEXT_WORK』值只能為合法 task ID (格式: ^[A-G]-\\d{{2,}}$) 或 NONE (當前值: '{nw_payload}')")
            else:
                # 3. task ID 必須在 TASKBOARD 恰好存在一列
                if clean_payload not in task_rows:
                    fails.append(f"docs/TASKBOARD.md:{nw_line_no}  『NEXT_WORK』指向不存在的任務 ID: {clean_payload}")
                elif len(task_rows[clean_payload]) > 1:
                    fails.append(f"docs/TASKBOARD.md:{nw_line_no}  『NEXT_WORK』指向的任務 ID 存在多個定義: {clean_payload} (共 {len(task_rows[clean_payload])} 列)")
                else:
                    target_line_no, target_status, _ = task_rows[clean_payload][0]
                    clean_target_status = target_status.strip("` \t")
                    # 4. 白名單限制：目標狀態必須明確屬於待辦、進行中、待裁決
                    if clean_target_status not in ALLOWED_ACTIVE_STATUSES and not any(
                        clean_target_status.startswith(f"{act} ")
                        or clean_target_status.startswith(f"{act}/")
                        or clean_target_status.startswith(f"{act}（")
                        or clean_target_status.startswith(f"{act}(")
                        for act in ALLOWED_ACTIVE_STATUSES
                    ):
                        fails.append(f"docs/TASKBOARD.md:{nw_line_no}  『NEXT_WORK』目標任務狀態不合法 (指向 {clean_payload}，狀態: '{target_status}'；只允許: 待辦、進行中、待裁決)")
                    else:
                        infos.append(f"docs/TASKBOARD.md:{nw_line_no}  NEXT_WORK = {clean_payload} (狀態: {target_status})")

    # ---------------------------------------------------------
    # Part 3: ACTIVE_MACRO_AUDITOR 指標結構檢驗
    # ---------------------------------------------------------
    ama_markers = []
    for idx, line in enumerate(lines, 1):
        m = re.match(r"^\s*(?:[-*]\s*)?\*\*ACTIVE_MACRO_AUDITOR\*\*[:：]\s*(.*?)\s*$", line)
        if m:
            ama_markers.append((idx, line.strip(), m.group(1).strip()))

    if len(ama_markers) == 0:
        fails.append("docs/TASKBOARD.md:0  未找到『ACTIVE_MACRO_AUDITOR』標記")
    elif len(ama_markers) > 1:
        fails.append(f"docs/TASKBOARD.md: 找到多個『ACTIVE_MACRO_AUDITOR』標記 (共 {len(ama_markers)} 個)")
    else:
        ama_line_no, ama_line_text, raw_ama_payload = ama_markers[0]
        ama_payload = raw_ama_payload.strip()

        # 2. 值不得為空
        if not ama_payload:
            fails.append(f"docs/TASKBOARD.md:{ama_line_no}  『ACTIVE_MACRO_AUDITOR』標記值不得為空")
        else:
            # 6. 不得保存 Git truth: HEAD, checkpoint, commit, commit range, hex commit hash, CI run ID
            if re.search(r"\bHEAD\b", ama_payload, re.IGNORECASE):
                fails.append(f"docs/TASKBOARD.md:{ama_line_no}  『ACTIVE_MACRO_AUDITOR』標記不得包含 HEAD 關鍵字")
            if re.search(r"\b(checkpoint|commit)\b", ama_payload, re.IGNORECASE):
                fails.append(f"docs/TASKBOARD.md:{ama_line_no}  『ACTIVE_MACRO_AUDITOR』標記不得包含 checkpoint/commit 關鍵字")
            if ".." in ama_payload:
                fails.append(f"docs/TASKBOARD.md:{ama_line_no}  『ACTIVE_MACRO_AUDITOR』標記不得包含 commit range (..)")
            if re.search(r"\bRun\s*#?\d+\b", ama_payload, re.IGNORECASE):
                fails.append(f"docs/TASKBOARD.md:{ama_line_no}  『ACTIVE_MACRO_AUDITOR』標記不得包含 CI run ID")
            ama_hex_hashes = re.findall(r"`([0-9a-fA-F]{7,40})`", ama_payload) + re.findall(r"\b(?=[0-9a-fA-F]*[a-fA-F])([0-9a-fA-F]{7,40})\b", ama_payload)
            if ama_hex_hashes:
                fails.append(f"docs/TASKBOARD.md:{ama_line_no}  『ACTIVE_MACRO_AUDITOR』標記不得保存 Git commit hash")

            if not any(f.startswith(f"docs/TASKBOARD.md:{ama_line_no}") for f in fails):
                infos.append(f"docs/TASKBOARD.md:{ama_line_no}  ACTIVE_MACRO_AUDITOR = {ama_payload}")

    return fails, infos

# Backward compatibility alias
check_8_taskboard_head = check_8_taskboard_metadata_purity


def check_9_handover_head(root_dir=None, git_head=None, git_prev=None, git_prev2=None, as_if_committed=False, git_ancestry=None):
    """CHECK 9 — 交接區 HEAD 審計狀態與合法範圍。

    驗證 semantic authority relationship：
    1. refactor-backlog.md §5.1 存在唯一『上次核對通過的 HEAD』checkpoint。
    2. checkpoint 在 AUDIT-LOG.md 中存在合法審查紀錄且結論為 Macro PASS / 核對通過。
    3. checkpoint 存在於 Git 歷史且為 HEAD 的祖先 commit（或 HEAD 自己）。
    4. checkpoint 等於 AUDIT-LOG 中最新且屬 HEAD ancestry 的 Macro PASS commit。
    5. checkpoint 之後可有任意數量 pending/repair commits，無固定數量上限。
    6. candidate / current HEAD 若未經 Macro PASS 裁決，不得自稱為 checkpoint。
    """
    if root_dir is None: root_dir = repo_root
    fails = []
    infos = []
    bl_path = os.path.join(root_dir, "docs", "refactor-backlog.md")
    if not os.path.exists(bl_path):
        fails.append("docs/refactor-backlog.md:0  檔案不存在")
        return fails, infos
    try:
        with open(bl_path, "r", encoding="utf-8") as f:
            bl_content = f.read()
    except Exception as e:
        fails.append(f"docs/refactor-backlog.md:0  讀取失敗: {e}")
        return fails, infos

    # 1. 存在唯一 checkpoint
    checkpoint_matches = re.findall(r"^上次核對通過的 HEAD：\s*`?([0-9a-fA-F]+)`?", bl_content, re.M)
    if not checkpoint_matches:
        fails.append("docs/refactor-backlog.md:0  未找到『上次核對通過的 HEAD』標記")
        return fails, infos
    if len(checkpoint_matches) > 1:
        fails.append(f"docs/refactor-backlog.md: 找到多個『上次核對通過的 HEAD』標記 (共 {len(checkpoint_matches)} 個)")
        return fails, infos

    ho_hash = checkpoint_matches[0].lower()

    # 2. 讀取 docs/AUDIT-LOG.md 驗證審查紀錄與 Macro PASS verdict
    al_path = os.path.join(root_dir, "docs", "AUDIT-LOG.md")
    if not os.path.exists(al_path):
        fails.append("docs/AUDIT-LOG.md:0  檔案不存在")
        return fails, infos
    try:
        with open(al_path, "r", encoding="utf-8") as f:
            al_content = f.read()
    except Exception as e:
        fails.append(f"docs/AUDIT-LOG.md:0  讀取失敗: {e}")
        return fails, infos

    al_table_content = al_content.split("## CI 歷史事故歸檔專區")[0]
    audit_rows = []
    for line in al_table_content.splitlines():
        line = line.strip()
        if line.startswith("|") and not line.startswith("|---") and "批次 commit" not in line:
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) >= 4:
                c_hash = parts[0].lower()
                if c_hash == "bootstrap":
                    continue
                summary = parts[3]
                is_pass, _ = parse_macro_audit_verdict(summary)
                audit_rows.append((c_hash, is_pass, summary))

    checkpoint_row = None
    for c_hash, is_pass, summary in audit_rows:
        if hashes_match(c_hash, ho_hash):
            checkpoint_row = (c_hash, is_pass, summary)
            break

    if checkpoint_row is None:
        fails.append(f"docs/refactor-backlog.md: 上次核對通過的 HEAD ({ho_hash}) 在 docs/AUDIT-LOG.md 中未找到審查紀錄")
    elif not checkpoint_row[1]:
        fails.append(f"docs/refactor-backlog.md: 上次核對通過的 HEAD ({ho_hash}) 在 docs/AUDIT-LOG.md 中的結論非 Macro PASS (現為: {checkpoint_row[2][:30]})")

    # 3. 取得 Git 歷史 / Ancestry
    ancestry = []
    if git_ancestry is not None:
        ancestry = [c.lower() for c in git_ancestry]
    elif _in_git_repo(root_dir):
        rc, out, _ = _git(root_dir, ["rev-list", "HEAD"])
        if rc == 0:
            ancestry = [line.strip().lower() for line in out.splitlines() if line.strip()]
            if as_if_committed:
                ancestry = ["candidate"] + ancestry
    else:
        raw_list = [x.lower() for x in [git_head, git_prev, git_prev2] if x]
        if as_if_committed and "candidate" not in raw_list:
            raw_list = ["candidate"] + raw_list
        ancestry = raw_list

    if not ancestry:
        fails.append("docs/refactor-backlog.md: 無法取得 git 歷史資訊 (ancestry)，判定 FAIL")
        return fails, infos

    current_head = ancestry[0]

    # 4. candidate / current HEAD 若沒有既存 Macro PASS evidence，不得自稱 checkpoint (Shape G)
    if current_head == "candidate" and hashes_match("candidate", ho_hash):
        fails.append(f"docs/refactor-backlog.md: 上次核對通過的 HEAD ({ho_hash}) 不得為 candidate 自己")
        return fails, infos
    if hashes_match(current_head, ho_hash):
        if checkpoint_row is None or not checkpoint_row[1]:
            fails.append(f"docs/refactor-backlog.md: 當前 HEAD ({current_head}) 未經 Macro PASS 裁決，不得自稱為 checkpoint")
            return fails, infos

    # 5. checkpoint 必須存在於 Git 歷史且為 HEAD 的 ancestor (Shape F)
    checkpoint_ancestry_idx = None
    for idx, c in enumerate(ancestry):
        if hashes_match(c, ho_hash):
            checkpoint_ancestry_idx = idx
            break

    if checkpoint_ancestry_idx is None:
        fails.append(f"docs/refactor-backlog.md: 上次核對通過的 HEAD ({ho_hash}) 不存在於當前 Git 歷史或非 HEAD 的祖先 commit")
        return fails, infos

    # 6. checkpoint 必須等於 AUDIT-LOG 中最新且屬 HEAD ancestry 的 Macro PASS commit (Shape E)
    latest_pass_in_ancestry = None
    for c in ancestry:
        if c == "candidate":
            continue
        for a_hash, a_is_pass, _ in audit_rows:
            if a_is_pass and hashes_match(c, a_hash):
                latest_pass_in_ancestry = c
                break
        if latest_pass_in_ancestry is not None:
            break

    if latest_pass_in_ancestry is not None:
        if not hashes_match(ho_hash, latest_pass_in_ancestry):
            fails.append(f"docs/refactor-backlog.md: 上次核對通過的 HEAD ({ho_hash}) 已過期；AUDIT-LOG 存在更晚的 Macro PASS ancestor commit ({latest_pass_in_ancestry})")

    pending_count = checkpoint_ancestry_idx
    infos.append(f"上次核對通過的 checkpoint: {ho_hash} (PASS), pending commits in range: {pending_count}")

    return fails, infos

def check_10_section_refs(root_dir=None):
    if root_dir is None: root_dir = repo_root
    fails = []
    infos = []
    target_files = []
    for d in ['.claude/rules', '.agents/rules']:
        dirpath = os.path.join(root_dir, d)
        if os.path.isdir(dirpath):
            for f in os.listdir(dirpath):
                if f.endswith('.md'):
                    target_files.append(os.path.join(dirpath, f))
    for f in ['PRINCIPLES.md', 'AGENTS.md']:
        fpath = os.path.join(root_dir, f)
        if os.path.exists(fpath):
            target_files.append(fpath)

    heading_cache = {}
    def get_headings(abs_p):
        if abs_p in heading_cache:
            return heading_cache[abs_p]
        if not os.path.exists(abs_p):
            heading_cache[abs_p] = None
            return None
        hdgs = set()
        try:
            with open(abs_p, 'r', encoding='utf-8') as f:
                for line in f:
                    m = re.match(r'^#+\s+([0-9]+[a-z]?(?:\.[0-9]+[a-z]?)*)', line.strip())
                    if m:
                        hdgs.add(m.group(1))
        except Exception as e:
            heading_cache[abs_p] = e
            return e
        if abs_p.replace('\\', '/').endswith('docs/refactor-backlog.md'):
            hdgs.add('5')
        heading_cache[abs_p] = hdgs
        return hdgs

    def resolve_target(rel_src, line, sec, sec_pos):
        if sec == '5' or sec.startswith('5.'):
            if any(k in line for k in ['refactor-backlog', '交接區', 'checkpoint', 'pending']):
                return 'docs/refactor-backlog.md'

        before = line[:sec_pos].rstrip()
        matches = list(re.finditer(r'(`?([a-zA-Z0-9_\-\./]+\.md)`?|PRINCIPLES|交接區|SOP_14)', before, re.IGNORECASE))
        if matches:
            raw_orig = matches[-1].group(1).strip('`')
            raw = raw_orig.lower()
            if not any(k in raw for k in ['taskboard', 'audit-log', 'exec-log', 'auditor-selftest']):
                if raw in ['principles.md', 'principles']: return 'PRINCIPLES.md'
                if raw in ['agents.md']: return 'AGENTS.md'
                if raw in ['auditor-protocol.md', '.claude/rules/auditor-protocol.md']: return '.claude/rules/auditor-protocol.md'
                if raw in ['prompt-preflight.md', '.agents/rules/prompt-preflight.md']: return '.agents/rules/prompt-preflight.md'
                if raw in ['role-boundaries.md', '.agents/rules/role-boundaries.md']: return '.agents/rules/role-boundaries.md'
                if raw in ['git-and-reporting.md', '.agents/rules/git-and-reporting.md']: return '.agents/rules/git-and-reporting.md'
                if raw in ['refactor-backlog.md', 'docs/refactor-backlog.md', '交接區']: return 'docs/refactor-backlog.md'
                if raw in ['sop_14']: return 'SOP/SOP_14_Rigorous_Verification_and_Audit_Protocol.md'
                if raw in ['handover.md', 'docs/handover.md']:
                    return 'docs/HANDOVER.md'
                if 'handover-pre-router-568209e' in raw:
                    return 'docs/archive/handover/HANDOVER-pre-router-568209e.md'
                for cand in [
                    os.path.join(root_dir, raw_orig),
                    os.path.join(root_dir, raw),
                    os.path.join(root_dir, os.path.dirname(rel_src), raw_orig),
                    os.path.join(root_dir, os.path.dirname(rel_src), raw),
                    os.path.join(root_dir, ".agents", "rules", raw_orig),
                    os.path.join(root_dir, ".agents", "rules", raw),
                    os.path.join(root_dir, ".claude", "rules", raw_orig),
                    os.path.join(root_dir, ".claude", "rules", raw),
                ]:
                    norm_p = os.path.normpath(cand).replace('\\', '/')
                    if os.path.exists(norm_p) and os.path.isfile(norm_p):
                        return os.path.relpath(norm_p, root_dir).replace('\\', '/')

        if rel_src.endswith('auditor-selftest.md'):
            return '.claude/rules/auditor-protocol.md'

        cur_abs = os.path.join(root_dir, rel_src)
        cur_hdgs = get_headings(cur_abs)
        if isinstance(cur_hdgs, set) and sec in cur_hdgs:
            return rel_src

        if 'refactor-backlog' in line or '交接區' in line:
            return 'docs/refactor-backlog.md'
        if 'PRINCIPLES' in line:
            return 'PRINCIPLES.md'
        if 'auditor-protocol' in line:
            return '.claude/rules/auditor-protocol.md'
        if 'role-boundaries' in line:
            return '.agents/rules/role-boundaries.md'
        if 'prompt-preflight' in line:
            return '.agents/rules/prompt-preflight.md'
        if 'git-and-reporting' in line:
            return '.agents/rules/git-and-reporting.md'
        if 'SOP_14' in line:
            return 'SOP/SOP_14_Rigorous_Verification_and_Audit_Protocol.md'
        if 'handover-pre-router-568209e' in line.lower():
            return 'docs/archive/handover/HANDOVER-pre-router-568209e.md'
        if 'HANDOVER' in line:
            return 'docs/HANDOVER.md'

        return None

    cross_file_indicators = [
        'PRINCIPLES.md', 'auditor-protocol.md', 'AGENTS.md', 'auditor-selftest.md',
        'prompt-preflight.md', 'role-boundaries.md', 'refactor-backlog.md',
        'TASKBOARD', 'HANDOVER', 'AUDIT-LOG', '交接區', 'SOP_', 'ADR-'
    ]

    for fpath in target_files:
        rel_fp = os.path.relpath(fpath, root_dir).replace("\\", "/")
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        except Exception as e:
            fails.append(f"{rel_fp}:0  檔案讀取失敗: {e}")
            continue

        headings = set()
        for l in lines:
            m = re.match(r'^#+\s+([0-9]+[a-z]?(?:\.[0-9]+[a-z]?)*)', l.strip())
            if m:
                headings.add(m.group(1))
        if rel_fp.endswith('docs/refactor-backlog.md'):
            headings.add('5')

        has_numeric_headings = len(headings) > 0

        for i, line in enumerate(lines, 1):
            refs = re.findall(r'§([0-9]+[a-z]?(?:\.[0-9]+[a-z]?)*)', line)
            if not refs:
                continue
            is_cross = (not has_numeric_headings) or any(ind in line for ind in cross_file_indicators)
            for m in re.finditer(r'§([0-9]+[a-z]?(?:\.[0-9]+[a-z]?)*)', line):
                sec = m.group(1)
                sec_pos = m.start()
                if not is_cross:
                    if sec not in headings:
                        fails.append(f"{rel_fp}:{i}  找不到章節標題: §{sec}")
                else:
                    tgt = resolve_target(rel_fp, line, sec, sec_pos)
                    if tgt is None:
                        fails.append(f"{rel_fp}:{i}  無法確定性解析跨檔案引用目標: §{sec}")
                    else:
                        tgt_abs = os.path.join(root_dir, tgt)
                        hdgs = get_headings(tgt_abs)
                        if isinstance(hdgs, Exception):
                            fails.append(f"{rel_fp}:{i}  目標檔案讀取失敗 ({tgt}): {hdgs}")
                        elif hdgs is None:
                            fails.append(f"{rel_fp}:{i}  目標檔案不存在 ({tgt}): §{sec}")
                        elif sec not in hdgs:
                            fails.append(f"{rel_fp}:{i}  目標檔案 ({tgt}) 找不到章節標題: §{sec}")
                        else:
                            infos.append(f"{rel_fp}:{i}  跨檔案引用: §{sec} -> {tgt}")

    return fails, infos

def check_11_selftest_correspondence(root_dir=None):
    if root_dir is None: root_dir = repo_root
    fails = []
    infos = []
    proto_path = os.path.join(root_dir, ".claude", "rules", "auditor-protocol.md")
    selftest_path = os.path.join(root_dir, ".claude", "rules", "auditor-selftest.md")
    if not os.path.exists(proto_path) or not os.path.exists(selftest_path):
        fails.append("規則檔案不存在，無法進行 §6.1-selftest 比對")
        return fails, infos

    try:
        with open(proto_path, "r", encoding="utf-8") as f:
            proto_content = f.read()
        with open(selftest_path, "r", encoding="utf-8") as f:
            selftest_content = f.read()
    except Exception as e:
        fails.append(f"規則檔案讀取失敗: {e}")
        return fails, infos

    m_proto = re.search(r"### 6\.1 每份提示詞的必備要素(.*?)(?=### 6\.2|\Z)", proto_content, re.S)
    if not m_proto:
        fails.append(".claude/rules/auditor-protocol.md: 未找到 ### 6.1 章節")
        return fails, infos
    proto_section = m_proto.group(1)

    proto_items = {}
    for m in re.finditer(r"(?:^|\n)([0-9]+)\.\s+(.*?)(?=(?:\n[0-9]+\.|\Z))", proto_section, re.S):
        num = int(m.group(1))
        text = m.group(2).strip()
        proto_items[num] = text

    m_self = re.search(r"## E\. 交付(.*?)(?=## F\.|\Z)", selftest_content, re.S)
    if not m_self:
        fails.append(".claude/rules/auditor-selftest.md: 未找到 ## E. 交付 章節")
        return fails, infos
    e_section = m_self.group(1)

    e_items = {}
    for m in re.finditer(r"-\s+\[\s*\]\s+(E[0-9]+)\s+(.*?)(?=(?:\n-\s+\[|\Z))", e_section, re.S):
        eid = m.group(1)
        etext = m.group(2).strip()
        e_items[eid] = etext

    mapped_proto_nums = set()
    for eid, etext in e_items.items():
        ref_nums = [int(x) for x in re.findall(r"§6\.1-([0-9]+)", etext)]
        for rnum in ref_nums:
            mapped_proto_nums.add(rnum)
            if rnum not in proto_items:
                fails.append(f".claude/rules/auditor-selftest.md: {eid} 指向不存在的 §6.1-{rnum}")

    for pnum in sorted(proto_items.keys()):
        if pnum not in mapped_proto_nums:
            fails.append(f".claude/rules/auditor-protocol.md: §6.1 第 {pnum} 項在 auditor-selftest.md E 節中無對應項目")

    if 8 in proto_items and "AUDIT-LOG" in proto_items[8]:
        e8_has_audit = any("AUDIT-LOG" in text for eid, text in e_items.items() if "§6.1-8" in text)
        if not e8_has_audit:
            fails.append(".claude/rules/auditor-selftest.md: E8 缺少 AUDIT-LOG 更新項目（與 §6.1-8 不一致）")

    return fails, infos

def check_12_audit_log_cadence(root_dir=None, git_count=None, git_ancestry=None):
    """CHECK 12 — AUDIT-LOG 審查紀錄歷史有效性與 Pending Range 相容性。

    規格：
    1. docs/AUDIT-LOG.md 必須存在。
    2. 必須能解析出至少一個合法 audit row，BOOTSTRAP 例外跳過。
    3. 最新非 BOOTSTRAP audit row commit 必須存在於目前 HEAD ancestry。
       若 latest audit hash 不存在或不屬於目前 Git history（ghost history），即為 FAIL。
    4. 若 latest audit commit 為 HEAD 的 ancestor：
       允許存在任意合法 pending-audit range（M3 repair commits 等），
       不以 pending commit count 作為 failure threshold。
    5. 顯示 pending commits 數量資訊以供審計生命週期參考。
    """
    if root_dir is None: root_dir = repo_root
    fails = []
    infos = []
    al_path = os.path.join(root_dir, "docs", "AUDIT-LOG.md")
    if not os.path.exists(al_path):
        fails.append("docs/AUDIT-LOG.md:0  檔案不存在")
        return fails, infos
    try:
        with open(al_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        fails.append(f"docs/AUDIT-LOG.md:0  讀取失敗: {e}")
        return fails, infos

    rows = re.findall(r"^\|\s*([0-9a-fA-F]+|BOOTSTRAP)\s*\|", content, re.M)
    if not rows:
        fails.append("docs/AUDIT-LOG.md:0  未找到自我審查檢查點紀錄列")
        return fails, infos
    if len(rows) == 1 and rows[0] == "BOOTSTRAP":
        infos.append("docs/AUDIT-LOG.md 僅有首列 BOOTSTRAP，跳過檢查")
        return fails, infos

    latest_hash = rows[-1]
    if latest_hash == "BOOTSTRAP":
        infos.append("docs/AUDIT-LOG.md 最新列為 BOOTSTRAP，跳過檢查")
        return fails, infos

    # 取得 Git 歷史 / Ancestry 比對
    if git_ancestry is not None:
        ancestry = [c.lower() for c in git_ancestry]
        if not ancestry:
            fails.append(f"docs/AUDIT-LOG.md: 提供之 git_ancestry 為空，無法驗證審查歷史 (hash={latest_hash})")
            return fails, infos
        match_idx = None
        for idx, c in enumerate(ancestry):
            if hashes_match(c, latest_hash):
                match_idx = idx
                break

        if match_idx is None:
            fails.append(f"docs/AUDIT-LOG.md: 最新審查紀錄 ({latest_hash}) 不存在於目前 Git HEAD 歷史 (ancestors) 中")
        else:
            pending_count = git_count if git_count is not None else match_idx
            infos.append(f"AUDIT-LOG latest reviewed commit: {latest_hash} (pending commits since latest review: {pending_count})")
        return fails, infos

    ancestry = []
    if _in_git_repo(root_dir):
        rc, out, _ = _git(root_dir, ["rev-list", "HEAD"])
        if rc == 0:
            ancestry = [line.strip().lower() for line in out.splitlines() if line.strip()]

    if ancestry:
        match_idx = None
        for idx, c in enumerate(ancestry):
            if hashes_match(c, latest_hash):
                match_idx = idx
                break

        if match_idx is None:
            fails.append(f"docs/AUDIT-LOG.md: 最新審查紀錄 ({latest_hash}) 不存在於目前 Git HEAD 歷史 (ancestors) 中")
        else:
            pending_count = git_count if git_count is not None else match_idx
            infos.append(f"AUDIT-LOG latest reviewed commit: {latest_hash} (pending commits since latest review: {pending_count})")
        return fails, infos

    # Fallback: 若無法取得 rev-list HEAD，但可以以 git rev-list 測 count 或已知在 repo 中
    try:
        res = subprocess.run(["git", "rev-list", "--count", f"{latest_hash}..HEAD"], cwd=root_dir, capture_output=True, text=True)
        if res.returncode == 0:
            lag = int(res.stdout.strip())
            infos.append(f"AUDIT-LOG latest reviewed commit: {latest_hash} (pending commits since latest review: {lag})")
        else:
            fails.append(f"docs/AUDIT-LOG.md: 最新審查紀錄 ({latest_hash}) 無法於 Git 歷史中解析")
    except Exception as e:
        fails.append(f"docs/AUDIT-LOG.md: 無法執行 git 指令以驗證審查歷史 (hash={latest_hash}): {e}")

    return fails, infos

def check_13_trailing_newline(root_dir=None, strict=False):
    if root_dir is None: root_dir = repo_root
    fails = []
    infos = []
    for root, dirs, files in os.walk(root_dir):
        if any(p in root for p in [".git", "node_modules", "__pycache__", ".venv"]):
            continue
        for file in files:
            if file.endswith((".md", ".py", ".json")):
                filepath = os.path.join(root, file)
                rel_fp = os.path.relpath(filepath, root_dir).replace("\\", "/")
                try:
                    with open(filepath, "rb") as fh:
                        data = fh.read()
                        if data and not data.endswith(b"\n"):
                            msg = f"{rel_fp}:0  檔尾缺少換行符"
                            if strict:
                                fails.append(msg)
                            else:
                                infos.append(msg)
                except Exception as e:
                    fails.append(f"{rel_fp}:0  檔案讀取失敗: {e}")
    return fails, infos

def check_14_simplified_chinese(root_dir=None):
    """CHECK 14 — 繁體中文環境下的簡體字與日文字元偵測。"""
    if root_dir is None: root_dir = repo_root
    fails = []
    infos = []
    simplified_chars = set("换爲这个们时说说过还没来实现应该产严术样价专车书长门间乐习买卖举属于")
    # Japanese kana: Hiragana (U+3040-U+309F), Katakana (U+30A0-U+30FF), Half-width Katakana (U+FF65-U+FF9F)
    jp_kana_re = re.compile(r'[\u3040-\u309f\u30a0-\u30ff\uff65-\uff9f]')
    # Reviewed Japanese Shinjitai denylist (distinct from Traditional Chinese)
    jp_shinjitai_chars = set('\u8a3c\u9244\u5e83\u5bfe\u8aad\u8ee2\u7d75\u7dcf\u99c5\u685c\u5358\u56f2\u55b6\u5186\u5fdc\u6c17\u7d4c\u770c\u6a29\u56fd\u6e08\u5b9f\u5199\u5bff\u6761\u56f3\u7a0e\u4f1d\u5909\u6b69\u6e80\u52b4\u6b74\u9332')
    historical_markers = ["簡體", "歷史說明", "原樣板", "日文", "簡繁", "日語"]
    for root, dirs, files in os.walk(root_dir):
        if any(p in root for p in [".git", "node_modules", "__pycache__", ".venv"]):
            continue
        for file in files:
            if file.endswith(".md"):
                filepath = os.path.join(root, file)
                rel_fp = os.path.relpath(filepath, root_dir).replace(os.sep, "/")
                try:
                    with open(filepath, "r", encoding="utf-8") as fh:
                        prev_line = ""
                        for idx, line in enumerate(fh, 1):
                            simp_hits = [c for c in line if c in simplified_chars]
                            kana_hits = jp_kana_re.findall(line)
                            shinjitai_hits = [c for c in line if c in jp_shinjitai_chars]
                            all_hits = simp_hits + kana_hits + shinjitai_hits
                            if all_hits:
                                hit_categories = []
                                if simp_hits:
                                    s_str = "".join(sorted(set(simp_hits)))
                                    hit_categories.append(f"簡體字 [{s_str}]")
                                if kana_hits or shinjitai_hits:
                                    j_str = "".join(sorted(set(kana_hits + shinjitai_hits)))
                                    hit_categories.append(f"日文字元 [{j_str}]")
                                category_desc = "與".join(hit_categories)
                                msg = f"{rel_fp}:{idx}  包含{category_desc}: {line.strip()[:60]}"
                                if rel_fp in ["docs/refactor-backlog.md", "docs/AUDIT-LOG.md"]:
                                    context = line + " " + prev_line
                                    if any(m in context for m in historical_markers):
                                        infos.append(f"{msg} (歷史紀錄引用例外)")
                                    else:
                                        fails.append(msg)
                                else:
                                    fails.append(msg)
                            prev_line = line
                except Exception as e:
                    fails.append(f"{rel_fp}:0  檔案讀取失敗: {e}")
    return fails, infos

def check_15_context_conflict(root_dir=None):
    """CHECK 15 — 交接區 §5.1 中同一 commit hash 的語境衝突。

    規格：讀 docs/refactor-backlog.md 的 §5.1 整節。
    若同一個 commit hash 同時出現在含「已核對通過」的句子
    與含「尚待審計官核對」（或「尚待核對」）的句子中，即為 FAIL。

    對應 2026-09-02 實際發生的事故（refactor-backlog 第 37 點 A 段）：
    23af193 既被記為「已核對通過」，同節最後一個項目符號又說「尚待審計官核對」。
    """
    if root_dir is None:
        root_dir = repo_root
    fails = []
    infos = []

    bl_path = os.path.join(root_dir, "docs", "refactor-backlog.md")
    if not os.path.exists(bl_path):
        fails.append("docs/refactor-backlog.md:0  檔案不存在")
        return fails, infos

    try:
        with open(bl_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        fails.append(f"docs/refactor-backlog.md:0  讀取失敗: {e}")
        return fails, infos

    m = re.search(r"^### 5\.1 .*?$(.*?)^### 5\.2 ", content, re.M | re.S)
    if not m:
        infos.append("docs/refactor-backlog.md 找不到交接區 §5.1 區段，跳過檢查")
        return fails, infos

    section = m.group(1)
    section_start_line = content[:m.start(1)].count("\n") + 1

    DONE_MARKERS = ("已核對通過", "核對通過")
    PENDING_MARKERS = ("尚待審計官核對", "尚待核對", "等待審計官核對")

    done_hashes = {}
    pending_hashes = {}

    # §5.1 的項目符號是跨行排版——hash 常在第一行、「已核對通過」在第二行。
    # 因此以「項目符號」為掃描單位，不能逐行比對。
    # 逐行比對的版本在 2026-09-04 實測中，done 與 pending 皆為空集合，
    # 即使注入衝突也抓不到（由執行者發現並回報）。
    blocks = []
    current = None
    for offset, line in enumerate(section.splitlines(), 0):
        if line.lstrip().startswith("- "):
            if current is not None:
                blocks.append(current)
            current = {"lineno": section_start_line + offset, "lines": [line]}
        elif current is not None:
            current["lines"].append(line)
    if current is not None:
        blocks.append(current)

    for block in blocks:
        text = "\n".join(block["lines"])
        hashes = re.findall(r"`([0-9a-f]{7,40})`", text)
        if not hashes:
            continue
        lineno = block["lineno"]
        if any(mk in text for mk in DONE_MARKERS):
            for h in hashes:
                done_hashes.setdefault(h, lineno)
        if any(mk in text for mk in PENDING_MARKERS):
            for h in hashes:
                pending_hashes.setdefault(h, lineno)

    for h in sorted(set(done_hashes) & set(pending_hashes)):
        fails.append(
            f"docs/refactor-backlog.md:{done_hashes[h]}  §5.1 中 {h} 同時被描述為"
            f"「已核對通過」與「尚待核對」（另見第 {pending_hashes[h]} 行）"
        )

    if not fails:
        infos.append(
            f"§5.1 已核對 {len(done_hashes)} 個 hash、待核對 {len(pending_hashes)} 個，無交集"
        )

    return fails, infos

def check_16_exec_log_cadence(root_dir=None, git_count=None, git_is_ancestor=None):
    """CHECK 16 — 執行者檢查紀錄（EXEC-LOG）證據生命週期與落後偵測。

    規格：讀 docs/EXEC-LOG.md 最後一列的 commit 欄位。
    若該值為 BOOTSTRAP 以外的 hash：
    1. 驗證該 hash 是否為目前 HEAD 之祖先 commit (git merge-base --is-ancestor <sha> HEAD)。
       若非祖先（exit code != 0），即為 FAIL。
    2. 僅在確認為祖先後，計算落後量 (git rev-list --count <sha>..HEAD，不使用 --no-merges)。
       若落後 HEAD 超過 1 個 commit，即為 FAIL。
    架構分工：
    - CHECK 16：由執行者持有之 EXEC-LOG 證據生命週期／頻率（Executor-owned EXEC-LOG evidence lifecycle / cadence）。
    - CHECK 12：由審計官持有之 AUDIT-LOG 歷史有效性／相容性（Auditor-owned AUDIT-LOG ancestry validity / pending-range compatibility）。
    兩者為獨立責任與獨立判準。
    """
    if root_dir is None: root_dir = repo_root
    fails = []
    infos = []
    el_path = os.path.join(root_dir, "docs", "EXEC-LOG.md")
    if not os.path.exists(el_path):
        fails.append("docs/EXEC-LOG.md:0  檔案不存在")
        return fails, infos
    try:
        with open(el_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        fails.append(f"docs/EXEC-LOG.md:0  讀取失敗: {e}")
        return fails, infos

    table_rows = []
    for line in content.splitlines():
        line_s = line.strip()
        if line_s.startswith("|"):
            cells = [p.strip() for p in line_s.split("|")[1:-1]]
            if cells and not all(c.replace("-", "").replace(":", "") == "" for c in cells):
                first_cell = cells[0].strip("`").strip()
                if first_cell and first_cell not in ["批次 commit", "commit", "Commit", "批次", "SHA", "Hash"]:
                    table_rows.append(first_cell)

    if not table_rows:
        fails.append("docs/EXEC-LOG.md:0  未找到執行者檢查紀錄列")
        return fails, infos

    latest_hash = table_rows[-1]
    if latest_hash == "BOOTSTRAP":
        infos.append("docs/EXEC-LOG.md 最新列為 BOOTSTRAP，跳過檢查")
        return fails, infos

    if not re.match(r"^[0-9a-fA-F]{7,40}$", latest_hash):
        fails.append(f"docs/EXEC-LOG.md: 最新紀錄之 commit hash 格式不合法或缺失: '{latest_hash}'")
        return fails, infos

    # 1. 祖先斷言先決 (git merge-base --is-ancestor <sha> HEAD)
    if git_is_ancestor is False:
        fails.append(f"docs/EXEC-LOG.md: 最新檢查紀錄 ({latest_hash}) 不是目前 HEAD 之祖先 commit（git merge-base --is-ancestor 失敗，可能是 squash-merge 歷史不相容或幽靈紀錄）")
        return fails, infos
    elif git_is_ancestor is True:
        pass
    elif git_count is not None:
        pass
    else:
        try:
            res_ancestor = subprocess.run(
                ["git", "merge-base", "--is-ancestor", latest_hash, "HEAD"],
                cwd=root_dir, capture_output=True, text=True
            )
            if res_ancestor.returncode == 1:
                fails.append(f"docs/EXEC-LOG.md: 最新檢查紀錄 ({latest_hash}) 不是目前 HEAD 之祖先 commit（git merge-base --is-ancestor 失敗，可能是 squash-merge 歷史不相容或幽靈紀錄）")
                return fails, infos
            elif res_ancestor.returncode != 0:
                fails.append(f"docs/EXEC-LOG.md: 無法取得 git rev-list，無法驗證檢查紀錄生命週期 (hash={latest_hash})")
                return fails, infos
        except Exception as e:
            fails.append(f"docs/EXEC-LOG.md: 無法取得 git rev-list，無法驗證檢查紀錄生命週期 (hash={latest_hash}): {e}")
            return fails, infos

    # 2. 落後量計算 (git rev-list --count <sha>..HEAD，移除 --no-merges)
    lag = 0
    if git_count is not None:
        lag = git_count
    else:
        try:
            res = subprocess.run(["git", "rev-list", "--count", f"{latest_hash}..HEAD"], cwd=root_dir, capture_output=True, text=True)
            if res.returncode == 0:
                lag = int(res.stdout.strip())
            else:
                fails.append(f"docs/EXEC-LOG.md: 無法取得 git rev-list，無法驗證檢查紀錄生命週期 (hash={latest_hash})")
                return fails, infos
        except Exception as e:
            fails.append(f"docs/EXEC-LOG.md: 無法執行 git 指令以驗證檢查紀錄生命週期 (hash={latest_hash}): {e}")
            return fails, infos

    if lag > 1:
        fails.append(f"docs/EXEC-LOG.md: 最新檢查紀錄 ({latest_hash}) 落後 HEAD {lag} 個 commit（允許落後 1 批，因本批尚未核對）")
    else:
        infos.append(f"docs/EXEC-LOG.md: 最新檢查紀錄 ({latest_hash}) 通過祖先檢驗且落後量合規 (lag={lag})")
    return fails, infos


SPEC_DIR = "docs/batches"
SPEC_EXEMPT_FILES = {"docs/EXEC-LOG.md", "docs/fingerprints/exec-latest.json"}

# 已知指向錯誤的歷史 tag。本清單只能縮短、不得加長。
# 修復批次完成後必須清空；清單中的 tag 若已修復卻未移除，CHECK 18 會 FAIL。
KNOWN_BAD_TAGS = {
    "audited-1491d33", "audited-3a85a30", "audited-59cea4c",
    "audited-7450c4a", "audited-875a604", "audited-936b9af",
    "audited-a44cc6b", "audited-e6f543a", "audited-ec840fe",
}


def _git(root_dir, args):
    """文字模式的 git，只用於 hash、檔名、numstat 等純 ASCII 輸出。"""
    res = subprocess.run(["git"] + args, cwd=root_dir,
                         capture_output=True, text=True)
    return res.returncode, res.stdout, res.stderr


def _git_bytes(root_dir, args):
    """
    位元組模式的 git。取檔案內容一律走這裡。

    text=True 會啟用 Python 的 universal newline，把 CRLF 靜靜換成 LF——
    一個 CRLF blob 與一個 LF blob 進到 Python 之後會變成同一個字串，
    「逐位元比對」的宣稱就不成立。取內容時不得使用文字模式。
    """
    res = subprocess.run(["git"] + args, cwd=root_dir, capture_output=True)
    return res.returncode, res.stdout, res.stderr


def _resolve_commit(root_dir, rev):
    """
    把 revision 解析成完整 40 碼 commit OID。
    不存在、有歧義、不是 commit，一律回 None。
    commit identity 一律走這裡，不使用字串前綴或 startswith。
    """
    rc, out, _ = _git(root_dir, ["rev-parse", "--verify", f"{rev}^{{commit}}"])
    if rc != 0:
        return None
    oid = out.strip()
    return oid if len(oid) == 40 else None


def _in_git_repo(root_dir):
    """
    這個路徑底下是否有 git repository。

    區分兩件事很重要：「根本沒有 repo 可驗」與「有 repo 但 git 回答不出來」。
    前者是不適用（例如規格模擬用的臨時目錄），後者是環境異常，
    必須 FAIL，不得放行。
    """
    rc, _, _ = _git(root_dir, ["rev-parse", "--git-dir"])
    return rc == 0


def _head_bootstrap_specs(root_dir):
    """
    從 committed HEAD tree 取 BOOTSTRAP 規格清單。

    不使用 `git ls-files`——那讀的是 index。index 暫存一次刪除就能讓
    「全庫至多一份」的答案改變，但 CHECK 17 驗的是 HEAD 這個
    committed 狀態的 invariant，不該被 index 或工作區的變動左右。
    回傳 (清單, 是否成功)。
    """
    rc, out, _ = _git(root_dir, ["ls-tree", "-r", "--name-only", "HEAD", SPEC_DIR + "/"])
    if rc != 0:
        return [], False
    return sorted(p for p in out.splitlines()
                  if p.strip().endswith("-BOOTSTRAP.spec.txt")), True


def _validate_exec_log_transition(root_dir, parent_oid, head_rev="HEAD"):
    """
    驗證 docs/EXEC-LOG.md 的狀態流轉。

    規則：
    1. parent 中所有較早歷史列完全不變。
    2. 若 parent 最後一列第一欄為『本批』：
       - child 將該列第一欄替換為 parent commit 的合法 commit identity（可解析為 parent_oid）。
       - 該列其餘欄位內容必須完全不變。
       - child 在尾端追加本批新紀錄，第一欄為『本批』。
    3. 若 parent 最後一列已是合法 concrete hash 或 BOOTSTRAP：
       - child 保持所有既有列不變，在尾端追加新的『本批』列。
    4. 不允許任意舊 row 修改、刪除、reorder。
    """
    fails, infos = [], []
    rc, p_bytes, _ = _git_bytes(root_dir, ["show", f"{parent_oid}:docs/EXEC-LOG.md"])
    if rc != 0:
        fails.append("docs/EXEC-LOG.md:0  無法自 parent 取出內容")
        return fails, infos
    rc, c_bytes, _ = _git_bytes(root_dir, ["show", f"{head_rev}:docs/EXEC-LOG.md"])
    if rc != 0:
        fails.append(f"docs/EXEC-LOG.md:0  無法自 {head_rev} 取出內容")
        return fails, infos

    try:
        p_text = p_bytes.decode("utf-8")
        c_text = c_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        fails.append(f"docs/EXEC-LOG.md:0  內容不是合法 UTF-8: {e}")
        return fails, infos

    p_lines = p_text.splitlines()
    c_lines = c_text.splitlines()

    def _is_data_row(line):
        s = line.strip()
        if not s.startswith("|"):
            return False
        if "批次 commit" in s:
            return False
        if re.match(r"^\|(\s*:?-+:?\s*\|)+$", s):
            return False
        return True

    def _split_cols(row_str):
        cols = [c.strip() for c in row_str.split("|")]
        if len(cols) >= 3 and cols[0] == "" and cols[-1] == "":
            return cols[1:-1]
        return [c.strip() for c in cols if c.strip()]

    p_rows = [line.strip() for line in p_lines if _is_data_row(line)]
    c_rows = [line.strip() for line in c_lines if _is_data_row(line)]

    if not p_rows:
        fails.append("docs/EXEC-LOG.md:0  parent 中未找到任何表格資料列")
        return fails, infos
    if not c_rows:
        fails.append("docs/EXEC-LOG.md:0  child 中未找到任何表格資料列")
        return fails, infos

    p_non_data = [line for line in p_lines if not _is_data_row(line)]
    c_non_data = [line for line in c_lines if not _is_data_row(line)]
    if p_non_data != c_non_data:
        fails.append("docs/EXEC-LOG.md:0  表格之外的非資料列內容遭修改")

    p_last_cols = _split_cols(p_rows[-1])
    if not p_last_cols:
        fails.append("docs/EXEC-LOG.md:0  parent 最後一列無法解析欄位")
        return fails, infos

    if len(c_rows) != len(p_rows) + 1:
        if len(c_rows) <= len(p_rows):
            fails.append(f"docs/EXEC-LOG.md:0  既有資料列遭刪除或未追加新列（parent {len(p_rows)} 列，child 實測 {len(c_rows)} 列）")
        else:
            fails.append(f"docs/EXEC-LOG.md:0  單次 commit 追加過多列（parent {len(p_rows)} 列，child 實測 {len(c_rows)} 列）")
        return fails, infos

    if p_last_cols[0] == "本批":
        for i in range(len(p_rows) - 1):
            if p_rows[i] != c_rows[i]:
                fails.append(f"docs/EXEC-LOG.md:0  第 {i+1} 筆歷史資料列遭修改")
        c_replaced_cols = _split_cols(c_rows[len(p_rows) - 1])
        if len(c_replaced_cols) != len(p_last_cols):
            fails.append("docs/EXEC-LOG.md:0  回填列欄位數與原列不符")
        else:
            c_hash = c_replaced_cols[0]
            resolved = _resolve_commit(root_dir, c_hash)
            if resolved is None or resolved != parent_oid:
                fails.append(f"docs/EXEC-LOG.md:0  上一批『本批』回填之 commit identity ({c_hash}) 無法解析或不等於 parent commit ({parent_oid[:7]})")
            if c_replaced_cols[1:] != p_last_cols[1:]:
                fails.append("docs/EXEC-LOG.md:0  回填列除第一欄 commit identity 外之其餘內容遭修改")
        c_new_cols = _split_cols(c_rows[len(p_rows)])
        if not c_new_cols or c_new_cols[0] != "本批":
            fails.append("docs/EXEC-LOG.md:0  最新追加列的第一欄必須為『本批』")
    else:
        for i in range(len(p_rows)):
            if p_rows[i] != c_rows[i]:
                fails.append(f"docs/EXEC-LOG.md:0  第 {i+1} 筆歷史資料列遭修改")
        c_new_cols = _split_cols(c_rows[len(p_rows)])
        if not c_new_cols or c_new_cols[0] != "本批":
            fails.append("docs/EXEC-LOG.md:0  最新追加列的第一欄必須為『本批』")

    if not fails:
        infos.append("docs/EXEC-LOG.md 狀態流轉驗證通過（歷史列不變，符合合法生命週期）")
    return fails, infos


def check_17_spec_replay(root_dir=None):
    """
    CHECK 17 — Batch Spec 重放一致性

    **強制範圍（enforcement scope）**：本檢查只對同時滿足以下條件的 commit
    執行逐位元重放——單一 parent、本 commit 恰好異動一份
    docs/batches/*.spec.txt、且該份不是 BOOTSTRAP 規格。
    對這類 commit，規格重放結果與 actual target 必須一致。

    以下情形依設計跳過重放，這些是合法 skip，不是漏洞：
      - 本 commit 未異動任何規格（一般維護 commit）
      - 非單一 parent（root commit、merge commit）

    規格格式原生支援 create_file mode，能以宣告式表達建立新檔並執行逐位元重放；
    BOOTSTRAP 特殊跳過語意已於 B-90 全面移除。

    對進入 enforcement scope 的 commit，本檢查驗五件事：
      1. 規格 HEAD: 欄位解析成完整 commit OID，必須等於唯一 parent 的 OID
      2. 由 parent 取出各 MOD 目標檔案，經 parse_spec + apply_mod_to_text 重放
      3. 重放結果 encode UTF-8 後，與本 commit 的 git blob 原始位元組直接比對
      4. parent..HEAD 的實際異動檔案集合不得超出
         {MOD 宣告的檔案} ∪ {本規格檔} ∪ SPEC_EXEMPT_FILES
      5. 豁免檔只允許追加：以 git numstat 取刪除行數，> 0 即 FAIL

    「全庫 BOOTSTRAP 至多一份」是 HEAD tree 的 repository invariant，
    在任何 early-return 之前先驗。
    """
    fails, infos = [], []
    root_dir = root_dir or "."

    if not _in_git_repo(root_dir):
        infos.append("此路徑不是 git repository，本檢查不適用")
        return fails, infos

    rc, out, _ = _git(root_dir, ["rev-list", "--parents", "-n", "1", "HEAD"])
    if rc != 0:
        infos.append("無法取得 git 資訊，跳過重放")
        return fails, infos
    parts = out.split()
    if len(parts) != 2:
        infos.append(f"HEAD 的 parent 數為 {len(parts) - 1}，非單一 parent，"
                     f"不在 CHECK 17 強制範圍內，跳過重放")
        return fails, infos
    parent_oid = _resolve_commit(root_dir, parts[1])
    if parent_oid is None:
        fails.append("無法把 HEAD 的 parent 解析為 commit OID")
        return fails, infos

    rc, out, _ = _git(root_dir, ["diff", "--name-only", parent_oid, "HEAD"])
    if rc != 0:
        infos.append("無法取得 git diff，跳過重放")
        return fails, infos
    changed = {p for p in out.splitlines() if p.strip()}

    specs = sorted(p for p in changed
                   if p.startswith(SPEC_DIR + "/") and p.endswith(".spec.txt"))

    # 順序很重要：「單一 commit 只允許一份規格」必須在任何 BOOTSTRAP
    # early-return 之前判定。否則「一份 BOOTSTRAP ＋ 一份普通規格」
    # 會從 BOOTSTRAP 分支提前 return，讓那份普通規格完全不被重放。
    if not specs:
        infos.append("本 commit 未異動 docs/batches/*.spec.txt，"
                     "不在 CHECK 17 強制範圍內，跳過重放（一般維護 commit）")
        return fails, infos
    if len(specs) > 1:
        fails.append(f"{SPEC_DIR}:0  單一 commit 只允許一份規格，實測 {len(specs)} 份: {specs}")
        return fails, infos

    spec_path = specs[0]
    rc, spec_bytes, _ = _git_bytes(root_dir, ["show", f"HEAD:{spec_path}"])
    if rc != 0:
        fails.append(f"{spec_path}:0  無法從 HEAD 取出規格內容")
        return fails, infos
    try:
        spec_text = spec_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        fails.append(f"{spec_path}:0  規格不是合法 UTF-8: {e}")
        return fails, infos

    sys.path.insert(0, os.path.join(root_dir, "scripts"))
    try:
        from build_prompt_evidence import parse_spec, apply_mod_to_text, validate_repo_path
    except Exception as e:
        fails.append(f"{spec_path}:0  無法載入指定 apply path: {e}")
        return fails, infos
    try:
        spec_head, mods, _expects = parse_spec(spec_text)
    except Exception as e:
        fails.append(f"{spec_path}:0  規格解析失敗: {e}")
        return fails, infos

    if not spec_head:
        fails.append(f"{spec_path}:0  規格缺少 HEAD: 欄位")
        return fails, infos
    spec_oid = _resolve_commit(root_dir, spec_head)
    if spec_oid is None:
        fails.append(f"{spec_path}:0  規格宣告的 base={spec_head} 無法解析為 commit"
                     f"（不存在、有歧義，或不是 commit）")
        return fails, infos
    if spec_oid != parent_oid:
        fails.append(f"{spec_path}:0  規格 base 與實際 parent 不是同一個 commit："
                     f"spec={spec_oid} parent={parent_oid}")
        return fails, infos
    infos.append(f"規格 {spec_path}，base OID 與 parent 相符，MOD {len(mods)} 個")

    declared = set()
    by_file = {}
    for mod in mods:
        declared.add(mod["file"])
        by_file.setdefault(mod["file"], []).append(mod)

    allowed = declared | {spec_path} | SPEC_EXEMPT_FILES
    extra = sorted(changed - allowed)
    if extra:
        fails.append(f"{spec_path}:0  規格未宣告卻被修改的檔案: {extra}")

    # 豁免檔驗證：
    # docs/fingerprints/exec-latest.json 為 generated snapshot，正確性由 fingerprint.py --verify 專責守護。
    # docs/EXEC-LOG.md 採專用 semantic transition validator，禁止任意刪改舊列，僅允許合法回填與追加。
    for ex in sorted(SPEC_EXEMPT_FILES & changed):
        if ex == "docs/fingerprints/exec-latest.json":
            infos.append(f"{ex}: fingerprint artifact integrity delegated to fingerprint.py --verify")
            continue
        if ex == "docs/EXEC-LOG.md":
            el_fails, el_infos = _validate_exec_log_transition(root_dir, parent_oid, "HEAD")
            fails.extend(el_fails)
            infos.extend(el_infos)
            continue
        rc, out, _ = _git(root_dir, ["diff", "--numstat", parent_oid, "HEAD", "--", ex])
        if rc != 0:
            fails.append(f"{ex}:0  無法取得 numstat，無法證明只有追加")
            continue
        for row in out.splitlines():
            cols = row.split("	")
            if len(cols) < 3:
                continue
            adds, dels = cols[0], cols[1]
            if adds == "-" or dels == "-":
                fails.append(f"{ex}:0  被視為二進位檔，無法證明只有追加")
                continue
            if int(dels) > 0:
                fails.append(f"{ex}:0  豁免檔只允許追加，numstat 實測刪除 {dels} 行")

    for path, mlist in sorted(by_file.items()):
        try:
            validate_repo_path(path)
        except ValueError as e:
            fails.append(f"{path}:0  規格目標檔案路徑不合法: {e}")
            continue

        is_create = (mlist[0]["mode"] == "create_file")
        if is_create:
            if len(mlist) > 1:
                fails.append(f"{path}:0  create_file 不得與其他 MOD 混用")
                continue
            rc, base_bytes, _ = _git_bytes(root_dir, ["show", f"{parent_oid}:{path}"])
            if rc == 0:
                fails.append(f"{path}:0  create_file 目標檔案在 parent commit 已存在")
                continue
            try:
                text = apply_mod_to_text(None, mlist[0])
            except Exception as e:
                fails.append(f"{path}:0  重放失敗: {e}")
                continue
        else:
            rc, base_bytes, _ = _git_bytes(root_dir, ["show", f"{parent_oid}:{path}"])
            if rc != 0:
                fails.append(f"{path}:0  無法從 base 取出原始內容（新檔無法以 MOD 表達）")
                continue
            try:
                text = base_bytes.decode("utf-8")
            except UnicodeDecodeError as e:
                fails.append(f"{path}:0  base 內容不是合法 UTF-8: {e}")
                continue
            try:
                for mod in mlist:
                    text = apply_mod_to_text(text, mod)
            except Exception as e:
                fails.append(f"{path}:0  重放失敗: {e}")
                continue

        expected = text.encode("utf-8")

        rc, actual, _ = _git_bytes(root_dir, ["show", f"HEAD:{path}"])
        if rc != 0:
            fails.append(f"{path}:0  本 commit 中不存在")
            continue
        if expected != actual:
            pos = next((i for i in range(min(len(expected), len(actual)))
                        if expected[i] != actual[i]), min(len(expected), len(actual)))
            line = expected[:pos].count(b"\n") + 1
            fails.append(
                f"{path}:{line}  重放結果與實際 commit 的位元組不一致"
                f"（首個相異 offset={pos}，"
                f"expected={expected[pos:pos + 12]!r} actual={actual[pos:pos + 12]!r}，"
                f"長度 expected={len(expected)} actual={len(actual)}）")
        else:
            infos.append(f"{path} 重放逐位元相符")

    return fails, infos


def check_18_tag_integrity(root_dir=None):
    """
    CHECK 18 — audited-* tag 名實一致

    每個 audited-<hash> tag 必須滿足：
      1. 名稱中的 hash 解析得到的完整 commit OID，等於 tag 指向的 commit OID
      2. 該 commit 由目前 HEAD 可達（git merge-base --is-ancestor）

    任何一方的 commit identity 無法解析，一律 FAIL，不得 fail-open：
    HEAD 解析不出來就跳過可達性驗證，等於在環境異常時自動放行。

    `git cat-file -e` 只證明物件還在 object database 裡——被丟棄的分支、
    orphan commit 都還在，那不是「本分支可達」，所以不用它。

    成因：`git tag audited-<hash>` 未帶 commit 參數時會打在當下 HEAD 上，
    tag 名字對、指向錯。2026-09-11 實測 17 個 tag 中 9 個如此。

    KNOWN_BAD_TAGS 為已知待修復的歷史 tag，本清單只能縮短不得加長；
    清單中的 tag 若已修復卻未從清單移除，本檢查一律 FAIL。
    """
    fails, infos = [], []
    root_dir = root_dir or "."

    if not _in_git_repo(root_dir):
        infos.append("此路徑不是 git repository，本檢查不適用")
        return fails, infos

    rc, out, _ = _git(root_dir, ["tag", "-l", "audited-*"])
    if rc != 0:
        fails.append("tag:0  repository 存在但無法取得 tag 清單，無法驗證 tag 完整性")
        return fails, infos
    tags = sorted(t.strip() for t in out.splitlines() if t.strip())
    if not tags:
        infos.append("repo 中無 audited-* tag，跳過")
        return fails, infos

    head_oid = _resolve_commit(root_dir, "HEAD")
    if head_oid is None:
        fails.append("tag:0  無法把 HEAD 解析為 commit OID，"
                     "無法進行可達性驗證（不得在此情形下放行）")
        return fails, infos

    known_bad_seen, repaired = [], []

    for t in tags:
        named = t[len("audited-"):]
        tag_oid = _resolve_commit(root_dir, t)
        if tag_oid is None:
            fails.append(f"tag:{t}  無法解析為 commit")
            continue
        named_oid = _resolve_commit(root_dir, named)
        if named_oid is None:
            fails.append(f"tag:{t}  名稱中的 hash 無法解析為 commit"
                         f"（不存在、有歧義，或不是 commit）")
            continue

        if named_oid != tag_oid:
            if t in KNOWN_BAD_TAGS:
                known_bad_seen.append(f"{t}->{tag_oid[:7]}")
            else:
                fails.append(f"tag:{t}  指向 {tag_oid[:7]}，與名稱不符（新增的名實不符）")
            continue

        if t in KNOWN_BAD_TAGS:
            repaired.append(t)

        rc2, _, _ = _git(root_dir, ["merge-base", "--is-ancestor", named_oid, head_oid])
        if rc2 != 0:
            fails.append(f"tag:{t}  指向的 commit {named_oid[:7]} "
                         f"無法由目前 HEAD 到達（物件還在，但不在本分支歷史上）")

    if repaired:
        fails.append(f"tag:0  下列 tag 已修復但仍留在 KNOWN_BAD_TAGS，必須移除: {sorted(repaired)}")
    if known_bad_seen:
        infos.append(f"已知待修復 tag {len(known_bad_seen)} 個（見 KNOWN_BAD_TAGS）: "
                     f"{sorted(known_bad_seen)}")
    infos.append(f"audited-* tag 共 {len(tags)} 個")
    return fails, infos


def check_19_utf8_bom(root_dir=None):
    """CHECK 19 — ADR-0013 §2C UTF-8 BOM 污染偵測（Git tracked regular files）。"""
    if root_dir is None:
        root_dir = repo_root
    fails = []
    infos = []

    if not _in_git_repo(root_dir):
        fails.append(f"check_consistency:0  路徑不是 git repository，無法驗證 tracked files: {root_dir}")
        return fails, infos

    rc, out_bytes, _ = _git_bytes(root_dir, ["ls-files", "-z"])
    if rc != 0:
        fails.append(f"git:0  無法取得 tracked files 清單 (git ls-files -z 失敗, rc={rc})")
        return fails, infos

    raw_paths = [p for p in out_bytes.split(b"\0") if p]
    scanned = 0
    for raw_p in raw_paths:
        try:
            rel_p = raw_p.decode("utf-8")
        except UnicodeDecodeError:
            rel_p = raw_p.decode("utf-8", errors="replace")
        rel_fp = rel_p.replace("\\", "/")
        full_path = os.path.join(root_dir, rel_p)

        if os.path.isdir(full_path):
            continue

        try:
            with open(full_path, "rb") as fh:
                header = fh.read(3)
                if header == b"\xef\xbb\xbf":
                    fails.append(f"{rel_fp}:1  檔案開頭包含 UTF-8 BOM (EF BB BF) 污染")
            scanned += 1
        except Exception as e:
            fails.append(f"{rel_fp}:0  檔案讀取失敗: {e}")

    infos.append(f"掃描 Git tracked 檔案共 {scanned} 個")
    return fails, infos


def _is_table_row(line):
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and len(s) >= 2


def _is_table_separator_row(line):
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")):
        return False
    cells = s[1:-1].split("|")
    if not cells:
        return False
    for c in cells:
        c_str = c.strip()
        if not c_str or not re.match(r"^:?-+:?$", c_str):
            return False
    return True


def check_20_markdown_table_continuity(root_dir=None):
    """CHECK 20 — Markdown 表格連續性（偵測被空白行切斷之表格）。"""
    if root_dir is None:
        root_dir = repo_root
    fails = []
    infos = []
    scanned = 0
    for root, dirs, files in os.walk(root_dir):
        if any(p in root for p in [".git", "node_modules", "__pycache__", ".venv", "docs/archive", "docs\\archive", "_archive"]):
            continue
        for file in files:
            if file.endswith(".md"):
                filepath = os.path.join(root, file)
                rel_fp = os.path.relpath(filepath, root_dir).replace(os.sep, "/")
                try:
                    with open(filepath, "r", encoding="utf-8") as fh:
                        lines = fh.readlines()
                    in_code = False
                    fence_char = None
                    in_table = False
                    had_blank = False
                    for idx, line in enumerate(lines):
                        s = line.strip()
                        if s.startswith("```") or s.startswith("~~~"):
                            curr = s[:3]
                            if not in_code:
                                in_code = True
                                fence_char = curr
                            elif fence_char == curr:
                                in_code = False
                                fence_char = None
                            in_table = False
                            had_blank = False
                            continue
                        if in_code:
                            continue
                        if _is_table_row(line):
                            is_header = (idx + 1 < len(lines) and _is_table_separator_row(lines[idx + 1]))
                            if is_header:
                                in_table = True
                                had_blank = False
                            elif _is_table_separator_row(line):
                                had_blank = False
                            else:
                                if in_table and had_blank:
                                    fails.append(f"{rel_fp}:{idx + 1}  表格被空白行切斷（同一表格接續列未緊鄰表格本體）: {s[:60]}")
                                    had_blank = False
                        elif not s:
                            if in_table:
                                had_blank = True
                        else:
                            in_table = False
                            had_blank = False
                    scanned += 1
                except Exception as e:
                    fails.append(f"{rel_fp}:0  檔案讀取失敗: {e}")
    infos.append(f"掃描 Markdown 檔案共 {scanned} 個")
    return fails, infos


def check_21_secret_leak_guard(root_dir=None):
    """CHECK 21 — 機密防護與輸出安全守衛 (Secret Leak Guard)。"""
    if root_dir is None:
        root_dir = repo_root
    fails = []
    infos = []

    # A & B: 驗證 .agents/rules/secret-output-safety.md 存在且包含 SECRET-1 至 SECRET-8 錨點
    rule_path = os.path.join(root_dir, ".agents", "rules", "secret-output-safety.md")
    if not os.path.exists(rule_path):
        fails.append(".agents/rules/secret-output-safety.md:0  工作區機敏安全守衛規範檔案不存在")
    else:
        try:
            with open(rule_path, "r", encoding="utf-8") as f:
                rule_text = f.read()
            anchors = [f"SECRET-{i}" for i in range(1, 9)]
            missing = [a for a in anchors if a not in rule_text]
            if missing:
                fails.append(f".agents/rules/secret-output-safety.md:0  缺少必要錨點: {', '.join(missing)}")
            else:
                infos.append("工作區機敏規範 .agents/rules/secret-output-safety.md 存在且 8 組錨點完整")
        except Exception as e:
            fails.append(f".agents/rules/secret-output-safety.md:0  讀取失敗: {e}")

    # C, D, E: 驗證 .githooks/pre-commit 存在、呼叫 scripts/secret_scan.py --staged 且無 bypass
    hook_path = os.path.join(root_dir, ".githooks", "pre-commit")
    if not os.path.exists(hook_path):
        fails.append(".githooks/pre-commit:0  追蹤之 pre-commit hook 檔案不存在")
    else:
        try:
            with open(hook_path, "r", encoding="utf-8") as f:
                hook_text = f.read()
            if "scripts/secret_scan.py --staged" not in hook_text:
                fails.append(".githooks/pre-commit:0  Hook 未呼叫 scripts/secret_scan.py --staged")
            if "--no-verify" in hook_text:
                fails.append(".githooks/pre-commit:0  Hook 包含禁止之 --no-verify 標記")
            infos.append("Git hook .githooks/pre-commit 存在且呼叫 staged secret scanner")
        except Exception as e:
            fails.append(f".githooks/pre-commit:0  讀取失敗: {e}")

    # F & G: 執行 secret_scan tracked-mode 邏輯，確認零 findings，且 failure 訊息不得含 raw secret
    try:
        scripts_dir = os.path.join(root_dir, "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import secret_scan
        findings = secret_scan.run_tracked_scan(root_dir)
        if findings:
            for det_id, p, line_no in findings:
                fails.append(f"{p}:{line_no}  [SECRET_SCAN BLOCK] 偵測到疑似機敏資訊或禁止檔案 (detector={det_id})")
        else:
            infos.append("全庫 Tracked 檔案機密掃描通過，零機敏特徵命中")
    except Exception as e:
        fails.append(f"scripts/secret_scan.py:0  Tracked 機敏掃描執行失敗: {e}")

    return fails, infos


def _has_unquoted_pipeline(cmd_text: str) -> bool:
    """偵測 shell 指令字串中是否存在未加引號之 pipeline 運算子 (| 或 |&)。"""
    if not cmd_text:
        return False
    cleaned = re.sub(r'\$\{\{.*?\}\}', ' ', cmd_text)
    for line in cleaned.splitlines():
        in_sq = False
        in_dq = False
        escaped = False
        code_chars = []
        for ch in line:
            if escaped:
                code_chars.append(ch)
                escaped = False
                continue
            if ch == '\\':
                escaped = True
                code_chars.append(ch)
                continue
            if ch == "'" and not in_dq:
                in_sq = not in_sq
                code_chars.append(ch)
                continue
            if ch == '"' and not in_sq:
                in_dq = not in_dq
                code_chars.append(ch)
                continue
            if ch == '#' and not in_sq and not in_dq:
                break
            code_chars.append(ch)

        line_code = ''.join(code_chars)

        in_sq = False
        in_dq = False
        escaped = False
        i = 0
        n = len(line_code)
        while i < n:
            ch = line_code[i]
            if escaped:
                escaped = False
                i += 1
                continue
            if ch == '\\':
                escaped = True
                i += 1
                continue
            if ch == "'" and not in_dq:
                in_sq = not in_sq
                i += 1
                continue
            if ch == '"' and not in_sq:
                in_dq = not in_dq
                i += 1
                continue
            if not in_sq and not in_dq:
                if ch == '|':
                    if i + 1 < n and line_code[i+1] == '|':
                        i += 2
                        continue
                    return True
            i += 1
    return False


def _establishes_pipefail(cmd_text: str) -> bool:
    """檢查指令文字中是否於管線執行前宣告 set -o pipefail。"""
    if not cmd_text:
        return False
    for line in cmd_text.splitlines():
        stripped = line.strip()
        if re.search(r'\bset\s+-[a-zA-Z0-9_-]*o\s+pipefail\b', stripped) or re.search(r'\bset\s+-o\s+pipefail\b', stripped):
            return True
    return False


def _parse_workflow_jobs_and_steps(wf_content: str) -> dict:
    """確定性解析 GitHub Actions 工作流程中的 jobs 與 steps。"""
    lines = wf_content.splitlines()
    in_jobs = False
    current_job = None
    current_step = None
    jobs = {}

    in_multiline_run = False
    run_indent = 0
    run_lines = []

    for line_no, raw_line in enumerate(lines, 1):
        stripped = raw_line.strip()
        indent = len(raw_line) - len(raw_line.lstrip())

        if in_multiline_run:
            if not stripped:
                run_lines.append("")
                continue
            if indent >= run_indent:
                run_lines.append(raw_line.strip())
                continue
            else:
                if current_step:
                    current_step['run'] = "\n".join(run_lines)
                in_multiline_run = False
                run_lines = []

        if not stripped or stripped.startswith("#"):
            continue

        if raw_line.startswith("jobs:"):
            in_jobs = True
            current_job = None
            current_step = None
            continue

        if not in_jobs:
            continue

        if indent == 2 and stripped.endswith(":") and not stripped.startswith("-"):
            job_name = stripped[:-1].strip()
            current_job = {
                'name': job_name,
                'line_no': line_no,
                'continue_on_error': False,
                'if': None,
                'steps': []
            }
            jobs[job_name] = current_job
            current_step = None
            continue

        if current_job is None:
            continue

        if indent == 4 and not stripped.startswith("-"):
            if stripped.startswith("continue-on-error:"):
                val = stripped.split(":", 1)[1].strip().lower()
                current_job['continue_on_error'] = (val == "true")
            elif stripped.startswith("if:"):
                current_job['if'] = stripped.split(":", 1)[1].strip()
            continue

        if stripped.startswith("- "):
            if in_multiline_run and current_step:
                current_step['run'] = "\n".join(run_lines)
                in_multiline_run = False
                run_lines = []

            current_step = {
                'line_no': line_no,
                'name': None,
                'uses': None,
                'run': None,
                'shell': None,
                'continue_on_error': False,
                'if': None
            }
            current_job['steps'].append(current_step)
            step_part = stripped[2:].strip()
            if step_part.startswith("name:"):
                current_step['name'] = step_part.split(":", 1)[1].strip().strip('"').strip("'")
            elif step_part.startswith("uses:"):
                current_step['uses'] = step_part.split(":", 1)[1].strip()
            elif step_part.startswith("run:"):
                run_val = step_part.split(":", 1)[1].strip()
                if run_val in ("|", "|-", "|+", ">", ">-", ">+"):
                    in_multiline_run = True
                    run_indent = indent + 2
                    run_lines = []
                else:
                    current_step['run'] = run_val
            continue

        if current_step:
            if stripped.startswith("name:"):
                current_step['name'] = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            elif stripped.startswith("uses:"):
                current_step['uses'] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("shell:"):
                current_step['shell'] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("continue-on-error:"):
                val = stripped.split(":", 1)[1].strip().lower()
                current_step['continue_on_error'] = (val == "true")
            elif stripped.startswith("if:"):
                current_step['if'] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("run:"):
                run_val = stripped.split(":", 1)[1].strip()
                if run_val in ("|", "|-", "|+", ">", ">-", ">+"):
                    in_multiline_run = True
                    run_indent = indent + 2
                    run_lines = []
                else:
                    current_step['run'] = run_val

    if in_multiline_run and current_step:
        current_step['run'] = "\n".join(run_lines)

    return jobs


def check_22_ci_supply_chain(root_dir=None):
    """CHECK 22 — CI 供應鏈可重現性與管道安全守衛 (CI Supply-Chain Reproducibility & Pipeline Guard)。"""
    if root_dir is None:
        root_dir = repo_root
    fails = []
    infos = []

    # 1. 檢驗 .github/workflows/verify.yml
    workflow_path = os.path.join(root_dir, ".github", "workflows", "verify.yml")
    if not os.path.exists(workflow_path):
        fails.append(".github/workflows/verify.yml:0  CI workflow 檔案不存在")
    else:
        try:
            with open(workflow_path, "r", encoding="utf-8") as f:
                wf_lines = f.readlines()

            has_top_level_contents_read = False
            in_top_permissions = False
            before_jobs = True

            for line_no, raw_line in enumerate(wf_lines, 1):
                stripped = raw_line.strip()
                indent = len(raw_line) - len(raw_line.lstrip())

                if raw_line.startswith("jobs:"):
                    before_jobs = False
                    in_top_permissions = False

                if before_jobs:
                    if raw_line.startswith("permissions:"):
                        in_top_permissions = True
                        if "contents: read" in raw_line or "contents:read" in raw_line:
                            has_top_level_contents_read = True
                        continue
                    elif in_top_permissions and indent > 0:
                        if stripped.startswith("contents:") and "read" in stripped:
                            has_top_level_contents_read = True
                    elif in_top_permissions and indent == 0 and stripped:
                        in_top_permissions = False

                # 檢查寫入權限 (write permission)
                if re.search(r":\s*write\b", stripped):
                    fails.append(f".github/workflows/verify.yml:{line_no}  工作流程包含未授權之寫入權限: {stripped}")

                # 檢查 first-party Actions 是否使用 40-hex SHA
                if "uses:" in stripped:
                    uses_part = stripped.split("uses:", 1)[1].strip().split("#")[0].strip()
                    for act in ["actions/checkout", "actions/setup-node", "actions/setup-python"]:
                        if uses_part.startswith(act):
                            if "@" not in uses_part:
                                fails.append(f".github/workflows/verify.yml:{line_no}  Action '{act}' 缺少版本/SHA: {uses_part}")
                            else:
                                ref = uses_part.split("@", 1)[1].strip()
                                if not re.fullmatch(r"^[0-9a-fA-F]{40}$", ref):
                                    fails.append(f".github/workflows/verify.yml:{line_no}  Action '{act}' 未固定至 40-hex commit SHA (實際為 '{ref}')")

            if not has_top_level_contents_read:
                fails.append(".github/workflows/verify.yml:0  工作流程缺少頂層 'permissions: contents: read' 宣告")
            else:
                infos.append(".github/workflows/verify.yml 頂層權限驗證通過 (contents: read, zero write)")

            # 2. 檢驗 CI 管道 Fail-Closed 與必要閘門不變量 (D-U10 Pipeline Guard & Required Gate Integrity)
            wf_content = "".join(wf_lines)
            jobs = _parse_workflow_jobs_and_steps(wf_content)
            required_jobs = {"verify", "gateway-windows"}

            for job_name, job in jobs.items():
                is_req_job = job_name in required_jobs

                # (a) 必要 job 不得設 continue-on-error: true 或條件跳過
                if is_req_job:
                    if job.get("continue_on_error"):
                        fails.append(f".github/workflows/verify.yml:{job['line_no']}  必要驗證工作 '{job_name}' 包含禁止之 'continue-on-error: true'")
                    if job.get("if"):
                        fails.append(f".github/workflows/verify.yml:{job['line_no']}  必要驗證工作 '{job_name}' 包含禁止之條件式跳過 'if: {job['if']}'")

                for step in job["steps"]:
                    s_name = step.get("name") or f"Line {step['line_no']}"
                    s_run = step.get("run")
                    s_shell = step.get("shell")
                    s_coe = step.get("continue_on_error")
                    s_if = step.get("if")

                    # (b) 必要 job 中的步驟 continue-on-error
                    if is_req_job and s_coe:
                        fails.append(f".github/workflows/verify.yml:{step['line_no']}  必要工作 '{job_name}' 步驟 '{s_name}' 包含禁止之 'continue-on-error: true'")

                    # (c) 必要驗證步驟不得條件式跳過 (允許獨立診斷步驟使用 if: failure())
                    if is_req_job and s_if:
                        is_diagnostic = (s_if.strip() == "failure()")
                        is_primary_gate = (s_name == "Run verification gates" or (s_run and "verify_all.py" in s_run))
                        if is_primary_gate or not is_diagnostic:
                            fails.append(f".github/workflows/verify.yml:{step['line_no']}  必要驗證步驟 '{s_name}' 包含禁止之條件式跳過 'if: {s_if}'")

                    # (d) Shell pipeline 必須具備 fail-closed 語意 (shell: bash 或 set -o pipefail)
                    if s_run and _has_unquoted_pipeline(s_run):
                        has_pipefail = (s_shell == "bash" or _establishes_pipefail(s_run))
                        if not has_pipefail:
                            fails.append(f".github/workflows/verify.yml:{step['line_no']}  步驟 '{s_name}' 包含未保護之 shell pipeline（缺少 'shell: bash' 或 'set -o pipefail'）: '{s_run.strip()}'")

            infos.append(".github/workflows/verify.yml 工作流程管道與必要閘門 fail-closed 驗證通過")

        except Exception as e:
            fails.append(f".github/workflows/verify.yml:0  檔案讀取失敗: {e}")

    # 3. 檢驗 requirements.txt
    req_path = os.path.join(root_dir, "requirements.txt")
    if not os.path.exists(req_path):
        fails.append("requirements.txt:0  requirements.txt 檔案不存在")
    else:
        try:
            with open(req_path, "r", encoding="utf-8") as f:
                req_lines = f.readlines()
            active_deps = 0
            for line_no, raw_line in enumerate(req_lines, 1):
                clean_line = raw_line.split("#", 1)[0].strip()
                if not clean_line:
                    continue
                pkg_spec = clean_line.split(";", 1)[0].strip()
                if "==" not in pkg_spec or any(op in pkg_spec for op in [">=", "<=", "~=", "!="]) or (">" in pkg_spec and "==" not in pkg_spec) or ("<" in pkg_spec and "==" not in pkg_spec):
                    fails.append(f"requirements.txt:{line_no}  相依套件未固定精確版本 (必須包含 '==' 且不得使用範圍或通配符): '{clean_line}'")
                else:
                    parts = pkg_spec.split("==")
                    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip() or "*" in parts[1]:
                        fails.append(f"requirements.txt:{line_no}  相依套件版本格式非法: '{clean_line}'")
                    else:
                        active_deps += 1
            infos.append(f"requirements.txt 共驗證 {active_deps} 項精確鎖定之相依套件")
        except Exception as e:
            fails.append(f"requirements.txt:0  檔案讀取失敗: {e}")

    return fails, infos


def check_23_transport_exclusivity_guard(repo_root=None):
    """CHECK 23 — 傳輸能力與合約一致性守衛 (Transport Capability / Contract Exclusivity Guard)。
    防止 active contract 重新形成排他性 transport lock-in（例如將某一 adapter 描述為唯一、只能、only 等），
    確保以 K1 Transport-Neutral Exact-SHA Invariant 作為 correctness authority。
    """
    if repo_root is None:
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    active_files = [
        ".agents/rules/git-and-reporting.md",
        ".agents/rules/prompt-preflight.md",
        ".claude/rules/auditor-protocol.md",
        ".claude/rules/auditor-selftest.md",
        "SOP/SOP_14_Rigorous_Verification_and_Audit_Protocol.md",
        "docs/TASKBOARD.md",
    ]

    exclusive_patterns = [
        (re.compile(r"(?:只能|僅能|只允許|僅允許|唯一允許)\s*(?:[^\n，。；;]{0,30})update_ref", re.IGNORECASE), "排他性 update_ref 指令/描述"),
        (re.compile(r"update_ref\s*(?:[^\n，。；;]{0,30})(?:是唯一|為唯一|是目前唯一)", re.IGNORECASE), "update_ref 被描述為唯一傳輸機制"),
        (re.compile(r"(?:only\s+allowed\s+through|only\s+through|solely\s+through|required\s+sole\s+path\s+is)\s*(?:[^\n,.;]{0,30})update_ref", re.IGNORECASE), "exclusive update_ref binding"),
        (re.compile(r"\bupdate_ref\b\s+is\s+(?:the\s+)?(?:only|sole|exclusive)\b", re.IGNORECASE), "update_ref declared as only transport"),
        (re.compile(r"\b(?:only|exclusive)\s+update_ref\b", re.IGNORECASE), "exclusive update_ref"),
        (re.compile(r"main\s*(?:ref)?\s*(?:更新|推進)?\s*(?:只能|唯一|只允許)\s*(?:[^\n，。；;]{0,30})update_ref", re.IGNORECASE), "main ref 更新排他性綁定 update_ref"),
        (re.compile(r"rollback\s*(?:只能|只允許)\s*(?:[^\n，。；;]{0,30})update_ref", re.IGNORECASE), "rollback 排他性綁定 update_ref"),
        (re.compile(r"回滾\s*(?:只能|只允許)\s*(?:[^\n，。；;]{0,30})update_ref", re.IGNORECASE), "回滾排他性綁定 update_ref"),
    ]

    fails = []
    infos = []
    scanned_count = 0

    for rel_path in active_files:
        full_path = os.path.join(repo_root, rel_path)
        if not os.path.exists(full_path):
            continue
        scanned_count += 1
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    for pat, desc in exclusive_patterns:
                        if pat.search(line):
                            fails.append(f"{rel_path}:{line_no}  {desc}: '{line.strip()}'")
        except Exception as e:
            fails.append(f"{rel_path}:0  讀取失敗: {e}")

    if not fails:
        infos.append(f"掃描 {scanned_count} 個 active contract 檔案，零排他性 transport lock-in 命中")

    return fails, infos


def check_24_active_state_projection_guard(repo_root=None):
    """CHECK 24 — 活動狀態投影漂移守衛 (Active State Projection Drift Guard)。

    防止同一 active lifecycle 同時宣告互斥 current states（例如 new transport contract active 同時宣稱現行維持 protected PR 生產傳輸模式，或宣稱 main 未來必須 Require PR）。
    結構化掃描作用面：
    - docs/TASKBOARD.md 僅掃描：**最後更新**、| B-103 |、| C-06 |、| TG-MVP-01B |
    - docs/refactor-backlog.md 僅掃描：§5.3 與 §5.4
    不掃描歷史 append-only 紀錄。
    """
    if repo_root is None:
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    stale_patterns = [
        (re.compile(r"現行維持\s*protected PR\s*生產傳輸(?:模式)?", re.IGNORECASE), "過期活動狀態投影 (現行維持 protected PR 生產傳輸模式)"),
        (re.compile(r"維持\s*protected PR\s*生產傳輸", re.IGNORECASE), "過期活動狀態投影 (維持 protected PR 生產傳輸)"),
        (re.compile(r"本批維持現行\s*PR\s*模式", re.IGNORECASE), "過期活動狀態投影 (本批維持現行 PR 模式)"),
        (re.compile(r"main\s*(?:未來)?必須.*?Require PR", re.IGNORECASE), "過期活動狀態投影 (main 未來必須 Require PR)"),
    ]

    fails = []
    infos = []

    # 1. 檢驗 docs/TASKBOARD.md 活動區域
    tb_path = os.path.join(repo_root, "docs", "TASKBOARD.md")
    if os.path.exists(tb_path):
        try:
            with open(tb_path, "r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    line_s = line.strip()
                    is_blocking_surface = (
                        line_s.startswith("**最後更新**") or
                        line_s.startswith("| B-103 |") or
                        line_s.startswith("| C-06 |") or
                        line_s.startswith("| TG-MVP-01B |")
                    )
                    if is_blocking_surface:
                        for pat, desc in stale_patterns:
                            if pat.search(line):
                                fails.append(f"docs/TASKBOARD.md:{line_no}  {desc}: '{line.strip()}'")
            if not any(f.startswith("docs/TASKBOARD.md") for f in fails):
                infos.append("docs/TASKBOARD.md 活動狀態投影一致，無過期 protected PR 模式宣告")
        except Exception as e:
            fails.append(f"docs/TASKBOARD.md:0  讀取失敗: {e}")

    # 2. 檢驗 docs/refactor-backlog.md 可變交接區 (§5.3 與 §5.4)
    rb_path = os.path.join(repo_root, "docs", "refactor-backlog.md")
    if os.path.exists(rb_path):
        try:
            with open(rb_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            in_blocking_sec = False
            for line_no, line in enumerate(lines, 1):
                if line.startswith("### 5.3") or line.startswith("### 5.4") or line.startswith("§5.3") or line.startswith("§5.4"):
                    in_blocking_sec = True
                elif in_blocking_sec and (line.startswith("## ") or (line.startswith("### ") and not (line.startswith("### 5.3") or line.startswith("### 5.4"))) or re.match(r"^\d+\.\s+\*\*", line)):
                    in_blocking_sec = False
                if in_blocking_sec:
                    for pat, desc in stale_patterns:
                        if pat.search(line):
                            fails.append(f"docs/refactor-backlog.md:{line_no}  {desc}: '{line.strip()}'")
            if not any(f.startswith("docs/refactor-backlog.md") for f in fails):
                infos.append("docs/refactor-backlog.md §5 可變狀態投影一致，無過期 protected PR 模式宣告")
        except Exception as e:
            fails.append(f"docs/refactor-backlog.md:0  讀取失敗: {e}")

    return fails, infos


def check_25_mechanical_governance(root_dir=None):
    """CHECK 25 — Mechanical Governance v1 Integrity Guard。
    驗證機器治理 v1 核心組件、規則註冊表、執行合約守衛、Git hooks 與環境基準完整性。
    """
    if root_dir is None:
        root_dir = repo_root

    fails = []
    infos = []

    # 1. docs/governance/rule-registry.json
    reg_path = os.path.join(root_dir, "docs", "governance", "rule-registry.json")
    if not os.path.exists(reg_path):
        fails.append("docs/governance/rule-registry.json:0  規則註冊表檔案不存在")
    else:
        try:
            with open(reg_path, "r", encoding="utf-8") as f:
                reg = json.load(f)
            if reg.get("schema_version") != 1:
                fails.append(f"docs/governance/rule-registry.json: schema_version 必須為 1 (實際: {reg.get('schema_version')})")
            reg_ver = reg.get("registry_version")
            if reg_ver not in ("B109-M1", "B109-M2"):
                fails.append(f"docs/governance/rule-registry.json: registry_version 必須為 'B109-M1' 或 'B109-M2' (實際: {reg_ver})")
            rules = reg.get("rules", [])
            if not isinstance(rules, list):
                fails.append("docs/governance/rule-registry.json: 'rules' 必須為陣列")
            else:
                rule_ids = [r.get("id") for r in rules if isinstance(r, dict) and "id" in r]
                if reg_ver == "B109-M2":
                    expected_ids = [f"GOV-M1-{i:03d}" for i in range(1, 14)] + [f"GOV-M2-{i:03d}" for i in range(1, 9)]
                else:
                    expected_ids = [f"GOV-M1-{i:03d}" for i in range(1, 14)]
                if len(rule_ids) != len(set(rule_ids)):
                    fails.append("docs/governance/rule-registry.json: 包含重複的 Rule ID")
                missing_ids = set(expected_ids) - set(rule_ids)
                if missing_ids:
                    fails.append(f"docs/governance/rule-registry.json: 缺少預期 Rule IDs: {sorted(missing_ids)}")
                extra_ids = set(rule_ids) - set(expected_ids)
                if extra_ids:
                    fails.append(f"docs/governance/rule-registry.json: 包含未授權額外 Rule IDs: {sorted(extra_ids)}")
                if rule_ids == expected_ids:
                    infos.append(f"rule-registry.json 存在且 {reg_ver} 規則清單驗證通過 (共 {len(rule_ids)} 條)")
        except Exception as e:
            fails.append(f"docs/governance/rule-registry.json:0  解析失敗: {e}")

    # 2. scripts/governance_preflight.py exists
    gov_preflight = os.path.join(root_dir, "scripts", "governance_preflight.py")
    if not os.path.exists(gov_preflight):
        fails.append("scripts/governance_preflight.py:0  檔案不存在")
    else:
        infos.append("scripts/governance_preflight.py 存在")

    # 3. .githooks/pre-push exists, first line #!/bin/sh, references governance_preflight
    pre_push = os.path.join(root_dir, ".githooks", "pre-push")
    if not os.path.exists(pre_push):
        fails.append(".githooks/pre-push:0  檔案不存在")
    else:
        try:
            with open(pre_push, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if not lines or not lines[0].startswith("#!/bin/sh"):
                fails.append(".githooks/pre-push:1  第一行必須為 '#!/bin/sh'")
            content = "".join(lines)
            if "governance_preflight" not in content:
                fails.append(".githooks/pre-push:0  未引用 governance_preflight")
            else:
                infos.append(".githooks/pre-push 存在且首行為 #!/bin/sh 並引用 governance_preflight")
        except Exception as e:
            fails.append(f".githooks/pre-push:0  讀取失敗: {e}")

    # 4. install_git_hooks requires pre-commit and pre-push
    install_hooks = os.path.join(root_dir, "scripts", "install_git_hooks.py")
    if not os.path.exists(install_hooks):
        fails.append("scripts/install_git_hooks.py:0  檔案不存在")
    else:
        try:
            with open(install_hooks, "r", encoding="utf-8") as f:
                ih_content = f.read()
            if "pre-commit" not in ih_content or "pre-push" not in ih_content:
                fails.append("scripts/install_git_hooks.py:0  未同時要求 pre-commit 與 pre-push")
            else:
                infos.append("scripts/install_git_hooks.py 同時要求 pre-commit 與 pre-push")
        except Exception as e:
            fails.append(f"scripts/install_git_hooks.py:0  讀取失敗: {e}")

    # 5. prompt-preflight requires Execution Contract
    pp_file = os.path.join(root_dir, ".agents", "rules", "prompt-preflight.md")
    if not os.path.exists(pp_file):
        fails.append(".agents/rules/prompt-preflight.md:0  檔案不存在")
    else:
        try:
            with open(pp_file, "r", encoding="utf-8") as f:
                pp_content = f.read()
            if "BEGIN_HHAI_EXECUTION_CONTRACT" not in pp_content or "Execution Contract" not in pp_content:
                fails.append(".agents/rules/prompt-preflight.md:0  未包含 Execution Contract 必要要求")
            else:
                infos.append(".agents/rules/prompt-preflight.md 要求 Execution Contract")
        except Exception as e:
            fails.append(f".agents/rules/prompt-preflight.md:0  讀取失敗: {e}")

    # 6. auditor-selftest contains E25
    ast_file = os.path.join(root_dir, ".claude", "rules", "auditor-selftest.md")
    if not os.path.exists(ast_file):
        fails.append(".claude/rules/auditor-selftest.md:0  檔案不存在")
    else:
        try:
            with open(ast_file, "r", encoding="utf-8") as f:
                ast_content = f.read()
            if "E25" not in ast_content:
                fails.append(".claude/rules/auditor-selftest.md:0  未包含 E25 檢核項目")
            else:
                infos.append(".claude/rules/auditor-selftest.md 包含 E25")
        except Exception as e:
            fails.append(f".claude/rules/auditor-selftest.md:0  讀取失敗: {e}")

    # 7. git-and-reporting contains: git switch -c convention, main exact-SHA guard, remote delete exact-set guard
    gar_file = os.path.join(root_dir, ".agents", "rules", "git-and-reporting.md")
    if not os.path.exists(gar_file):
        fails.append(".agents/rules/git-and-reporting.md:0  檔案不存在")
    else:
        try:
            with open(gar_file, "r", encoding="utf-8") as f:
                gar_content = f.read()
            if "git switch -c" not in gar_content:
                fails.append(".agents/rules/git-and-reporting.md:0  未包含 'git switch -c' 分支建立慣例")
            if "main" not in gar_content.lower() or ("exact-sha" not in gar_content.lower() and "exact sha" not in gar_content.lower()):
                fails.append(".agents/rules/git-and-reporting.md:0  未包含 main advancement exact-SHA guard")
            if "exact-set" not in gar_content.lower() and "remote ref deletion" not in gar_content.lower():
                fails.append(".agents/rules/git-and-reporting.md:0  未包含 remote delete exact-set guard")
            infos.append(".agents/rules/git-and-reporting.md 包含 git switch -c、main exact-SHA 與 remote delete exact-set 規範")
        except Exception as e:
            fails.append(f".agents/rules/git-and-reporting.md:0  讀取失敗: {e}")

    # 8. environment baseline checks
    bl_file = os.path.join(root_dir, "docs", "ops", "antigravity-environment-baseline.md")
    if not os.path.exists(bl_file):
        fails.append("docs/ops/antigravity-environment-baseline.md:0  檔案不存在")
    else:
        try:
            with open(bl_file, "r", encoding="utf-8") as f:
                bl_content = f.read()
            required_bl_markers = [
                ("PERSISTENT LAYER", "PERSISTENT LAYER 分層宣告"),
                ("NON-PERSISTENT / DEPRECATED LAYER", "NON-PERSISTENT / DEPRECATED LAYER 分層宣告"),
                ("Advanced Command Access", "Advanced Command Access 區塊"),
                ("Terminal Commands", "Terminal Commands 區塊"),
                ("github.com", "github.com Execute URL 限制"),
                ("Deny", "Deny 設定說明"),
            ]
            for marker, desc in required_bl_markers:
                if marker not in bl_content:
                    fails.append(f"docs/ops/antigravity-environment-baseline.md:0  缺少必要標記: {desc} ('{marker}')")

            # Check 12 entries mentioned
            twelve_entries = [
                "--delete", "git branch -D", "git checkout", "git clean",
                "git commit --amend", "git credential", "git rebase", "git reset",
                "git restore", "git stash", "git switch --discard-changes", "git switch -C"
            ]
            missing_entries = [e for e in twelve_entries if e not in bl_content]
            if missing_entries:
                fails.append(f"docs/ops/antigravity-environment-baseline.md:0  12 項 Deny 清單缺少項目: {missing_entries}")

            # Warning: do not delete github.com
            if "不得" not in bl_content and "do not delete" not in bl_content.lower():
                fails.append("docs/ops/antigravity-environment-baseline.md:0  缺少不得刪除 github.com entry 之明確警告")

            # old Deny List deprecated
            if "DEPRECATED" not in bl_content:
                fails.append("docs/ops/antigravity-environment-baseline.md:0  缺少舊 Deny List 棄用宣告 (DEPRECATED)")

            # Triggers: new computer, reinstall, IDE update
            bl_lower = bl_content.lower()
            if "新電腦" not in bl_content and "new computer" not in bl_lower:
                fails.append("docs/ops/antigravity-environment-baseline.md:0  缺少新電腦觸發 (new computer trigger)")
            if "重新安裝" not in bl_content and "reinstall" not in bl_lower:
                fails.append("docs/ops/antigravity-environment-baseline.md:0  缺少重新安裝觸發 (reinstall trigger)")
            if "更新" not in bl_content and "update" not in bl_lower:
                fails.append("docs/ops/antigravity-environment-baseline.md:0  缺少 IDE 更新觸發 (IDE update trigger)")

            # Restart verification
            if "重啟" not in bl_content and "restart" not in bl_lower:
                fails.append("docs/ops/antigravity-environment-baseline.md:0  缺少重啟核對程序 (restart verification)")

            # Direct vs inferred persistence distinction
            if "推論" not in bl_content and "inferred" not in bl_lower and "inference" not in bl_lower:
                fails.append("docs/ops/antigravity-environment-baseline.md:0  缺少直接測試 vs 同機制推論之精確度區分")

            infos.append("docs/ops/antigravity-environment-baseline.md 包含雙層架構、12 Deny 清單、觸發機制與重啟驗證")
        except Exception as e:
            fails.append(f"docs/ops/antigravity-environment-baseline.md:0  讀取失敗: {e}")

    # 9. TASKBOARD contains environment recovery trigger
    tb_file = os.path.join(root_dir, "docs", "TASKBOARD.md")
    if not os.path.exists(tb_file):
        fails.append("docs/TASKBOARD.md:0  檔案不存在")
    else:
        try:
            with open(tb_file, "r", encoding="utf-8") as f:
                tb_content = f.read()
            if "antigravity-environment-baseline.md" not in tb_content:
                fails.append("docs/TASKBOARD.md:0  缺少 environment recovery trigger (未參照 antigravity-environment-baseline.md)")
            else:
                infos.append("docs/TASKBOARD.md 包含 environment recovery trigger 參照")
        except Exception as e:
            fails.append(f"docs/TASKBOARD.md:0  讀取失敗: {e}")

    return fails, infos


check_25_mechanical_governance_v1_guard = check_25_mechanical_governance


def check_26_plan_actual_evidence_integrity(root_dir=None, as_if_committed=False):
    """
    CHECK 26 — M2 計畫與執行重放暨證據完整性守衛 (M2 Plan-vs-Actual / Evidence Integrity Replay Guard).

    A. docs/governance/execution-record.json exists
    B. Calls execution_record.verify_execution_record_file(as_if_committed=as_if_committed)
    C. Validates all plan-vs-actual invariants, fresh Git diff replay, REG-11/12/13
    """
    if root_dir is None:
        root_dir = repo_root
    fails = []
    infos = []

    rec_rel = os.path.join("docs", "governance", "execution-record.json")
    rec_abs = os.path.join(root_dir, rec_rel)
    if not os.path.exists(rec_abs):
        fails.append(f"{rec_rel}:0  執行紀錄檔案不存在")
        return fails, infos

    try:
        from scripts.execution_record import verify_execution_record_file
    except ImportError:
        import execution_record
        verify_execution_record_file = execution_record.verify_execution_record_file

    ok, msg = verify_execution_record_file(rec_rel, repo_root=root_dir, as_if_committed=as_if_committed)
    if not ok:
        fails.append(f"{rec_rel}: {msg}")
    else:
        infos.append("execution-record.json: Plan-vs-Actual exact replay, REG-11/12/13 integrity verified")

    return fails, infos


check_26_plan_actual_evidence_integrity_guard = check_26_plan_actual_evidence_integrity


def verify_check_consistency_inventory(file_content: str) -> tuple[bool, str, dict]:
    """
    Validates complete, consistent, and duplicate-free inventory (1..26)
    across docstring and run_checks(). Supports both 'CHECK N -' and 'CHECK N:' punctuations.
    """
    # 1. Parse docstring inventory
    docstring_match = re.search(r'"""(.*?)"""', file_content, re.DOTALL)
    if not docstring_match:
        return False, "Could not find module docstring", {}
    docstring_text = docstring_match.group(1)

    docstring_ids = []
    seen_doc_ids = set()
    for m in re.finditer(r'CHECK\s+(\d+)\s*[-—:]', docstring_text):
        cid = int(m.group(1))
        if cid in seen_doc_ids:
            return False, f"Duplicate CHECK {cid} in docstring inventory", {}
        seen_doc_ids.add(cid)
        docstring_ids.append(cid)

    # 2. Parse run_checks() body
    run_checks_match = re.search(r'def run_checks\([^)]*\):(.*?)(?=\ndef [a-zA-Z0-9_]+|\Z)', file_content, re.DOTALL)
    if not run_checks_match:
        return False, "Could not find run_checks() function", {}
    run_checks_text = run_checks_match.group(1)

    # total_checks
    tc_match = re.search(r'total_checks\s*=\s*(\d+)', run_checks_text)
    if not tc_match:
        return False, "total_checks assignment not found in run_checks()", {}
    total_checks = int(tc_match.group(1))

    run_checks_ids = []
    seen_rc_ids = set()
    for m in re.finditer(r'print\(["\'](?:\\n)?CHECK\s+(\d+)\s*[-—:]', run_checks_text):
        cid = int(m.group(1))
        if cid in seen_rc_ids:
            return False, f"Duplicate CHECK {cid} in run_checks()", {}
        seen_rc_ids.add(cid)
        run_checks_ids.append(cid)

    expected_ids = list(range(1, 27))
    if total_checks != 26:
        return False, f"total_checks must be 26 (got {total_checks})", {}

    if docstring_ids != expected_ids:
        missing = set(expected_ids) - set(docstring_ids)
        extra = set(docstring_ids) - set(expected_ids)
        return False, f"Docstring inventory mismatch (missing={sorted(list(missing))}, extra={sorted(list(extra))})", {}

    if run_checks_ids != expected_ids:
        missing = set(expected_ids) - set(run_checks_ids)
        extra = set(run_checks_ids) - set(expected_ids)
        return False, f"run_checks() inventory mismatch (missing={sorted(list(missing))}, extra={sorted(list(extra))})", {}

    return True, "", {
        "total_checks": total_checks,
        "docstring_ids": docstring_ids,
        "run_checks_ids": run_checks_ids,
    }


if __name__ == "__main__":
    run_checks()

