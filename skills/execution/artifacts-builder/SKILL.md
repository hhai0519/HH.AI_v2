---
name: artifacts-builder
description: 一套用於使用現代前端 Web 技術（React、Tailwind CSS、shadcn/ui）建立精細、多組件 HTML 成品的工具。適用於需要狀態管理、路由或 shadcn/ui 元件的複雜成品。
---

# Artifacts 原型建構 (Artifacts Builder)

本技能專精於建立功能完整的**互動式 HTML 原型**，整合 React、Tailwind CSS 與 shadcn/ui 元件庫，能快速呈現複雜 UI 概念或可執行的前端原型。

## 🎯 觸發條件

- 需要建立互動式 UI 演示或原型
- 需要多頁面路由的 Web 應用原型
- 需要使用 shadcn/ui 標準元件（Button、Dialog、Table...）
- 需要帶有狀態管理的複雜 UI（購物車、表單驗證、即時篩選）
- 簡單靜態 HTML 已無法滿足需求

## 🏗️ 技術選型

| 場景 | 推薦選擇 |
|---|---|
| 簡單靜態頁面 | 直接 HTML + CSS + JS（不使用本技能） |
| **複雜互動原型** | **本技能（React + Tailwind + shadcn）** |
| 需要路由 | React + React Router |
| 需要狀態管理 | React useState / useReducer / Zustand |
| 圖表元件 | Recharts / D3（搭配 `d3js-visualization`）|

## 📋 標準建構流程

```
1. 分析需求 → 定義元件樹
2. 設計 Token（色彩/字型/間距）
3. 建立基礎佈局元件
4. 實作各功能頁面
5. 串接狀態管理
6. 加入動畫與微交互
7. 驗證響應式設計
```

## 🎨 元件架構範例

```jsx
// shadcn/ui 標準元件整合
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"

export function SkillCard({ skill, category, dlpStatus }) {
  return (
    <Card className="hover:shadow-lg transition-shadow">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {skill.name}
          <Badge variant={dlpStatus ? "success" : "destructive"}>
            {dlpStatus ? "✅ DLP" : "❌ No DLP"}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-muted-foreground">{skill.description}</p>
      </CardContent>
    </Card>
  );
}
```

## 💡 設計品質標準

> [!IMPORTANT]
> 所有 Artifact 輸出必須達到「WOW 效果」——首次看到即令人印象深刻。
> - ✅ 使用 Google Fonts（Inter、Outfit）
> - ✅ 實作 hover 效果與微動畫
> - ✅ 深色模式支援
> - ✅ 響應式設計（Mobile-first）
> - ❌ 不使用純藍/純紅等普通顏色
> - ❌ 不留白或佔位符

## 🤝 協同技能

- `theme-factory`：取得專業配色方案
- `d3js-visualization`：整合複雜圖表元件
