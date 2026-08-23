# pdf Reference

## 📋 核心操作程式庫

### 文字提取（最快最準）

```python
import fitz  # PyMuPDF

def extract_text(pdf_path: str, pages: list = None) -> dict:
    """
    提取 PDF 文字內容
    pages: 頁碼列表（1-based），None = 全部
    """
    doc = fitz.open(pdf_path)
    results = {}

    page_range = range(len(doc)) if pages is None else [p-1 for p in pages]

    for i in page_range:
        page = doc[i]
        text = page.get_text("text")  # 純文字
        # 或 "markdown" - 保留部分格式
        # 或 "dict" - 完整結構（含字型、座標）
        results[i + 1] = text.strip()

    doc.close()

    total_chars = sum(len(t) for t in results.values())
    print(f"✅ 提取完成：{len(results)} 頁，共 {total_chars} 字元")
    return results

def extract_tables(pdf_path: str) -> list:
    """提取 PDF 中的表格（PyMuPDF v1.23+）"""
    doc = fitz.open(pdf_path)
    all_tables = []

    for page_num, page in enumerate(doc):
        tables = page.find_tables()
        for table in tables:
            df = table.to_pandas()
            all_tables.append({"page": page_num + 1, "data": df})

    return all_tables
```

### 合併 PDF

```python
from pypdf import PdfWriter, PdfReader

def merge_pdfs(input_paths: list, output_path: str) -> str:
    """合併多個 PDF 並保留書籤"""
    writer = PdfWriter()

    for path in input_paths:
        reader = PdfReader(path)
        for page in reader.pages:
            writer.add_page(page)
        print(f"✅ 已加入：{path}（{len(reader.pages)} 頁）")

    with open(output_path, 'wb') as f:
        writer.write(f)

    print(f"✅ 合併完成：{output_path}（共 {len(writer.pages)} 頁）")
    return output_path

def split_pdf(input_path: str, page_ranges: list, output_dir: str = '.') -> list:
    """
    拆分 PDF
    page_ranges: [(1, 5), (6, 10)] → 按範圍拆分
    或 None → 每頁一個文件
    """
    import os
    reader = PdfReader(input_path)
    outputs = []

    if page_ranges is None:
        page_ranges = [(i+1, i+1) for i in range(len(reader.pages))]

    for i, (start, end) in enumerate(page_ranges):
        writer = PdfWriter()
        for page_num in range(start-1, min(end, len(reader.pages))):
            writer.add_page(reader.pages[page_num])

        output_path = os.path.join(output_dir, f"part_{i+1:03d}_p{start}-p{end}.pdf")
        with open(output_path, 'wb') as f:
            writer.write(f)
        outputs.append(output_path)
        print(f"✅ 已輸出：{output_path}")

    return outputs
```

### 浮水印

```python
def add_watermark(input_path: str, watermark_text: str, output_path: str,
                  opacity: float = 0.3, angle: int = 45, font_size: int = 60):
    """在每頁添加對角線浮水印"""
    import fitz
    from PIL import Image, ImageDraw, ImageFont
    import io

    doc = fitz.open(input_path)

    for page in doc:
        rect = page.rect
        page.insert_text(
            (rect.width * 0.15, rect.height * 0.55),
            watermark_text,
            fontsize=font_size,
            rotate=angle,
            color=(0.7, 0.7, 0.7),
            fill_opacity=opacity
        )

    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
    return output_path

def encrypt_pdf(input_path: str, user_password: str, owner_password: str = None,
                allow_printing: bool = True, output_path: str = None) -> str:
    """加密 PDF"""
    from pypdf import PdfWriter, PdfReader

    reader = PdfReader(input_path)
    writer = PdfWriter()

    for page in reader.pages:
        writer.add_page(page)

    writer.encrypt(
        user_password=user_password,
        owner_password=owner_password or user_password,
        use_128bit=True
    )

    output = output_path or input_path.replace('.pdf', '_encrypted.pdf')
    with open(output, 'wb') as f:
        writer.write(f)
    return output
```

### OCR（掃描 PDF）

```python
def ocr_pdf(input_path: str, output_path: str, lang: str = 'chi_tra+eng') -> str:
    """
    對掃描版 PDF 進行 OCR
    lang: 'chi_tra' 繁中, 'chi_sim' 簡中, 'eng' 英文, 組合: 'chi_tra+eng'
    """
    import fitz
    import pytesseract
    from PIL import Image
    import io

    doc = fitz.open(input_path)
    full_text = []

    for page_num, page in enumerate(doc):
        # 轉換為高解析度圖片（300 DPI）
        mat = fitz.Matrix(300/72, 300/72)
        clip = page.get_pixmap(matrix=mat)
        img_data = clip.tobytes("png")

        # OCR 識別
        img = Image.open(io.BytesIO(img_data))
        text = pytesseract.image_to_string(img, lang=lang, config='--psm 1')
        full_text.append(f"=== Page {page_num + 1} ===\n{text}")
        print(f"✅ OCR 第 {page_num + 1} 頁完成")

    # 保存結果
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(full_text))

    return output_path
```
