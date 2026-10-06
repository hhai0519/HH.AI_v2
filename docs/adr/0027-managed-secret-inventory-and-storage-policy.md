# ADR-0027: 受管金鑰盤點與儲存政策 (Managed Secret Inventory & Storage Policy)

- Status: Accepted Architecture Decision / Specification Candidate Pending External Macro Audit
- Date: 2026-10-05
- Decision Owner: 使用者 HH（D-SEC-1～6）& External Macro Auditor

## Context

使用者已於看板 B-110 完成 D-SEC-1～6 之架構決策。本專案既有的 ADR-0026 僅涵蓋 Channel Gateway 之 Windows Credential Manager 機密提供者與讀取邊界，尚未推廣至專案全域受管金鑰。為收斂全專案受管金鑰之盤點與儲存政策，由任務切片 SEC-01 負責專案層級規格定稿與非機密盤點。

## 三態區分

本政策之生命週期嚴格區分三個狀態：

1. **現行行為（Current Behavior）**：
   - Channel Gateway 已具備 ADR-0026 定義之 Windows Credential Manager 精確查找唯讀提供者，但寫入器、一鍵配置與 UTF-16LE 契約尚未實作。
   - MCP 工具金鑰（包含 Jules、Notion 等）現行由 Windows 使用者層級環境變數提供（見 `docs/mcp-environment-guide.md`）。
   - GitHub API 存取現行透過 Windows 使用者層級環境變數中的 Personal Access Token（PAT）提供。
   - 使用者機器上的既有 credential 現況為 UNKNOWN，不可稱零遷移成本。

2. **已定稿但未實作之目標（Decided but Not Implemented Target）**：
   - 受管獨立金鑰以 Windows Credential Manager Generic Credential 儲存，採精確 TargetName 查找與 UTF-16LE blob 契約。
   - MCP 金鑰由 MCP launcher 於子程序啟動時注入環境變數，消除使用者層級持久環境變數依賴。
   - GitHub API 權威授權委派由 GitHub CLI（`gh auth token`）動態取得，不由 HH.AI_v2 儲存。
   - SEC-02、SEC-03、SEC-04 之目標行為在各自實作並經驗收前均未生效。

3. **遷移條件（Migration Conditions）**：
   - 各元件之目標儲存行為僅在對應切片（SEC-02、SEC-03、SEC-04）實作完成、通過驗證並經使用者本機確認後，方得切換生效。
   - 在唯讀 doctor 檢驗通過且使用者本機確認前，嚴禁擅自清理或修改既有環境變數與儲存配置。

## Decision

### 1. 儲存類別與衍生設定區分

專案定義四種儲存類別，其名稱與語意與 `docs/governance/secret-inventory.json` 之 `storage_classes` 完全一致：

- **CREDMAN_GENERIC**：由 HH.AI_v2 於 Windows Credential Manager 管理之 Generic Credential，具備本機持久化（local-machine persistence）、精確 TargetName 查找與 UTF-16LE blob 契約（D-SEC-1, D-SEC-2）。
- **GH_CLI_DELEGATED**：HH.AI_v2 不儲存；於執行期透過瀏覽器完成 `gh auth login` 授權後，由 `gh auth token` 命令動態取得（D-SEC-4）。
- **EXTERNAL_TOOL_MANAGED**：僅登錄；由原工具管理，HH.AI_v2 不讀取、不寫入、不遷移（D-SEC-3）。
- **DERIVED_AT_LAUNCH**：不單獨儲存；於啟動時由另一盤點登錄項目衍生產生。

獨立金鑰（`INDEPENDENT_SECRET`）與衍生設定（`DERIVED_CONFIG`）嚴格區分：衍生設定（例如包含 Notion 憑證之 OpenAPI MCP 標頭）於啟動時動態組裝，不得另行儲存於 Windows Credential Manager 或任何組態檔案中，避免同一憑證於系統中重複保存。

### 2. 命名空間與元件劃分

受管金鑰 TargetName 命名空間沿用 D-SEC-1 規範：`HH.AI_v2/<component>/v1/<name>`。
- **channel-gateway**：依 ADR-0026 規範，涵蓋 Telegram、未來 LINE 管道及 local-api HMAC 密鑰。
- **mcp-launcher**：新增 `mcp-launcher` 元件命名空間，涵蓋 Jules（`HH.AI_v2/mcp-launcher/v1/jules/api-key`）與 Notion（`HH.AI_v2/mcp-launcher/v1/notion/api-token`）。
- **gemini-api-key**：待 SEC-04 識別其具體使用端元件後，再行定案其組件名稱與 TargetName。

### 3. 憑證型態、持久化與精確查找

所有受管 Generic Credential 均採 `CRED_TYPE_GENERIC` 與 `CRED_PERSIST_LOCAL_MACHINE`（D-SEC-1）。延續 ADR-0026 原則，存取一律依精確 TargetName 查找，嚴格零列舉（Zero Credential Enumeration），禁止遍歷或列舉 Credential Manager 項目。

### 4. Blob 格式契約

依據 D-SEC-2，Generic Credential blob 格式由應用程式自行定義，Windows API 本身不強制要求 UTF-16LE 編碼。HH.AI_v2 選定 UTF-16LE 作為專案 blob 格式契約，以確保與 Windows 內建認證管理員使用者介面、`cmdkey` 及常見 keyring 工具互通。
在 SEC-02 實作時，writer、reader、provider 與 consumer 必須一起變更，由 provider 邊界轉換為使用端所需之位元組（例如現有 Gateway 使用端為 UTF-8 Buffer）。SEC-02 實作時不得假設既有 blob 編碼可單靠位元組無歧義推斷。

### 5. 納管範圍與僅登錄項目

依據 D-SEC-3，納管範圍包含 Channel Gateway、MCP launcher（Jules、Notion、OpenAPI 衍生標頭）、GitHub 委派授權及 Gemini API 金鑰。Git Credential Manager（GCM）與 IDE SecretStorage 屬僅登錄項目（`EXTERNAL_TOOL_MANAGED`），由原工具自行管理，HH.AI_v2 絕不讀取、不寫入、不遷移。

### 6. GitHub 委派授權模式

依據 D-SEC-4，GitHub API 存取採 `gh auth login` 瀏覽器授權。執行期 launcher 透過 `gh auth token` 命令動態取得權限權杖傳入子程序環境變數，HH.AI_v2 不自行保存 GitHub Token。同時記錄該委派模式可能帶有較廣權限範圍之風險。

### 7. 零備份值原則與安全防護

依據 D-SEC-5，專案貫徹零備份值原則，版本庫與任何中繼設定嚴格禁止備份真實金鑰值；環境重建時由使用者本機重新輸入或向服務商重新核發。執行者（Agent）在任何流程中嚴禁經手真實金鑰值。同時評估 Windows 同使用者 generic credential 之存取殘留風險，並以 B-108 攔截規則作為縱深防禦。

### 8. 實作順序

依據 D-SEC-6，實作與遷移順序如下：
SEC-01 → SEC-02 → SEC-03 → SEC-04 → 有界 Gateway 行為修正 → TG-MVP-15 → TG-CUT。
其中 SEC-05 舊版殘留清理維持 NONBLOCKING 狀態，排至 E-01／TG-CUT，不阻擋 TG-MVP-15。

### 9. 非機密受管金鑰盤點清單

`docs/governance/secret-inventory.json` 為受管金鑰 TargetName 與分類之非機密權威清單。該檔案僅包含非機密中繼資料，絕對不得含有任何金鑰值、長度、雜湊、前綴或遮蔽片段。檔案中之 `format_class` 僅為分類標籤，不構成「所有秘密皆可辨識」之宣稱，偵測覆蓋由 SEC-01 後續增量另行驗證。

## Consequences

1. 確立受管金鑰統一政策；目標為於 SEC-02～04 實作並經驗收後，消除分散存放於環境變數或設定檔之長期風險（實作與驗收前未生效）。
2. 達成獨立金鑰與衍生設定之解耦，杜絕同一憑證多處重複儲存。
3. 明確區隔三態，確保未經驗收之目標行為不被提前視為已生效。
4. 排除 GCM 與 IDE SecretStorage，降低對外部工具既有安全鏈路之干擾。
5. 委派 GitHub CLI 管理權杖降低儲存責任，但需持續注意 CLI 權限範圍可能過廣之特性。

## 附錄 A：人類可讀對照（非機密）

| ID | 類型 | 儲存類別 | TargetName | 舊名稱 | 目標狀態 | 遷移 owner |
|---|---|---|---|---|---|---|
| `gateway-telegram-bot-token` | INDEPENDENT_SECRET | CREDMAN_GENERIC | `HH.AI_v2/channel-gateway/v1/telegram/<encoded-account-id>/bot-token` | — | DECIDED_NOT_IMPLEMENTED | SEC-02、SEC-03 |
| `gateway-line-channel-access-token` | INDEPENDENT_SECRET | CREDMAN_GENERIC | `HH.AI_v2/channel-gateway/v1/line/<encoded-account-id>/channel-access-token` | — | DECIDED_NOT_IMPLEMENTED | future LINE slice |
| `gateway-line-channel-secret` | INDEPENDENT_SECRET | CREDMAN_GENERIC | `HH.AI_v2/channel-gateway/v1/line/<encoded-account-id>/channel-secret` | — | DECIDED_NOT_IMPLEMENTED | future LINE slice |
| `gateway-local-api-hmac` | INDEPENDENT_SECRET | CREDMAN_GENERIC | `HH.AI_v2/channel-gateway/v1/local-api/hmac` | — | DECIDED_NOT_IMPLEMENTED | SEC-02、SEC-03 |
| `mcp-jules-api-key` | INDEPENDENT_SECRET | CREDMAN_GENERIC | `HH.AI_v2/mcp-launcher/v1/jules/api-key` | `JULES_API_KEY` | DECIDED_NOT_IMPLEMENTED | SEC-04 |
| `mcp-notion-api-token` | INDEPENDENT_SECRET | CREDMAN_GENERIC | `HH.AI_v2/mcp-launcher/v1/notion/api-token` | `NOTION_API_TOKEN`、`NOTION_TOKEN` | DECIDED_NOT_IMPLEMENTED | SEC-04、SEC-05 |
| `mcp-notion-openapi-headers` | DERIVED_CONFIG | DERIVED_AT_LAUNCH | — | `OPENAPI_MCP_HEADERS` | DECIDED_NOT_IMPLEMENTED | SEC-04 |
| `github-delegated-token` | INDEPENDENT_SECRET | GH_CLI_DELEGATED | — | `GITHUB_PERSONAL_ACCESS_TOKEN`、`GITHUB_TOKEN` | DECIDED_NOT_IMPLEMENTED | SEC-04、SEC-05 |
| `gemini-api-key` | INDEPENDENT_SECRET | CREDMAN_GENERIC | — | `GEMINI_API_KEY` | TARGET_PENDING_CONSUMER_IDENTIFICATION | SEC-04 |
| `git-credential-manager` | REGISTERED_ONLY | EXTERNAL_TOOL_MANAGED | — | — | NOT_MANAGED_BY_HH_AI_V2 | — |
| `ide-secret-storage` | REGISTERED_ONLY | EXTERNAL_TOOL_MANAGED | — | — | NOT_MANAGED_BY_HH_AI_V2 | — |

註：「目標狀態」欄取自 secret-inventory.json 之 target_status；現行實作與環境狀態以該檔之 current_state 欄為準（例如 Channel Gateway 已有 ADR-0026 之精確查找讀取提供者）。

## 2026-10-05 補充（SEC-01 INC-2）：偵測覆蓋矩陣

本節依歷史更正慣例新增，上方原文除 Consequences 第 1 點之語氣更正外保留不改。受管金鑰格式類別與偵測器之對應，以 `docs/governance/secret-detection-matrix.json` 為非機密權威清單：標為 REQUIRED 之格式類別，須同時被 `scripts/secret_scan.py` 之對應偵測器與 `shared/dlpSanitizer.js` 之對應標籤偵測，並由 `scripts/tests/test_secret_detection_matrix.py` 以合成樣本與誤報反例驗證；無穩定前綴、格式未確立或僅登錄之類別明列為不可依格式偵測或不適用，不構成「所有秘密皆可辨識」之宣稱。scanner 與 DLP 各自保留其通用規則。Google API Key 之支援格式定為「AIza 後接恰好 35 個 [0-9A-Za-z_-] 字元，且前後不緊鄰同集合字元」；DLP 既有之 AIzaSy 規則較寬而保留。覆蓋結論另受 B-113 所載限制：scanner 遇無法讀取之內容時略過，且含 TEST 等 placeholder 字樣之 token 被豁免。

## 2026-10-05 補充（SEC-01 INC-3）：受管金鑰持久存放指引守衛

本節依歷史更正慣例新增，上方原文保留不改。`scripts/check_consistency.py` 之 CHECK 27 掃描有效技能文字（`skills/` 下追蹤之 Markdown，排除 `skills/deprecated/`）與 `docs/mcp-environment-guide.md`，以 Markdown 標題區塊為判定單位：同一區塊內同時出現持久存放指示（使用者層級環境變數、`SetEnvironmentVariable`、`setx`，或 `.env` 檔搭配存放動詞）與受管金鑰名稱或憑證字詞者即為命中。既存之過渡指引與現況描述須於 `docs/governance/secret-guidance-exceptions.json` 逐區塊列管，每筆例外綁定區塊全文 SHA-256、一對一對應、owner 須為看板上未完成之任務；區塊改動、owner 結案或例外失配均使 CHECK 失敗。依 ADR-0027 存入 Windows Credential Manager 之指令不屬持久存放指示；子程序執行期環境變數注入亦不構成命中。輸入缺失、格式不符、Git 列舉或讀檔失敗一律判定失敗。

## 2026-10-06 補充（B-113）：scanner 失效關閉與 placeholder 豁免收斂

本節依歷史更正慣例新增，上方原文保留不改。`scripts/secret_scan.py` 於 tracked 或 staged 模式遇應掃描而無法讀取之內容（含 index 項目缺失、未合併或 blob 讀取失敗）一律以 SCAN_READ_ERROR 判定失敗；僅工作樹已刪除之檔案、gitlink 與暫存區刪除不屬掃描對象。placeholder 字樣僅在值中以非英數字元或首尾為界之獨立片段出現時豁免，夾於 token 英數主體中之字樣不再豁免，亦不再依同行其他位置之標記豁免。2026-10-05 SEC-01 INC-2 補充所載之 B-113 限制自此解除；含獨立 placeholder 片段之 token 仍不在覆蓋結論內。
