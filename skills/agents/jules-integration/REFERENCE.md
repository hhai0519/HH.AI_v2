# jules-integration — 參考細節

## 額度查詢

目前 `Antigravity Jules Bridge` 擴充套件本身**沒有**內建的配額查詢 API（截至本文件撰寫時，
Jules 官方 REST API v1alpha 也尚未提供公開的配額查詢端點）。實務上的做法：

1. 請使用者直接在 [Jules Dashboard](https://jules.google.com) 確認今天剩餘次數
   （Dashboard 上會顯示已用/剩餘），這是目前最可靠的來源
2. 如果之後 Jules API 開放配額查詢端點，或擴充套件新增這個功能，優先改用程式化查詢，
   降低每次都要使用者手動確認的摩擦——但在那之前，**寧可多問使用者一次，也不要用本地
   session 列表去猜測配額**（session 列表 API 不保證能準確反映官方配額計算方式，
   猜測出來的數字如果算錯，可能導致誤判「還有額度」而浪費掉稀缺的呼叫次數）

## Context 打包內容（由擴充套件負責，本技能只需知道涵蓋範圍）

根據 `Send2Jules` 官方文件（`docs/architecture.md`），送到 Jules 的 prompt 會包含：

- Git diff（uncommitted 變更會先自動建立 WIP commit + 推送暫存分支）
- 目前開啟的檔案與游標位置
- Antigravity 對話 artifacts（`task.md`、`implementation_plan.md`）——會掃描
  `~/.gemini/antigravity/brain/` 底下的對話記錄，讓使用者從快速選單挑選要附帶的對話上下文

**在委派前提醒使用者確認**：如果目前開啟的檔案或最近的對話裡包含敏感資訊（連線字串、
金鑰、真實使用者資料），要先關閉那些檔案或避免選取那段對話，因為打包機制是自動抓取的，
不會主動過濾敏感內容。

## 跟 `authorized_mcp_tools` 白名單的對應

`SKILL.md` frontmatter 裡的 `authorized_mcp_tools: ["antigravity-jules-bridge.sendToJules"]`
對應的是這個擴充套件實際暴露的指令 ID。如果之後擴充套件版本更新、指令 ID 有變化，
記得同步更新這個欄位，不要讓白名單指向一個已經不存在的舊指令（那樣看起來像有限制，
實際上呼叫會直接失敗，反而掩蓋了「白名單機制其實沒生效」這個問題，不如直接讓它報錯明顯）。

## 已知限制

- 擴充套件最後更新時間是 2025-11-23，維護頻率不算高。如果之後 Jules API 有重大變更
  導致這個擴充套件失效，暫時的備援方案是回到「使用者手動在 Jules Dashboard 網頁操作」，
  不建議退回到自行 vendor 原始碼、手動編譯部署 MCP server 那條路（見
  `docs/adr/0003-jules-integration-via-extension.md` 的決策理由）。
