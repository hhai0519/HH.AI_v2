---
name: pdf
description: 當使用者想要對 PDF 檔案執行任何操作時使用此技能。包含讀取/提取文字、合併 PDF、拆分、旋轉頁面、添加浮水印、建立新 PDF、填寫表單、加密、提取圖像以及對掃描 PDF 進行 OCR。
---

# PDF 全能處理器 (PDF Toolkit)

本技能是 PDF 文件操作的**一站式工具箱**，涵蓋文字提取、合併拆分、浮水印、加密、表單填寫、圖片提取與掃描 OCR，使用 PyMuPDF（fitz）和 pypdf 提供專業級 PDF 處理能力。

## 🎯 觸發條件

- 「把這些 PDF 合併成一個」「從 PDF 裡抓文字」
- 「幫 PDF 加浮水印 / 加密碼」
- 「把 PDF 的特定頁面抽出來」
- 「掃描的 PDF 要 OCR 識別」
- 「填 PDF 表單」

## 🛠️ 依賴安裝

```bash
pip install pymupdf pypdf pillow pytesseract
# OCR 支援（需另安裝 Tesseract）
# Windows: https://github.com/UB-Mannheim/tesseract/wiki
# Mac: brew install tesseract
# Linux: apt install tesseract-ocr
```

## ⚡ 快速使用範例

```python
# 合併所有 PDF
merge_pdfs(["report1.pdf", "report2.pdf", "appendix.pdf"], "final_report.pdf")

# 提取第 1-5 頁
split_pdf("big_doc.pdf", [(1, 5)], output_dir="./output")

# 掃描 PDF 轉文字
ocr_pdf("scanned_invoice.pdf", "invoice_text.txt", lang="chi_tra+eng")

# 加浮水印 + 加密打包
add_watermark("report.pdf", "機密文件 CONFIDENTIAL", "report_wm.pdf")
encrypt_pdf("report_wm.pdf", user_password="<SECRET_PASSWORD>")
```

## 🤝 協同技能

- `xlsx`：PDF 表格提取後轉換為 Excel
- `image-enhancer`：掃描 PDF 的圖片品質優化
- `csv-data-summarizer`：PDF 資料提取後的統計分析

> [!NOTE]
> 詳細程式碼範例（文字提取、合併拆分、浮水印、加密、OCR）請見 [REFERENCE.md](./REFERENCE.md)
