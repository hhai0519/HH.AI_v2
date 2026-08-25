# HH.AI SOP 文件總覽

## 系統治理文件職責分工
- **`SOP/` (本目錄)**：「該怎麼操作」的流程指南，提供具體的步驟、指令與作業標準。
- **`docs/adr/`**：「當初為什麼這樣決定」的架構決策紀錄（Architecture Decision Records），記錄系統演進的決策留痕。
- **`.agents/rules/`**：「agent 執行任務時的行為約束」，此處的規則會被系統原生機制自動載入並嚴格執行。

## 核心 SOP 索引清單
1. [SOP_01_Automation_Process.md](./SOP_01_Automation_Process.md)：規範系統自動化進程的觸發、防呆機制與越權攔截標準。
2. [SOP_02_Security_Guidelines.md](./SOP_02_Security_Guidelines.md)：規範系統中所有 Agent 技能在執行時的安全邊界與機密防護措施。
3. [SOP_04_Data_Cleanup.md](./SOP_04_Data_Cleanup.md)：規範系統快取、無效日誌與孤兒程序的定期深度清理機制。
4. [SOP_05_System_Policies.md](./SOP_05_System_Policies.md)：規範系統最頂層的核心治理規則與絕對禁止事項。
5. [SOP_06_Handover_Manual.md](./SOP_06_Handover_Manual.md)：提供代理人系統的每日交接程序、基建維護指令與故障排除指南。
6. [SOP_09_AutoResearch_CPU.md](./SOP_09_AutoResearch_CPU.md)：規範 CPU 模式下自動化模型研究與參數評估流程。
7. [SOP_11_Task_Reflection_Protocol.md](./SOP_11_Task_Reflection_Protocol.md)：確立所有 AI 代理人在高風險決策或複雜任務後的反思與自我修正迴圈。
8. [SOP_12_MCP_Auth_Recovery.md](./SOP_12_MCP_Auth_Recovery.md)：規範 MCP 工具認證掉線時的緊急憑證修復程序。
9. [SOP_13_Hyperparameter_Training.md](./SOP_13_Hyperparameter_Training.md)：規範超參數訓練、動態調整及模型評估狀態的追蹤機制。
10. [SOP_14_Rigorous_Verification_and_Audit_Protocol.md](./SOP_14_Rigorous_Verification_and_Audit_Protocol.md)：規範重大變更或跨多份文件修改時的強制聯席審計標準。

## 已淘汰與已轉換的 SOP 去向紀錄
為避免未來查找文件時以為資料遺失，以下列出 11 份舊版 SOP 文件的去向（3 份轉為 ADR/rules、8 份淘汰）：

### 轉為 ADR 或 Rules (3 份)
- **`SOP_00_Skill_Lifecycle_Management.md`**：已拆分為 `ADR-0013` 與兩份 `.agents/rules/` 規則。
- **`SOP_10_AI_Command_Center.md`**：已轉為 `ADR-0012`。
- **`SOP_15_OmniChannel_Connection_Development_History.md`**：已轉為 `ADR-0011`。

### 已淘汰 (8 份)
- **`SOP_00_RUNBOOK.md`**：內容已被 `ADR-0009` 與 `ADR-0012` 完整涵蓋。
- **`SOP_00_System_Prompt_Bootstrap.md`**：被 `AGENTS.md` 與 `.agents/rules/` 的原生載入機制取代。
- **`SOP_00_System_Architecture_Map.md`**：查證後確認三段內容皆無留痕價值（舊三層技能清單已被七桶 README 取代、雙生通訊架構已被 ADR-0011 涵蓋、系統支柱資料層引用的兩個 Manifest 檔案已確認是無人讀取的死檔案）。
- **`SOP_00B_Agent_File_Governance.md`**：已被 `AGENTS.md` 涵蓋。
- **`SOP_00C_New_Skill_Onboarding.md`**：已被 `AGENTS.md` 涵蓋。
- **`SOP_03_Skills_Maintenance.md`**：已被 `validate_skills.py` 與 `AGENTS.md` 取代。
- **`SOP_07_Program_CPU.md`**：已被 `SOP_09` 完全取代，原檔另有編碼損毀。
- **`SOP_08_Project_Readme.md`**：描述的目錄結構與檔案已不存在，嚴重過時。
