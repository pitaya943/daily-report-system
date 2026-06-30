# 員工日報回報系統 — 系統規格書

> **版本**: v1.0.1
> **日期**: 2026-06-30
> **狀態**: 已實作（反映當前生產環境實際運作狀態）
> **維護工程師參考文件**

---

## 目錄

1. [系統概述](#1-系統概述)
2. [技術架構](#2-技術架構)
3. [資料庫設計](#3-資料庫設計)
4. [認證與授權](#4-認證與授權)
5. [路由與頁面邏輯](#5-路由與頁面邏輯)
6. [薪資計算邏輯（核心業務）](#6-薪資計算邏輯核心業務)
7. [保留金系統](#7-保留金系統)
8. [匯出功能](#8-匯出功能)
9. [材料管理](#9-材料管理)
10. [變動紀錄（Audit Log）](#10-變動紀錄audit-log)
11. [資料庫初始化與 Migration](#11-資料庫初始化與-migration)
12. [前端架構](#12-前端架構)
13. [設定系統（SystemConfig）](#13-設定系統systemconfig)
14. [已知限制與注意事項](#14-已知限制與注意事項)

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

- `app.py`: 所有路由、業務邏輯、匯出功能
- `models.py`: SQLAlchemy ORM 資料模型
- 啟動後自動執行 `_init_db()` 進行 schema migration

---

## 2. 技術架構

### 2.1 後端

```
Flask 3.x (Python 3.11)
├── flask-sqlalchemy 3.x  — ORM（SQLite/PostgreSQL 雙支援）
├── flask-login           — Session-based 認證
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
    # PostgreSQL：將 postgres:// 轉為 postgresql://（SQLAlchemy 要求）
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
- 所有表單以 POST 方式提交（Jinja2 渲染，非 API）

---

## 3. 資料庫設計

### 3.1 ER Diagram（文字版）

```
users ──< reports          (one user → many reports)
users ──< material_requests (one user → many requests)
materials ──< material_requests
users ──< audit_logs
users ──< user_retention_rates
system_config (key-value store)
```

### 3.2 users 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | 自增 ID |
| display_name | VARCHAR(50) UNIQUE | 顯示名稱（登入帳號） |
| password_hash | VARCHAR(256) | pbkdf2:sha256 |
| role | VARCHAR(10) | `'ADMIN'` 或 `'USER'` |
| is_active | BOOLEAN | False = 停用（無法登入） |
| payment_method | VARCHAR(10) | `'TRANSFER'` 或 `'CASH'` |
| insurance_deduction | INTEGER | 勞健保固定扣除額（NTD）；0 = 未投保 |
| tax_exempt | BOOLEAN | True = 未投保免稅；False = 未投保需扣稅（insurance_deduction==0 時有效）|
| bank_account | VARCHAR(14) | 銀行帳號（3碼分行+11碼帳號）；TRANSFER 時必填 |
| fixed_salary | INTEGER | 固定月薪（10號發薪時加入）；預設 0 |
| retention_offset | INTEGER | ADMIN 手動調整保留金累計（可負值）|
| created_at / updated_at | DATETIME | 建立/更新時間 |

**索引**:
- ix_reports_user_date (user_id, report_date)
- ix_reports_date_confirmed (report_date, is_confirmed)
- ix_reports_user_confirmed (user_id, is_confirmed)

### 3.3 reports 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| user_id | INTEGER FK | → users.id |
| report_date | DATE | 回報日期（每人每天最多一筆，無 UNIQUE 約束，靠業務邏輯防重）|
| direct_13 ~ soil_clearing | INTEGER | 21 個工項數量欄位（預設 0）|
| is_confirmed | BOOLEAN | ADMIN 已確認 |
| confirmed_by | INTEGER FK | 確認者 user.id |
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

### 3.4 materials 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| name | VARCHAR(100) | 材料名稱 |
| unit | VARCHAR(20) | 單位（支/個/包…）|
| remaining_quantity | INTEGER | 庫存量 |
| sort_order | INTEGER | 顯示排序 |

### 3.5 material_requests 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| user_id | INTEGER FK | 申請者 |
| material_id | INTEGER FK | 申請材料 |
| requested_quantity | INTEGER | 申請數量 |
| status | VARCHAR(10) | `PENDING` / `APPROVED` / `REJECTED` |
| reviewed_by | INTEGER FK | 審核者（ADMIN）|
| reviewed_at | DATETIME | 審核時間 |

**索引**: ix_mat_req_user_id, ix_mat_req_status

### 3.6 system_config 表（Key-Value）

| Key | 說明 | 預設值 |
|-----|------|--------|
| `retention_rate` | 全域保留金費率(%) | 20 |
| `tax_rate` | 稅務費率(%) | 3 |
| `price_{field}` | 各工項單價（NTD）| 見 DEFAULT_PRICES |

**全域費率的解析**:
- `retention_rate` 僅在帳戶無 `UserRetentionRate` 對應記錄時使用
- 各工項費率由 `get_users_all_retention_rates()` 批次載入

### 3.7 user_retention_rates 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| user_id | INTEGER FK | |
| field | VARCHAR(50) | 工項欄位名（如 `direct_13`）|
| rate | INTEGER | 客製費率(%) |

若某 user+field 無記錄，則使用全域 `retention_rate`。

### 3.8 audit_logs 表

| 欄位 | 型別 | 說明 |
|------|------|------|
| id | INTEGER PK | |
| user_id | INTEGER FK | 操作者 |
| action_type | VARCHAR(50) | 操作類型（見第 10 節）|
| description | TEXT | 人可讀描述 |
| created_at | DATETIME | 操作時間 |

**索引**: ix_audit_logs_created_at, ix_audit_logs_user_id, ix_audit_logs_action_type

---

## 4. 認證與授權

### 4.1 認證流程

1. 使用者 POST `/login`，輸入 `display_name` + `password`
2. `User.query.filter_by(display_name=...).first()` 查詢用戶
3. `werkzeug.security.check_password_hash()` 驗證密碼
4. 帳號停用（`is_active=False`）→ 拒絕登入
5. 通過 → `flask_login.login_user(user)` 建立 session
6. 登出：`flask_login.logout_user()` + redirect to `/login`

### 4.2 授權裝飾器

```python
@login_required          # flask-login 提供；未登入 → 重定向 /login
@admin_required          # 自訂；非 ADMIN → abort(403)
```

`admin_required` 實作：
```python
def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role != 'ADMIN':
            abort(403)
        return f(*args, **kwargs)
    return decorated
```

### 4.3 路由權限表

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
| `/confirmation` | GET/POST | ✓ | ✓ |
| `/salary` | GET/POST | ✓ | ✓ |
| `/settings` | GET | ✓ | ✓ |
| `/settings/users` | POST | ✓ | ✓ |
| `/settings/users/<id>/password` | POST | ✓ | ✓* |
| 其他 `/settings/...` 路由 | POST | ✓ | ✓ |

> \* `/settings/users/<id>/password` 亦允許用戶修改自身密碼（需 `current_user.id == user_id` 或 ADMIN）

---

## 5. 路由與頁面邏輯

### 5.1 `/report` — 回報頁面

**GET**: 顯示今日表單。若今日已有回報，預填現有數值（允許「修改今日回報」）。

**POST**:
1. 解析 21 個欄位值（`int`，預設 0）
2. 查詢當日是否已有回報（`Report.query.filter_by(user_id=..., report_date=today)`）
3. 有 → 更新；無 → 新增
4. `add_audit('REPORT_CREATE'/'REPORT_UPDATE', ...)`
5. Flash success，redirect to `/report`

**特殊情境**:
- 回報提交後，ADMIN 確認前，USER 仍可修改
- ADMIN 確認後，USER 無法修改（`history_edit()` 檢查 `r.is_confirmed` + `current_user.role`）

### 5.2 `/history` — 歷史紀錄

**GET**: 分頁查詢（`per_page=30`），支援篩選：
- USER: 只看自己的回報
- ADMIN: 可選擇指定帳戶 + 日期範圍

**POST `/history/<id>/edit`**:
1. 取得 Report，驗證所有人（USER: `r.user_id == current_user.id`）
2. 已確認 + 非 ADMIN → 403 拒絕
3. 若先前已確認（`was_confirmed=True`） + 是 ADMIN → 自動取消確認
4. 更新欄位，commit，redirect

**POST `/history/<id>/delete`**:
1. USER: 僅能刪除自己的、未確認回報
2. ADMIN: 可刪任何回報
3. 刪除 + audit log

### 5.3 `/confirmation` — ADMIN 確認頁

**GET**: 顯示**未確認且未駁回**的所有回報（按日期）+ 待審材料申請

**POST 動作（`action` 欄位）**:
- `confirm`: 確認指定 report_id → `is_confirmed=True`
- `reject`: 駁回 → `is_rejected=True`
- `material_approve`: 核准材料申請 → `status='APPROVED'`，扣庫存
- `material_reject`: 拒絕申請 → `status='REJECTED'`，**不**扣庫存

**庫存扣減邏輯（材料核准）**:
```python
material.remaining_quantity -= request.requested_quantity
# 若庫存不足：拒絕核准，flash 錯誤
if material.remaining_quantity < 0:
    db.session.rollback()
    flash('庫存不足', 'danger')
```

### 5.4 `/salary` — 薪資計算

詳見第 6 節（核心業務邏輯）。

**支援的 `action`**:
- `calculate`: 計算並顯示結果
- `export-excel`: 下載 Excel
- `export-pdf`: 下載 PDF
- `export-transfer`: 下載 Word 薪轉單（僅 TRANSFER 帳戶）

### 5.5 `/settings` — 設定

ADMIN 管理頁，子路由：

| 子路由 | 功能 |
|--------|------|
| POST `/settings/users` | 新增帳戶 |
| POST `/settings/users/<id>/password` | 重設密碼 |
| POST `/settings/users/<id>/payment` | 更改發薪方式 |
| POST `/settings/users/<id>/insurance` | 設定投保狀態 |
| POST `/settings/users/<id>/bank-account` | 設定銀行帳號 |
| POST `/settings/users/<id>/fixed-salary` | 設定固定薪資 |
| POST `/settings/users/<id>/retention-offset` | 保留金調整 |
| POST `/settings/users/<id>/retention-rates` | 設定客製保留金費率 |
| POST `/settings/users/<id>/deactivate` | 停用帳戶 |
| POST `/settings/users/<id>/reactivate` | 復原帳戶 |
| POST `/settings/users/<id>/delete` | 永久刪除帳戶 |
| POST `/settings/tax-rate` | 更新稅率 |
| POST `/settings/item-prices` | 批次更新工項單價 |
| POST `/settings/materials` | 新增材料 |
| POST `/settings/materials/<id>/edit` | 編輯材料 |
| POST `/settings/materials/<id>/delete` | 刪除材料 |

**帳戶排序邏輯**:
```python
_all_users_raw = User.query.order_by(User.id).all()
all_users = sorted(_all_users_raw, key=lambda u: (0 if u.role == 'ADMIN' else 1, u.id))
# ADMIN 置頂，其餘按 id 升序
```

### 5.6 `/personal_stats` — 個人統計

雙查詢面板（同時支援兩個獨立日期範圍）：

1. **工項統計面板** (`stats_start` / `stats_end`): 彙總個人工項數量
2. **薪資試算面板** (`salary_start` / `salary_end`): 計算預估薪資

薪資試算包含：
- 工項薪資（按當前系統單價）
- 保留金扣除（含個人費率）
- 勞健保 / 稅務扣除（由「扣除勞健保/稅務支出」checkbox 控制）

---

## 6. 薪資計算邏輯（核心業務）

### 6.1 計算流程

```
輸入：start_date, end_date, is_10th_payday（boolean）

Step 1: 查詢範圍內所有已確認回報（僅在職帳戶）
Step 2: 排除停用帳戶回報（active_user_ids filter）
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

### 6.2 10號 / 25號發薪差異

| 項目 | 25號發薪 | 10號發薪 |
|------|----------|----------|
| 工項薪資 | ✓ | ✓ |
| 保留金扣除 | ✓ | ✓ |
| 固定薪資 | ✗ | ✓ |
| 勞健保扣除 | ✗ | ✓ |
| 稅務支出 | ✓（有時）| ✓（有時）|

> 稅務支出 = 工項毛額 × 稅率，不受發薪期別影響；但 10 號 + 固定薪資的帳戶稅務計算僅針對工項毛額，不含固定薪資。

### 6.3 帳戶投保狀態矩陣

| `insurance_deduction` | `tax_exempt` | 行為 |
|-----------------------|--------------|------|
| > 0 | — | 已投保：10號扣固定勞健保，不扣稅 |
| 0 | False | 未投保需扣稅：扣工項毛額 × 稅率% |
| 0 | True | 未投保免稅：不扣勞健保也不扣稅 |

### 6.4 薪轉單（Word）匯出邏輯

- 使用 `python-docx` 產生「板信商業銀行薪資轉帳送件單」
- 僅包含 `payment_method == 'TRANSFER'` 且 `final_salary > 0` 的帳戶
- 日期計算：`date(end_date.year, end_date.month, 10)`（若為假日則順延至下一個工作日）
- 雙欄排版（左右各 15 筆，共 30 格）

---

## 7. 保留金系統

### 7.1 設計目的

保留金是從工項薪資中預留的品質保證金，年底前達到上限後停扣。

### 7.2 參數

- `RETENTION_CAP = 5000`（NTD，年度累計上限）
- `RETENTION_FIELDS`：計入保留金的工項欄位清單（直總/間接管，不含動員/管修等特殊工項）

### 7.3 計算邏輯（按期計算）

```python
# 本年度 1/1 至 計薪起始日前 的累計保留金
pre_calc = Σ(pre_period_totals[f] * user_rates[f] for f in RETENTION_FIELDS)
ytd_before = min(RETENTION_CAP, max(0.0, pre_calc + user.retention_offset))

# 本期應扣
period_ret_raw = Σ(period_totals[f] * user_rates[f] for f in RETENTION_FIELDS)

# 實際扣除（不超過剩餘額度）
period_retention = max(0.0, min(period_ret_raw, RETENTION_CAP - ytd_before))
```

### 7.4 費率優先順序

1. `UserRetentionRate` 表中有記錄 → 使用客製費率
2. 無記錄 → 使用全域 `retention_rate`（SystemConfig）

### 7.5 `retention_offset` 用途

ADMIN 可手動調整 YTD 保留金計算基準，用於：
- 跨年度調整（重置後手動補償）
- 特殊情況修正（帳戶遷移、計算錯誤修正）

---

## 8. 匯出功能

### 8.1 Excel (`openpyxl`)

- 每位用戶一個工作表，含工項明細、保留金、固定薪資、稅務
- 最後一頁為「彙總」
- 金額欄位格式：`#,##0`
- 標色規則：固定薪資行綠色、勞健保行紅色、稅務行橘色

### 8.2 PDF (`reportlab`)

- 使用 `CJKFont`（粗黑體），支援繁體中文
- 每頁固定寬度，自動換頁
- 內容與 Excel 相同，但格式為流水表格

### 8.3 Word 薪轉單 (`python-docx`)

- 嚴格符合「板信商業銀行薪資轉帳送件單」格式
- TABLE_1（委託人資訊）+ TABLE_2（明細）無縫拼接（共用外框線）
- 字型：中文標楷體、數字 Times New Roman
- 帳號格式：`XXXX-XXX-XXXXXXX`（由 14 碼銀行帳號格式化）

---

## 9. 材料管理

### 9.1 申請流程

```
USER 提交申請（status=PENDING）
    ↓ ADMIN 審核（/confirmation）
  核准 → status=APPROVED，material.remaining_quantity -= qty
  拒絕 → status=REJECTED，庫存不變
    ↓
USER 可取消 PENDING 狀態的申請（APPROVED/REJECTED 不可取消）
```

### 9.2 庫存保護

核准時若 `remaining_quantity < requested_quantity` → 拒絕核准，不扣庫存，flash 錯誤。

### 9.3 材料排序

`sort_order` 欄位控制顯示順序，由 ADMIN 在設定頁調整。

---

## 10. 變動紀錄（Audit Log）

### 10.1 Action Types

| action_type | 觸發時機 |
|-------------|----------|
| `REPORT_CREATE` | 新增回報 |
| `REPORT_UPDATE` | 修改回報 |
| `REPORT_DELETE` | 刪除回報 |
| `REPORT_CONFIRM` | ADMIN 確認回報 |
| `REPORT_UNCONFIRM` | ADMIN 取消確認 |
| `REPORT_REJECT` | ADMIN 駁回回報 |
| `ACCOUNT_CREATE` | 新增帳戶 |
| `ACCOUNT_UPDATE` | 更新帳戶資訊（密碼/投保/發薪/固定薪資等）|
| `ACCOUNT_DEACTIVATE` | 停用帳戶 |
| `ACCOUNT_REACTIVATE` | 復原帳戶 |
| `ACCOUNT_DELETE` | 永久刪除帳戶 |
| `PASSWORD_CHANGE` | 密碼變更 |
| `MATERIAL_REQUEST` | 材料申請 |
| `MATERIAL_CANCEL` | 取消材料申請 |
| `MATERIAL_ADD` | 新增材料品項 |
| `MATERIAL_UPDATE` | 更新材料庫存/資訊 |
| `MATERIAL_DELETE` | 刪除材料品項 |
| `MATERIAL_APPROVE` | 核准材料申請 |
| `MATERIAL_REJECT` | 拒絕材料申請 |
| `SYSTEM_CONFIG` | 系統設定變更（稅率/單價/保留金費率）|
| `RETENTION_RESET` | 重置保留金 |
| `RETENTION_SET` | 設定保留金調整值 |

### 10.2 查詢與篩選

- 分頁顯示（`per_page=20`）
- 可篩選：操作者帳戶、action_type、日期範圍
- 使用 `ix_audit_logs_created_at` 索引加速排序

---

## 11. 資料庫初始化與 Migration

### 11.1 `_init_db()` 函數

在 `app.py` 頂部以 `with app.app_context(): _init_db()` 呼叫。

執行順序：
1. `db.create_all()` — 建立所有不存在的表
2. 各 column migration（`ALTER TABLE … ADD COLUMN`，try/except 確保冪等）
3. `CREATE INDEX IF NOT EXISTS`（冪等）
4. Seed SystemConfig 預設值（`if not cfg: db.session.add(...)`）
5. 修正舊版預設值（稅率 5% → 3%）

### 11.2 新增欄位流程（給維護工程師）

1. 在 `models.py` 的 Model class 新增 Column
2. 在 `app.py` 的 `_init_db()` 加入對應的 `ALTER TABLE … ADD COLUMN` try/except 區塊
3. 在相關路由中加入讀寫邏輯
4. 推送到 GitHub → Railway 自動 redeploy → `_init_db()` 執行 migration

**注意**: 不使用 Flask-Migrate/Alembic，所有 migration 手動管理。

---

## 12. 前端架構

### 12.1 base.html 共用版型

- 左側固定側欄（220px），收合時縮為 52px（icon-only 模式）
- 側欄狀態存於 `localStorage.ycSidebarCollapsed`
- 頁面載入前套用預收合狀態（避免 FOUC）
- Loading overlay：點擊連結/提交表單時顯示，`DOMContentLoaded` 後隱藏
- Flash messages 在 `content-area` 頂部顯示

### 12.2 側欄收合邏輯

```javascript
// 頁面載入前（<head>）
if(localStorage.getItem('ycSidebarCollapsed')==='true')
  document.documentElement.classList.add('sidebar-collapsed-preload');

// DOM 載入後
if(document.documentElement.classList.contains('sidebar-collapsed-preload')){
  document.body.classList.add('sidebar-collapsed');
  document.documentElement.classList.remove('sidebar-collapsed-preload');
}

// 切換函數
function toggleSidebar(){
  var collapsed = document.body.classList.toggle('sidebar-collapsed');
  localStorage.setItem('ycSidebarCollapsed', collapsed);
}
```

### 12.3 各頁面 JS 特殊邏輯

**salary.html**:
- `setPayday10()` / `setPayday25()`: 自動填入日期範圍 + 切換 `is_10th_payday` checkbox
- 計算結果用 sticky 左欄 + 右側結果欄排版

**settings.html**:
- `openFixedSalary()`: 開啟固定薪資設定 Modal
- `openInsurance()`: 開啟投保設定 Modal，`toggleInsType()` 控制金額欄顯示/disable
- `openPayment()` + `submitPaymentForm()`: 選轉帳但無銀行帳號時攔截並跳轉到銀行帳號設定 Modal
- `openBankAccount()`: 開啟銀行帳號設定 Modal

**personal_stats.html**:
- `deduct_insurance` checkbox：控制勞健保或稅務扣除是否納入試算

---

## 13. 設定系統（SystemConfig）

### 13.1 工項單價

所有 `price_{field}` key 儲存於 SystemConfig，ADMIN 可在設定頁批次修改。

讀取方式（`get_item_prices()`）：
```python
def get_item_prices() -> dict:
    cfgs = SystemConfig.query.filter(SystemConfig.key.like('price_%')).all()
    prices = {c.key[6:]: float(c.value) for c in cfgs}  # 去除 'price_' 前綴
    for f, p in DEFAULT_PRICES.items():
        prices.setdefault(f, p)  # 補全缺少的欄位
    return prices
```

### 13.2 稅率

- Key: `tax_rate`
- 值為百分比整數字串（如 `"3"` 代表 3%）
- 讀取：`get_tax_rate()` → `float(cfg.value)`

### 13.3 保留金費率

- Key: `retention_rate`（全域）
- 個別帳戶覆蓋：`UserRetentionRate` 表

---

## 14. 已知限制與注意事項

### 14.1 每人每日一筆回報

系統無資料庫 UNIQUE 約束強制「每人每天一筆」。業務邏輯在 `/report` 的 POST handler 中處理（查詢後更新或新增）。若直接操作資料庫可能產生重複記錄，薪資計算會加總所有記錄。

### 14.2 無 CSRF 保護

所有 POST 表單無 CSRF token 保護。在私有內網部署或信任環境下風險較低，但公開部署應加入 Flask-WTF 的 CSRF 機制。（見 security_report.md）

### 14.3 稅務計算基數

稅務支出計算基數為「工項薪資毛額」，不包含固定薪資。此為業務決策，非 bug。

### 14.4 保留金年度邏輯

保留金以「計薪起始日的年份」決定年度（`date(sd.year, 1, 1)`），跨年度計薪可能有邊界問題。

### 14.5 銀行帳號格式

14 碼字串（3碼銀行分行 + 11碼帳號），前端僅驗證長度，無 checksum 驗證。

### 14.6 Session Secret Key

`SECRET_KEY` 預設為 `'dev-secret-key'`，生產環境必須透過環境變數設定強密鑰，否則 session 可被偽造。

---

*最後更新: 2026-06-30 | 由 Claude Sonnet 4.6 輔助生成*
