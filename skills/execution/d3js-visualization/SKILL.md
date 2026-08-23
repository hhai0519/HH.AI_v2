---
name: d3js-visualization
description: "使用 d3.js 建立互動式資料視覺化。適用於客製化圖表、網路圖、地理視覺化，或任何需要對視覺元素、過渡或互動進行精細控制的複雜 SVG 資料視覺化。"
---


# D3.js 互動視覺化 (D3.js Visualization)

### 【摘要】觸發條件與 DLP 聲明
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議

本技能使用 **D3.js v7** 建立需要高度客製化的 SVG 資料視覺化，包含力導向網路圖、地理熱力圖、桑基圖（Sankey）、K 線圖、平行座標圖等複雜圖表，完整掌控動畫、互動與過渡效果。


---

## 🎯 觸發條件

- 需要力導向網路圖（技能關係圖、知識圖譜）
- 需要地理視覺化（Choropleth、點地圖）
- 需要桑基圖（資金流向、轉換漏鬥）
- 需要比 ECharts/Plotly 更精細的自訂控制

---

## 🛠️ 核心架構模式

### 標準 D3 Chart 結構

```javascript
// 通用 D3 圖表架構
class D3Chart {
  constructor(selector, config = {}) {
    this.config = {
      width: config.width || 800,
      height: config.height || 500,
      margin: config.margin || { top: 40, right: 30, bottom: 60, left: 60 },
      ...config
    };
    
    // 計算繪圖區域
    this.innerWidth = this.config.width - this.config.margin.left - this.config.margin.right;
    this.innerHeight = this.config.height - this.config.margin.top - this.config.margin.bottom;
    
    // 建立 SVG 容器
    this.svg = d3.select(selector)
      .append('svg')
      .attr('width', this.config.width)
      .attr('height', this.config.height)
      .attr('viewBox', `0 0 ${this.config.width} ${this.config.height}`)
      .attr('style', 'max-width: 100%; height: auto;');
    
    // 主繪圖群組（套用 margin）
    this.g = this.svg.append('g')
      .attr('transform', `translate(${this.config.margin.left},${this.config.margin.top})`);
    
    // Tooltip
    this.tooltip = d3.select('body').append('div')
      .attr('class', 'd3-tooltip')
      .style('opacity', 0)
      .style('position', 'absolute')
      .style('background', 'rgba(0,0,0,0.8)')
      .style('color', 'white')
      .style('padding', '8px 12px')
      .style('border-radius', '6px')
      .style('font-size', '13px')
      .style('pointer-events', 'none');
  }
  
  showTooltip(event, content) {
    this.tooltip.transition().duration(200).style('opacity', 1);
    this.tooltip.html(content)
      .style('left', (event.pageX + 15) + 'px')
      .style('top', (event.pageY - 28) + 'px');
  }
  
  hideTooltip() {
    this.tooltip.transition().duration(300).style('opacity', 0);
  }
}
```

---


> [!NOTE]
> 詳細參數與 API 清單、進階範例請見 [REFERENCE.md](./REFERENCE.md)
