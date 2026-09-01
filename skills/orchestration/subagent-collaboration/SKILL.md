---
name: subagent-collaboration
description: "執行多步驟任務、執行計畫或複雜的單次操作時使用。同時具備「配方混合器 (Recipe Mixer)」職責，負責將使用者意圖封裝為動態參數，並精準調度對應的 persona 角色設定。"
---
<!-- v1.1.0 - Integrated Recipe Mixer capabilities for Dynamic Payload Assembly -->
<!-- v1.0.0 - Adapted from obra/superpowers subagent-driven-development for 本協作系統 -->

# 子代理人協作與配方混合器技能 (Subagent Collaboration & Recipe Mixer Skill)

### 【摘要】觸發條件與 DLP 聲明
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議

## 概覽 (Overview)

本技能具備雙重職責：
1. **任務隔離與派發 (Subagent Collaboration)**：主代理人將原子性任務委派給子代理人執行，避免上下文汙染。
2. **配方解析與混合器 (Recipe Mixer)**：負責將使用者的模糊意圖，解析並封裝成標準的 `Dynamic Payload`，再透過 `[SYSTEM-CALL]` 注入到負責執行的 Cognitive Persona 體內。

**Core principle:** 主代理人設計任務/解析意圖 → 子代理人執行/角色思考 → 主代理人審查 = 高品質、可重現的輸出

---

## The Recipe Mixer (配方混合器) 職責

當任務需要調用 persona 角色（如 Musk, Jobs, Taleb）時，本技能必須負責「意圖翻譯」與「參數裝配」（註：persona 設定檔位於舊專案 Data/personas/，屬 Configuration Data 而非技能，尚未遷移至 HH.AI_v2）：

1. **需求解析**：剖析使用者的模糊指令，提煉出核心的軟體工程或商業邏輯。
2. **參數裝配 (Dynamic Payload Builder)**：依 `templates/SKILL.md.template` 定義的通訊協定，組裝以下參數：
   - `objective`：核心意圖
   - `target_audience`：受眾畫像
   - `strategic_constraints`：策略限制或禁語
   - `tone_variables`：語氣微調
3. **精準調用 (System Call)**：
   ```
   [SYSTEM-CALL: persona-name | PAYLOAD: { objective: "...", target_audience: "...", strategic_constraints: "...", tone_variables: "..." }]
   ```

---

## 分層 Payload 淨化機制 (Payload Tiering Protocol)

> [!IMPORTANT]
> 本技能作為 Payload 淨化的**責任方**，在組裝 Dynamic Payload 前必須識別目標層級並執行型別淨化。

| 目標層級 | 允許注入 | 嚴禁注入 |
|---|---|---|
| `analysis/`（分析與 Persona 層） | 戰略目標、語氣設定、情緒變數、自然語言約束 | SQL、DOM 路徑、raw URL、技術指令 |
| `execution/` 與 `platform/`（工具與整合層） | URL、DOM Selector、SQL Query、JSON Schema、檔案路徑 | 認知參數、語氣描述、角色設定、情緒變數 |

**執行流程**：

1. **判斷目標層級**：由目標技能的路徑直接判定。技能一律位於
   `skills/<bucket>/<skill-name>/`，`<bucket>` 即為層級。
   不需要查詢任何映射表，也不需要讀取 frontmatter 欄位。
2. **依上方型別矩陣過濾 Payload 內容**：
   - 目標在 `analysis/` 或 `orchestration/` → 移除所有技術型參數
   - 目標在 `execution/`、`platform/` 或 `agents/` → 移除所有認知型參數
3. 組裝淨化後的 Payload，執行 `[SYSTEM-CALL]`。
4. **若目標技能不存在、或所屬 bucket 無法判定：停下來詢問 Orchestrator，
   禁止猜測。** 也禁止為了避免流程中斷而跳過淨化程序——淨化是安全邊界，
   不是可選步驟。

## 任務派發與執行流程 (The Process)

```
1. 主代理人：閱讀計畫，拆解為獨立任務清單或認知呼叫
2. 對每個任務：
   a. 若為實體任務：撰寫完整的子代理人指令（含背景、前置條件、成功標準）並派發。
   b. 若為認知任務：啟動 Recipe Mixer 封裝 Dynamic Payload，透過 SYSTEM-CALL 調用 Persona。
   c. 等待回報狀態與資料
   d. 審查輸出（規格合規 → 品質審查）
   e. 標記完成或退回修正
3. 所有任務完成後：最終整合審查
```

---

## Controller (主代理人) 職責

### 任務拆解規則
- 每個任務需**可獨立執行、可獨立驗證**
- 任務之間依賴需明確標注（Task 2 depends on Task 1 output）
- 每個實體任務的指令必須包含背景說明、前置條件、成功標準與回報格式。

---

## Two-Stage Review (雙重審查)

每個任務完成後，主代理人自行執行兩階段審查：

### 階段一：規格合規審查
- ✅ 所有要求的專案都實作/回答了嗎？
- ✅ 是否符合 Dynamic Payload 中的策略限制？
- ❌ → 退回給子代理人或 Persona 修正。

### 階段二：品質審查
- 程式碼是否清晰可維護？輸出是否高質量且契合人物設定？
- ❌ → 退回修正。

---


詳細參數與完整指引請參見 `REFERENCE.md`。
