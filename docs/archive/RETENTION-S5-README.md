# S5 首批封存原文／證據保留索引

這裡不是 Windows `.git` retention engine；只保存 repo 原始文件的逐位元組快照，不搬移或刪除原檔。封存文字不構成最新狀態權威。

- 原始文件：`docs/ops/q2-draft-precheck.md`（Base `9191cb4d072ec9b05d10d9a5204982ad329de0c0`）。
- 歷史原文快照：`RETENTION-S5-Q2-DRAFT-PRE-9191cb4.md`；Git blob `14884f63bb974907f80a85541d349866bc25f610`，SHA-256 `233fc184268f7202c229c04c90d1b279184935ecfcbaff41384d39c208663a4f`，原文 3683 bytes。原始文件仍留在原位。
- 內容 manifest：`RETENTION-S5-MANIFEST-9191cb4.json`。提交後須核對 Git blob、manifest SHA 與 archive 位元組；不得覆寫此快照與 manifest。未建立跨批自動防止修改的驗證器（B-59、B-120 尚 OPEN）。
- 外部 USER `.git` receipt、prompt／control／state-plan、Downloads bundle、IDE 設定截圖**沒有被本批複製**。Manifest 中的 SHA 是 KEEP 來源索引，不是位元組歸檔完成證據。沒有完整來源的項目是 UNKNOWN／KEEP，禁止刪除。
- Retention R2 §§5.2–5.4 的 archive ZIP、專用維護鎖、write-ahead journal、168h UTC 隔離、再次 post-main、使用者單次授權等都尚未實作；需要另批 E24／E27 與 USER 決裁。

**USER 常設決定（2026-10-17）**：本批只在既有 `docs/archive/` 新增 `RETENTION-S5-` 開頭的三靜態檔（不新增資料夾；canonical runner 不建立新資料夾，原規劃的 `docs/archive/retention/` 依 USER 2026-10-17 決定改放），不含不可變機械守衛；日後增檔須 USER 另行決定或依正式容量政策，原始資料不移動、不刪除。
