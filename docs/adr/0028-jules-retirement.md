# ADR-0028：Google Jules 退役與歷史保全（J1）

- Status: Accepted（USER 2026-11-01 已決定退役；本 ADR 須在正式 J1 post-main 後才生效於 repo）
- Date: 2026-11-03
- Supersedes: ADR-0019 的現行整合／啟動決策；不刪改 ADR-0019 及 ADR-0003 的歷史敘事
- Owner: B-127（J1 文件／治理、J2 程式／受管憑證）

## Context／正式來源

Google 於 2026-10-29 公告 Jules 2026-11-11 後轉為唯讀，2026-12-31 終止：
<https://jules.google/docs/changelog/2026-10-29>。
USER 2026-11-01 已決定 HH.AI_v2 退役 Jules，並於 2026-11-02 決定 G12 → uv Python → J1 → J2 的順序。

## Decision（對現行指引有約束力）

1. `jules-integration` 標記 **RETIRED／HISTORICAL ONLY**，保留原路徑、原工作流歷史文字與引用；從可執行技能索引移出。不得用任何 prompt、MCP、CLI、Bridge、session 或 PR 自動化啟用 Jules；不以其他外部代理自動接替。
2. 既有 Jules 歷史提案、ADR、批次、Git objects、bundle、11 個 Jules 歷史遠端 refs 一律維持保全。任何移動、封存、刪除或遠端 refs 變更，均須符合 G8 及 USER 逐次授權；本 ADR 不授權破壞性操作。
3. B-10／B-105 與 D-U12／13／15／16 之 **Jules 啟用或委派規劃** 已由 USER 新決定取代（SUPERSEDED，不代表歷史內容錯誤）；F-01 的索引漂移改善保持獨立工作，F-03 多代理研究保留但不可再使用 Jules 作現行途徑；B-75 過去 Jules Bridge 事故的復原與上下文保護仍有效。
4. 現行文件不得要求使用者建立、保存或重新取得 Jules API 金鑰、安裝 Jules CLI/MCP 或授權 GitHub App。USER 曾提供其本機移除觀察，但本 ADR 不宣稱已獨立查證個人帳號／外部授權撤銷。
5. **J2 明確獨立切片**：Windows Credential Manager 與 Gateway managed-credential target 之 Jules target 拒絕、相應測試、inventory 及環境契約同步另經 E24／E27 和 Windows 原生負例驗收。J1 不得宣稱 J2 已完成，不探測或輸出任何真實憑證。
6. 原始 `docs/adr/0019-jules-official-cli-and-mcp.md`、`docs/adr/0003-jules-integration-via-extension.md`、歷史操作記錄均保持原文，引用時須標明其歷史／已被取代地位。

## Consequences／驗收

- 根／技能／agents 的現行索引不得把 Jules 描述成可啟動技能；為維持既有 CHECK 4／CHECK 7 的所有追蹤檔對帳，得於明確標記 **RETIRED** 的非執行清冊保留一個歷史連結，該列絕非當前選用入口。
- `PRINCIPLES.md`、技能文件、MCP 環境指南及相關技能指引不得宣稱 Jules 是現行可調用路線；歷史、保全與 G8 例外仍可提及 Jules。
- 不變更 `scripts/check_consistency.py`、`scripts/validate_skills.py` 或 Gate 判定邏輯以求本批過關；必須用現行正式 CHECK 做退役前後的真實驗證，E27 依 B-127/J1 原授權及 D-SO 先執行複核。
