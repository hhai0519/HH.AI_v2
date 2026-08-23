# SQL 資料探勘 (PostgreSQL Query Engine) - 技術細節參考

## 🛠️ 連線設定

所有資料庫連線字串與憑證必須透過環境變數傳入，**嚴禁在程式碼中硬編碼真實密碼與連線資訊**。

```python
import psycopg2
import pandas as pd
import os
from typing import Optional

class SafePostgresReader:
    """安全唯讀 PostgreSQL 連線管理器"""
    
    BLOCKED_KEYWORDS = ['INSERT', 'UPDATE', 'DELETE', 'DROP', 'TRUNCATE',
                        'CREATE', 'ALTER', 'GRANT', 'REVOKE', 'VACUUM']
    
    def __init__(self, host: str, port: int, database: str, 
                 user: str, password: str, connect_timeout: int = 10):
        self.conn_params = {
            "host": host, "port": port, "database": database,
            "user": user, "password": password,
            "connect_timeout": connect_timeout,
            "options": "-c default_transaction_read_only=on"  # 資料庫層唯讀鎖
        }
        self._conn = None
    
    def _validate_query(self, sql: str):
        """SQL 安全驗證"""
        sql_upper = sql.upper().strip()
        for keyword in self.BLOCKED_KEYWORDS:
            if keyword in sql_upper.split():
                raise PermissionError(f"❌ 安全攔截：不允許執行 {keyword} 操作")
    
    def query(self, sql: str, params: tuple = None) -> pd.DataFrame:
        """執行安全查詢，返回 DataFrame"""
        self._validate_query(sql)
        
        if not self._conn or self._conn.closed:
            self._conn = psycopg2.connect(**self.conn_params)
        
        try:
            df = pd.read_sql_query(sql, self._conn, params=params)
            print(f"✅ 查詢完成：{len(df)} 行 × {len(df.columns)} 欄")
            return df
        except Exception as e:
            print(f"❌ 查詢失敗：{e}")
            raise
    
    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
```

---

## 🔧 多資料庫智能路由

```python
import os

# 必須從環境變數讀取連線資訊，不要硬編碼真實憑證
DB_CONFIGS = {
    "production": {
        "host": os.environ.get("PROD_DB_HOST"), 
        "database": os.environ.get("PROD_DB_NAME"), 
        "user": os.environ.get("PROD_DB_USER"),
        "password": os.environ.get("PROD_DB_PASS")
    },
    "analytics": {
        "host": os.environ.get("ANALYTICS_DB_HOST"), 
        "database": os.environ.get("ANALYTICS_DB_NAME"), 
        "user": os.environ.get("ANALYTICS_DB_USER"),
        "password": os.environ.get("ANALYTICS_DB_PASS")
    }
}

def smart_query(question: str, sql: str) -> pd.DataFrame:
    """根據問題描述自動選擇資料庫"""
    keywords_map = {
        "production": ["交易", "訂單", "使用者", "生產"],
        "analytics": ["分析", "報表", "統計", "趨勢"]
    }
    
    target_db = "production"  # 預設
    for db, keywords in keywords_map.items():
        if any(kw in question for kw in keywords):
            target_db = db
            break
    
    print(f"🎯 自動選擇資料庫：{target_db}")
    reader = SafePostgresReader(**DB_CONFIGS[target_db])
    return reader.query(sql)
```

---

## 📋 常用查詢模板

### Schema 探索

```sql
-- 1. 列出所有使用者表格
SELECT 
    table_schema,
    table_name,
    table_type,
    pg_size_pretty(pg_total_relation_size(quote_ident(table_schema) || '.' || quote_ident(table_name))) AS table_size
FROM information_schema.tables
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY table_schema, table_name;

-- 2. 查詢特定表格的欄位結構
SELECT 
    column_name,
    data_type,
    character_maximum_length,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'your_table_name'
ORDER BY ordinal_position;

-- 3. 查詢索引資訊
SELECT
    indexname,
    indexdef,
    pg_size_pretty(pg_relation_size(indexname::text)) AS index_size
FROM pg_indexes
WHERE tablename = 'your_table_name';
```

### 資料品質稽查

```sql
-- 4. 全面缺失值報告
SELECT
    COUNT(*) AS total_rows,
    COUNT(col1) AS col1_non_null,
    ROUND(100.0 * (COUNT(*) - COUNT(col1)) / COUNT(*), 2) AS col1_null_pct,
    COUNT(col2) AS col2_non_null,
    ROUND(100.0 * (COUNT(*) - COUNT(col2)) / COUNT(*), 2) AS col2_null_pct
FROM your_table;

-- 5. 重複記錄偵測
SELECT 
    email, COUNT(*) AS count
FROM users
GROUP BY email
HAVING COUNT(*) > 1
ORDER BY count DESC;

-- 6. 分布統計（含百分位數）
SELECT
    MIN(value) AS min_val,
    MAX(value) AS max_val,
    ROUND(AVG(value)::numeric, 2) AS mean,
    ROUND(STDDEV(value)::numeric, 2) AS std_dev,
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY value) AS q1,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY value) AS median,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY value) AS q3,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY value) AS p95
FROM your_table;
```

### 時間序列分析

```sql
-- 7. 按日/週/月聚合
SELECT
    DATE_TRUNC('day', created_at) AS date,
    COUNT(*) AS daily_count,
    SUM(amount) AS daily_revenue,
    ROUND(AVG(amount)::numeric, 2) AS avg_order_value
FROM orders
WHERE created_at >= NOW() - INTERVAL '90 days'
GROUP BY 1
ORDER BY 1;

-- 8. 環比增長率
WITH daily AS (
    SELECT DATE_TRUNC('day', created_at) AS day, COUNT(*) AS cnt
    FROM events GROUP BY 1
)
SELECT
    day,
    cnt,
    LAG(cnt) OVER (ORDER BY day) AS prev_day_cnt,
    ROUND((cnt - LAG(cnt) OVER (ORDER BY day)) * 100.0 / NULLIF(LAG(cnt) OVER (ORDER BY day), 0), 2) AS growth_pct
FROM daily
ORDER BY day DESC
LIMIT 30;
```
