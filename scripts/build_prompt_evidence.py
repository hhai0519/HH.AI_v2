#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/build_prompt_evidence.py

以批次規格（batch spec）為單一來源，機械化產生提示詞證據區塊：
1. 解析 spec
2. 錨點唯一性驗證（count=1）
3. 產生 E11 區塊（錨點總數由 len(mods) 產生）
4. 產生 (b)(d) 行數與圍欄數區塊
5. 模擬並產生 (e) 區塊（check_consistency 檢查與尾三條 CHECK 10 INFO 行）
6. 驗證 EXPECT 區塊（ID 序列連續性驗證）

相依限制：只用 Python 標準庫。
"""

import io
import os
import re
import sys
import argparse
import hashlib
import shutil
import subprocess
import tempfile
import glob


class SpecParseError(Exception):
    def __init__(self, message, line_no=None):
        super().__init__(message)
        self.message = message
        self.line_no = line_no

    def __str__(self):
        if self.line_no is not None:
            return f"第 {self.line_no} 行解析錯誤: {self.message}"
        return f"解析錯誤: {self.message}"


def parse_spec(spec_text):
    """
    解析批次規格文字。
    回傳 (head, mods, expects)
    """
    lines = spec_text.splitlines()
    head = None
    mods = []
    expects = []

    state = "TOP"
    current_mod = None
    current_expect = None
    anchor_lines = []
    payload_lines = []

    valid_modes = {"insert_after", "insert_before", "replace", "create_file"}

    for idx, raw_line in enumerate(lines, 1):
        # 註解只在 TOP, MOD_HEADER, EXPECT_HEADER 有效
        if state in ("TOP", "MOD_HEADER", "EXPECT_HEADER"):
            stripped = raw_line.strip()
            if stripped.startswith("#"):
                continue

        if state == "TOP":
            stripped = raw_line.strip()
            if not stripped:
                continue
            if stripped.startswith("HEAD:"):
                head = stripped[len("HEAD:"):].strip()
                continue

            mod_match = re.match(r"^=== MOD (\S+) ===$", stripped)
            if mod_match:
                mod_id = mod_match.group(1)
                current_mod = {
                    "id": mod_id,
                    "file": None,
                    "mode": None,
                    "anchor": None,
                    "payload": None,
                    "line": idx,
                }
                state = "MOD_HEADER"
                continue

            expect_match = re.match(r"^=== EXPECT(?: (\S+))? ===$", stripped)
            if expect_match:
                exp_id = expect_match.group(1) or str(len(expects) + 1)
                current_expect = {
                    "id": exp_id,
                    "type": None,
                    "file": None,
                    "pattern": None,
                    "range": None,
                    "line": idx,
                }
                state = "EXPECT_HEADER"
                continue

            raise SpecParseError(f"未預期的內容: {stripped}", idx)

        elif state == "MOD_HEADER":
            stripped = raw_line.strip()
            if not stripped:
                continue
            if stripped.startswith("file:"):
                if current_mod["file"] is not None:
                    raise SpecParseError("重複定義 file 欄位", idx)
                current_mod["file"] = stripped[len("file:"):].strip()
                continue
            if stripped.startswith("mode:"):
                if current_mod["mode"] is not None:
                    raise SpecParseError("重複定義 mode 欄位", idx)
                mode_val = stripped[len("mode:"):].strip()
                if mode_val not in valid_modes:
                    raise SpecParseError(f"無效的 mode: {mode_val}，必須為 {valid_modes}", idx)
                current_mod["mode"] = mode_val
                continue
            if raw_line == "--- ANCHOR ---":
                if not current_mod["file"]:
                    raise SpecParseError("MOD 缺少 file 欄位", idx)
                if not current_mod["mode"]:
                    raise SpecParseError("MOD 缺少 mode 欄位", idx)
                anchor_lines = []
                state = "IN_ANCHOR"
                continue
            if raw_line == "--- PAYLOAD ---":
                if not current_mod["file"]:
                    raise SpecParseError("MOD 缺少 file 欄位", idx)
                if not current_mod["mode"]:
                    raise SpecParseError("MOD 缺少 mode 欄位", idx)
                if current_mod["mode"] == "create_file":
                    current_mod["anchor"] = ""
                    payload_lines = []
                    state = "IN_PAYLOAD"
                    continue
                raise SpecParseError("MOD 缺少 ANCHOR 區塊", idx)
            raise SpecParseError(f"MOD 標頭區語法錯誤: {stripped}", idx)

        elif state == "IN_ANCHOR":
            if raw_line == "--- PAYLOAD ---":
                current_mod["anchor"] = "\n".join(anchor_lines)
                if current_mod["mode"] == "create_file" and current_mod["anchor"].strip() != "":
                    raise SpecParseError("create_file 的 ANCHOR 必須為空", current_mod["line"])
                payload_lines = []
                state = "IN_PAYLOAD"
                continue
            if raw_line == "--- END MOD ---":
                raise SpecParseError("MOD 缺少 PAYLOAD 區塊", idx)
            anchor_lines.append(raw_line)

        elif state == "IN_PAYLOAD":
            if raw_line == "--- END MOD ---":
                current_mod["payload"] = "\n".join(payload_lines)
                if current_mod["mode"] != "create_file":
                    if current_mod["anchor"] is None or not current_mod["anchor"]:
                        raise SpecParseError("MOD 的 ANCHOR 不得為空", current_mod["line"])
                else:
                    if current_mod["anchor"] is None:
                        current_mod["anchor"] = ""
                for m in mods:
                    if m["file"] == current_mod["file"]:
                        if current_mod["mode"] == "create_file" or m["mode"] == "create_file":
                            raise SpecParseError(f"同一檔案 {current_mod['file']} 不得重複 create_file 或混用不同模式", idx)
                mods.append(current_mod)
                current_mod = None
                state = "TOP"
                continue
            payload_lines.append(raw_line)

        elif state == "EXPECT_HEADER":
            stripped = raw_line.strip()
            if not stripped:
                continue
            if stripped.startswith("type:"):
                current_expect["type"] = stripped[len("type:"):].strip()
                continue
            if stripped.startswith("file:"):
                current_expect["file"] = stripped[len("file:"):].strip()
                continue
            if stripped.startswith("pattern:"):
                current_expect["pattern"] = stripped[len("pattern:"):].strip()
                continue
            if stripped.startswith("range:"):
                current_expect["range"] = stripped[len("range:"):].strip()
                continue
            if raw_line == "--- END EXPECT ---":
                for field in ("type", "file", "pattern", "range"):
                    if not current_expect.get(field):
                        raise SpecParseError(f"EXPECT 區塊缺少 {field} 欄位", idx)
                expects.append(current_expect)
                current_expect = None
                state = "TOP"
                continue
            raise SpecParseError(f"EXPECT 標頭區語法錯誤: {stripped}", idx)

    if state != "TOP":
        raise SpecParseError(f"規格檔案未正常結束，仍處於狀態 {state}", len(lines))

    return head, mods, expects


def verify_anchors(mods, repo_root):
    """
    在工作區目標檔案中檢查各 MOD 的錨點唯一性。
    若 count != 1，印出命中位置後回傳 False，否則回傳 (True, results)。
    """
    results = []
    for mod in mods:
        fpath = os.path.join(repo_root, mod["file"])
        if mod["mode"] == "create_file":
            if os.path.exists(fpath):
                print(f"[錨點] MOD {mod['id']}  {mod['file']}:0  count=0")
                print(f"[錯誤] create_file 目標檔案在基準中已存在: {mod['file']}")
                return False, results
            results.append((mod, 0))
            continue

        if not os.path.isfile(fpath):
            print(f"[錨點] MOD {mod['id']}  {mod['file']}:0  count=0")
            print(f"[錯誤] 目標檔案不存在: {mod['file']}")
            return False, results

        with io.open(fpath, encoding="utf-8") as f:
            content = f.read()

        anchor = mod["anchor"]
        count = content.count(anchor)

        if count == 0:
            print(f"[錨點] MOD {mod['id']}  {mod['file']}:0  count=0")
            print(f"[錯誤] MOD {mod['id']} 錨點未命中 (count=0)")
            return False, results
        elif count > 1:
            positions = []
            pos = 0
            while True:
                idx = content.find(anchor, pos)
                if idx == -1:
                    break
                line_no = content.count("\n", 0, idx) + 1
                positions.append(line_no)
                pos = idx + 1
            print(f"[錨點] MOD {mod['id']}  {mod['file']}:{positions[0]}  count={count}")
            pos_str = ", ".join(f"第 {p} 行" for p in positions)
            print(f"[錯誤] MOD {mod['id']} 錨點重複命中 {count} 次，位置: {pos_str}")
            return False, results
        else:
            idx = content.find(anchor)
            line_no = content.count("\n", 0, idx) + 1
            results.append((mod, line_no))

    return True, results


def format_e11(mods, anchor_results):
    """
    產生 E11 區塊，總數必須由 len(mods) 產生。
    """
    lines = [f"[E11] 錨點總數: {len(mods)}"]
    for mod, line_no in anchor_results:
        if mod["mode"] == "create_file":
            lines.append(f"[錨點] MOD {mod['id']}  {mod['file']}:new  count=1 (create_file)")
        else:
            lines.append(f"[錨點] MOD {mod['id']}  {mod['file']}:{line_no}  count=1")
    return "\n".join(lines)


def format_bcd(mods, repo_root):
    """
    產生 (b)(d) 區塊：檔案行數與圍欄數。
    """
    seen_files = []
    for mod in mods:
        if mod["file"] not in seen_files:
            seen_files.append(mod["file"])

    output_lines = []
    for frel in seen_files:
        fpath = os.path.join(repo_root, frel)
        if not os.path.isfile(fpath):
            continue
        with io.open(fpath, encoding="utf-8") as f:
            text = f.read()
        lines = text.splitlines()
        line_count = len(lines)
        fence_count = sum(1 for l in lines if l.strip().startswith("```"))
        output_lines.append(f"[b] {frel}  {line_count}")
        output_lines.append(f"[d] {frel}  圍欄 {fence_count}")
    return "\n".join(output_lines)


def apply_mod_to_text(content, mod):
    """
    將單一 MOD 套用至檔案內容字串。
    """
    mode = mod["mode"]
    payload = mod["payload"]

    if mode == "create_file":
        if content is not None:
            raise ValueError(f"create_file 目標檔案在 base 已存在: {mod['file']}")
        return payload

    if content is None:
        raise ValueError(f"目標檔案不存在: {mod['file']}")

    anchor = mod["anchor"]
    if content.count(anchor) != 1:
        raise ValueError(f"套用 MOD {mod['id']} 時錨點 count != 1")

    if mode == "replace":
        idx = content.find(anchor)
        return content[:idx] + payload + content[idx + len(anchor):]

    elif mode == "insert_after":
        idx = content.find(anchor)
        anchor_end = idx + len(anchor)
        if anchor.endswith("\n"):
            insert_pos = anchor_end
        else:
            nl = content.find("\n", anchor_end)
            insert_pos = len(content) if nl == -1 else nl + 1
        p = payload if payload.endswith("\n") else payload + "\n"
        return content[:insert_pos] + p + content[insert_pos:]

    elif mode == "insert_before":
        idx = content.find(anchor)
        prev_nl = content.rfind("\n", 0, idx)
        line_start = 0 if prev_nl == -1 else prev_nl + 1
        p = payload if payload.endswith("\n") else payload + "\n"
        return content[:line_start] + p + content[line_start:]

    else:
        raise ValueError(f"未知 mode: {mode}")


def simulate_and_verify(mods, expects, repo_root):
    """
    在臨時目錄中模擬套用全部 MOD，執行 check_consistency.py 與 EXPECT 驗證。
    """
    temp_dir = tempfile.mkdtemp(prefix="bpe_sim_")
    try:
        shutil.copytree(repo_root, temp_dir, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))

        # 套用 MODs
        for mod in mods:
            fpath = os.path.join(temp_dir, mod["file"])
            if mod["mode"] == "create_file":
                if os.path.exists(fpath):
                    raise ValueError(f"create_file 目標檔案在 base 已存在: {mod['file']}")
                pdir = os.path.dirname(fpath)
                if pdir:
                    os.makedirs(pdir, exist_ok=True)
                new_content = apply_mod_to_text(None, mod)
            else:
                if not os.path.isfile(fpath):
                    raise ValueError(f"目標檔案不存在: {mod['file']}")
                with io.open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                new_content = apply_mod_to_text(content, mod)
            with io.open(fpath, "w", encoding="utf-8", newline="\n") as f:
                f.write(new_content)

        # 執行 check_consistency.py
        check_script = os.path.join(temp_dir, "scripts", "check_consistency.py")
        if not os.path.isfile(check_script):
            print(f"[錯誤] 模擬副本中找不到 scripts/check_consistency.py")
            return False

        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [sys.executable, check_script],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        stdout = proc.stdout or ""
        summary_match = re.search(r"總結: 通過 (\d+) 項, 失敗 (\d+) 項", stdout)
        if summary_match:
            passed = int(summary_match.group(1))
            failed = int(summary_match.group(2))
        else:
            passed = 0
            failed = 1 if proc.returncode != 0 else 0

        print(f"[模擬] check_consistency: 通過 {passed} 項, 失敗 {failed} 項")

        if failed > 0 or proc.returncode != 0:
            print("[錯誤] check_consistency 模擬未通過:")
            print(stdout)
            if proc.stderr:
                print(proc.stderr)
            return False

        # 產生 (e-1) 與 (e-3)
        seen_files = []
        for mod in mods:
            if mod["file"] not in seen_files:
                seen_files.append(mod["file"])

        for frel in seen_files:
            fpath = os.path.join(temp_dir, frel)
            with io.open(fpath, encoding="utf-8") as f:
                t = f.read()
            lines = t.splitlines()
            line_count = len(lines)
            fence_count = sum(1 for l in lines if l.strip().startswith("```"))
            fsha = hashlib.sha256(t.encode("utf-8")).hexdigest()
            print(f"[e-1] {frel}  套用後 {line_count} 行  圍欄 {fence_count}  sha256={fsha}")

            # 擷取 CHECK 10 INFO 行
            # 從 CHECK 10 區塊中尋找
            c10_match = re.search(r"CHECK 10 - [^\n]+\n(.*?)(?=\nCHECK \d+|\n=|$)", stdout, re.S)
            if c10_match:
                c10_text = c10_match.group(1)
                norm_rel = frel.replace("\\", "/")
                info_lines = [
                    l.strip()
                    for l in c10_text.splitlines()
                    if "[INFO]" in l and (norm_rel in l.replace("\\", "/"))
                ]
                last3 = info_lines[-3:]
                for il in last3:
                    print(f"[e-3] {il}")

        # 驗證 EXPECT 區塊
        for exp in expects:
            if exp["type"] == "id_sequence":
                exp_file = os.path.join(temp_dir, exp["file"])
                if not os.path.isfile(exp_file):
                    print(f"[EXPECT] {exp['file']}  {exp['pattern']}  宣告 {exp['range']}  實測 0 個  不符")
                    print(f"[錯誤] EXPECT 目標檔案不存在: {exp['file']}")
                    return False

                with io.open(exp_file, encoding="utf-8") as f:
                    exp_text = f.read()

                found_ids = [int(m) for m in re.findall(exp["pattern"], exp_text, re.M)]
                sorted_ids = sorted(found_ids)

                range_parts = exp["range"].split("-")
                start_id = int(range_parts[0])
                end_id = int(range_parts[1])
                expected_ids = list(range(start_id, end_id + 1))

                is_match = (sorted_ids == expected_ids)
                status_str = "相符" if is_match else "不符"
                print(f"[EXPECT] {exp['file']}  {exp['pattern']}  宣告 {exp['range']}  實測 {len(sorted_ids)} 個  {status_str}")

                if not is_match:
                    missing = sorted(list(set(expected_ids) - set(sorted_ids)))
                    extra = sorted(list(set(sorted_ids) - set(expected_ids)))
                    print(f"[錯誤] EXPECT 驗證不符:")
                    print(f"  實測序列: {sorted_ids}")
                    if missing:
                        print(f"  缺號: {missing}")
                    if extra:
                        print(f"  多出: {extra}")
                    return False

        return True

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(description="Build prompt evidence from batch spec")
    parser.add_argument("spec", help="批次規格檔案路徑")
    parser.add_argument("--check-only", action="store_true", help="只做錨點唯一性驗證，不做模擬")
    parser.add_argument("--repo-root", default=None, help="Repo 根目錄路徑（選用）")
    args = parser.parse_args(argv)

    if args.repo_root:
        repo_root = os.path.abspath(args.repo_root)
    else:
        # 預設為 script 所在 repo
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    if not os.path.isfile(args.spec):
        print(f"[錯誤] 規格檔案不存在: {args.spec}", file=sys.stderr)
        sys.exit(2)

    with io.open(args.spec, encoding="utf-8") as f:
        spec_content = f.read()

    try:
        head, mods, expects = parse_spec(spec_content)
    except SpecParseError as e:
        print(f"[錯誤] {e}", file=sys.stderr)
        sys.exit(2)

    # 證據必須與規格 bytes 綁定：先印出規格身分，再做任何事。
    # 目的是讓「產生證據的規格」與「執行者手上的規格」可被機械比對，
    # 不再依賴「此證據未經修改」這種文字宣稱。
    spec_sha = hashlib.sha256(spec_content.encode("utf-8")).hexdigest()
    print(f"[SPEC] path={os.path.basename(args.spec)}")
    print(f"[SPEC] sha256={spec_sha}")

    def _oid(rev):
        # commit identity 一律解析成完整 40 碼 OID。
        # 不存在、有歧義、不是 commit，一律回 None。
        # 不使用 short hash 或 startswith——前綴相同不代表是同一個 commit，
        # 且必須與 check_consistency.py 的 CHECK 17 使用相同的 Git 語意。
        r = subprocess.run(["git", "rev-parse", "--verify", f"{rev}^{{commit}}"],
                           cwd=repo_root, capture_output=True, text=True)
        o = r.stdout.strip()
        return o if r.returncode == 0 and len(o) == 40 else None

    _rr = subprocess.run(["git", "rev-parse", "--git-dir"],
                         cwd=repo_root, capture_output=True, text=True)
    in_repo = _rr.returncode == 0
    if not in_repo:
        # 沒有 repository 可比對（例如規格格式的單元測試用臨時目錄）。
        # 這是「不適用」，不是「解析失敗」；後者在有 repo 時一律 S1。
        print(f"[SPEC] base={head}  (此路徑非 git repository，略過 base identity 比對)"
              f"  mods={len(mods)}")
        head_oid = base_oid = None
    else:
        head_oid = _oid("HEAD")
        base_oid = _oid(head) if head else None
        print(f"[SPEC] base={head}  base_oid={base_oid}  head_oid={head_oid}  mods={len(mods)}")
    if in_repo and head_oid is None:
        print("[錯誤] repository 存在但無法把工作區 HEAD 解析為唯一 commit OID；S1，停止",
              file=sys.stderr)
        sys.exit(2)
    if in_repo and base_oid is None:
        print(f"[錯誤] 規格宣告的 base={head} 無法解析為唯一 commit"
              f"（不存在、有歧義，或不是 commit）；S1，停止", file=sys.stderr)
        sys.exit(2)
    if in_repo and base_oid != head_oid:
        print(f"[錯誤] 規格 base 與工作區 HEAD 不是同一個 commit："
              f"base={base_oid} head={head_oid}；S1，停止", file=sys.stderr)
        sys.exit(2)
    ok, anchor_results = verify_anchors(mods, repo_root)
    if not ok:
        sys.exit(1)

    print(format_e11(mods, anchor_results))
    print(format_bcd(mods, repo_root))

    if not args.check_only:
        sim_ok = simulate_and_verify(mods, expects, repo_root)
        if not sim_ok:
            sys.exit(1)

    print("[完成] 全部檢查通過，以上輸出可直接貼入提示詞的證據區塊")
    return 0


if __name__ == "__main__":
    sys.exit(main())
