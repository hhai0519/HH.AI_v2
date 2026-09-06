#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/fingerprint.py — 產生與驗證 repo 的事實指紋。

受管檔案集合記錄 lines, fences, sha256, headings 四項屬性。
提供 --write、--verify、--compare 指令供執行者、審計官與 CI 自動化核對。
"""

import os
import sys
import io
import re
import json
import glob
import hashlib
import subprocess
from datetime import datetime, timezone

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

MANAGED_PATTERNS = [
    "MISSION.md",
    "PRINCIPLES.md",
    "AGENTS.md",
    ".claude/rules/*.md",
    ".agents/rules/*.md",
    "SOP/*.md",
    "docs/*.md",            # 僅頂層，不遞迴
    "docs/adr/*.md",
    "scripts/*.py",
    "scripts/tests/*.py",
    ".github/workflows/*.yml",
]


def get_base_head(root_dir=None):
    if root_dir is None:
        root_dir = REPO_ROOT
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root_dir,
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return "UNKNOWN"


def get_managed_files(root_dir=None):
    if root_dir is None:
        root_dir = REPO_ROOT
    all_files = set()
    for pattern in MANAGED_PATTERNS:
        full_pattern = os.path.join(root_dir, pattern)
        for filepath in glob.glob(full_pattern):
            if os.path.isfile(filepath):
                rel_path = os.path.relpath(filepath, root_dir).replace("\\", "/")
                # 必須排除 docs/fingerprints/ 底下的任何檔案
                if rel_path.startswith("docs/fingerprints/"):
                    continue
                all_files.add(rel_path)
    return sorted(list(all_files))


def compute_file_fingerprint(filepath):
    """回傳單一檔案的四項指紋屬性。

    sha256 在雜湊前先把 CRLF 正規化為 LF：Windows Git 的 `core.autocrlf`
    預設會在 checkout 時把 LF 轉為 CRLF，若直接雜湊原始位元組，
    同一個 commit 在 Windows 與 Linux 上會得到不同的雜湊值，
    CI 必然紅燈（2026-09-06 實證，見 refactor-backlog.md 第 48 點）。
    換行本身的差異改由獨立的 CRLF 偵測負責，不混進指紋。
    """
    with io.open(filepath, "rb") as f:
        raw_bytes = f.read()
    raw_text = raw_bytes.decode("utf-8", errors="replace")
    lines_list = raw_text.splitlines()

    lines = len(lines_list)
    fences = sum(1 for l in lines_list if l.strip().startswith("```"))
    normalized_bytes = raw_bytes.replace(b"\r\n", b"\n")
    sha256 = hashlib.sha256(normalized_bytes).hexdigest()
    headings = [l for l in lines_list if re.match(r"^#{1,6}\s", l)]

    return {
        "lines": lines,
        "fences": fences,
        "sha256": sha256,
        "headings": headings,
    }


def compute_skills_fingerprint(root_dir=None):
    if root_dir is None:
        root_dir = REPO_ROOT
    skills_dir = os.path.join(root_dir, "skills")
    by_bucket = {}
    total = 0
    if os.path.isdir(skills_dir):
        for bucket in sorted(os.listdir(skills_dir)):
            bucket_path = os.path.join(skills_dir, bucket)
            if not os.path.isdir(bucket_path):
                continue
            count = 0
            for skill_name in sorted(os.listdir(bucket_path)):
                skill_md = os.path.join(bucket_path, skill_name, "SKILL.md")
                if os.path.isfile(skill_md):
                    count += 1
            if count > 0:
                by_bucket[bucket] = count
                total += count
    return {
        "total": total,
        "by_bucket": by_bucket,
    }


def generate_fingerprint(root_dir=None):
    if root_dir is None:
        root_dir = REPO_ROOT

    managed_files = get_managed_files(root_dir)
    files_data = {}
    for rel_path in managed_files:
        full_path = os.path.join(root_dir, rel_path)
        files_data[rel_path] = compute_file_fingerprint(full_path)

    skills_data = compute_skills_fingerprint(root_dir)
    base_head = get_base_head(root_dir)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    fingerprint = {
        "schema_version": 1,
        "base_head": base_head,
        "generated_at": now_utc,
        "files": files_data,
        "skills": skills_data,
    }
    return fingerprint


def compare_fingerprints(actual_fp, expected_fp):
    """只比對 files 與 skills 兩個區段。
    schema_version, base_head, generated_at 不參與比對。
    回傳 differences: list of str
    """
    diffs = []
    actual_files = actual_fp.get("files", {})
    expected_files = expected_fp.get("files", {})

    all_paths = sorted(list(set(actual_files.keys()) | set(expected_files.keys())))
    for p in all_paths:
        if p not in expected_files:
            diffs.append(f"[檔案新增] {p}")
            continue
        if p not in actual_files:
            diffs.append(f"[檔案缺少] {p}")
            continue

        act_data = actual_files[p]
        exp_data = expected_files[p]

        for field in ["lines", "fences", "sha256"]:
            if act_data.get(field) != exp_data.get(field):
                diffs.append(f"[欄位不符] {p}.{field}: 指紋檔={exp_data.get(field)} 實測={act_data.get(field)}")

        act_headings = act_data.get("headings", [])
        exp_headings = exp_data.get("headings", [])
        if act_headings != exp_headings:
            # 只印出第一個相異的索引與兩邊的字串
            mismatch_idx = -1
            min_len = min(len(act_headings), len(exp_headings))
            for i in range(min_len):
                if act_headings[i] != exp_headings[i]:
                    mismatch_idx = i
                    break
            if mismatch_idx == -1:
                mismatch_idx = min_len
            act_str = act_headings[mismatch_idx] if mismatch_idx < len(act_headings) else "<EOF>"
            exp_str = exp_headings[mismatch_idx] if mismatch_idx < len(exp_headings) else "<EOF>"
            diffs.append(f"[欄位不符] {p}.headings[{mismatch_idx}]: 指紋檔={repr(exp_str)} 實測={repr(act_str)}")

    # 比對 skills
    actual_skills = actual_fp.get("skills", {})
    expected_skills = expected_fp.get("skills", {})

    if actual_skills.get("total") != expected_skills.get("total"):
        diffs.append(f"[技能不符] total: 指紋檔={expected_skills.get('total')} 實測={actual_skills.get('total')}")

    actual_buckets = actual_skills.get("by_bucket", {})
    expected_buckets = expected_skills.get("by_bucket", {})
    all_buckets = sorted(list(set(actual_buckets.keys()) | set(expected_buckets.keys())))
    for b in all_buckets:
        act_cnt = actual_buckets.get(b, 0)
        exp_cnt = expected_buckets.get(b, 0)
        if act_cnt != exp_cnt:
            diffs.append(f"[技能不符] {b}: 指紋檔={exp_cnt} 實測={act_cnt}")

    return diffs


def verify_fingerprint(target_json_path, root_dir=None):
    if root_dir is None:
        root_dir = REPO_ROOT
    if not os.path.exists(target_json_path):
        sys.stderr.write(f"指紋檔案不存在: {target_json_path}\n")
        return 1

    try:
        with io.open(target_json_path, "r", encoding="utf-8") as f:
            expected_fp = json.load(f)
    except Exception as e:
        sys.stderr.write(f"無法讀取或解析指紋檔案 {target_json_path}: {e}\n")
        return 1

    actual_fp = generate_fingerprint(root_dir)
    diffs = compare_fingerprints(actual_fp, expected_fp)
    if diffs:
        for d in diffs:
            sys.stderr.write(f"{d}\n")
        return 1
    return 0


def main():
    args = sys.argv[1:]
    target_json = os.path.join(REPO_ROOT, "docs", "fingerprints", "exec-latest.json")

    if not args:
        fp = generate_fingerprint(REPO_ROOT)
        print(json.dumps(fp, indent=2, sort_keys=True, ensure_ascii=False))
        sys.exit(0)

    if args[0] == "--write":
        fp = generate_fingerprint(REPO_ROOT)
        os.makedirs(os.path.dirname(target_json), exist_ok=True)
        with io.open(target_json, "w", encoding="utf-8") as f:
            f.write(json.dumps(fp, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        sys.exit(0)

    if args[0] == "--verify":
        code = verify_fingerprint(target_json, REPO_ROOT)
        sys.exit(code)

    if args[0] == "--compare":
        if len(args) < 2:
            sys.stderr.write("使用方式: python3 scripts/fingerprint.py --compare <指紋檔路徑>\n")
            sys.exit(2)
        compare_target = os.path.abspath(args[1])
        code = verify_fingerprint(compare_target, REPO_ROOT)
        sys.exit(code)

    sys.stderr.write(f"未知的參數: {args[0]}\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
