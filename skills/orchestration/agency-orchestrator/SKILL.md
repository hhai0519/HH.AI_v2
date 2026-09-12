---
name: agency-orchestrator
description: "複雜多技能任務調度器。負責通用意圖解析、任務分解與多技能依賴協調。當遇到跨領域複雜任務 (complex task)、需要多個技能或子代理人協同執行時使用。"
---

# 複雜多技能任務調度器 (Agency Orchestrator)

本技能提供**跨領域複雜任務的意圖解析、工作分解與多技能協調能力**。
當單一技能無法獨立完成任務，需調度分析、執行與平台層等多個技能協同作業時，可呼叫本技能進行任務編排。

> [!NOTE]
> 本技能為**可重複呼叫的任務調度能力**，不是全專案的治理當局或控制平面。專案使命見 [MISSION.md](file:///c:/Users/HH.AI_260806/Desktop/HH.AI_v2/MISSION.md)，決策原則見 [PRINCIPLES.md](file:///c:/Users/HH.AI_260806/Desktop/HH.AI_v2/PRINCIPLES.md)，自動化指令定義唯一真理見 [SOP/SOP_00A_Master_Index.json](file:///c:/Users/HH.AI_260806/Desktop/HH.AI_v2/SOP/SOP_00A_Master_Index.json)。

---

## 🎯 依賴與協同技能 (Dependencies)

本技能在編排複雜任務時，通常協同調度以下能力：
- 任務協同與子代理人調度：呼叫 `skills/orchestration/subagent-collaboration`
- 計畫可行性審查與防範幻覺：呼叫 `skills/orchestration/reality-checker`
- 安全合規審查：呼叫 `skills/orchestration/security-auditor`

---

## 🔄 複雜任務分解啟發式架構 (Orchestration Heuristic)

在處理大型跨領域任務時，本技能採用分階段的工作分解啟發法（Heuristic），引導任務循序推進：

### 1. 需求與規劃階段 (Planning Heuristic)
- **核心目標**：釐清使用者意圖、盤點輸入資料、界定範圍與可驗證之產出目標。
- **典型參與**：`investment-researcher`、`financial-analyst`、`twse-data-analyst` 等領域分析技能。
- **產出**：明確的執行步驟與預期成果清單。

### 2. 架構與規格階段 (Architecture Heuristic)
- **核心目標**：定義資料結構、介面規格、元件架構或依賴順序。
- **典型參與**：`software-architect`、`backend-architect`、`reality-checker`。
- **產出**：清晰的實作藍圖與介面約定。

### 3. 實作與驗證階段 (Dev & Verify Heuristic)
- **核心目標**：按藍圖逐步執行實作，並隨即進行自動化測試與外觀/資料驗證。
- **典型參與**：`frontend-developer`、`d3js-visualization`、`webapp-testing` 等執行型技能。
- **產出**：已驗證可運行的程式碼或分析報告。

### 4. 整合交付階段 (Integration Heuristic)
- **核心目標**：綜整各模組輸出、核對驗證證據、更新相關文件。
- **典型參與**：`evidence-collector`、`devops-engineer`。
- **產出**：整合結果與執行總結。

---

## 🛠️ 任務反思與除錯迴圈 (Reflection Heuristic)

在調度執行過程中若遇連續工具錯誤或阻礙時，應啟動反思機制：
1. **軌跡檢視**：具體分析前幾步執行的成果與實際報錯根因。
2. **調整策略**：針對錯誤調整輸入參數或切換替代技能，避免相同錯誤重試。
3. **錯誤上報界限**：若連續重試 3 次仍無法突破瓶頸，應中斷迴圈，依主控規則（M1/M2/M3/S1）向調用者或使用者回報障礙點，不得掩蓋問題。

---

## 🛡️ 安全邊界與資料防洩

本技能嚴格遵守專案安全規範：
- 資料防洩：遵循 [SOP/SOP_02_Security_Guidelines.md](file:///c:/Users/HH.AI_260806/Desktop/HH.AI_v2/SOP/SOP_02_Security_Guidelines.md) §1。
- 參數淨化：遵循 [.agents/rules/skill-engineering-guardrails.md](file:///c:/Users/HH.AI_260806/Desktop/HH.AI_v2/.agents/rules/skill-engineering-guardrails.md) §3，跨層調度時淨化自然語言，禁止將包含敏感資訊或未過濾的 raw 內容派發至執行層。
- 狀態隔離：本技能調度任務產生的成果直接回傳給調用者，**嚴禁自行寫入全域狀態檔、記憶體檔或擅自修改專案治理規則**。
