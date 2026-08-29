## 📋 核心處理流程

### 全自動增強管線

```python
from PIL import Image, ImageEnhance, ImageFilter
import cv2
import numpy as np

class ImageEnhancerPipeline:
    """全自動影像增強管線"""
    
    def __init__(self, input_path: str):
        self.original = Image.open(input_path)
        self.img = self.original.copy()
        self.cv_img = cv2.imread(input_path)
    
    def auto_enhance(self, 
                     sharpen: bool = True,
                     denoise: bool = True,
                     contrast: float = 1.2,
                     brightness: float = 1.05,
                     saturation: float = 1.1) -> 'ImageEnhancerPipeline':
        """一鍵自動增強（適合截圖和照片）"""
        
        # 1. 降噪（先降噪再銳化，順序很重要）
        if denoise:
            self.denoise()
        
        # 2. 色彩增強
        if brightness != 1.0:
            self.img = ImageEnhance.Brightness(self.img).enhance(brightness)
        if contrast != 1.0:
            self.img = ImageEnhance.Contrast(self.img).enhance(contrast)
        if saturation != 1.0:
            self.img = ImageEnhance.Color(self.img).enhance(saturation)
        
        # 3. 銳化（最後執行）
        if sharpen:
            self.sharpen()
        
        return self
    
    def sharpen(self, amount: float = 1.5) -> 'ImageEnhancerPipeline':
        """Unsharp Mask 銳化（比簡單銳化更自然）"""
        # 轉 OpenCV 格式
        cv_img = np.array(self.img)
        cv_img = cv2.cvtColor(cv_img, cv2.COLOR_RGB2BGR)
        
        # Unsharp Mask
        blurred = cv2.GaussianBlur(cv_img, (0, 0), 3)
        sharpened = cv2.addWeighted(cv_img, 1 + amount, blurred, -amount, 0)
        
        # 轉回 PIL
        self.img = Image.fromarray(cv2.cvtColor(sharpened, cv2.COLOR_BGR2RGB))
        return self
    
    def denoise(self, h: int = 10) -> 'ImageEnhancerPipeline':
        """Non-local Means 降噪（截圖最佳）"""
        cv_img = np.array(self.img)
        cv_img = cv2.cvtColor(cv_img, cv2.COLOR_RGB2BGR)
        
        denoised = cv2.fastNlMeansDenoisingColored(cv_img, None, h, h, 7, 21)
        self.img = Image.fromarray(cv2.cvtColor(denoised, cv2.COLOR_BGR2RGB))
        return self
    
    def upscale(self, scale: float = 2.0, method: str = 'lanczos') -> 'ImageEnhancerPipeline':
        """放大圖片（不失真）
        
        method 選項：
          - 'lanczos': 最高品質，適合照片和圖示（預設）
          - 'bicubic': 速度較快，適合截圖
          - 'nearest': 畫素藝術風格（保留鋸齒感）
        """
        w, h = self.img.size
        new_size = (int(w * scale), int(h * scale))
        
        resample_map = {
            'lanczos': Image.LANCZOS,
            'bicubic': Image.BICUBIC,
            'nearest': Image.NEAREST
        }
        
        self.img = self.img.resize(new_size, resample_map.get(method, Image.LANCZOS))
        return self
    
    def save(self, output_path: str, quality: int = 95, optimize: bool = True) -> str:
        """儲存增強後的圖片"""
        ext = output_path.split('.')[-1].lower()
        
        if ext == 'jpg' or ext == 'jpeg':
            self.img.save(output_path, 'JPEG', quality=quality, optimize=optimize)
        elif ext == 'png':
            self.img.save(output_path, 'PNG', optimize=optimize)
        elif ext == 'webp':
            self.img.save(output_path, 'WEBP', quality=quality)
        else:
            self.img.save(output_path)
        
        original_size = self.original.size
        new_size = self.img.size
        print(f"✅ 已儲存：{output_path}")
        print(f"   原始尺寸：{original_size[0]}x{original_size[1]}")
        print(f"   增強後：{new_size[0]}x{new_size[1]}")
        return output_path
```

---

## 🎛️ 場景對應設定

| 場景 | 建議設定 |
|---|---|
| **UI 截圖（簡報用）** | `upscale(2.0)`, `sharpen(1.5)`, `contrast(1.1)` |
| **照片（社群媒體）** | `denoise(10)`, `sharpen(1.0)`, `saturation(1.15)` |
| **掃描檔案（OCR 前處理）** | `upscale(1.5)`, `contrast(1.5)`, 轉灰階, `sharpen(2.0)` |
| **產品截圖（檔案用）** | `upscale(1.5)`, `sharpen(1.2)`, `brightness(1.05)` |

---

