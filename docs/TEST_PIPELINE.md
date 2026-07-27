# Test Pipeline & CI/CD Flow

> **版本**: v1.0.6
> **更新日期**: 2026-07-27
> **系統規模**: 6,162 行 `app.py`、81 routes、9 data models
> **角色**: 雙角色（ADMIN / USER）、三工項系統（西區 32 欄 / 南區 37 欄 / 大表 25 欄）
> **現況**: 零測試覆蓋率、零 CI 基礎建設，本文件為從頭建立的完整規劃。
> **部署平台**: Railway (Nixpacks) + GitHub `main` 分支連動

---

## 目錄

1. [測試金字塔架構](#一測試金字塔架構)
2. [Phase 0 — 測試基礎建設](#二phase-0--測試基礎建設)
3. [Phase 1 — Unit Tests](#三phase-1--unit-tests純邏輯無-io)
4. [Phase 2 — Integration Tests](#四phase-2--integration-testsroute--db)
5. [Phase 3 — E2E Tests](#五phase-3--e2e-testsplaywright)
6. [Phase 4 — 安全靜態掃描](#六phase-4--安全靜態掃描)
7. [CI/CD Pipeline（GitHub Actions）](#七cicd-pipelinegithub-actions)
8. [GitHub Secrets 設定](#八github-secrets-必要設定)
9. [app.py 必要小改動](#九apppy-需要的小改動支援測試環境)
10. [實施優先順序](#十實施優先順序)
11. [Coverage 目標](#十一coverage-目標與-definition-of-done)
12. [已知風險與限制](#十二已知風險與限制)

---

## 一、測試金字塔架構

```
                     ┌──────────────────────┐
                     │   E2E (Playwright)   │  5–10 個黃金路徑
                     │   Staging server     │  觸發：merge to main
                    ─┴──────────────────────┴─
                   /   Integration (pytest)   \  ~120 個 route + DB 測試
                  /    pytest-flask + SQLite    \  觸發：push to main / PR
                 ──────────────────────────────
                /        Unit (pytest)           \  ~80 個純邏輯測試
               /    zero I/O, zero DB, mock all   \  觸發：所有 push
              ────────────────────────────────────
```

**測試哲學**：以業務風險排優先順序

```
薪資計算錯誤 > 庫存不變式破壞 > 授權漏洞 > 一般功能回歸
```

---

## 二、Phase 0 — 測試基礎建設

### 2.1 目錄結構

```
tests/
├── conftest.py               # 全域 fixture：app, client, db, seed
├── unit/
│   ├── test_salary.py        # 薪資計算邏輯
│   ├── test_retention.py     # 保留金計算
│   ├── test_material_invariant.py  # 庫存不變式
│   ├── test_collab.py        # 共同作業分配
│   └── test_filters.py       # Jinja2 template filters
├── integration/
│   ├── test_auth.py          # 認證與授權
│   ├── test_report.py        # 回報提交
│   ├── test_confirmation.py  # 確認流程
│   ├── test_materials.py     # 材料管理
│   ├── test_salary_route.py  # 薪資路由
│   ├── test_bm.py            # 大表（BM）系統
│   ├── test_ledger.py        # 流水帳
│   ├── test_settings.py      # 設定
│   └── test_security.py      # 安全測試
└── e2e/
    ├── test_user_golden_path.py   # USER 黃金路徑
    └── test_admin_golden_path.py  # ADMIN 黃金路徑
```

### 2.2 測試環境設定（conftest.py）

```python
# tests/conftest.py
import pytest
from app import app as flask_app


@pytest.fixture(scope='session')
def app():
    flask_app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'WTF_CSRF_ENABLED': False,     # 關閉 CSRF（整合測試層）
        'SECRET_KEY': 'test-secret-key',
        'RATELIMIT_ENABLED': False,    # 關閉速率限制
        'BANK_ENCRYPT_KEY': '',        # 停用 Fernet 加密（明文）
        'R2_ACCOUNT_ID': '',           # 停用 R2 client
        # APScheduler 需在 app.py 加 TESTING 守門條件
    })
    with flask_app.app_context():
        from models import db
        db.create_all()
        yield flask_app
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def db_rollback(app):
    """每個 test function 結束後 rollback，確保測試隔離"""
    from models import db
    yield
    db.session.rollback()
    db.session.remove()


# ── User Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def admin_user(app):
    from models import db, User
    from werkzeug.security import generate_password_hash
    u = User(display_name='test_admin', role='ADMIN',
             password_hash=generate_password_hash('password'),
             zone='西區', is_active=True)
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def west_user(app):
    from models import db, User
    from werkzeug.security import generate_password_hash
    u = User(display_name='west_user01', role='USER',
             password_hash=generate_password_hash('password'),
             zone='西區', is_active=True)
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def south_user(app):
    from models import db, User
    from werkzeug.security import generate_password_hash
    u = User(display_name='south_user01', role='USER',
             password_hash=generate_password_hash('password'),
             zone='南區', is_active=True)
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def bm_user(app):
    from models import db, User
    from werkzeug.security import generate_password_hash
    u = User(display_name='bm_user01', role='USER',
             password_hash=generate_password_hash('password'),
             zone='西區', is_active=True, is_big_meter=True)
    db.session.add(u)
    db.session.commit()
    return u


# ── Login Helper ──────────────────────────────────────────────────────────

def login(client, display_name, password='password'):
    return client.post('/login', data={
        'display_name': display_name,
        'password': password
    }, follow_redirects=True)
```

### 2.3 工具鏈（requirements-dev.txt）

| 套件 | 版本 | 用途 |
|------|------|------|
| `pytest` | 8.x | 測試 runner |
| `pytest-flask` | 1.3.x | Flask app context 整合 |
| `pytest-cov` | 5.x | 覆蓋率報告 |
| `pytest-xdist` | 3.x | 並行測試（`-n auto`）|
| `playwright` | 1.x | E2E 瀏覽器自動化 |
| `bandit` | 1.8.x | Python 靜態安全掃描（SAST）|
| `ruff` | 0.x | Lint + format check |
| `safety` | 3.x | 依賴套件 CVE 掃描 |

---

## 三、Phase 1 — Unit Tests（純邏輯，無 I/O）

**觸發**：所有 branch push
**執行時間目標**：< 60 秒
**覆蓋率目標**：計算函數 ≥ 85%

### 3.1 薪資計算（test_salary.py）— P0

| 測試案例 | 說明 | 驗證重點 |
|---------|------|----------|
| `test_west_single_user_gross` | 西區單人，3 個工項有值 | `gross = Σ(qty × price)`，精確到元 |
| `test_south_single_user_gross` | 南區單人，`s_orig_13=2, s_dsv_25=1` | 使用 SOUTH 單價，非 WEST |
| `test_bm_single_user_gross` | 大表用戶 `bm_50_down=2` | BM 單價，無保留金 |
| `test_collab_2_persons_split` | qty=6，collab_count=2 | 每人得 3.0（精確 Numeric 除法）|
| `test_collab_3_persons_split` | qty=1，collab_count=3 | 每人得 0.333...（float 累加，不四捨五入）|
| `test_fixed_salary_10th_payday` | `is_10th_payday=True`，fixed=5000 | final += 5000 |
| `test_fixed_salary_every_period` | `fixed_salary_every_period=True` | 每期加，不論是否 10 日 |
| `test_fixed_salary_not_10th` | `is_10th_payday=False`，`every_period=False` | fixed = 0 |
| `test_insurance_deduction_10th` | `insurance=834`，`is_10th=True` | final -= 834 |
| `test_insurance_deduction_not_10th` | `is_10th=False` | ins = 0，不扣 |
| `test_tax_not_enrolled` | `insurance=0`，`tax_exempt=False` | `tax = round(gross × rate / 100)` |
| `test_tax_enrolled` | `insurance > 0` | tax = 0（已加保免稅）|
| `test_tax_exempt_flag` | `tax_exempt=True`，`insurance=0` | tax = 0 |
| `test_net_salary_formula` | `net = gross - retention` | 公式正確 |
| `test_final_salary_formula` | `final = net + fixed - ins - tax` | 公式正確 |
| `test_admin_no_retention` | ADMIN role | `retention = 0` |
| `test_bm_no_retention` | `is_big_meter=True` | `retention = 0` |

### 3.2 保留金系統（test_retention.py）— P0

| 測試案例 | 說明 |
|---------|------|
| `test_retention_cap` | 計算值超過 60,000 → clamp 至 60,000 |
| `test_retention_floor` | 計算值為負 → clamp 至 0 |
| `test_retention_offset_positive` | offset=1,000，calculated=50,000 → ytd=51,000（不超過 cap）|
| `test_retention_offset_exceeds_cap` | calculated + offset > 60,000 → 仍 = 60,000 |
| `test_period_retention_cap` | ytd_before=55,000，period_raw=8,000 → period=5,000（不超剩餘 cap）|
| `test_west_8_fields` | `WEST_RETENTION_FIELDS` = 8 欄（direct + indirect）|
| `test_south_28_fields` | `SOUTH_RETENTION_FIELDS` = 28 欄 |
| `test_per_user_rate_override` | `UserRetentionRate.rate=30 > global=20`，應用個人費率 |
| `test_global_rate_fallback` | 無 `UserRetentionRate` 記錄 → 使用全域費率 |
| `test_collab_retention_split` | qty=6，collab_count=3 → 每人 2 只 × rate |

### 3.3 材料庫存不變式（test_material_invariant.py）— P0

**不變式**：`received_quantity = cumulative_usage + remaining_quantity`

```python
def assert_invariant(m):
    assert m.received_quantity == m.cumulative_usage + m.remaining_quantity
```

| 測試案例 |
|---------|
| 新增材料後不變式成立 |
| 核准申請（扣庫存、加累計使用量）後不變式成立 |
| 暫存區解決-信任A（保留 A 系統值）後不變式成立 |
| 暫存區解決-信任B（採用 B 系統值更新）後不變式成立 |
| 邊界：`remaining_quantity` 不能為負（`max(0, ...)` 防護）|

### 3.4 共同作業分配（test_collab.py）— P1

| 測試案例 |
|---------|
| `collab_count=1` → 1/1 = 100%（無共同作業）|
| `collab_count=7`（最大上限）→ 每人 1/7 |
| `collab_count=None`（舊資料相容）→ 視為 1 |
| 協作者驗證：跨區用戶被過濾（`zone != submitter.zone`）|
| 協作者驗證：非 USER role 被過濾 |
| 協作者驗證：已停用帳號（`is_active=False`）被過濾 |
| `collab_ids` 上限 6 人（`[:6]` 截斷）|

### 3.5 Jinja2 Template Filters（test_filters.py）— P2

| Filter | 測試案例 |
|--------|---------|
| `qty` | `3` → `"3"`；`3.1` → `"3.1"`；`0` → `""`；`0.0` → `""` |
| `mat_qty` | `1.000` → `"1"`；`1.500` → `"1.5"` |
| `money` | `1234567` → `"1,234,567"` |
| `from_json` | 有效 JSON string → dict；無效字串 → `{}` |
| `tw_time` | datetime → `"2026-07-27 14:30"` |

---

## 四、Phase 2 — Integration Tests（Route + DB）

**觸發**：push to `main` 或 PR opened
**執行時間目標**：< 5 分鐘
**DB 環境**：SQLite `:memory:`（`conftest.py` 設定）

### 4.1 認證與授權（test_auth.py）— P0

| 測試案例 | 預期結果 |
|---------|----------|
| 正確帳密登入 | 302 redirect，session 有 `user_id` |
| 錯誤密碼 | 200，flash 含錯誤訊息，無 session |
| 已停用帳號登入 | 200，flash 拒絕訊息 |
| 未登入 `GET /report` | 302 → `/login` |
| 未登入 `GET /confirmation` | 302 → `/login` |
| USER `GET /confirmation` | 403 或 redirect |
| USER `POST /materials/add` | 403 或 redirect |
| USER `POST /settings/users/create` | 403 或 redirect |
| ADMIN `GET /report` | 302 → `/summary` |
| 登出後 `GET /report` | 302 → `/login`（session 失效）|

### 4.2 回報提交（test_report.py）— P0

**西區 USER**：

| 測試案例 | 驗證 |
|---------|------|
| `GET /report` | 200，包含 32 個西區工項欄位名稱 |
| `POST` 有效西區回報（`direct_13=3`）| 302，DB 新增 `Report`，`is_confirmed=False` |
| `POST` 含跨區協作者（south_user.id）| `collab_ids` 被過濾（跨區不合法）|
| `POST` 含有效協作者（同區 USER）| `collab_count=2`，`collab_json=[uid]` |

**南區 USER**：

| 測試案例 | 驗證 |
|---------|------|
| `GET /report` | 包含 `s_orig_13` 等南區欄位，不含 `original_change` |
| `POST` 有效南區回報 | 值正確儲存至 `s_orig_13` 等南區欄位 |

**大表 USER**：

| 測試案例 | 驗證 |
|---------|------|
| `GET /report` | 包含 `bm_50_down` 等 25 個大表欄位 |
| `POST` 有效大表回報 | `bm_50_down` 欄位正確儲存 |

### 4.3 確認流程（test_confirmation.py）— P0

| 測試案例 | 驗證 |
|---------|------|
| ADMIN `GET /confirmation` | 200，顯示待確認回報 |
| 單筆確認 `POST .../confirm` | `is_confirmed=True`，AuditLog 1 筆 |
| 單筆駁回 `POST .../reject` | `is_rejected=True` |
| 批次確認（3 筆）| 3 筆 `is_confirmed=True`，AuditLog 3 筆 |
| 批次駁回（2 筆）| 2 筆 `is_rejected=True` |
| 批次送出空 ids | flash `'請先勾選項目'`，0 筆 DB 變動 |
| 重複確認（已確認 id 再送批次）| 跳過，不重複 commit |
| 自訂工項 `POST .../custom-item` | `custom_item_name/qty/price` 更新至 DB |

### 4.4 材料管理（test_materials.py）— P0

| 測試案例 | 驗證 |
|---------|------|
| USER `GET /materials`（有隱藏材料）| 隱藏材料不在 response |
| ADMIN `GET /materials` | 隱藏材料顯示（含 `is_hidden=True` 資料）|
| USER 申請材料（庫存 > 0）| `MaterialRequest` status=PENDING |
| USER 申請材料（庫存 = 0）| flash 錯誤，無 DB 新增 |
| ADMIN 批次核准（2 筆）| 各自扣庫存，`cumulative_usage` 增加，不變式成立 |
| ADMIN 批次駁回（1 筆）| status=REJECTED，庫存不變 |
| AJAX toggle-hidden | 回傳 `{"ok": true, "is_hidden": <bool>}`，DB 更新 |
| AJAX move-up | 回傳 `{"ok": true, "swapped": true}`，`sort_order` 交換 |
| AJAX move-up（第一行）| 回傳 `{"ok": true, "swapped": false}` |
| 暫存區批次解決-信任A | `is_quarantined=False`，不變式成立 |
| 暫存區批次解決-信任B | B 數值覆蓋 A 系統值，不變式成立 |
| 重置庫存 | 所有 `remaining=0`，`mat_last_import_name` Key 刪除 |

### 4.5 薪資計算路由（test_salary_route.py）— P1

| 測試案例 | 驗證 |
|---------|------|
| `GET /salary`（無資料）| 200，`salary_results=None` |
| `POST /salary` with date range | 200，包含用戶名稱和計算結果 |
| 含共同作業分配（collab_count=2）| 兩人各得 1/2 只數 |
| 停用帳戶已確認回報仍計入 | 結果顯示「（停用）」標記 |
| `GET /salary?export=excel` | Content-Type = xlsx，可被 openpyxl 解析 |
| `GET /salary?export=pdf` | Content-Type = application/pdf，非空檔案 |

### 4.6 大表（BM）系統（test_bm.py）— P1

| 測試案例 | 驗證 |
|---------|------|
| BM USER `POST /report` | `bm_*` 欄位正確儲存 |
| ADMIN `GET /bm/confirmation` | 只顯示 `is_big_meter=True` 用戶的回報 |
| `/bm/confirmation` 不含一般 USER 回報 | 一般用戶回報不出現 |
| BM 回報確認 | `is_confirmed=True`，AuditLog 記錄 |
| `GET /bm/summary` | 200，含大表計算結果 |

### 4.7 流水帳（test_ledger.py）— P1

| 測試案例 | 驗證 |
|---------|------|
| `POST /ledger/add`（收入）| `entry_type=INCOME`，amount > 0 |
| `POST /ledger/add`（支出）| `entry_type=EXPENSE` |
| `POST /ledger/add` 金額填負數 | flash 錯誤，無 DB 新增 |
| `GET /ledger/export` | xlsx 格式，可被 openpyxl 解析 |

### 4.8 設定（test_settings.py）— P1

| 測試案例 | 驗證 |
|---------|------|
| `POST /settings/users/create` | 新增 `User`，`display_name` 唯一 |
| `POST /settings/tax-rate` | SystemConfig `tax_rate` 更新 |
| `POST /settings/item-prices` | 西區單價更新，price cache 清除 |
| `POST /settings/item-prices-south` | 南區單價獨立更新，不影響西區 |
| `POST /settings/users/<id>/zone` | `User.zone` 更新至指定區域 |
| `POST /settings/mat-tabs` | `mat_tab_1_name` SystemConfig 更新 |

### 4.9 安全測試（test_security.py）— P0

| 測試案例 | 驗證 |
|---------|------|
| 所有 `@admin_required` routes：USER 直接 POST | 全部 403/302 |
| 跨用戶：USER_A `DELETE` USER_B 的 report | 403/404 |
| 跨用戶：USER_A cancel USER_B 的材料申請 | 403/404 |
| 材料申請 `requested_quantity=-1` | 被拒，無 DB 新增 |
| 材料申請 `requested_quantity=999999999` | 被拒或後端截斷 |
| 備註超過 50 字 | 截斷至 50 字後儲存 |
| `GET /settings` response body | 不含 14 位純數字明文銀行帳號 |

### 4.10 Excel 匯出格式驗證（通用 helper）— P2

適用所有 `export-excel` 端點：

```python
import io, openpyxl

def assert_valid_excel(response):
    assert response.status_code == 200
    assert 'spreadsheetml' in response.content_type
    assert 'attachment' in response.headers.get('Content-Disposition', '')
    wb = openpyxl.load_workbook(io.BytesIO(response.data))
    assert len(wb.sheetnames) >= 1
    assert wb.active.max_row >= 1  # 非空白
```

涵蓋端點：`/history/export-excel`、`/bm/history/export-excel`、`/materials/export-excel`、`/ledger/export`、`/summary/export-excel`、`/bm/summary/export-excel`

---

## 五、Phase 3 — E2E Tests（Playwright）

**觸發**：merge to `main` → staging deploy 完成後自動觸發
**環境**：Railway staging（獨立 DB，非生產）
**原則**：只測黃金路徑，不追求全覆蓋

### 5.1 USER 西區黃金路徑

```
1. 開啟 staging URL
2. 以 west_user 帳密登入 → 確認 redirect 至 /report
3. 填入 direct_13=2, mobilization=1 → 送出
4. 確認 flash 成功訊息，表單重置
5. 至材料庫存頁 → 申請一項有庫存材料，備註填「E2E test」
6. 確認申請 PENDING 狀態出現在申請紀錄
7. 至個人統計頁 → 確認今日工項數字顯示
```

### 5.2 ADMIN 黃金路徑

```
1. 以 admin 登入
2. 至確認頁面 → 看到 5.1 的回報
3. 勾選 → 批次確認 → 確認 flash 成功，回報從列表消失
4. 至材料庫存 → 看到 5.1 的材料申請 → 批次核准
5. 確認庫存數字正確減少（不變式成立）
6. 至薪資計算 → 輸入今日日期 → 確認 west_user 有工項數字
```

### 5.3 回歸守衛

```
- 登入失敗 response body 不含 "$2b$"（bcrypt hash 不洩漏）
- 確認後回報在 USER /history 顯示「已確認」badge
- 隱藏材料後 USER /materials 不顯示該材料
- ADMIN /materials 仍顯示已隱藏材料（含 opacity-50 樣式）
```

---

## 六、Phase 4 — 安全靜態掃描

**觸發**：PR to `main`（非每次 push，避免雜訊）

```bash
# SAST — Python 靜態安全掃描
bandit -r app.py models.py -ll -f json -o bandit-report.json

# SCA — 依賴套件 CVE 掃描
safety check --json -o safety-report.json

# Lint
ruff check app.py models.py --output-format=github
```

**Pipeline Gate 條件**：

| 條件 | 結果 |
|------|------|
| bandit HIGH severity = 0 | ✅ pass |
| bandit HIGH severity ≥ 1 | ❌ pipeline fail |
| safety CRITICAL CVE = 0 | ✅ pass |
| safety CRITICAL CVE ≥ 1 | ❌ pipeline fail |

---

## 七、CI/CD Pipeline（GitHub Actions）

### 7.1 Pipeline 結構圖

```
任意 branch push
       │
       ▼
┌─────────────────────┐
│  Job 1: lint        │  ruff + bandit（快速，< 30s）
└──────┬──────────────┘
       │ pass
       ▼
┌─────────────────────┐
│  Job 2: unit-test   │  pytest tests/unit/ --tb=short
└──────┬──────────────┘  目標 < 60s
       │ pass
       ▼（以下僅 main branch 或 PR→main）
┌─────────────────────┐
│  Job 3: integ-test  │  pytest tests/integration/ --cov=app
└──────┬──────────────┘  coverage gate ≥ 70%，目標 < 5min
       │ pass
       ▼
┌─────────────────────┐
│  Job 4: security    │  bandit + safety（< 1min）
└──────┬──────────────┘
       │ pass（僅 main）
       ▼
┌─────────────────────┐
│  Job 5: staging     │  Railway staging deploy
│         deploy      │
└──────┬──────────────┘
       │ success
       ▼
┌─────────────────────┐
│  Job 6: e2e-test    │  playwright test（< 10min）
└──────┬──────────────┘
       │ pass
       ▼
┌─────────────────────┐
│  Job 7: approval    │  GitHub Environment Protection Rule
│  (manual gate)      │  PM 或 TL 點選 Approve
└──────┬──────────────┘
       │ approved
       ▼
┌─────────────────────┐
│  Job 8: prod-deploy │  Railway production deploy
└──────┬──────────────┘
       │ success
       ▼
┌─────────────────────┐
│  Job 9: smoke-test  │  curl health-check + 登入頁 HTTP 200
└─────────────────────┘  目標 < 1min
```

### 7.2 GitHub Actions YAML（`.github/workflows/ci.yml`）

```yaml
name: CI/CD Pipeline

on:
  push:
    branches: ["**"]
  pull_request:
    branches: [main]

env:
  PYTHON_VERSION: "3.11"

jobs:

  # ── Job 1: Lint ────────────────────────────────────────────────────────
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "${{ env.PYTHON_VERSION }}" }
      - run: pip install ruff bandit
      - run: ruff check app.py models.py --output-format=github
      - run: bandit -r app.py models.py -ll

  # ── Job 2: Unit Tests ──────────────────────────────────────────────────
  unit-test:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "${{ env.PYTHON_VERSION }}" }
      - run: pip install -r requirements.txt pytest pytest-flask pytest-cov
      - run: pytest tests/unit/ -v --tb=short --cov=app --cov-report=xml
      - uses: actions/upload-artifact@v4
        with: { name: unit-coverage, path: coverage.xml }

  # ── Job 3: Integration Tests ───────────────────────────────────────────
  integration-test:
    runs-on: ubuntu-latest
    needs: unit-test
    if: github.ref == 'refs/heads/main' || github.event_name == 'pull_request'
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "${{ env.PYTHON_VERSION }}" }
      - run: pip install -r requirements.txt pytest pytest-flask pytest-cov
      - run: pytest tests/integration/ -v --tb=short --cov=app --cov-fail-under=70
      - uses: actions/upload-artifact@v4
        with: { name: integ-coverage, path: coverage.xml }

  # ── Job 4: Security Scan ───────────────────────────────────────────────
  security-scan:
    runs-on: ubuntu-latest
    needs: integration-test
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - run: pip install bandit safety
      - run: bandit -r app.py models.py -ll -f json -o bandit-report.json
      - run: safety check
      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: security-reports, path: "*.json" }

  # ── Job 5: Staging Deploy ──────────────────────────────────────────────
  staging-deploy:
    runs-on: ubuntu-latest
    needs: security-scan
    if: github.ref == 'refs/heads/main'
    environment: staging
    steps:
      - uses: actions/checkout@v4
      - name: Deploy to Railway Staging
        run: |
          curl -s https://railway.app/api/deploy \
            -H "Authorization: Bearer ${{ secrets.RAILWAY_TOKEN }}" \
            -d '{"environmentId": "${{ secrets.RAILWAY_STAGING_ENV_ID }}"}'

  # ── Job 6: E2E Tests ───────────────────────────────────────────────────
  e2e-test:
    runs-on: ubuntu-latest
    needs: staging-deploy
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "${{ env.PYTHON_VERSION }}" }
      - run: pip install playwright pytest-playwright
      - run: playwright install chromium
      - run: pytest tests/e2e/ -v --tb=short
        env:
          BASE_URL: ${{ secrets.STAGING_URL }}
          ADMIN_PASSWORD: ${{ secrets.TEST_ADMIN_PASSWORD }}
          USER_PASSWORD: ${{ secrets.TEST_USER_PASSWORD }}

  # ── Job 7+8: Manual Approval → Production Deploy ───────────────────────
  prod-deploy:
    runs-on: ubuntu-latest
    needs: e2e-test
    if: github.ref == 'refs/heads/main'
    environment: production   # GitHub Environment Protection Rule → Manual Approval
    steps:
      - uses: actions/checkout@v4
      - name: Deploy to Railway Production
        run: |
          curl -s https://railway.app/api/deploy \
            -H "Authorization: Bearer ${{ secrets.RAILWAY_TOKEN }}" \
            -d '{"environmentId": "${{ secrets.RAILWAY_PROD_ENV_ID }}"}'

  # ── Job 9: Smoke Test ──────────────────────────────────────────────────
  smoke-test:
    runs-on: ubuntu-latest
    needs: prod-deploy
    steps:
      - name: Production Health Check
        run: |
          HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" ${{ secrets.PROD_URL }}/login)
          [ "$HTTP_CODE" = "200" ] || (echo "Smoke test FAILED: HTTP $HTTP_CODE" && exit 1)
          echo "Smoke test PASSED: HTTP $HTTP_CODE"
```

---

## 八、GitHub Secrets 必要設定

| Secret | 說明 |
|--------|------|
| `RAILWAY_TOKEN` | Railway API token（至 Railway 帳號設定取得）|
| `RAILWAY_STAGING_ENV_ID` | Staging environment ID |
| `RAILWAY_PROD_ENV_ID` | Production environment ID |
| `STAGING_URL` | Staging server URL（E2E 測試目標，如 `https://xxx-staging.railway.app`）|
| `PROD_URL` | Production URL（smoke test，如 `https://xxx.railway.app`）|
| `TEST_ADMIN_PASSWORD` | E2E staging 用 ADMIN 帳號密碼 |
| `TEST_USER_PASSWORD` | E2E staging 用 USER 帳號密碼 |

---

## 九、app.py 需要的小改動（支援測試環境）

測試環境啟動時，兩處 module-level 副作用需要守門：

**改動 1 — APScheduler（`app.py` 末尾）**

```python
# 原本（直接初始化）
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    ...
    _scheduler.start()

# 改為（加入 TESTING 守門）
if not app.config.get('TESTING'):
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        ...
        _scheduler.start()
    except Exception as _e_sched:
        ...
```

**改動 2 — 無需修改**

`_init_db()` 中的 `UPDATE materials SET sort_order = id WHERE sort_order = 0` 在 SQLite 可正常執行，無需修改。

`boto3` R2 client：`R2_ACCOUNT_ID=''` 時 `_r2_client=None`，所有 R2 操作 silently skip，測試環境下行為正確。

---

## 十、實施優先順序

| 優先 | 項目 | 工時估計 | 業務風險說明 |
|------|------|---------|-------------|
| **P0** | Phase 0 基礎建設（conftest.py + 工具鏈）| 0.5 天 | 無此無法跑任何測試 |
| **P0** | Phase 1.1 薪資計算 unit tests（17 案例）| 1 天 | 薪資錯誤直接影響發放 |
| **P0** | Phase 1.2 保留金 unit tests（10 案例）| 0.5 天 | 60,000 NTD 上限邏輯複雜 |
| **P0** | Phase 1.3 材料不變式 unit tests（5 案例）| 0.5 天 | 庫存損壞難以追溯 |
| **P0** | Phase 2.1 認證授權 integration（11 案例）| 0.5 天 | 安全基線 |
| **P0** | Phase 2.9 安全測試 integration（8 案例）| 0.5 天 | 越權與輸入驗證 |
| **P0** | Phase 2.3 確認流程 integration（8 案例）| 0.5 天 | 主要 ADMIN 工作流 |
| **P1** | Phase 2.4 材料管理 integration（12 案例）| 1 天 | 材料模組剛大改 |
| **P1** | Phase 2.2 回報提交 integration（8 案例）| 0.5 天 | 最高頻操作 |
| **P1** | `.github/workflows/ci.yml` + GitHub Secrets | 0.5 天 | CI/CD 自動化 |
| **P2** | Phase 1.4/1.5 其他 unit tests | 0.5 天 | |
| **P2** | Phase 2.5~2.8/2.10 其他 integration | 1.5 天 | |
| **P2** | Phase 4 靜態安全掃描（CI 整合）| 0.5 天 | |
| **P3** | Phase 3 E2E tests（Playwright）| 2 天 | 需 staging 環境就緒 |
| **P3** | Railway staging environment 建立 | 0.5 天 | |

**總估計：約 11–12 個工作天，完整 CI/CD pipeline 上線。**

---

## 十一、Coverage 目標與 Definition of Done

| 指標 | 目標 | 說明 |
|------|------|------|
| Unit test coverage（計算函數）| ≥ 85% | pytest-cov 量測 |
| Integration test pass rate | 100% | merge gate，任一 fail 不得合併 |
| Security scan HIGH severity | 0 | bandit hard block |
| Security scan CRITICAL CVE | 0 | safety hard block |
| E2E test pass rate | 100% | prod deploy gate |
| CI pipeline 平均時間 | < 10 分鐘 | push → lint + unit 結果出爐 |
| Production smoke test | HTTP 200 | 登入頁正常回應 |

---

## 十二、已知風險與限制

| 風險 | 影響 | 緩解方案 |
|------|------|---------|
| SQLite 不支援 PostgreSQL 特性 | `collab_json::jsonb @>` GIN 查詢、`ALTER COLUMN TYPE` 在 SQLite 無法執行 | Integration test mock 這些路徑，或在 CI 另起 PostgreSQL service container |
| APScheduler module-level 初始化 | pytest import app 時啟動排程器 | app.py 加 `TESTING` flag 守門（見第九節）|
| boto3 R2 client | 測試時若 R2 env var 非空會嘗試真實連線 | conftest.py 確保 `R2_ACCOUNT_ID=''` |
| Fernet 加密 | `BANK_ENCRYPT_KEY=''` 時明文存取 | 測試環境預期行為，加密測試留 P3 |
| Railway staging 環境 | 目前不存在，E2E job 無目標 | 建立前 e2e-test job 設 `continue-on-error: true` |
| BM 子系統 E2E | 需獨立的 bm_user 與 staging 資料 | 優先覆蓋一般 USER，BM E2E 納入 P3 後續 |
| 大量 migration SQL 在 SQLite | 部分 `ALTER TABLE` 語法不相容 | `_init_db()` 中的 migration 用 try/except，已可在 SQLite 靜默跳過 |
