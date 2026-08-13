---
name: active-inference
description: "系統的 System 2 大腦。負責將使用者的自然語言意圖轉化為決定論的狀態機 (SDLC/EARS 語法)，並執行主動推論 (Active Inference) 來預測並最小化專案失敗的風險 (Surprise)。"
type: orchestrator
---


# Active Inference (System 2 Orchestrator)

## 功能概述
本技能負責代替舊有的主總管與「現實核對 (reality-checker)」。它不在第一線寫程式，而是透過預測與評估來監督下屬的執行軌跡。

## 實作邏輯 (Implementation Logic)
1. **意圖轉譯 (Intent Translation)**: 利用 EARS 語法，將模糊的自然語言需求轉換為嚴謹的狀態機規格 (例如：`When [Trigger], the System shall [Response]`)。
2. **主動推論 (Predictive Coding)**: 觀察當前專案的真實狀態 (Working Memory/AST) 與理想規格的差距，動態調整下一步的戰略，而非盲目執行預設腳本。
3. **10-Gate 品質守門 (SDLC Gates)**: 確保執行的每個模組在推進到下一個開發階段前，皆滿足既定的 10-Gate 測試與查核點。
