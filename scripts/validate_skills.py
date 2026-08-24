#!/usr/bin/env python3
"""
驗證 skills/ 目錄下所有技能是否符合 AGENTS.md 定義的架構規範，
並套用 Anthropic 官方 Agent Skills 規格（anthropics/skills 的 quick_validate.py）
定義的 frontmatter 硬性規則。

用法：
    python3 scripts/validate_skills.py

檢查項目：
1. 每個 bucket 下的每個技能資料夾都要有 SKILL.md
2. SKILL.md 必須有合法的 YAML frontmatter，且 name / description 不可空白
3. name 欄位要跟資料夾名稱一致
4. 【官方規則】name 必須是 kebab-case（小寫字母/數字/連字號），不能開頭/結尾是連字號
   或有連續連字號，長度不超過 64 字元
5. 【官方規則】description 不可包含角括號 < >，長度不超過 1024 字元
6. 【官方規則】frontmatter 只能包含官方允許的欄位，加上本專案自訂的擴充欄位
7. 同一個技能名稱不可出現在超過一個 bucket
8. SKILL.md 正文超過 150 行時提出警告（本專案訂得比官方 500 行建議更嚴格，
   因為傾向更早拆分 REFERENCE.md，維持精簡）
9. bucket README.md / AGENTS.md 是否存在，並列出實際技能資料夾中未被 README 收錄的項目

參考來源：https://github.com/anthropics/skills（Agent Skills 官方規格與範例）
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"

VALID_BUCKETS = {
    "orchestration",
    "analysis",
    "agents",
    "execution",
    "platform",
    "meta",
    "deprecated",
}

MAX_LINES_BEFORE_WARNING = 150

# 官方 Agent Skills 規格允許的 frontmatter 欄位
OFFICIAL_ALLOWED_KEYS = {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}
# 本專案自訂擴充欄位（見 AGENTS.md 第 2 節），官方規格沒有但本專案沿用
PROJECT_CUSTOM_KEYS = {"authorized_mcp_tools", "semantic_firewall", "disable-model-invocation"}
ALLOWED_KEYS = OFFICIAL_ALLOWED_KEYS | PROJECT_CUSTOM_KEYS

NAME_MAX_LEN = 64
DESCRIPTION_MAX_LEN = 1024
KEBAB_CASE_RE = re.compile(r"^[a-z0-9-]+$")


def parse_frontmatter(text: str):
    """抓出 --- ... --- 之間的 YAML frontmatter,回傳 (dict, body)"""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not m:
        return None, text
    fm_text, body = m.group(1), m.group(2)
    fm = {}
    for line in fm_text.splitlines():
        line = line.rstrip()
        if not line or line.strip().startswith("#"):
            continue
        if ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip().strip('"').strip("'")
    return fm, body


def validate_name(name: str, errors: list, location: str):
    """套用官方 kebab-case / 長度規則"""
    if not KEBAB_CASE_RE.match(name):
        errors.append(f"[{location}] name '{name}' 不符合 kebab-case（只能小寫字母/數字/連字號）")
    if name.startswith("-") or name.endswith("-") or "--" in name:
        errors.append(f"[{location}] name '{name}' 不能開頭/結尾是連字號，或包含連續連字號")
    if len(name) > NAME_MAX_LEN:
        errors.append(f"[{location}] name 長度 {len(name)} 超過官方上限 {NAME_MAX_LEN} 字元")


def validate_description(desc: str, errors: list, location: str):
    """套用官方 description 規則"""
    if "<" in desc or ">" in desc:
        errors.append(f"[{location}] description 不能包含角括號 < 或 >")
    if len(desc) > DESCRIPTION_MAX_LEN:
        errors.append(f"[{location}] description 長度 {len(desc)} 超過官方上限 {DESCRIPTION_MAX_LEN} 字元")


def main():
    errors = []
    warnings = []
    seen_names = {}

    if not SKILLS_DIR.exists():
        print(f"❌ 找不到 skills/ 目錄：{SKILLS_DIR}")
        sys.exit(1)

    for bucket_dir in sorted(SKILLS_DIR.iterdir()):
        if not bucket_dir.is_dir():
            continue
        bucket = bucket_dir.name
        if bucket not in VALID_BUCKETS:
            errors.append(f"未知的 bucket 分類：{bucket}（不在 AGENTS.md 定義的 7 種分類內）")
            continue

        readme = bucket_dir / "README.md"
        if bucket != "deprecated" and not readme.exists():
            warnings.append(f"[{bucket}] 缺少 README.md")

        bucket_agents_md = bucket_dir / "AGENTS.md"
        if not bucket_agents_md.exists():
            warnings.append(f"[{bucket}] 缺少範圍受限的 AGENTS.md（見根目錄 AGENTS.md 第 6a 節）")

        readme_text = readme.read_text(encoding="utf-8") if readme.exists() else ""

        for skill_dir in sorted(bucket_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_name = skill_dir.name
            skill_md = skill_dir / "SKILL.md"
            location = f"{bucket}/{skill_name}"

            if not skill_md.exists():
                errors.append(f"[{location}] 缺少 SKILL.md")
                continue

            text = skill_md.read_text(encoding="utf-8")
            fm, body = parse_frontmatter(text)

            if fm is None:
                errors.append(f"[{location}] SKILL.md 沒有合法的 YAML frontmatter（缺少開頭/結尾 ---）")
                continue

            # 官方規則：frontmatter 欄位白名單
            unexpected_keys = set(fm.keys()) - ALLOWED_KEYS
            if unexpected_keys:
                errors.append(
                    f"[{location}] frontmatter 有不在允許清單內的欄位：{', '.join(sorted(unexpected_keys))}"
                )

            name = fm.get("name", "")
            desc = fm.get("description", "")

            if not name:
                errors.append(f"[{location}] frontmatter 缺少 name 欄位")
            else:
                if name != skill_name:
                    errors.append(f"[{location}] frontmatter 的 name（{name}）跟資料夾名稱不一致")
                validate_name(name, errors, location)

            if not desc:
                errors.append(f"[{location}] description 欄位是空的 —— 此技能永遠不會被自動觸發")
            else:
                validate_description(desc, errors, location)

            if name:
                if name in seen_names:
                    errors.append(
                        f"技能名稱重複：'{name}' 同時出現在 {seen_names[name]} 與 {location}"
                    )
                else:
                    seen_names[name] = location

            line_count = body.count("\n") + (1 if body and not body.endswith("\n") else 0)
            if line_count > MAX_LINES_BEFORE_WARNING:
                ref = skill_dir / "REFERENCE.md"
                if not ref.exists():
                    warnings.append(
                        f"[{location}] SKILL.md 正文 {line_count} 行，超過 {MAX_LINES_BEFORE_WARNING} 行建議值，"
                        f"且沒有 REFERENCE.md，考慮拆分（漸進式揭露；官方硬上限是 500 行）"
                    )

            if bucket != "deprecated" and skill_name not in readme_text:
                warnings.append(f"[{location}] 未出現在 {bucket}/README.md 中，索引可能過期")

    print("=" * 60)
    print(f"檢查完成：{len(seen_names)} 個技能")
    print("=" * 60)

    if warnings:
        print(f"\n⚠️  警告（{len(warnings)}）：")
        for w in warnings:
            print(f"  - {w}")

    if errors:
        print(f"\n❌ 錯誤（{len(errors)}）：")
        for e in errors:
            print(f"  - {e}")
        print("\n驗證失敗，請修正上述錯誤後再視為完成。")
        sys.exit(1)
    else:
        print("\n✅ 沒有結構性錯誤。" + ("（但請留意上面的警告）" if warnings else ""))
        sys.exit(0)


if __name__ == "__main__":
    main()
