# 批次規格區（Batch Spec Lifecycle）

> 本目錄存放每一批的**正式執行契約**。
> 規格格式的說明見 `scripts/batch_spec_example.txt`，本檔只規範生命週期。
>
> 規則本體在 `.claude/rules/auditor-protocol.md` §6.1 第 21 項，
> 執行者側的對應規則在 `.agents/rules/role-boundaries.md` §6，
> 機械守衛是 `scripts/check_consistency.py` 的 CHECK 17。

---

## 一、為什麼規格必須進 repo

規格若只存在於對話或 `/tmp`：

- CI 取不到，無法重放
- 下一個接手者只能靠人記得
- 「模擬的對象」「送出的文字」「執行者套用的文字」三者沒有共同來源

依 `PRINCIPLES.md` §2.8，只能靠人記得的東西視為尚未生效。
規格進 repo 之後，三者在結構上不可能不一致——
CHECK 17 從 parent commit 重放規格並與實際 commit 逐位元比對。

---

## 二、命名

```
docs/batches/<base-hash>-<slug>.spec.txt
```

- `<base-hash>`：本批的 base commit 短 hash（7 碼），
  必須等於規格內 `HEAD:` 欄位，也必須等於本 commit 的 parent。
  **檔名與欄位互為交叉檢查**，兩者不符即代表規格取錯基準。
- `<slug>`：小寫英數與連字號，描述本批做什麼。

---

## 三、一批一 commit

| 情形 | 規則 |
|---|---|
| 一般批次 | 一份規格、一個 commit。規格與該批修改在同一個 commit 內。 |
| 修正批次 | **不是同一批**。開新規格，base 為前一個 commit（即被修正的那一個）。 |
| merge commit | CHECK 17 跳過（parent 數 != 1）。本專案不使用 merge，此為防禦性條款。 |
| 沒有規格的維護 commit | 允許。CHECK 17 輸出 INFO 並跳過，不強迫產生虛假規格。 |
| 一個 commit 兩份規格 | FAIL。無法判定該重放哪一份。 |

---

## 四、CI 如何知道該重放哪一份

CHECK 17 不讀 commit message、不讀任何清單，
它問 git：**本 commit 在 `docs/batches/` 底下新增或修改了哪些 `.spec.txt`**。

```
git diff --name-only <parent> HEAD -- docs/batches/
```

零份 → 跳過；一份 → 重放；兩份以上 → FAIL。
這個對應關係沒有需要人維護的中介物，因此不會過期。

---

## 五、比對範圍

CHECK 17 同時驗三件事，缺一不可：

1. **宣告的修改是否正確重放** — 每個 MOD 目標檔案，重放結果 encode UTF-8 後
   與實際 commit 的 git blob **原始位元組**直接比對。取 blob 不經文字模式，
   否則 CRLF 與 LF 兩個不同的 blob 會被 Python 正規化成同一個字串。
   base 的比對走完整 commit OID，不使用前綴或 startswith。
2. **未宣告的修改是否存在** — `parent..HEAD` 的實際異動檔案集合，
   不得超出 `{MOD 宣告的檔案} ∪ {本規格檔} ∪ 豁免集`。
3. **豁免檔是否只被追加** — 刪除行數由 `git diff --numstat` 直接取得，
   > 0 即 FAIL。不自行解析 unified diff 的行首：內容本身就是 `---` 的那一行
   會與 diff 檔頭標記混淆，靠字首判定一定會漏。

豁免集只有兩個，且理由必須成立：

| 檔案 | 為什麼不能以 MOD 表達 |
|---|---|
| `docs/EXEC-LOG.md` | 內容是執行者自己的檢查結果，審計官寫規格時還不存在 |
| `docs/fingerprints/exec-latest.json` | 由 `scripts/fingerprint.py` 產生，另由 `--verify` 守 |

**豁免是刻意保留的缺口，不是遺漏**，登錄為 `docs/TASKBOARD.md` B-92 待觀察。

---

## 六、BOOTSTRAP 例外

規格格式目前沒有 `create_file` mode，無法表達「新建檔案」。
本機制上線的那一批必然要建立新檔，因此：

- 檔名以 `-BOOTSTRAP.spec.txt` 結尾者，CHECK 17 跳過重放並輸出 INFO。
- **全庫至多允許一份**，超過即 FAIL。
- `create_file` mode 由 `docs/TASKBOARD.md` B-90 於下一批補上，
  屆時本例外連同這一節一併移除。

**CHECK 17 的強制範圍要講精確。** 它只對「單一 parent、恰好異動一份
非 BOOTSTRAP 規格」的 commit 執行逐位元重放。以下都是設計內的合法跳過：
無規格的維護 commit、root commit 與 merge commit、BOOTSTRAP 例外。
`-BOOTSTRAP.spec.txt` 是**目前針對 spec-driven 單一 parent 批次的暫時
replay 例外**，不是「唯一能繞過 CHECK 17 的路徑」——那個講法把
設計內的不適用情形也算成漏洞了。

**因此對 BOOTSTRAP 那一批本身，不得宣稱它受 CHECK 17 保護。**
對該批而言，偏離規格不會被 CHECK 17 攔截，也不會因此讓 CI 變紅。
該批的正確性依賴 canonical apply path、動手前的錨點唯一性驗證、
範圍檢查、測試、指紋，以及 CI 對這些項目的重跑，而非逐位元重放。
逐位元重放的完整保證自本例外移除（B-90）之後的每一個正常
EXACT_SPEC 批次起生效。

**BOOTSTRAP 不是繞過「一 commit 一份規格」的後門。**
CHECK 17 先判定「本 commit 的規格是否恰好一份」，
只有恰好一份且那一份本身是 BOOTSTRAP 時才跳過重放。
「一份 BOOTSTRAP ＋ 一份普通規格」一律 FAIL——
否則那份普通規格會完全不被重放。
