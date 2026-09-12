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
  CHECK 12 — AUDIT-LOG 審查週期落後
  CHECK 13 — 檔尾換行符
  CHECK 14 — 繁體中文環境下的簡體字偵測
  CHECK 15 — 交接區 §5.1 的 commit hash 語境衝突
  CHECK 16 — 執行者檢查紀錄（EXEC-LOG）落後偵測

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
    total_checks = 16
    passed = 0
    failed = 0
    
    # ---------------------------------------------------------
    # CHECK 1: 控制字元
    # ---------------------------------------------------------
    print("CHECK 1 - 控制字元")
    c1_fails = []
    for root, dirs, files in os.walk(repo_root):
        if ".git" in root or ".venv" in root or "node_modules" in root:
            continue
        for file in files:
            if file.endswith(".md") or file.endswith(".json"):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        for i, line in enumerate(f):
                            if chr(27) in line:
                                rel_path = os.path.relpath(filepath, repo_root).replace("\\", "/")
                                c1_fails.append(f"{rel_path}:{i+1}  找到 ESC 控制字元")
                except:
                    pass
    
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
    c2_fails = []
    for root, dirs, files in os.walk(repo_root):
        if ".git" in root or ".venv" in root or "node_modules" in root:
            continue
        for file in files:
            if file.endswith(".md"):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        lines = f.read().splitlines()
                        fence_count = sum(1 for l in lines if l.strip().startswith("```"))
                        if fence_count % 2 != 0:
                            rel_path = os.path.relpath(filepath, repo_root).replace("\\", "/")
                            c2_fails.append(f"{rel_path}:0  圍欄數為奇數 ({fence_count})")
                except:
                    pass

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
    c5_fails = []
    sop_index_path = os.path.join(repo_root, "SOP", "SOP_00A_Master_Index.json")
    
    if not os.path.exists(sop_index_path):
        c5_fails.append(f"SOP/SOP_00A_Master_Index.json:0  檔案不存在")
    else:
        try:
            with open(sop_index_path, "r", encoding="utf-8") as f:
                sop_data = json.load(f)
                
            routes = sop_data.get("special_trigger_routes", {})
            for key, val in routes.items():
                target = val.split('#')[0]
                if target.startswith("PENDING_MIGRATION:"):
                    print(f"  [INFO] 略過未遷移路由: {key} -> {val}")
                    continue
                target_abs = os.path.normpath(os.path.join(repo_root, target))
                if not os.path.exists(target_abs):
                    c5_fails.append(f"SOP/SOP_00A_Master_Index.json:0  路由目標不存在: {val}")
                    
            tags = sop_data.get("tags", {})
            seen_sop = set()
            for key, val_list in tags.items():
                for fname in val_list:
                    if fname in seen_sop:
                        continue
                    seen_sop.add(fname)
                    target_abs = os.path.join(repo_root, "SOP", fname)
                    if not os.path.exists(target_abs):
                        c5_fails.append(
                            f"SOP/SOP_00A_Master_Index.json:0  SOP 檔案不存在: {fname} (tag: {key})")
        except Exception as e:
            c5_fails.append(f"SOP/SOP_00A_Master_Index.json:0  解析錯誤: {e}")

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
    c6_fails = []
    old_paths = ["01_Orchestrators", "02_Cognitive", "03_Execution", "05_Actions"]
    allowed_c6 = [
        "skills/platform/json-to-flex-renderer/SKILL.md"
    ]
    
    for root, dirs, files in os.walk(skills_dir):
        if ".git" in root or ".venv" in root or "node_modules" in root:
            continue
        for file in files:
            if file.endswith(".md"):
                filepath = os.path.join(root, file)
                rel_fp = os.path.relpath(filepath, repo_root).replace("\\", "/")
                
                # Check allowed list
                is_allowed = False
                if rel_fp in allowed_c6:
                    print(f"  [INFO] 略過已知殘留: {rel_fp} (原因: runtime 層尚未遷移，遷移完成後必須更新；見 docs/TASKBOARD.md F-06)")
                    is_allowed = True
                
                if not is_allowed:
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            for i, line in enumerate(f):
                                for op in old_paths:
                                    if op in line:
                                        c6_fails.append(f"{rel_fp}:{i+1}  殘留舊路徑: {op}")
                    except:
                        pass

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
    # CHECK 12: AUDIT-LOG 審查週期落後
    # ---------------------------------------------------------
    print("\nCHECK 12 - AUDIT-LOG 審查週期落後")
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
    for info in c13_infos:
        print(f"  [INFO] {info}")
    if len(c13_fails) == 0:
        print("  [PASS] 0 命中")
        passed += 1
    else:
        print(f"  [FAIL] {len(c13_fails)} 命中")
        for fail in c13_fails:
            print(f"    {fail}")
        failed += 1

    # ---------------------------------------------------------
    # CHECK 14: 繁體中文環境下的簡體字偵測
    # ---------------------------------------------------------
    print("\nCHECK 14 - 繁體中文環境下的簡體字偵測")
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
                except Exception:
                    pass
    return c3_fails, c3_infos


def check_8_taskboard_metadata_purity(root_dir=None, git_head=None, git_prev=None, git_prev2=None, as_if_committed=False):
    """CHECK 8 — 任務看板當前狀態 Metadata 純度。

    驗證 TASKBOARD.md 的『最後更新』標記為活動看板狀態標記：
    1. 存在唯一的『最後更新』標記。
    2. 包含有效日期 (YYYY-MM-DD) 與當前工作階段/狀態描述。
    3. 不得包含 Git HEAD、checkpoint、commit、pending range (..) 或任何 commit hash。
       Git 與審計狀態單一事實來源由 Git HEAD、AUDIT-LOG 與交接區 §5.1 擁有，
       防止將 Git truth 重新複製回看板產生第二事實來源。
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

    markers = []
    for idx, line in enumerate(lines, 1):
        if "**最後更新**：" in line:
            markers.append((idx, line.strip()))

    if len(markers) == 0:
        fails.append("docs/TASKBOARD.md:0  未找到『最後更新』標記")
        return fails, infos
    if len(markers) > 1:
        fails.append(f"docs/TASKBOARD.md: 找到多個『最後更新』標記 (共 {len(markers)} 個)")
        return fails, infos

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
                is_pass = ("通過" in summary or "pass" in summary.lower()) and not any(
                    neg in summary for neg in ["不通過", "NEEDS MICRO-FIX", "待微修", "CI failure", "failure"]
                )
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
        infos.append("無法取得 git 歷史資訊，略過 ancestry 比對")
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
        except Exception:
            continue

        headings = set()
        for l in lines:
            m = re.match(r'^#+\s+([0-9]+[a-z]?(?:\.[0-9]+[a-z]?)*)', l.strip())
            if m:
                headings.add(m.group(1))

        has_numeric_headings = len(headings) > 0

        for i, line in enumerate(lines, 1):
            refs = re.findall(r'§([0-9]+[a-z]?(?:\.[0-9]+[a-z]?)*)', line)
            if not refs:
                continue
            is_cross = (not has_numeric_headings) or any(ind in line for ind in cross_file_indicators)
            for sec in refs:
                if rel_fp.endswith("auditor-protocol.md") and sec in ["4.1", "4.2", "4.4"]:
                    is_cross = True
                if is_cross:
                    infos.append(f"{rel_fp}:{i}  跨檔案引用: §{sec}")
                else:
                    if sec not in headings:
                        fails.append(f"{rel_fp}:{i}  找不到章節標題: §{sec}")
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

def check_12_audit_log_cadence(root_dir=None, git_count=None):
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

    lag = 0
    if git_count is not None:
        lag = git_count
    else:
        try:
            res = subprocess.run(["git", "rev-list", "--count", f"{latest_hash}..HEAD"], cwd=root_dir, capture_output=True, text=True)
            if res.returncode == 0:
                lag = int(res.stdout.strip())
            else:
                infos.append(f"無法取得 git rev-list，跳過比對 (hash={latest_hash})")
        except Exception:
            infos.append(f"無法執行 git 指令，跳過比對 (hash={latest_hash})")

    if lag > 1:
        fails.append(f"docs/AUDIT-LOG.md: 最新審查紀錄 ({latest_hash}) 落後 HEAD {lag} 個 commit（允許落後 1 批，因本批尚未核對）")
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
                except Exception:
                    pass
    return fails, infos

def check_14_simplified_chinese(root_dir=None):
    if root_dir is None: root_dir = repo_root
    fails = []
    infos = []
    chars = set("换爲这个们时说说过还没来实现应该产严术样价专车书长门间乐习买卖举属于")
    allowed_files = ["docs/refactor-backlog.md", "docs/AUDIT-LOG.md"]
    for root, dirs, files in os.walk(root_dir):
        if any(p in root for p in [".git", "node_modules", "__pycache__", ".venv"]):
            continue
        for file in files:
            if file.endswith(".md"):
                filepath = os.path.join(root, file)
                rel_fp = os.path.relpath(filepath, root_dir).replace("\\", "/")
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as fh:
                        for idx, line in enumerate(fh, 1):
                            hit = [c for c in line if c in chars]
                            if hit:
                                hit_str = "".join(sorted(set(hit)))
                                msg = f"{rel_fp}:{idx}  包含簡體字 [{hit_str}]: {line.strip()[:60]}"
                                if rel_fp in allowed_files:
                                    infos.append(f"{msg} (歷史紀錄引用例外)")
                                else:
                                    fails.append(msg)
                except Exception:
                    pass
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

def check_16_exec_log_cadence(root_dir=None, git_count=None):
    """CHECK 16 — 執行者檢查紀錄（EXEC-LOG）落後偵測。

    規格：讀 docs/EXEC-LOG.md 最後一列的 commit 欄位。
    若該值為 BOOTSTRAP 以外的 hash，且不等於 HEAD 也不等於 HEAD~1，即為 FAIL。
    判準與 CHECK 12 對 AUDIT-LOG.md 的驗證相同。
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

    rows = re.findall(r"^\|\s*([0-9a-fA-F]+|BOOTSTRAP)\s*\|", content, re.M)
    if not rows:
        fails.append("docs/EXEC-LOG.md:0  未找到執行者檢查紀錄列")
        return fails, infos
    if len(rows) == 1 and rows[0] == "BOOTSTRAP":
        infos.append("docs/EXEC-LOG.md 僅有首列 BOOTSTRAP，跳過檢查")
        return fails, infos

    latest_hash = rows[-1]
    if latest_hash == "BOOTSTRAP":
        infos.append("docs/EXEC-LOG.md 最新列為 BOOTSTRAP，跳過檢查")
        return fails, infos

    lag = 0
    if git_count is not None:
        lag = git_count
    else:
        try:
            res = subprocess.run(["git", "rev-list", "--count", f"{latest_hash}..HEAD"], cwd=root_dir, capture_output=True, text=True)
            if res.returncode == 0:
                lag = int(res.stdout.strip())
            else:
                infos.append(f"無法取得 git rev-list，跳過比對 (hash={latest_hash})")
        except Exception:
            infos.append(f"無法執行 git 指令，跳過比對 (hash={latest_hash})")

    if lag > 1:
        fails.append(f"docs/EXEC-LOG.md: 最新檢查紀錄 ({latest_hash}) 落後 HEAD {lag} 個 commit（允許落後 1 批，因本批尚未核對）")
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

if __name__ == "__main__":
    run_checks()
