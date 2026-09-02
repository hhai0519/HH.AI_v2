# ADR-0005: 高風險技能遷移，禁止只憑摘要放行，必須看完整內容 + 直接查驗實體檔案

- Status: Accepted
- Date: 2026-08-13

## Context

第四批·第一小批遷移 `agency-orchestrator`、`reality-checker` 等 5 個
orchestration 技能時，經歷了 3 輪來回才真正定案：

1. 第一輪：Agent 回報「已完成」，但只給了 frontmatter 前後比對，沒有給本體
   內容。逐欄位核對後，發現 `triggers`、`dependencies` 資訊被無聲丟棄
   （見 ADR-0004 的同類型問題再次出現）。
2. 第二輪：要求看完整 SKILL.md 全文後，才發現更嚴重的問題——一段
   「Zero-Block Policy」規則寫著「執行中若遇能力不足或需外部協作，嚴禁中斷
   或詢問使用者」，直接牴觸本專案從頭到尾的核心原則（遇到不確定情況要停下來
   問人，不要自行找替代方案）。同時發現硬編碼觸發符號（`$$自動化$$` 等）
   完全沒被處理、同一份檔案內有兩段互相矛盾的「系統通訊層宣告」、以及一個
   遷移後已經失效的 Windows 絕對路徑。這些問題只看前兩次的摘要式回報
   完全看不出來。
3. 第三輪：修正過程中，Agent 用文字取代方式改路徑，卻把中文註解誤植進了
   反引號包起來的指令字串內部，導致指令本身變成無效指令；同時 frontmatter
   裡的 `type: orchestrator` 是一個從未在 AGENTS.md 定義過的欄位值，如果
   不在這批就處理掉，後面幾十個技能會照抄一個沒有明確定義的欄位。

每一輪的問題，都是靠「不接受文字摘要、要求看完整內容」以及「直接 clone
public repo 核對實體檔案，不只看 Agent 的文字報告」才抓到的。

## Decision

往後遷移任何 `orchestration/` 或 `agents/` bucket 底下的技能（尤其是
總管／路由類、會被其他技能依賴的核心技能），一律套用「三層核對」流程。

本節規範已移至 `SOP/SOP_14_Rigorous_Verification_and_Audit_Protocol.md` §7。
本 ADR 只保留 Context 記錄的三輪來回事件，作為該流程的來源依據。

## Consequences

- 高風險技能的遷移速度會變慢（這批花了 3 輪），但符合根目錄 `AGENTS.md`
  第 0 節「品質優先於速度」的原則。
- 需要人工持續核對，無法完全交給 Agent 自主判斷完成，這是刻意的設計，
  不是流程效率不足。
- 這次額外發現：Agent 自己的「已完成」回報可信度，跟給出的細節完整程度
  成正比——只給摘要時最容易漏掉重要問題，這個經驗值得套用到所有後續批次。

## 2026-09-01 分層搬移

依 `PRINCIPLES.md` §1，原 Decision 章節的三層核對流程（三個步驟與
適用範圍）屬可執行規範，已移至
`SOP/SOP_14_Rigorous_Verification_and_Audit_Protocol.md` §7。
Context 與 Consequences 原文未變動。
