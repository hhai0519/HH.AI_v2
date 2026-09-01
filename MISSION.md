# HH.AI v2 — Mission

## 使命

Evolve HH.AI into a well-engineered, composable skill system.
Not by preserving the past as-is.
But by preserving proven knowledge (especially tested financial-calculation logic)
while redesigning how that knowledge is organized.

演進,不是搬家。保留有價值的知識(尤其是已驗證的財務計算邏輯本身),
重新設計的是「知識怎麼被組織」,不是把能動的邏輯重寫一遍去冒不必要的風險。

## 三個優先序

1. **品質優先於速度**——遷移過程中,寧可一批做得慢也做得對，不要求快。
2. **保留已驗證邏輯，重構組織方式**——技術指標公式、財務計算腳本這類已經在
   生產環境跑過、驗證過的邏輯，原則上原封不動搬進 `scripts/`；重構的對象是
   資料夾結構、SKILL.md 格式、觸發詞、README 索引，不是重寫演算法本身。
3. **知識保存優於檔案保存**——舊技能裡有價值的判斷邏輯、SOP、觸發情境，
   要在遷移時被完整理解並保留（即使換了檔案格式），而不是逐字複製整份檔案。

## 完成的定義

不是看搬了幾個檔案、幾份 Markdown。是看：
- 每個技能是否只做一件事、職責清楚
- 重複知識是否都被抽成共用內容，而不是散落在多個技能裡各寫一次
- 新增一個技能時，是否能直接照著 `AGENTS.md` 的規範走，不用重新思考格式
- `scripts/validate_skills.py` 是否通過

決策與協作原則見 [PRINCIPLES.md](./PRINCIPLES.md)，詳細架構規範見 [AGENTS.md](./AGENTS.md)。
