# ADR-0003: Jules 整合初期採用非官方 VSCode 擴充套件橋接方案

- Status: Superseded by ADR-0019
- Date: 2026-08-10

## Context

前期研究（見對話歷史中的 4 份 Jules 整合報告）規劃的方案是：把
`sajidmahamud835/antigravity-jules-integration` 的原始碼複製進
`skills/03_Execution/jules-integration`，自行 `npm install` + 編譯，
並手動把 `JULES_API_KEY` 寫進 `mcp_config.json`。

查證後發現兩個問題：
1. Antigravity 本質上是 VS Code fork，原生支援透過 Extensions 面板（預設市集
   是 Open VSX）或 `.vsix` 手動安裝擴充套件，不需要自己 vendor 原始碼、扛下游
   專案的維護與升級責任。
2. 手動方案裡金鑰會以明文寫入 `mcp_config.json`（一個會被追蹤進 git 的設定檔），
   跟官方擴充套件用 OS 層級 SecretStorage 存放金鑰相比，安全性明顯較差——而且
   這個落差正是前期報告自己提出「嚴禁硬編碼金鑰」的規則，卻在自己給的實作腳本裡
   違反的地方。

進一步查證確認 Antigravity 擴充套件市集裡已經有現成的 **Antigravity Jules Bridge**
（`antigravity-jules-bridge.antigravity-jules-bridge`，原始碼為
[Germain-L/Send2Jules](https://github.com/Germain-L/Send2Jules)），功能涵蓋前期
研究想要的核心能力（context 打包、git 同步、雲端委派），且金鑰用 SecretStorage
安全存放。

## Decision

`jules-integration` 技能改為依賴透過 Extensions 面板安裝的官方擴充套件，
不再自行 vendor `sajidmahamud835/antigravity-jules-integration` 的原始碼。
技能本身只定義「什麼時候該委派、額度怎麼把關、委派前後要檢查什麼」，不包含
任何編譯/部署腳本。

「Suggestions BETA」網頁 DOM 抓取那套繞道方案（前期研究規劃用 Chrome DevTools MCP
解析 Jules Dashboard）予以擱置，不列入本次遷移範圍——一來官方擴充套件沒有涵蓋
這塊，二來這套方案本身承認容易因 UI 更新失效，且涉及對 Google 網頁做非官方
自動化存取，優先度不高。

## Consequences

- 不需要維護一份第三方原始碼的本地副本，降低長期維護負擔。
- 技能的觸發積極度沿用 `agents/` bucket 的保守標準
  （見 ADR-0002），因為額度稀缺、有真實副作用。
- 依賴一個 9 個月沒更新的擴充套件（`Send2Jules` 最後更新 2025-11-23），如果
  Jules 官方 API 有重大變更導致它失效，備援方案是退回使用者手動在 Jules
  Dashboard 網頁操作，而不是重新回頭 vendor 原始碼。
- Suggestions BETA 功能如果之後想做，需要另外開一次評估，不在這次的
  `jules-integration` 技能範圍內。
