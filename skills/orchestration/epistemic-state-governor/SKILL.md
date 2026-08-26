---
name: epistemic-state-governor
description: "認知狀態管制官。負責監控整個 Swarm 的推演健康度。實作 SMARt 模型，作為系統的自主性控制閥。能動態撤銷 Agent 的外部輸出權限，強制系統進行內部反思或尋求人類協助，徹底防堵幻覺擴散。"
---
> 協同邊界說明：本技能負責監控整個 Swarm 的推演健康度（安全與狀態管控），而 `devops-engineer` 負責 CI/CD、伺服器管理等實際基礎設施操作。兩者為分工非取代關係。

# Epistemic State Governor

## 功能概述
本技能確保系統「在不知道答案時會停下來，而不是亂猜」，是系統安全的最後防線。

## 實作邏輯 (Implementation Logic)
1. **SMARt 狀態機執行**: 嚴格管控 Agent 處於四種狀態之一：Stable (S), Meta-cognitive (M), Assisted (A), Regulated (Rt)。
2. **Epistemic Drift 偵測**: 監控 Agent 的 Chain-of-Thought 熵值、檢索衝突或多 Agent 意見分歧。
3. **強制介入 (Revocation)**: 當偵測到高度不確定性，立即撤銷 Stable 狀態的輸出權限，將系統切換至 M (要求重想) 或 A (要求其他 Agent 覆核)。
4. **Human-in-the-loop 升級**: 若內部機制無法解決衝突，強制進入 Rt 狀態，暫停執行並等待使用者手動批准。