# PE River Map - 核心計算邏輯參考

## 🛠️ 河流圖核心計算

```python
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

def draw_pe_river(df: pd.DataFrame, pe_bands: list = [8, 12, 16, 20, 25]):
    """
    df: DataFrame with columns ['date', 'close', 'eps_ttm']
    pe_bands: List of P/E multiples to draw as river bands
    """
    df['date'] = pd.to_datetime(df['date'])
    
    fig, ax = plt.subplots(figsize=(14, 7))
    
    colors = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#3b82f6']
    band_labels = []
    
    # Draw PE bands
    for i, pe in enumerate(pe_bands):
        band_price = df['eps_ttm'] * pe
        ax.fill_between(df['date'], 
                        df['eps_ttm'] * (pe_bands[i-1] if i > 0 else 0),
                        band_price,
                        alpha=0.15, color=colors[i])
        ax.plot(df['date'], band_price, '--', color=colors[i], 
                linewidth=0.8, label=f'{pe}x PE')
        band_labels.append(mpatches.Patch(color=colors[i], label=f'{pe}x PE'))
    
    # Draw actual price
    ax.plot(df['date'], df['close'], 'k-', linewidth=2, label='實際股價', zorder=5)
    
    ax.set_title('P/E 估值河流圖', fontsize=16, fontweight='bold')
    ax.set_xlabel('日期')
    ax.set_ylabel('股價（元）')
    ax.legend(handles=band_labels + [
        mpatches.Patch(color='black', label='實際股價')
    ], loc='upper left')
    ax.grid(alpha=0.3)
    
    # 註：此處輸出圖片路徑為範例，實際執行應動態指定當前工作區路徑或 scratch 目錄。
    plt.tight_layout()
    plt.savefig('pe_river_map.png', dpi=150)
    return fig
```

## 🔢 EPS 趨勢分析

```python
# 透過滾動 EPS 推算合理股價
def estimate_fair_value(current_eps: float, growth_rate: float, target_pe: float, years: int = 3) -> dict:
    """
    current_eps: 當前 EPS (TTM)
    growth_rate: 預期年增率 (小數, e.g., 0.15 = 15%)
    target_pe: 合理 PE 倍數
    """
    projected_eps = current_eps * ((1 + growth_rate) ** years)
    fair_value = projected_eps * target_pe
    
    return {
        "當前 EPS": current_eps,
        f"{years}年後預估 EPS": round(projected_eps, 2),
        "目標PE": target_pe,
        "合理股價目標": round(fair_value, 1)
    }
```
