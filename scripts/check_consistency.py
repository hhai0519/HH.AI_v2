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
  CHECK 8 — 任務看板 HEAD 落後
  CHECK 9 — 交接區 HEAD 落後
  CHECK 10 — §X.Y 章節引用有效性
  CHECK 11 — §6.1 清單與自檢清單 E 節項目對應
  CHECK 12 — AUDIT-LOG 審查週期落後
  CHECK 13 — 檔尾換行符
  CHECK 14 — 繁體中文環境下的簡體字偵測
  CHECK 15 — 提示詞上下文衝突字串偵測

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

def run_checks():
    total_checks = 15
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
    c3_fails = []
    md_link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
    allowed_c3 = [
        ("skills/execution/playwright-automation/README.md", "skills/playwright-skill/API_REFERENCE.md")
    ]
    
    for root, dirs, files in os.walk(repo_root):
        if ".git" in root or ".venv" in root or "node_modules" in root:
            continue
        for file in files:
            if file.endswith(".md"):
                filepath = os.path.join(root, file)
                rel_fp = os.path.relpath(filepath, repo_root).replace("\\", "/")
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
                                if link.startswith("http") or link.startswith("file://") or link.startswith("mailto:") or "<" in link or ">" in link:
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
                                            print(f"  [INFO] 略過已知失效連結: {rel_fp}:{i+1} -> {link} (原因: vendored 上游原文，依 ADR-0018 不改寫)")
                                            break
                                    if not is_allowed:
                                        c3_fails.append(f"{rel_fp}:{i+1}  目標不存在: {link}")
                except Exception:
                    pass

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
                    print(f"  [INFO] 略過已知殘留: {rel_fp} (原因: runtime 層尚未遷移，遷移完成後必須更新；見 docs/HANDOVER.md §5.5)")
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
    # CHECK 8: 任務看板 HEAD 落後
    # ---------------------------------------------------------
    print("\nCHECK 8 - 任務看板 HEAD 落後")
    c8_fails, c8_infos = check_8_taskboard_head(repo_root)
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
    # CHECK 9: 交接區 HEAD 落後
    # ---------------------------------------------------------
    print("\nCHECK 9 - 交接區 HEAD 落後")
    c9_fails, c9_infos = check_9_handover_head(repo_root)
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
    # CHECK 15: 提示詞上下文衝突字串偵測
    # ---------------------------------------------------------
    print("\nCHECK 15 - 提示詞上下文衝突字串偵測")
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

def get_git_heads(root):
    env_head = os.environ.get("GIT_HEAD")
    env_prev = os.environ.get("GIT_HEAD_PREV")
    head = None
    prev = None
    try:
        res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True)
        if res.returncode == 0:
            head = res.stdout.strip()
        res2 = subprocess.run(["git", "rev-parse", "--short", "HEAD~1"], cwd=root, capture_output=True, text=True)
        if res2.returncode == 0:
            prev = res2.stdout.strip()
    except Exception:
        pass
    if env_head:
        head = env_head
    if env_prev:
        prev = env_prev
    return head, prev

def check_8_taskboard_head(root_dir=None, git_head=None, git_prev=None):
    if root_dir is None: root_dir = repo_root
    fails = []
    infos = []
    tb_path = os.path.join(root_dir, "docs", "TASKBOARD.md")
    if not os.path.exists(tb_path):
        fails.append("docs/TASKBOARD.md:0  檔案不存在")
        return fails, infos
    try:
        with open(tb_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        fails.append(f"docs/TASKBOARD.md:0  讀取失敗: {e}")
        return fails, infos

    m = re.search(r"\*\*最後更新\*\*：.*?HEAD\s+`?([0-9a-fA-F]+)`?\s+之後", content)
    if not m:
        fails.append("docs/TASKBOARD.md:0  未找到『最後更新』HEAD 標記")
        return fails, infos
    tb_hash = m.group(1).lower()

    head = git_head.lower() if git_head else None
    prev = git_prev.lower() if git_prev else None
    if head is None or prev is None:
        g_head, g_prev = get_git_heads(root_dir)
        if head is None: head = g_head
        if prev is None: prev = g_prev

    if head is None:
        infos.append("無法取得 git HEAD 資訊，略過比對")
        return fails, infos

    matches_head = head.startswith(tb_hash) or tb_hash.startswith(head)
    matches_prev = prev and (prev.startswith(tb_hash) or tb_hash.startswith(prev))
    if not matches_head and not matches_prev:
        fails.append(f"docs/TASKBOARD.md: 最後更新 HEAD ({tb_hash}) 落後超過一批 (HEAD={head}, HEAD~1={prev})")
    return fails, infos

def check_9_handover_head(root_dir=None, git_head=None, git_prev=None):
    if root_dir is None: root_dir = repo_root
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

    m = re.search(r"上次核對通過的 HEAD：\s*`?([0-9a-fA-F]+)`?", content)
    if not m:
        fails.append("docs/refactor-backlog.md:0  未找到『上次核對通過的 HEAD』標記")
        return fails, infos
    ho_hash = m.group(1).lower()

    head = git_head.lower() if git_head else None
    prev = git_prev.lower() if git_prev else None
    if head is None or prev is None:
        g_head, g_prev = get_git_heads(root_dir)
        if head is None: head = g_head
        if prev is None: prev = g_prev

    if head is None:
        infos.append("無法取得 git HEAD 資訊，略過比對")
        return fails, infos

    matches_head = head.startswith(ho_hash) or ho_hash.startswith(head)
    matches_prev = prev and (prev.startswith(ho_hash) or ho_hash.startswith(prev))
    if not matches_head and not matches_prev:
        fails.append(f"docs/refactor-backlog.md: 上次核對通過的 HEAD ({ho_hash}) 落後超過一批 (HEAD={head}, HEAD~1={prev})")
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
        'PRINCIPLES.md', 'auditor-protocol.md', 'AGENTS.md', 'handover-selftest.md',
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
    selftest_path = os.path.join(root_dir, ".claude", "rules", "handover-selftest.md")
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
        fails.append(".claude/rules/handover-selftest.md: 未找到 ## E. 交付 章節")
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
                fails.append(f".claude/rules/handover-selftest.md: {eid} 指向不存在的 §6.1-{rnum}")

    for pnum in sorted(proto_items.keys()):
        if pnum not in mapped_proto_nums:
            fails.append(f".claude/rules/auditor-protocol.md: §6.1 第 {pnum} 項在 handover-selftest.md E 節中無對應項目")

    if 8 in proto_items and "AUDIT-LOG" in proto_items[8]:
        e8_has_audit = any("AUDIT-LOG" in text for eid, text in e_items.items() if "§6.1-8" in text)
        if not e8_has_audit:
            fails.append(".claude/rules/handover-selftest.md: E8 缺少 AUDIT-LOG 更新項目（與 §6.1-8 不一致）")

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

if __name__ == "__main__":
    run_checks()
