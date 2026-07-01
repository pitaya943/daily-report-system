# 安全性報告 — 員工日報回報系統

> 版本: v1.0.3 | 日期: 2026-07-01 | 類型: 內部審查

---

## 執行摘要

本系統為工程隊內部管理工具，部署於 Railway 公有雲，可透過公開 URL 存取。以下列出所有已識別的安全問題，依風險等級排序，並提供修復建議。

**風險等級**: 🔴 高 | 🟡 中 | 🟢 低 | ⚪ 資訊

---

## 🔴 高風險問題（以下高風險問題均已在 v1.0.2/v1.0.3 修復）

### SEC-001: 缺少 CSRF 保護 ✅ 已修復（v1.0.2）

**問題描述**:  
系統所有 POST 表單無 CSRF（Cross-Site Request Forgery）保護機制。攻擊者可製作惡意頁面，誘導已登入的 ADMIN 執行非預期操作（刪除帳戶、修改薪資、批次確認回報等）。

**影響範圍**: 所有 POST 路由（設定、薪資計算、確認、回報等）

**攻擊情境**:  
1. 攻擊者製作惡意 HTML（含隱藏表單指向系統 URL）
2. ADMIN 點擊連結（或訪問含惡意圖片的頁面）
3. 瀏覽器攜帶合法 Cookie 發出 POST 請求
4. 系統執行攻擊者的操作

**修復建議**:
```python
# 安裝 flask-wtf
pip install flask-wtf

# app.py
from flask_wtf.csrf import CSRFProtect
csrf = CSRFProtect(app)

# base.html — 所有表單加入
<form method="POST">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  ...
</form>
```

**緊急程度**: 立即修復（若系統對外公開）

---

### SEC-002: 弱預設 Secret Key ✅ 已修復（v1.0.2）

**問題描述**:  
`app.py` 中 `SECRET_KEY` 預設值為硬編碼字串 `'dev-secret-key'`。若生產環境未設定 `SECRET_KEY` 環境變數，Flask session cookie 可被任意偽造，攻擊者可以任何帳戶身份存取系統（包含 ADMIN）。

**相關程式碼**:
```python
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
```

**攻擊情境**: 攻擊者知道預設 key → 偽造 `user_id=1`（ADMIN）的 session cookie → 完全控制系統

**修復建議**:
```python
# 方法 1：啟動時強制要求
secret = os.environ.get('SECRET_KEY')
if not secret:
    raise RuntimeError("SECRET_KEY 環境變數未設定，拒絕啟動")
app.config['SECRET_KEY'] = secret

# 生成強密鑰（執行一次取值）
python -c "import secrets; print(secrets.token_hex(32))"
```

**緊急程度**: 確認 Railway 環境變數已正確設定

---

### SEC-003: 無速率限制（Rate Limiting）✅ 已修復（v1.0.2）

**問題描述**:  
登入介面（`/login`）無暴力破解防護。攻擊者可無限次嘗試密碼組合。

**攻擊情境**: 工具自動化每秒數十次登入嘗試，短時間破解弱密碼帳戶

**修復建議**:
```python
# 安裝
pip install flask-limiter

# app.py
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")  # 登入介面：每分鐘最多 10 次
def login():
    ...
```

---

## 🟡 中風險問題

### SEC-004: 密碼無複雜度要求（⚠️ 未修復）

**問題描述**:  
ADMIN 建立帳戶或重設密碼時無密碼複雜度驗證，允許 `"1234"` 或單字元密碼。

**修復建議**:
```python
def validate_password(pw: str) -> bool:
    return (
        len(pw) >= 8 and
        any(c.isdigit() for c in pw) and
        any(c.isalpha() for c in pw)
    )
```

在帳戶建立和密碼重設路由中加入驗證。

---

### SEC-005: Session 無過期時間 ✅ 已修復（v1.0.2）

**問題描述**:  
登入後 session 未設定自動過期時間。若用戶在公共電腦登入後未登出，其他人可持續存取系統。

**修復建議**:
```python
from datetime import timedelta
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = True  # 僅 HTTPS

# 登入時
login_user(user, remember=False)
session.permanent = True
```

---

### SEC-006: 錯誤訊息資訊洩露

**問題描述**:  
登入失敗時顯示 `'帳號或密碼錯誤'`，此為良好設計。但若 Flask 在開發模式（`DEBUG=True`）下運行，500 錯誤會顯示完整 traceback，包含資料庫路徑、環境變數等敏感資訊。

**修復建議**:
- 確認生產環境 `DEBUG=False`（或未設定 `FLASK_DEBUG`）
- Railway 環境中移除 `FLASK_DEBUG=1` 環境變數
- 加入自訂 500 錯誤頁面（`@app.errorhandler(500)`）

---

### SEC-007: 銀行帳號明文儲存 ✅ 已修復（v1.0.2）

**問題描述**:  
`users.bank_account` 以明文字串儲存於資料庫。若資料庫遭洩露，員工銀行帳號直接暴露。

**修復建議**:  
對銀行帳號進行可逆加密（如 AES-256-GCM），使用獨立的 `ENCRYPTION_KEY` 環境變數。匯出薪轉單時解密，存入資料庫時加密。

---

### SEC-008: 缺少 HTTP 安全標頭 ✅ 已修復（v1.0.2）

**問題描述**:  
系統未設定安全 HTTP 回應標頭，增加 XSS、Clickjacking 等攻擊面。

**修復建議**:
```python
# 安裝
pip install flask-talisman

from flask_talisman import Talisman
Talisman(
    app,
    force_https=True,
    strict_transport_security=True,
    content_security_policy={
        'default-src': "'self'",
        'script-src': ["'self'", 'cdn.jsdelivr.net'],
        'style-src': ["'self'", 'cdn.jsdelivr.net'],
    }
)
```

---

## 🟢 低風險問題

### SEC-009: 無輸入內容日誌

**問題描述**:  
系統記錄操作類型（REPORT_CREATE 等）但不記錄實際輸入值差異。若有惡意修改，難以事後追蹤具體變更內容。

**修復建議**:  
在 `REPORT_UPDATE`、`ACCOUNT_UPDATE` 等 audit log 中記錄修改前後的關鍵欄位值（已在部分路由中實作，如固定薪資修改記錄 `old → new`，可推廣至全部更新操作）。

---

### SEC-010: CDN 資源無 Subresource Integrity (SRI)

**問題描述**:  
Bootstrap 和 Bootstrap Icons 從 CDN 載入，若 CDN 遭攻擊（供應鏈攻擊），惡意 JS/CSS 可被注入。

**修復建議**:
```html
<!-- 加入 integrity 屬性 -->
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/..."
      rel="stylesheet"
      integrity="sha384-T3c6CoIi6uLrA9TneNEoa7RxnatzjcDSCmG1MXxSR1GAsXEV/Dwwykc2MPK8M2HN"
      crossorigin="anonymous">
```

---

### SEC-011: 材料申請無數量上限

**問題描述**:  
使用者可申請任意大量材料（如 999999 支）。雖有庫存檢查，但可能造成業務混亂。

**修復建議**:  
在 `/materials` POST handler 加入：`if qty <= 0 or qty > 1000: flash('數量超出範圍', 'danger')`

---

## ⚪ 資訊性說明

### SEC-012: 密碼雜湊強度

**現狀**: 使用 `werkzeug.security.generate_password_hash()`，預設為 `pbkdf2:sha256`，為業界標準，安全性足夠。

**建議**: 如需更高強度，可升級為 bcrypt 或 Argon2（需安裝額外套件）。

---

### SEC-013: SQL 注入防護

**現狀**: 全程使用 SQLAlchemy ORM，無原生 SQL 字串拼接，SQL 注入風險極低。部分 `_init_db()` 中的 DDL 使用 `text()` 但為硬編碼字串（無用戶輸入）。

**結論**: 此風險已有效控制。

---

### SEC-014: XSS 防護

**現狀**: Jinja2 預設自動跳脫（`{{ var }}` 等效 `{{ var | e }}`）。未使用 `| safe` 過濾器在用戶輸入上。

**結論**: XSS 風險已有效控制。

---

## 修復狀態摘要（v1.0.3）

| 優先級 | 問題 | 狀態 | 修復版本 |
|--------|------|------|----------|
| 1 | SEC-002 SECRET_KEY 生產設定 | ✅ 已修復 | v1.0.2 |
| 2 | SEC-001 CSRF 保護 | ✅ 已修復 | v1.0.2 |
| 3 | SEC-005 Session 過期設定 | ✅ 已修復 | v1.0.2 |
| 4 | SEC-003 登入速率限制 | ✅ 已修復 | v1.0.2 |
| 5 | SEC-006 確認 DEBUG=False | ✅ 已確認 | v1.0.2 |
| 6 | SEC-004 密碼複雜度 | ⚠️ 未修復 | — |
| 7 | SEC-008 安全 HTTP 標頭 | ✅ 已修復 | v1.0.2 |
| 8 | SEC-007 銀行帳號加密 | ✅ 已修復 | v1.0.2 |

> 唯一待修復項目：SEC-004 密碼複雜度要求（低優先級，系統為內部工具，帳號由 ADMIN 統一管理）

---

*報告生成日期: 2026-07-01 | 版本: v1.0.3 | 審查範圍: app.py, models.py, templates/*
