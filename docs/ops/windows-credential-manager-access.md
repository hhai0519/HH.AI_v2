# Windows Credential Manager 存取原語

本檔描述 SEC-02 INC-2 候選介面，尚待獨立審查。沒有使用者本機設定、遷移、輪替或服務啟用授權。
儲存政策為 ADR-0027；既有 Gateway 讀取契約為 ADR-0026。受管 metadata 權威為 `docs/governance/secret-inventory.json`，其中不保存金鑰值。

## 介面

`core/managed-credential-target.js` 提供 `resolveManagedTarget({ inventoryId, accountId })`；`core/windows-credential-manager-access.js` 提供 `WindowsCredentialManagerAccess` 與 `CredentialManagerError`。實體路徑均位於 `runtime/channel-gateway/`。

| 方法 | 輸入 | 回傳 |
|---|---|---|
| `isPresent(ref)` | 受管 inventory reference | boolean |
| `createNew(ref, utf16leBlob)` | reference、UTF-16LE Buffer | 成功為 true；已有項目則拒絕 |
| `deleteExact(ref)` | reference | 刪除成功為 true；原已不存在為 false |

ref 只有 `inventoryId` 與選用的 `accountId`；不接受呼叫端指定的 TargetName。帳號目標沿用 SecretRef 衍生規則，固定目標採明列常數。所有 native 操作均以同一個精確 TargetName、CRED_TYPE_GENERIC 查詢，沒有列舉 API。

## 白名單

| inventoryId | TargetName 來源 |
|---|---|
| gateway-telegram-bot-token | ADR-0026 的 Telegram SecretRef |
| gateway-line-channel-access-token | ADR-0026 的 LINE access-token SecretRef |
| gateway-line-channel-secret | ADR-0026 的 LINE secret SecretRef |
| gateway-local-api-hmac | ADR-0026 的固定 HMAC TargetName |
| mcp-jules-api-key | HH.AI_v2/mcp-launcher/v1/jules/api-key |
| mcp-notion-api-token | HH.AI_v2/mcp-launcher/v1/notion/api-token |

未定 TargetName 的 Gemini、GitHub 委派、衍生標頭、GCM 與 IDE SecretStorage 一律拒絕。支援命名不代表 LINE 或 MCP consumer 已實作或遷移。原 Gateway reader／provider 與消費端介面保持原契約。

## 新建與既有項目

createNew 在受管互斥區內先查精確存在性；查得已有項目即拒絕，不讀取或推測舊 blob 編碼、不自動刪除重建、不提供 overwrite 或 rotate 選項。native 新建使用 CRED_TYPE_GENERIC、CRED_PERSIST_LOCAL_MACHINE 與 flags=0。
Win32 CredWriteW 本身可以取代同 TargetName／Type 的既有項目，並非原子 create-if-absent。受管互斥鎖只序列化遵循同一協定的呼叫者；不約束外部程式或 Credential Manager 使用者介面，不宣稱消除所有外部競爭。使用者本機設定與遷移的操作前提由 SEC-03 另行定稿，本批不執行。
Windows TargetName 不分大小寫；互斥識別必須對同一 TargetName 的大小寫變體一致，且區分 Windows 使用者。互斥鎖不持久保存金鑰或建立磁碟鎖檔。
WaitOne 回報 abandoned mutex 時已取得擁有權；本介面仍失敗關閉，釋放擁有權一次、Dispose 一次，不進行 native credential 操作，exit 1 映射 PROVIDER_UNAVAILABLE，不重試。busy 未取得擁有權時只 Dispose，不 ReleaseMutex。
deleteExact 是獨立原語，不由 createNew 自動呼叫；未來使用者操作的確認流程留 SEC-03。本批只准刪除測試自行擁有的合成項目。

## 編碼與生命週期

createNew 借用呼叫端 UTF-16LE Buffer，不修改該 Buffer；呼叫端負責歸零。內部複本、驗證暫存與 unmanaged blob 由各自 owner 在成功及失敗路徑 best-effort 歸零後釋放。
blob 不含 BOM、NUL 或終止字元；必須是完整 Unicode scalar sequence、非空、偶數位元組，最大 2560 位元組。不得截斷、猜編碼或以 UTF-8 blob fallback。Gateway provider 仍將讀得的 UTF-16LE blob 轉為 fresh UTF-8 Buffer，消費端負責其生命週期。
presence 不複製、不解碼、不輸出 blob。CredReadW 取得的指標由成功取得該指標的 owner exactly once CredFree；寫入用的 HGlobal 由配置者 exactly once FreeHGlobal，不能交給 CredFree。
timeout 為 60000ms 上限，不增加重試。子程序被強制終止時，不宣稱 finally 或歸零一定執行；OS 資源隨程序終止回收，持久 credential 的操作結果仍可能未知，不自行反覆寫入或刪除。

## 輸出與錯誤

native stdout 僅為 PRESENT、ABSENT、CREATED 或 DELETED；wrapper 依操作嚴格配對，拒絕其他輸出。原始 stdout／stderr、參數、blob、值、長度、值雜湊與機敏片段不得進入錯誤或日誌。
固定錯誤碼為 INVALID_SECRET_REFERENCE、UNSUPPORTED_PLATFORM、PROVIDER_UNAVAILABLE、PROVIDER_PROTOCOL_ERROR、PROVIDER_ACCESS_DENIED、CREDENTIAL_ALREADY_EXISTS、CREDENTIAL_BUSY、SECRET_ENCODING_INVALID。
秘密只經捕獲的 binary stdin 傳入，不能出現在命令列、環境、檔案或 JSON；非機密 reference 經 argument array 傳遞，shell=false、NoProfile、NonInteractive，子程序只取得六個既有非機密環境鍵。

## 驗證與尚未啟用範圍

跨平台測試涵蓋白名單、編碼、協定拒絕、borrowed Buffer 與內部複本的歸零、timeout／spawn failure／非零結果；Windows live 測試只使用當次隨機 GUID 帳號衍生的合成目標，初始確認不存在，最後依 owner 狀態清理。
同一 live fixture 驗證新建後可由既有 Gateway provider 讀回、第二次新建拒絕且原合成值不變、存在性、刪除與原已不存在。另驗證 native 取得後失敗的清理與互斥拒絕。非 Windows 分支只驗證 UNSUPPORTED_PLATFORM，不冒稱 native live 已測。
INC-1-F3 的轉碼暫存 Buffer 測試需同時涵蓋成功與部分轉碼後失敗；不能以原始 payload 歸零測試替代。
此批不新增批次讀取 API、timeout／retry 政策、真實金鑰探測、初始化入口、MCP launcher、LINE adapter 或使用者層級環境變數清理。
