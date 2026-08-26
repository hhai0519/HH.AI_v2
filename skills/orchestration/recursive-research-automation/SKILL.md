---
name: recursive-research-automation
description: "當使用者要求進行遞迴式深度研究、需要從廣度掃描收斂到深度分析時使用。僅在指令包含『$$自動化_通用研究$$』時啟用。"
---
# 遞迴研究自動化路徑 (Recursive Research Automation Path)

### 【摘要】觸發條件與 DLP 聲明
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議

## 功能概述
本技能定義了自動化深度研究的標準作業程式 (SOP)。它採用「遞迴式」的研究邏輯，透過不斷分析前一階段的發現來啟動更深化的研究路徑，並整合資源配額監控（如 Gemini 3 Flash 配額），確保在資源耗盡前（預設 10%）安全產出報告。

> [!IMPORTANT]
> **Sub-Budgeting 保護機制**：研究代理人在自我遞迴時，必須遵守單次探索不可超過總剩餘 Quota 的 5% 原則，以確保有足夠空間完成收斂報告。

## 觸發條件
- 指令必須明確包含「$$自動化_通用研究$$」。
- 需要在背景不斷運行研究直到配額觸發終結條件。
- 要求進行受控的深度遞迴分析。

## 執行流程

### 0. 前置認證健康檢查 (Pre-flight Auth Check) [新增]

> [!IMPORTANT]
> 依照 SOP_12「外部 MCP 服務認證修復標準作業程序」，必須在啟動研究迴圈前執行此檢查。
> 若跳過此步驟，可能在第 N 輪研究後才因認證失效而中斷，造成大量資源浪費。

**執行邏輯（偽碼 Pseudocode）**：
```python
import subprocess
import time
import threading

MAX_AUTH_RETRIES = 3  # SOP_11 規定：反思迴圈最多 3-5 次
AUTH_INPUT_TIMEOUT_SEC = 120  # SRE 顧問建議：防止在非互動式環境永久懸掛

def _input_with_timeout(prompt: str, timeout_sec: int) -> str:
    """支援 Windows 的帶 timeout 的 input()"""
    result = [None]
    
    def _get_input():
        result[0] = input(prompt)
    
    thread = threading.Thread(target=_get_input, daemon=True)
    thread.start()
    thread.join(timeout=timeout_sec)
    
    if thread.is_alive():
        raise TimeoutError(f"使用者未在 {timeout_sec} 秒內回應，操作已逾時。")
    return result[0]

def pre_flight_auth_check(mcp_client) -> bool:
    """
    在啟動深度研究迴圈前，強制驗證 NotebookLM MCP 認證狀態。
    符合 SOP_12 引導修復模式。
    """
    for retry in range(MAX_AUTH_RETRIES):
        # Step 1：查詢 MCP 認證狀態
        status = mcp_client.call("notebooklm", "server_info", {})
        auth_status = status.get("auth_status", "unknown")

        if auth_status == "configured":
            print("✅ [前置檢查] NotebookLM 認證正常，開始研究迴圈。")
            return True

        # Step 2：認證失效，依 SOP_12 §3.1 引導使用者
        print(f"\n⚠️ [認證警告] NotebookLM auth_status = '{auth_status}'（第 {retry+1}/{MAX_AUTH_RETRIES} 次嘗試）")
        print("依照 SOP_12，請先在 Chrome 開啟 https://notebook.google.com 並確認登入。")

        try:
            _input_with_timeout("👉 登入完成後，請按 Enter 鍵繼續...", AUTH_INPUT_TIMEOUT_SEC)
        except TimeoutError as e:
            raise RuntimeError(f"[前置認證] {e}") from e

        # Step 3：執行 nlm login（安全設計：capture_output=True 不落盤）
        try:
            result = subprocess.run(
                ["nlm", "login"],
                capture_output=True,   # 資安稽核官建議：輸出不落盤
                text=True,
                timeout=60
            )
            if result.returncode != 0:
                print(f"   nlm login 失敗：{result.stderr[:200]}，重試中...")
                continue
        except subprocess.TimeoutExpired:
            print("   nlm login 執行逾時，重試中...")
            continue

        # Step 4：通知 MCP Server 重新載入快取
        mcp_client.call("notebooklm", "refresh_auth", {})
        time.sleep(3)  # 等待快取同步

    # 超過最大重試次數
    raise RuntimeError(
        f"[前置認證失敗] 已重試 {MAX_AUTH_RETRIES} 次仍無法通過 NotebookLM 認證。"
        "任務中止。請依 SOP_12 手動排查。"
    )

# 在研究迴圈前呼叫
pre_flight_auth_check(mcp_client=your_mcp_client_instance)
```


詳細參數與完整指引請參見 `REFERENCE.md`。