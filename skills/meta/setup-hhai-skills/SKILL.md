---
name: setup-hhai-skills
description: "一次性的專案初始化與交接設定指南。當接手現有專案、需要了解專案技術棧與目錄結構、或準備開始開發臺股網站功能時手動觸發閱讀。"
disable-model-invocation: true
---

# 專案初始化與交接指南 (Setup & Handover)

本技能提供**專案交接狀態追蹤**與**臺股網站開發標準作業程序 (SOP)**。
Agent 在新環境啟動或準備開發功能前，應優先閱讀本指南以確保對齊專案現況。

---

## 1. 專案概況與狀態追蹤 (Status & Handover)

每次開始新功能或接手新 Session，請先確認或更新任務清單 `task.md`：

```markdown
<!-- task.md 範例 -->
## 目前功能：臺股 K 線圖頁面

- [x] 1. 建立 HTML 頁面骨架 - 完成 2024-01-15
- [x] 2. 實作 CSS 基礎樣式與深色主題 - 完成 2024-01-15
- [/] 3. 實作 K 線圖元件 ← 進行中
- [ ] 4. 串接 TWSE API
- [ ] 5. 截圖驗證所有圖表渲染正確
- [ ] 6. 主控臺錯誤清零確認
```

### 驗證通過標準 (Definition of Done)
每個任務必須滿足：
✅ 功能行為符合需求
✅ 截圖顯示正確（無空白、無亂碼）
✅ 主控臺零錯誤
✅ 響應式頁面在 1280px 與 1920px 均正常
✅ task.md 中對應任務標記 `[x]`

---

## 2. 開發 SOP 核心四階段 (Development Loop)

```
PHASE 1: 計畫  →  PHASE 2: 實作  →  PHASE 3: 驗證  →  PHASE 4: 迭代
   (Plan)              (Build)           (Verify)          (Iterate)
```

- **PHASE 1 (Plan)**: 拆解任務至 `task.md`，定義成功標準。若任務超過 5 步驟，可呼叫 `subagent-collaboration` 派發子代理人。
- **PHASE 2 (Build)**: 實作程式碼。建議順序：HTML 骨架 → 假資料測試 → 串接真實 API → 互動功能。
- **PHASE 3 (Verify)**: 使用 Playwright 截圖驗證。
- **PHASE 4 (Iterate)**: 若遇錯誤阻塞，呼叫 `systematic-debugging` 進行排查。

---

## 3. 自主實驗迴圈 (autoresearch 模式)

當需要 AI 自主改進圖表或 UI 品質時，可啟動自主實驗迴圈：
1. 建立 `experiment_program.md` 定義實驗目標與指令。
2. 建立 `experiments.tsv` (含 `commit`, `vqs_score`, `status`, `description` 欄位)。
3. 在每次實驗後，執行 `verify_task.py` 檢查是否有主控臺錯誤、圖表是否渲染，並針對截圖評分。
4. **VQS (Visual Quality Score) 評分標準**：無錯誤(+40)、圖表正確(+30)、響應式正常(+30)。
5. 若分數改善則保留變更，若退步則 `git reset HEAD~1 --hard` 退回上一步。

> [!CAUTION]
> **執行 `git reset --hard` 前，必須先向使用者說明目前分數與變更內容，取得明確同意後才能執行，不可自動判斷分數後直接硬重置。**

---

## 🛠️ 技術細節與 API 參考

關於臺股網站標準目錄結構、TWSE 公開 API 參考代碼，以及完整的 `verify_task.py` 驗證腳本，請參考：
👉 **[REFERENCE.md](./REFERENCE.md)**
