# 員工日報回報系統 — 系統規格書

> **版本**: v1.0.5
> **日期**: 2026-07-09
> **狀態**: 已實作（反映當前生產環境實際運作狀態）
> **維護工程師參考文件**

---

## 版本變更紀錄

| 版本 | 日期 | 變更摘要 |
|------|------|----------|
| v1.0.5 | 2026-07-09 | 大表（BM）用戶類型（獨立工項/計價/確認頁）；新增 bm_40_fen 工項；ADMIN 移除保留金；fixed_salary_every_period 欄位（固定薪資每期發放）；薪資計算過濾零薪資帳戶 |
| v1.0.4 | 2026-07-09 | 南/西區分區系統（工項/計價/保留金各自獨立）；共同作業回報（collab_count/collab_json）；工項欄位型別升級 NUMERIC(8,1)；共作只數 ceil/floor 分配；SystemConfig 批次快取；計價 N+1 → 1 次批次查詢；JSONB GIN index；Excel/PDF 只數 round(val,1) |
| v1.0.3 | 2026-07-01 | UTC+8 時間儲存；流水帳（LedgerEntry）+ 憑證 R2 上傳；日月報檔案庫（ReportArchive）+ R2 存儲；薪資計算涵蓋停用帳戶；Excel 欄寬修正；月報 YTD 保留金修正 |
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
13. [材料管理](#13-材料管理)
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
- 材料庫存管理與申請流程
- 公司收支流水帳（含憑證上傳至 Cloudflare R2）
- 日月報自動/手動生成並存儲至 Cloudflare R2
- 薪資轉帳文件匯出（Excel/PDF/Word）
- 完整操作稽核日誌

### 1.2 使用者規模

- 設計容量：≤ 10 ADMIN + ≤ 75 USER（共 85 人）
- 資料量：每月約 85 × 22 = 1,870 筆回報；年度約 22,440 筆

### 1.3 應用程式入口

- `app.py`: 所有路由、業務邏輯、匯出功能、安全設定（~5,000 行）
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
├── openpyxl              — Excel 匯出
├── reportlab             — PDF 匯出
├── python-docx           — Word（薪轉單）匯出
├── boto3                 — Cloudflare R2（S3 相容）上傳/下載
└── apscheduler 3.10.4    — 定時任務（日月報自動生成）
```

### 2.2 資料庫

- **本地開發**: SQLite（`instance/app.db`）
- **生產環境**: PostgreSQL via Supabase（環境變數 `DATABASE_URL`）

```python
_db_url = os.environ.get('DATABASE_URL', 'sqlite:///daily_report.db')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
```

### 2.3 部署

- Railway 平台，連接 GitHub `main` 分支
- `git push origin main` → 自動觸發 re-deploy
- 無 Docker，直接 Python 執行環境
- Filesystem 為 ephemeral，所有持久化檔案存於 Cloudflare R2

### 2.4 前端

- Bootstrap 5.3（CDN）+ Bootstrap Icons 1.11（CDN）
- 無 JS 框架，純 Jinja2 + 原生 JS
- 所有 POST 表單包含 CSRF hidden token（Flask-WTF 自動驗證）

### 2.5 時間處理

所有時間戳以 **UTC+8（台灣時間）** 的 naive datetime 儲存：

```python
def tw_now():
    return datetime.utcnow() + timedelta(hours=8)
```

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

`CSRFProtect(app)` 全域啟用。所有 POST 表單第一行：
```html
<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

### 3.2 登入速率限制

`/login` 限制每 IP 10 次/分鐘（memory backend）。超出回傳 429。

> **注意**: memory backend 不跨 worker/重啟持久化。多 worker 需改 Redis backend。

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

使用 `BANK_ENCRYPT_KEY` 環境變數進行 Fernet 對稱加密，儲存於 `VARCHAR(200)` 欄位。`BANK_ENCRYPT_KEY` 未設定時明文儲存，功能不中斷。

### 3.6 HTTP 安全標頭

```python
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options']         = 'SAMEORIGIN'
    response.headers['X-XSS-Protection']        = '1; mode=block'
    response.headers['Referrer-Policy']         = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy']      = 'geolocation=(), microphone=(), camera=()'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
        "font-src 'self' cdn.jsdelivr.net data:; "
        "img-src 'self' data:; "
        "connect-src 'self';"
    )
    return response
```

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
| is_big_meter | BOOLEAN | True = 大表用戶；使用 BM 工項與計價，無保留金 |
| is_active | BOOLEAN | False = 停用（無法登入）|
| payment_method | VARCHAR(10) | `'TRANSFER'` 或 `'CASH'` |
| insurance_deduction | INTEGER | 勞健保固定扣除額（NTD）；0 = 未投保 |
| tax_exempt | BOOLEAN | True = 未投保免稅；False = 未投保需扣稅 |
| bank_account | VARCHAR(200) | Fernet 加密 token 或明文 14 碼（降級模式）|
| fixed_salary | INTEGER | 固定薪資（NTD）；預設 0 |
| fixed_salary_every_period | BOOLEAN | True = 每期皆發放固定薪資（不受 is_10th_payday 限制）；False = 僅 10 號發薪日 |
| retention_offset | INTEGER | ADMIN 手動調整保留金累計（可負值）|
| created_at / updated_at | DATETIME | UTC+8 naive datetime |

**v1.0.5 新增欄位**:
- `is_big_meter BOOLEAN NOT NULL DEFAULT FALSE`
- `fixed_salary_every_period BOOLEAN NOT NULL DEFAULT FALSE`

**帳戶排序規則（settings 頁）**: ADMIN 置頂 → 西區 USER（依 display_name）→ 南區 USER（依 display_name）；大表 USER 歸入其 zone 群組內。

### 4.3 reports 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| user_id | INTEGER FK | → users.id（回報者）|
| report_date | DATE | 回報日期 |
| *工項欄位* | NUMERIC(8,1) | 各工項數量 |
| collab_count | INTEGER | 含提交者在內的總共作人數；1 = 無共作 |
| collab_json | TEXT | JSON list of additional user_ids，不含提交者；如 `"[5, 12]"` |
| is_confirmed | BOOLEAN | ADMIN 已確認 |
| confirmed_by | INTEGER FK | → users.id（確認者）|
| confirmed_at | DATETIME | 確認時間（UTC+8）|
| is_rejected | BOOLEAN | ADMIN 已駁回 |
| created_at / updated_at | DATETIME | UTC+8 naive datetime |

#### 西區工項欄位（31 欄，`WEST_REPORT_FIELDS`）

```
直總管：  direct_13, direct_20, direct_25, direct_40
間接管：  indirect_13, indirect_20, indirect_25, indirect_40
原改：    original_change
直總換由令：dsv_13, dsv_20, dsv_25
間接換由令：isv_13, isv_20, isv_25
換開關：  sw_13, sw_20, sw_25, switch_valve_40
直總固拆：dfix_13, dfix_20, dfix_25, direct_fixed_40
間接固拆：ifix_13, ifix_20, ifix_25, indirect_fixed_40
共用：    pipe_repair, mobilization, recheck, soil_clearing
APP 工項：app_item
```

#### 南區工項欄位（36 欄，`SOUTH_REPORT_FIELDS`）

```
直總管：  direct_13, direct_20, direct_25, direct_40
間接管：  indirect_13, indirect_20, indirect_25, indirect_40
原改：    s_orig_13, s_orig_20, s_orig_25, s_orig_40     ← 南區專屬
直總換由令：s_dsv_13, s_dsv_20, s_dsv_25, s_dsv_40       ← 南區含 40mm
間接換由令：s_isv_13, s_isv_20, s_isv_25, s_isv_40
換開關：  s_sw_13, s_sw_20, s_sw_25, switch_valve_40
直總固拆：s_dfix_13, s_dfix_20, s_dfix_25, direct_fixed_40
間接固拆：s_ifix_13, s_ifix_20, s_ifix_25, indirect_fixed_40
共用：    pipe_repair, mobilization, recheck, soil_clearing
```

#### 大表工項欄位（26 欄，`BIG_METER_FIELDS`）

```
下（bm_*_down, 7 欄）：
  bm_50_down, bm_75_down, bm_100_down, bm_150_down, bm_200_down, bm_250_down, bm_300_down

上（bm_*_up, 6 欄）：
  bm_50_up, bm_75_up, bm_100_up, bm_150_up, bm_200_up, bm_250_up

其他工項（13 欄）：
  bm_rm_screw50, bm_rm_noscrew50, bm_rm_75, bm_rm_100, bm_rm_150, bm_rm_200,
  bm_hole, bm_clean_big, bm_truck, bm_mobilization, bm_recheck, bm_app, bm_40_fen
```

> `bm_40_fen`（40MM分）為 v1.0.5 新增工項，預設單價 150 NTD。

**欄位型別**: 全部為 `NUMERIC(8,1)`。

#### 索引

```sql
CREATE INDEX ix_reports_user_date        ON reports (user_id, report_date)
CREATE INDEX ix_reports_date_confirmed   ON reports (report_date, is_confirmed)
CREATE INDEX ix_reports_user_confirmed   ON reports (user_id, is_confirmed)
CREATE INDEX idx_reports_status          ON reports (is_confirmed, is_rejected, report_date, id)
CREATE INDEX idx_reports_user_date       ON reports (user_id, report_date, is_confirmed)
CREATE INDEX idx_reports_date_conf       ON reports (report_date, is_confirmed)
CREATE INDEX idx_reports_collab_gin ON reports USING gin ((collab_json::jsonb))
```

### 4.4 materials 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| name | VARCHAR(100) | 材料名稱 |
| unit | VARCHAR(20) | 單位 |
| remaining_quantity | INTEGER | 庫存量 |
| sort_order | INTEGER | 顯示排序 |

### 4.5 material_requests 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| user_id | INTEGER FK | 申請者 → users.id |
| material_id | INTEGER FK | 申請材料 → materials.id |
| requested_quantity | INTEGER | 申請數量 |
| status | VARCHAR(10) | `PENDING` / `APPROVED` / `REJECTED` |
| reviewed_by | INTEGER FK | → users.id |
| reviewed_at | DATETIME | |

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

### 4.7 user_retention_rates 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| user_id | INTEGER FK | |
| field | VARCHAR(50) | 工項欄位名 |
| rate | INTEGER | 客製費率（NTD/只）|

> **大表用戶與 ADMIN 不使用此表**：兩者保留金固定為 0，系統不計算也不顯示保留金。

### 4.8 audit_logs 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| user_id | INTEGER FK | 操作者 |
| action_type | VARCHAR(50) | 操作類型 |
| description | TEXT | 人可讀描述 |
| created_at | DATETIME | UTC+8 |

### 4.9 ledger_entries 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| entry_date | DATE | 記帳日期 |
| description | VARCHAR(200) | |
| amount | INTEGER | NTD 正整數 |
| entry_type | VARCHAR(10) | `INCOME` / `EXPENSE` |
| category | VARCHAR(50) | |
| note | TEXT | |
| receipt_key | VARCHAR(300) | R2 object key |
| receipt_name | VARCHAR(200) | 原始檔名 |
| created_by | INTEGER FK | |
| payer_id | INTEGER FK | 員工墊付時填入；NULL = 公司付款 |
| created_at / updated_at | DATETIME | |

### 4.10 report_archives 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| report_type | VARCHAR(10) | `DAILY` / `MONTHLY` |
| report_date | DATE | 基準日 |
| period_start / period_end | DATE | 涵蓋範圍 |
| r2_key_excel | VARCHAR(300) | |
| source | VARCHAR(10) | `auto` / `manual` |
| generated_by | INTEGER FK | NULL = 自動排程 |
| generated_at | DATETIME | |

---

## 5. 認證與授權

### 5.1 認證流程

1. POST `/login`，輸入 `display_name` + `password`（下拉選單選帳號）
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

### 5.3 路由權限表

| 路由 | 方法 | 需登入 | 需 ADMIN |
|------|------|--------|----------|
| `/login` | GET/POST | ✗ | ✗ |
| `/logout` | GET | ✓ | ✗ |
| `/report` | GET/POST | ✓ | USER only |
| `/api/collab-users` | GET | ✓ | USER only |
| `/history` | GET | ✓ | ✗ |
| `/history/<id>/edit` | POST | ✓ | ✗ |
| `/history/<id>/delete` | POST | ✓ | ✗ |
| `/materials` | GET | ✓ | ✗ |
| `/materials/request` | POST | ✓ | USER only |
| `/materials/requests/<id>/cancel` | POST | ✓ | USER only |
| `/audit` | GET | ✓ | ✗ |
| `/personal_stats` | GET/POST | ✓ | USER only |
| `/summary` | GET | ✓ | ✓ |
| `/confirmation` | GET | ✓ | ✓ |
| `/confirmation/report/<id>/confirm` | POST | ✓ | ✓ |
| `/confirmation/report/<id>/reject` | POST | ✓ | ✓ |
| `/confirmation/material/<id>/approve` | POST | ✓ | ✓ |
| `/confirmation/material/<id>/reject` | POST | ✓ | ✓ |
| `/bm_confirmation` | GET | ✓ | ✓ |
| `/bm_confirmation/report/<id>/confirm` | POST | ✓ | ✓ |
| `/bm_confirmation/report/<id>/reject` | POST | ✓ | ✓ |
| `/salary` | GET/POST | ✓ | ✓ |
| `/settings` | GET | ✓ | ✗ |
| `/settings/users/create` | POST | ✓ | ✓ |
| `/settings/users/<id>/...` | POST | ✓ | ✓\* |
| `/settings/users/<id>/toggle-big-meter` | POST | ✓ | ✓ |
| `/settings/tax-rate` | POST | ✓ | ✓ |
| `/settings/retention-rate` | POST | ✓ | ✓ |
| `/settings/retention-rate-south` | POST | ✓ | ✓ |
| `/settings/tax-rate-south` | POST | ✓ | ✓ |
| `/settings/item-prices` | POST | ✓ | ✓ |
| `/settings/item-prices-south` | POST | ✓ | ✓ |
| `/settings/item-prices-bm` | POST | ✓ | ✓ |
| `/ledger` | GET | ✓ | ✓ |
| `/report_archives` | GET | ✓ | ✓ |
| `/admin/migrate-bank-encrypt` | GET | ✓ | ✓ |

> \* `/settings/users/<id>/password` 亦允許用戶修改自身密碼

---

## 6. 路由與頁面邏輯

### 6.1 `/report` — 回報頁面（USER only）

**GET**: 依 `current_user.is_big_meter` 決定顯示 `BIG_METER_FIELDS`（26 欄）；否則依 `current_user.zone` 決定 `WEST_REPORT_FIELDS`（31 欄）或 `SOUTH_REPORT_FIELDS`（36 欄）。

**POST**: 同 v1.0.4，解析對應欄位值並存入 Report。

### 6.2 `/bm_confirmation` — 大表確認頁（ADMIN only，v1.0.5 新增）

獨立於一般確認頁，僅顯示 `is_big_meter=True` 用戶的待確認回報，顯示 26 個大表工項欄位。操作（確認/駁回）與一般確認頁相同邏輯。

### 6.3 `/confirmation` — 一般確認頁（ADMIN）

僅顯示非大表用戶（`is_big_meter=False`）的待確認回報。

### 6.4 `/salary` — 薪資計算（ADMIN）

詳見第 10 節。`action`：`calculate`、`export-excel`、`export-pdf`、`export-transfer`

### 6.5 其他路由

與 v1.0.4 相同（`/history`、`/summary`、`/settings`、`/ledger`、`/report_archives`、`/personal_stats`）。

---

## 7. 南/西區分區系統

（與 v1.0.4 相同，詳見 v1.0.4 規格書第 7 節）

### 7.1 常數定義

```python
ZONE_WEST  = '西區'
ZONE_SOUTH = '南區'
```

### 7.2 工項欄位集合

```python
WEST_REPORT_FIELDS  = [...] # 31 個 (key, label) tuple
SOUTH_REPORT_FIELDS = [...] # 36 個 (key, label) tuple

def get_zone_fields(zone: str) -> list:
    return SOUTH_REPORT_FIELDS if zone == ZONE_SOUTH else WEST_REPORT_FIELDS
```

### 7.3 保留金欄位集合

```python
WEST_RETENTION_FIELDS  = ['direct_13','direct_20','direct_25','direct_40',
                           'indirect_13','indirect_20','indirect_25','indirect_40']  # 8 欄

SOUTH_RETENTION_FIELDS = [...]  # 28 欄（含換由令、換開關、固拆等）

def get_zone_retention_fields(zone: str) -> list:
    return SOUTH_RETENTION_FIELDS if zone == ZONE_SOUTH else WEST_RETENTION_FIELDS
```

### 7.4 計價系統

SystemConfig key 規則：
- 西區：`price_{field}`
- 南區：`price_south_{field}`；找不到時 fallback 至 `price_{field}`

---

## 8. 大表（BM）用戶系統

### 8.1 設計目的

大型瓦斯表（50mm 以上口徑）施工由特定員工負責，其工項種類、計價與一般西/南區完全不同，且無保留金制度。以 `user.is_big_meter = True` 標記大表用戶，獨立管理。

### 8.2 工項欄位（26 欄，`BIG_METER_FIELDS`）

分三組顯示：

| 組別 | 欄位數 | 欄位前綴 |
|------|--------|----------|
| 下（地下施工）| 7 | `bm_*_down` |
| 上（地上施工）| 6 | `bm_*_up` |
| 其他工項 | 13 | `bm_rm_*`, `bm_hole`, `bm_clean_big`, `bm_truck`, `bm_mobilization`, `bm_recheck`, `bm_app`, `bm_40_fen` |

`bm_40_fen`（40MM分）為 v1.0.5 新增，預設單價 150 NTD。

### 8.3 計價

```python
DEFAULT_PRICES_BM = {
    'bm_50_down': ..., 'bm_75_down': ..., ...
    'bm_40_fen': 150.0,   # v1.0.5 新增
}

def get_item_prices_bm() -> dict:
    # 從 SystemConfig 讀取 price_bm_{field}，快取 TTL 300s
    ...
```

### 8.4 薪資計算特殊規則

| 項目 | 大表用戶 | 一般 USER |
|------|----------|-----------|
| 使用欄位 | `BIG_METER_FIELDS` | 依 zone |
| 計價 | `bm_prices` | 依 zone 計價 |
| 保留金 | **0（不計算）** | 依 zone 費率計算 |
| 固定薪資 | 依 `is_10th_payday` / `fixed_salary_every_period` | 同左 |

### 8.5 報表（日月報 Excel）

大表用戶的只數彙總與西/南區**分離**，在 Excel 中以獨立「大表」區塊（深綠色標頭 `1F5C2E`）呈現，不混入西區欄位。

### 8.6 確認流程

大表回報走獨立確認頁 `/bm_confirmation`，避免與一般回報混淆。

### 8.7 設定頁顯示

- 大表用戶不顯示保留金重置（偏移量）與保留金費率按鈕
- ADMIN 可在帳戶列點「大表」切換按鈕開關 `is_big_meter`
- 大表工項單價在「大表工項單價」獨立區塊設定（`/settings/item-prices-bm`）

---

## 9. 共同作業系統

（與 v1.0.4 相同）

### 9.1 資料欄位

| 欄位 | 型別 | 說明 |
|------|------|------|
| `collab_count` | INTEGER | 含提交者在內的總人數；1 = 單人作業 |
| `collab_json` | TEXT | JSON list of additional user_ids（不含提交者）|

### 9.2 只數分配演算法（ceil/floor）

設原始只數 = `q`，共作人數 = `n`：

```python
submitter_share = math.ceil(q / n)   # 提交者
collab_share    = math.floor(q / n)  # 每位協作者
```

**數學保證**: `ceil(q/n) + (n-1) × floor(q/n) = q`

### 9.3 應用場景

| 功能 | 分配方式 |
|------|----------|
| `/summary` 統計報表 | ceil/floor |
| `/personal_stats` 個人統計 | ceil/floor |
| `/salary` 薪資計算 | float 除法（`qty / n`）|
| Excel/PDF qty 欄 | `round(float(total), 1)` |

---

## 10. 薪資計算邏輯（核心業務）

### 10.1 計算流程

```
輸入：start_date, end_date, is_10th_payday（boolean）

Step 1: 查詢範圍內「所有已確認回報」（含停用帳戶回報）
Step 2: 建立 user_data dict（含 collab_json 展開）
  - 每筆回報：float(qty) / n 累加（提交者 + 協作者）
  - user_data 記錄 is_big_meter 和 is_admin 旗標
Step 3: 補入有固定薪資但本期無回報的帳戶
Step 4: 批次查詢各帳戶保留金費率
Step 5: 對每位用戶計算（依類型套用不同規則）：
  a. 工項薪資毛額（BM 用戶用 bm_prices；其他依 zone）
  b. 保留金（大表用戶 = 0；ADMIN = 0；一般 USER 依 zone 費率）
  c. 固定薪資（依 is_10th_payday 或 fixed_salary_every_period）
  d. 勞健保（is_10th_payday 時才扣）
  e. 稅務支出（未投保且非免稅：毛額 × zone 稅率%）
  f. 最終薪資 = 毛額 − 保留金 + 固定薪資 − 勞健保 − 稅務
Step 6: 過濾（gross_salary=0 AND final_salary=0 的帳戶不顯示）
```

### 10.2 用戶類型矩陣

| 類型 | 工項欄位 | 計價 | 保留金 |
|------|----------|------|--------|
| 大表用戶（`is_big_meter=True`）| `BIG_METER_FIELDS` | `bm_prices` | 0 |
| ADMIN | 依 zone（不回報，通常 0）| 依 zone | 0 |
| 西區 USER | `WEST_REPORT_FIELDS` | `west_prices` | 依費率計算 |
| 南區 USER | `SOUTH_REPORT_FIELDS` | `south_prices` | 依費率計算 |

### 10.3 固定薪資發放規則

```python
every_period = bool(u and u.fixed_salary_every_period)
fixed = (u.fixed_salary if u else 0) if (is_10th_payday or every_period) else 0
```

| `is_10th_payday` | `fixed_salary_every_period` | 固定薪資發放 |
|------------------|-----------------------------|--------------|
| True | 任意 | ✓ |
| False | True | ✓（特例帳戶每期發放）|
| False | False | ✗ |

### 10.4 零薪資過濾（v1.0.5 新增）

```python
user_data = {uid: d for uid, d in user_data.items()
             if d['gross_salary'] != 0 or d['final_salary'] != 0}
```

有固定薪資設定但本期不發放（非 10 號且 `fixed_salary_every_period=False`），且無任何工作回報的帳戶，不出現在薪資明細中。

### 10.5 10號 / 25號發薪差異

| 項目 | 25號發薪 | 10號發薪 |
|------|----------|----------|
| 工項薪資 | ✓ | ✓ |
| 保留金扣除 | ✓ | ✓ |
| 固定薪資（一般）| ✗ | ✓ |
| 固定薪資（every_period）| ✓ | ✓ |
| 勞健保扣除 | ✗ | ✓ |
| 稅務支出 | 視情況 | 視情況 |

### 10.6 帳戶投保狀態矩陣

| `insurance_deduction` | `tax_exempt` | 行為 |
|-----------------------|--------------|------|
| > 0 | — | 已投保：10號扣固定勞健保，不扣稅 |
| 0 | False | 未投保需扣稅：扣工項毛額 × zone 稅率% |
| 0 | True | 未投保免稅：不扣勞健保也不扣稅 |

### 10.7 停用帳戶

已確認回報代表公司應支付的工作成果，停用帳戶薪資照常計算並在名稱旁標示「停用」badge。

---

## 11. 保留金系統

### 11.1 適用範圍

**僅適用於 `is_big_meter=False` 且 `role != 'ADMIN'` 的 USER**。

```python
RETENTION_CAP = 60000  # NTD，年度累計上限
```

### 11.2 欄位集合

- **西區**：`WEST_RETENTION_FIELDS`（8 欄：direct/indirect 各 4 口徑）
- **南區**：`SOUTH_RETENTION_FIELDS`（28 欄：含換由令、換開關、固拆等）
- **大表/ADMIN**：不適用（`ret_fields = []`，保留金固定 0）

### 11.3 費率優先順序

1. `UserRetentionRate` 表有記錄 → 客製費率
2. 無記錄 → 對應區域全域費率（`retention_rate` 或 `retention_rate_south`）

### 11.4 計算邏輯

```python
pre_calc   = Σ(pre_totals[f] × user_rates[f] for f in zone_retention_fields)
ytd_before = min(RETENTION_CAP, max(0.0, pre_calc + u.retention_offset))
period_ret_raw = Σ(period_totals[f] × user_rates[f] for f in zone_retention_fields)
period_retention = max(0.0, min(period_ret_raw, RETENTION_CAP - ytd_before))
```

---

## 12. 匯出功能

### 12.1 薪資 Excel（openpyxl）

每位用戶一個工作表：
- 大表用戶：使用 `BIG_METER_FIELDS` + `bm_prices`，標頭標示「大表」
- 西/南區 USER：依 zone 使用對應欄位與計價

**只數欄位顯示**: `round(float(val), 1)`。

**欄寬自動調整**: 內容長度 / 0.7，上限 60，下限 8。

### 12.2 日月報 Excel（`_report_excel()`）

多 Sheet 結構，大表用戶以獨立「大表」區塊（深綠色標頭）呈現，不混入西/南區統計。

| 區塊顏色（標頭）| 說明 |
|----------------|------|
| `2F75B6`（藍）| 西區 |
| `7030A0`（紫）| 南區 |
| `1F5C2E`（深綠）| 大表 |

月報第四 Sheet 為薪資彙總，大表/ADMIN 用戶保留金顯示 0。

### 12.3 薪資 PDF（reportlab）

使用 `STSong-Light` CID font，Windows fallback `msjh.ttc`。

### 12.4 Word 薪轉單（python-docx）

僅包含 `payment_method=='TRANSFER'` 且 `final_salary > 0` 的帳戶。

---

## 13. 材料管理

（與 v1.0.4 相同）

申請流程：USER 提交（PENDING）→ ADMIN 審核 → APPROVED/REJECTED；庫存自動扣減。

---

## 14. 流水帳（LedgerEntry）

（與 v1.0.3 相同）子路由：`/ledger/add`、`/ledger/<id>/edit`、`/ledger/<id>/delete`、`/ledger/<id>/settle`、`/ledger/<id>/receipt`。

---

## 15. 日月報檔案庫（ReportArchive）

（與 v1.0.3 相同）自動排程：每日 23:59（日報）、每月最後一天 23:59（月報）。R2 路徑格式：
- 日報：`reports/daily/{YYYY}/{YYYYMMDD}_daily.xlsx`
- 月報：`reports/monthly/{YYYY}/{YYYYMM}_monthly.xlsx`

---

## 16. Cloudflare R2 儲存

### 16.1 環境變數

| 變數 | 說明 |
|------|------|
| `R2_ACCOUNT_ID` | Cloudflare 帳號 ID |
| `R2_ACCESS_KEY_ID` | API Token Access Key |
| `R2_SECRET_ACCESS_KEY` | API Token Secret |
| `R2_BUCKET_NAME` | Bucket 名稱 |

R2 未設定時靜默失敗，下載按鈕隱藏。

---

## 17. 變動紀錄（Audit Log）

### 17.1 Action Types

| action_type | 觸發時機 |
|-------------|----------|
| `REPORT_CREATE` | 新增回報 |
| `REPORT_UPDATE` | 修改回報 |
| `REPORT_DELETE` | 刪除回報 |
| `REPORT_CONFIRM` | ADMIN 確認回報 |
| `REPORT_UNCONFIRM` | ADMIN 取消確認 |
| `REPORT_REJECT` | ADMIN 駁回回報 |
| `ACCOUNT_CREATE` | 新增帳戶 |
| `ACCOUNT_UPDATE` | 更新帳戶資訊（含 is_big_meter、fixed_salary_every_period）|
| `ACCOUNT_DEACTIVATE` | 停用帳戶 |
| `ACCOUNT_REACTIVATE` | 復原帳戶 |
| `ACCOUNT_DELETE` | 永久刪除帳戶 |
| `PASSWORD_CHANGE` | 密碼變更 |
| `MATERIAL_REQUEST` | 材料申請 |
| `MATERIAL_CANCEL` | 取消材料申請 |
| `MATERIAL_ADD` | 新增材料品項 |
| `MATERIAL_UPDATE` | 更新材料庫存 |
| `MATERIAL_DELETE` | 刪除材料品項 |
| `MATERIAL_APPROVE` | 核准材料申請 |
| `MATERIAL_REJECT` | 拒絕材料申請 |
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
   - `insurance_deduction`, `sort_order`, `retention_offset`, `tax_exempt`
   - `is_rejected`, `bank_account VARCHAR(200)`, `fixed_salary`
   - `source`, `payer_id`, `generated_by`（ledger/archive 相關）
   - `zone`（v1.0.4）
   - **工項型別升級**：`ALTER COLUMN {col} TYPE NUMERIC(8,1)`（v1.0.4）
   - 西區拆分欄位（15 欄）、南區欄位（22 欄）、`collab_count`, `collab_json`（v1.0.4）
   - `is_big_meter BOOLEAN NOT NULL DEFAULT FALSE`（v1.0.5）
   - 大表工項欄位（26 欄，`bm_*`，含 v1.0.5 新增 `bm_40_fen`）
   - `fixed_salary_every_period BOOLEAN NOT NULL DEFAULT FALSE`（v1.0.5）
3. `CREATE INDEX IF NOT EXISTS`（含 GIN index）
4. Seed SystemConfig 預設值（含大表計價 `price_bm_*`）

### 18.2 v1.0.5 新增欄位一覽

```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_big_meter BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS fixed_salary_every_period BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS bm_40_fen NUMERIC(8,1) DEFAULT 0;
-- （其餘 25 個 bm_* 欄位已於 v1.0.4 或更早版本新增）
```

### 18.3 新增欄位流程

1. `models.py` 新增 Column
2. `_init_db()` 加入 try/except ALTER TABLE 區塊
3. 相關路由加入讀寫邏輯 → git push → Railway 自動執行

> **注意**: 不使用 Flask-Migrate/Alembic，所有 migration 手動管理。

---

## 19. 前端架構

### 19.1 base.html

- 左側固定側欄（220px），收合時 52px
- 側欄狀態存於 `localStorage.ycSidebarCollapsed`
- Loading overlay：點連結/提交表單時顯示

### 19.2 Jinja2 Template Filters

| Filter | 說明 |
|--------|------|
| `\| qty` | 整數顯示為 `3`，帶小數顯示為 `3.1`，零顯示為空字串 |
| `\| money` | 千位分隔，整數省略小數點 |
| `\| from_json` | JSON string → Python list，錯誤返回 `[]` |
| `\| report_json` | Report ORM object → JSON string（含所有工項欄位 + collab meta）|
| `\| tw_time` | datetime → `'YYYY-MM-DD HH:MM'` 格式 |

### 19.3 _pagination.html macro

```jinja2
{% macro paginate(pagination, endpoint, url_args, page_param='page') %}
```

支援 `page_param`，允許同頁面多個分頁控件。

---

## 20. 設定系統（SystemConfig）

### 20.1 工項單價快取

```python
_price_cache_west:  dict = {}
_price_cache_south: dict = {}
_price_cache_bm:    dict = {}
_PRICE_CACHE_TTL = 300  # 5 分鐘
```

呼叫 `_invalidate_price_cache()` 立即清除三個區域快取。

### 20.2 費率快取

```python
_config_cache: dict = {}
_CONFIG_CACHE_TTL = 60  # 60 秒
```

`_get_config(key)` 在快取過期時一次 `SELECT *` 載入所有 SystemConfig 行。

---

## 21. 效能優化機制

### 21.1 查詢優化彙整

| 優化項目 | 舊版 | 新版 | 節省 |
|----------|------|------|------|
| `get_item_prices_for_zone()` cache miss | N 次 SELECT | 1 次 IN 查詢 | ~97% |
| 費率/稅率查詢（每次請求）| 4–6 次 SELECT | 0 次（60s 快取）| 100% |
| `confirmation()` GET | 載入全部 users + materials | 只載當頁所需 | 全表→頁面所需 |
| collab_json JSONB 搜尋 | Seq Scan | GIN Index | 全表掃描→索引 |

### 21.2 Supabase 連線池

```python
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 1800,
    'pool_size': 3,
    'max_overflow': 3,
}
```

---

## 22. 已知限制與注意事項

### 22.1 每人每日一筆回報

無 DB UNIQUE 約束強制。業務邏輯在 `/report` POST handler 中處理。

### 22.2 稅務計算基數

稅務支出計算基數為「工項薪資毛額」，不含固定薪資。此為業務決策，非 bug。

### 22.3 保留金年度邊界

以「計薪起始日的年份」決定年度（`date(sd.year, 1, 1)`），跨年度計薪可能有邊界問題。

### 22.4 速率限制 memory backend

Flask-Limiter 使用 `memory://` backend，不跨 worker/重啟持久化。高安全性環境應改用 Redis backend。

### 22.5 工項單價快取多 worker

`get_item_prices_*()` 為 process-level 快取，多 worker 部署時更新後最多 300 秒才全部刷新。

### 22.6 費率快取多 worker

`_config_cache` 同為 process-level，TTL 60 秒。

### 22.7 銀行帳號加密金鑰管理

`BANK_ENCRYPT_KEY` 遺失後無法解密現有帳號。應妥善保管，更換前需先執行資料遷移。

### 22.8 R2 presigned URL 有效期

Presigned URL 有效期 3600 秒。請勿儲存此 URL，每次存取應重新產生。

### 22.9 APScheduler 單 worker 限制

多 worker 部署時可能造成重複生成報表。當前部署為單 worker，無此問題。多 worker 需改用 Celery + Redis。

### 22.10 JSONB GIN index 僅支援 PostgreSQL

`collab_json::jsonb @> '[uid]'` 搜尋依賴 PostgreSQL JSONB 語法。SQLite（本地開發）不支援此語法。**建議本地開發亦使用 Supabase PostgreSQL**。

### 22.11 大表用戶 zone 欄位

大表用戶仍有 `zone` 欄位（預設 `'西區'`），但計薪時不使用 zone 決定欄位或計價，僅用於帳戶列表分組顯示。

---

*最後更新: 2026-07-09 | 版本: v1.0.5 | 由 Claude Sonnet 4.6 輔助生成*
