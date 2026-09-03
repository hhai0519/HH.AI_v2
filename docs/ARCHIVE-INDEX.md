# 歸檔索引

> **這是索引，不是歸檔區本身。**
> 本專案的歸檔機制散在五個層級，本檔的作用是回答
> 「某某東西被歸檔到哪裡了、要去哪裡找」。
>
> 新增或變更任何歸檔機制時，必須同步更新本檔。

---

## 一、查詢入口

| 你在找什麼 | 去哪裡找 |
|---|---|
| 某個**技能**為什麼不見了 | `skills/deprecated/README.md`；規則見 `.agents/rules/skill-engineering-guardrails.md` §4 |
| 某份 **SOP** 去了哪裡 | `SOP/README.md`「已淘汰與已轉換的 SOP 去向紀錄」 |
| 某個 **ADR 的規範內容**被搬到哪 | 該 ADR 末尾的「分層搬移」紀錄；原則見 `PRINCIPLES.md` §1、§3.3 |
| 某個**任務**做完後去哪了 | `docs/TASKBOARD.md` 封存區；規則見 `.claude/rules/auditor-protocol.md` §10.4 |
| 某個 **Jules 分支**為什麼沒合併 | `docs/refactor-backlog.md`「三之二、Jules 自動化修正分支處理狀態」 |
| 舊 repo 的某個檔案**為什麼不遷移** | `docs/refactor-backlog.md` §二 E、F 節 |
| 某個**決定**當初為什麼那樣做 | `docs/adr/`；重構過程的判斷見 `docs/refactor-backlog.md` 編號項目 |

---

## 二、五個歸檔層級

| 層級 | 機制 | 規則位置 | 歸檔區位置 |
|---|---|---|---|
| **技能** | 統一歸檔與差異化刪除政策（情況 A 下架整個技能／情況 B 清理內部失效內容） | `.agents/rules/skill-engineering-guardrails.md` §4 | `skills/deprecated/` |
| **SOP** | 淘汰與轉換的去向紀錄 | `SOP/README.md` | 無實體歸檔區，以紀錄替代 |
| **ADR** | 只追加不改寫；規範搬走時原地留指向、檔尾追加搬移紀錄 | `PRINCIPLES.md` §3.3、範本見 `docs/adr/0018-vendored-external-assets.md` | ADR 原檔保留 |
| **任務** | 五態流轉，`可封存` 需使用者確認後移入封存區 | `.claude/rules/auditor-protocol.md` §10.3、§10.4 | `docs/TASKBOARD.md` 封存區 |
| **分支** | 不採用的分支保留在遠端，不刪除 | `docs/refactor-backlog.md` 三之二 | GitHub 遠端分支 |

---

## 三、共通原則

1. **歸檔不是刪除。** 五個層級都採「保留可查」，不做物理刪除。
   唯一例外是 guardrails §4 情況 B——清理技能檔案**內部**的失效內容，
   那是修正不是歸檔。
2. **歸檔要留去向。** 只把東西移走而不記錄去向，等同遺失。
   `SOP/README.md` 開頭那句「為避免未來查找文件時以為資料遺失」
   就是這條原則的表述。
3. **去向紀錄要逐項，不能概括。** 2026-09-01 曾發生
   `SOP_00_Skill_Lifecycle_Management.md` 的去向被寫成
   「已拆分為 ADR-0013 與兩份 rules」，實際上 §一至§四從未遷移也未淘汰，
   概括式的記錄反而掩蓋了遺失。

---

## 四、已知缺口

| 缺口 | 說明 | 追蹤 |
|---|---|---|
| `skills/deprecated/` 是空的 | `refactor-backlog.md` §F 列了一批「確定淘汰不遷移」的項目，但那些項目的淘汰紀錄只在 backlog，沒有進任何歸檔區 | `TASKBOARD.md` E-05 |
| 計畫書（Execution Plans）無保留規範 | 舊 repo `Data/TODO.md` 有一項未完成待辦要求建立儲存、命名與長期保留標準並寫入 SOP，至今未做 | `TASKBOARD.md` G-02 |
