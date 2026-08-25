---
title: "微型模型超參數訓練與日誌監控 SOP"
version: "1.0.0"
tags: ["SOP", "AutoResearch", "超參數優化", "模型進化", "監控"]
dependencies: ["SOP_09_AutoResearch_CPU.md"]
---

# 微型模型超參數訓練與日誌監控 SOP (SOP_13)

本文件規範微型語言模型超參數訓練（`auto_optimize_controller.py`）之例行維護、監控與指標回報程序，以確保模型自我優化任務在隔離環境下自主且穩定地運行。

---

## 一、實驗控制與執行架構 (Execution Architecture)

### 1.1 核心腳本說明
1. **訓練核心 (`train_cpu.py`)**：在 CPU 環境下執行 TinyStories 資料集之單次 60 秒語言模型訓練，計算評估指標 `val_bpb`。
2. **優化控制器 (`auto_optimize_controller.py`)**：讀取搜尋空間，批次調用並傳入超參數（`DEPTH`, `LR`），並將每輪實驗結果更新至狀態看板。

### 1.2 狀態監控檔案
* **結果日誌表 (`results.tsv`)**：以 Tab 分隔記錄歷次實驗參數與其指標（`keep` 代表效能提升，`discard` 代表未提升）。
* **狀態看板 (`docs/reports/optimization-status.md`)**：記錄當前實驗進度、選用參數以及目前歷史最佳之 `val_bpb` 指標。

---

## 二、例行監控與巡檢步驟 (Routine Monitoring)

### 2.1 指標提取與驗證
例行維護時，必須檢查最近一輪實驗的輸出日誌，驗證是否有更新的 `val_bpb` 被記錄：
# 從 results.tsv 取最新 5 筆結果（該技能尚未遷移至 HH.AI_v2，路徑為預計位置）：
```bash
tail -n 5 skills/agents/autoresearch-agent/results.tsv
```

### 2.2 熔斷與安全閥 (熔斷機制)
* 依據 `SOP_01` 的配額防護原則，若在背景任務中因 CPU 長時間滿載造成系統響應緩慢，應手動暫停任務。
* 任務超時防護：單次訓練由 `train_cpu.py` 內建的 `TIME_BUDGET=60` 進行強制超時熔斷，避免因梯度爆炸或死鎖而無限運行。

---

## 三、異常處理 (Troubleshooting)

| 異常現象 | 可能原因 | 排除步驟 |
| :--- | :--- | :--- |
| `val_bpb` 回傳 `999.0` | 找不到訓練資料或評估崩潰 | 檢查是否已執行 `py prepare_cpu.py` 準備資料。 |
| 實驗卡住無輸出 | 行程被鎖定或資源耗盡 | 結束 Python 背景行程，清空 CPU 快取後重新執行控制器。 |
| results.tsv 遺失 | 誤刪或路徑變更 | 由 Git 版本控制中還原該檔案，確保歷史記錄不遺失。 |

---
*本文件建立於 2026-06-21 ｜ Version 1.0.0*
