# ADR-0012: 分散式悲觀鎖機制 (Distributed Pessimistic Lock)

- Status: Accepted
- Date: 2026-08-24

## Context

在多 Agent 協作環境下，系統原先採用本地 `FileTimeTracker` 作為樂觀鎖機制來治理 Agent 之間的衝突。然而，隨著系統架構演進至 Loki Swarm 雙管線架構（參照 **ADR-0008**），單純的本地樂觀鎖已無法滿足高併發與跨進程的資源互斥需求。

因此，自 V3.2.0 版本起，系統徹底廢止了本地 `FileTimeTracker` 樂觀鎖機制，決定改採基於資料庫層級的「分散式悲觀鎖（Pessimistic Distributed Lock）」，以確保多 Agent 協作操作共享資源（如檔案、任務、Manifest）時的絕對互斥。

## Decision

採用資料庫層級的分散式悲觀鎖，由統一的狀態管理器集中管理。

*(註：目前該鎖機制的實作位於舊專案的 `Modules/db_state_manager.js`，尚未遷移至 HH.AI_v2。此機制正是 Omni-Channel 架構中「Single-Agent Lock Manager」的核心底層實作，參照 **ADR-0011**。)*

所有 Agent 開發與操作共享資源時，必須遵守以下 API 規格與生命週期管理：

1. **獲取鎖 (Acquire Lock)**：
   所有 Agent 在操作共享資源前，必須呼叫 `acquireAgentLock(resourceId, agentId)` 取得資料庫層級鎖定。
   ```javascript
   const { acquireAgentLock, startLockHeartbeat, releaseAgentLock, stopHeartbeat } = require('./Modules/db_state_manager');
   const acquired = await acquireAgentLock('manifest.json', 'agent-alpha');
   if (!acquired) throw new Error('資源鎖定中，請稍後重試。');
   ```

2. **心跳續命 (Heartbeat)**：
   若執行深度研究或模型編譯等長期任務（預期超過 45 秒），必須在取得鎖後啟動 `startLockHeartbeat(resourceId, agentId)` 進行背景自動續命，防止 TTL 到期導致鎖被系統強制收回並被其他 Agent 搶佔。
   *(長期任務的生命週期管理與 Windows Job Object 的常駐約束息息相關，長期執行時務必確保進程正常存活，參照 **ADR-0009**)*

3. **釋放鎖 (Release Lock)**：
   任務結束時（無論成功或失敗），務必在 `finally` 區塊呼叫 `stopHeartbeat()` 終止心跳迴圈，並呼叫 `releaseAgentLock()` 明確釋放資源。

## Consequences

- **強制 API 遵循**：未來所有涉及共享狀態讀寫的技能或腳本，都必須嚴格實作上述三步驟（Acquire -> Heartbeat -> Release）。未實作心跳機制的長任務將面臨 TTL 到期被中斷的風險。
- **錯誤處理標準化**：為防止腳本崩潰或例外狀況導致資源死鎖，鎖的釋放（`releaseAgentLock` 與 `stopHeartbeat`）必須強制寫在 `finally` 區塊。
- **遷移依賴**：在 `Modules/db_state_manager.js` 完成遷移之前，新架構中的 Agent 衝突治理需依賴暫時的 mock 實作或直接呼叫舊環境。後續遷移時需原樣保留這套 API 介面規格以維持向下相容。
