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

同 v1.0.5，用於個別帳戶客製保留金費率。大表用戶與 ADMIN 不使用此表。

### 4.8 audit_logs 表

同 v1.0.5。Action types 詳見第 17 節。

### 4.9 ledger_entries / report_archives 表

同 v1.0.3，無變動。

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

### 6.3 其他路由

與 v1.0.5 相同（`/report`、`/bm_confirmation`、`/salary`、`/history`、`/summary`、`/settings`、`/ledger`、`/report_archives`、`/personal_stats`）。

---

## 7. 南/西區分區系統

同 v1.0.5，詳見 v1.0.5 規格書第 7 節。

---

## 8. 大表（BM）用戶系統

同 v1.0.5，詳見 v1.0.5 規格書第 8 節。

---

## 9. 共同作業系統

同 v1.0.4，詳見 v1.0.5 規格書第 9 節。

---

## 10. 薪資計算邏輯（核心業務）

同 v1.0.5，詳見 v1.0.5 規格書第 10 節。

---

## 11. 保留金系統

同 v1.0.5，詳見 v1.0.5 規格書第 11 節。

---

## 12. 匯出功能

### 12.1 薪資 Excel / PDF / Word

同 v1.0.5。

### 12.2 日月報 Excel

同 v1.0.5。

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

同 v1.0.3，詳見 v1.0.3/v1.0.5 規格書第 14 節。

---

## 15. 日月報檔案庫（ReportArchive）

同 v1.0.3，詳見 v1.0.5 規格書第 15 節。

---

## 16. Cloudflare R2 儲存

同 v1.0.5，詳見 v1.0.5 規格書第 16 節。

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
   - v1.0.3–v1.0.5 欄位：略（詳見 v1.0.5 規格書）
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

同 v1.0.5。側欄收合狀態存於 `localStorage.ycSidebarCollapsed`。

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
