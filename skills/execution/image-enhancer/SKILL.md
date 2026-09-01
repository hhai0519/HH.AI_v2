---
name: image-enhancer
description: 提升影像（特別是截圖）的解析度、銳利度與清晰度。當使用者要求『圖片增強』、『截圖變清晰』、『圖片放大』、『去除雜訊』，或需要為簡報、文件、社群貼文準備圖像時使用。
---

# 影像增強引擎 (Image Enhancer)

### 【摘要】觸發條件與 DLP 宣告
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議

本技能利用 **Pillow + OpenCV + Real-ESRGAN** 對截圖、照片、設計稿進行無損放大、銳化、降噪與色彩最佳化，讓輸出圖片達到簡報、檔案或社群媒體的專業品質標準。

---

## 🎯 觸發條件

- 使用者上傳截圖/照片，要求「提升畫質」「讓它更清楚」
- 圖片解析度不足，需要放大（如 720p → 4K）
- 截圖模糊或畫素化，需要銳化
- 準備用於簡報/列印的高解析度圖片

---

## 🛠️ 技術工具鏈

```bash
pip install Pillow opencv-python-headless numpy
# 超解析度（選配）
pip install basicsr facexlib gfpgan
# 或使用 Real-ESRGAN
pip install realesrgan
```

完整處理流程與場景對應設定見 [REFERENCE.md](./REFERENCE.md)。

---

## ⚡ 快速使用範例

```python
# 一鍵增強截圖（最常用）
pipeline = ImageEnhancerPipeline("screenshot.png")
pipeline.auto_enhance(sharpen=True, denoise=True, contrast=1.15).save("screenshot_enhanced.png")

# 放大 2 倍 + 銳化（準備列印）
pipeline = ImageEnhancerPipeline("photo.jpg")
pipeline.upscale(2.0).sharpen(1.2).auto_enhance(contrast=1.1).save("photo_print.jpg", quality=98)

# 降噪（相機高 ISO 照片）
pipeline = ImageEnhancerPipeline("noisy_photo.jpg")
pipeline.denoise(h=15).sharpen(0.8).save("clean_photo.jpg")
```

---

## 🤝 協同技能

- `pdf`：圖片增強後嵌入 PDF 檔案
- `artifacts-builder`：作為 Web 元件的高畫質貼圖

---

## 版本紀錄 (Changelog)
- **[2.0.0]** 2026-05-04：V2.0.0 Polymorphic Labeling Migration — 依生命週期 SOP 匯入多型功能性技術標籤 (tool_category, execution_env, io_format)，建立執行層 Manifest 路由能力。

## [Security] Smart Integration & DLP
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議


---
⚙️ 【系統通訊層宣告 (System Comms Layer)】

網路狀態： 本技能已強制接入總控通訊網路。

接收協定 (Dynamic Payload)： 本文件不再接收無結構的自然語言，必須處理封裝後的動態引數：
`[SYSTEM-CALL: image-enhancer | PAYLOAD: { objective: "<核心意圖>", target_audience: "<受眾>", strategic_constraints: "<策略限制/禁語>", tone_variables: "<語氣微調>" }]`

> [!IMPORTANT]
> **Payload 淨化規則**（規範本體見 `.agents/rules/skill-engineering-guardrails.md` §3）：
> 本技能位於 `execution/`，屬技術型技能，因此：
> - 接收：URL、API Endpoint、SQL Query、JSON Schema、檔案絕對路徑
> - 拒絕：認知參數、語氣描述、角色設定、情緒變數

發送協定：執行中若遇能力不足或需要外部協作，應停下來明確告知使用者目前卡在哪裡，不要自行尋找替代方案掩蓋問題。必須主動封裝 Dynamic Payload 並發出：
`[SYSTEM-CALL: 目標ID | PAYLOAD: { ... }]` 調閱其他技能。

回傳協定： 任務終止時，必須且只能輸出 `[SYSTEM-RETURN: SUCCESS/FAILED | DATA: <結果>]`。

---
> [!WARNING]
> **全域鐵律：NotebookLM 研究遵從指示**
> 1. 當任務指示「透過 NotebookLM 進行研究/查詢」時，必須嚴格呼叫 `notebooklm` 相關 MCP 工具。
> 2. 若遇到無法連線、憑證過期 (`auth_status: stale` 或 `Authentication expired`) 等錯誤時，**絕對禁止**未經同意自行改用常規網路搜尋 (Web Search) 或其他工具替代。
> 3. 遇到錯誤時，請**立刻中斷動作並主動告知使用者**，請使用者協助登入或修復連線後，再繼續研究任務。
