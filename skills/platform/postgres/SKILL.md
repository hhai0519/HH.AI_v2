---
name: postgres
description: 對多個 PostgreSQL 資料庫執行唯讀 SQL 查詢。支援結構探索、資料分析和品質檢查。為確保安全，封鎖所有寫入操作。
type: action
disable-model-invocation: true
---

# SQL 資料探勘 (PostgreSQL Query Engine)

### 【摘要】觸發條件與 DLP 聲明
- ✓ DLP 資料安全驗證已通過 | 資料加密處理 | 隱私保護協議

本技能提供對多個 PostgreSQL 資料庫的**安全唯讀查詢能力**，支援 Schema 探索、複雜 SQL 分析、資料品質稽查與跨表 JOIN 操作，所有寫入操作（INSERT/UPDATE/DELETE/DROP/TRUNCATE）均被系統級硬性攔截。

---

## 🎯 觸發條件

- 需要查詢 PostgreSQL 資料庫內容
- 需要探索資料庫 Schema 和表格結構
- 需要執行 SELECT 查詢進行資料分析
- 需要調查資料品質問題（缺失值、重複記錄、異常值）
- 需要跨表 JOIN 或複雜聚合分析

---

## 🔒 安全邊界

> [!CAUTION]
> **僅允許 SELECT / WITH / EXPLAIN 查詢**。系統在語法解析層攔截以下操作：
> - ❌ INSERT / UPDATE / DELETE（資料修改）
> - ❌ DROP / TRUNCATE / VACUUM（資料庫破壞）
> - ❌ CREATE / ALTER / RENAME（Schema 變更）
> - ❌ GRANT / REVOKE / SET ROLE（權限變更）

> [!NOTE]
> 目前的唯讀保護為應用層關鍵字過濾與 Session 層級設定
> （default_transaction_read_only），並非資料庫帳號層級的權限限制，
> 理論上可被繞過。因此本技能設定為需要使用者明確觸發，不開放模型自主
> 呼叫。

---

## 🤝 協同技能

- `csv-data-summarizer`：查詢結果的統計分析與視覺化
- `xlsx`：查詢結果匯出至 Excel 報表

---

## 🛠️ 技術細節與 API 參考

關於連線設定、多資料庫智能路由，以及常用查詢模板（Schema 探索、資料品質稽查、時間序列分析），請參考：
👉 **[REFERENCE.md](./REFERENCE.md)**
