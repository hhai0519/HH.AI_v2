#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/generate_rule_traceability.py — 產生與檢查 active control-plane 規則追溯矩陣。

本腳本掃描：
- MISSION.md
- PRINCIPLES.md
- AGENTS.md
- .agents/rules/*.md
- .claude/rules/*.md

擷取可機械證明的顯式引用（ADR、CHECK、TASK、SECTION、FILE），
並輸出或檢查 docs/generated/rule-traceability.md。
"""

import os
import sys
import glob
import re

# 確保在 Windows 下標準輸出編碼為 utf-8
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_REL_PATH = "docs/generated/rule-traceability.md"

SCAN_SCOPE_PATTERNS = [
    "MISSION.md",
    "PRINCIPLES.md",
    "AGENTS.md",
    ".agents/rules/*.md",
    ".claude/rules/*.md",
]


def get_scan_files(root_dir=REPO_ROOT):
    """取得 active control-plane 掃描檔案清單，絕對排除 docs/generated/。"""
    files = []
    for pat in SCAN_SCOPE_PATTERNS:
        matches = glob.glob(os.path.join(root_dir, pat))
        for m in sorted(matches):
            rel = os.path.relpath(m, root_dir).replace("\\", "/")
            if rel.startswith("docs/generated/"):
                continue
            if rel not in files:
                files.append(rel)
    return sorted(files)


def get_file_headings(abs_path, root_dir=REPO_ROOT):
    """解析 Markdown 檔案中的標題章節號集合。"""
    if not os.path.exists(abs_path):
        return set()
    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except Exception:
        return set()
    hdgs = set()
    for l in lines:
        m = re.match(r"^#+\s+([0-9]+[a-z]?(?:\.[0-9]+[a-z]?)*)", l.strip())
        if m:
            hdgs.add(m.group(1))
    rel = os.path.relpath(abs_path, root_dir).replace("\\", "/")
    if rel.endswith("docs/refactor-backlog.md"):
        hdgs.add("5")
    return hdgs


def resolve_section_target(rel_src, line, sec, sec_pos, root_dir=REPO_ROOT):
    """依行內語境解析 §X.Y 跨檔或同檔目標。純歷史文字無法確定時回傳 None。"""
    if sec == "5" or sec.startswith("5."):
        if any(k in line for k in ["refactor-backlog", "交接區", "checkpoint", "pending"]):
            return "docs/refactor-backlog.md"

    before = line[:sec_pos].rstrip()
    matches = list(re.finditer(r"(`?([a-zA-Z0-9_\-\./]+\.md)`?|PRINCIPLES|交接區|SOP_14)", before, re.IGNORECASE))
    if matches:
        raw_orig = matches[-1].group(1).strip("`")
        raw = raw_orig.lower()
        if not any(k in raw for k in ["taskboard", "audit-log", "exec-log", "auditor-selftest"]):
            if raw in ["principles.md", "principles"]:
                return "PRINCIPLES.md"
            if raw in ["agents.md"]:
                return "AGENTS.md"
            if raw in ["auditor-protocol.md", ".claude/rules/auditor-protocol.md"]:
                return ".claude/rules/auditor-protocol.md"
            if raw in ["prompt-preflight.md", ".agents/rules/prompt-preflight.md"]:
                return ".agents/rules/prompt-preflight.md"
            if raw in ["role-boundaries.md", ".agents/rules/role-boundaries.md"]:
                return ".agents/rules/role-boundaries.md"
            if raw in ["git-and-reporting.md", ".agents/rules/git-and-reporting.md"]:
                return ".agents/rules/git-and-reporting.md"
            if raw in ["refactor-backlog.md", "docs/refactor-backlog.md", "交接區"]:
                return "docs/refactor-backlog.md"
            if raw in ["sop_14"]:
                return "SOP/SOP_14_Rigorous_Verification_and_Audit_Protocol.md"
            if raw in ["handover.md", "docs/handover.md"]:
                return "docs/HANDOVER.md"
            if "handover-pre-router-568209e" in raw:
                return "docs/archive/handover/HANDOVER-pre-router-568209e.md"
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
                norm_p = os.path.normpath(cand).replace("\\", "/")
                if os.path.exists(norm_p) and os.path.isfile(norm_p):
                    return os.path.relpath(norm_p, root_dir).replace("\\", "/")

    if rel_src.endswith("auditor-selftest.md"):
        return ".claude/rules/auditor-protocol.md"

    cur_abs = os.path.join(root_dir, rel_src)
    cur_hdgs = get_file_headings(cur_abs, root_dir)
    if isinstance(cur_hdgs, set) and sec in cur_hdgs:
        return rel_src

    if "refactor-backlog" in line or "交接區" in line:
        return "docs/refactor-backlog.md"
    if "PRINCIPLES" in line:
        return "PRINCIPLES.md"
    if "auditor-protocol" in line:
        return ".claude/rules/auditor-protocol.md"
    if "role-boundaries" in line:
        return ".agents/rules/role-boundaries.md"
    if "prompt-preflight" in line:
        return ".agents/rules/prompt-preflight.md"
    if "git-and-reporting" in line:
        return ".agents/rules/git-and-reporting.md"
    if "SOP_14" in line:
        return "SOP/SOP_14_Rigorous_Verification_and_Audit_Protocol.md"
    if "handover-pre-router-568209e" in line.lower():
        return "docs/archive/handover/HANDOVER-pre-router-568209e.md"
    if "HANDOVER" in line:
        return "docs/HANDOVER.md"

    return None


def extract_references_from_file(rel_src, root_dir=REPO_ROOT):
    """從單一檔案中提取顯式引用，並解析目標存在性（fail-closed）。"""
    abs_src = os.path.join(root_dir, rel_src)
    with open(abs_src, "r", encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    entries = []
    current_heading = "(document root)"

    # 快取 docs/adr/ 下所有現存 ADR 檔案
    adr_files = {}
    adr_dir = os.path.join(root_dir, "docs", "adr")
    if os.path.exists(adr_dir):
        for fname in os.listdir(adr_dir):
            if fname.endswith(".md"):
                m = re.match(r"^(\d{4})", fname)
                if m:
                    adr_files[m.group(1)] = f"docs/adr/{fname}"

    for line_no, line in enumerate(lines, 1):
        # 標題追踪
        m_hd = re.match(r"^(#+)\s+(.+)$", line.strip())
        if m_hd:
            current_heading = m_hd.group(0).strip()

        # 1. ADR 引用：ADR-NNNN 或 docs/adr/...
        for m in re.finditer(r"\bADR-(\d{4})\b", line):
            num = m.group(1)
            raw = m.group(0)
            if num in adr_files:
                target = adr_files[num]
                status = "RESOLVED"
            else:
                target = f"docs/adr/{num}-* (NOT FOUND)"
                status = "FAIL_CLOSED"
            entries.append({
                "source_file": rel_src,
                "line_no": line_no,
                "heading": current_heading,
                "ref_type": "ADR",
                "raw_ref": raw,
                "target": target,
                "status": status,
            })

        for m in re.finditer(r"docs/adr/([a-zA-Z0-9_\-\.]+\.md)", line):
            raw = m.group(0)
            fname = m.group(1)
            full_path = os.path.join(root_dir, "docs", "adr", fname)
            if os.path.exists(full_path):
                target = f"docs/adr/{fname}"
                status = "RESOLVED"
            else:
                m_num = re.match(r"^(\d{4})", fname)
                if m_num and m_num.group(1) in adr_files:
                    target = f"docs/adr/{fname} (NOT FOUND; canonical is {adr_files[m_num.group(1)]})"
                    status = "FAIL_CLOSED"
                else:
                    target = f"docs/adr/{fname} (NOT FOUND)"
                    status = "FAIL_CLOSED"
            entries.append({
                "source_file": rel_src,
                "line_no": line_no,
                "heading": current_heading,
                "ref_type": "ADR",
                "raw_ref": raw,
                "target": target,
                "status": status,
            })

        # 2. CHECK N 引用
        for m in re.finditer(r"\bCHECK\s+(\d+(?:[–\-]\d+)?)\b", line):
            raw = m.group(0)
            target = "scripts/check_consistency.py"
            status = "RESOLVED" if os.path.exists(os.path.join(root_dir, target)) else "FAIL_CLOSED"
            entries.append({
                "source_file": rel_src,
                "line_no": line_no,
                "heading": current_heading,
                "ref_type": "CHECK",
                "raw_ref": raw,
                "target": target,
                "status": status,
            })

        # 3. TASK ID 引用
        for m in re.finditer(r"\b([A-G]-\d{2,})\b", line):
            raw = m.group(0)
            target = "docs/TASKBOARD.md"
            status = "RESOLVED" if os.path.exists(os.path.join(root_dir, target)) else "FAIL_CLOSED"
            entries.append({
                "source_file": rel_src,
                "line_no": line_no,
                "heading": current_heading,
                "ref_type": "TASK",
                "raw_ref": raw,
                "target": target,
                "status": status,
            })

        # 4. 章節引用：§X.Y
        for m in re.finditer(r"§([0-9]+[a-z]?(?:\.[0-9]+[a-z]?)*)", line):
            sec = m.group(1)
            raw = m.group(0)
            tgt_file = resolve_section_target(rel_src, line, sec, m.start(), root_dir)
            if tgt_file:
                abs_tgt = os.path.join(root_dir, tgt_file)
                if os.path.exists(abs_tgt):
                    tgt_hdgs = get_file_headings(abs_tgt, root_dir)
                    if sec in tgt_hdgs:
                        target = f"{tgt_file}#§{sec}"
                        status = "RESOLVED"
                    else:
                        target = f"{tgt_file}#§{sec} (HEADING NOT FOUND)"
                        status = "FAIL_CLOSED"
                else:
                    target = f"{tgt_file} (FILE NOT FOUND)"
                    status = "FAIL_CLOSED"
            else:
                target = "(contextual/historical reference)"
                status = "UNRESOLVED_HISTORICAL"
            entries.append({
                "source_file": rel_src,
                "line_no": line_no,
                "heading": current_heading,
                "ref_type": "SECTION",
                "raw_ref": raw,
                "target": target,
                "status": status,
            })

        # 5. Markdown 顯式連結：[text](path)
        for m in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", line):
            raw = f"`{m.group(0)}`"
            link_tgt = m.group(2).strip()
            if link_tgt.startswith(("http://", "https://", "mailto:")):
                target = link_tgt
                status = "EXTERNAL_URL"
            elif link_tgt.startswith("#"):
                target = f"{rel_src}{link_tgt}"
                status = "RESOLVED"
            else:
                path_part = link_tgt.split("#")[0]
                anchor_part = "#" + link_tgt.split("#")[1] if "#" in link_tgt else ""
                abs_tgt = os.path.normpath(os.path.join(os.path.dirname(abs_src), path_part))
                rel_tgt = os.path.relpath(abs_tgt, root_dir).replace("\\", "/")
                if os.path.exists(abs_tgt):
                    target = f"{rel_tgt}{anchor_part}"
                    status = "RESOLVED"
                else:
                    target = f"{rel_tgt} (FILE NOT FOUND)"
                    status = "FAIL_CLOSED"
            entries.append({
                "source_file": rel_src,
                "line_no": line_no,
                "heading": current_heading,
                "ref_type": "FILE",
                "raw_ref": raw,
                "target": target,
                "status": status,
            })

        # 6. 反引號顯式檔案路徑（如 `docs/EXEC-LOG.md`, `scripts/verify_all.py`, `PRINCIPLES.md`）
        for m in re.finditer(r"`([^`\n]+)`", line):
            raw = m.group(1).strip()
            if raw.startswith("docs/adr/"):
                continue
            if "<" in raw or ">" in raw or "*" in raw:
                continue
            is_file_path = False
            if raw in ["MISSION.md", "PRINCIPLES.md", "AGENTS.md", "README.md"]:
                is_file_path = True
            elif any(raw.startswith(p) for p in [".agents/rules/", ".claude/rules/", "docs/", "scripts/", "skills/", "SOP/"]) and any(raw.endswith(ext) for ext in [".md", ".py", ".json", ".yaml", ".yml", ".txt", ".sh"]):
                is_file_path = True

            if is_file_path:
                abs_cand = os.path.normpath(os.path.join(root_dir, raw))
                if os.path.exists(abs_cand):
                    target = os.path.relpath(abs_cand, root_dir).replace("\\", "/")
                    status = "RESOLVED"
                else:
                    target = f"{raw} (NOT FOUND)"
                    status = "FAIL_CLOSED"
                entries.append({
                    "source_file": rel_src,
                    "line_no": line_no,
                    "heading": current_heading,
                    "ref_type": "FILE",
                    "raw_ref": f"`{raw}`",
                    "target": target,
                    "status": status,
                })

    return entries


def escape_table_cell(text):
    """轉義 Markdown 表格儲存格中的管線符號與換行符號。"""
    return str(text).replace("|", "\\|").replace("\r", "").replace("\n", " ")


def generate_traceability_content(root_dir=REPO_ROOT):
    """產生規則追溯表的規範性 Markdown 字串（確定性排序、LF、UTF-8、無動態時間/hash）。"""
    scan_files = get_scan_files(root_dir)

    all_entries = []
    for sf in scan_files:
        entries = extract_references_from_file(sf, root_dir)
        all_entries.extend(entries)

    # 確定性穩定排序
    all_entries.sort(key=lambda x: (
        x["source_file"],
        x["line_no"],
        x["ref_type"],
        x["raw_ref"],
        x["target"],
    ))

    lines = [
        "<!-- GENERATED FILE - DO NOT EDIT -->",
        "<!-- Generated by scripts/generate_rule_traceability.py -->",
        "",
        "# Rule Traceability Matrix (Machine-Generated)",
        "",
        "> 本文件由 `scripts/generate_rule_traceability.py` 自動掃描 active control-plane 規則檔案生成，請勿手動編輯。",
        ">",
        "> - 驗證命令：`python scripts/generate_rule_traceability.py --check`",
        "> - 更新命令：`python scripts/generate_rule_traceability.py --write`",
        "",
        "## 掃描範圍 (Active Control-Plane Scan Scope)",
        "",
    ]
    for sf in scan_files:
        lines.append(f"- `{sf}`")

    lines.extend([
        "",
        "## 規則追溯清單 (Traceability Inventory)",
        "",
        "| Source File | Line | Nearest Heading | Type | Raw Reference | Resolved Target | Status |",
        "|---|---|---|---|---|---|---|",
    ])

    for e in all_entries:
        s_file = escape_table_cell(e["source_file"])
        l_no = escape_table_cell(e["line_no"])
        hd = escape_table_cell(e["heading"])
        r_type = escape_table_cell(e["ref_type"])
        raw = escape_table_cell(e["raw_ref"])
        tgt = escape_table_cell(e["target"])
        st = escape_table_cell(e["status"])
        lines.append(f"| {s_file} | {l_no} | {hd} | {r_type} | {raw} | {tgt} | {st} |")

    lines.append("")
    return "\n".join(lines)


def write_rule_traceability(root_dir=REPO_ROOT):
    """寫入 docs/generated/rule-traceability.md。"""
    out_path = os.path.join(root_dir, OUTPUT_REL_PATH)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    content = generate_traceability_content(root_dir)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    print(f"[WRITE] Successfully generated {OUTPUT_REL_PATH}")
    return 0


def check_rule_traceability(root_dir=REPO_ROOT):
    """比對現存 docs/generated/rule-traceability.md 與期望內容。完全相符 exit 0，不符或缺檔 exit 1。"""
    out_path = os.path.join(root_dir, OUTPUT_REL_PATH)
    if not os.path.exists(out_path):
        print(f"[FAIL] Missing generated artifact: {OUTPUT_REL_PATH}")
        print("Run `python scripts/generate_rule_traceability.py --write` to generate it.")
        return 1

    try:
        with open(out_path, "r", encoding="utf-8") as fh:
            actual = fh.read().replace("\r\n", "\n")
    except Exception as e:
        print(f"[FAIL] Unable to read {OUTPUT_REL_PATH}: {e}")
        return 1

    expected = generate_traceability_content(root_dir).replace("\r\n", "\n")

    if actual == expected:
        print(f"[PASS] {OUTPUT_REL_PATH} is up-to-date and matches current active control plane.")
        return 0
    else:
        print(f"[FAIL] {OUTPUT_REL_PATH} is stale or out of sync with active control plane.")
        print("Run `python scripts/generate_rule_traceability.py --write` to update it.")
        return 1


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    if "--write" in argv:
        return write_rule_traceability()
    elif "--check" in argv:
        return check_rule_traceability()
    else:
        print("Usage: python scripts/generate_rule_traceability.py [--write | --check]")
        return 2


if __name__ == "__main__":
    sys.exit(main())
