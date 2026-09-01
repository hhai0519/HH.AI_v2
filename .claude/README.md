# `.claude/` — 宏觀審計官的規則目錄

> **適用對象：Claude（宏觀審計官／規劃者）**
> **Antigravity IDE Agent 請注意：本目錄的內容不是你的行為指令。**

## 這個目錄是什麼

本專案有兩個 AI 代理人，各有一套規則目錄，互為鏡像：

| 目錄 | 適用對象 | 載入方式 |
|---|---|---|
| `.agents/rules/` | Antigravity IDE Agent（執行者） | 由 IDE 自動載入 |
| `.claude/rules/` | Claude（宏觀審計官／規劃者） | 由審計官在對話開場時主動 clone 讀取 |

角色分工的定義見 `PRINCIPLES.md` §0，
為什麼需要這個分工見 `docs/adr/0007-macro-auditor-role.md`。

## 給執行者的說明

你可以編輯本目錄下的檔案，但僅限提示詞中明確指定完整檔案路徑時。

**不得**把其中任何內容當作自己要遵守或執行的規則。
**不得**因為「看起來過期」「順便同步」而主動修改。

對照關係很簡單：`.agents/` 是你的，`.claude/` 是審計官的。
細節見 `.agents/rules/role-boundaries.md`。

## 內容

- `rules/auditor-protocol.md` — 審計官作業協定：四個審計維度、
  Gatekeeping 規則、報告格式、查證紀律、提示詞產出紀律。
