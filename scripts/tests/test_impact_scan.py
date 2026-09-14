#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tests/test_impact_scan.py

B-68 Phase 1: 確定性反向依賴掃描與證據重放測試套件。
涵蓋全規格金絲雀 A–O 與關鍵真實事故（Critical Real Regression）測試：
A. tracked source exact literal -> hit
B. tracked test assertion 引用同 literal -> 同時 hit
C. untracked same literal -> 不得 hit
D. gitignored same literal -> 不得 hit
E. multiple queries -> deterministic sorted output
F. duplicate query ID -> FAIL
G. malformed query/evidence JSON -> FAIL
H. non-Git repo -> FAIL CLOSED
I. git ls-files failure -> FAIL CLOSED
J. tracked read failure -> FAIL CLOSED (deterministic inject)
K. evidence missing one actual dependency -> CHECK FAIL
L. evidence contains phantom dependency -> CHECK FAIL
M. base OID mismatch -> CHECK FAIL
N. all dependencies exactly represented -> CHECK PASS
O. same input / same HEAD 連跑兩次 -> deterministic equivalent output
CRITICAL REAL REGRESSION:
  production file: scripts/example.py 包含: OLD DISPLAY STRING
  test file: scripts/tests/test_example.py 包含: assert "OLD DISPLAY STRING" ...
  query: OLD DISPLAY STRING
  impact scanner 必須同時找出兩者；若 evidence 只列其一，CHECK / REPLAY 必須 FAIL。
"""

import json
import os
import subprocess
from unittest import mock
import pytest

import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from impact_scan import (
    ImpactScanError,
    SCHEMA_VERSION,
    get_head_oid,
    get_tracked_files,
    run_check_replay,
    run_discovery,
    validate_queries,
)


def init_git_repo(repo_dir: str) -> str:
    """初始化測試用 Git 倉庫並建立 initial commit，回傳 HEAD OID。"""
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True, capture_output=True)
    # 建立一個初始檔案以確保有 HEAD commit
    init_file = os.path.join(repo_dir, ".gitkeep")
    with open(init_file, "w", encoding="utf-8") as f:
        f.write("")
    subprocess.run(["git", "add", ".gitkeep"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo_dir, check=True, capture_output=True)
    return get_head_oid(repo_dir)


def commit_files(repo_dir: str, files_dict: dict[str, str], commit_msg="add files") -> str:
    """寫入檔案並 commit 到 git 倉庫，回傳新的 commit OID。"""
    for rel_path, content in files_dict.items():
        abs_path = os.path.join(repo_dir, rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        subprocess.run(["git", "add", rel_path], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo_dir, check=True, capture_output=True)
    return get_head_oid(repo_dir)


def test_canary_a_b_real_regression(tmp_path):
    """
    Canary A, B 及 Critical Real Regression:
    production file (scripts/example.py) 與 test file (scripts/tests/test_example.py)
    同時包含 'OLD DISPLAY STRING'。
    impact scanner 必須同時找出兩者。
    若 evidence 故意漏掉 test file，CHECK / REPLAY 必須 FAIL！
    """
    repo = str(tmp_path)
    init_git_repo(repo)
    head_oid = commit_files(repo, {
        "scripts/example.py": 'DISPLAY_MSG = "OLD DISPLAY STRING"\nprint(DISPLAY_MSG)\n',
        "scripts/tests/test_example.py": 'from example import DISPLAY_MSG\nassert DISPLAY_MSG == "OLD DISPLAY STRING"\n'
    })

    queries = [{"id": "q1", "kind": "literal", "value": "OLD DISPLAY STRING"}]
    discovery = run_discovery(repo, queries)

    # 必須同時找出兩檔
    res = discovery["results"][0]
    matched = res["matched_paths"]
    assert "scripts/example.py" in matched
    assert "scripts/tests/test_example.py" in matched
    assert len(matched) == 2

    # 行號診斷
    matches_by_path = {m["path"]: m["lines"] for m in res["matches"]}
    assert matches_by_path["scripts/example.py"] == [1]
    assert matches_by_path["scripts/tests/test_example.py"] == [2]

    # 若 evidence 故意只列 scripts/example.py -> CHECK / REPLAY 必須 FAIL
    incomplete_evidence = {
        "schema_version": SCHEMA_VERSION,
        "base_oid": head_oid,
        "mode": "REQUIRED",
        "queries": queries,
        "results": [
            {
                "query_id": "q1",
                "query_kind": "literal",
                "query_value": "OLD DISPLAY STRING",
                "dependencies": [
                    {"path": "scripts/example.py", "disposition": "UPDATE", "lines": [1]}
                ]
            }
        ]
    }
    is_pass, errors = run_check_replay(repo, incomplete_evidence)
    assert not is_pass
    assert any("scripts/tests/test_example.py" in err and "遺漏實際依賴路徑" in err for err in errors)

    # 若 evidence 完整列出兩檔且有合法 disposition -> CHECK PASS
    complete_evidence = {
        "schema_version": SCHEMA_VERSION,
        "base_oid": head_oid,
        "mode": "REQUIRED",
        "queries": queries,
        "results": [
            {
                "query_id": "q1",
                "query_kind": "literal",
                "query_value": "OLD DISPLAY STRING",
                "dependencies": [
                    {"path": "scripts/example.py", "disposition": "UPDATE", "lines": [1]},
                    {"path": "scripts/tests/test_example.py", "disposition": "UPDATE", "lines": [2]}
                ]
            }
        ]
    }
    is_pass, errors = run_check_replay(repo, complete_evidence)
    assert is_pass
    assert len(errors) == 0


def test_canary_c_d_untracked_and_gitignored(tmp_path):
    """
    Canary C: untracked same literal -> 不得 hit
    Canary D: gitignored same literal -> 不得 hit
    """
    repo = str(tmp_path)
    init_git_repo(repo)

    # commit tracked 檔案
    commit_files(repo, {
        "tracked.py": "TARGET_LITERAL = 42\n",
        ".gitignore": "ignored/\n*.bak\n"
    })

    # 建立 untracked 檔案（未 git add）
    with open(os.path.join(repo, "untracked.py"), "w", encoding="utf-8") as f:
        f.write("TARGET_LITERAL = 42\n")

    # 建立 gitignored 檔案
    os.makedirs(os.path.join(repo, "ignored"), exist_ok=True)
    with open(os.path.join(repo, "ignored", "secret.py"), "w", encoding="utf-8") as f:
        f.write("TARGET_LITERAL = 42\n")

    with open(os.path.join(repo, "backup.bak"), "w", encoding="utf-8") as f:
        f.write("TARGET_LITERAL = 42\n")

    queries = [{"id": "q1", "kind": "symbol", "value": "TARGET_LITERAL"}]
    discovery = run_discovery(repo, queries)

    matched = discovery["results"][0]["matched_paths"]
    assert matched == ["tracked.py"]
    assert "untracked.py" not in matched
    assert "ignored/secret.py" not in matched
    assert "backup.bak" not in matched


def test_canary_e_multiple_queries_deterministic_sort(tmp_path):
    """
    Canary E: multiple queries -> deterministic sorted output
    """
    repo = str(tmp_path)
    init_git_repo(repo)
    commit_files(repo, {
        "b_file.py": "FOO_BAR = 1\n",
        "a_file.py": "HELLO_WORLD = 2\nFOO_BAR = 3\n"
    })

    # 提供未排序的 queries
    queries = [
        {"id": "z_query", "kind": "symbol", "value": "FOO_BAR"},
        {"id": "a_query", "kind": "symbol", "value": "HELLO_WORLD"}
    ]
    discovery = run_discovery(repo, queries)

    # 驗證 queries 依 id 排序
    assert discovery["queries"][0]["id"] == "a_query"
    assert discovery["queries"][1]["id"] == "z_query"

    # 驗證 results 依 query_id 排序
    assert discovery["results"][0]["query_id"] == "a_query"
    assert discovery["results"][0]["matched_paths"] == ["a_file.py"]

    assert discovery["results"][1]["query_id"] == "z_query"
    # 檔案路徑也必須確定性排序 a_file.py 在 b_file.py 前
    assert discovery["results"][1]["matched_paths"] == ["a_file.py", "b_file.py"]


def test_canary_f_duplicate_query_id():
    """Canary F: duplicate query ID -> FAIL"""
    queries = [
        {"id": "dup", "kind": "literal", "value": "ONE"},
        {"id": "dup", "kind": "literal", "value": "TWO"}
    ]
    with pytest.raises(ImpactScanError) as exc:
        validate_queries(queries)
    assert "重複的 query ID" in str(exc.value)


def test_canary_g_malformed_query():
    """Canary G: malformed query -> FAIL"""
    # 非法 kind
    with pytest.raises(ImpactScanError) as exc:
        validate_queries([{"id": "q1", "kind": "invalid_kind", "value": "test"}])
    assert "kind 非法" in str(exc.value)

    # 空值
    with pytest.raises(ImpactScanError) as exc:
        validate_queries([{"id": "q1", "kind": "literal", "value": ""}])
    assert "value 必須為非空字串" in str(exc.value)

    # 缺 id
    with pytest.raises(ImpactScanError) as exc:
        validate_queries([{"kind": "literal", "value": "hello"}])
    assert "缺少合法 'id'" in str(exc.value)


def test_canary_h_non_git_repo(tmp_path):
    """Canary H: non-Git repo -> FAIL CLOSED"""
    non_git = str(tmp_path / "not_a_repo")
    os.makedirs(non_git)
    with pytest.raises(ImpactScanError) as exc:
        get_tracked_files(non_git)
    assert "git ls-files 執行失敗" in str(exc.value) or "無法執行" in str(exc.value)


def test_canary_i_git_ls_files_failure(tmp_path):
    """Canary I: git ls-files failure -> FAIL CLOSED"""
    repo = str(tmp_path)
    init_git_repo(repo)

    # 模擬 subprocess.run 失敗
    with mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=128, stdout=b"", stderr=b"fatal: corrupted git repo")
        with pytest.raises(ImpactScanError) as exc:
            get_tracked_files(repo)
        assert "git ls-files 執行失敗" in str(exc.value)


def test_canary_j_tracked_read_failure(tmp_path):
    """Canary J: tracked read failure -> FAIL CLOSED"""
    repo = str(tmp_path)
    init_git_repo(repo)
    commit_files(repo, {"file.txt": "some content\n"})

    # 模擬開啟檔案時拋出 OSError
    with mock.patch("builtins.open", side_effect=PermissionError("Permission denied")):
        with pytest.raises(ImpactScanError) as exc:
            run_discovery(repo, [{"id": "q1", "kind": "literal", "value": "content"}])
        assert "讀取追蹤檔案失敗" in str(exc.value)


def test_canary_k_missing_dependency(tmp_path):
    """Canary K: evidence missing one actual dependency -> CHECK FAIL"""
    repo = str(tmp_path)
    init_git_repo(repo)
    head_oid = commit_files(repo, {
        "file1.py": "COMMON_KEY = 'val'\n",
        "file2.py": "COMMON_KEY = 'val'\n"
    })

    evidence = {
        "schema_version": SCHEMA_VERSION,
        "base_oid": head_oid,
        "mode": "REQUIRED",
        "queries": [{"id": "q1", "kind": "literal", "value": "COMMON_KEY"}],
        "results": [
            {
                "query_id": "q1",
                "query_kind": "literal",
                "query_value": "COMMON_KEY",
                "dependencies": [
                    {"path": "file1.py", "disposition": "UPDATE"}
                    # file2.py 遺漏
                ]
            }
        ]
    }
    is_pass, errors = run_check_replay(repo, evidence)
    assert not is_pass
    assert any("file2.py" in err and "遺漏實際依賴路徑" in err for err in errors)


def test_canary_l_phantom_dependency(tmp_path):
    """Canary L: evidence contains phantom dependency -> CHECK FAIL"""
    repo = str(tmp_path)
    init_git_repo(repo)
    head_oid = commit_files(repo, {
        "file1.py": "MY_CONST = 1\n"
    })

    evidence = {
        "schema_version": SCHEMA_VERSION,
        "base_oid": head_oid,
        "mode": "REQUIRED",
        "queries": [{"id": "q1", "kind": "literal", "value": "MY_CONST"}],
        "results": [
            {
                "query_id": "q1",
                "query_kind": "literal",
                "query_value": "MY_CONST",
                "dependencies": [
                    {"path": "file1.py", "disposition": "UPDATE"},
                    {"path": "ghost_file.py", "disposition": "UPDATE"}  # 幽靈依賴
                ]
            }
        ]
    }
    is_pass, errors = run_check_replay(repo, evidence)
    assert not is_pass
    assert any("ghost_file.py" in err and "包含幽靈依賴路徑" in err for err in errors)


def test_canary_m_base_oid_mismatch(tmp_path):
    """Canary M: base OID mismatch -> CHECK FAIL"""
    repo = str(tmp_path)
    init_git_repo(repo)
    commit_files(repo, {"file.py": "DATA = 100\n"})

    evidence = {
        "schema_version": SCHEMA_VERSION,
        "base_oid": "0000000000000000000000000000000000000000",  # 錯誤 OID
        "mode": "REQUIRED",
        "queries": [{"id": "q1", "kind": "literal", "value": "DATA"}],
        "results": [
            {
                "query_id": "q1",
                "query_kind": "literal",
                "query_value": "DATA",
                "dependencies": [{"path": "file.py", "disposition": "UPDATE"}]
            }
        ]
    }
    is_pass, errors = run_check_replay(repo, evidence)
    assert not is_pass
    assert any("Base OID mismatch" in err for err in errors)


def test_canary_n_all_dependencies_exactly_represented(tmp_path):
    """Canary N: all dependencies exactly represented -> CHECK PASS"""
    repo = str(tmp_path)
    init_git_repo(repo)
    head_oid = commit_files(repo, {
        "src/a.py": "SHARED_TOKEN = 'abc'\n",
        "src/b.py": "token = SHARED_TOKEN\n",
        "docs/ref.md": "See SHARED_TOKEN for details\n"
    })

    evidence = {
        "schema_version": SCHEMA_VERSION,
        "base_oid": head_oid,
        "mode": "REQUIRED",
        "queries": [{"id": "q1", "kind": "symbol", "value": "SHARED_TOKEN"}],
        "results": [
            {
                "query_id": "q1",
                "query_kind": "symbol",
                "query_value": "SHARED_TOKEN",
                "dependencies": [
                    {"path": "src/a.py", "disposition": "UPDATE"},
                    {"path": "src/b.py", "disposition": "VERIFY_ONLY"},
                    {"path": "docs/ref.md", "disposition": "HISTORICAL_NO_CHANGE"}
                ]
            }
        ]
    }
    is_pass, errors = run_check_replay(repo, evidence)
    assert is_pass
    assert len(errors) == 0


def test_canary_o_deterministic_repeatability(tmp_path):
    """Canary O: same input / same HEAD 連跑兩次 -> deterministic equivalent output"""
    repo = str(tmp_path)
    init_git_repo(repo)
    commit_files(repo, {
        "file1.py": "KEY_A = 1\nKEY_B = 2\n",
        "file2.py": "KEY_B = 20\nKEY_A = 10\n"
    })

    queries = [
        {"id": "q_b", "kind": "literal", "value": "KEY_B"},
        {"id": "q_a", "kind": "literal", "value": "KEY_A"}
    ]
    run1 = run_discovery(repo, queries)
    run2 = run_discovery(repo, queries)

    # 兩次執行的 dict 與 JSON 字串必須完全一致
    assert run1 == run2
    json1 = json.dumps(run1, sort_keys=True)
    json2 = json.dumps(run2, sort_keys=True)
    assert json1 == json2


def test_no_semantic_inference(tmp_path):
    """驗證嚴禁模糊或語意推論：相似或部分詞彙不得被誤判為 dependency。"""
    repo = str(tmp_path)
    init_git_repo(repo)
    commit_files(repo, {
        "file1.py": "OLD_DISPLAY_STRING_V2 = 1\n",
        "file2.py": "OLD DISPLAY STRING\n",
        "file3.py": "old display string\n"  # 忽略大小寫在 Phase 1 算 mismatch
    })

    queries = [{"id": "q1", "kind": "literal", "value": "OLD DISPLAY STRING"}]
    discovery = run_discovery(repo, queries)

    matched = discovery["results"][0]["matched_paths"]
    assert matched == ["file2.py"]
    assert "file1.py" not in matched
    assert "file3.py" not in matched


def test_mode_none_with_reason(tmp_path):
    """驗證 mode=NONE 支援，且必須有非空 reason。"""
    repo = str(tmp_path)
    head_oid = init_git_repo(repo)

    # 合法 NONE
    ev_valid = {
        "schema_version": SCHEMA_VERSION,
        "base_oid": head_oid,
        "mode": "NONE",
        "reason": "Isolated create-only operation"
    }
    is_pass, errors = run_check_replay(repo, ev_valid)
    assert is_pass
    assert len(errors) == 0

    # 缺 reason
    ev_no_reason = {
        "schema_version": SCHEMA_VERSION,
        "base_oid": head_oid,
        "mode": "NONE"
    }
    is_pass, errors = run_check_replay(repo, ev_no_reason)
    assert not is_pass
    assert any("reason" in err for err in errors)
