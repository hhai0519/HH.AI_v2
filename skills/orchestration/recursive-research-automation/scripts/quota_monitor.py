import sqlite3
import json
import os
import sys

# 預設路徑與設定
DB_PATH = os.path.join(os.getcwd(), "state_copy.vscdb")
THRESHOLD = 20.0  # 剩餘 20% 代表觸發終結路徑

# 強致 UTF-8 輸出
if sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        # Python 3.7 以前的版本
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def get_quota():
    """嘗試從各種來源獲獲取 Gemini 3 Flash 配額百分比，優先級：手動臨時檔 > 資料庫自動偵測"""
    
    # 優先級 1: 手動覆蓋 (最高優先級)
    if os.path.exists("current_quota.tmp"):
        try:
            with open("current_quota.tmp", "r", encoding='utf-8-sig') as f:
                content = f.read().strip()
                if content:
                    val = float(content)
                    return val, "Source: current_quota.tmp (Manual Override)"
        except Exception as e:
            print(f"⚠️ 讀取 current_quota.tmp 失敗: {e}")

    # 優先級 2: 資料庫自動偵測
    try:
        if not os.path.exists(DB_PATH):
            return None, f"找不到資料庫文件: {DB_PATH}"
            
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 嘗試舊版 Cockpit 鍵值
        cursor.execute("SELECT value FROM ItemTable WHERE key='jlcodes.本協作系統-cockpit'")
        row = cursor.fetchone()
        if row:
            data = json.loads(row[0])
            remaining = data.get("state.model_quotas", {}).get("MODEL_PLACEHOLDER_M47", {}).get("remaining_percent")
            if remaining is not None:
                conn.close()
                return float(remaining), "Source: Cockpit DB Cached"

        # 嘗試新版模型配額鍵值 (modelCredits)
        cursor.execute("SELECT value FROM ItemTable WHERE key='本協作系統UnifiedStateSync.modelCredits'")
        row = cursor.fetchone()
        if row:
            # TODO: 目前 modelCredits 為二進位加密/壓縮格式，暫僅標註偵測到鍵值
            # 實際百分比解析需待通訊協定逆向，目前返回 None 觸發手動提示
            conn.close()
            return None, "偵測到新版 modelCredits 鍵值，但目前無法直接解析二進位格式。請改用 current_quota.tmp 進行手動注入。"

        conn.close()
    except Exception as e:
        return None, f"讀取資料庫時發生異常: {e}"

    return None, "無法自動取得配額。請手動檢查 本協作系統 Cockpit 面板並更新 current_quota.tmp。"

def main():
    print("=== 本協作系統 Quota Monitor v1.1 ===")
    quota, msg = get_quota()
    
    if quota is not None:
        print(f"當前配額: {quota}%")
        print(f"來源: {msg}")
        if quota <= THRESHOLD:
            print(f"⚠️ 終結警報：配額已低於臨界點 ({THRESHOLD}%)！")
            sys.exit(1) # 回傳 1 觸發自動化停機
        else:
            print(f"✅ 配額充足 ({quota}%)，可繼續循環研究。")
            sys.exit(0)
    else:
        print(f"ℹ️ 狀態提示: {msg}")
        # 在無法確定的情況下，回傳 0 (不中斷)，但發出強烈警告
        print("---")
        print("警告: 監控腳本未能取得有效配額數值。")
        print(f"若確認剩餘額度 > {THRESHOLD}%，請執行: echo 80 > current_quota.tmp 以強制繼續。")
        sys.exit(0) # 預設不中斷，等待手動輸入或由 SOP 第 4 條決定

if __name__ == "__main__":
    main()
