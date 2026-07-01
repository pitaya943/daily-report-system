# 員工日報回報系統 — 系統規格書

> **版本**: v1.0.3
> **日期**: 2026-07-01
> **狀態**: 已實作（反映當前生產環境實際運作狀態）
> **維護工程師參考文件**

---

## 版本變更紀錄

| 版本 | 日期 | 變更摘要 |
|------|------|----------|
| v1.0.3 | 2026-07-01 | UTC+8 時間儲存；流水帳（LedgerEntry）+ 憑證 R2 上傳；日月報檔案庫（ReportArchive）+ R2 存儲；薪資計算涵蓋停用帳戶；Excel 欄寬修正；月報 YTD 保留金修正；流水帳 Audit Log 修正 |
| v1.0.2 | 2026-06-30 | 安全強化（CSRF/速率限制/Session/標頭/銀行帳號加密）；擴展性優化（批次查詢/TTL快取/確認頁篩選）；連帶刪除 FK 修正；材料申請分頁 |
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
7. [薪資計算邏輯（核心業務）](#7-薪資計算邏輯核心業務)
8. [保留金系統](#8-保留金系統)
9. [匯出功能](#9-匯出功能)
10. [材料管理](#10-材料管理)
11. [流水帳（LedgerEntry）](#11-流水帳ledgerentry)
12. [日月報檔案庫（ReportArchive）](#12-日月報檔案庫reportarchive)
13. [Cloudflare R2 儲存](#13-cloudflare-r2-儲存)
14. [變動紀錄（Audit Log）](#14-變動紀錄audit-log)
15. [資料庫初始化與 Migration](#15-資料庫初始化與-migration)
16. [前端架構](#16-前端架構)
17. [設定系統（SystemConfig）](#17-設定系統systemconfig)
18. [已知限制與注意事項](#18-已知限制與注意事項)

---

## 1. 系統概述

### 1.1 目的

本系統為工程隊管理工具，提供：

- 員工每日施工工項回報（瓦斯管線施工數量）
- ADMIN 確認/駁回回報紀錄
- 基於確認回報自動計算薪資（工項計價 + 固定薪資 + 保留金 + 勞健保 + 稅務）
- **停用帳戶的已確認回報仍納入薪資計算，並標註（停用）**
- 材料庫存管理與申請流程
- 公司收支流水帳（含憑證上傳至 Cloudflare R2）
- 日月報自動/手動生成並存儲至 Cloudflare R2
- 薪資轉帳文件匯出（Excel/PDF/Word）
- 完整操作稽核日誌

### 1.2 使用者規模

- 設計容量：≤ 10 ADMIN + ≤ 75 USER（共 85 人）
- 資料量：每月約 85 × 22 = 1,870 筆回報；年度約 22,440 筆

### 1.3 應用程式入口

- `app.py`: 所有路由、業務邏輯、匯出功能、安全設定（~3,600+ 行）
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
- 選擇邏輯：`DATABASE_URL` 存在時使用 PostgreSQL，否則 SQLite

```python
if os.environ.get('DATABASE_URL'):
    db_url = os.environ['DATABASE_URL'].replace('postgres://', 'postgresql://', 1)
else:
    db_url = 'sqlite:///app.db'
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

### 2.5 時間處理（v1.0.3 新增）

系統所有時間戳均以 **UTC+8（台灣時間）** 的 naive datetime 儲存於資料庫。

```python
def tw_now():
    """回傳目前台灣時間（UTC+8）的 naive datetime。"""
    return datetime.utcnow() + timedelta(hours=8)

@app.template_filter('tw_time')
def tw_time_filter(dt):
    """顯示已按 UTC+8 儲存的 datetime。"""
    if dt is None:
        return ''
    return dt.strftime('%Y-%m-%d %H:%M')
```

`models.py` 中所有 `default=datetime.utcnow` 已全數改為 `default=_tw_now`（模組層級同名函數）。

**注意**: 資料庫儲存的是 UTC+8 naive datetime（無 timezone info），`tw_time` filter 僅做格式化，不加任何時區偏移。

### 2.6 定時任務（APScheduler）

```python
scheduler = BackgroundScheduler(timezone='Asia/Taipei')
# 每日 23:59 自動生成日報
scheduler.add_job(auto_daily_report, CronTrigger(hour=23, minute=59))
# 每月最後一天 23:59 自動生成月報
scheduler.add_job(auto_monthly_report, CronTrigger(day='last', hour=23, minute=59))
scheduler.start()
```

---

## 3. 安全機制

### 3.1 CSRF 保護（SEC-001 ✅ 已修復）

使用 Flask-WTF `CSRFProtect`，全域啟用：

```python
from flask_wtf.csrf import CSRFProtect
csrf = CSRFProtect(app)
```

所有 POST 表單均在第一行加入：
```html
<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

缺少 token 的 POST 請求回傳 **400 Bad Request**。

### 3.2 登入速率限制（SEC-003 ✅ 已修復）

使用 Flask-Limiter，限制 `/login` 端點：

```python
limiter = Limiter(get_remote_address, app=app, default_limits=[], storage_uri='memory://')

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute')
def login(): ...
```

同一 IP 每分鐘超過 10 次登入嘗試 → 回傳 **429 Too Many Requests**。

> **注意**: memory backend 不跨 worker 共享狀態。多 worker 部署需改用 Redis backend。

### 3.3 Session 安全（SEC-005 ✅ 已修復）

```python
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=10)
app.config['SESSION_COOKIE_HTTPONLY']    = True
app.config['SESSION_COOKIE_SAMESITE']   = 'Lax'
app.config['SESSION_COOKIE_SECURE']     = not app.debug  # 生產 HTTPS = True
```

登入時設定 `session.permanent = True`，確保 10 分鐘閒置後自動登出。

### 3.4 SECRET_KEY 驗證（SEC-002 ✅ 已修復）

```python
_sk = os.environ.get('SECRET_KEY')
if not _sk:
    logging.warning('SECRET_KEY env var not set — using hardcoded fallback (unsafe for production)')
app.config['SECRET_KEY'] = _sk or 'daily-report-secret-2026-yc-local'
```

未設定環境變數時 app 仍啟動（不 crash），但在 log 顯示警告。**生產環境必須設定 `SECRET_KEY`**。

### 3.5 銀行帳號加密（SEC-007 ✅ 已修復）

使用 Fernet 對稱加密，金鑰由環境變數 `BANK_ENCRYPT_KEY` 控制。加密後 token 約 88 字元，儲存於 `VARCHAR(200)` 欄位。`BANK_ENCRYPT_KEY` 未設定時以明文儲存，功能不中斷。

### 3.6 HTTP 安全標頭（SEC-008 ✅ 已修復）

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
users ──< reports              (user_id FK + confirmed_by FK)
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
| is_active | BOOLEAN | False = 停用（無法登入）|
| payment_method | VARCHAR(10) | `'TRANSFER'` 或 `'CASH'` |
| insurance_deduction | INTEGER | 勞健保固定扣除額（NTD）；0 = 未投保 |
| tax_exempt | BOOLEAN | True = 未投保免稅；False = 未投保需扣稅 |
| bank_account | VARCHAR(200) | Fernet 加密 token 或明文 14 碼（降級模式）|
| fixed_salary | INTEGER | 固定月薪（10號發薪時加入）；預設 0 |
| retention_offset | INTEGER | ADMIN 手動調整保留金累計（可負值）|
| created_at / updated_at | DATETIME | UTC+8 naive datetime |

### 4.3 reports 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| user_id | INTEGER FK | → users.id（回報者）|
| report_date | DATE | 回報日期（每人每天最多一筆，業務邏輯防重）|
| direct_13 ~ soil_clearing | INTEGER | 21 個工項數量欄位（預設 0）|
| is_confirmed | BOOLEAN | ADMIN 已確認 |
| confirmed_by | INTEGER FK | → users.id（確認者；ADMIN 刪除時置 NULL）|
| confirmed_at | DATETIME | 確認時間（UTC+8）|
| is_rejected | BOOLEAN | ADMIN 已駁回 |
| created_at / updated_at | DATETIME | UTC+8 naive datetime |

**工項欄位清單**（共 21 欄）:

```
direct_13, direct_20, direct_25, direct_40       — 直總管 13/20/25/40mm
indirect_13, indirect_20, indirect_25, indirect_40 — 間接管
original_change                                   — 原改
direct_switch_valve, indirect_switch_valve        — 換由令（直/間）
switch_valve_13_25, switch_valve_40              — 換開關 13~25 / 40
direct_fixed_13_25, direct_fixed_40              — 直總固拆
indirect_fixed_13_25, indirect_fixed_40          — 間接固拆
pipe_repair, mobilization, recheck, soil_clearing — 管修/動員/複查/清積土
```

**索引**:
- `ix_reports_user_date` (user_id, report_date)
- `ix_reports_date_confirmed` (report_date, is_confirmed)
- `ix_reports_user_confirmed` (user_id, is_confirmed)

### 4.4 materials 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| name | VARCHAR(100) | 材料名稱 |
| unit | VARCHAR(20) | 單位（支/個/包…）|
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
| reviewed_by | INTEGER FK | → users.id（審核者）|
| reviewed_at | DATETIME | 審核時間（UTC+8）|

**索引**: `ix_mat_req_user_id`, `ix_mat_req_status`

### 4.6 system_config 表（Key-Value）

| Key | 說明 | 預設值 |
|-----|------|--------|
| `retention_rate` | 全域保留金費率(%) | 20 |
| `tax_rate` | 稅務費率(%) | 3 |
| `price_{field}` | 各工項單價（NTD）| 見 DEFAULT_PRICES |

### 4.7 user_retention_rates 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| user_id | INTEGER FK | |
| field | VARCHAR(50) | 工項欄位名（如 `direct_13`）|
| rate | INTEGER | 客製費率(%) |

若某 user+field 無記錄，則使用全域 `retention_rate`。

### 4.8 audit_logs 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| user_id | INTEGER FK | 操作者 → users.id |
| action_type | VARCHAR(50) | 操作類型（見第 14 節）|
| description | TEXT | 人可讀描述 |
| created_at | DATETIME | UTC+8 naive datetime |

**索引**: `ix_audit_logs_created_at`, `ix_audit_logs_user_id`, `ix_audit_logs_action_type`

### 4.9 ledger_entries 表（v1.0.3 新增）

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| entry_date | DATE | 記帳日期 |
| description | VARCHAR(200) | 描述 |
| amount | INTEGER | NTD，正=收入，負=支出 |
| entry_type | VARCHAR(10) | `'INCOME'` 或 `'EXPENSE'` |
| category | VARCHAR(50) | 類別（材料費/人工費/雜支/工程款…）|
| note | TEXT | 備註 |
| receipt_key | VARCHAR(300) | Cloudflare R2 object key |
| receipt_name | VARCHAR(200) | 原始憑證檔名 |
| created_by | INTEGER FK | → users.id（建立者）|
| payer_id | INTEGER FK | → users.id（支出者；NULL=公司）|
| created_at / updated_at | DATETIME | UTC+8 naive datetime |

**索引**: `ix_ledger_date (entry_date)`, `ix_ledger_type (entry_type)`

**沖銷邏輯**: `payer_id` 非 NULL 時代表由該員工先行墊付；介面顯示時標示「員工墊付」。

### 4.10 report_archives 表（v1.0.3 新增）

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| report_type | VARCHAR(10) | `'DAILY'` 或 `'MONTHLY'` |
| report_date | DATE | 報表基準日 |
| period_start | DATE | 涵蓋期間起始 |
| period_end | DATE | 涵蓋期間結束 |
| r2_key_excel | VARCHAR(300) | R2 Excel 物件鍵 |
| r2_key_pdf | VARCHAR(300) | R2 PDF 物件鍵（預留，目前未使用）|
| source | VARCHAR(10) | `'auto'`（排程）或 `'manual'`（ADMIN 手動）|
| generated_by | INTEGER FK | → users.id；NULL = 自動排程 |
| generated_at | DATETIME | UTC+8 naive datetime |

**索引**: `ix_report_archive_date`, `ix_report_archive_type`

**排序**: 列表頁以 `generated_at DESC, id DESC` 排序，最新生成在最前。

---

## 5. 認證與授權

### 5.1 認證流程

1. 使用者 POST `/login`，輸入 `display_name` + `password`
2. 速率限制檢查（10 次/分鐘/IP）
3. `User.query.filter_by(display_name=...).first()` 查詢用戶
4. `werkzeug.security.check_password_hash()` 驗證密碼
5. 帳號停用（`is_active=False`）→ 拒絕登入
6. 通過 → `flask_login.login_user(user)` + `session.permanent = True` 建立 session
7. 登出：`flask_login.logout_user()` + redirect to `/login`
8. 閒置 10 分鐘後 session 自動過期，下次請求重定向至 `/login`

### 5.2 授權裝飾器

```python
@login_required          # flask-login 提供；未登入 → 重定向 /login
@admin_required          # 自訂；非 ADMIN → abort(403)
```

### 5.3 路由權限表

| 路由 | 方法 | 需登入 | 需 ADMIN |
|------|------|--------|----------|
| `/login` | GET/POST | ✗ | ✗ |
| `/logout` | GET | ✓ | ✗ |
| `/report` | GET/POST | ✓ | ✗ |
| `/history` | GET | ✓ | ✗ |
| `/history/<id>/edit` | POST | ✓ | ✗ |
| `/history/<id>/delete` | POST | ✓ | ✗ |
| `/materials` | GET/POST | ✓ | ✗ |
| `/materials/cancel/<id>` | POST | ✓ | ✗ |
| `/audit` | GET | ✓ | ✗ |
| `/personal_stats` | GET/POST | ✓ | ✗ |
| `/summary` | GET/POST | ✓ | ✓ |
| `/confirmation` | GET | ✓ | ✓ |
| `/confirmation/report/<id>/confirm` | POST | ✓ | ✓ |
| `/confirmation/report/<id>/reject` | POST | ✓ | ✓ |
| `/confirmation/material/<id>/approve` | POST | ✓ | ✓ |
| `/confirmation/material/<id>/reject` | POST | ✓ | ✓ |
| `/salary` | GET/POST | ✓ | ✓ |
| `/settings` | GET | ✓ | ✓ |
| `/settings/users/...` | POST | ✓ | ✓\* |
| `/ledger` | GET | ✓ | ✓ |
| `/ledger/add` | POST | ✓ | ✓ |
| `/ledger/<id>/edit` | POST | ✓ | ✓ |
| `/ledger/<id>/delete` | POST | ✓ | ✓ |
| `/ledger/<id>/settle` | POST | ✓ | ✓ |
| `/ledger/<id>/receipt` | GET | ✓ | ✓ |
| `/report_archives` | GET | ✓ | ✓ |
| `/report_archives/manual` | POST | ✓ | ✓ |
| `/report_archives/<id>/download/<fmt>` | GET | ✓ | ✓ |
| `/report_archives/<id>/delete` | POST | ✓ | ✓ |
| `/admin/migrate-bank-encrypt` | GET | ✓ | ✓ |

> \* `/settings/users/<id>/password` 亦允許用戶修改自身密碼

---

## 6. 路由與頁面邏輯

### 6.1 `/report` — 回報頁面

**GET**: 顯示今日表單。若今日已有回報，預填現有數值（允許「修改今日回報」）。

**POST**:
1. 解析 21 個欄位值（`int`，預設 0）
2. 查詢當日是否已有回報
3. 有 → 更新；無 → 新增
4. `add_audit('REPORT_CREATE'/'REPORT_UPDATE', ...)`
5. Flash success，redirect

### 6.2 `/history` — 歷史紀錄

**GET**: 分頁查詢（`per_page=30`），支援篩選：
- USER: 只看自己的回報
- ADMIN: 可選擇指定帳戶 + 日期範圍

### 6.3 `/confirmation` — ADMIN 確認頁

**GET**: 分頁顯示未確認未駁回回報 + 待審材料申請

- 預設顯示最近 30 天；支援自訂日期範圍
- 材料申請 `per_page=20`，使用獨立 `mat_page` 分頁參數

### 6.4 `/salary` — 薪資計算

詳見第 7 節。支援 `action`：`calculate`、`export-excel`、`export-pdf`、`export-transfer`

### 6.5 `/settings` — 設定

帳戶管理、工項單價、稅率、保留金費率、材料管理（詳見 v1.0.2 SPEC）。

### 6.6 `/ledger` — 流水帳（v1.0.3 新增）

**GET**: 顯示流水帳列表，支援：
- 日期範圍篩選（`date_from`, `date_to`）
- 類型篩選（收入/支出/全部）
- 分頁（`per_page=25`）
- 期間合計（收入/支出/淨額）

**收入欄位**: 僅顯示給未設定 `payer_id` 的使用者（公司收款）；設定了 `payer_id` 的支出者可查看所有相關記錄。

**子路由**:

| 子路由 | 功能 |
|--------|------|
| POST `/ledger/add` | 新增記錄 + 選填上傳憑證至 R2 |
| POST `/ledger/<id>/edit` | 修改記錄（可換憑證）|
| POST `/ledger/<id>/delete` | 刪除記錄 + 從 R2 刪除憑證 |
| POST `/ledger/<id>/settle` | 標記沖銷（更新 payer_id 為 NULL 或特定狀態）|
| GET `/ledger/<id>/receipt` | 產生 R2 presigned URL → 重導下載 |

**Audit Log**: 所有 CRUD 操作皆於 `db.session.commit()` 前呼叫 `add_audit()`，確保記錄被提交。

### 6.7 `/report_archives` — 日月報檔案庫（v1.0.3 新增）

**GET**: 列出所有報表記錄（`generated_at DESC`），支援類型篩選和分頁。

**子路由**:

| 子路由 | 功能 |
|--------|------|
| POST `/report_archives/manual` | 手動觸發生成指定日期的日報或月報 |
| GET `/report_archives/<id>/download/<fmt>` | 產生 R2 presigned URL → 下載 Excel |
| POST `/report_archives/<id>/delete` | 刪除記錄 + 從 R2 刪除檔案 |

**自動生成**: APScheduler 於每日 23:59 和每月最後一天 23:59 觸發。生成後建立 `ReportArchive` 記錄，Excel 上傳至 R2，`source='auto'`，`generated_by=NULL`。

**手動生成**: ADMIN 在頁面輸入日期和類型後觸發；`source='manual'`，`generated_by=current_user.id`。

---

## 7. 薪資計算邏輯（核心業務）

### 7.1 計算流程（v1.0.3 修正：涵蓋停用帳戶）

```
輸入：start_date, end_date, is_10th_payday（boolean）

Step 1: 查詢範圍內「所有已確認回報」（不限帳戶狀態 — 含停用帳戶）
Step 2: 建立 user_data dict，含 is_deactivated 標記
Step 3: 補入有固定薪資但本期無回報的所有帳戶（含停用）
Step 4: 批次查詢各帳戶保留金費率（get_users_all_retention_rates）
Step 5: 對每位用戶計算：
  a. 工項薪資毛額 = Σ(欄位數量 × 單價)
  b. 本期保留金 = min(期間應扣, 年度上限剩餘空間)
  c. 淨薪資 = 毛額 - 保留金
  d. 若 is_10th_payday:
     - 固定薪資 = user.fixed_salary
     - 勞健保扣除 = user.insurance_deduction（已投保才扣）
  e. 稅務支出 = 毛額 × 稅率（未投保且非免稅帳戶）
  f. 最終薪資 = 淨薪資 + 固定薪資 - 勞健保 - 稅務支出
```

**停用帳戶處理邏輯**:
```python
# 不過濾停用帳戶 — 已確認回報代表公司應支付的工作成果
users_dict = {u.id: u for u in User.query.all()}

# 設定 is_deactivated 旗標
is_deact = (not u_obj.is_active) if u_obj else False
user_data[uid] = {'username': uname,
                  'is_deactivated': is_deact, ...}
```

**UI 顯示**: `salary.html` 在帳戶名稱旁加上灰色「停用」badge（title 說明仍需支付薪資原因）。

**Excel 顯示**: `_report_excel` 月報薪資匯總工作表中，停用帳戶顯示名稱為 `{display_name}（停用）`。

### 7.2 10號 / 25號發薪差異

| 項目 | 25號發薪 | 10號發薪 |
|------|----------|----------|
| 工項薪資 | ✓ | ✓ |
| 保留金扣除 | ✓ | ✓ |
| 固定薪資 | ✗ | ✓ |
| 勞健保扣除 | ✗ | ✓ |
| 稅務支出 | ✓（有時）| ✓（有時）|

### 7.3 帳戶投保狀態矩陣

| `insurance_deduction` | `tax_exempt` | 行為 |
|-----------------------|--------------|------|
| > 0 | — | 已投保：10號扣固定勞健保，不扣稅 |
| 0 | False | 未投保需扣稅：扣工項毛額 × 稅率% |
| 0 | True | 未投保免稅：不扣勞健保也不扣稅 |

### 7.4 薪轉單（Word）匯出邏輯

- 使用 `python-docx` 產生「板信商業銀行薪資轉帳送件單」
- 僅包含 `payment_method == 'TRANSFER'` 且 `final_salary > 0` 的帳戶
- 停用帳戶如有最終薪資亦包含在內

---

## 8. 保留金系統

### 8.1 設計目的

保留金是從工項薪資中預留的品質保證金，年底前達到上限後停扣。

### 8.2 參數

- `RETENTION_CAP = 60000`（NTD，年度累計上限）
- `RETENTION_FIELDS`：8 個欄位（direct/indirect 13/20/25/40mm）

### 8.3 計算邏輯（v1.0.3 月報 YTD 修正）

```python
# 本年度 1/1 至計薪起始日前的累計保留金（批次查詢，避免 N+1）
year_start = date(start_date.year, 1, 1)
pre_period_end = start_date - timedelta(days=1)
_pre_reports = Report.query.filter(
    Report.is_confirmed == True,
    Report.report_date >= year_start,
    Report.report_date <= pre_period_end
).all()
# 按用戶分組
pre_totals_by_user = {}
for _r in _pre_reports:
    ...

# Per-user YTD 計算
pre_calc = sum(pre_totals.get(f, 0) * u_rates[f] for f in RETENTION_FIELDS)
ytd_before = min(RETENTION_CAP, max(0.0, pre_calc + u.retention_offset))

# 本期應扣（不超過剩餘額度）
retention = max(0.0, min(ret_raw, RETENTION_CAP - ytd_before))
```

### 8.4 費率優先順序

1. `UserRetentionRate` 表有記錄 → 客製費率
2. 無記錄 → 全域 `retention_rate`（SystemConfig）

---

## 9. 匯出功能

### 9.1 Excel（openpyxl）

每位用戶一個工作表，含工項明細、保留金、固定薪資、稅務；最後一頁彙總表。

**欄寬自動調整（v1.0.3 修正）**:

```python
def auto_w(ws):
    from openpyxl.cell.cell import MergedCell
    # 排除跨多欄 merge 的 origin cell（如標題列），避免誇大欄寬
    mc_origins = set()
    for rng in ws.merged_cells.ranges:
        if rng.max_col > rng.min_col:
            mc_origins.add((rng.min_row, rng.min_col))
    for col in ws.columns:
        real_cells = [c for c in col if not isinstance(c, MergedCell)]
        if not real_cells:
            continue
        col_letter = real_cells[0].column_letter
        measure = [c for c in real_cells if (c.row, c.column) not in mc_origins]
        if not measure:
            continue
        w = max((len(str(c.value or '')) for c in measure), default=4)
        ws.column_dimensions[col_letter].width = max(8, min(round(w / 0.7), 60))
```

目標：欄寬 = 內容長度 / 0.7（內容佔 70% 欄寬，留餘白），上限 60，下限 8。

### 9.2 PDF（reportlab）

CJK 繁體中文支援，自動換頁流水表格。

### 9.3 Word 薪轉單（python-docx）

嚴格符合「板信商業銀行薪資轉帳送件單」格式，銀行帳號格式化為 `XXXX-XXX-XXXXXXX`。

---

## 10. 材料管理

### 10.1 申請流程

```
USER 提交申請（status=PENDING）
    ↓ ADMIN 審核（/confirmation，20 筆分頁）
  核准 → status=APPROVED，material.remaining_quantity -= qty
  拒絕 → status=REJECTED，庫存不變
    ↓
USER 可取消 PENDING 狀態的申請
```

### 10.2 庫存保護

核准時若 `remaining_quantity < requested_quantity` → 拒絕，不扣庫存，flash 錯誤。

---

## 11. 流水帳（LedgerEntry）

### 11.1 設計目的

記錄公司日常收支，含憑證（發票/收據）上傳，並支援員工墊付沖銷。

### 11.2 欄位說明

| 欄位 | 說明 |
|------|------|
| `entry_type` | `INCOME`（收入）或 `EXPENSE`（支出）|
| `amount` | 正整數 NTD（儲存時統一為正值，`entry_type` 決定方向）|
| `payer_id` | 員工墊付時填入員工 ID；公司付款時為 NULL |
| `receipt_key` | R2 物件鍵，`None` 表示無憑證 |

### 11.3 憑證上傳

- 前端限制：最大 10MB，接受 PDF/JPG/PNG/GIF/WEBP
- 後端處理：`werkzeug.utils.secure_filename()` + UUID 前綴避免衝突
- R2 路徑格式：`receipts/{uuid}_{safe_filename}`
- 刪除記錄時同步刪除 R2 物件（`r2_delete(key)`）

### 11.4 Audit Log 記錄

流水帳所有 CRUD 皆記錄（`add_audit` 在 `commit()` 之前呼叫）：

| action_type | 說明 |
|-------------|------|
| `LEDGER_CREATE` | 新增記錄 |
| `LEDGER_UPDATE` | 修改記錄 |
| `LEDGER_DELETE` | 刪除記錄 |
| `LEDGER_SETTLE` | 沖銷墊付 |

---

## 12. 日月報檔案庫（ReportArchive）

### 12.1 自動排程觸發

- **日報**: APScheduler `CronTrigger(hour=23, minute=59)` 每日觸發
  - 生成當日所有已確認回報的 Excel 日報
  - 上傳至 R2：`reports/daily/{YYYY}/{YYYYMMDD}_daily.xlsx`

- **月報**: `CronTrigger(day='last', hour=23, minute=59)` 每月最後一天觸發
  - 生成當月 1 日至月底的已確認回報 Excel 月報（含薪資彙總工作表）
  - 上傳至 R2：`reports/monthly/{YYYY}/{YYYYMM}_monthly.xlsx`

### 12.2 手動生成

ADMIN 在 `/report_archives` 頁面指定日期和類型後觸發，邏輯與自動生成相同，`source='manual'`。

### 12.3 下載

路由產生 R2 presigned URL（有效期 3600 秒），瀏覽器直接從 R2 下載，不經 Railway 傳輸。

---

## 13. Cloudflare R2 儲存

### 13.1 環境變數

| 變數 | 說明 |
|------|------|
| `R2_ACCOUNT_ID` | Cloudflare 帳號 ID |
| `R2_ACCESS_KEY_ID` | R2 API Token Access Key |
| `R2_SECRET_ACCESS_KEY` | R2 API Token Secret |
| `R2_BUCKET_NAME` | Bucket 名稱 |

### 13.2 boto3 整合

```python
import boto3
r2 = boto3.client(
    's3',
    endpoint_url=f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com',
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
)
```

### 13.3 操作函數

```python
def r2_upload(key, data, content_type='application/octet-stream'):
    r2.put_object(Bucket=R2_BUCKET_NAME, Key=key, Body=data, ContentType=content_type)

def r2_presigned_url(key, expires=3600):
    return r2.generate_presigned_url('get_object', Params={'Bucket': R2_BUCKET_NAME, 'Key': key}, ExpiresIn=expires)

def r2_delete(key):
    r2.delete_object(Bucket=R2_BUCKET_NAME, Key=key)
```

### 13.4 Fallback

若 R2 環境變數未設定，`r2_upload` 等函數靜默失敗（不 crash），`ReportArchive.r2_key_excel` 為 `None`，下載按鈕隱藏。

---

## 14. 變動紀錄（Audit Log）

### 14.1 Action Types

| action_type | 觸發時機 |
|-------------|----------|
| `REPORT_CREATE` | 新增回報 |
| `REPORT_UPDATE` | 修改回報 |
| `REPORT_DELETE` | 刪除回報 |
| `REPORT_CONFIRM` | ADMIN 確認回報 |
| `REPORT_UNCONFIRM` | ADMIN 取消確認 |
| `REPORT_REJECT` | ADMIN 駁回回報 |
| `ACCOUNT_CREATE` | 新增帳戶 |
| `ACCOUNT_UPDATE` | 更新帳戶資訊 |
| `ACCOUNT_DEACTIVATE` | 停用帳戶 |
| `ACCOUNT_REACTIVATE` | 復原帳戶 |
| `ACCOUNT_DELETE` | 永久刪除帳戶（cascade）|
| `PASSWORD_CHANGE` | 密碼變更 |
| `MATERIAL_REQUEST` | 材料申請 |
| `MATERIAL_CANCEL` | 取消材料申請 |
| `MATERIAL_ADD` | 新增材料品項 |
| `MATERIAL_UPDATE` | 更新材料庫存/資訊 |
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

### 14.2 Audit Log 正確性保證

**重要**: `add_audit()` 必須在 `db.session.commit()` **之前**呼叫，確保 audit log 與主記錄在同一 transaction 提交：

```python
# 正確順序
add_audit(current_user.id, 'LEDGER_CREATE', f'新增流水帳: {entry.description}')
db.session.commit()
```

v1.0.3 修正了 `ledger_add`、`ledger_edit`、`ledger_delete` 中原先順序顛倒的問題。

---

## 15. 資料庫初始化與 Migration

### 15.1 `_init_db()` 函數

在 `app.py` 頂部以 `with app.app_context(): _init_db()` 呼叫。

執行順序：
1. `db.create_all()` — 建立所有不存在的表
2. 各 column migration（`ALTER TABLE … ADD COLUMN`，try/except 確保冪等）
3. `ALTER TABLE users ALTER COLUMN bank_account TYPE VARCHAR(200)` — v1.0.2 擴展
4. `CREATE INDEX IF NOT EXISTS`（冪等）—含 v1.0.3 新增的 `ix_ledger_*`, `ix_report_archive_*`
5. Seed SystemConfig 預設值
6. 修正舊版預設值

### 15.2 新增欄位流程

1. `models.py` 的 Model class 新增 Column
2. `app.py` 的 `_init_db()` 加入 `ALTER TABLE … ADD COLUMN` try/except 區塊
3. 相關路由加入讀寫邏輯
4. 推送 → Railway redeploy → 自動執行 migration

> **注意**: 不使用 Flask-Migrate/Alembic，所有 migration 手動管理，冪等 try/except。

---

## 16. 前端架構

### 16.1 base.html 共用版型

- 左側固定側欄（220px），收合時縮為 52px（icon-only）
- 側欄狀態存於 `localStorage.ycSidebarCollapsed`
- Loading overlay：點擊連結/提交表單時顯示（`data-no-loading` 屬性可跳過）

### 16.2 _pagination.html macro

```jinja2
{% macro paginate(pagination, endpoint, url_args, page_param='page') %}
```

支援 `page_param` 參數，允許同一頁面多個分頁控件使用不同 query 參數。

### 16.3 停用帳戶標示

薪資計算結果中，停用帳戶在名稱旁顯示灰色 badge：
```html
{% if data.is_deactivated %}
  <span class="badge bg-secondary ms-1" title="此帳戶已停用，但有已確認回報，公司仍需支付薪資">停用</span>
{% endif %}
```

---

## 17. 設定系統（SystemConfig）

### 17.1 工項單價快取

`get_item_prices()` 使用 module-level TTL 快取（300 秒）。ADMIN 更新工項單價後自動呼叫 `_invalidate_price_cache()`。

> **注意**: 快取為 process-level，多 worker 部署時各 worker 快取獨立。

### 17.2 稅率

- Key: `tax_rate`，值為百分比整數字串（如 `"3"` 代表 3%）

### 17.3 保留金費率

- Key: `retention_rate`（全域），個別帳戶覆蓋由 `UserRetentionRate` 表

---

## 18. 已知限制與注意事項

### 18.1 每人每日一筆回報

系統無資料庫 UNIQUE 約束強制「每人每天一筆」。業務邏輯在 `/report` POST handler 中處理。若直接操作資料庫可能產生重複記錄，薪資計算會加總所有記錄。

### 18.2 稅務計算基數

稅務支出計算基數為「工項薪資毛額」，不包含固定薪資。此為業務決策，非 bug。

### 18.3 保留金年度邊界

保留金以「計薪起始日的年份」決定年度（`date(sd.year, 1, 1)`），跨年度計薪可能有邊界問題。

### 18.4 速率限制 memory backend

Flask-Limiter 使用 `memory://` backend，速率計數器不跨 worker/重啟持久化。高安全性環境應改用 Redis backend。

### 18.5 工項單價快取多 worker 問題

`get_item_prices()` 的 TTL 快取為 process-level，多 worker 部署時各 worker 有獨立快取，更新後最多 300 秒才全部刷新。單 worker Railway 部署下無此問題。

### 18.6 銀行帳號加密金鑰管理

`BANK_ENCRYPT_KEY` 遺失後無法解密現有銀行帳號。應妥善保管金鑰，並在更換前執行資料遷移。

### 18.7 R2 presigned URL 有效期

`/ledger/<id>/receipt` 和 `/report_archives/<id>/download/<fmt>` 產生的 presigned URL 有效期為 3600 秒。請勿儲存此 URL，每次存取應重新產生。

### 18.8 APScheduler 單 worker 限制

若 Railway 部署多個 worker，APScheduler 可能在多個 worker 中同時觸發定時任務，造成重複生成報表。當前部署為單 worker，無此問題。多 worker 需改用分散式排程（如 Celery + Redis）。

---

*最後更新: 2026-07-01 | 版本: v1.0.3 | 由 Claude Sonnet 4.6 輔助生成*
