## 變更類型

- [ ] `feat` — 新功能
- [ ] `fix` — 錯誤修正
- [ ] `hotfix` — 緊急生產修復（從 `main` 分支出來）
- [ ] `test` — 補充 / 修正測試案例
- [ ] `refactor` — 重構（不影響對外行為）
- [ ] `docs` — 文件 / 規格更新
- [ ] `chore` — 依賴升級 / 設定調整

---

## 變更說明

> 這個 PR 做了什麼？為什麼需要這個改動？

（請填寫）

---

## 影響範圍

> 哪些功能 / 模組 / 路由受到影響？

- [ ] 薪資計算邏輯（`/salary`、保留金公式）
- [ ] 材料庫存（`/materials`、`/confirmation/materials`）
- [ ] 日報回報（`/report`、`/confirmation/reports`）
- [ ] 大表系統（`/bm/*`）
- [ ] 帳目流水（`/ledger/*`）
- [ ] 認證 / 授權（`/login`、`admin_required`）
- [ ] 資料模型（`models.py`）
- [ ] 設定 / 系統管理（`/settings`）
- [ ] 其他：＿＿＿＿

---

## 開發者自查清單

### 測試
- [ ] 新邏輯有對應的測試案例（unit 或 integration）
- [ ] 本地跑過 `pytest tests/` 全綠
- [ ] 若改動薪資 / 保留金公式，有更新 `test_salary.py` / `test_retention.py`
- [ ] 若改動庫存邏輯，確認不變式 `received = cumulative + remaining` 仍成立

### 安全
- [ ] 沒有新增 `eval()` / `exec()` / 直接字串拼 SQL
- [ ] 新路由已套用適當的 `@login_required` / `@admin_required`
- [ ] 沒有把敏感資訊（密碼、token）寫進 log 或 response

### 資料庫
- [ ] 若有 schema 變更，已在 `SPEC_員工日報系統_v1.0.6.md` Section 18 補上 migration SQL
- [ ] Migration 是 idempotent（重複執行不會壞）

---

## Reviewer 重點提示

> 請提醒 Reviewer 需要特別檢查哪個部分（例如：Decimal 精度、session 狀態、並發安全）

（請填寫）

---

## 相關資源

- Issue #：
- SPEC 章節：
- 設計決策說明：
