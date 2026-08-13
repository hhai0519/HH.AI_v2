<!-- Parent: ../../AGENTS.md -->

# skills/meta

## Purpose

造技能的技能、治理類（skill-creator、setup-hhai-skills 等）。這裡的技能通常是
low-frequency、one-shot 性質，或是用來維護技能庫本身的工具。

## For AI Agents

- 這裡的技能改動時，優先參考 `templates/SKILL.md.template`，確保它產生出來的
  新技能符合根目錄 `AGENTS.md` 的規範。
- `setup-hhai-skills` 是一次性專案初始化技能，通常是 user-invoked，不需要
  model 自主觸發。
