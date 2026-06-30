# 員工日報回報系統

> 版本: v1.0.1 | 更新日期: 2026-06-30 | 狀態: 生產環境運行中

工程隊員工每日工項回報、薪資計算與材料管理的一體化 Web 應用程式。

---

## 技術棧

| 層次 | 技術 |
|------|------|
| 後端框架 | Python 3.11 + Flask 3.x |
| ORM | Flask-SQLAlchemy 3.x |
| 認證 | Flask-Login |
| 資料庫（本地） | SQLite |
| 資料庫（生產） | PostgreSQL (Supabase) |
| 部署 | Railway（GitHub push 自動部署）|
| 文件匯出 | openpyxl（Excel）、reportlab（PDF）、python-docx（Word）|
| 前端 | Bootstrap 5.3、Bootstrap Icons 1.11 |

---

## 快速啟動（本地開發）

```bash
# 1. 建立虛擬環境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. 安裝依賴
pip install -r requirements.txt

# 3. 啟動（SQLite 自動建立於 instance/app.db）
python app.py

# 4. 填入測試資料（可選）
python seed_test_data.py
```

預設開啟於 `http://127.0.0.1:5000`

---

## 測試帳號（seed_test_data.py 執行後）

| 角色 | 帳號 | 密碼 |
|------|------|------|
| ADMIN | Root | admin123 |
| USER | 測試用戶1~16, 19~20 | user01pass ~ user20pass |
| USER（停用） | 測試用戶17, 18 | user17pass / user18pass |

---

## 環境變數

| 變數 | 說明 | 預設值 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 連線字串（生產環境）| 未設定時使用 SQLite |
| `SECRET_KEY` | Flask session 密鑰 | `dev-secret-key`（**生產環境必須修改**）|

---

## 目錄結構

```
yc/
├── app.py                        # 主應用程式（路由、業務邏輯、匯出）
├── models.py                     # SQLAlchemy 資料模型
├── requirements.txt              # Python 依賴
├── seed_test_data.py             # 測試資料填充腳本
├── templates/
│   ├── base.html                 # 共用版型（側欄、topbar、loading overlay）
│   ├── login.html                # 登入頁
│   ├── report.html               # 回報頁面
│   ├── history.html              # 歷史紀錄
│   ├── materials.html            # 材料管理
│   ├── audit.html                # 變動紀錄
│   ├── settings.html             # 系統設定（ADMIN）
│   ├── salary.html               # 薪資計算（ADMIN）
│   ├── summary.html              # 統計報表（ADMIN）
│   ├── confirmation.html         # 確認頁面（ADMIN）
│   ├── personal_stats.html       # 個人統計
│   └── _pagination.html          # 分頁元件（macro）
├── SPEC_員工日報系統_v1.0.1.md   # 系統規格書（詳細）
├── report_flowchart.md           # 回報功能流程圖
├── security_report.md            # 安全性報告
├── scalability_report.md         # 擴展性報告
└── instance/
    └── app.db                    # 本地 SQLite 資料庫
```

---

## 功能總覽

### USER 可用功能
- **回報頁面** — 每日工項數量輸入（21 個欄位），已確認回報鎖定無法修改
- **歷史紀錄** — 查詢 / 編輯（未確認）/ 刪除自己的回報
- **剩餘材料** — 查看庫存、提交 / 取消材料申請
- **變動紀錄** — 查看所有系統操作日誌（唯讀）
- **個人統計** — 工項統計、薪資試算（含稅務/勞健保扣除模擬）

### ADMIN 追加功能
- **統計報表** — 跨帳戶工項統計、Excel/PDF 匯出
- **確認頁面** — 批次確認 / 駁回回報、審核材料申請
- **薪資計算** — 含固定薪資/勞健保/保留金/稅務，Excel/PDF/薪轉單（Word）匯出
- **設定** — 帳戶管理（新增/停用/密碼重設）、工項單價、稅率/保留金設定、材料管理

---

## 薪資計算邏輯摘要

```
最終薪資 = 工項薪資毛額
         - 保留金（上限 RETENTION_CAP = 5000，年度累計）
         + 固定薪資（10號發薪時）
         - 勞健保扣除（10號發薪時，已投保帳戶）
         - 稅務支出（未投保且非免稅帳戶，= 毛額 × 稅率%）
```

---

## 部署

推送到 `main` 分支後，Railway 自動觸發部署。資料庫 schema migration 在 `_init_db()` 啟動時自動完成（冪等 ALTER TABLE + CREATE INDEX IF NOT EXISTS）。

```bash
git add . && git commit -m "feat: ..." && git push origin main
```

---

## 相關文件

- [系統規格書 v1.0.1](SPEC_員工日報系統_v1.0.1.md) — 完整系統設計與業務邏輯
- [回報流程圖](report_flowchart.md) — 回報功能 Mermaid 流程圖
- [安全性報告](security_report.md) — 已知安全問題與建議
- [擴展性報告](scalability_report.md) — 效能瓶頸與未來擴展方向
