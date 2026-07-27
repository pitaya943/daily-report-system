# 員工日報回報系統 — 系統規格書

> **版本**: v1.0.6
> **日期**: 2026-07-27
> **狀態**: 已實作（反映當前生產環境實際運作狀態）
> **維護工程師參考文件**

---

## 版本變更紀錄

| 版本 | 日期 | 變更摘要 |
|------|------|----------|
| v1.0.6 | 2026-07-27 | 材料庫存全面升級（code/spec/cumulative_usage/received_quantity/tab_id/is_hidden/is_quarantined/quarantine_note）；Excel 兩步驟比對與暫存區批次解決；材料分頁系統（最多10頁）；材料隱藏/顯示（ADMIN AJAX）；確認頁面批次確認/駁回（checkbox）；材料申請批次核准/駁回；歷史/大表歷史/材料庫存匯出 Excel；ADMIN 材料頁 AJAX 優化（移動排序/隱藏不重整頁面、ADMIN 跳過 all_materials 查詢）；備註截斷至 50 字 |
| v1.0.5 | 2026-07-09 | 大表（BM）用戶類型（獨立工項/計價/確認頁）；新增 bm_40_fen 工項；ADMIN 移除保留金；fixed_salary_every_period 欄位；薪資計算過濾零薪資帳戶 |
| v1.0.4 | 2026-07-09 | 南/西區分區系統；共同作業回報；工項欄位型別升級 NUMERIC(8,1)；共作只數 ceil/floor 分配；SystemConfig 批次快取 |
| v1.0.3 | 2026-07-01 | UTC+8 時間儲存；流水帳；日月報檔案庫；R2 存儲 |
| v1.0.1 | 2026-06-30 | README 更新，SPEC 初版 |
| v1.0.0 | 2026-06-01 | 系統上線 |

---

## 目錄

1. [系統概述](#1-系統概述)
2. [技術架構](#2-技術架構)
3. [安全機制](#3-安全機制)
4. [資料庫設計](#4-資料庫設計)
5. [認證與授權](#5-認證與授權)
6. [路由與頁面邏輯](#6-路由與頁面邏輯)
7. [南/西區分區系統](#7-南西區分區系統)
8. [大表（BM）用戶系統](#8-大表bm用戶系統)
9. [共同作業系統](#9-共同作業系統)
10. [薪資計算邏輯（核心業務）](#10-薪資計算邏輯核心業務)
11. [保留金系統](#11-保留金系統)
12. [匯出功能](#12-匯出功能)
13. [材料庫存管理](#13-材料庫存管理)
14. [流水帳（LedgerEntry）](#14-流水帳ledgerentry)
15. [日月報檔案庫（ReportArchive）](#15-日月報檔案庫reportarchive)
16. [Cloudflare R2 儲存](#16-cloudflare-r2-儲存)
17. [變動紀錄（Audit Log）](#17-變動紀錄audit-log)
18. [資料庫初始化與 Migration](#18-資料庫初始化與-migration)
19. [前端架構](#19-前端架構)
20. [設定系統（SystemConfig）](#20-設定系統systemconfig)
21. [效能優化機制](#21-效能優化機制)
22. [已知限制與注意事項](#22-已知限制與注意事項)

---

## 1. 系統概述

### 1.1 目的

本系統為工程隊管理工具，提供：

- 員工每日施工工項回報（瓦斯管線施工數量），**支援西區、南區、大表（BM）三套工項欄位與計價**
- **共同作業回報**：多人共同施工，只數依 ceil/floor 演算法分配
- ADMIN 確認/駁回回報紀錄（一般回報與大表回報各有獨立確認頁）
- 基於確認回報自動計算薪資（工項計價 + 固定薪資 + 保留金 + 勞健保 + 稅務）
- 停用帳戶的已確認回報仍納入薪資計算，並標註（停用）
- 材料庫存管理（分頁/隱藏/Excel 比對/暫存區）與申請流程
- 公司收支流水帳（含憑證上傳至 Cloudflare R2）
- 日月報自動/手動生成並存儲至 Cloudflare R2
- 薪資轉帳文件匯出（Excel/PDF/Word）
- 完整操作稽核日誌

### 1.2 使用者規模

- 設計容量：≤ 10 ADMIN + ≤ 75 USER（共 85 人）
- 資料量：每月約 85 × 22 = 1,870 筆回報；年度約 22,440 筆

### 1.3 應用程式入口

- `app.py`: 所有路由、業務邏輯、匯出功能、安全設定（~5,500 行）
- `models.py`: SQLAlchemy ORM 資料模型
- 啟動後自動執行 `_init_db()` 進行 schema migration

---

## 2. 技術架構

### 2.1 後端

```
Flask 3.x (Python 3.11+)
├── flask-sqlalchemy 3.x  — ORM（SQLite/PostgreSQL 雙支援）
├── flask-login           — Session-based 認證
├── flask-wtf 1.2.x       — CSRF 保護（CSRFProtect）
├── flask-limiter 3.12    — 登入速率限制（memory backend）
├── cryptography 44.x     — Fernet 對稱加密（銀行帳號）
├── werkzeug              — 密碼 pbkdf2:sha256 雜湊
├── openpyxl              — Excel 匯出/匯入
├── reportlab             — PDF 匯出
├── python-docx           — Word（薪轉單）匯出
├── boto3                 — Cloudflare R2（S3 相容）上傳/下載
└── apscheduler 3.10.4    — 定時任務（日月報自動生成）
```

### 2.2 資料庫

- **本地開發**: SQLite（`instance/app.db`）
- **生產環境**: PostgreSQL via Supabase（環境變數 `DATABASE_URL`）

### 2.3 部署

- Railway 平台，連接 GitHub `main` 分支
- `git push origin main` → 自動觸發 re-deploy
- 無 Docker，直接 Python 執行環境
- Filesystem 為 ephemeral，所有持久化檔案存於 Cloudflare R2

### 2.4 前端

- Bootstrap 5.3（CDN）+ Bootstrap Icons 1.11（CDN）
- 無 JS 框架，純 Jinja2 + 原生 JS
- 所有 POST 表單包含 CSRF hidden token（Flask-WTF 自動驗證）
- **v1.0.6 新增**：部分 ADMIN 操作改用 `fetch` AJAX（移動排序、隱藏材料），不重整頁面

### 2.5 時間處理

所有時間戳以 **UTC+8（台灣時間）** 的 naive datetime 儲存。

### 2.6 定時任務（APScheduler）

```python
scheduler = BackgroundScheduler(timezone='Asia/Taipei')
scheduler.add_job(auto_daily_report,   CronTrigger(hour=23, minute=59))
scheduler.add_job(auto_monthly_report, CronTrigger(day='last', hour=23, minute=59))
scheduler.start()
```

---

## 3. 安全機制

### 3.1 CSRF 保護

`CSRFProtect(app)` 全域啟用。所有 POST 表單第一行包含 `{{ csrf_token() }}`。AJAX `fetch` 呼叫亦在 request body 中帶入 `csrf_token`。

### 3.2 登入速率限制

`/login` 限制每 IP 10 次/分鐘（memory backend）。超出回傳 429。

### 3.3 Session 安全

```python
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=10)
app.config['SESSION_COOKIE_HTTPONLY']    = True
app.config['SESSION_COOKIE_SAMESITE']   = 'Lax'
app.config['SESSION_COOKIE_SECURE']     = not app.debug
```

### 3.4 SECRET_KEY

未設定時 fallback 至 hardcoded 字串並寫入 warning log。**生產環境必須設定 `SECRET_KEY`**。

### 3.5 銀行帳號加密

使用 `BANK_ENCRYPT_KEY` 環境變數進行 Fernet 對稱加密。未設定時明文儲存，功能不中斷。

### 3.6 HTTP 安全標頭

`X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`, `Permissions-Policy`, `Content-Security-Policy`（`script-src` 允許 `cdn.jsdelivr.net`）。

---

## 4. 資料庫設計

### 4.1 ER Diagram（文字版）

```
users ──< reports              (user_id FK + confirmed_by FK + collab_json)
users ──< material_requests    (user_id FK + reviewed_by FK)
materials ──< material_requests
users ──< audit_logs
users ──< user_retention_rates
users ──< ledger_entries       (created_by FK + payer_id FK)
users ──< report_archives      (generated_by FK)
system_config (key-value store)
```

### 4.2 users 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | 自增 ID |
| display_name | VARCHAR(50) UNIQUE | 顯示名稱（登入帳號）|
| password_hash | VARCHAR(256) | pbkdf2:sha256 |
| role | VARCHAR(10) | `'ADMIN'` 或 `'USER'` |
| zone | VARCHAR(10) | `'西區'` 或 `'南區'`；預設 `'西區'` |
| is_big_meter | BOOLEAN | True = 大表用戶 |
| is_active | BOOLEAN | False = 停用 |
| payment_method | VARCHAR(10) | `'TRANSFER'` 或 `'CASH'` |
| insurance_deduction | INTEGER | 勞健保固定扣除額（NTD）；0 = 未投保 |
| tax_exempt | BOOLEAN | True = 未投保免稅 |
| bank_account | VARCHAR(200) | Fernet 加密 token 或明文 |
| fixed_salary | INTEGER | 固定薪資（NTD）；預設 0 |
| fixed_salary_every_period | BOOLEAN | True = 每期皆發放固定薪資 |
| retention_offset | INTEGER | ADMIN 手動調整保留金累計（可負值）|
| created_at / updated_at | DATETIME | UTC+8 naive datetime |

### 4.3 reports 表

工項欄位全部為 `NUMERIC(8,1)`。詳見第 7、8 節的欄位分組。新增欄位：`collab_count INTEGER`、`collab_json TEXT`、`custom_item_name VARCHAR(100)`、`custom_item_qty NUMERIC(8,1)`、`custom_item_price INTEGER`。

### 4.4 materials 表（v1.0.6 大幅更新）

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| code | VARCHAR(50) | 材料編號（可空）|
| name | VARCHAR(100) | 材料名稱 |
| spec | VARCHAR(200) | 規格（可空）|
| unit | VARCHAR(20) | 單位 |
| cumulative_usage | NUMERIC(12,3) | 累計使用量 |
| received_quantity | NUMERIC(12,3) | 實領量（= cumulative_usage + remaining_quantity）|
| remaining_quantity | NUMERIC(12,3) | 庫存量 |
| tab_id | INTEGER | 所屬分頁 1–10；預設 1 |
| sort_order | INTEGER | 分頁內顯示排序 |
| is_hidden | BOOLEAN | True = 對 USER 隱藏（ADMIN 仍顯示，半透明）|
| is_quarantined | BOOLEAN | True = 暫存區，不出現在一般庫存列表 |
| quarantine_note | TEXT | JSON 字串，記錄比對詳情（見下方）|
| created_at / updated_at | DATETIME | UTC+8 |

**不變式（Invariant）**：`received_quantity = cumulative_usage + remaining_quantity`

每次更新庫存必須同時維護此不變式。

**quarantine_note JSON 結構**：

```json
{
  "x": "5",
  "a_cumulative": "10",
  "a_received": "15",
  "a_remaining": "5",
  "a_received_new": "20",
  "a_remaining_new": "10",
  "b_cumulative": "12",
  "b_received": "20",
  "b_remaining": "7",
  "wrong_party": "A",
  "reason": "B系統累計使用量(12)與A系統更新後(10)不符"
}
```

`wrong_party`：`"A"`（A系統可能有誤）、`"B"`（B系統可能有誤）、`"?"`（無法判斷）。

### 4.5 material_requests 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| user_id | INTEGER FK | 申請者 |
| material_id | INTEGER FK | 申請材料 |
| requested_quantity | INTEGER | 申請數量（min=1, max=99）|
| note | VARCHAR(200) | 備註（後端截斷至 50 字）|
| status | VARCHAR(10) | `PENDING` / `APPROVED` / `REJECTED` |
| reviewed_by | INTEGER FK | 審核者 |
| reviewed_at | DATETIME | |
| created_at | DATETIME | |

### 4.6 system_config 表（Key-Value）

| Key | 說明 | 預設值 |
|-----|------|--------|
| `retention_rate` | 西區全域保留金費率（NTD/只）| 20 |
| `retention_rate_south` | 南區全域保留金費率（NTD/只）| 20 |
| `tax_rate` | 西區稅務費率（%）| 3 |
| `tax_rate_south` | 南區稅務費率（%）| 3 |
| `price_{field}` | 西區各工項單價（NTD）| 見 `DEFAULT_PRICES_WEST` |
| `price_south_{field}` | 南區各工項單價（NTD）| 見 `DEFAULT_PRICES_SOUTH` |
| `price_bm_{field}` | 大表各工項單價（NTD）| 見 `DEFAULT_PRICES_BM` |
| `mat_tab_{N}_name` | 材料分頁 N（1–10）名稱；空字串 = 隱藏 | `mat_tab_1_name`=「全部材料」，其餘空 |
| `mat_last_import_name` | 最後一次成功匯入 Excel 的檔名（不含副檔名）；重置庫存後刪除此 key | — |

### 4.7 user_retention_rates 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| user_id | INTEGER FK→users.id | |
| field | VARCHAR(50) | 工項欄位名稱（如 `direct_13`）|
| rate | INTEGER | 保留金費率（NTD/只）|

用於個別帳戶客製保留金費率，覆蓋 SystemConfig 全域費率。欄位缺席 = 使用該區域全域費率。大表用戶（`is_big_meter=True`）與 ADMIN 不使用此表（回傳空 dict）。

### 4.8 audit_logs 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| user_id | INTEGER FK→users.id NULLABLE | NULL = 系統自動生成 |
| action_type | VARCHAR(50) | 操作類型，詳見第 17 節 |
| description | TEXT | 操作說明文字 |
| created_at | DATETIME | UTC+8 時間 |

索引：`(created_at)`、`(user_id, created_at)`、`(action_type)`

### 4.9 ledger_entries 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| entry_date | DATE | 記帳日期 |
| description | VARCHAR(200) | 摘要 |
| amount | INTEGER | NTD；正=收入，負=支出 |
| entry_type | VARCHAR(10) | `INCOME` / `EXPENSE` |
| category | VARCHAR(50) NULLABLE | 分類（材料費/人工費/雜支/設備費/運費/其他）|
| note | TEXT NULLABLE | 備註 |
| receipt_key | VARCHAR(300) NULLABLE | R2 object key |
| receipt_name | VARCHAR(200) NULLABLE | 原始檔名 |
| created_by | INTEGER FK→users.id | |
| payer_id | INTEGER FK→users.id NULLABLE | 支出者（NULL = 公司）|
| created_at | DATETIME | |
| updated_at | DATETIME | |

索引：`(entry_date)`、`(entry_type)`

### 4.10 report_archives 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| report_type | VARCHAR(10) | `DAILY` / `MONTHLY` |
| report_date | DATE | 報表對應日期 |
| period_start | DATE | 期間起始 |
| period_end | DATE | 期間結束 |
| r2_key_excel | VARCHAR(300) NULLABLE | R2 Excel 物件 key |
| r2_key_pdf | VARCHAR(300) NULLABLE | R2 PDF 物件 key |
| source | VARCHAR(10) | `auto`（排程）/ `manual`（手動）|
| generated_by | INTEGER FK→users.id NULLABLE | NULL = 自動排程 |
| generated_at | DATETIME | |

索引：`(report_date)`、`(report_type)`

---

## 5. 認證與授權

### 5.1 認證流程

1. POST `/login`，輸入 `display_name` + `password`
2. 速率限制（10 次/分鐘/IP）
3. `check_password_hash()` 驗證；帳號停用 → 拒絕
4. `login_user(user)` + `session.permanent = True`
5. ADMIN → redirect `/confirmation`；USER → redirect `/report`

### 5.2 授權裝飾器

```python
@login_required   # 未登入 → redirect /login
@admin_required   # 非 ADMIN → 403
```

ADMIN 存取 `/report` 或 `/personal_stats` 時自動 redirect 至 `/summary`。

### 5.3 路由權限表（v1.0.6 新增路由以 ★ 標示）

| 路由 | 方法 | 需 ADMIN |
|------|------|----------|
| `/login` / `/logout` | GET/POST | — |
| `/report`, `/api/collab-users` | GET/POST | USER only |
| `/history`, `/history/export-excel` | GET | ✗ |
| `/history/<id>/edit`, `/history/<id>/delete` | POST | ✗ |
| `/materials` | GET | ✗ |
| `/materials/request`, `/materials/requests/<id>/cancel` | POST | USER only |
| `/materials/export-excel` ★ | GET | ✓ |
| `/materials/import-excel` | POST | ✓ |
| `/materials/add`, `/materials/<id>/update`, `/materials/<id>/delete` | POST | ✓ |
| `/materials/<id>/move-up`, `/materials/<id>/move-down` | POST | ✓（支援 ajax=1）|
| `/materials/<id>/set-tab`, `/materials/<id>/toggle-hidden` | POST | ✓（支援 ajax=1）|
| `/materials/<id>/resolve-quarantine` | POST | ✓ |
| `/materials/batch-resolve-quarantine` ★ | POST | ✓ |
| `/admin/reset-materials` | POST | ✓ |
| `/audit` | GET | ✗ |
| `/personal_stats` | GET/POST | USER only |
| `/confirmation` | GET | ✓ |
| `/confirmation/report/<id>/confirm`, `/confirmation/report/<id>/reject` | POST | ✓ |
| `/confirmation/report/<id>/custom-item` | POST | ✓ |
| `/confirmation/material/<id>/approve`, `/confirmation/material/<id>/reject` | POST | ✓ |
| `/confirmation/reports/batch` ★ | POST | ✓ |
| `/confirmation/materials/batch` ★ | POST | ✓ |
| `/bm/confirmation`, `/bm/confirmation/report/<id>/confirm`, `/bm/confirmation/report/<id>/reject` | GET/POST | ✓ |
| `/bm/history`, `/bm/history/export-excel` | GET | ✓ |
| `/bm/history/<id>/edit`, `/bm/history/<id>/delete` | POST | ✓ |
| `/summary`, `/summary/export-excel` | GET | ✓ |
| `/salary` | GET/POST | ✓ |
| `/settings` | GET | ✗ |
| `/settings/users/create`, `/settings/users/<id>/...` | POST | ✓ |
| `/settings/tax-rate`, `/settings/retention-rate`, etc. | POST | ✓ |
| `/settings/mat-tabs` ★ | POST | ✓ |
| `/ledger`, `/ledger/add`, etc. | GET/POST | ✓ |
| `/reports/archives`, `/reports/archives/<id>/<fmt>` | GET | ✓ |
| `/admin/migrate-bank-encrypt` | GET | ✓ |

---

## 6. 路由與頁面邏輯

### 6.1 `/materials` — 材料庫存頁（v1.0.6 大幅更新）

**GET**：

- 讀取 `active_tab`（query string，預設 1）
- 讀取 10 個分頁名稱（`mat_tab_{N}_name`），計算 `visible_tabs`
- 查詢 `tab_materials`：當前分頁中 `is_quarantined=False` 的材料，USER 額外過濾 `is_hidden=False`
- **ADMIN**：不查 `all_materials`（節省 DB round-trip）；查詢暫存區材料 `quarantine_materials`
- **USER**：查 `all_materials`（用於申請紀錄展示）
- 讀取 `mat_last_import_name`（已對比標籤）

### 6.2 `/confirmation` — 確認頁（v1.0.6 更新）

不含大表用戶的待確認回報，分西區/南區兩組顯示。改為 checkbox 批次操作，移除逐筆按鈕。

### 6.3 其他主要路由

| 路由 | 說明 |
|------|------|
| `GET/POST /report` | USER 填寫當日施工工項（依 `zone` + `is_big_meter` 選擇欄位組）；ADMIN → redirect `/summary` |
| `GET /api/collab-users` | 回傳與 current_user 同區、同類型（大表/一般）的啟用 USER 清單，供共同作業下拉使用 |
| `GET /history` | 歷史回報列表（可篩選日期/帳戶/區域/是否含自訂工項）；ADMIN 可見所有人 |
| `GET /personal_stats` | USER 個人統計（本月/本年各工項合計、YTD 保留金）；ADMIN → redirect |
| `GET /summary` | ADMIN 統計總表（所有 USER 各工項彙總，含西區/南區/大表分組）|
| `GET/POST /salary` | ADMIN 薪資計算頁（輸入起訖日期 + 是否為 10 日發薪日）|
| `GET /bm/confirmation` | 大表回報確認頁（獨立於一般 confirmation）|
| `GET /settings` | 設定頁（帳戶管理、單價設定、保留金費率、分頁名稱等）|
| `GET /ledger` | 公司流水帳（收支明細、R2 憑證）|
| `GET /reports/archives` | 日月報檔案庫（下載 Excel/PDF）|
| `GET /audit` | 稽核日誌（可依帳戶/類型/日期篩選）|

---

## 7. 南/西區分區系統

### 7.1 區域常數

```python
ZONE_WEST  = '西區'
ZONE_SOUTH = '南區'
```

`User.zone` 欄位儲存 `'西區'` 或 `'南區'`，預設 `'西區'`。

### 7.2 工項欄位定義

**WEST_REPORT_FIELDS（32 欄）**

| field | 顯示名稱 |
|-------|----------|
| direct_13 | 直總-13 |
| direct_20 | 直總-20 |
| direct_25 | 直總-25 |
| direct_40 | 直總-40 |
| indirect_13 | 間接-13 |
| indirect_20 | 間接-20 |
| indirect_25 | 間接-25 |
| indirect_40 | 間接-40 |
| original_change | 原改 |
| dsv_13 | 直總-換由令(含表)-13 |
| dsv_20 | 直總-換由令(含表)-20 |
| dsv_25 | 直總-換由令(含表)-25 |
| isv_13 | 間接-換由令(含表)-13 |
| isv_20 | 間接-換由令(含表)-20 |
| isv_25 | 間接-換由令(含表)-25 |
| sw_13 | 13換開關(含表) |
| sw_20 | 20換開關(含表) |
| sw_25 | 25換開關(含表) |
| switch_valve_40 | 40換開關(含表) |
| dfix_13 | 直總-13固拆(含表) |
| dfix_20 | 直總-20固拆(含表) |
| dfix_25 | 直總-25固拆(含表) |
| direct_fixed_40 | 直總-40固拆(含表) |
| ifix_13 | 間接-13固拆(含表) |
| ifix_20 | 間接-20固拆(含表) |
| ifix_25 | 間接-25固拆(含表) |
| indirect_fixed_40 | 間接-40固拆(含表) |
| pipe_repair | 管修(提高) |
| mobilization | 動員 |
| recheck | 複查案/9年表 |
| soil_clearing | 清積土 |
| app_item | APP |

**SOUTH_REPORT_FIELDS（37 欄）**

共用欄位（同西區）：`direct_13/20/25/40`、`indirect_13/20/25/40`、`switch_valve_40`、`direct_fixed_40`、`indirect_fixed_40`、`pipe_repair`、`mobilization`、`recheck`、`soil_clearing`、`app_item`

南區專屬（取代西區 `original_change`/`dsv_*`/`isv_*`/`sw_*`/`dfix_*`/`ifix_*`）：

| field | 顯示名稱 |
|-------|----------|
| s_orig_13/20/25/40 | 原改-13/20/25/40 |
| s_dsv_13/20/25/40 | 直總-換由令(含表)-13/20/25/40 |
| s_isv_13/20/25/40 | 間接-換由令(含表)-13/20/25/40 |
| s_sw_13/20/25 | 13/20/25換開關(含表) |
| s_dfix_13/20/25 | 直總-13/20/25固拆(含表) |
| s_ifix_13/20/25 | 間接-13/20/25固拆(含表) |

### 7.3 保留金欄位

**WEST_RETENTION_FIELDS（8 欄）**：`direct_13/20/25/40`、`indirect_13/20/25/40`（換由令/換開關/固拆不扣）

**SOUTH_RETENTION_FIELDS（28 欄）**：上述 8 欄 + 南區換由令/換開關/固拆 20 欄（`s_dsv_*`、`s_isv_*`、`s_sw_*`、`switch_valve_40`、`s_dfix_*`、`direct_fixed_40`、`s_ifix_*`、`indirect_fixed_40`）

### 7.4 工具函數

```python
def get_zone_fields(zone: str) -> list:
    return SOUTH_REPORT_FIELDS if zone == ZONE_SOUTH else WEST_REPORT_FIELDS

def get_zone_retention_fields(zone: str) -> list:
    return SOUTH_RETENTION_FIELDS if zone == ZONE_SOUTH else WEST_RETENTION_FIELDS

def get_user_report_fields(user) -> list:
    """大表用戶用 BIG_METER_FIELDS，其餘依 zone。"""
    if getattr(user, 'is_big_meter', False):
        return BIG_METER_FIELDS
    return get_zone_fields(user.zone)
```

### 7.5 計價設定

西區：`price_{field}`（SystemConfig key），預設值見 `DEFAULT_PRICES_WEST`。
南區：`price_south_{field}`，預設值見 `DEFAULT_PRICES_SOUTH`。
SystemConfig 初始化時兩區單價均 seed。`_invalidate_price_cache()` 同時清除西區/南區/大表三份快取。

---

## 8. 大表（BM）用戶系統

### 8.1 識別

`User.is_big_meter = True`。大表用戶使用獨立的 25 個工項欄位與計價，與南/西區一般用戶完全分開管理。

### 8.2 BIG_METER_FIELDS（25 欄）

| field | 顯示名稱 |
|-------|----------|
| bm_50_down | 50mm下 |
| bm_75_down | 75mm下 |
| bm_100_down | 100mm下 |
| bm_150_down | 150mm下 |
| bm_200_down | 200mm下 |
| bm_250_down | 250mm下 |
| bm_300_down | 300mm下 |
| bm_50_up | 50mm上 |
| bm_75_up | 75mm上 |
| bm_100_up | 100mm上 |
| bm_150_up | 150mm上 |
| bm_200_up | 200mm上 |
| bm_250_up | 250mm上 |
| bm_rm_screw50 | 拆表/復水-螺紋50mm |
| bm_rm_noscrew50 | 拆表/復水-非螺紋50mm |
| bm_rm_75 | 拆表/復水-75mm |
| bm_rm_100 | 拆表/復水-100mm |
| bm_rm_150 | 拆表/復水-150mm |
| bm_rm_200 | 拆表/復水-200mm |
| bm_hole | 孔片 |
| bm_clean_big | 清箱大 |
| bm_truck | 小貨車 |
| bm_mobilization | 動員 |
| bm_recheck | 復查 |
| bm_app | APP |

### 8.3 計價

SystemConfig key：`price_bm_{field}`，預設值見 `DEFAULT_PRICES_BM`。快取函數：`get_item_prices_bm()`。

### 8.4 獨立確認頁

大表用戶的回報由 `/bm/confirmation` 頁面管理（獨立於 `/confirmation`）。薪資計算在同一個 `/salary` 頁面但以大表計價計算，且不計保留金（`period_retention = ytd_retention = 0`）。

### 8.5 共同作業

大表用戶的共同作業須為同區且同 `is_big_meter=True` 的 USER，後端驗證：`User.is_big_meter == is_bm`。

---

## 9. 共同作業系統

### 9.1 資料模型

Report 新增兩欄：

| 欄位 | 型別 | 說明 |
|------|------|------|
| collab_count | INTEGER DEFAULT 1 | 含提交者的總人數；1 = 無共同作業 |
| collab_json | TEXT NULLABLE | JSON list of additional collab user_ids（不含提交者）如 `[5, 12]` |

### 9.2 限制條件

- 共同作業者須為同區（`zone`）、同類型（`is_big_meter`）、啟用（`is_active`）的 USER
- 最多選 6 名（含提交者共 7 人上限）
- 後端驗證：

```python
valid_ids = {u.id for u in User.query.filter(
    User.id.in_(collab_ids),
    User.role == 'USER',
    User.is_active == True,
    User.zone == zone,
    User.is_big_meter == is_bm
).all() if u.id != current_user.id}
collab_ids = [i for i in collab_ids if i in valid_ids][:6]
```

### 9.3 只數分配（ceil/floor 演算法）

每回報以 `collab_count`（N）平分只數：

```
每人份額 = field_qty / N   (float 除法)
```

薪資計算時，提交者與各協作者均取 `getattr(r, k, 0) / N` 累加，不四捨五入到整數，精確到 `Numeric(8,1)` 精度。

### 9.4 協作者查詢 API

```
GET /api/collab-users
Response: [{"id": 5, "name": "USER03"}, ...]
```

回傳與 `current_user` 同 `zone` 且同 `is_big_meter` 的所有啟用 USER（不含自己），依 `display_name` 排序。

### 9.5 稽核日誌

回報時 `collab_ids` 非空則在 description 中記錄 `（共N人作業）`。

---

## 10. 薪資計算邏輯（核心業務）

### 10.1 輸入

- 起訖日期（`start_date` / `end_date`）
- 是否為 10 日發薪日（`is_10th_payday`，影響固定薪資與勞健保扣除）
- 範圍內所有 `is_confirmed=True` 的 Report

### 10.2 計算流程

```
1. 查詢範圍內已確認回報
2. 按 user_id 初始化 user_data（含協作者）
3. 每筆回報：只數 / collab_count → 分配給提交者 + 各協作者
4. 自訂工項金額（qty × price / N）亦分配給提交者 + 各協作者
5. 乘以各帳戶對應區域的單價 → gross_salary
6. 計算 period_retention（本期保留金，不超過 RETENTION_CAP - ytd_before）
7. net_salary = gross_salary - period_retention
8. 加固定薪資（is_10th_payday 或 every_period 時）
9. 扣勞健保（is_10th_payday 且已加保）
10. 扣稅（未加保且非免稅 → gross_salary × tax_rate）
11. final_salary = net_salary + fixed - insurance - tax
```

### 10.3 使用者類型矩陣

| 類型 | 計價表 | 保留金 | 稅務 |
|------|--------|--------|------|
| 西區 USER | WEST 單價 | 8 欄 × 費率 | 西區稅率 |
| 南區 USER | SOUTH 單價 | 28 欄 × 費率 | 南區稅率 |
| 大表 USER | BM 單價 | 無 | 大表稅率（同西區） |
| ADMIN | 西區/南區（依 zone）| 無 | 有 |

### 10.4 保留金計算細節

- `period_retention = max(0, min(period_ret_raw, RETENTION_CAP - ytd_before))`
- `ytd_before`：計算期間開始前，本年度已累積的保留金（含 `retention_offset`）
- `ytd_retention`：本年度至今全部累積保留金（`min(RETENTION_CAP, ytd_calc + offset)`）
- `RETENTION_CAP = 60000` NTD

### 10.5 過濾條件

最終結果過濾 `gross_salary == 0 AND final_salary == 0` 的帳戶（不顯示在薪資結果中，但有固定薪資的帳戶仍納入）。

---

## 11. 保留金系統

### 11.1 適用範圍

- 西區 USER：8 個直總/間接欄位（`WEST_RETENTION_FIELDS`）
- 南區 USER：28 個欄位（`SOUTH_RETENTION_FIELDS`）
- 大表 USER：不扣保留金（回傳空 dict）
- ADMIN：不扣保留金

### 11.2 費率優先順序

1. `UserRetentionRate` 表中該用戶該欄位的個人費率（最高優先）
2. SystemConfig `retention_rate`（西區全域）或 `retention_rate_south`（南區全域，預設各 20 NTD/只）

### 11.3 年度上限

`RETENTION_CAP = 60000` NTD。`ytd_retention` 不超過此值；`period_retention` 不超過 `RETENTION_CAP - ytd_before`（避免全年累積超限）。

### 11.4 ADMIN 調整

`User.retention_offset`（INT，正負皆可）：ADMIN 可設定固定偏移量，加入 `ytd_retention` 計算中。`/settings/users/<id>/set-retention` 路由透過反推計算：`offset = target - calculated_raw`。

### 11.5 核心函數

```python
def get_ytd_retention(user_id: int) -> float:
    # 查詢本年度已確認回報（含 collab 分配）
    # totals = {field: sum(qty/N for r in reports)}
    # user_rates = get_user_all_retention_rates(user_id)
    # calculated = sum(totals[f] * user_rates[f] for f in ret_fields)
    return min(RETENTION_CAP, max(0.0, calculated + offset))

def get_users_all_retention_rates(user_ids, users_dict) -> dict:
    # 批次載入，回傳 {uid: {field: rate}}
    # 大表用戶 → {}
```

---

## 12. 匯出功能

### 12.1 薪資 Excel / PDF / Word

路由：`GET /salary`（含 `?export=excel` / `?export=pdf` / `?export=word`）

- **Excel**：每位 USER 一個 sheet，含工項明細、單價、小計、固定薪資、保留金、勞健保、稅務、實發金額。`openpyxl`，樣式：標題粗體、金額欄右對齊、負數紅色。
- **PDF**：`reportlab`，A4 橫式，同 Excel 內容排版。
- **Word（薪轉單）**：`python-docx`，僅含：姓名、銀行帳號、實發金額，供財務直接使用。
- 三種格式均以 `Content-Disposition: attachment` 回應，不觸發 loading overlay（連結加 `data-no-loading`）。

### 12.2 日月報 Excel

由 `_run_auto_report(report_type, target_date, source)` 生成。

- **日報（DAILY）**：對應 `target_date` 這一天所有已確認回報，三個 sheet（西區/南區/大表），各 sheet 含帳戶名稱、各工項只數、小計金額。
- **月報（MONTHLY）**：對應 `target_date` 所在月份全月，三個 sheet，格式同日報。
- 生成後上傳至 Cloudflare R2（`r2_key_excel`），並在 `report_archives` 插入記錄。
- 若 R2 未設定，仍生成 `ReportArchive` 記錄但 `r2_key_excel=None`（下載時顯示警告）。

### 12.3 歷史紀錄匯出 Excel（v1.0.6 新增）

路由：`GET /history/export-excel`（`data-no-loading`，不觸發 loading overlay）

帶入與 `/history` 相同的 query string 篩選條件，匯出篩選後的全部歷史紀錄（WEST∪SOUTH 所有工項欄位）為 `.xlsx`。

### 12.4 大表歷史紀錄匯出 Excel（v1.0.6 新增）

路由：`GET /bm/history/export-excel`，同上邏輯，欄位使用 `BIG_METER_FIELDS`。

### 12.5 材料庫存匯出 Excel（v1.0.6 新增）

路由：`GET /materials/export-excel`（ADMIN only，`data-no-loading`）

匯出所有 `is_quarantined=False` 的材料，欄位含：分頁名稱、材料編號、材料名稱、規格、單位、累計使用量、實領量、庫存量、是否隱藏。

---

## 13. 材料庫存管理（v1.0.6 全面重寫）

### 13.1 資料模型不變式

```
received_quantity = cumulative_usage + remaining_quantity
```

所有庫存操作（核准申請、暫存區解決、直接調整）必須維護此不變式。

### 13.2 分頁系統

- `tab_id` 1–10 對應 SystemConfig `mat_tab_N_name`
- `visible_tabs`：name 不為空的分頁 ID 集合
- ADMIN 可在材料庫存頁的「管理分頁名稱」修改
- `materials_set_tab(material_id)` POST：`new_tab = max(1, min(10, int(tab_id)))`

### 13.3 隱藏/顯示（AJAX）

```
POST /materials/<id>/toggle-hidden
Body: csrf_token=... [&ajax=1]
Response (ajax=1): {"ok": true, "is_hidden": <bool>}
```

`ajax=1` 時回傳 JSON，前端更新 row CSS（`opacity-50`）、badge（`.hidden-badge`）、按鈕狀態，不重整頁面。

### 13.4 移動排序（AJAX）

```
POST /materials/<id>/move-up  (或 move-down)
Body: csrf_token=... [&ajax=1]
Response (ajax=1): {"ok": true, "swapped": <bool>}
```

`ajax=1` 時回傳 JSON，前端用 `insertBefore`/`insertAdjacentElement` 交換 DOM `<tr>`，再呼叫 `refreshMoveButtons()` 更新首/末列 disabled 狀態。

### 13.5 Excel 兩步驟比對邏輯

**匯入格式要求**：第一列為標題，必須含「材料編號」和「實領量」。支援 `.xlsx` / `.csv`。

**Step 1 — 計算新進量 x**：

```
x = B.received_quantity - A.received_quantity
```

- `x < 0`：B 系統實領量少於 A → 進暫存區（異常）
- `x = 0`：新進量為零，繼續 Step 2
- `x > 0`：正常新進，繼續 Step 2

**Step 2 — 比對更新後數值**：

計算 A 更新後數值：

```
a_received_new  = A.received + x
a_remaining_new = A.remaining + x
```

比對 B 系統數值（B.cumulative、B.received、B.remaining）與 A 更新後數值是否一致。

**進暫存區條件**（任一成立）：
1. `x < 0`（B 實領量倒退）
2. A 系統內部不一致（`cumulative + remaining ≠ received`）
3. B 系統數值與 A 更新後不符（可能是 B 的記錄有誤）

**正常更新條件**：
- `x ≥ 0` 且 A 系統內部一致 且 B 系統數值與 A 更新後相符
- 執行：`received += x`，`remaining += x`（`cumulative` 不變）

**wrong_party 判斷邏輯**：
- A 系統內部不一致 → `"A"`
- B 數值與預期不符且 A 內部一致 → `"B"`
- 其他 → `"?"`

### 13.6 暫存區批次解決

路由：`POST /materials/batch-resolve-quarantine`

```python
for mid in request.form.getlist('ids'):
    m = Material.query.get(mid)
    action = request.form.get(f'action_{mid}', 'keep_a')
    if action == 'use_b':
        # 採用 B 系統三值
        m.cumulative_usage   = Decimal(note['b_cumulative'])
        m.remaining_quantity = Decimal(note['b_remaining'])
        m.received_quantity  = Decimal(note['b_received'])
    else:  # keep_a
        # 保留 A 累計使用量，套入 x 更新庫存
        if x > 0:
            m.received_quantity  = Decimal(note['a_received_new'])
            m.remaining_quantity = Decimal(note['a_remaining_new'])
    m.is_quarantined  = False
    m.quarantine_note = None
```

**預設 action 邏輯**：`wrong_party == 'A'` → 預選「信任B」；其餘 → 預選「信任A」。

操作後 redirect 至 `url_for('materials') + '#quarantineSection'`，JS 使用 `scrollIntoView` 保持頁面位置。

### 13.7 重置庫存

路由：`POST /admin/reset-materials`

呼叫 `_seed_materials_csv(reset=True)`：94 筆預設材料（來自 `_MATERIALS_SEED`），所有 quantity=0，`is_hidden=False`，`is_quarantined=False`，`tab_id=1`。

同時刪除 `SystemConfig` 中 `mat_last_import_name` key（清除「已對比」標籤）。

### 13.8 材料申請批次處理（v1.0.6 新增）

路由：`POST /confirmation/materials/batch`

```python
action = request.form.get('batch_action')  # 'approve' or 'reject'
for req_id in request.form.getlist('ids'):
    req = MaterialRequest.query.get(req_id)
    if req.status != 'PENDING': continue  # 跳過非待審核
    if action == 'approve':
        # 扣庫存，加累計使用量，維護不變式
        ...
```

---

## 14. 流水帳（LedgerEntry）

### 14.1 子路由

| 路由 | 說明 |
|------|------|
| `GET /ledger` | 列表（可篩選日期/類型/分類），顯示收入/支出總計，頁數 20 筆/頁 |
| `POST /ledger/add` | 新增記錄（必填：日期/摘要/金額/類型；選填：分類/備註/R2憑證/支出者）|
| `POST /ledger/<id>/edit` | 修改記錄 |
| `POST /ledger/<id>/delete` | 刪除記錄（同時刪除 R2 憑證）|
| `POST /ledger/<id>/settle` | 標記墊付已沖銷（設定 `settled_at`）|
| `GET /ledger/<id>/receipt` | 從 R2 下載憑證（預簽名 URL，3600s 效期）|
| `GET /ledger/export` | 匯出篩選後記錄為 Excel |

### 14.2 分類

`LEDGER_CATEGORIES = ['材料費', '人工費', '雜支', '設備費', '運費', '其他']`

### 14.3 R2 憑證上傳

支援 PDF / JPEG / PNG / WebP，最大 10 MB。Object key 格式：`receipts/{entry_id}/{uuid}.{ext}`。`_r2_client` 未初始化時跳過上傳，記錄仍儲存。

---

## 15. 日月報檔案庫（ReportArchive）

### 15.1 自動排程

使用 APScheduler（`BackgroundScheduler`，timezone `Asia/Taipei`）：

| 排程 | 觸發時間 | 說明 |
|------|----------|------|
| `_daily_job` | 每天 23:59:00 | 生成當天日報 |
| `_monthly_job` | 每月末 23:59:30 | 生成當月月報 |

### 15.2 手動生成

`POST /reports/archives/generate`（ADMIN only），可指定日期與 `report_type`。

### 15.3 R2 路徑格式

```
reports/DAILY/{YYYY}/{MM}/{YYYY-MM-DD}.xlsx
reports/MONTHLY/{YYYY}/{MM}/{YYYY-MM}.xlsx
```

PDF 路徑同上，副檔名改為 `.pdf`。

### 15.4 下載

`GET /reports/archives/<id>/<fmt>`（fmt: `excel` / `pdf`）：從 R2 取得 presigned URL（3600s），redirect 至該 URL；R2 未設定時 flash 警告。

---

## 16. Cloudflare R2 儲存

### 16.1 環境變數

| 環境變數 | 說明 |
|----------|------|
| `R2_ACCOUNT_ID` | Cloudflare Account ID |
| `R2_ACCESS_KEY_ID` | R2 存取金鑰 ID |
| `R2_SECRET_ACCESS_KEY` | R2 存取金鑰密文 |
| `R2_BUCKET_NAME` | Bucket 名稱 |

四個環境變數均設定時才啟用 R2 client（`boto3` S3 相容 API，endpoint `https://{account_id}.r2.cloudflarestorage.com`）。任一缺失則 `_r2_client = None`，所有 R2 操作靜默跳過。

### 16.2 用途

| 功能 | Object key 前綴 |
|------|----------------|
| 日月報 Excel | `reports/DAILY/` / `reports/MONTHLY/` |
| 日月報 PDF | 同上，副檔名 `.pdf` |
| 流水帳憑證 | `receipts/{entry_id}/` |

### 16.3 Helper 函數

```python
def _r2_upload(file_obj, object_key, content_type) -> bool
def _r2_delete(object_key) -> bool
def _r2_presign(object_key, expires_in=3600) -> str | None
```

---

## 17. 變動紀錄（Audit Log）

### 17.1 Action Types（v1.0.6 新增以 ★ 標示）

| action_type | 觸發時機 |
|-------------|----------|
| `REPORT_CREATE` | 新增回報 |
| `REPORT_UPDATE` | 修改回報 |
| `REPORT_DELETE` | 刪除回報 |
| `REPORT_CONFIRM` | ADMIN 確認回報（含批次） |
| `REPORT_REJECT` | ADMIN 駁回回報（含批次） |
| `ACCOUNT_CREATE` | 新增帳戶 |
| `ACCOUNT_UPDATE` | 更新帳戶資訊 |
| `ACCOUNT_DEACTIVATE` | 停用帳戶 |
| `ACCOUNT_REACTIVATE` | 復原帳戶 |
| `ACCOUNT_DELETE` | 永久刪除帳戶 |
| `PASSWORD_CHANGE` | 密碼變更 |
| `MATERIAL_REQUEST` | 材料申請 |
| `MATERIAL_CANCEL` | 取消材料申請 |
| `MATERIAL_ADD` | 新增材料品項 |
| `MATERIAL_UPDATE` | 更新材料庫存 |
| `MATERIAL_DELETE` | 刪除材料品項 |
| `MATERIAL_APPROVE` | 核准材料申請（含批次） |
| `MATERIAL_REJECT` | 拒絕材料申請（含批次） |
| `MATERIAL_IMPORT` ★ | 匯入 Excel 盤點比對 |
| `MATERIAL_RESET` ★ | 重置庫存 |
| `MATERIAL_KEEP_A` ★ | 暫存區解決：保留 A 系統值（含批次） |
| `MATERIAL_SYNC_B` ★ | 暫存區解決：採用 B 系統值（含批次） |
| `SYSTEM_CONFIG` | 系統設定變更 |
| `RETENTION_RESET` | 重置保留金 |
| `RETENTION_SET` | 設定保留金調整值 |
| `LEDGER_CREATE` | 新增流水帳記錄 |
| `LEDGER_UPDATE` | 修改流水帳記錄 |
| `LEDGER_DELETE` | 刪除流水帳記錄 |
| `LEDGER_SETTLE` | 沖銷流水帳墊付 |

---

## 18. 資料庫初始化與 Migration

### 18.1 `_init_db()` 執行順序

1. `db.create_all()`
2. Column migrations（各自 try/except，冪等）：
   - **v1.0.3–v1.0.5 欄位（累積遷移，各自 try/except）**：
     ```sql
     -- users 表
     ALTER TABLE users ADD COLUMN insurance_deduction INTEGER NOT NULL DEFAULT 0;
     ALTER TABLE users ADD COLUMN retention_offset INTEGER NOT NULL DEFAULT 0;
     ALTER TABLE users ADD COLUMN tax_exempt BOOLEAN NOT NULL DEFAULT FALSE;
     ALTER TABLE users ADD COLUMN bank_account VARCHAR(14);
     ALTER TABLE users ALTER COLUMN bank_account TYPE VARCHAR(200);
     ALTER TABLE users ADD COLUMN fixed_salary INTEGER NOT NULL DEFAULT 0;
     ALTER TABLE users ADD COLUMN zone VARCHAR(10) NOT NULL DEFAULT '西區';
     ALTER TABLE users ADD COLUMN IF NOT EXISTS is_big_meter BOOLEAN NOT NULL DEFAULT FALSE;
     ALTER TABLE users ADD COLUMN IF NOT EXISTS fixed_salary_every_period BOOLEAN NOT NULL DEFAULT FALSE;
     -- materials 表
     ALTER TABLE materials ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0;
     -- reports 表（INTEGER→NUMERIC 升級）
     ALTER TABLE reports ALTER COLUMN direct_13 TYPE NUMERIC(8,1) ...;  -- 及其他 15 個共用工項欄
     ALTER TABLE reports ADD COLUMN IF NOT EXISTS is_rejected BOOLEAN NOT NULL DEFAULT FALSE;
     ALTER TABLE reports ADD COLUMN IF NOT EXISTS collab_count INTEGER NOT NULL DEFAULT 1;
     ALTER TABLE reports ADD COLUMN IF NOT EXISTS collab_json TEXT;
     ALTER TABLE reports ADD COLUMN IF NOT EXISTS app_item NUMERIC(8,1) NOT NULL DEFAULT 0;
     ALTER TABLE reports ADD COLUMN IF NOT EXISTS custom_item_name VARCHAR(100);
     ALTER TABLE reports ADD COLUMN IF NOT EXISTS custom_item_qty NUMERIC(8,1) DEFAULT 0;
     ALTER TABLE reports ADD COLUMN IF NOT EXISTS custom_item_price INTEGER DEFAULT 0;
     -- 西區拆分欄（15 欄：dsv_*/isv_*/sw_*/dfix_*/ifix_*）
     ALTER TABLE reports ADD COLUMN IF NOT EXISTS dsv_13 NUMERIC(8,1) NOT NULL DEFAULT 0; -- 等
     -- 南區欄（21 欄：s_orig_*/s_dsv_*/s_isv_*/s_sw_*/s_dfix_*/s_ifix_*）
     ALTER TABLE reports ADD COLUMN IF NOT EXISTS s_orig_13 NUMERIC(8,1) NOT NULL DEFAULT 0; -- 等
     -- 大表欄（27 欄：bm_50_down ... bm_40_fen）
     ALTER TABLE reports ADD COLUMN IF NOT EXISTS bm_50_down NUMERIC(8,1) NOT NULL DEFAULT 0; -- 等
     -- audit_logs
     ALTER TABLE audit_logs ALTER COLUMN user_id DROP NOT NULL;
     -- report_archives
     ALTER TABLE report_archives ADD COLUMN source VARCHAR(10) NOT NULL DEFAULT 'auto';
     ALTER TABLE report_archives ADD COLUMN generated_by INTEGER REFERENCES users(id);
     -- ledger_entries
     ALTER TABLE ledger_entries ADD COLUMN payer_id INTEGER REFERENCES users(id);
     -- material_requests
     ALTER TABLE material_requests ADD COLUMN IF NOT EXISTS note VARCHAR(200);
     ```
   - **v1.0.6 新增**：
     ```sql
     ALTER TABLE materials ADD COLUMN IF NOT EXISTS code VARCHAR(50);
     ALTER TABLE materials ADD COLUMN IF NOT EXISTS spec VARCHAR(200);
     ALTER TABLE materials ADD COLUMN IF NOT EXISTS cumulative_usage NUMERIC(12,3) NOT NULL DEFAULT 0;
     ALTER TABLE materials ADD COLUMN IF NOT EXISTS received_quantity NUMERIC(12,3) NOT NULL DEFAULT 0;
     ALTER TABLE materials ADD COLUMN IF NOT EXISTS tab_id INTEGER NOT NULL DEFAULT 1;
     ALTER TABLE materials ADD COLUMN IF NOT EXISTS is_hidden BOOLEAN NOT NULL DEFAULT FALSE;
     ALTER TABLE materials ADD COLUMN IF NOT EXISTS is_quarantined BOOLEAN NOT NULL DEFAULT FALSE;
     ALTER TABLE materials ADD COLUMN IF NOT EXISTS quarantine_note TEXT;
     ALTER TABLE material_requests ADD COLUMN IF NOT EXISTS note VARCHAR(200);
     ```
3. `CREATE INDEX IF NOT EXISTS`
4. Seed SystemConfig 預設值（含 `mat_tab_1_name`=「全部材料」，`mat_tab_2_name` ~ `mat_tab_10_name`=空字串）

### 18.2 新增欄位流程

1. `models.py` 新增 Column
2. `_init_db()` 加入 try/except ALTER TABLE 區塊
3. 相關路由加入讀寫邏輯 → git push → Railway 自動執行

> **注意**: 不使用 Flask-Migrate/Alembic，所有 migration 手動管理。

---

## 19. 前端架構

### 19.1 base.html

提供全站共用結構：

- **側欄（Sidebar）**：可收合，狀態存於 `localStorage.ycSidebarCollapsed`。依 `current_user.role` 控制顯示項目（ADMIN 看不到「回報頁面」和「個人統計」）；依 `current_user.is_big_meter` 顯示大表確認頁連結。
- **Loading overlay**：所有表單送出或連結點擊時顯示全頁遮罩；含 `data-no-loading` attribute 的元素不觸發。
- **Flash messages**：Bootstrap alert，自動 5 秒後淡出。
- **CSP header**（`after_request` hook）：`default-src 'self'`；允許 `cdn.jsdelivr.net`（Bootstrap/Icons CDN）；`script-src` 含 `'unsafe-inline'`（Jinja2 inline script 需要）。
- **Session 過期**：`PERMANENT_SESSION_LIFETIME = 10 分鐘`；session cookie `HttpOnly + SameSite=Lax + Secure`（生產環境）。

### 19.2 materials.html AJAX 模式（v1.0.6 新增）

**移動排序**（`matMove(btn, dir)`）：

```javascript
fetch(url, { method:'POST', body:'csrf_token=...&ajax=1' })
  .then(r => r.json())
  .then(data => {
    if (data.ok && data.swapped) {
      // DOM: insertBefore / insertAdjacentElement
      refreshMoveButtons(tbody);
    }
  });
```

**隱藏切換**（`matToggleHidden(btn)`）：

```javascript
fetch(url, { method:'POST', body:'csrf_token=...&ajax=1' })
  .then(r => r.json())
  .then(data => {
    // 更新 btn class、title、icon、row opacity、.hidden-badge display
  });
```

**暫存區批次 JS**（`checkAndConfirmBatch()`、`toggleAllQ()`、`setAllQ(action)`）：

- `setAllQ('keep_a')` / `setAllQ('use_b')`：一次設定所有 `select[name^=action_]` 的值
- `checkAndConfirmBatch()`：驗證至少一項已勾選，彈出 `confirm()`，返回 `false` 阻止 submit

### 19.3 confirmation.html 批次模式（v1.0.6 新增）

**`submitBatch(formId, action, verb)`**：

```javascript
function submitBatch(formId, action, verb) {
  const form = document.getElementById(formId);
  const checked = form.querySelectorAll('input[name="ids"]:checked');
  if (checked.length === 0) { alert('請先勾選項目'); return; }
  if (!confirm('確定' + verb + '已勾選的 ' + checked.length + ' 筆？')) return;
  form.querySelector('[name="batch_action"]').value = action;
  form.submit();
}
```

報表表單：`id="batchReportForm"` → `POST /confirmation/reports/batch`
材料申請表單：`id="batchMatForm"` → `POST /confirmation/materials/batch`

### 19.4 Jinja2 Template Filters

| Filter | 說明 |
|--------|------|
| `\| qty` | 整數顯示為 `3`，帶小數顯示為 `3.1`，零顯示為空字串 |
| `\| mat_qty` | 材料數量格式化（移除多餘尾隨零）|
| `\| money` | 千位分隔，整數省略小數點 |
| `\| from_json` | JSON string → Python dict，錯誤返回 `{}` |
| `\| report_json` | Report ORM object → JSON string |
| `\| tw_time` | datetime → `'YYYY-MM-DD HH:MM'` 格式 |

### 19.5 `data-no-loading` 屬性

連結或按鈕加上 `data-no-loading` attribute 時，點擊不觸發 loading overlay（用於 Excel 下載等 streaming response）。

---

## 20. 設定系統（SystemConfig）

### 20.1 工項單價快取

```python
_price_cache_west:  dict = {}
_price_cache_south: dict = {}
_price_cache_bm:    dict = {}
_PRICE_CACHE_TTL = 300  # 5 分鐘
```

`_invalidate_price_cache()` 同時清除三個快取。

### 20.2 費率快取

```python
_config_cache: dict = {}
_CONFIG_CACHE_TTL = 60  # 60 秒
```

---

## 21. 效能優化機制

### 21.1 查詢優化彙整（v1.0.6 新增兩項）

| 優化項目 | 節省 |
|----------|------|
| 工項單價快取（TTL 300s）| ~97% |
| 費率/稅率快取（TTL 60s）| 100% |
| ADMIN 材料頁跳過 `all_materials` 查詢 ★ | 1 次 DB round-trip/頁面載入 |
| AJAX move-up/down/toggle-hidden（不重整頁面）★ | 省完整頁面重新查詢 |
| GIN index 加速 collab_json 搜尋 | 全表掃描→索引 |

### 21.2 Supabase 連線池

```python
'pool_pre_ping': True,
'pool_recycle': 1800,
'pool_size': 3,
'max_overflow': 3,
```

---

## 22. 已知限制與注意事項

### 22.1 每人每日一筆回報

無 DB UNIQUE 約束，業務邏輯在 `/report` POST handler 中處理。

### 22.2 稅務計算基數

稅務支出計算基數為「工項薪資毛額」，不含固定薪資。此為業務決策，非 bug。

### 22.3 保留金年度邊界

以「計薪起始日的年份」決定年度（`date(sd.year, 1, 1)`），跨年度計薪可能有邊界問題。

### 22.4 速率限制 memory backend

Flask-Limiter 使用 `memory://` backend，不跨 worker/重啟持久化。多 worker 需改用 Redis backend。

### 22.5 工項單價快取多 worker

`get_item_prices_*()` 為 process-level 快取，多 worker 部署時更新後最多 300 秒才全部刷新。

### 22.6 銀行帳號加密金鑰管理

`BANK_ENCRYPT_KEY` 遺失後無法解密現有帳號。應妥善保管。

### 22.7 R2 presigned URL 有效期

Presigned URL 有效期 3600 秒。請勿儲存此 URL。

### 22.8 APScheduler 單 worker 限制

多 worker 部署時可能造成重複生成報表。當前部署為單 worker，無此問題。

### 22.9 材料庫存 SQLite 相容性

`collab_json::jsonb @> '[uid]'` 搜尋依賴 PostgreSQL JSONB 語法，SQLite 不支援。**建議本地開發亦使用 Supabase PostgreSQL**。

### 22.10 大表用戶 zone 欄位

大表用戶仍有 `zone` 欄位（預設 `'西區'`），計薪時不使用 zone 決定欄位，僅用於帳戶列表分組顯示。

### 22.11 材料庫存暫存區解決後的不變式驗證

信任B 時直接寫入 B 系統三值（`b_cumulative`、`b_received`、`b_remaining`），需確認 B 系統三值本身符合不變式（由 Excel 上傳邏輯保證）。信任A 時只更新 `received` 和 `remaining`，`cumulative` 不變，不變式由計算公式保證。

---

*最後更新: 2026-07-27 | 版本: v1.0.6 | 由 Claude Sonnet 4.6 輔助生成*
