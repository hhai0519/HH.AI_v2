# ADR-0013: 系統巡檢鉤子與非同步錯誤暫存機制 (Watchdog & Async Buffer)

- Status: Accepted
- Date: 2026-08-25

## Context

當 Agent 執行跨技能協作、掃描技能目錄或處理狀態同步時，若遇到異常，必須有一個穩健的機制來記錄問題而不中斷當前主要任務。系統原先使用本地的 `Pending_Optimization.json` 作為 Watchdog 錯誤暫存區，但在高併發與多 Agent 協作場景下，本地檔案的競態危害（Race Condition）與 I/O 阻塞成為了效能與穩定性的瓶頸。

因此，自 V3.2.0 版本起，系統廢除了本地 JSON 寫入機制，全面升級為雲端原生狀態管理，將 Watchdog 異常紀錄寫入 Neon DB。

*(註：目前負責此機制的 `Modules/db_state_manager.js` 仍位於舊專案，尚未遷移至 HH.AI_v2。此模組與 **ADR-0012** 中描述的分散式悲觀鎖為同一個核心模組實作。)*

## Decision

系統全面導入背景 Watchdog 巡檢機制與資料庫層級的非同步暫存協定。

### 1. 巡檢觸發時機
Agent 在以下情況**必須**自動觸發背景巡檢：
- 啟動跨技能協作（呼叫 Orchestrator 或協作型技能）之前
- 掃描技能目錄（`skills/`）或進行技能狀態讀取時

*(原 SOP 另有一條「執行 Manifest Sync / Inject 操作時」的觸發時機，因 Data/00_Skill_Manifest.json 已確認為無人讀取的死檔案，該觸發條件在 HH.AI_v2 已無對象，故移除。)*

### 2. 偵測清單 (Detection Checklist)
巡檢必須核查以下四類異常：
| # | 異常類型 | 偵測條件 |
|---|---|---|
| A | **索引孤兒 (Orphan)** | 實體技能數量 ≠ 各 bucket `README.md` 索引數量 |
| B | **YAML 標頭缺失** | `SKILL.md` 無法提取 `name` 欄位 |
| C | **BOM 污染** | 檔案起始字元含 `\uFEFF`（offset 0） |
| D | **Frontmatter 不合規** | `SKILL.md` 前置配置區塊中出現 `AGENTS.md` 允許清單以外的欄位 |

### 3. 強制禁止事項 (Safety Boundary)
偵測到任何異常時，Agent **絕對禁止**：
- ❌ 中斷或暫停當前主任務
- ❌ 自行執行未授權的大規模覆寫或刪除操作
- ❌ 向使用者發出超過**一行**的警示訊息

### 4. Buffer 寫入協定與狀態升級
嚴禁使用 `fs.writeFileSync` 操作本地 JSON 檔。遇異常需紀錄優化事項時，**必須強制呼叫** `Modules/db_state_manager.js` 的 `writePendingOptimization` 方法寫入 Neon DB，由系統底層保障併發寫入之 ACID 安全。

**新舊機制優勢對比**：
| 特性 | 舊機制（JSON 檔） | 新機制（Neon DB） |
|------|-----------------|-----------------|
| 併發安全 | ❌ 競態危害 | ✅ 行級鎖 ACID |
| 查詢能力 | ❌ 全量讀取 | ✅ SQL 條件過濾 |
| 膨脹風險 | ❌ 無限成長 | ✅ SKIP LOCKED 佇列 |
| Context 佔用 | ❌ 隨異常增多 | ✅ 零 Context 佔用 |

### 5. 錯誤物件 Schema（強制型別）
寫入資料庫時必須符合以下欄位規格：
| 欄位 | 型別 | 是否必填 | 說明 |
|---|---|---|---|
| `Timestamp` | ISO 8601 String | ✅ REQUIRED | 異常偵測時間 |
| `Detected_Issue` | String | ✅ REQUIRED | 異常描述 |
| `Affected_Files` | String[] | ✅ REQUIRED | 受影響檔案路徑清單 |
| `Suggested_Fix` | String | ✅ REQUIRED | 建議的修復動作 |
| `Status` | `"PENDING"` \| `"RESOLVED"` | ✅ REQUIRED | 修復狀態 |
| `Priority` | `"HIGH"` \| `"MEDIUM"` \| `"LOW"` | ✅ REQUIRED | 優先級 |

### 6. 技能觸發詞排他性矩陣規範
* **設計原則**：防止多個 Agent 搶奪同一個使用者自然語言意圖而造成衝突。
* **排他性規則**：
  * **最高總管 (Orchestrator)**：觸發詞僅限於高階協調、戰略規劃與狀態控制。
  * **專業代理 (Cognitive Agent)**：觸發詞僅限於專業學科（如 "台股"、"財務分析"），且**必須限定為僅能由 Orchestrator 進行內部調用**。
  * **審查流程**：新技能 onboarding 時，必須交叉檢驗觸發詞是否與既有活躍技能重疊，如有重疊則強制退回，直到修改為獨佔詞為止。

### 7. 使用者通報協定 (Alert Protocol)
Buffer 寫入完成後，Agent **僅能**在對話**結尾**以一行警示通知使用者，禁止打斷正在進行的主任務說明：
```
⚠️ Watchdog 偵測到 N 個異常，已記錄至 Neon DB 待命。
```
使用者將依此訊息決定何時執行批次修復。**Agent 不得自行啟動修復。**

## Consequences
- 全域錯誤暫存機制與鎖機制高度綁定，底層重構必須確保這兩大核心的穩定性。
- 新增或歸檔技能時，必須確保所屬 bucket 的 `README.md` 索引同步更新，否則將觸發背景 Watchdog 錯誤。
