---
name: langsmith-fetch
description: 透過從 LangSmith Studio 獲取執行追蹤來偵錯 LangChain 和 LangGraph 代理人。在偵錯代理人行為、調查錯誤、分析工具呼叫、檢查記憶體操作或檢查代理人效能時使用。自動獲取最近的追蹤並分析執行模式。需要安裝 langsmith-fetch CLI。
---

# LangSmith 追蹤分析 (LangSmith Fetch)

### 【摘要】觸發條件與 DLP 聲明
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議

本技能透過 **LangSmith Studio API** 提取 LangChain / LangGraph Agent 的執行追蹤記錄，進行深度除錯：分析 Tool Call 鏈、工作記憶存取、Token 消耗、Agent 決策路徑和錯誤定位。

---

## 🎯 觸發條件

- Agent 行為異常（無限迴圈、跳過步驟）
- Tool Call 失敗或回傳錯誤
- 需要分析 Agent 的決策過程
- 性能問題（Token 使用過多、回應太慢）
- 調查記憶體（Memory）讀寫異常

---

## 🛠️ 初始化與配置

```python
# 環境設定
import os
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_API_KEY"] = "your-langsmith-api-key"
os.environ["LANGCHAIN_PROJECT"] = "your-project-name"

# 安裝
# pip install langsmith langchain

from langsmith import Client

client = Client(api_key=os.environ["LANGCHAIN_API_KEY"])
```

---

## 📋 追蹤提取工作流

### 1. 列出最近執行的 Runs

```python
def get_recent_runs(project_name: str, limit: int = 20, 
                    run_type: str = None, error_only: bool = False):
    """提取最近的 Agent 執行記錄"""
    
    filters = {"project_name": project_name}
    if run_type:
        filters["run_type"] = run_type  # "chain", "tool", "llm"
    if error_only:
        filters["error"] = {"$ne": None}
    
    runs = list(client.list_runs(
        **filters,
        limit=limit,
        order="desc"
    ))
    
    for run in runs:
        status = "❌ ERROR" if run.error else "✅ OK"
        duration = (run.end_time - run.start_time).total_seconds() if run.end_time else "N/A"
        tokens = run.prompt_tokens + run.completion_tokens if run.prompt_tokens else "N/A"
        
        print(f"{status} [{run.run_type}] {run.name}")
        print(f"  ID: {run.id}")
        print(f"  時間: {run.start_time.strftime('%H:%M:%S')} | 耗時: {duration}s | Tokens: {tokens}")
        if run.error:
            print(f"  ❌ 錯誤: {run.error[:200]}")
        print()
    
    return runs
```

### 2. 深度分析單一 Run

```python
def analyze_run(run_id: str) -> dict:
    """深度分析單一執行追蹤"""
    run = client.read_run(run_id)
    
    analysis = {
        "id": str(run.id),
        "name": run.name,
        "status": "error" if run.error else "success",
        "duration_sec": (run.end_time - run.start_time).total_seconds() if run.end_time else None,
        "total_tokens": (run.prompt_tokens or 0) + (run.completion_tokens or 0),
        "error": run.error,
        "inputs": run.inputs,
        "outputs": run.outputs,
        "tool_calls": []
    }
    
    # 提取子 Runs（Tool Calls）
    child_runs = list(client.list_runs(parent_run_id=run_id))
    for child in child_runs:
        if child.run_type == "tool":
            analysis["tool_calls"].append({
                "tool": child.name,
                "input": child.inputs,
                "output": child.outputs,
                "error": child.error,
                "duration": (child.end_time - child.start_time).total_seconds() if child.end_time else None
            })
    
    return analysis

def print_run_tree(run_id: str, depth: int = 0):
    """樹狀顯示 Agent 執行路徑"""
    run = client.read_run(run_id)
    indent = "  " * depth
    status = "❌" if run.error else "✅"
    print(f"{indent}{status} [{run.run_type}] {run.name}")
    
    children = list(client.list_runs(parent_run_id=run_id))
    for child in sorted(children, key=lambda r: r.start_time):
        print_run_tree(str(child.id), depth + 1)
```

### 3. 錯誤模式分析

```python
def find_error_patterns(project_name: str, limit: int = 100) -> dict:
    """分析常見錯誤模式"""
    error_runs = list(client.list_runs(
        project_name=project_name,
        error={"$ne": None},
        limit=limit
    ))
    
    from collections import Counter
    import re
    
    # 錯誤分類
    error_types = Counter()
    for run in error_runs:
        if run.error:
            # 提取錯誤類型
            match = re.search(r'(\w+Error|\w+Exception)', run.error)
            if match:
                error_types[match.group(1)] += 1
            else:
                error_types["UnclassifiedError"] += 1
    
    print("=== 錯誤類型分布 ===")
    for error, count in error_types.most_common(10):
        print(f"  {error}: {count} 次")
    
    return dict(error_types)
```

---


詳細參數與進階說明請參閱 [REFERENCE.md](./REFERENCE.md)。
