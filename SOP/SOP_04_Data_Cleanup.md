---
title: "資料清理與工作站保護標準作業程序"
version: "3.1.3"
tags: ["SOP", "資料清理", "工作站管理", "Data Cleanup"]
dependencies: [".agents/rules/skill-engineering-guardrails.md"]
---

# 資料清理與工作站保護標準作業程序 (SOP)

**文件編號**：SOP-CLEANUP-001
**版本**：3.1.3
**建立日期**：2026-04-19
**更新日期**：2026-05-04（更新於 2026-05-04）
**適用範圍**：所有 本協作系統 工作站與相關專案目錄的資料管理

---

## ⚠️ 安全警示：執行前確認

> **此 SOP 涉及資料刪除與系統清理，執行前必須確認已備份所有重要資料。**
> 操作前務必檢查保護資產清單，確保未誤觸受保護目錄。

---

## 一、受保護資產清單（Protected Assets）

### 1.1 核心受保護路徑

| 名稱 | 路徑 | 說明 |
|------|------|------|
| Skills 官方技能庫 | `<USER_HOME>\.gemini\本協作系統\skills\` | 本協作系統 核心技能（數量見各 bucket 的 README.md），禁止直接刪除 |
| Skills 本地目錄 | `./skills/` | 本地擴充技能目錄 |
| Windows 啟動項目 | `%APPDATA%\..\Start Menu\Programs\Startup\` | 系統自動啟動設定（操作需謹慎） |

> [!IMPORTANT]
> **Watchdog 機制說明**：詳見 `docs/adr/0013-watchdog-async-buffer-neon-db.md`。

### 1.2 專案應用目錄

| 名稱 | 路徑 | 說明 |
|------|------|------|
| tw-stock-web | `<工作站路徑>\tw-stock-web\` | 主要 Next.js 應用程式目錄 |
| taiwan-stock | `<工作站路徑>\taiwan-stock\` | 靜態分析頁面 |
| autoresearch-cpu | `<工作站路徑>\autoresearch-cpu\` | ML 訓練實驗目錄 |

### 1.3 可歸檔資產

| 名稱 | 路徑 | 說明 |
|------|------|------|
| Git 歸檔壓縮包 | `docs\archives\*.zip` | 版本歷史壓縮備份 |
| 訓練實驗結果 | `autoresearch-cpu\results.tsv` | 不再需要的舊版實驗結果 |
| 歷史摘要文件 | `Summary_History.md` | 舊版工作站歷史記錄彙整 |

---

## 二、安全清理執行流程

**執行前確認：請依序完成以下 5 個步驟**

### Step 1：掃描異常路徑引用
```powershell
# @EXECUTE
# 搜尋所有腳本中的舊路徑引用（排除 node_modules 與 .next）
Get-ChildItem -Recurse -Include "*.py","*.ps1","*.bat","*.js","*.html","*.json" |
  Where-Object { $_.FullName -notmatch "node_modules|\.next" } |
  Select-String -Pattern "舊路徑|Desktop\\<WORKSPACE_ROOT>"
```
確認後，將引用了舊路徑的腳本逐一更新至新路徑。

### Step 2：確認 Windows 啟動項目
```powershell
# @EXECUTE
# 確認 Windows 啟動資料夾內容
Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
```
確認後，若有不需要的啟動項目，手動評估是否移除。

### Step 3：確認背景執行程序
```powershell
# @EXECUTE
# 確認是否有佔用舊路徑的背景程序
Get-Process | Where-Object { $_.Path -like "*<WORKSPACE_ROOT>*" }
```
若有殘留程序在執行，先行終止再繼續清理。

### Step 4：標記待刪除項目
- 將確認可刪除的項目移動至 `_TO_DELETE\` 暫存資料夾，勿直接刪除。
- `_TO_DELETE\` 保留觀察 **7 天**後，確認無異常再執行永久刪除。

### Step 5：驗證服務健康狀態
```powershell
# @EXECUTE
# 確認本地開發伺服器正常回應
Invoke-WebRequest http://localhost:3000 -UseBasicParsing | Select StatusCode
Invoke-WebRequest http://localhost:8888 -UseBasicParsing | Select StatusCode
```
確認 Dashboard、腳本、Watchdog Hook 與 Next.js 應用程式均正常運作。

---

## 三、可安全清理的暫存項目
| 類型 | 說明 |
|------|------|
| `node_modules\` | 可透過 `npm install` 重新還原 |
| `.next\` | Next.js 建置快取，可重新建置 |
| `*.log` 類型 | 超過保留期限（建議 7 天）的舊日誌 |
| `*.bak` 類型 | 不再需要的舊版備份 |
| `_TO_DELETE\` | 觀察期結束後可永久刪除 |

---

## 四、工作站目錄結構（標準化範本）

```
<WORKSPACE_ROOT>/              ← 主要工作站目錄
├── README.md                    ← 工作站說明與快速啟動指南
├── Summary_History.md           ← 舊版工作站歷史記錄彙整
├── skills/                      ← 技能目錄（七桶分類架構）
│   ├── orchestration/
│   ├── analysis/
│   ├── agents/
│   ├── execution/
│   ├── platform/
│   ├── meta/
│   └── deprecated/
├── autoresearch-cpu/            ← ML 訓練實驗目錄
│   └── SOP_09_AutoResearch_CPU.md
├── SOP/                         ← 標準作業程序文件
│   ├── SOP_01_Automation_Process.md
│   ├── SOP_02_Security_Guidelines.md
│   ├── SOP_04_Data_Cleanup.md     ← 本文件
│   ├── SOP_05_System_Policies.md
│   ├── SOP_06_Handover_Manual.md
│   ├── SOP_09_AutoResearch_CPU.md
│   └── reports/
│       └── skills_categorization_report.md
```

> **注意**：`skills/` 本地目錄的技能定義以 本協作系統 官方技能庫為準，路徑為：
> `<USER_HOME>\.gemini\本協作系統\skills\`

---

## 五、清理後復原備忘
- 若誤刪重要資料，優先查看 `_TO_DELETE\` 暫存資料夾是否仍保留。
- 若 `_TO_DELETE\` 已清空，確認 `docs\archives\` 目錄或 Git 歷史版本中是否有備份。
- 實驗結果或報告可於 `docs\reports\` 目錄中查找歸檔版本。

---

## 六、UI 語言與顯示規範 (UI & Language Standards)

> **語言規定：所有 Dashboard 介面文字與設定項目，必須使用台灣正體中文（Traditional Chinese）撰寫。**

1. **翻譯覆蓋率要求**：每項 Skill 的說明必須確認 `SKILL.md` 的 YAML frontmatter 中已有完整的正體中文翻譯，填寫率須達 100%。
2. **SKILL.md 語言規定**：`SKILL.md` 的觸發說明與描述必須使用**台灣正體中文**（允許保留英文技術術語）。
3. **技能命名一致性**：實體目錄名稱須與技能唯一識別碼完全一致，例如 `twse-market-logic` 禁止出現命名不一致的情況。

---

## 七、本地服務埠號規範

> **重要提醒：以下服務埠號為固定規範，切勿隨意更改以免衝突**

| 服務 | 埠號 | URL | 說明 |
|------|------|-----|------|
| **Next.js 應用程式** | **3000** | http://localhost:3000 | tw-stock-web 主要應用 |
| **靜態 HTTP 伺服器** | **8888** | http://localhost:8888 | taiwan-stock/ 靜態頁面 |

### 服務啟動確認步驟
1. 確認工作目錄與服務類型正確（html / js / bat / py）
2. 以系統管理員身分執行對應腳本
3. 啟動伺服器，確認無埠號衝突
4. 等待約 12 秒後進行健康狀態確認
5. 更新 SOP 中的最新服務狀態

---

*本 SOP 建立於 2026-04-19 ｜ v3.1.3 更新於 2026-05-04（更新於 2026-05-04）*
