#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/anchor.py — 錨點自動抽取器。

以機械方式切片並計算唯一性 count，避免手抄錨點產生字串漂移。
"""

import os
import sys
import io
import json

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


def extract_anchor(filepath, start_line, end_line):
    if not os.path.exists(filepath):
        sys.stderr.write(f"錯誤: 檔案不存在: {filepath}\n")
        sys.exit(2)

    try:
        with io.open(filepath, "r", encoding="utf-8") as f:
            full_content = f.read()
    except Exception as e:
        sys.stderr.write(f"錯誤: 讀取檔案失敗 {filepath}: {e}\n")
        sys.exit(2)

    lines = full_content.splitlines()
    total_lines = len(lines)

    if start_line < 1 or end_line > total_lines or start_line > end_line:
        sys.stderr.write(f"錯誤: 行號無效或越界: 起始={start_line}, 結束={end_line}, 總行數={total_lines}\n")
        sys.exit(2)

    selected_lines = lines[start_line - 1 : end_line]
    raw_text = "\n".join(selected_lines)  # 不得補尾端換行
    count = full_content.count(raw_text)

    return {
        "file": filepath.replace("\\", "/"),
        "start": start_line,
        "end": end_line,
        "count": count,
        "text": raw_text,
    }


def main():
    args = sys.argv[1:]
    is_json = False
    if "--json" in args:
        is_json = True
        args.remove("--json")

    if len(args) < 3:
        sys.stderr.write("使用方式: python3 scripts/anchor.py <檔案路徑> <起始行> <結束行> [--json]\n")
        sys.exit(2)

    filepath = args[0]
    try:
        start_line = int(args[1])
        end_line = int(args[2])
    except ValueError:
        sys.stderr.write("錯誤: 起始行與結束行必須為整數\n")
        sys.exit(2)

    data = extract_anchor(filepath, start_line, end_line)

    if is_json:
        print(json.dumps(data, ensure_ascii=False))
    else:
        print(f"檔案: {data['file']}")
        print(f"行號: {data['start']}-{data['end']}")
        print(f"count: {data['count']}")
        print("--- 原文開始 ---")
        print(data["text"])
        print("--- 原文結束 ---")

    if data["count"] == 1:
        sys.exit(0)
    else:
        sys.stderr.write(f"錨點不唯一（count={data['count']}），不可作為錨點使用\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
