# csv-data-summarizer Reference

## 📋 完整分析管線

### 全自動一鍵分析

```python
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from scipy import stats

def auto_analyze_csv(file_path: str, output_dir: str = './analysis_output'):
    """全自動 CSV 分析管線"""
    import os
    os.makedirs(output_dir, exist_ok=True)

    # ── 1. 載入資料 ──
    df = pd.read_csv(file_path, encoding='utf-8-sig')
    print(f"✅ 資料載入完成：{df.shape[0]} 列 × {df.shape[1]} 欄")

    # ── 2. 基本摘要 ──
    print("\n=== 📊 資料集概覽 ===")
    print(f"形狀：{df.shape}")
    print(f"\n欄位類型：\n{df.dtypes.to_string()}")
    print(f"\n描述性統計：\n{df.describe().round(3).to_string()}")

    # ── 3. 資料品質報告 ──
    print("\n=== 🔍 資料品質報告 ===")
    quality = pd.DataFrame({
        '總行數': len(df),
        '缺失值': df.isnull().sum(),
        '缺失率%': (df.isnull().sum() / len(df) * 100).round(2),
        '唯一值數': df.nunique(),
        '重複行數': [df.duplicated().sum()] + [None] * (len(df.columns) - 1)
    })
    print(quality.to_string())

    # ── 4. 離群值偵測（IQR 法） ──
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    print("\n=== ⚠️ 離群值偵測（IQR 法）===")
    for col in numeric_cols:
        Q1 = df[col].quantile(0.25)
        Q3 = df[col].quantile(0.75)
        IQR = Q3 - Q1
        outliers = df[(df[col] < Q1 - 1.5*IQR) | (df[col] > Q3 + 1.5*IQR)][col]
        if len(outliers) > 0:
            print(f"  {col}: {len(outliers)} 個離群值 (範圍: {outliers.min():.2f} ~ {outliers.max():.2f})")

    # ── 5. 視覺化 ──
    generate_visualizations(df, numeric_cols, output_dir)

    return df
```

### 視覺化套件

```python
def generate_visualizations(df: pd.DataFrame, numeric_cols, output_dir: str):
    """生成完整視覺化套件"""

    # (A) 各數值欄位：直方圖 + KDE + 箱形圖
    n_cols = len(numeric_cols)
    if n_cols > 0:
        fig, axes = plt.subplots(n_cols, 2, figsize=(14, 4 * n_cols))
        if n_cols == 1:
            axes = [axes]

        for i, col in enumerate(numeric_cols):
            # 分布圖（直方圖 + KDE）
            df[col].hist(ax=axes[i][0], bins=30, edgecolor='white', color='#3b82f6', alpha=0.8)
            axes[i][0].set_title(f'{col} 分布', fontsize=12)
            axes[i][0].set_xlabel(col)
            axes[i][0].set_ylabel('頻率')

            # 箱形圖（離群值可視化）
            df.boxplot(column=col, ax=axes[i][1], patch_artist=True,
                      boxprops=dict(facecolor='#3b82f6', alpha=0.7))
            axes[i][1].set_title(f'{col} 箱形圖', fontsize=12)

        plt.tight_layout()
        plt.savefig(f'{output_dir}/distributions.png', dpi=150, bbox_inches='tight')
        plt.close()
        print(f"✅ 分布圖 → {output_dir}/distributions.png")

    # (B) 相關性熱力圖
    if len(numeric_cols) > 1:
        corr_matrix = df[numeric_cols].corr()
        mask = np.triu(np.ones_like(corr_matrix, dtype=bool))

        fig, ax = plt.subplots(figsize=(max(8, len(numeric_cols)), max(6, len(numeric_cols)-1)))
        sns.heatmap(corr_matrix, mask=mask, annot=True, fmt='.2f',
                    cmap='coolwarm', center=0, vmin=-1, vmax=1,
                    square=True, ax=ax, cbar_kws={'shrink': 0.8})
        ax.set_title('欄位相關性矩陣', fontsize=14, pad=20)
        plt.tight_layout()
        plt.savefig(f'{output_dir}/correlation.png', dpi=150, bbox_inches='tight')
        plt.close()
        print(f"✅ 相關性熱力圖 → {output_dir}/correlation.png")

    # (C) 時間序列（若有日期欄位）
    date_cols = df.select_dtypes(include=['datetime64']).columns
    if len(date_cols) == 0:
        for col in df.columns:
            if any(kw in col.lower() for kw in ['date', 'time', '日期', '時間']):
                try:
                    df[col] = pd.to_datetime(df[col])
                    date_cols = [col]
                    break
                except:
                    pass

    if len(date_cols) > 0 and len(numeric_cols) > 0:
        date_col = date_cols[0]
        df_sorted = df.sort_values(date_col)

        fig, ax = plt.subplots(figsize=(14, 5))
        for col in numeric_cols[:3]:  # 最多顯示 3 條趨勢線
            ax.plot(df_sorted[date_col], df_sorted[col], label=col, linewidth=1.5)

        ax.set_title('時間序列趨勢', fontsize=14)
        ax.set_xlabel('日期')
        ax.legend()
        ax.grid(alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(f'{output_dir}/timeseries.png', dpi=150, bbox_inches='tight')
        plt.close()
        print(f"✅ 時間序列圖 → {output_dir}/timeseries.png")
```
