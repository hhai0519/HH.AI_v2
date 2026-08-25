---
title: "自動化研究 CPU 版實驗框架"
version: "3.1.3"
tags: ["SOP", "AutoResearch", "CPU", "機器學習", "超參數優化"]
dependencies: ["SOP_01_Automation_Process.md"]
---

# 自動化研究 CPU 版實驗框架 (AutoResearch CPU)

本文件規範 CPU 環境下的自動化機器學習超參數實驗流程，適用於 TinyStories 驗證集上的語言模型調優任務。本框架改編自 Karpathy/autoresearch 的 `program.md` 原始設計，並依 V3.1.3 SOP 規範進行合規化重構。

**目標**：在 TinyStories 驗證集上最小化 `val_bpb`（每位元組位元數，越低越好）。
**硬性限制**：每次實驗的時間預算為 60 秒。

---

## 一、環境建置 (Setup)

### 1.1 安裝依賴套件
```bash
py -m pip install torch datasets tokenizers numpy
```

### 1.2 準備資料集（僅需執行一次）
```bash
python prepare_cpu.py
```

### 1.3 建立實驗分支
```bash
git checkout -b autoresearch/YYYYMMDD
```

### 1.4 驗證前置條件
1. 確認 `results.tsv` 僅有標頭列（無歷史資料）。
2. 執行乾跑確認腳本可正常啟動：
   ```bash
   python train_cpu.py  # 若無真實資料，將以隨機資料執行乾跑
   ```

---

## 二、實驗執行規範 (Experimentation)

每次實驗以 `TIME_BUDGET=60` 秒為上限執行：
```bash
python train_cpu.py > run.log 2>&1
```

### 2.1 允許調整的超參數（`train_cpu.py` 中可修改）
| 超參數 | 建議範圍 | 說明 |
|--------|---------|------|
| `DEPTH`（`n_layer`）| 2、3、4 | 模型層數 |
| `ASPECT_RATIO` | 依需調整 | 改變模型寬度 |
| `LR`（學習率） | 依需調整 | 控制梯度更新步幅 |
| `BETAS` | 依需調整 | Adam 優化器動量參數 |
| `WEIGHT_DECAY` | 依需調整 | 權重衰減正則化強度 |
| `MAX_SEQ_LEN` | 建議維持低值 | CPU 環境下序列長度（過大會超時） |
| 激活函數 | MLP 內可替換 | 如 ReLU、GELU、SiLU |
| 優化器類型 | AdamW 或帶動量的 SGD | 影響收斂速度 |
| 正規化層 | RMSNorm 或 LayerNorm | 影響訓練穩定性 |

### 2.2 禁止修改的項目（固定設定，任何情況下不得更動）
- `prepare_cpu.py`（資料載入與評估邏輯）
- `evaluate()` 函式結構（評估方式須保持一致以確保可比較性）
- 時間預算（固定 60 秒）

---

## 三、輸出格式 (Output Format)

每次實驗結束後，`run.log` 應包含以下標準化輸出：

```
---
val_bpb:          2.345678
val_loss:         1.625432
training_seconds: 60.1
total_seconds:    62.3
num_steps:        45
num_params_M:     0.07
```

---

## 四、實驗日誌規範 (Logging)

結果須記錄至 `results.tsv`（Tab 分隔格式）：

```
commit  | val_bpb | status   | description
--------|---------|----------|---------------------------
abc123  | 2.3456  | keep     | DEPTH=3, LR=3e-4
def456  | 2.5678  | discard  | DEPTH=4 超時，步數不足
```

**Status 欄位說明**：
| 值 | 說明 |
|----|------|
| `keep` | 效果有改善，保留此提交 |
| `discard` | 效果未改善或持平，還原至前一版本 |
| `crash` | 訓練過程崩潰，記錄錯誤原因 |

---

## 五、自動化迴圈協議 (LOOP FOREVER Protocol)

> [!IMPORTANT]
> **啟動後不得主動中斷詢問使用者是否繼續。**
> 本框架設計為完全自主執行，每次睡眠會話預計完成 **12 次以上**實驗（每次約 60 秒加少量額外時間）。

### 5.1 決策邏輯
- 若 `val_bpb` **改善**：在 Git 分支上推進提交（`git commit`）。
- 若 `val_bpb` **持平或變差**：回退至前一個良好狀態（`git reset --hard HEAD~1`）。

### 5.2 指標提取指令
```bash
grep "^val_bpb:" run.log
```

---

## 六、合規備註

本文件原為 `autoresearch-cpu\program_cpu.md`，依 V3.1.3 SOP §任務二要求，已：
1. 重新命名並遷移至 `SOP/SOP_09_AutoResearch_CPU.md`。
2. 全文翻譯為台灣正體中文。
3. 補齊標準 YAML 標頭（含 `title`、`version`、`tags`、`dependencies`）。
4. 內文重整為標準 Markdown 格式。

---

*本文件改編自 karpathy/autoresearch program.md ｜ V3.1.3 合規化重構於 2026-05-04*
