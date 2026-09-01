# d3js-visualization Reference

## 📊 力導向網路圖（Force-Directed Graph）

```javascript
class ForceGraph extends D3Chart {
  render(nodes, links) {
    // 定義力模擬
    const simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links).id(d => d.id).distance(80))
      .force('charge', d3.forceManyBody().strength(-300))
      .force('center', d3.forceCenter(this.innerWidth / 2, this.innerHeight / 2))
      .force('collision', d3.forceCollide().radius(d => d.radius + 5));
    
    // 繪製連線
    const link = this.g.selectAll('.link')
      .data(links).enter()
      .append('line')
      .attr('class', 'link')
      .attr('stroke', d => d.color || '#999')
      .attr('stroke-opacity', 0.6)
      .attr('stroke-width', d => Math.sqrt(d.value || 1));
    
    // 繪製節點
    const node = this.g.selectAll('.node')
      .data(nodes).enter()
      .append('g')
      .attr('class', 'node')
      .call(d3.drag()
        .on('start', (event, d) => {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x; d.fy = d.y;
        })
        .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on('end', (event, d) => {
          if (!event.active) simulation.alphaTarget(0);
          d.fx = null; d.fy = null;
        })
      );
    
    node.append('circle')
      .attr('r', d => d.radius || 12)
      .attr('fill', d => d.color || '#69b3a2')
      .on('mouseover', (event, d) => this.showTooltip(event, `<b>${d.id}</b><br>${d.label || ''}`))
      .on('mouseout', () => this.hideTooltip());
    
    node.append('text')
      .text(d => d.label || d.id)
      .attr('dy', '0.35em')
      .attr('text-anchor', 'middle')
      .style('font-size', '11px')
      .style('fill', 'white')
      .style('pointer-events', 'none');
    
    // 動畫更新
    simulation.on('tick', () => {
      link
        .attr('x1', d => d.source.x)
        .attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x)
        .attr('y2', d => d.target.y);
      node.attr('transform', d => `translate(${d.x},${d.y})`);
    });
  }
}
```

---

## 🗺️ 地圖熱力圖（Choropleth）

```javascript
class ChoroplethMap extends D3Chart {
  async render(geoDataUrl, dataMap, valueKey) {
    const geoData = await d3.json(geoDataUrl);
    
    const projection = d3.geoMercator()
      .fitSize([this.innerWidth, this.innerHeight], geoData);
    
    const path = d3.geoPath().projection(projection);
    
    const colorScale = d3.scaleSequential()
      .domain(d3.extent(Object.values(dataMap)))
      .interpolator(d3.interpolateYlOrRd);
    
    this.g.selectAll('.region')
      .data(geoData.features).enter()
      .append('path')
      .attr('class', 'region')
      .attr('d', path)
      .attr('fill', d => {
        const val = dataMap[d.properties.name];
        return val ? colorScale(val) : '#eee';
      })
      .attr('stroke', '#fff')
      .attr('stroke-width', 0.5)
      .on('mouseover', (event, d) => {
        const val = dataMap[d.properties.name] || '無資料';
        this.showTooltip(event, `<b>${d.properties.name}</b><br>${valueKey}: ${val}`);
      })
      .on('mouseout', () => this.hideTooltip());
  }
}
```

---

## 🌊 流向圖（Sankey Diagram）

```javascript
// 需要 d3-sankey 套件
import { sankey, sankeyLinkHorizontal } from 'd3-sankey';

class SankeyChart extends D3Chart {
  render(nodes, links) {
    const sankeyLayout = sankey()
      .nodeWidth(20)
      .nodePadding(10)
      .extent([[0, 0], [this.innerWidth, this.innerHeight]]);
    
    const { nodes: sNodes, links: sLinks } = sankeyLayout({ nodes, links });
    
    // 繪製連結（流）
    this.g.selectAll('.link')
      .data(sLinks).enter()
      .append('path')
      .attr('d', sankeyLinkHorizontal())
      .attr('fill', 'none')
      .attr('stroke', d => d.color || '#a8d8ea')
      .attr('stroke-opacity', 0.5)
      .attr('stroke-width', d => Math.max(1, d.width));
    
    // 繪製節點
    this.g.selectAll('.node')
      .data(sNodes).enter()
      .append('rect')
      .attr('x', d => d.x0).attr('y', d => d.y0)
      .attr('height', d => d.y1 - d.y0)
      .attr('width', d => d.x1 - d.x0)
      .attr('fill', (_, i) => d3.schemeTableau10[i % 10]);
  }
}
```

---

## 🤝 協同技能

- `artifacts-builder`：D3 圖表嵌入 React 組件
- `theme-factory`：標準化配色主題套用

---

## 版本紀錄 (Changelog)
- **[2.0.0]** 2026-05-04：V2.0.0 Polymorphic Labeling Migration — 依生命週期 SOP 導入多態功能性技術標籤 (tool_category, execution_env, io_format)，建立執行層 Manifest 路由能力。

## [Security] Smart Integration & DLP
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議


---
⚙️ 【系統通訊層宣告 (System Comms Layer)】

網路狀態： 本技能已強制接入總控通訊網路。

接收協定 (Dynamic Payload)： 本文檔不再接收無結構的自然語言，必須處理封裝後的動態參數：
`[SYSTEM-CALL: d3js-visualization | PAYLOAD: { objective: "<核心意圖>", target_audience: "<受眾>", strategic_constraints: "<策略限制/禁語>", tone_variables: "<語氣微調>" }]`

> [!IMPORTANT]
> **Payload 淨化規則**（規範本體見 `.agents/rules/skill-engineering-guardrails.md` §3）：
> 本技能位於 `execution/`，屬技術型技能，因此：
> - 接收：URL、API Endpoint、SQL Query、JSON Schema、檔案絕對路徑
> - 拒絕：認知參數、語氣描述、角色設定、情緒變數

發送協定：執行中若遇能力不足或需要外部協作，應停下來明確告知使用者目前卡在哪裡，不要自行尋找替代方案掩蓋問題。如需調閱其他技能，封裝 Dynamic Payload 並發出：
`[SYSTEM-CALL: 目標ID | PAYLOAD: { ... }]`

回傳協定： 任務終止時，必須且只能輸出 `[SYSTEM-RETURN: SUCCESS/FAILED | DATA: <結果>]`。
