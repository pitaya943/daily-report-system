# 員工日報回報系統 — 系統規格書

> **版本**: v1.0.2
> **日期**: 2026-06-30
> **狀態**: 已實作（反映當前生產環境實際運作狀態）
> **維護工程師參考文件**

---

## 版本變更紀錄

| 版本 | 日期 | 變更摘要 |
|------|------|----------|
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
11. [變動紀錄（Audit Log）](#11-變動紀錄audit-log)
12. [資料庫初始化與 Migration](#12-資料庫初始化與-migration)
13. [前端架構](#13-前端架構)
14. [設定系統（SystemConfig）](#14-設定系統systemconfig)
15. [已知限制與注意事項](#15-已知限制與注意事項)

---

## 1. 系統概述

### 1.1 目的

本系統為工程隊管理工具，提供：

- 員工每日施工工項回報（瓦斯管線施工數量）
- ADMIN 確認/駁回回報紀錄
- 基於確認回報自動計算薪資（工項計價 + 固定薪資 + 保留金 + 勞健保 + 稅務）
- 材料庫存管理與申請流程
- 薪資轉帳文件匯出（Excel/PDF/Word）
- 完整操作稽核日誌

### 1.2 使用者規模

- 設計容量：≤ 10 ADMIN + ≤ 75 USER（共 85 人）
- 資料量：每月約 85 × 22 = 1,870 筆回報；年度約 22,440 筆

### 1.3 應用程式入口

- `app.py`: 所有路由、業務邏輯、匯出功能、安全設定
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
└── python-docx           — Word（薪轉單）匯出
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

### 2.4 前端

- Bootstrap 5.3（CDN）+ Bootstrap Icons 1.11（CDN）
- 無 JS 框架，純 Jinja2 + 原生 JS
- 所有 POST 表單包含 CSRF hidden token（Flask-WTF 自動驗證）

---

## 3. 安全機制

### 3.1 CSRF 保護（SEC-001）

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

### 3.2 登入速率限制（SEC-003）

使用 Flask-Limiter，限制 `/login` 端點：

```python
limiter = Limiter(get_remote_address, app=app, default_limits=[], storage_uri='memory://')

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute')
def login(): ...
```

同一 IP 每分鐘超過 10 次登入嘗試 → 回傳 **429 Too Many Requests**。

> **注意**: memory backend 不跨 worker 共享狀態。多 worker 部署需改用 Redis backend。

### 3.3 Session 安全（SEC-005）

```python
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=10)
app.config['SESSION_COOKIE_HTTPONLY']    = True
app.config['SESSION_COOKIE_SAMESITE']   = 'Lax'
app.config['SESSION_COOKIE_SECURE']     = not app.debug  # 生產 HTTPS = True
```

登入時設定 `session.permanent = True`，確保 10 分鐘閒置後自動登出。

### 3.4 SECRET_KEY 驗證（SEC-002）

```python
_sk = os.environ.get('SECRET_KEY')
if not _sk:
    logging.warning('SECRET_KEY env var not set — using hardcoded fallback (unsafe for production)')
app.config['SECRET_KEY'] = _sk or 'daily-report-secret-2026-yc-local'
```

未設定環境變數時 app 仍啟動（不 crash），但在 log 顯示警告。**生產環境必須設定 `SECRET_KEY`**。

### 3.5 銀行帳號加密（SEC-007）

使用 Fernet 對稱加密，金鑰由環境變數 `BANK_ENCRYPT_KEY` 控制：

```python
_BANK_KEY_STR = os.environ.get('BANK_ENCRYPT_KEY', '').strip()
try:
    _fernet = Fernet(_BANK_KEY_STR.encode()) if _BANK_KEY_STR else None
except Exception:
    _fernet = None  # 金鑰無效時優雅降級，不 crash
```

**加密函數**:
```python
def encrypt_bank(acct: str) -> str:
    if not _fernet or not acct:
        return acct  # 未設定金鑰時原值回傳
    return _fernet.encrypt(acct.encode()).decode()

def decrypt_bank(acct: str) -> str:
    if not _fernet or not acct:
        return acct
    try:
        return _fernet.decrypt(acct.encode()).decode()
    except (InvalidToken, Exception):
        return acct  # 過渡期：解密失敗表示舊明文資料，直接回傳
```

加密後的 Fernet token 約 88 字元，儲存於 `VARCHAR(200)` 欄位。`BANK_ENCRYPT_KEY` 未設定時以明文儲存，功能不中斷。

**使用位置**:
- `settings_bank_account()`: 儲存前 `encrypt_bank(acct)`
- 新增帳戶: 儲存前 `encrypt_bank(bank_account_raw)`
- `salary()`: 讀取時 `decrypt_bank(u.bank_account)`
- `settings()`: 讀取時建立 `bank_accounts = {u.id: decrypt_bank(u.bank_account or '')}`

**首次設定後現有資料遷移**: 訪問 `/admin/migrate-bank-encrypt`（ADMIN 限定，一次性路由）。

### 3.6 HTTP 安全標頭（SEC-008）

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
| bank_account | **VARCHAR(200)** | **Fernet 加密 token**（設定金鑰後）或明文 14 碼（降級模式）|
| fixed_salary | INTEGER | 固定月薪（10號發薪時加入）；預設 0 |
| retention_offset | INTEGER | ADMIN 手動調整保留金累計（可負值）|
| created_at / updated_at | DATETIME | 建立/更新時間 |

> v1.0.2 變更：`bank_account` 由 `VARCHAR(14)` 擴展至 `VARCHAR(200)`，以容納 Fernet 加密 token。

### 4.3 reports 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| user_id | INTEGER FK | → users.id（回報者）|
| report_date | DATE | 回報日期（每人每天最多一筆，業務邏輯防重）|
| direct_13 ~ soil_clearing | INTEGER | 21 個工項數量欄位（預設 0）|
| is_confirmed | BOOLEAN | ADMIN 已確認 |
| confirmed_by | INTEGER FK | → users.id（確認者；ADMIN 刪除時置 NULL）|
| confirmed_at | DATETIME | 確認時間 |
| is_rejected | BOOLEAN | ADMIN 已駁回 |

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
| reviewed_by | INTEGER FK | → users.id（審核者；ADMIN 刪除時置 NULL）|
| reviewed_at | DATETIME | 審核時間 |

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
| action_type | VARCHAR(50) | 操作類型（見第 11 節）|
| description | TEXT | 人可讀描述 |
| created_at | DATETIME | 操作時間 |

**索引**: `ix_audit_logs_created_at`, `ix_audit_logs_user_id`, `ix_audit_logs_action_type`

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
| `/settings/users/<id>/password` | POST | ✓ | ✓\* |
| 其他 `/settings/...` 路由 | POST | ✓ | ✓ |
| `/admin/migrate-bank-encrypt` | GET | ✓ | ✓ |

> \* `/settings/users/<id>/password` 亦允許用戶修改自身密碼（`current_user.id == user_id` 或 ADMIN）

---

## 6. 路由與頁面邏輯

### 6.1 `/report` — 回報頁面

**GET**: 顯示今日表單。若今日已有回報，預填現有數值（允許「修改今日回報」）。

**POST**:
1. 解析 21 個欄位值（`int`，預設 0）
2. 查詢當日是否已有回報（`filter_by(user_id=..., report_date=today)`）
3. 有 → 更新；無 → 新增
4. `add_audit('REPORT_CREATE'/'REPORT_UPDATE', ...)`
5. Flash success，redirect

**特殊情境**:
- 已確認的回報：USER 無法修改；ADMIN 修改時自動取消確認
- ADMIN 修改已確認回報 → `is_confirmed=False`，並記錄 `REPORT_UNCONFIRM`

### 6.2 `/history` — 歷史紀錄

**GET**: 分頁查詢（`per_page=30`），支援篩選：
- USER: 只看自己的回報
- ADMIN: 可選擇指定帳戶 + 日期範圍

### 6.3 `/confirmation` — ADMIN 確認頁

**GET**: 分頁顯示未確認未駁回回報 + 待審材料申請

**日期篩選（v1.0.2 新增）**:
- 預設顯示最近 30 天（`?start_date=&end_date=`）
- 支援自訂日期範圍篩選
- GET 參數：`start_date`, `end_date`（ISO 格式），`page`（報表分頁），`mat_page`（材料分頁）

**材料申請分頁（v1.0.2 新增）**:
- `per_page=20`，使用 `mat_page` 參數（獨立於報表分頁的 `page` 參數）

**動作端點**:
- POST `/confirmation/report/<id>/confirm` → `is_confirmed=True`
- POST `/confirmation/report/<id>/reject` → `is_rejected=True`
- POST `/confirmation/material/<id>/approve` → `status='APPROVED'`，扣庫存
- POST `/confirmation/material/<id>/reject` → `status='REJECTED'`

### 6.4 `/salary` — 薪資計算

詳見第 7 節。支援 `action`：`calculate`、`export-excel`、`export-pdf`、`export-transfer`

### 6.5 `/settings` — 設定

帳戶管理子路由：

| 子路由 | 功能 |
|--------|------|
| POST `/settings/users` | 新增帳戶 |
| POST `/settings/users/<id>/password` | 重設密碼 |
| POST `/settings/users/<id>/payment` | 更改發薪方式 |
| POST `/settings/users/<id>/insurance` | 設定投保狀態 |
| POST `/settings/users/<id>/bank-account` | 設定銀行帳號（加密儲存）|
| POST `/settings/users/<id>/fixed-salary` | 設定固定薪資 |
| POST `/settings/users/<id>/retention-offset` | 保留金調整 |
| POST `/settings/users/<id>/retention-rates` | 設定客製保留金費率 |
| POST `/settings/users/<id>/deactivate` | 停用帳戶（保留資料）|
| POST `/settings/users/<id>/reactivate` | 復原帳戶 |
| POST `/settings/users/<id>/delete` | 永久刪除帳戶（cascade 模式） |

**帳戶刪除 cascade 模式（v1.0.2 修正）**:

刪除前按順序清理所有 FK 參照：
1. `Report.confirmed_by = user_id` → 置 NULL
2. `MaterialRequest.reviewed_by = user_id` → 置 NULL
3. `UserRetentionRate` where `user_id` → 刪除
4. `AuditLog` where `user_id` → 刪除
5. `Report` where `user_id` → 刪除
6. `MaterialRequest` where `user_id` → 刪除
7. `db.session.delete(user)` → 刪除用戶本體

### 6.6 `/personal_stats` — 個人統計

雙查詢面板（同時支援兩個獨立日期範圍）：

1. **工項統計面板** (`stats_start` / `stats_end`)
2. **薪資試算面板** (`salary_start` / `salary_end`)

v1.0.2 效能優化：改用 `get_users_all_retention_rates([current_user.id])[current_user.id]`（批次查詢），避免 N+1 問題。

---

## 7. 薪資計算邏輯（核心業務）

### 7.1 計算流程

```
輸入：start_date, end_date, is_10th_payday（boolean）

Step 1: 查詢範圍內所有已確認回報（僅在職帳戶）
Step 2: 排除停用帳戶回報
Step 3: 補入有固定薪資但本期無回報的在職帳戶
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
- 銀行帳號讀取時透過 `decrypt_bank()` 解密
- 雙欄排版（左右各 15 筆，共 30 格）

---

## 8. 保留金系統

### 8.1 設計目的

保留金是從工項薪資中預留的品質保證金，年底前達到上限後停扣。

### 8.2 參數

- `RETENTION_CAP = 5000`（NTD，年度累計上限）
- `RETENTION_FIELDS`：計入保留金的工項欄位清單（直總/間接管，不含動員/管修等特殊工項）

### 8.3 計算邏輯

```python
# 本年度 1/1 至計薪起始日前的累計保留金
ytd_before = min(RETENTION_CAP, max(0.0, pre_calc + user.retention_offset))

# 本期應扣（不超過剩餘額度）
period_retention = max(0.0, min(period_ret_raw, RETENTION_CAP - ytd_before))
```

### 8.4 費率優先順序

1. `UserRetentionRate` 表有記錄 → 客製費率
2. 無記錄 → 全域 `retention_rate`（SystemConfig）

---

## 9. 匯出功能

### 9.1 Excel（openpyxl）

每位用戶一個工作表，含工項明細、保留金、固定薪資、稅務；最後一頁彙總表。

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

## 11. 變動紀錄（Audit Log）

### 11.1 Action Types

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

---

## 12. 資料庫初始化與 Migration

### 12.1 `_init_db()` 函數

在 `app.py` 頂部以 `with app.app_context(): _init_db()` 呼叫。

執行順序：
1. `db.create_all()` — 建立所有不存在的表
2. 各 column migration（`ALTER TABLE … ADD COLUMN`，try/except 確保冪等）
3. `ALTER TABLE users ALTER COLUMN bank_account TYPE VARCHAR(200)` — v1.0.2 擴展欄位
4. `CREATE INDEX IF NOT EXISTS`（冪等）
5. Seed SystemConfig 預設值
6. 修正舊版預設值（稅率 5% → 3%）

### 12.2 新增欄位流程

1. `models.py` 的 Model class 新增 Column
2. `app.py` 的 `_init_db()` 加入 `ALTER TABLE … ADD COLUMN` try/except 區塊
3. 相關路由加入讀寫邏輯
4. 推送 → Railway redeploy → 自動執行 migration

> **注意**: 不使用 Flask-Migrate/Alembic，所有 migration 手動管理，冪等 try/except。

---

## 13. 前端架構

### 13.1 base.html 共用版型

- 左側固定側欄（220px），收合時縮為 52px（icon-only）
- 側欄狀態存於 `localStorage.ycSidebarCollapsed`
- Loading overlay：點擊連結/提交表單時顯示

### 13.2 _pagination.html macro

```jinja2
{% macro paginate(pagination, endpoint, url_args, page_param='page') %}
```

支援 `page_param` 參數（v1.0.2 新增），允許同一頁面多個分頁控件使用不同 query 參數（如 confirmation 頁的 `page` 與 `mat_page`）。

### 13.3 各頁面 JS 特殊邏輯

**salary.html**: `setPayday10()` / `setPayday25()` 自動填入日期範圍
**settings.html**: `openBankAccount()` / `openInsurance()` / `openPayment()` 等 Modal 開關
**report.html**: JS 複製隱藏 form input → 實際 POST（避免多欄位送出問題）

---

## 14. 設定系統（SystemConfig）

### 14.1 工項單價快取（v1.0.2 新增）

`get_item_prices()` 使用 module-level TTL 快取（300 秒）：

```python
_price_cache: dict = {}
_price_cache_ts: float = 0.0
_PRICE_CACHE_TTL = 300

def get_item_prices() -> dict:
    global _price_cache, _price_cache_ts
    if _price_cache and (time.monotonic() - _price_cache_ts) < _PRICE_CACHE_TTL:
        return _price_cache
    # ... 從 DB 讀取 ...
    _price_cache = prices
    _price_cache_ts = time.monotonic()
    return _price_cache

def _invalidate_price_cache():
    global _price_cache
    _price_cache = {}
```

ADMIN 更新工項單價後自動呼叫 `_invalidate_price_cache()`。

> **注意**: 快取為 process-level，多 worker 部署時各 worker 快取獨立。

### 14.2 稅率

- Key: `tax_rate`，值為百分比整數字串（如 `"3"` 代表 3%）

### 14.3 保留金費率

- Key: `retention_rate`（全域），個別帳戶覆蓋由 `UserRetentionRate` 表

---

## 15. 已知限制與注意事項

### 15.1 每人每日一筆回報

系統無資料庫 UNIQUE 約束強制「每人每天一筆」。業務邏輯在 `/report` POST handler 中處理（查詢後更新或新增）。若直接操作資料庫可能產生重複記錄，薪資計算會加總所有記錄。

### 15.2 稅務計算基數

稅務支出計算基數為「工項薪資毛額」，不包含固定薪資。此為業務決策，非 bug。

### 15.3 保留金年度邊界

保留金以「計薪起始日的年份」決定年度（`date(sd.year, 1, 1)`），跨年度計薪可能有邊界問題。

### 15.4 速率限制 memory backend

Flask-Limiter 使用 `memory://` backend，速率計數器不跨 worker/重啟持久化。多 worker 或重啟後計數重置。高安全性環境應改用 Redis backend。

### 15.5 工項單價快取多 worker 問題

`get_item_prices()` 的 TTL 快取為 process-level，多 worker 部署時各 worker 有獨立快取，更新後最多 300 秒各 worker 才會刷新。單 worker Railway 部署下無此問題。

### 15.6 銀行帳號加密金鑰管理

`BANK_ENCRYPT_KEY` 遺失後無法解密現有銀行帳號（Fernet 為對稱加密，無法從密文反推金鑰）。應妥善保管金鑰，並在更換前執行資料遷移。

---

*最後更新: 2026-06-30 | 版本: v1.0.2 | 由 Claude Sonnet 4.6 輔助生成*
