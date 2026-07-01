import io
import os
from datetime import datetime, date, timedelta
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, send_file, abort, session)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from cryptography.fernet import Fernet, InvalidToken

from models import db, User, Report, Material, MaterialRequest, AuditLog, SystemConfig, UserRetentionRate, LedgerEntry, ReportArchive

app = Flask(__name__)
_sk = os.environ.get('SECRET_KEY')
if not _sk:
    import logging as _logging
    _logging.warning('SECRET_KEY env var not set — using hardcoded fallback (unsafe for production)')
app.config['SECRET_KEY'] = _sk or 'daily-report-secret-2026-yc-local'

_db_url = os.environ.get('DATABASE_URL', 'sqlite:///daily_report.db')
# Supabase / Railway may return "postgres://" which SQLAlchemy 1.4+ rejects
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# 保持連線池熱機，避免每次請求重新建立 TCP 連線到 Supabase
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 1800,
    'pool_size': 3,
    'max_overflow': 3,
}

db.init_app(app)

# ---------------------------------------------------------------------------
# Security: SEC-001 CSRF / SEC-003 Rate Limiting / SEC-005 Session /
#           SEC-007 Bank Encryption / SEC-008 HTTP Headers
# ---------------------------------------------------------------------------

# SEC-005: Session security
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=10)
app.config['SESSION_COOKIE_HTTPONLY']    = True
app.config['SESSION_COOKIE_SAMESITE']   = 'Lax'
app.config['SESSION_COOKIE_SECURE']     = not app.debug  # HTTP 本機開發不受影響

# SEC-001: CSRF protection
csrf = CSRFProtect(app)

# SEC-003: Login rate limiting (memory backend, no Redis needed)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri='memory://',
)

# SEC-007: Bank account encryption (Fernet symmetric key)
_BANK_KEY_STR = os.environ.get('BANK_ENCRYPT_KEY', '').strip()
try:
    _fernet = Fernet(_BANK_KEY_STR.encode()) if _BANK_KEY_STR else None
except Exception:
    import logging as _log_init
    _log_init.warning('BANK_ENCRYPT_KEY invalid or malformed — bank encryption disabled')
    _fernet = None


def encrypt_bank(acct: str) -> str:
    if not _fernet or not acct:
        return acct
    return _fernet.encrypt(acct.encode()).decode()


def decrypt_bank(acct: str) -> str:
    if not _fernet or not acct:
        return acct
    try:
        return _fernet.decrypt(acct.encode()).decode()
    except (InvalidToken, Exception):
        return acct  # 過渡期：明文資料直接回傳


# Cloudflare R2 (S3-compatible object storage for ledger receipts)
_R2_ACCOUNT_ID        = os.environ.get('R2_ACCOUNT_ID', '').strip()
_R2_ACCESS_KEY_ID     = os.environ.get('R2_ACCESS_KEY_ID', '').strip()
_R2_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY', '').strip()
_R2_BUCKET            = os.environ.get('R2_BUCKET_NAME', '').strip()

_r2_client = None
if _R2_ACCOUNT_ID and _R2_ACCESS_KEY_ID and _R2_SECRET_ACCESS_KEY and _R2_BUCKET:
    try:
        import boto3
        _r2_client = boto3.client(
            's3',
            endpoint_url=f'https://{_R2_ACCOUNT_ID}.r2.cloudflarestorage.com',
            aws_access_key_id=_R2_ACCESS_KEY_ID,
            aws_secret_access_key=_R2_SECRET_ACCESS_KEY,
            region_name='auto',
        )
    except Exception:
        import logging as _log_r2
        _log_r2.warning('R2 client init failed — receipt upload disabled')

ALLOWED_RECEIPT_TYPES = {'application/pdf', 'image/jpeg', 'image/png', 'image/webp'}
MAX_RECEIPT_BYTES = 10 * 1024 * 1024  # 10 MB


def _r2_upload(file_obj, object_key: str, content_type: str = 'application/octet-stream') -> bool:
    if not _r2_client:
        return False
    _r2_client.upload_fileobj(
        file_obj,
        _R2_BUCKET,
        object_key,
        ExtraArgs={'ContentType': content_type},
    )
    return True


def _r2_delete(object_key: str):
    if _r2_client and object_key:
        try:
            _r2_client.delete_object(Bucket=_R2_BUCKET, Key=object_key)
        except Exception:
            pass


def _r2_presigned_url(object_key: str, expiry: int = 3600) -> str:
    if not _r2_client or not object_key:
        return ''
    return _r2_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': _R2_BUCKET, 'Key': object_key},
        ExpiresIn=expiry,
    )


# SEC-008: HTTP security headers
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


def _init_db():
    try:
        db.create_all()
    except Exception as e:
        app.logger.error(f'db.create_all() failed: {e}')
    # Column migration: add insurance_deduction if missing (idempotent)
    try:
        with db.engine.connect() as conn:
            from sqlalchemy import text
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN insurance_deduction INTEGER NOT NULL DEFAULT 0"
            ))
            conn.commit()
    except Exception:
        pass  # column already exists → safe to ignore
    # Column migration: add sort_order to materials if missing
    try:
        with db.engine.connect() as conn:
            from sqlalchemy import text
            conn.execute(text(
                "ALTER TABLE materials ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"
            ))
            conn.commit()
    except Exception:
        pass
    # Initialize sort_order for existing materials (sort_order=0 → use id)
    try:
        with db.engine.connect() as conn:
            from sqlalchemy import text
            conn.execute(text("UPDATE materials SET sort_order = id WHERE sort_order = 0"))
            conn.commit()
    except Exception:
        pass
    # Column migration: add retention_offset to users if missing
    try:
        with db.engine.connect() as conn:
            from sqlalchemy import text
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN retention_offset INTEGER NOT NULL DEFAULT 0"
            ))
            conn.commit()
    except Exception:
        pass
    # Column migration: add tax_exempt to users if missing
    try:
        with db.engine.connect() as conn:
            from sqlalchemy import text
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN tax_exempt BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            conn.commit()
    except Exception:
        pass
    # Column migration: add is_rejected to reports if missing
    try:
        with db.engine.connect() as conn:
            from sqlalchemy import text
            conn.execute(text(
                "ALTER TABLE reports ADD COLUMN is_rejected BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            conn.commit()
    except Exception:
        pass
    # Column migration: add bank_account to users if missing
    try:
        with db.engine.connect() as conn:
            from sqlalchemy import text
            conn.execute(text("ALTER TABLE users ADD COLUMN bank_account VARCHAR(14)"))
            conn.commit()
    except Exception:
        pass
    # Column migration: expand bank_account to VARCHAR(200) for Fernet encryption
    try:
        with db.engine.connect() as conn:
            from sqlalchemy import text
            conn.execute(text("ALTER TABLE users ALTER COLUMN bank_account TYPE VARCHAR(200)"))
            conn.commit()
    except Exception:
        pass
    # Column migration: add fixed_salary to users if missing
    try:
        with db.engine.connect() as conn:
            from sqlalchemy import text
            conn.execute(text("ALTER TABLE users ADD COLUMN fixed_salary INTEGER NOT NULL DEFAULT 0"))
            conn.commit()
    except Exception:
        pass
    # DB indexes (idempotent — CREATE INDEX IF NOT EXISTS)
    try:
        with db.engine.connect() as conn:
            from sqlalchemy import text as _text
            _idxs = [
                "CREATE INDEX IF NOT EXISTS ix_reports_user_date ON reports (user_id, report_date)",
                "CREATE INDEX IF NOT EXISTS ix_reports_date_confirmed ON reports (report_date, is_confirmed)",
                "CREATE INDEX IF NOT EXISTS ix_reports_user_confirmed ON reports (user_id, is_confirmed)",
                "CREATE INDEX IF NOT EXISTS ix_audit_logs_created_at ON audit_logs (created_at)",
                "CREATE INDEX IF NOT EXISTS ix_audit_logs_user_id ON audit_logs (user_id)",
                "CREATE INDEX IF NOT EXISTS ix_audit_logs_action_type ON audit_logs (action_type)",
                "CREATE INDEX IF NOT EXISTS ix_mat_req_user_id ON material_requests (user_id)",
                "CREATE INDEX IF NOT EXISTS ix_mat_req_status ON material_requests (status)",
            ]
            for _sql in _idxs:
                conn.execute(_text(_sql))
            conn.commit()
    except Exception:
        pass
    # Seed / correct default SystemConfig entries
    try:
        for _key, _default in [('retention_rate', '20'), ('tax_rate', '3')]:
            cfg = db.session.get(SystemConfig, _key)
            if not cfg:
                db.session.add(SystemConfig(key=_key, value=_default))
            elif _key == 'tax_rate' and cfg.value == '5':
                # 舊預設值 5% → 修正為 3%
                cfg.value = '3'
        # Seed default item prices into SystemConfig (idempotent)
        for _field, _ in REPORT_FIELDS:
            _pk = f'price_{_field}'
            if not db.session.get(SystemConfig, _pk):
                db.session.add(SystemConfig(key=_pk,
                                            value=str(DEFAULT_PRICES.get(_field, 0.0))))
        db.session.commit()
    except Exception:
        pass
    # Performance indexes (idempotent — IF NOT EXISTS)
    _indexes = [
        # 確認頁：待確認回報掃描（最關鍵）
        "CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(is_confirmed, is_rejected, report_date, id)",
        # 薪資/歷史：帳戶 + 日期範圍
        "CREATE INDEX IF NOT EXISTS idx_reports_user_date ON reports(user_id, report_date, is_confirmed)",
        # 薪資：日期範圍 + 已確認
        "CREATE INDEX IF NOT EXISTS idx_reports_date_conf ON reports(report_date, is_confirmed)",
        # 材料申請
        "CREATE INDEX IF NOT EXISTS idx_mat_req_status ON material_requests(status, created_at)",
        # 變動紀錄
        "CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id, created_at)",
        # 帳戶保留金費率批次載入
        "CREATE INDEX IF NOT EXISTS idx_urt_user ON user_retention_rates(user_id)",
        # 流水帳
        "CREATE INDEX IF NOT EXISTS ix_ledger_date ON ledger_entries(entry_date)",
        "CREATE INDEX IF NOT EXISTS ix_ledger_type ON ledger_entries(entry_type)",
    ]
    from sqlalchemy import text as _text
    for _sql in _indexes:
        try:
            with db.engine.connect() as conn:
                conn.execute(_text(_sql))
                conn.commit()
        except Exception:
            pass

with app.app_context():
    _init_db()


class SimplePagination:
    """Paginate a plain Python list (mirrors Flask-SQLAlchemy Pagination API)."""
    def __init__(self, items_all, page, per_page=20):
        self.total = len(items_all)
        self.per_page = per_page
        self.pages = max(1, (self.total + per_page - 1) // per_page)
        self.page = max(1, min(page, self.pages))
        start = (self.page - 1) * per_page
        self.items = items_all[start:start + per_page]
        self.has_prev = self.page > 1
        self.has_next = self.page < self.pages
        self.prev_num = self.page - 1 if self.has_prev else None
        self.next_num = self.page + 1 if self.has_next else None

    def iter_pages(self, left_edge=1, right_edge=1, left_current=2, right_current=2):
        last = 0
        for num in range(1, self.pages + 1):
            if (num <= left_edge
                    or (self.page - left_current - 1 < num < self.page + right_current)
                    or num > self.pages - right_edge):
                if last + 1 != num:
                    yield None
                yield num
                last = num


@app.template_filter('money')
def money_filter(value):
    """Format number with comma thousands separator; auto-detects decimal need."""
    try:
        v = float(value)
        if abs(v - round(v)) < 0.005:
            return f'{int(round(v)):,}'
        return f'{v:,.2f}'
    except (ValueError, TypeError):
        return str(value)


@app.template_filter('report_json')
def report_json_filter(r):
    import json
    data = {k: getattr(r, k, 0) for k, _ in REPORT_FIELDS}
    data['id'] = r.id
    data['report_date'] = str(r.report_date)
    return json.dumps(data, ensure_ascii=False)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = '請先登入'
login_manager.login_message_category = 'warning'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role != 'ADMIN':
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPORT_FIELDS = [
    ('direct_13',              '直總-13'),
    ('direct_20',              '直總-20'),
    ('direct_25',              '直總-25'),
    ('direct_40',              '直總-40'),
    ('indirect_13',            '間接-13'),
    ('indirect_20',            '間接-20'),
    ('indirect_25',            '間接-25'),
    ('indirect_40',            '間接-40'),
    ('original_change',        '原改'),
    ('direct_switch_valve',    '直總-換由令(含表)-13~25'),
    ('indirect_switch_valve',  '間接-換由令(含表)-13~25'),
    ('switch_valve_13_25',     '13~25換開關(含表)'),
    ('switch_valve_40',        '40換開關(含表)'),
    ('direct_fixed_13_25',     '直總-13~25固拆(含表)'),
    ('direct_fixed_40',        '直總-40固拆(含表)'),
    ('indirect_fixed_13_25',   '間接-13~25固拆(含表)'),
    ('indirect_fixed_40',      '間接-40固拆(含表)'),
    ('pipe_repair',            '管修(提高)'),
    ('mobilization',           '動員'),
    ('recheck',                '複查案/9年表'),
    ('soil_clearing',          '清積土'),
]

DEFAULT_PRICES = {
    'direct_13':            120.0,
    'direct_20':            120.0,
    'direct_25':            120.0,
    'direct_40':            170.0,
    'indirect_13':           75.0,
    'indirect_20':           75.0,
    'indirect_25':           75.0,
    'indirect_40':          125.0,
    'original_change':       45.0,
    'direct_switch_valve':  200.0,
    'indirect_switch_valve':150.0,
    'switch_valve_13_25':   320.0,
    'switch_valve_40':      450.0,
    'direct_fixed_13_25':   340.0,
    'direct_fixed_40':      500.0,
    'indirect_fixed_13_25': 230.0,
    'indirect_fixed_40':    450.0,
    'pipe_repair':          150.0,
    'mobilization':        1200.0,
    'recheck':               60.0,
    'soil_clearing':        100.0,
}

# 保留金：以下 8 個欄位每只抽固定費率（可依帳戶客製化）
RETENTION_FIELDS = [
    'direct_13', 'direct_20', 'direct_25', 'direct_40',
    'indirect_13', 'indirect_20', 'indirect_25', 'indirect_40',
]
RETENTION_FIELDS_LABELED = [(f, lbl) for f, lbl in REPORT_FIELDS if f in set(RETENTION_FIELDS)]
RETENTION_RATE = 20  # default fallback
RETENTION_CAP  = 60000  # 年度保留金上限 (NTD)


def get_retention_rate() -> float:
    cfg = db.session.get(SystemConfig, 'retention_rate')
    return float(cfg.value) if cfg else float(RETENTION_RATE)


def get_tax_rate() -> float:
    """未在公司保勞健者適用的稅務支出比率（%），預設 3"""
    cfg = db.session.get(SystemConfig, 'tax_rate')
    return float(cfg.value) if cfg else 3.0


_price_cache: dict = {}
_price_cache_ts: float = 0.0
_PRICE_CACHE_TTL = 300  # 5 分鐘


def get_item_prices() -> dict:
    """各工項單位計薪，優先讀取 SystemConfig（鍵：price_<field>），否則用 DEFAULT_PRICES。
    結果快取 5 分鐘，避免每次 request 重複查詢 DB。"""
    import time
    global _price_cache, _price_cache_ts
    if _price_cache and (time.monotonic() - _price_cache_ts) < _PRICE_CACHE_TTL:
        return _price_cache
    prices = {}
    for k, _ in REPORT_FIELDS:
        cfg = db.session.get(SystemConfig, f'price_{k}')
        prices[k] = float(cfg.value) if cfg else DEFAULT_PRICES.get(k, 0.0)
    _price_cache    = prices
    _price_cache_ts = time.monotonic()
    return _price_cache


def _invalidate_price_cache():
    global _price_cache
    _price_cache = {}


def calc_retention_from_totals(totals: dict) -> float:
    """全域費率版：RETENTION_FIELDS 合計只數 × 全域費率（向後相容，勿刪）"""
    rate = get_retention_rate()
    return sum(totals.get(f, 0) for f in RETENTION_FIELDS) * rate


def get_user_all_retention_rates(user_id: int) -> dict:
    """回傳 {field: rate}，未自訂的欄位使用全域費率。"""
    global_rate = get_retention_rate()
    result = {f: global_rate for f in RETENTION_FIELDS}
    for cr in UserRetentionRate.query.filter_by(user_id=user_id).all():
        if cr.field in result:
            result[cr.field] = float(cr.rate)
    return result


def get_users_all_retention_rates(user_ids) -> dict:
    """批次載入多帳戶費率，回傳 {uid: {field: rate}}，減少 DB 查詢次數。"""
    ids = list(user_ids)
    global_rate = get_retention_rate()
    result = {uid: {f: global_rate for f in RETENTION_FIELDS} for uid in ids}
    if ids:
        for cr in UserRetentionRate.query.filter(
            UserRetentionRate.user_id.in_(ids)
        ).all():
            if cr.user_id in result and cr.field in result[cr.user_id]:
                result[cr.user_id][cr.field] = float(cr.rate)
    return result


def get_ytd_retention(user_id: int) -> float:
    """今年度累積保留金（最低 0，最高 RETENTION_CAP）"""
    year_start = date(date.today().year, 1, 1)
    reports = Report.query.filter(
        Report.user_id == user_id,
        Report.is_confirmed == True,
        Report.report_date >= year_start,
        Report.report_date <= date.today()
    ).all()
    totals = {f: sum(getattr(r, f, 0) for r in reports) for f in RETENTION_FIELDS}
    user_rates = get_user_all_retention_rates(user_id)
    calculated = sum(totals.get(f, 0) * user_rates[f] for f in RETENTION_FIELDS)
    u = db.session.get(User, user_id)
    offset = u.retention_offset if u else 0
    return min(float(RETENTION_CAP), max(0.0, calculated + offset))


def _calc_ytd_retention_raw(user_id: int) -> float:
    """純計算值（不含偏移），供 set-retention 路由使用"""
    year_start = date(date.today().year, 1, 1)
    reports = Report.query.filter(
        Report.user_id == user_id,
        Report.is_confirmed == True,
        Report.report_date >= year_start,
        Report.report_date <= date.today()
    ).all()
    totals = {f: sum(getattr(r, f, 0) for r in reports) for f in RETENTION_FIELDS}
    user_rates = get_user_all_retention_rates(user_id)
    return sum(totals.get(f, 0) * user_rates[f] for f in RETENTION_FIELDS)


CASH_DENOMINATIONS = [1000, 500, 100, 50, 10, 5, 1]


def calculate_cash_bills(amount: float) -> dict:
    """以最少張/枚數組合現金面額，回傳 {面額: 張數} dict（只含非零項）"""
    remaining = round(amount)
    result = {}
    for d in CASH_DENOMINATIONS:
        count = remaining // d
        if count:
            result[d] = count
            remaining -= count * d
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def add_audit(user_id, action_type, description):
    log = AuditLog(user_id=user_id, action_type=action_type, description=description)
    db.session.add(log)


def parse_report_values(form):
    vals = {}
    for key, _ in REPORT_FIELDS:
        try:
            vals[key] = max(0, int(form.get(key, 0)))
        except (ValueError, TypeError):
            vals[key] = 0
    return vals


def report_diff(old_report, new_vals):
    changes = []
    for key, label in REPORT_FIELDS:
        ov = getattr(old_report, key, 0)
        nv = new_vals.get(key, 0)
        if ov != nv:
            changes.append(f'{label}: {ov} → {nv}')
    return '、'.join(changes) if changes else '無變更'


def get_user_display(users_dict, uid):
    u = users_dict.get(uid)
    return u.display_name if u else '(已刪除)'


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('confirmation') if current_user.role == 'ADMIN' else url_for('report'))
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    active_users = User.query.filter_by(is_active=True).order_by(User.display_name).all()
    if request.method == 'POST':
        user_id = request.form.get('user_id', '').strip()
        password = request.form.get('password', '')
        user = db.session.get(User, int(user_id)) if user_id.isdigit() else None
        if user and user.is_active and check_password_hash(user.password_hash, password):
            login_user(user, remember=True)
            session.permanent = True  # 確保 PERMANENT_SESSION_LIFETIME 生效
            return redirect(url_for('confirmation') if user.role == 'ADMIN' else url_for('report'))
        flash('密碼錯誤，請重試', 'danger')
    return render_template('login.html', active_users=active_users)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('已成功登出', 'info')
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# Page 1: Daily Report
# ---------------------------------------------------------------------------

@app.route('/report', methods=['GET', 'POST'])
@login_required
def report():
    if request.method == 'POST':
        try:
            report_date = date.fromisoformat(request.form.get('date', str(date.today())))
        except ValueError:
            report_date = date.today()

        vals = parse_report_values(request.form)
        r = Report(user_id=current_user.id, report_date=report_date, **vals)
        db.session.add(r)

        nonzero = ', '.join(f'{label}:{vals[k]}' for k, label in REPORT_FIELDS if vals[k] > 0)
        add_audit(current_user.id, 'REPORT_CREATE',
                  f'新增 {report_date} 的回報｜{nonzero or "全部為0"}')
        db.session.commit()
        flash('回報已成功送出', 'success')
        return redirect(url_for('report'))

    return render_template('report.html', report_fields=REPORT_FIELDS, today=str(date.today()))


# ---------------------------------------------------------------------------
# Page 2: History
# ---------------------------------------------------------------------------

@app.route('/history')
@login_required
def history():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    selected_user_id = request.args.get('user_id', '')

    q = Report.query
    if current_user.role == 'USER':
        q = q.filter_by(user_id=current_user.id)
    elif selected_user_id:
        q = q.filter_by(user_id=int(selected_user_id))

    if start_date:
        q = q.filter(Report.report_date >= date.fromisoformat(start_date))
    if end_date:
        q = q.filter(Report.report_date <= date.fromisoformat(end_date))

    page = request.args.get('page', 1, type=int)
    pagination = (q.order_by(Report.report_date.desc(), Report.created_at.desc())
                  .paginate(page=page, per_page=20, error_out=False))
    _all_users_list = User.query.all()
    users_dict = {u.id: u for u in _all_users_list}
    all_users = _all_users_list if current_user.role == 'ADMIN' else []
    url_args = {k: v for k, v in request.args.items() if k != 'page'}

    return render_template('history.html',
                           reports=pagination.items,
                           pagination=pagination,
                           users_dict=users_dict,
                           all_users=all_users,
                           report_fields=REPORT_FIELDS,
                           start_date=start_date,
                           end_date=end_date,
                           selected_user_id=selected_user_id,
                           url_args=url_args)


@app.route('/history/<int:report_id>/edit', methods=['POST'])
@login_required
def history_edit(report_id):
    r = db.session.get(Report, report_id)
    if not r:
        abort(404)
    if current_user.role != 'ADMIN' and r.user_id != current_user.id:
        abort(403)

    if r.is_confirmed and current_user.role != 'ADMIN':
        flash('已確認的回報無法修改', 'danger')
        return redirect(url_for('history'))

    new_vals = parse_report_values(request.form)
    diff = report_diff(r, new_vals)
    was_confirmed = r.is_confirmed

    for key, _ in REPORT_FIELDS:
        setattr(r, key, new_vals[key])
    r.updated_at = datetime.utcnow()

    if was_confirmed and current_user.role == 'ADMIN':
        r.is_confirmed = False
        r.confirmed_by = None
        r.confirmed_at = None
        add_audit(current_user.id, 'REPORT_UNCONFIRM',
                  f'修改回報 #{r.id} ({r.report_date}) 導致確認狀態重置為尚未確認')
    if r.is_rejected:
        r.is_rejected = False

    add_audit(current_user.id, 'REPORT_UPDATE',
              f'修改回報 #{r.id} ({r.report_date})｜{diff}')
    db.session.commit()
    flash('回報已更新', 'success')
    return redirect(url_for('history'))


@app.route('/history/<int:report_id>/delete', methods=['POST'])
@login_required
def history_delete(report_id):
    r = db.session.get(Report, report_id)
    if not r:
        abort(404)
    if current_user.role != 'ADMIN' and r.user_id != current_user.id:
        abort(403)
    if r.is_confirmed and current_user.role != 'ADMIN':
        flash('已確認的回報只能由管理員刪除', 'danger')
        return redirect(url_for('history'))

    users_dict = {u.id: u for u in User.query.all()}
    uname = get_user_display(users_dict, r.user_id)
    add_audit(current_user.id, 'REPORT_DELETE',
              f'刪除回報 #{r.id} ({uname} / {r.report_date})')
    db.session.delete(r)
    db.session.commit()
    flash('回報已刪除', 'success')
    return redirect(url_for('history'))


# ---------------------------------------------------------------------------
# Page 3: Settings
# ---------------------------------------------------------------------------

@app.route('/settings')
@login_required
def settings():
    _all_users_raw = User.query.order_by(User.id).all() if current_user.role == 'ADMIN' else []
    all_users = sorted(_all_users_raw, key=lambda u: (0 if u.role == 'ADMIN' else 1, u.id))
    uid_list = [u.id for u in all_users]

    # ── 3 queries total (was N×2 + 1) ────────────────────────────────
    global_rate = int(get_retention_rate())

    # 1 query: 當年全部已確認回報（供 YTD 保留金計算）
    ytd_by_user: dict = {}
    user_ret_rates: dict = {}
    if uid_list:
        year_start = date(date.today().year, 1, 1)
        ytd_reports = (Report.query
                       .filter(Report.is_confirmed == True,
                               Report.report_date >= year_start,
                               Report.report_date <= date.today())
                       .all())
        ytd_totals: dict = {}
        for r in ytd_reports:
            uid = r.user_id
            if uid not in ytd_totals:
                ytd_totals[uid] = {f: 0 for f in RETENTION_FIELDS}
            for f in RETENTION_FIELDS:
                ytd_totals[uid][f] += getattr(r, f, 0)

        # 1 query: 所有帳戶客製費率
        all_custom = (UserRetentionRate.query
                      .filter(UserRetentionRate.user_id.in_(uid_list)).all())
        custom_map: dict = {}
        for cr in all_custom:
            custom_map.setdefault(cr.user_id, {})[cr.field] = cr.rate

        for u in all_users:
            custom = custom_map.get(u.id, {})
            user_rates = {f: float(custom.get(f, global_rate)) for f in RETENTION_FIELDS}
            user_ret_rates[u.id] = {
                'rates': {f: int(v) for f, v in user_rates.items()},
                'is_custom': bool(custom)
            }
            totals = ytd_totals.get(u.id, {})
            calculated = sum(totals.get(f, 0) * user_rates[f] for f in RETENTION_FIELDS)
            ytd_by_user[u.id] = min(float(RETENTION_CAP),
                                    max(0.0, calculated + u.retention_offset))
    # ─────────────────────────────────────────────────────────────────

    # ── USER：計算自己的保留金 ──────────────────────────────────────────────
    my_ytd = 0.0
    my_ret_rates = {}
    if current_user.role != 'ADMIN':
        year_start = date(date.today().year, 1, 1)
        my_reports = (Report.query
                      .filter(Report.user_id == current_user.id,
                              Report.is_confirmed == True,
                              Report.report_date >= year_start,
                              Report.report_date <= date.today())
                      .all())
        my_totals = {f: 0 for f in RETENTION_FIELDS}
        for r in my_reports:
            for f in RETENTION_FIELDS:
                my_totals[f] += getattr(r, f, 0)
        my_rates = get_user_all_retention_rates(current_user.id)
        my_ret_rates = my_rates
        calculated = sum(my_totals.get(f, 0) * float(my_rates.get(f, global_rate))
                         for f in RETENTION_FIELDS)
        my_ytd = min(float(RETENTION_CAP),
                     max(0.0, calculated + current_user.retention_offset))

    bank_accounts = {u.id: decrypt_bank(u.bank_account or '') for u in all_users}
    bank_accounts[current_user.id] = decrypt_bank(current_user.bank_account or '')

    return render_template('settings.html', all_users=all_users,
                           retention_rate=global_rate,
                           tax_rate=get_tax_rate(),
                           ytd_by_user=ytd_by_user,
                           user_ret_rates=user_ret_rates,
                           retention_fields_labeled=RETENTION_FIELDS_LABELED,
                           report_fields=REPORT_FIELDS,
                           item_prices=get_item_prices(),
                           my_ytd=my_ytd,
                           my_ret_rates=my_ret_rates,
                           bank_accounts=bank_accounts)


@app.route('/settings/password', methods=['POST'])
@login_required
def settings_password():
    old_pw = request.form.get('old_password', '')
    new_pw = request.form.get('new_password', '')
    confirm_pw = request.form.get('confirm_password', '')

    if not check_password_hash(current_user.password_hash, old_pw):
        flash('舊密碼錯誤', 'danger')
    elif new_pw != confirm_pw:
        flash('新密碼與確認密碼不符', 'danger')
    elif len(new_pw) < 4:
        flash('新密碼至少需要 4 個字元', 'danger')
    else:
        current_user.password_hash = generate_password_hash(new_pw)
        current_user.updated_at = datetime.utcnow()
        add_audit(current_user.id, 'PASSWORD_CHANGE',
                  f'{current_user.display_name} 修改了自己的密碼')
        db.session.commit()
        flash('密碼已更新', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/users/create', methods=['POST'])
@admin_required
def settings_create_user():
    display_name = request.form.get('display_name', '').strip()
    password = request.form.get('password', '')
    role = request.form.get('role', 'USER')

    confirm_password = request.form.get('confirm_password', '')
    if not display_name or not password:
        flash('名稱和密碼不能為空', 'danger')
    elif role not in ('ADMIN', 'USER'):
        flash('無效的角色', 'danger')
    elif len(password) < 4:
        flash('密碼至少需要 4 個字元', 'danger')
    elif password != confirm_password:
        flash('兩次輸入的密碼不相符', 'danger')
    elif User.query.filter_by(display_name=display_name).first():
        flash(f'名稱「{display_name}」已存在', 'danger')
    else:
        payment_method = request.form.get('payment_method', 'CASH')
        if payment_method not in ('CASH', 'TRANSFER'):
            payment_method = 'CASH'
        bank_account_raw = request.form.get('bank_account', '').strip().replace('-', '').replace(' ', '')
        ba_ok = True
        if payment_method == 'TRANSFER':
            if not bank_account_raw:
                flash('選擇轉帳發薪時必須填入銀行帳號', 'danger')
                ba_ok = False
            elif not (bank_account_raw.isdigit() and len(bank_account_raw) == 14):
                flash('銀行帳號格式錯誤（需為 14 位數字：3碼分行代碼 + 11碼帳號主碼）', 'danger')
                ba_ok = False
        if ba_ok:
            u = User(display_name=display_name,
                     password_hash=generate_password_hash(password),
                     role=role, is_active=True,
                     payment_method=payment_method,
                     bank_account=encrypt_bank(bank_account_raw) if bank_account_raw else None)
            db.session.add(u)
            add_audit(current_user.id, 'ACCOUNT_CREATE',
                      f'建立帳戶「{display_name}」（角色：{role}）')
            db.session.commit()
            flash(f'帳戶「{display_name}」已建立', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/users/<int:user_id>/display-name', methods=['POST'])
@admin_required
def settings_update_display_name(user_id):
    target = db.session.get(User, user_id)
    if not target:
        abort(404)
    new_name = request.form.get('display_name', '').strip()
    if not new_name:
        flash('名稱不能為空', 'danger')
    elif User.query.filter(User.display_name == new_name, User.id != user_id).first():
        flash(f'名稱「{new_name}」已被其他帳戶使用', 'danger')
    else:
        old_name = target.display_name
        target.display_name = new_name
        target.updated_at = datetime.utcnow()
        add_audit(current_user.id, 'ACCOUNT_UPDATE',
                  f'更新帳戶名稱：{old_name} → {new_name}')
        db.session.commit()
        flash(f'名稱已更新為「{new_name}」', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/users/<int:user_id>/payment-method', methods=['POST'])
@admin_required
def settings_payment_method(user_id):
    target = db.session.get(User, user_id)
    if not target:
        abort(404)
    method = request.form.get('payment_method', 'CASH')
    if method not in ('CASH', 'TRANSFER'):
        method = 'CASH'
    if method == 'TRANSFER' and not target.bank_account:
        flash(f'「{target.display_name}」尚未設定銀行帳號，無法切換為轉帳，請先設定銀行帳號', 'danger')
        return redirect(url_for('settings'))
    old = target.payment_method
    target.payment_method = method
    target.updated_at = datetime.utcnow()
    label = '領現' if method == 'CASH' else '轉帳'
    add_audit(current_user.id, 'ACCOUNT_UPDATE',
              f'更新「{target.display_name}」發薪方式：{old} → {method}')
    db.session.commit()
    flash(f'「{target.display_name}」發薪方式已更新為「{label}」', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/users/<int:user_id>/bank-account', methods=['POST'])
@admin_required
def settings_bank_account(user_id):
    target = db.session.get(User, user_id)
    if not target:
        abort(404)
    acct = request.form.get('bank_account', '').strip().replace('-', '').replace(' ', '')
    if acct and not (acct.isdigit() and len(acct) == 14):
        flash('銀行帳號格式錯誤（需為 14 位數字：3碼分行代碼 + 11碼帳號主碼）', 'danger')
        return redirect(url_for('settings'))
    target.bank_account = encrypt_bank(acct) if acct else None
    target.updated_at = datetime.utcnow()
    if not target.bank_account and target.payment_method == 'TRANSFER':
        target.payment_method = 'CASH'
        add_audit(current_user.id, 'ACCOUNT_UPDATE',
                  f'清除「{target.display_name}」銀行帳號，發薪方式自動改為領現')
        flash(f'「{target.display_name}」銀行帳號已清除，發薪方式已自動改為領現', 'warning')
    else:
        add_audit(current_user.id, 'ACCOUNT_UPDATE',
                  f'更新「{target.display_name}」銀行帳號')
        flash(f'「{target.display_name}」銀行帳號已更新', 'success')
    db.session.commit()
    return redirect(url_for('settings'))


@app.route('/settings/users/<int:user_id>/fixed-salary', methods=['POST'])
@admin_required
def settings_fixed_salary(user_id):
    target = db.session.get(User, user_id)
    if not target:
        abort(404)
    try:
        amount = max(0, int(request.form.get('fixed_salary', 0)))
    except (ValueError, TypeError):
        flash('請輸入有效的整數', 'danger')
        return redirect(url_for('settings'))
    old = target.fixed_salary
    target.fixed_salary = amount
    target.updated_at = datetime.utcnow()
    add_audit(current_user.id, 'ACCOUNT_UPDATE',
              f'更新「{target.display_name}」固定薪資：{old} → {amount} NTD')
    db.session.commit()
    flash(f'「{target.display_name}」固定薪資已更新為 {amount:,} NTD', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/users/<int:user_id>/insurance', methods=['POST'])
@admin_required
def settings_insurance(user_id):
    target = db.session.get(User, user_id)
    if not target:
        abort(404)
    ins_type = request.form.get('ins_type', 'uninsured_taxed')
    if ins_type == 'insured':
        try:
            amount = max(1, int(request.form.get('insurance_deduction', 1)))
        except (ValueError, TypeError):
            flash('請輸入有效的整數', 'danger')
            return redirect(url_for('settings'))
        target.insurance_deduction = amount
        target.tax_exempt = False
        add_audit(current_user.id, 'ACCOUNT_UPDATE',
                  f'更新「{target.display_name}」投保狀態：公司投保，扣除額 {amount} NTD')
        flash(f'「{target.display_name}」已設為公司投保，每期扣除 {amount:,} NTD', 'success')
    elif ins_type == 'uninsured_exempt':
        target.insurance_deduction = 0
        target.tax_exempt = True
        add_audit(current_user.id, 'ACCOUNT_UPDATE',
                  f'更新「{target.display_name}」投保狀態：未投保，免稅')
        flash(f'「{target.display_name}」已設為未投保（免稅）', 'success')
    else:
        target.insurance_deduction = 0
        target.tax_exempt = False
        add_audit(current_user.id, 'ACCOUNT_UPDATE',
                  f'更新「{target.display_name}」投保狀態：未投保，扣稅務支出')
        flash(f'「{target.display_name}」已設為未投保（扣稅務支出）', 'success')
    target.updated_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for('settings'))


@app.route('/settings/tax-rate', methods=['POST'])
@admin_required
def settings_tax_rate():
    try:
        rate = max(0.0, float(request.form.get('rate', 5)))
    except (ValueError, TypeError):
        flash('請輸入有效的數值', 'danger')
        return redirect(url_for('settings'))
    cfg = db.session.get(SystemConfig, 'tax_rate')
    if cfg:
        cfg.value = str(rate)
    else:
        db.session.add(SystemConfig(key='tax_rate', value=str(rate)))
    add_audit(current_user.id, 'SYSTEM_CONFIG', f'更新稅務支出費率：{rate}%')
    db.session.commit()
    flash(f'稅務支出費率已更新為 {rate}%', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/retention-rate', methods=['POST'])
@admin_required
def settings_retention_rate():
    try:
        rate = max(0, int(request.form.get('rate', 20)))
    except (ValueError, TypeError):
        flash('請輸入有效的整數', 'danger')
        return redirect(url_for('settings'))
    cfg = db.session.get(SystemConfig, 'retention_rate')
    if cfg:
        cfg.value = str(rate)
    else:
        db.session.add(SystemConfig(key='retention_rate', value=str(rate)))
    add_audit(current_user.id, 'SYSTEM_CONFIG',
              f'更新保留金費率：{rate} NTD/只')
    db.session.commit()
    flash(f'保留金費率已更新為 {rate} NTD/只', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/item-prices', methods=['POST'])
@admin_required
def settings_item_prices():
    updated = 0
    for k, _ in REPORT_FIELDS:
        val_str = request.form.get(f'price_{k}', '').strip()
        if val_str == '':
            continue
        try:
            val = max(0.0, float(val_str))
        except ValueError:
            flash('無效數值，已略過部分欄位', 'warning')
            continue
        cfg = db.session.get(SystemConfig, f'price_{k}')
        if cfg:
            cfg.value = str(val)
        else:
            db.session.add(SystemConfig(key=f'price_{k}', value=str(val)))
        updated += 1
    if updated:
        add_audit(current_user.id, 'SYSTEM_CONFIG',
                  f'更新各工項單位計薪（{updated} 個工項）')
        db.session.commit()
        _invalidate_price_cache()
        flash('各工項單位計薪已儲存', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/users/<int:user_id>/set-retention', methods=['POST'])
@admin_required
def settings_set_retention(user_id):
    u = db.session.get(User, user_id)
    if not u:
        abort(404)
    action = request.form.get('action', 'set')
    try:
        target = float(request.form.get('amount', 0))
    except (ValueError, TypeError):
        target = 0.0
    calculated = _calc_ytd_retention_raw(user_id)
    if action == 'reset':
        u.retention_offset = -int(calculated)
        add_audit(current_user.id, 'RETENTION_RESET',
                  f'重置「{u.display_name}」今年度累積保留金為 0（計算值 {calculated:.0f}，偏移 {u.retention_offset}）')
        flash(f'「{u.display_name}」累積保留金已重置為 0', 'success')
    else:
        u.retention_offset = int(target - calculated)
        add_audit(current_user.id, 'RETENTION_SET',
                  f'設定「{u.display_name}」今年度累積保留金為 {int(target)}（計算值 {calculated:.0f}，偏移 {u.retention_offset}）')
        flash(f'「{u.display_name}」累積保留金已設定為 {int(target)} NTD', 'success')
    db.session.commit()
    return redirect(url_for('settings'))


@app.route('/settings/users/<int:user_id>/retention-rates', methods=['POST'])
@admin_required
def settings_retention_rates(user_id):
    u = db.session.get(User, user_id)
    if not u:
        abort(404)
    action = request.form.get('action', 'set')
    if action == 'reset':
        UserRetentionRate.query.filter_by(user_id=user_id).delete()
        add_audit(current_user.id, 'ACCOUNT_UPDATE',
                  f'重置「{u.display_name}」保留金費率為全域設定')
        db.session.commit()
        flash(f'「{u.display_name}」保留金費率已重置為全域設定', 'success')
    else:
        for field in RETENTION_FIELDS:
            try:
                rate = max(0, int(request.form.get(f'rate_{field}', 0)))
            except (ValueError, TypeError):
                rate = 0
            existing = UserRetentionRate.query.filter_by(user_id=user_id, field=field).first()
            if existing:
                existing.rate = rate
            else:
                db.session.add(UserRetentionRate(user_id=user_id, field=field, rate=rate))
        add_audit(current_user.id, 'ACCOUNT_UPDATE',
                  f'更新「{u.display_name}」各工項保留金客製費率')
        db.session.commit()
        flash(f'「{u.display_name}」保留金費率已更新', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def settings_delete_user(user_id):
    if user_id == current_user.id:
        flash('無法刪除自己的帳戶', 'danger')
        return redirect(url_for('settings'))

    target = db.session.get(User, user_id)
    if not target:
        abort(404)

    mode = request.form.get('delete_mode', 'keep')
    dname = target.display_name

    if mode == 'cascade':
        # Nullify FK back-references (other users' records pointing to this user)
        Report.query.filter(Report.confirmed_by == user_id).update(
            {'confirmed_by': None}, synchronize_session=False)
        MaterialRequest.query.filter(MaterialRequest.reviewed_by == user_id).update(
            {'reviewed_by': None}, synchronize_session=False)
        # Delete all records owned by this user
        UserRetentionRate.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        AuditLog.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        Report.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        MaterialRequest.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        add_audit(current_user.id, 'ACCOUNT_DELETE',
                  f'刪除帳戶「{dname}」並連帶刪除所有回報與材料申請紀錄')
        db.session.delete(target)
    else:
        target.is_active = False
        target.updated_at = datetime.utcnow()
        add_audit(current_user.id, 'ACCOUNT_DEACTIVATE',
                  f'停用帳戶「{dname}」（保留歷史資料）')

    db.session.commit()
    flash(f'帳戶「{dname}」已處理完成', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/users/<int:user_id>/reactivate', methods=['POST'])
@admin_required
def settings_reactivate_user(user_id):
    target = db.session.get(User, user_id)
    if not target:
        abort(404)
    if target.is_active:
        flash('該帳戶目前為啟用狀態', 'warning')
        return redirect(url_for('settings'))
    target.is_active = True
    target.updated_at = datetime.utcnow()
    add_audit(current_user.id, 'ACCOUNT_REACTIVATE',
              f'重新啟用帳戶「{target.display_name}」')
    db.session.commit()
    flash(f'帳戶「{target.display_name}」已重新啟用', 'success')
    return redirect(url_for('settings'))



@app.route('/settings/users/<int:user_id>/password', methods=['POST'])
@admin_required
def settings_reset_password(user_id):
    target = db.session.get(User, user_id)
    if not target:
        abort(404)
    new_pw = request.form.get('new_password', '')
    confirm_pw = request.form.get('confirm_password', '')
    if len(new_pw) < 4:
        flash('密碼至少需要 4 個字元', 'danger')
    elif new_pw != confirm_pw:
        flash('兩次輸入的密碼不相符', 'danger')
    else:
        target.password_hash = generate_password_hash(new_pw)
        target.updated_at = datetime.utcnow()
        add_audit(current_user.id, 'PASSWORD_CHANGE',
                  f'{current_user.display_name} 重設了「{target.display_name}」的密碼')
        db.session.commit()
        flash(f'「{target.display_name}」的密碼已重設', 'success')
    return redirect(url_for('settings'))


# ---------------------------------------------------------------------------
# Page 4: Materials
# ---------------------------------------------------------------------------

@app.route('/materials')
@login_required
def materials():
    all_materials = Material.query.order_by(Material.sort_order, Material.id).all()
    users_dict = {u.id: u for u in User.query.all()}

    my_requests = None
    if current_user.role == 'USER':
        my_requests = (MaterialRequest.query
                       .filter_by(user_id=current_user.id)
                       .order_by(MaterialRequest.created_at.desc()).all())

    return render_template('materials.html',
                           all_materials=all_materials,
                           my_requests=my_requests,
                           users_dict=users_dict)


@app.route('/materials/request', methods=['POST'])
@login_required
def materials_request():
    if current_user.role == 'ADMIN':
        abort(403)
    material_id = int(request.form.get('material_id', 0))
    try:
        qty = int(request.form.get('quantity', 0))
    except (ValueError, TypeError):
        qty = 0

    if qty <= 0:
        flash('申請數量必須大於 0', 'danger')
        return redirect(url_for('materials'))

    m = db.session.get(Material, material_id)
    if not m:
        abort(404)

    req = MaterialRequest(user_id=current_user.id, material_id=material_id,
                          requested_quantity=qty, status='PENDING')
    db.session.add(req)
    add_audit(current_user.id, 'MATERIAL_REQUEST',
              f'申請領取「{m.name}」{qty}{m.unit}')
    db.session.commit()
    flash('申請已送出，等待管理員審核', 'success')
    return redirect(url_for('materials'))


@app.route('/materials/requests/<int:req_id>/cancel', methods=['POST'])
@login_required
def materials_cancel_request(req_id):
    req = db.session.get(MaterialRequest, req_id)
    if not req or req.user_id != current_user.id or req.status != 'PENDING':
        flash('無法取消此申請', 'danger')
        return redirect(url_for('materials'))
    m = db.session.get(Material, req.material_id)
    mat_name = m.name if m else '(已刪除)'
    add_audit(current_user.id, 'MATERIAL_CANCEL',
              f'取消申請領取「{mat_name}」{req.requested_quantity}')
    db.session.delete(req)
    db.session.commit()
    flash('申請已取消', 'success')
    return redirect(url_for('materials'))


@app.route('/materials/add', methods=['POST'])
@admin_required
def materials_add():
    name = request.form.get('name', '').strip()
    unit = request.form.get('unit', '').strip()
    try:
        qty = max(0, int(request.form.get('quantity', 0)))
    except (ValueError, TypeError):
        qty = 0

    if not name or not unit:
        flash('材料名稱和單位不能為空', 'danger')
    else:
        max_order = db.session.query(db.func.max(Material.sort_order)).scalar() or 0
        m = Material(name=name, unit=unit, remaining_quantity=qty, sort_order=max_order + 1)
        db.session.add(m)
        add_audit(current_user.id, 'MATERIAL_ADD',
                  f'新增材料「{name}」（{unit}），初始數量：{qty}')
        db.session.commit()
        flash(f'材料「{name}」已新增', 'success')
    return redirect(url_for('materials'))


@app.route('/materials/<int:material_id>/update', methods=['POST'])
@admin_required
def materials_update(material_id):
    m = db.session.get(Material, material_id)
    if not m:
        abort(404)
    try:
        new_qty = max(0, int(request.form.get('quantity', 0)))
    except (ValueError, TypeError):
        new_qty = 0
    old_qty = m.remaining_quantity
    m.remaining_quantity = new_qty
    m.updated_at = datetime.utcnow()
    add_audit(current_user.id, 'MATERIAL_UPDATE',
              f'調整「{m.name}」數量：{old_qty}{m.unit} → {new_qty}{m.unit}')
    db.session.commit()
    flash(f'「{m.name}」數量已更新', 'success')
    return redirect(url_for('materials'))


@app.route('/materials/<int:material_id>/delete', methods=['POST'])
@admin_required
def materials_delete(material_id):
    m = db.session.get(Material, material_id)
    if not m:
        abort(404)
    name = m.name
    MaterialRequest.query.filter_by(material_id=material_id).delete()
    db.session.delete(m)
    add_audit(current_user.id, 'MATERIAL_DELETE', f'刪除材料「{name}」及其所有申請紀錄')
    db.session.commit()
    flash(f'材料「{name}」已刪除', 'success')
    return redirect(url_for('materials'))


@app.route('/materials/<int:material_id>/move-up', methods=['POST'])
@admin_required
def materials_move_up(material_id):
    m = db.session.get(Material, material_id)
    if not m:
        abort(404)
    prev = (Material.query.filter(Material.sort_order < m.sort_order)
            .order_by(Material.sort_order.desc()).first())
    if prev:
        m.sort_order, prev.sort_order = prev.sort_order, m.sort_order
        db.session.commit()
    return redirect(url_for('materials'))


@app.route('/materials/<int:material_id>/move-down', methods=['POST'])
@admin_required
def materials_move_down(material_id):
    m = db.session.get(Material, material_id)
    if not m:
        abort(404)
    nxt = (Material.query.filter(Material.sort_order > m.sort_order)
           .order_by(Material.sort_order.asc()).first())
    if nxt:
        m.sort_order, nxt.sort_order = nxt.sort_order, m.sort_order
        db.session.commit()
    return redirect(url_for('materials'))


# ---------------------------------------------------------------------------
# Page 5: Summary (ADMIN)
# ---------------------------------------------------------------------------

@app.route('/summary')
@admin_required
def summary():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    selected_user_id = request.args.get('user_id', '')
    confirm_filter = request.args.get('confirm_filter', 'all')
    selected_fields = request.args.getlist('fields') or [k for k, _ in REPORT_FIELDS]

    all_users = User.query.order_by(User.display_name).all()
    results = None

    if start_date and end_date:
        q = Report.query.filter(
            Report.report_date >= date.fromisoformat(start_date),
            Report.report_date <= date.fromisoformat(end_date)
        )
        if selected_user_id:
            q = q.filter_by(user_id=int(selected_user_id))
        if confirm_filter == 'confirmed':
            q = q.filter_by(is_confirmed=True)
        elif confirm_filter == 'unconfirmed':
            q = q.filter_by(is_confirmed=False)

        reports = q.all()
        users_dict = {u.id: u for u in all_users}

        user_totals = {}
        for r in reports:
            uid = r.user_id
            if uid not in user_totals:
                uname = users_dict[uid].display_name if uid in users_dict else '(已刪除)'
                user_totals[uid] = {'username': uname,
                                    'totals': {k: 0 for k, _ in REPORT_FIELDS},
                                    'count': 0}
            for k, _ in REPORT_FIELDS:
                user_totals[uid]['totals'][k] += getattr(r, k, 0)
            user_totals[uid]['count'] += 1

        grand = {k: sum(d['totals'][k] for d in user_totals.values()) for k, _ in REPORT_FIELDS}
        page = request.args.get('page', 1, type=int)
        summary_pagination = SimplePagination(list(user_totals.items()), page, 20)
        results = {'user_totals': dict(summary_pagination.items),
                   'grand_total': grand,
                   'total_reports': len(reports)}
    else:
        summary_pagination = None

    url_args = {k: v for k, v in request.args.items() if k != 'page'}
    return render_template('summary.html',
                           results=results,
                           summary_pagination=summary_pagination,
                           all_users=all_users,
                           report_fields=REPORT_FIELDS,
                           selected_fields=selected_fields,
                           start_date=start_date,
                           end_date=end_date,
                           selected_user_id=selected_user_id,
                           confirm_filter=confirm_filter,
                           url_args=url_args)


# ---------------------------------------------------------------------------
# Page 6: Confirmation (ADMIN)
# ---------------------------------------------------------------------------

@app.route('/confirmation')
@admin_required
def confirmation():
    page = request.args.get('page', 1, type=int)

    # 日期篩選：預設最近 30 天
    default_start = (date.today() - timedelta(days=30)).isoformat()
    default_end   = date.today().isoformat()
    filter_start  = request.args.get('start_date', default_start)
    filter_end    = request.args.get('end_date',   default_end)
    try:
        sd = date.fromisoformat(filter_start)
        ed = date.fromisoformat(filter_end)
    except ValueError:
        sd, ed        = date.today() - timedelta(days=30), date.today()
        filter_start  = sd.isoformat()
        filter_end    = ed.isoformat()

    pending_pagination = (Report.query
                          .filter(Report.is_confirmed == False,
                                  Report.is_rejected  == False,
                                  Report.report_date  >= sd,
                                  Report.report_date  <= ed)
                          .order_by(Report.report_date.asc(), Report.id.asc())
                          .paginate(page=page, per_page=20, error_out=False))
    mat_page = request.args.get('mat_page', 1, type=int)
    mat_pagination = (MaterialRequest.query.filter_by(status='PENDING')
                      .order_by(MaterialRequest.created_at.asc())
                      .paginate(page=mat_page, per_page=20, error_out=False))
    users_dict = {u.id: u for u in User.query.all()}
    materials_dict = {m.id: m for m in Material.query.all()}
    url_args = {k: v for k, v in request.args.items() if k not in ('page', 'mat_page')}

    return render_template('confirmation.html',
                           pending_pagination=pending_pagination,
                           pending_reports=pending_pagination.items,
                           mat_pagination=mat_pagination,
                           pending_materials=mat_pagination.items,
                           users_dict=users_dict,
                           materials_dict=materials_dict,
                           report_fields=REPORT_FIELDS,
                           url_args=url_args,
                           filter_start=filter_start,
                           filter_end=filter_end)


@app.route('/confirmation/report/<int:report_id>/confirm', methods=['POST'])
@admin_required
def confirm_report(report_id):
    r = db.session.get(Report, report_id)
    if not r:
        abort(404)
    users_dict = {u.id: u for u in User.query.all()}
    r.is_confirmed = True
    r.confirmed_by = current_user.id
    r.confirmed_at = datetime.utcnow()
    r.updated_at = datetime.utcnow()
    add_audit(current_user.id, 'REPORT_CONFIRM',
              f'確認 {get_user_display(users_dict, r.user_id)} 的回報 #{r.id}（{r.report_date}）')
    db.session.commit()
    flash('回報已確認', 'success')
    return redirect(url_for('confirmation'))


@app.route('/confirmation/report/<int:report_id>/reject', methods=['POST'])
@admin_required
def reject_report(report_id):
    r = db.session.get(Report, report_id)
    if not r:
        abort(404)
    users_dict = {u.id: u for u in User.query.all()}
    r.is_rejected = True
    r.updated_at = datetime.utcnow()
    add_audit(current_user.id, 'REPORT_REJECT',
              f'駁回 {get_user_display(users_dict, r.user_id)} 的回報 #{r.id}（{r.report_date}）')
    db.session.commit()
    flash('回報已駁回，回報者可在歷史紀錄中查看', 'warning')
    return redirect(url_for('confirmation'))


@app.route('/confirmation/material/<int:req_id>/approve', methods=['POST'])
@admin_required
def approve_material(req_id):
    req = db.session.get(MaterialRequest, req_id)
    if not req:
        abort(404)
    m = db.session.get(Material, req.material_id)
    users_dict = {u.id: u for u in User.query.all()}
    uname = get_user_display(users_dict, req.user_id)

    req.status = 'APPROVED'
    req.reviewed_by = current_user.id
    req.reviewed_at = datetime.utcnow()

    old_qty = m.remaining_quantity if m else 0
    if m:
        m.remaining_quantity = max(0, m.remaining_quantity - req.requested_quantity)
        m.updated_at = datetime.utcnow()

    mname = m.name if m else '?'
    munit = m.unit if m else ''
    add_audit(current_user.id, 'MATERIAL_APPROVE',
              f'核准 {uname} 申請的「{mname}」{req.requested_quantity}{munit}，'
              f'庫存 {old_qty} → {m.remaining_quantity if m else "?"}')
    db.session.commit()
    flash('材料申請已核准', 'success')
    return redirect(url_for('confirmation'))


@app.route('/confirmation/material/<int:req_id>/reject', methods=['POST'])
@admin_required
def reject_material(req_id):
    req = db.session.get(MaterialRequest, req_id)
    if not req:
        abort(404)
    m = db.session.get(Material, req.material_id)
    users_dict = {u.id: u for u in User.query.all()}
    uname = get_user_display(users_dict, req.user_id)

    req.status = 'REJECTED'
    req.reviewed_by = current_user.id
    req.reviewed_at = datetime.utcnow()

    mname = m.name if m else '?'
    munit = m.unit if m else ''
    add_audit(current_user.id, 'MATERIAL_REJECT',
              f'駁回 {uname} 申請的「{mname}」{req.requested_quantity}{munit}')
    db.session.commit()
    flash('材料申請已駁回', 'success')
    return redirect(url_for('confirmation'))


# ---------------------------------------------------------------------------
# Page 7: Audit Log
# ---------------------------------------------------------------------------

@app.route('/audit')
@login_required
def audit():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    action_type_filter = request.args.get('action_type', '')
    user_id_filter = request.args.get('user_id', '')

    q = AuditLog.query
    if current_user.role == 'USER':
        q = q.filter_by(user_id=current_user.id)
    elif user_id_filter:
        q = q.filter_by(user_id=int(user_id_filter))

    if start_date:
        q = q.filter(AuditLog.created_at >= datetime.fromisoformat(start_date))
    if end_date:
        q = q.filter(AuditLog.created_at <= datetime.fromisoformat(end_date + 'T23:59:59'))
    if action_type_filter:
        q = q.filter_by(action_type=action_type_filter)

    page = request.args.get('page', 1, type=int)
    pagination = q.order_by(AuditLog.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    _all_users_list = User.query.order_by(User.display_name).all()
    users_dict = {u.id: u for u in _all_users_list}
    all_users = _all_users_list if current_user.role == 'ADMIN' else []
    all_action_types = [r[0] for r in db.session.query(AuditLog.action_type).distinct().all()]
    url_args = {k: v for k, v in request.args.items() if k != 'page'}

    return render_template('audit.html',
                           logs=pagination.items,
                           pagination=pagination,
                           users_dict=users_dict,
                           all_users=all_users,
                           all_action_types=all_action_types,
                           start_date=start_date,
                           end_date=end_date,
                           selected_action=action_type_filter,
                           selected_user_id=user_id_filter,
                           url_args=url_args)


# ---------------------------------------------------------------------------
# Page 8: Salary (ADMIN)
# ---------------------------------------------------------------------------

@app.route('/salary', methods=['GET', 'POST'])
@admin_required
def salary():
    salary_results = None
    all_active_users = User.query.filter_by(is_active=True).order_by(User.display_name).all()
    item_prices = get_item_prices()
    form_data = {}

    if request.method == 'POST':
        action = request.form.get('action', 'calculate')
        start_str = request.form.get('start_date', '')
        end_str = request.form.get('end_date', '')

        prices = item_prices  # 單價固定由 SystemConfig 讀取，USER/ADMIN 無法從表單修改

        is_10th_payday = request.form.get('is_10th_payday') == '1'
        form_data = {'start_date': start_str, 'end_date': end_str,
                     'is_10th_payday': is_10th_payday}

        if start_str and end_str:
            try:
                sd = date.fromisoformat(start_str)
                ed = date.fromisoformat(end_str)
            except ValueError:
                flash('日期格式錯誤', 'danger')
                return render_template('salary.html', report_fields=REPORT_FIELDS,
                                       salary_results=None, form_data=form_data,
                                       all_active_users=all_active_users,
                                       now_year=date.today().year)

            reports = Report.query.filter(
                Report.is_confirmed == True,
                Report.report_date >= sd,
                Report.report_date <= ed
            ).all()

            # 一次查詢涵蓋全年：pre-period 上限計算 + YTD 保留金（消除 N 次 per-user 查詢）
            today = date.today()
            pre_year_start = date(sd.year, 1, 1)      # 保留金上限計算基準年
            ytd_year_start = date(today.year, 1, 1)   # YTD 顯示基準年（今年）
            query_start = min(pre_year_start, ytd_year_start)
            year_confirmed = Report.query.filter(
                Report.is_confirmed == True,
                Report.report_date >= query_start,
                Report.report_date <= today
            ).all()
            pre_ret_by_user: dict = {}
            ytd_totals_by_user: dict = {}
            for _r in year_confirmed:
                _uid = _r.user_id
                # YTD：今年的累積保留金（含本期）
                if _r.report_date >= ytd_year_start:
                    if _uid not in ytd_totals_by_user:
                        ytd_totals_by_user[_uid] = {f: 0 for f in RETENTION_FIELDS}
                    for f in RETENTION_FIELDS:
                        ytd_totals_by_user[_uid][f] += getattr(_r, f, 0)
                # Pre-period：計薪年度 Jan 1 到 sd 之前（用於保留金上限）
                if pre_year_start <= _r.report_date < sd:
                    if _uid not in pre_ret_by_user:
                        pre_ret_by_user[_uid] = {f: 0 for f in RETENTION_FIELDS}
                    for f in RETENTION_FIELDS:
                        pre_ret_by_user[_uid][f] += getattr(_r, f, 0)

            users_dict = {u.id: u for u in User.query.all()}
            active_user_ids = {u.id for u in all_active_users}

            user_data = {}
            for r in reports:
                uid = r.user_id
                if uid not in active_user_ids:
                    continue  # 略過已停用帳戶的回報
                if uid not in user_data:
                    uname = users_dict[uid].display_name if uid in users_dict else '(已刪除)'
                    user_data[uid] = {'username': uname,
                                      'totals': {k: 0 for k, _ in REPORT_FIELDS}}
                for k, _ in REPORT_FIELDS:
                    user_data[uid]['totals'][k] += getattr(r, k, 0)

            # 有固定薪資但本期無回報的在職帳戶也需納入計算
            for u in all_active_users:
                if u.id not in user_data and u.fixed_salary > 0:
                    user_data[u.id] = {'username': u.display_name,
                                       'totals': {k: 0 for k, _ in REPORT_FIELDS}}

            tax_rate = get_tax_rate()
            # 批次載入所有帳戶的客製保留金費率
            batch_rates = get_users_all_retention_rates(list(user_data.keys()))
            for uid, data in user_data.items():
                subtotals = {k: data['totals'][k] * prices.get(k, 0) for k, _ in REPORT_FIELDS}
                data['subtotals'] = subtotals
                data['gross_salary'] = sum(subtotals.values())

                # 保留金上限邏輯（使用帳戶客製費率）
                u = users_dict.get(uid)
                user_rates = batch_rates[uid]
                ret_offset = u.retention_offset if u else 0
                pre_totals = pre_ret_by_user.get(uid, {f: 0 for f in RETENTION_FIELDS})
                pre_calc = sum(pre_totals.get(f, 0) * user_rates[f] for f in RETENTION_FIELDS)
                ytd_before = min(RETENTION_CAP, max(0.0, pre_calc + ret_offset))
                period_ret_raw = sum(data['totals'].get(f, 0) * user_rates[f] for f in RETENTION_FIELDS)
                data['period_retention'] = max(0.0, min(period_ret_raw, RETENTION_CAP - ytd_before))

                data['net_salary'] = data['gross_salary'] - data['period_retention']
                # YTD 保留金：使用已批次載入的全年回報（不再逐帳戶發 DB 查詢）
                _ytd_totals = ytd_totals_by_user.get(uid, {})
                _ytd_calc = sum(_ytd_totals.get(f, 0) * user_rates[f] for f in RETENTION_FIELDS)
                data['ytd_retention'] = min(float(RETENTION_CAP),
                                            max(0.0, _ytd_calc + ret_offset))
                data['payment_method'] = u.payment_method if u else 'TRANSFER'
                data['bank_account']   = decrypt_bank(u.bank_account) if u else None

                # 勞健保：10 號發薪時扣（下期），已投保帳戶
                # 勞健保與固定薪資僅在10號發薪時計入
                ins = (u.insurance_deduction if u and u.insurance_deduction > 0 else 0) if is_10th_payday else 0
                data['insurance_deduction'] = ins

                fixed = (u.fixed_salary if u else 0) if is_10th_payday else 0
                data['fixed_salary'] = fixed

                # 稅務支出：未投保且未設免稅者
                not_enrolled = (u.insurance_deduction == 0 and not u.tax_exempt) if u else True
                data['tax_deduction'] = round(data['gross_salary'] * tax_rate / 100) if not_enrolled else 0
                data['final_salary'] = data['net_salary'] + fixed - ins - data['tax_deduction']

            grand_gross = sum(d['gross_salary'] for d in user_data.values())
            grand_period_retention = sum(d['period_retention'] for d in user_data.values())
            grand_ytd_retention = sum(d['ytd_retention'] for d in user_data.values())
            grand_insurance = sum(d['insurance_deduction'] for d in user_data.values())
            grand_fixed = sum(d['fixed_salary'] for d in user_data.values())
            grand_tax = sum(d['tax_deduction'] for d in user_data.values())
            grand = sum(d['final_salary'] for d in user_data.values())
            transfer_total = sum(d['final_salary'] for d in user_data.values()
                                 if d['payment_method'] == 'TRANSFER')
            cash_total = sum(d['final_salary'] for d in user_data.values()
                             if d['payment_method'] == 'CASH')
            # 提現面額：各人分開計算後再相加，避免合並面額被拆分（例如 500+500 ≠ 1000）
            cash_bills = {}
            for _d in user_data.values():
                if _d['payment_method'] == 'CASH' and _d['final_salary'] > 0:
                    for _denom, _cnt in calculate_cash_bills(_d['final_salary']).items():
                        cash_bills[_denom] = cash_bills.get(_denom, 0) + _cnt
            salary_results = {'start_date': start_str, 'end_date': end_str,
                              'user_data': user_data,
                              'grand_salary': grand,
                              'grand_gross': grand_gross,
                              'grand_period_retention': grand_period_retention,
                              'grand_ytd_retention': grand_ytd_retention,
                              'grand_insurance': grand_insurance,
                              'grand_fixed': grand_fixed,
                              'grand_tax': grand_tax,
                              'tax_rate': tax_rate,
                              'transfer_total': transfer_total,
                              'cash_total': cash_total,
                              'cash_bills': cash_bills,
                              'prices': prices}

            if action == 'export-excel':
                return _export_salary_excel(salary_results)
            elif action == 'export-pdf':
                return _export_salary_pdf(salary_results)
            elif action == 'export-transfer':
                return _export_salary_transfer_doc(salary_results)

    return render_template('salary.html', report_fields=REPORT_FIELDS,
                           salary_results=salary_results, form_data=form_data,
                           all_active_users=all_active_users,
                           item_prices=item_prices,
                           now_year=date.today().year)


def _export_salary_excel(results):
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = '薪資明細'

    title = f'薪資明細  {results["start_date"]} ～ {results["end_date"]}'
    ws.merge_cells('A1:D1')
    ws['A1'] = title
    ws['A1'].font = Font(bold=True, size=14)
    ws['A1'].alignment = Alignment(horizontal='center')

    blue  = PatternFill('solid', fgColor='4472C4')
    green = PatternFill('solid', fgColor='70AD47')
    amber = PatternFill('solid', fgColor='FFC000')
    lgreen = PatternFill('solid', fgColor='E2EFDA')
    lamber = PatternFill('solid', fgColor='FFF2CC')

    row = 3
    for uid, data in results['user_data'].items():
        method_label = '領現 (CASH)' if data['payment_method'] == 'CASH' else '轉帳 (TRANSFER)'
        name_cell = ws.cell(row=row, column=1,
                            value=f'帳戶：{data["username"]}　　發薪方式：{method_label}')
        name_cell.font = Font(bold=True, size=12)
        row += 1

        headers = ['工項', '只數', '單價 (NTD)', '小計 (NTD)']
        for c, h in enumerate(headers, 1):
            cell = ws.cell(row=row, column=c, value=h)
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = blue
            cell.alignment = Alignment(horizontal='center')
        row += 1

        for k, label in REPORT_FIELDS:
            ws.cell(row=row, column=1, value=label)
            ws.cell(row=row, column=2, value=data['totals'][k])
            ws.cell(row=row, column=3, value=results['prices'].get(k, 0))
            ws.cell(row=row, column=4, value=round(data['subtotals'][k], 2))
            row += 1

        # 薪資小結
        for col in range(1, 5):
            ws.cell(row=row, column=col).fill = PatternFill('solid', fgColor='D9E1F2')
        ws.cell(row=row, column=1, value='計薪小計（稅前）').font = Font(bold=True)
        ws.cell(row=row, column=4, value=round(data['gross_salary'], 2)).font = Font(bold=True)
        row += 1

        for col in range(1, 5):
            ws.cell(row=row, column=col).fill = lamber
        ws.cell(row=row, column=1, value='本期保留金（扣除）').font = Font(color='C00000')
        ws.cell(row=row, column=4, value=-round(data['period_retention'], 2)).font = Font(color='C00000')
        row += 1

        if data.get('fixed_salary', 0) > 0:
            for col in range(1, 5):
                ws.cell(row=row, column=col).fill = PatternFill('solid', fgColor='E8F5E9')
            ws.cell(row=row, column=1, value='固定薪資').font = Font(color='2E7D32')
            ws.cell(row=row, column=4, value=round(data['fixed_salary'], 2)).font = Font(color='2E7D32')
            row += 1

        if data.get('insurance_deduction', 0) > 0:
            for col in range(1, 5):
                ws.cell(row=row, column=col).fill = PatternFill('solid', fgColor='FDECEA')
            ws.cell(row=row, column=1, value='勞健保扣除').font = Font(color='C00000')
            ws.cell(row=row, column=4, value=-round(data['insurance_deduction'], 2)).font = Font(color='C00000')
            row += 1

        if data.get('tax_deduction', 0) > 0:
            for col in range(1, 5):
                ws.cell(row=row, column=col).fill = PatternFill('solid', fgColor='FFF3E0')
            tax_pct = results.get('tax_rate', 5)
            ws.cell(row=row, column=1, value=f'稅務支出（{tax_pct}%，未投保）').font = Font(color='E65100')
            ws.cell(row=row, column=4, value=-round(data['tax_deduction'], 2)).font = Font(color='E65100')
            row += 1

        for col in range(1, 5):
            ws.cell(row=row, column=col).fill = lgreen
        net_cell = ws.cell(row=row, column=1, value='本期實領金額')
        net_cell.font = Font(bold=True, color='375623')
        nv_cell = ws.cell(row=row, column=4, value=round(data['final_salary'], 2))
        nv_cell.font = Font(bold=True, color='375623')
        row += 1

        # 提現面額配置
        if data['payment_method'] == 'CASH' and data['final_salary'] > 0:
            bills = calculate_cash_bills(data['final_salary'])
            if bills:
                ws.cell(row=row, column=1, value='── 提現面額配置 ──').font = Font(italic=True, color='7F7F7F')
                row += 1
                for denom in CASH_DENOMINATIONS:
                    cnt = bills.get(denom, 0)
                    if cnt:
                        ws.cell(row=row, column=1, value=f'  {denom} 元')
                        ws.cell(row=row, column=2, value=f'× {cnt} {"張" if denom >= 100 else "枚"}')
                        ws.cell(row=row, column=4, value=denom * cnt)
                        row += 1
        row += 1  # 帳戶之間空一行

    # 發放總覽
    row += 1
    summary_title = ws.cell(row=row, column=1, value='── 薪資發放總覽 ──')
    summary_title.font = Font(bold=True, size=12)
    row += 1

    for col in range(1, 5):
        ws.cell(row=row, column=col).fill = blue
    ws.cell(row=row, column=1, value='項目').font = Font(bold=True, color='FFFFFF')
    ws.cell(row=row, column=4, value='金額 (NTD)').font = Font(bold=True, color='FFFFFF')
    row += 1

    ws.cell(row=row, column=1, value='計薪小計（稅前）合計')
    ws.cell(row=row, column=4, value=round(results['grand_gross'], 2))
    row += 1
    ws.cell(row=row, column=1, value='保留金合計（扣除）').font = Font(color='C00000')
    ws.cell(row=row, column=4, value=-round(results['grand_period_retention'], 2)).font = Font(color='C00000')
    row += 1
    if results.get('grand_fixed', 0) > 0:
        ws.cell(row=row, column=1, value='固定薪資合計').font = Font(color='2E7D32')
        ws.cell(row=row, column=4, value=round(results['grand_fixed'], 2)).font = Font(color='2E7D32')
        row += 1
    if results.get('grand_insurance', 0) > 0:
        ws.cell(row=row, column=1, value='勞健保扣除合計').font = Font(color='C00000')
        ws.cell(row=row, column=4, value=-round(results['grand_insurance'], 2)).font = Font(color='C00000')
        row += 1
    if results.get('grand_tax', 0) > 0:
        tax_pct = results.get('tax_rate', 5)
        ws.cell(row=row, column=1, value=f'稅務支出合計（{tax_pct}%）').font = Font(color='E65100')
        ws.cell(row=row, column=4, value=-round(results['grand_tax'], 2)).font = Font(color='E65100')
        row += 1

    for col in range(1, 5):
        ws.cell(row=row, column=col).fill = lgreen
    ws.cell(row=row, column=1, value='實領薪資總合計').font = Font(bold=True, color='375623')
    ws.cell(row=row, column=4, value=round(results['grand_salary'], 2)).font = Font(bold=True, color='375623')
    row += 1

    ws.cell(row=row, column=1, value='轉帳薪資總額').font = Font(color='0070C0')
    ws.cell(row=row, column=4, value=round(results['transfer_total'], 2)).font = Font(color='0070C0')
    row += 1

    for col in range(1, 5):
        ws.cell(row=row, column=col).fill = lamber
    ws.cell(row=row, column=1, value='提現薪資總額').font = Font(bold=True, color='7F4C00')
    ws.cell(row=row, column=4, value=round(results['cash_total'], 2)).font = Font(bold=True, color='7F4C00')
    row += 1

    if results['cash_bills']:
        ws.cell(row=row, column=1, value='提現面額配置（所有領現帳戶合計）').font = Font(italic=True)
        row += 1
        for denom in CASH_DENOMINATIONS:
            cnt = results['cash_bills'].get(denom, 0)
            if cnt:
                ws.cell(row=row, column=1, value=f'  {denom} 元')
                ws.cell(row=row, column=2, value=f'× {cnt} {"張" if denom >= 100 else "枚"}')
                ws.cell(row=row, column=4, value=denom * cnt)
                row += 1

    from openpyxl.utils import get_column_letter
    from openpyxl.cell.cell import MergedCell
    for col_idx in range(1, ws.max_column + 1):
        col_letter = get_column_letter(col_idx)
        max_len = max(
            (len(str(c.value)) for c in ws[col_letter]
             if c.value and not isinstance(c, MergedCell)),
            default=10
        )
        ws.column_dimensions[col_letter].width = min(max_len * 2.2 + 4, 60)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f'salary_{results["start_date"]}_{results["end_date"]}.xlsx'
    return send_file(buf,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=fname)


def _export_salary_pdf(results):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # Use reportlab built-in CID font — no system font installation required
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    try:
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
        font_name = 'STSong-Light'
    except Exception:
        font_name = 'Helvetica'

    # Override with a better TTF if available locally (Windows / macOS dev)
    _cjk_candidates = [
        'C:/Windows/Fonts/msjh.ttc',
        'C:/Windows/Fonts/msyh.ttc',
        '/System/Library/Fonts/PingFang.ttc',
    ]
    for fp in _cjk_candidates:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont('CJK', fp))
                font_name = 'CJK'
                break
            except Exception:
                pass

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)

    def style(name, **kw):
        kw.setdefault('fontName', font_name)
        kw.setdefault('fontSize', 10)
        kw.setdefault('leading', 16)
        return ParagraphStyle(name, **kw)

    C_BLUE   = colors.HexColor('#4472C4')
    C_GREEN  = colors.HexColor('#E2EFDA')
    C_AMBER  = colors.HexColor('#FFF2CC')
    C_DGREY  = colors.HexColor('#D9E1F2')
    C_RED    = colors.HexColor('#C00000')
    C_DGREEN = colors.HexColor('#375623')

    story = []
    story.append(Paragraph(
        f'薪資明細  {results["start_date"]} ～ {results["end_date"]}',
        style('title', fontSize=16, alignment=1, spaceAfter=16)))

    n_fields = len(REPORT_FIELDS)

    for uid, data in results['user_data'].items():
        method_label = '領現 (CASH)' if data['payment_method'] == 'CASH' else '轉帳 (TRANSFER)'
        story.append(Paragraph(
            f'帳戶：{data["username"]}　　發薪方式：{method_label}',
            style('h2', fontSize=12, spaceBefore=10, spaceAfter=4)))

        tdata = [['工項', '只數', '單價(NTD)', '小計(NTD)']]
        for k, label in REPORT_FIELDS:
            tdata.append([label,
                          str(data['totals'][k]),
                          f'{results["prices"].get(k, 0):,.0f}',
                          f'{data["subtotals"][k]:,.0f}'])
        # 小結行
        tdata.append(['計薪小計（稅前）', '', '', f'{data["gross_salary"]:,.0f}'])
        tdata.append(['本期保留金（扣除）', '', '', f'-{data["period_retention"]:,.0f}'])
        fixed_s = data.get('fixed_salary', 0)
        ins_d   = data.get('insurance_deduction', 0)
        if fixed_s > 0:
            tdata.append(['固定薪資', '', '', f'+{fixed_s:,.0f}'])
        if ins_d > 0:
            tdata.append(['勞健保扣除', '', '', f'-{ins_d:,.0f}'])
        tdata.append(['本期實領金額', '', '', f'{data["final_salary"]:,.0f}'])

        subtotal_row  = 1 + n_fields
        retention_row = subtotal_row + 1
        extra = (1 if fixed_s > 0 else 0) + (1 if ins_d > 0 else 0)
        fixed_row = retention_row + 1 if fixed_s > 0 else None
        ins_row = (retention_row + (2 if fixed_s > 0 else 1)) if ins_d > 0 else None
        net_row = retention_row + 1 + extra

        ts_cmds = [
            ('FONTNAME',   (0, 0), (-1, -1), font_name),
            ('FONTSIZE',   (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, 0),  C_BLUE),
            ('TEXTCOLOR',  (0, 0), (-1, 0),  colors.white),
            ('ALIGN',      (1, 0), (-1, -1), 'RIGHT'),
            ('GRID',       (0, 0), (-1, -1), 0.4, colors.grey),
            ('BACKGROUND', (0, subtotal_row), (-1, subtotal_row), C_DGREY),
            ('BACKGROUND', (0, retention_row), (-1, retention_row), C_AMBER),
            ('TEXTCOLOR',  (0, retention_row), (-1, retention_row), C_RED),
            ('BACKGROUND', (0, net_row), (-1, net_row), C_GREEN),
            ('TEXTCOLOR',  (0, net_row), (-1, net_row), C_DGREEN),
            ('FONTNAME',   (0, net_row), (-1, net_row), font_name),
        ]
        if fixed_row:
            ts_cmds += [
                ('BACKGROUND', (0, fixed_row), (-1, fixed_row), colors.HexColor('#E8F5E9')),
                ('TEXTCOLOR',  (0, fixed_row), (-1, fixed_row), colors.HexColor('#2E7D32')),
            ]
        if ins_row:
            ts_cmds += [
                ('BACKGROUND', (0, ins_row), (-1, ins_row), colors.HexColor('#FDECEA')),
                ('TEXTCOLOR',  (0, ins_row), (-1, ins_row), C_RED),
            ]
        ts = TableStyle(ts_cmds)
        t = Table(tdata, colWidths=[210, 55, 90, 90])
        t.setStyle(ts)
        story.append(t)

        # 提現面額配置（僅限領現帳戶）
        if data['payment_method'] == 'CASH' and data['final_salary'] > 0:
            bills = calculate_cash_bills(data['final_salary'])
            if bills:
                story.append(Spacer(1, 4))
                bdata = [['面額', '張 / 枚', '小計(NTD)']]
                for denom in CASH_DENOMINATIONS:
                    cnt = bills.get(denom, 0)
                    if cnt:
                        unit = '張' if denom >= 100 else '枚'
                        bdata.append([f'{denom} 元', f'× {cnt} {unit}', f'{denom*cnt:,}'])
                bt = Table(bdata, colWidths=[100, 100, 100])
                bt.setStyle(TableStyle([
                    ('FONTNAME',   (0, 0), (-1, -1), font_name),
                    ('FONTSIZE',   (0, 0), (-1, -1), 8),
                    ('BACKGROUND', (0, 0), (-1, 0),  colors.HexColor('#7F7F7F')),
                    ('TEXTCOLOR',  (0, 0), (-1, 0),  colors.white),
                    ('ALIGN',      (1, 0), (-1, -1), 'RIGHT'),
                    ('GRID',       (0, 0), (-1, -1), 0.4, colors.grey),
                    ('BACKGROUND', (0, 1), (-1, -1), C_AMBER),
                ]))
                story.append(bt)

        story.append(Spacer(1, 14))

    # 發放總覽
    story.append(Paragraph('薪資發放總覽', style('h2', fontSize=12, spaceBefore=6, spaceAfter=4)))
    sdata = [
        ['項目', '金額 (NTD)'],
        ['計薪小計（稅前）合計', f'{results["grand_gross"]:,.0f}'],
        ['保留金合計（扣除）',   f'-{results["grand_period_retention"]:,.0f}'],
    ]
    if results.get('grand_fixed', 0) > 0:
        sdata.append(['固定薪資合計', f'+{results["grand_fixed"]:,.0f}'])
    if results.get('grand_insurance', 0) > 0:
        sdata.append(['勞健保扣除合計', f'-{results["grand_insurance"]:,.0f}'])
    if results.get('grand_tax', 0) > 0:
        sdata.append([f'稅務支出合計（{results.get("tax_rate",5)}%）', f'-{results["grand_tax"]:,.0f}'])
    sdata += [
        ['實領薪資總合計',       f'{results["grand_salary"]:,.0f}'],
        ['轉帳薪資總額',         f'{results["transfer_total"]:,.0f}'],
        ['提現薪資總額',         f'{results["cash_total"]:,.0f}'],
    ]
    if results['cash_bills']:
        sdata.append(['── 提現面額配置（合計）──', ''])
        for denom in CASH_DENOMINATIONS:
            cnt = results['cash_bills'].get(denom, 0)
            if cnt:
                unit = '張' if denom >= 100 else '枚'
                sdata.append([f'  {denom} 元 × {cnt} {unit}', f'{denom*cnt:,}'])

    st = Table(sdata, colWidths=[250, 150])
    n_s = len(sdata)
    st.setStyle(TableStyle([
        ('FONTNAME',   (0, 0), (-1, -1), font_name),
        ('FONTSIZE',   (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0),  C_BLUE),
        ('TEXTCOLOR',  (0, 0), (-1, 0),  colors.white),
        ('ALIGN',      (1, 0), (-1, -1), 'RIGHT'),
        ('GRID',       (0, 0), (-1, -1), 0.4, colors.grey),
        ('BACKGROUND', (0, 3), (-1, 3),  C_GREEN),   # 實領合計
        ('TEXTCOLOR',  (0, 3), (-1, 3),  C_DGREEN),
        ('BACKGROUND', (0, 2), (-1, 2),  C_AMBER),   # 保留金
        ('TEXTCOLOR',  (0, 2), (-1, 2),  C_RED),
        ('BACKGROUND', (0, 5), (-1, 5),  C_AMBER),   # 提現
    ]))
    story.append(st)

    doc.build(story)
    buf.seek(0)
    fname = f'salary_{results["start_date"]}_{results["end_date"]}.pdf'
    return send_file(buf, mimetype='application/pdf',
                     as_attachment=True, download_name=fname)


def _export_salary_transfer_doc(results):
    """匯出板信薪資轉帳送件單（Word .docx）"""
    try:
        from docx import Document
        from docx.shared import Pt, Cm
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
    except ImportError:
        flash('缺少 python-docx 套件，無法匯出薪轉單', 'danger')
        return redirect(url_for('salary'))

    FONT_CJK = '標楷體'
    FONT_LAT = 'Times New Roman'
    GREY     = 'D9D9D9'

    # ── font helpers ──────────────────────────────────────────────────────────
    def _font(run, pt, bold=False, underline=False):
        run.font.size      = Pt(pt)
        run.font.bold      = bold
        run.font.underline = underline
        rPr    = run._r.get_or_add_rPr()
        rFonts = rPr.find(qn('w:rFonts'))
        if rFonts is None:
            rFonts = OxmlElement('w:rFonts'); rPr.insert(0, rFonts)
        rFonts.set(qn('w:ascii'),    FONT_LAT)
        rFonts.set(qn('w:hAnsi'),   FONT_LAT)
        rFonts.set(qn('w:eastAsia'), FONT_CJK)
        rFonts.set(qn('w:cs'),      FONT_CJK)

    def _font_kai(run, pt, bold=False, underline=False):
        run.font.size      = Pt(pt)
        run.font.bold      = bold
        run.font.underline = underline
        rPr    = run._r.get_or_add_rPr()
        rFonts = rPr.find(qn('w:rFonts'))
        if rFonts is None:
            rFonts = OxmlElement('w:rFonts'); rPr.insert(0, rFonts)
        for attr in ('w:ascii', 'w:hAnsi', 'w:eastAsia', 'w:cs'):
            rFonts.set(qn(attr), FONT_CJK)

    # ── cell/table helpers ────────────────────────────────────────────────────
    def _shd(cell, hex_fill):
        tcPr = cell._tc.get_or_add_tcPr()
        shd  = OxmlElement('w:shd')
        shd.set(qn('w:val'),   'clear')
        shd.set(qn('w:color'), 'auto')
        shd.set(qn('w:fill'),  hex_fill)
        tcPr.append(shd)

    def _row_height(row, cm, exact=True):
        trPr = row._tr.get_or_add_trPr()
        h    = OxmlElement('w:trHeight')
        h.set(qn('w:val'),   str(int(cm * 567)))
        h.set(qn('w:hRule'), 'exact' if exact else 'atLeast')
        trPr.append(h)

    def _para_fmt(para, align=WD_ALIGN_PARAGRAPH.LEFT, before=0, after=0):
        para.alignment = align
        para.paragraph_format.space_before = Pt(before)
        para.paragraph_format.space_after  = Pt(after)

    def _cell_text(cell, text, pt, bold=False, align=WD_ALIGN_PARAGRAPH.LEFT,
                   underline=False, kai=False):
        for extra in cell.paragraphs[1:]:
            extra._p.getparent().remove(extra._p)
        para = cell.paragraphs[0]
        for r in para._p.findall(qn('w:r')):
            para._p.remove(r)
        _para_fmt(para, align)
        run = para.add_run(text)
        (_font_kai if kai else _font)(run, pt=pt, bold=bold, underline=underline)
        return run

    def _tbl_borders(table, top=True, bottom=True, outer_sz=12, inner_sz=4):
        tbl   = table._tbl
        tblPr = tbl.find(qn('w:tblPr'))
        if tblPr is None:
            tblPr = OxmlElement('w:tblPr'); tbl.insert(0, tblPr)
        old = tblPr.find(qn('w:tblBorders'))
        if old is not None:
            tblPr.remove(old)
        tblBdr = OxmlElement('w:tblBorders')
        tblPr.append(tblBdr)
        for side, draw in [('top', top), ('bottom', bottom),
                            ('left', True), ('right', True),
                            ('insideH', True), ('insideV', True)]:
            e        = OxmlElement(f'w:{side}')
            is_outer = side in ('top', 'bottom', 'left', 'right')
            if draw:
                e.set(qn('w:val'),   'single')
                e.set(qn('w:sz'),    str(outer_sz if is_outer else inner_sz))
                e.set(qn('w:color'), '000000')
            else:
                e.set(qn('w:val'),   'none')
                e.set(qn('w:sz'),    '0')
                e.set(qn('w:color'), 'auto')
            tblBdr.append(e)

    def _cell_btm_border(cell, sz=4):
        tcPr  = cell._tc.get_or_add_tcPr()
        tcBdr = tcPr.find(qn('w:tcBdr'))
        if tcBdr is None:
            tcBdr = OxmlElement('w:tcBdr'); tcPr.append(tcBdr)
        btm = OxmlElement('w:bottom')
        btm.set(qn('w:val'),   'single')
        btm.set(qn('w:sz'),    str(sz))
        btm.set(qn('w:color'), '000000')
        tcBdr.append(btm)

    def _set_table_widths(table, widths_cm):
        tbl   = table._tbl
        tblPr = tbl.find(qn('w:tblPr'))
        if tblPr is None:
            tblPr = OxmlElement('w:tblPr'); tbl.insert(0, tblPr)
        tblLayout = OxmlElement('w:tblLayout')
        tblLayout.set(qn('w:type'), 'fixed')
        tblPr.append(tblLayout)
        total = int(sum(w * 567 for w in widths_cm))
        tblW  = tblPr.find(qn('w:tblW'))
        if tblW is None:
            tblW = OxmlElement('w:tblW'); tblPr.append(tblW)
        tblW.set(qn('w:w'), str(total)); tblW.set(qn('w:type'), 'dxa')
        old = tbl.find(qn('w:tblGrid'))
        if old is not None:
            tbl.remove(old)
        tblGrid = OxmlElement('w:tblGrid')
        tbl.insert(list(tbl).index(tblPr) + 1, tblGrid)
        for w in widths_cm:
            gc = OxmlElement('w:gridCol'); gc.set(qn('w:w'), str(int(w * 567))); tblGrid.append(gc)
        for row in table.rows:
            col = 0
            for tc in row._tr.findall(qn('w:tc')):
                if col >= len(widths_cm): break
                tcPr = tc.find(qn('w:tcPr'))
                if tcPr is None: tcPr = OxmlElement('w:tcPr'); tc.insert(0, tcPr)
                gs   = tcPr.find(qn('w:gridSpan'))
                span = int(gs.get(qn('w:val'), 1)) if gs is not None else 1
                w_sum = sum(widths_cm[col:col + span]) if col + span <= len(widths_cm) else widths_cm[col]
                tcW = tcPr.find(qn('w:tcW'))
                if tcW is None: tcW = OxmlElement('w:tcW'); tcPr.append(tcW)
                tcW.set(qn('w:w'), str(int(w_sum * 567))); tcW.set(qn('w:type'), 'dxa')
                col += span

    def _blank_run(para, value_str, width):
        padded = value_str.center(width) if len(value_str) < width else value_str
        run = para.add_run(padded)
        _font(run, pt=12, underline=True)

    def _add_tab(para, pos_cm):
        pPr  = para._p.get_or_add_pPr()
        tabs = pPr.find(qn('w:tabs'))
        if tabs is None:
            tabs = OxmlElement('w:tabs'); pPr.append(tabs)
        tab = OxmlElement('w:tab')
        tab.set(qn('w:val'), 'left')
        tab.set(qn('w:pos'), str(int(pos_cm * 567)))
        tabs.append(tab)

    # ── business helpers ──────────────────────────────────────────────────────
    def _next_workday(d):
        if d.weekday() == 5: return d + timedelta(days=2)
        if d.weekday() == 6: return d + timedelta(days=1)
        return d

    def _roc(d):
        return f"{d.year - 1911} 年 {d.month} 月 {d.day} 日"

    def _fmt_acct(a):
        if not a or len(a) != 14: return a or '（未設定）'
        return f"{a[:4]}-{a[4:7]}-{a[7:]}"

    # ── payday date ───────────────────────────────────────────────────────────
    ed = date.fromisoformat(results['end_date'])
    is_25th = results.get('is_25th_payday', False)
    if is_25th:
        raw = date(ed.year, ed.month, 25)
    else:
        raw = date(ed.year, ed.month, 10)
    payday = _next_workday(raw)

    # ── TRANSFER entries ──────────────────────────────────────────────────────
    entries = [
        (_fmt_acct(d.get('bank_account', '')), int(round(d['final_salary'])))
        for d in results['user_data'].values()
        if d['payment_method'] == 'TRANSFER' and d['final_salary'] > 0
    ]
    total_amt = sum(a for _, a in entries)
    total_n   = len(entries)

    # ── company constants ─────────────────────────────────────────────────────
    CO_NAME = '宇丞工程有限公司'
    CO_ACCT = '02975000021056'
    CO_ID   = '27893806'
    CO_TEL  = '02-29497898'
    BANK    = '板信商業銀行'

    # ── document setup ────────────────────────────────────────────────────────
    doc = Document()
    sec = doc.sections[0]
    sec.page_width    = Cm(21.0)
    sec.page_height   = Cm(29.7)
    sec.left_margin   = Cm(1.8)
    sec.right_margin  = Cm(1.8)
    sec.top_margin    = Cm(1.5)
    sec.bottom_margin = Cm(1.5)

    try:
        st  = doc.styles['Normal']
        rPr = st._element.get_or_add_rPr()
        rF  = rPr.find(qn('w:rFonts'))
        if rF is None:
            rF = OxmlElement('w:rFonts'); rPr.insert(0, rF)
        rF.set(qn('w:ascii'),    FONT_LAT)
        rF.set(qn('w:hAnsi'),   FONT_LAT)
        rF.set(qn('w:eastAsia'), FONT_CJK)
        rF.set(qn('w:cs'),      FONT_CJK)
        st.paragraph_format.space_before = Pt(0)
        st.paragraph_format.space_after  = Pt(0)
    except Exception:
        pass

    # ── Title ─────────────────────────────────────────────────────────────────
    p = doc.add_paragraph()
    _para_fmt(p, WD_ALIGN_PARAGRAPH.CENTER, after=4)
    _font(p.add_run('薪資轉帳送件單'), pt=20, bold=False)

    # ── Date line ─────────────────────────────────────────────────────────────
    p = doc.add_paragraph()
    _para_fmt(p, WD_ALIGN_PARAGRAPH.RIGHT, after=2)
    _font(p.add_run(f'{_roc(payday)}（第 1 頁/共 1 頁）'), pt=12)

    # ── TABLE_1: info + summary + 此致 + 銀行 + 轉帳明細表 (4 cols) ────────────
    T1_W = [3.0, 5.7, 3.0, 5.7]
    t1   = doc.add_table(rows=4, cols=4)

    for ci, text in enumerate(['委託人名稱', CO_NAME, '轉帳帳號', CO_ACCT]):
        _cell_text(t1.cell(0, ci), text, pt=14, align=WD_ALIGN_PARAGRAPH.CENTER)
    for ci, text in enumerate(['委託人 ID', CO_ID, '聯絡人/電話', CO_TEL]):
        _cell_text(t1.cell(1, ci), text, pt=14, align=WD_ALIGN_PARAGRAPH.CENTER)

    # Row 2: merged full-width — summary + 此致 + 板信商業銀行
    t1.cell(2, 0).merge(t1.cell(2, 3))
    cell = t1.cell(2, 0)
    for extra in cell.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)
    p0 = cell.paragraphs[0]
    _para_fmt(p0, before=3, after=0)
    n_str   = str(total_n)
    amt_str = f'{total_amt:,}'
    _font(p0.add_run('本次員工薪資轉帳共'), pt=12)
    _blank_run(p0, n_str, 8)
    _font(p0.add_run('筆，金額共計'), pt=12)
    _blank_run(p0, amt_str, 9)
    _font(p0.add_run('元，請由上列「轉帳帳號」轉入明細表之各受領人帳戶，隨件附送'), pt=12)
    _font(p0.add_run('檔案'), pt=12, bold=True, underline=True)
    _font(p0.add_run('＿＿份及電腦印列明細表_______頁，請惠予辦理。'), pt=12)
    p1 = cell.add_paragraph()
    _para_fmt(p1, before=2, after=0)
    _font(p1.add_run('此　　　致'), pt=12)
    p2 = cell.add_paragraph()
    _para_fmt(p2, before=0, after=3)
    _font(p2.add_run(BANK), pt=14)
    _font(p2.add_run('　台照'), pt=12)

    # Row 3: 轉帳明細表 — gray bg
    t1.cell(3, 0).merge(t1.cell(3, 3))
    cell = t1.cell(3, 0)
    _cell_text(cell, '轉帳明細表', pt=14, align=WD_ALIGN_PARAGRAPH.CENTER)
    _shd(cell, GREY)

    _tbl_borders(t1, bottom=False)
    _cell_btm_border(t1.cell(3, 0), sz=4)
    _set_table_widths(t1, T1_W)

    # ── TABLE_2: detail + signature rows (6 cols) ─────────────────────────────
    NROWS = 15
    T2_W  = [1.2, 5.0, 2.5, 1.2, 5.0, 2.5]
    t2    = doc.add_table(rows=1 + NROWS + 2, cols=6)

    # Header (all white)
    for ci, (lbl, pt) in enumerate(
        zip(['序號', '帳號', '金額', '序號', '帳號', '金額'],
            [10, 14, 14, 10, 14, 14])
    ):
        _cell_text(t2.cell(0, ci), lbl, pt=pt, align=WD_ALIGN_PARAGRAPH.CENTER)
    _row_height(t2.rows[0], 0.8)

    # Data rows
    for r in range(NROWS):
        li   = r
        ri_  = r + NROWS
        cells = t2.row_cells(1 + r)
        _row_height(t2.rows[1 + r], 0.8)
        _cell_text(cells[0], str(li  + 1), pt=12, align=WD_ALIGN_PARAGRAPH.CENTER)
        _cell_text(cells[3], str(ri_ + 1), pt=12, align=WD_ALIGN_PARAGRAPH.CENTER)
        if li < len(entries):
            acct, amt = entries[li]
            _cell_text(cells[1], acct,           pt=13, kai=True)
            _cell_text(cells[2], f'{amt:,.2f}',  pt=13, align=WD_ALIGN_PARAGRAPH.RIGHT, kai=True)
        if ri_ < len(entries):
            acct, amt = entries[ri_]
            _cell_text(cells[4], acct,           pt=13, kai=True)
            _cell_text(cells[5], f'{amt:,.2f}',  pt=13, align=WD_ALIGN_PARAGRAPH.RIGHT, kai=True)

    # Signature label row (gray)
    fr = NROWS + 1
    t2.cell(fr, 0).merge(t2.cell(fr, 1))
    t2.cell(fr, 2).merge(t2.cell(fr, 3))
    t2.cell(fr, 4).merge(t2.cell(fr, 5))
    _row_height(t2.rows[fr], 0.8)
    for ci, lbl in [(0, '受託人簽收'), (2, '異動名單'), (4, '委託人(存戶)簽章')]:
        _cell_text(t2.cell(fr, ci), lbl, pt=12, align=WD_ALIGN_PARAGRAPH.CENTER)
        _shd(t2.cell(fr, ci), GREY)

    # Blank signature row
    fb = fr + 1
    t2.cell(fb, 0).merge(t2.cell(fb, 1))
    t2.cell(fb, 2).merge(t2.cell(fb, 3))
    t2.cell(fb, 4).merge(t2.cell(fb, 5))
    _row_height(t2.rows[fb], 2.0, exact=True)
    for ci in (0, 2, 4):
        _cell_text(t2.cell(fb, ci), '', pt=12)

    _tbl_borders(t2, top=False)
    _set_table_widths(t2, T2_W)

    # Remove auto-paragraph between t1 and t2
    body  = doc.element.body
    elems = list(body)
    mid   = elems[elems.index(t1._tbl) + 1]
    if mid is not t2._tbl:
        body.remove(mid)

    # ── Notes ─────────────────────────────────────────────────────────────────
    INDENT = Cm(1.5)
    p = doc.add_paragraph()
    p.paragraph_format.space_before      = Pt(6)
    p.paragraph_format.space_after       = Pt(0)
    p.paragraph_format.left_indent       = INDENT
    p.paragraph_format.first_line_indent = -INDENT
    _font(p.add_run('備註：1.本送件單由委託人填具乙式兩份，乙份交受託人依約定辦理，'
                    '乙份由受託人簽章後交委託人存查'), pt=12)
    _font(p.add_run('（含檔案、明細表等文件）'), pt=12, bold=True, underline=True)
    _font(p.add_run('。'), pt=12)

    p = doc.add_paragraph()
    p.paragraph_format.space_before      = Pt(0)
    p.paragraph_format.space_after       = Pt(6)
    p.paragraph_format.left_indent       = INDENT
    p.paragraph_format.first_line_indent = Pt(0)
    _font(p.add_run('2.若有人員異動時，請於異動名單欄註明員工姓名及帳號。'), pt=12)

    # ── Bottom admin lines ─────────────────────────────────────────────────────
    TAB1, TAB2, TAB3 = 5.5, 10.5, 14.5
    p = doc.add_paragraph()
    _para_fmt(p)
    _add_tab(p, TAB1); _add_tab(p, TAB2); _add_tab(p, TAB3)
    _font(p.add_run('編號：SA2013　114.01.13'), pt=10)
    p.add_run('\t')
    _font(p.add_run('主管：　　　　　　　　'), pt=12)
    p.add_run('\t')
    _font(p.add_run('經辦：　　　　　　　　'), pt=12)
    p.add_run('\t')
    _font(p.add_run('驗印：'), pt=12)

    p = doc.add_paragraph()
    _para_fmt(p)
    _add_tab(p, TAB1); _add_tab(p, TAB2)
    _font(p.add_run('保存期限：七年'), pt=10)
    p.add_run('\t')
    p.add_run('\t')
    _font(p.add_run('批號：'), pt=12)

    # ── export ────────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    fname = f"薪轉單_{payday.strftime('%Y%m%d')}.docx"
    return send_file(
        buf,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        as_attachment=True,
        download_name=fname,
    )


# ---------------------------------------------------------------------------
# Page 9: Personal Statistics (USER and ADMIN)
# ---------------------------------------------------------------------------

@app.route('/personal-stats', methods=['GET', 'POST'])
@login_required
def personal_stats():
    totals_result = None
    salary_result = None
    form = request.form if request.method == 'POST' else {}

    stats_start   = form.get('stats_start',   '')
    stats_end     = form.get('stats_end',     '')
    stats_confirm = form.get('stats_confirm', 'all')
    salary_start  = form.get('salary_start',  '')
    salary_end    = form.get('salary_end',    '')
    deduct_ins_checked = form.get('deduct_insurance') == '1'

    ytd_retention = get_ytd_retention(current_user.id)
    my_ret_rates  = get_users_all_retention_rates([current_user.id])[current_user.id]

    # ── 工項總和查詢：只要日期有填就計算（不依賴 action）──────────────────
    if stats_start and stats_end:
        try:
            q = Report.query.filter(
                Report.user_id == current_user.id,
                Report.report_date >= date.fromisoformat(stats_start),
                Report.report_date <= date.fromisoformat(stats_end)
            )
            if stats_confirm == 'confirmed':
                q = q.filter_by(is_confirmed=True)
            elif stats_confirm == 'unconfirmed':
                q = q.filter_by(is_confirmed=False)
            _reports_s = q.all()
            totals_s = {k: 0 for k, _ in REPORT_FIELDS}
            for r in _reports_s:
                for k, _ in REPORT_FIELDS:
                    totals_s[k] += getattr(r, k, 0)
            period_ret_s = sum(totals_s.get(f, 0) * my_ret_rates[f] for f in RETENTION_FIELDS)
            totals_result = {'start': stats_start, 'end': stats_end,
                             'confirm_filter': stats_confirm,
                             'totals': totals_s, 'count': len(_reports_s),
                             'period_retention': period_ret_s}
        except ValueError:
            pass

    # ── 薪資試算：只要日期有填就計算，單價唯讀來自 SystemConfig ─────────
    item_prices = get_item_prices()
    if salary_start and salary_end:
        try:
            prices = item_prices
            sd_ps  = date.fromisoformat(salary_start)
            ed_ps  = date.fromisoformat(salary_end)
            _reports_p = Report.query.filter(
                Report.user_id == current_user.id,
                Report.is_confirmed == True,
                Report.report_date >= sd_ps,
                Report.report_date <= ed_ps
            ).all()
            totals_p = {k: 0 for k, _ in REPORT_FIELDS}
            for r in _reports_p:
                for k, _ in REPORT_FIELDS:
                    totals_p[k] += getattr(r, k, 0)
            subtotals  = {k: totals_p[k] * prices.get(k, 0) for k, _ in REPORT_FIELDS}
            grand_total = sum(subtotals.values())

            year_start  = date(sd_ps.year, 1, 1)
            pre_reports = Report.query.filter(
                Report.user_id == current_user.id,
                Report.is_confirmed == True,
                Report.report_date >= year_start,
                Report.report_date < sd_ps
            ).all()
            pre_totals = {f: sum(getattr(r, f, 0) for r in pre_reports) for f in RETENTION_FIELDS}
            pre_calc   = sum(pre_totals.get(f, 0) * my_ret_rates[f] for f in RETENTION_FIELDS)
            ytd_before = min(RETENTION_CAP, max(0.0, pre_calc + current_user.retention_offset))
            period_ret_raw  = sum(totals_p.get(f, 0) * my_ret_rates[f] for f in RETENTION_FIELDS)
            period_retention = max(0.0, min(period_ret_raw, RETENTION_CAP - ytd_before))

            ins_amount   = current_user.insurance_deduction if deduct_ins_checked else 0
            not_enrolled = (current_user.insurance_deduction == 0 and not current_user.tax_exempt)
            tax_rate_val = get_tax_rate()
            # 未投保需扣稅者，僅在勾選checkbox時才計算稅務支出
            tax_amount   = round(grand_total * tax_rate_val / 100) if (not_enrolled and deduct_ins_checked) else 0
            salary_result = {'start': salary_start, 'end': salary_end,
                             'totals': totals_p, 'prices': prices,
                             'subtotals': subtotals,
                             'grand_total': grand_total,
                             'period_retention': period_retention,
                             'insurance_deduction': ins_amount,
                             'tax_deduction': tax_amount,
                             'tax_rate': tax_rate_val,
                             'not_enrolled': not_enrolled,
                             'final_salary': grand_total - period_retention - ins_amount - tax_amount,
                             'deduct_insurance': deduct_ins_checked,
                             'count': len(_reports_p)}
        except ValueError:
            pass

    return render_template('personal_stats.html',
                           report_fields=REPORT_FIELDS,
                           default_prices=item_prices,
                           totals_result=totals_result,
                           salary_result=salary_result,
                           ytd_retention=ytd_retention,
                           now_year=date.today().year,
                           stats_start=stats_start, stats_end=stats_end,
                           stats_confirm=stats_confirm,
                           salary_start=salary_start, salary_end=salary_end,
                           deduct_ins_checked=deduct_ins_checked,
                           my_insurance=current_user.insurance_deduction,
                           my_tax_exempt=current_user.tax_exempt,
                           tax_rate=get_tax_rate())


# ---------------------------------------------------------------------------
# Ledger (公司流水帳 + 憑證上傳) — ADMIN only
# ---------------------------------------------------------------------------

LEDGER_CATEGORIES = ['材料費', '人工費', '雜支', '設備費', '運費', '其他']


@app.route('/ledger')
@login_required
@admin_required
def ledger():
    page        = request.args.get('page', 1, type=int)
    f_start     = request.args.get('start_date', '')
    f_end       = request.args.get('end_date', '')
    f_type      = request.args.get('entry_type', '')
    f_category  = request.args.get('category', '')

    q = LedgerEntry.query
    if f_start:
        try:
            q = q.filter(LedgerEntry.entry_date >= date.fromisoformat(f_start))
        except ValueError:
            pass
    if f_end:
        try:
            q = q.filter(LedgerEntry.entry_date <= date.fromisoformat(f_end))
        except ValueError:
            pass
    if f_type in ('INCOME', 'EXPENSE'):
        q = q.filter(LedgerEntry.entry_type == f_type)
    if f_category:
        q = q.filter(LedgerEntry.category == f_category)

    pagination  = q.order_by(LedgerEntry.entry_date.desc(), LedgerEntry.id.desc()).paginate(
        page=page, per_page=20, error_out=False)
    entries     = pagination.items

    total_income  = db.session.query(db.func.sum(LedgerEntry.amount)).filter(
        LedgerEntry.entry_type == 'INCOME').scalar() or 0
    total_expense = db.session.query(db.func.sum(LedgerEntry.amount)).filter(
        LedgerEntry.entry_type == 'EXPENSE').scalar() or 0

    url_args  = {k: v for k, v in request.args.items() if k != 'page'}
    users_dict = {u.id: u.display_name for u in User.query.all()}
    return render_template('ledger.html',
                           pagination=pagination, entries=entries,
                           total_income=total_income, total_expense=total_expense,
                           categories=LEDGER_CATEGORIES,
                           f_start=f_start, f_end=f_end,
                           f_type=f_type, f_category=f_category,
                           url_args=url_args,
                           users_dict=users_dict,
                           r2_enabled=bool(_r2_client))


@app.route('/ledger/add', methods=['POST'])
@login_required
@admin_required
def ledger_add():
    entry_date  = request.form.get('entry_date', '').strip()
    description = request.form.get('description', '').strip()
    amount_str  = request.form.get('amount', '').strip()
    entry_type  = request.form.get('entry_type', '').strip()
    category    = request.form.get('category', '').strip()
    note        = request.form.get('note', '').strip()[:100]

    if not entry_date or not description or not amount_str or entry_type not in ('INCOME', 'EXPENSE'):
        flash('必填欄位不完整', 'danger')
        return redirect(url_for('ledger'))
    try:
        amount = int(amount_str)
        if amount <= 0:
            raise ValueError
    except ValueError:
        flash('金額必須為正整數', 'danger')
        return redirect(url_for('ledger'))

    receipt_key  = None
    receipt_name = None
    receipt_file = request.files.get('receipt')
    if receipt_file and receipt_file.filename:
        if receipt_file.content_type not in ALLOWED_RECEIPT_TYPES:
            flash('憑證格式不支援（僅接受 PDF / JPG / PNG / WebP）', 'danger')
            return redirect(url_for('ledger'))
        data = receipt_file.read()
        if len(data) > MAX_RECEIPT_BYTES:
            flash('憑證檔案超過 10MB 上限', 'danger')
            return redirect(url_for('ledger'))
        if not _r2_client:
            flash('R2 儲存未設定，無法上傳憑證，請聯繫管理員', 'warning')
        else:
            import uuid
            ext = receipt_file.filename.rsplit('.', 1)[-1].lower() if '.' in receipt_file.filename else 'bin'
            receipt_key = f'receipts/{entry_date}/{uuid.uuid4().hex}.{ext}'
            receipt_name = receipt_file.filename
            ct = receipt_file.content_type
            try:
                _r2_upload(io.BytesIO(data), receipt_key, ct)
            except Exception as e:
                app.logger.error(f'R2 upload failed: {e}')
                flash('憑證上傳失敗，記錄仍已儲存（無附件）', 'warning')
                receipt_key = None
                receipt_name = None

    entry = LedgerEntry(
        entry_date=date.fromisoformat(entry_date),
        description=description,
        amount=amount,
        entry_type=entry_type,
        category=category or None,
        note=note or None,
        receipt_key=receipt_key,
        receipt_name=receipt_name,
        created_by=current_user.id,
    )
    db.session.add(entry)
    db.session.commit()
    add_audit(current_user.id, 'LEDGER_ADD', f'新增流水帳「{description}」{entry_type} {amount}元')
    flash('記錄已新增', 'success')
    return redirect(url_for('ledger'))


@app.route('/ledger/<int:entry_id>/edit', methods=['POST'])
@login_required
@admin_required
def ledger_edit(entry_id):
    entry = LedgerEntry.query.get_or_404(entry_id)

    entry_date  = request.form.get('entry_date', '').strip()
    description = request.form.get('description', '').strip()
    amount_str  = request.form.get('amount', '').strip()
    entry_type  = request.form.get('entry_type', '').strip()
    category    = request.form.get('category', '').strip()
    note        = request.form.get('note', '').strip()[:100]

    if not entry_date or not description or not amount_str or entry_type not in ('INCOME', 'EXPENSE'):
        flash('必填欄位不完整', 'danger')
        return redirect(url_for('ledger'))
    try:
        amount = int(amount_str)
        if amount <= 0:
            raise ValueError
    except ValueError:
        flash('金額必須為正整數', 'danger')
        return redirect(url_for('ledger'))

    receipt_file = request.files.get('receipt')
    if receipt_file and receipt_file.filename:
        if receipt_file.content_type not in ALLOWED_RECEIPT_TYPES:
            flash('憑證格式不支援', 'danger')
            return redirect(url_for('ledger'))
        data = receipt_file.read()
        if len(data) > MAX_RECEIPT_BYTES:
            flash('憑證檔案超過 10MB 上限', 'danger')
            return redirect(url_for('ledger'))
        if _r2_client:
            old_key = entry.receipt_key
            import uuid
            ext = receipt_file.filename.rsplit('.', 1)[-1].lower() if '.' in receipt_file.filename else 'bin'
            new_key = f'receipts/{entry_date}/{uuid.uuid4().hex}.{ext}'
            try:
                _r2_upload(io.BytesIO(data), new_key, receipt_file.content_type)
                if old_key:
                    _r2_delete(old_key)
                entry.receipt_key  = new_key
                entry.receipt_name = receipt_file.filename
            except Exception as e:
                app.logger.error(f'R2 upload failed during edit: {e}')
                flash('新憑證上傳失敗，保留原附件', 'warning')
        else:
            flash('R2 儲存未設定，無法更換憑證', 'warning')

    entry.entry_date  = date.fromisoformat(entry_date)
    entry.description = description
    entry.amount      = amount
    entry.entry_type  = entry_type
    entry.category    = category or None
    entry.note        = note or None
    entry.updated_at  = datetime.utcnow()
    db.session.commit()
    add_audit(current_user.id, 'LEDGER_EDIT', f'編輯流水帳 #{entry_id}「{description}」')
    flash('記錄已更新', 'success')
    return redirect(url_for('ledger'))


@app.route('/ledger/<int:entry_id>/delete', methods=['POST'])
@login_required
@admin_required
def ledger_delete(entry_id):
    entry = LedgerEntry.query.get_or_404(entry_id)
    if entry.receipt_key:
        _r2_delete(entry.receipt_key)
    desc = entry.description
    db.session.delete(entry)
    db.session.commit()
    add_audit(current_user.id, 'LEDGER_DELETE', f'刪除流水帳 #{entry_id}「{desc}」')
    flash('記錄已刪除', 'success')
    return redirect(url_for('ledger'))


@app.route('/ledger/<int:entry_id>/receipt')
@login_required
@admin_required
def ledger_receipt(entry_id):
    entry = LedgerEntry.query.get_or_404(entry_id)
    if not entry.receipt_key:
        flash('此記錄無附件', 'warning')
        return redirect(url_for('ledger'))
    if not _r2_client:
        flash('R2 儲存未設定', 'danger')
        return redirect(url_for('ledger'))
    url = _r2_presigned_url(entry.receipt_key, expiry=3600)
    if not url:
        flash('無法產生下載連結', 'danger')
        return redirect(url_for('ledger'))
    return redirect(url)


@app.route('/ledger/export')
@login_required
@admin_required
def ledger_export():
    f_start    = request.args.get('start_date', '')
    f_end      = request.args.get('end_date', '')
    f_type     = request.args.get('entry_type', '')
    f_category = request.args.get('category', '')

    q = LedgerEntry.query
    if f_start:
        try:
            q = q.filter(LedgerEntry.entry_date >= date.fromisoformat(f_start))
        except ValueError:
            pass
    if f_end:
        try:
            q = q.filter(LedgerEntry.entry_date <= date.fromisoformat(f_end))
        except ValueError:
            pass
    if f_type in ('INCOME', 'EXPENSE'):
        q = q.filter(LedgerEntry.entry_type == f_type)
    if f_category:
        q = q.filter(LedgerEntry.category == f_category)

    entries = q.order_by(LedgerEntry.entry_date.asc(), LedgerEntry.id.asc()).all()

    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '流水帳'

    headers = ['日期', '說明', '類型', '類別', '金額(NTD)', '備註', '有附件']
    ws.append(headers)
    hdr_font = Font(bold=True)
    hdr_fill = PatternFill('solid', fgColor='D9E1F2')
    for cell in ws[1]:
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal='center')

    type_label = {'INCOME': '收入', 'EXPENSE': '支出'}
    for e in entries:
        ws.append([
            e.entry_date.strftime('%Y-%m-%d'),
            e.description,
            type_label.get(e.entry_type, e.entry_type),
            e.category or '',
            e.amount,
            e.note or '',
            '是' if e.receipt_key else '否',
        ])

    ws.column_dimensions['A'].width = 12
    ws.column_dimensions['B'].width = 30
    ws.column_dimensions['C'].width = 8
    ws.column_dimensions['D'].width = 12
    ws.column_dimensions['E'].width = 12
    ws.column_dimensions['F'].width = 30
    ws.column_dimensions['G'].width = 8

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f'流水帳_{date.today().strftime("%Y%m%d")}.xlsx'
    return send_file(buf, as_attachment=True, download_name=fname,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ---------------------------------------------------------------------------
# Auto Report — 日報 / 月報生成、R2 儲存、管理員查閱
# ---------------------------------------------------------------------------

def _report_get_font():
    """取得可用的 CJK 字型名稱（reportlab）。"""
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    try:
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
        font = 'STSong-Light'
    except Exception:
        font = 'Helvetica'
    for fp in ['C:/Windows/Fonts/msjh.ttc', '/System/Library/Fonts/PingFang.ttc']:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont('CJK_RPT', fp))
                font = 'CJK_RPT'
                break
            except Exception:
                pass
    return font


def _report_excel(report_type, label, start_date, end_date,
                  users, reports, ledger_entries, materials, prices):
    """生成多 Sheet Excel，回傳 BytesIO。"""
    import openpyxl
    from openpyxl.styles import Font as XFont, PatternFill, Alignment

    HDR_FILL = PatternFill('solid', fgColor='4472C4')
    HDR_FONT = XFont(bold=True, color='FFFFFF')
    BOLD     = XFont(bold=True)
    ALT_FILL = PatternFill('solid', fgColor='EBF3FB')
    GRN_FILL = PatternFill('solid', fgColor='E2EFDA')
    RED_FONT = XFont(bold=True, color='C00000')
    GRN_FONT = XFont(bold=True, color='375623')

    def set_hdr(ws, row, cols):
        for ci, v in enumerate(cols, 1):
            c = ws.cell(row=row, column=ci, value=v)
            c.fill = HDR_FILL; c.font = HDR_FONT
            c.alignment = Alignment(horizontal='center')

    def auto_w(ws):
        for col in ws.columns:
            w = max((len(str(c.value or '')) for c in col), default=4)
            ws.column_dimensions[col[0].column_letter].width = min(w + 4, 40)

    wb = openpyxl.Workbook()
    udict = {u.id: u.display_name for u in users}

    # ── Sheet 1: 工項彙總 ───────────────────────────────────────────────
    ws1 = wb.active
    ws1.title = '工項彙總'
    span = chr(65 + len(REPORT_FIELDS) + 1)
    ws1.merge_cells(f'A1:{span}1')
    ws1['A1'] = f'{"日報" if report_type == "DAILY" else "月報"}　{label}　期間：{start_date} ～ {end_date}'
    ws1['A1'].font = XFont(bold=True, size=13)
    ws1['A1'].alignment = Alignment(horizontal='center')

    set_hdr(ws1, 2, ['帳戶'] + [lbl for _, lbl in REPORT_FIELDS] + ['合計'])

    user_totals = {}
    for r in reports:
        uid = r.user_id
        if uid not in user_totals:
            user_totals[uid] = {k: 0 for k, _ in REPORT_FIELDS}
        for k, _ in REPORT_FIELDS:
            user_totals[uid][k] += getattr(r, k, 0) or 0

    grand = {k: 0 for k, _ in REPORT_FIELDS}
    ri = 3
    for uid, tots in user_totals.items():
        row_sum = sum(tots.values())
        row_vals = [udict.get(uid, f'UID {uid}')] + [tots[k] for k, _ in REPORT_FIELDS] + [row_sum]
        for ci, v in enumerate(row_vals, 1):
            c = ws1.cell(ri, ci, v)
            if ri % 2 == 0: c.fill = ALT_FILL
            if ci > 1: c.alignment = Alignment(horizontal='center')
        for k, _ in REPORT_FIELDS:
            grand[k] += tots[k]
        ri += 1
    total_row = ['總計'] + [grand[k] for k, _ in REPORT_FIELDS] + [sum(grand.values())]
    for ci, v in enumerate(total_row, 1):
        c = ws1.cell(ri, ci, v); c.font = BOLD; c.fill = GRN_FILL
    auto_w(ws1)

    # ── Sheet 2: 流水帳 ─────────────────────────────────────────────────
    ws2 = wb.create_sheet('流水帳')
    set_hdr(ws2, 1, ['日期', '說明', '類型', '類別', '金額(NTD)', '備註', '建立者'])
    inc_total = exp_total = 0
    for ri2, e in enumerate(ledger_entries, 2):
        ws2.cell(ri2, 1, str(e.entry_date))
        ws2.cell(ri2, 2, e.description)
        ws2.cell(ri2, 3, '收入' if e.entry_type == 'INCOME' else '支出')
        ws2.cell(ri2, 4, e.category or '')
        ac = ws2.cell(ri2, 5, e.amount)
        ac.alignment = Alignment(horizontal='right')
        if e.entry_type == 'INCOME':
            ac.font = GRN_FONT; inc_total += e.amount
        else:
            ac.font = RED_FONT; exp_total += e.amount
        ws2.cell(ri2, 6, e.note or '')
        ws2.cell(ri2, 7, udict.get(e.created_by, '?'))
        if ri2 % 2 == 0:
            for ci in range(1, 8): ws2.cell(ri2, ci).fill = ALT_FILL
    sr = len(ledger_entries) + 2
    ws2.cell(sr, 1, '合計').font = BOLD
    ws2.cell(sr, 3, f'收入:{inc_total:,}  支出:{exp_total:,}  淨餘:{inc_total - exp_total:,}').font = BOLD
    for ci in range(1, 8): ws2.cell(sr, ci).fill = GRN_FILL
    auto_w(ws2)

    # ── Sheet 3: 材料庫存 ────────────────────────────────────────────────
    ws3 = wb.create_sheet('材料庫存')
    set_hdr(ws3, 1, ['#', '材料名稱', '單位', '剩餘數量'])
    for ri3, m in enumerate(materials, 2):
        ws3.cell(ri3, 1, ri3 - 1)
        ws3.cell(ri3, 2, m.name)
        ws3.cell(ri3, 3, m.unit)
        qc = ws3.cell(ri3, 4, m.remaining_quantity)
        qc.alignment = Alignment(horizontal='center')
        if m.remaining_quantity == 0: qc.font = RED_FONT
        if ri3 % 2 == 0:
            for ci in range(1, 5): ws3.cell(ri3, ci).fill = ALT_FILL
    auto_w(ws3)

    # ── Sheet 4: 薪資彙總（月報專屬）────────────────────────────────────
    if report_type == 'MONTHLY':
        ws4 = wb.create_sheet('薪資彙總')
        set_hdr(ws4, 1, ['帳戶', '發薪方式', '工作收入', '保留金(期間)', '勞健保', '稅務支出', '固定薪資', '實領金額'])
        tax_v = get_tax_rate()
        sal_ri = 2
        total_net = 0
        for u in users:
            tots = user_totals.get(u.id, {k: 0 for k, _ in REPORT_FIELDS})
            gross = sum(tots.get(k, 0) * prices.get(k, 0) for k, _ in REPORT_FIELDS)
            if gross == 0 and u.fixed_salary == 0:
                continue
            u_rates = get_user_all_retention_rates(u.id)
            ret_raw = sum(tots.get(f, 0) * u_rates[f] for f in RETENTION_FIELDS)
            retention = max(0.0, min(ret_raw, RETENTION_CAP))
            insurance = u.insurance_deduction
            not_enrolled = (u.insurance_deduction == 0 and not u.tax_exempt)
            tax = round(gross * tax_v / 100) if not_enrolled else 0
            net = int(gross - retention - insurance - tax + u.fixed_salary)
            total_net += net
            row_vals = [u.display_name, '領現' if u.payment_method == 'CASH' else '轉帳',
                        int(gross), int(retention), insurance, tax, u.fixed_salary, net]
            for ci, v in enumerate(row_vals, 1):
                c = ws4.cell(sal_ri, ci, v)
                if ci >= 3: c.alignment = Alignment(horizontal='right')
                if sal_ri % 2 == 0: c.fill = ALT_FILL
            sal_ri += 1
        ws4.cell(sal_ri, 1, '薪資支出合計').font = BOLD
        tc = ws4.cell(sal_ri, 8, total_net)
        tc.font = BOLD; tc.alignment = Alignment(horizontal='right')
        for ci in range(1, 9): ws4.cell(sal_ri, ci).fill = GRN_FILL
        auto_w(ws4)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _report_pdf(report_type, label, start_date, end_date,
                users, reports, ledger_entries, materials, prices):
    """生成多頁 PDF，回傳 BytesIO。"""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors as rl_colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import ParagraphStyle

    fn = _report_get_font()

    def sty(name, **kw):
        kw.setdefault('fontName', fn)
        kw.setdefault('fontSize', 9)
        kw.setdefault('leading', 14)
        return ParagraphStyle(name, **kw)

    C_HDR  = rl_colors.HexColor('#4472C4')
    C_ALT  = rl_colors.HexColor('#EBF3FB')
    C_GRN  = rl_colors.HexColor('#E2EFDA')
    C_RED  = rl_colors.HexColor('#C00000')
    C_DGRN = rl_colors.HexColor('#375623')
    WHITE  = rl_colors.white

    def mk_table(data, col_widths=None):
        t = Table(data, colWidths=col_widths, repeatRows=1)
        n = len(data)
        style_cmds = [
            ('FONTNAME',    (0, 0), (-1, -1), fn),
            ('FONTSIZE',    (0, 0), (-1, -1), 8),
            ('BACKGROUND',  (0, 0), (-1, 0),  C_HDR),
            ('TEXTCOLOR',   (0, 0), (-1, 0),  WHITE),
            ('FONTNAME',    (0, 0), (-1, 0),  fn),
            ('FONTSIZE',    (0, 0), (-1, 0),  9),
            ('ALIGN',       (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',      (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID',        (0, 0), (-1, -1), 0.4, rl_colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, C_ALT]),
            ('BACKGROUND',  (0, n-1), (-1, n-1), C_GRN),
            ('FONTNAME',    (0, n-1), (-1, n-1), fn),
        ]
        t.setStyle(TableStyle(style_cmds))
        return t

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=24, rightMargin=24,
                            topMargin=24, bottomMargin=24)
    story = []
    title_sty = sty('T', fontSize=14, alignment=1, spaceAfter=10, fontName=fn)
    h2_sty    = sty('H2', fontSize=11, spaceBefore=10, spaceAfter=4, fontName=fn)
    udict = {u.id: u.display_name for u in users}

    # ── 工項彙總 ─────────────────────────────────────────────────────────
    story.append(Paragraph(
        f'{"日報" if report_type == "DAILY" else "月報"}　{label}　{start_date} ～ {end_date}',
        title_sty))
    story.append(Paragraph('工項彙總', h2_sty))

    user_totals = {}
    for r in reports:
        uid = r.user_id
        if uid not in user_totals:
            user_totals[uid] = {k: 0 for k, _ in REPORT_FIELDS}
        for k, _ in REPORT_FIELDS:
            user_totals[uid][k] += getattr(r, k, 0) or 0

    grand = {k: 0 for k, _ in REPORT_FIELDS}
    hdr = ['帳戶'] + [lbl for _, lbl in REPORT_FIELDS] + ['合計']
    rows = [hdr]
    for uid, tots in user_totals.items():
        rows.append([udict.get(uid, f'UID{uid}')] +
                    [tots[k] for k, _ in REPORT_FIELDS] +
                    [sum(tots.values())])
        for k, _ in REPORT_FIELDS:
            grand[k] += tots[k]
    rows.append(['總計'] + [grand[k] for k, _ in REPORT_FIELDS] + [sum(grand.values())])
    story.append(mk_table(rows))

    # ── 流水帳 ───────────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph('流水帳', h2_sty))
    inc_t = exp_t = 0
    l_rows = [['日期', '說明', '類型', '類別', '金額(NTD)', '備註', '建立者']]
    for e in ledger_entries:
        t_lbl = '收入' if e.entry_type == 'INCOME' else '支出'
        l_rows.append([str(e.entry_date), e.description, t_lbl,
                       e.category or '', f'{e.amount:,}', e.note or '',
                       udict.get(e.created_by, '?')])
        if e.entry_type == 'INCOME': inc_t += e.amount
        else: exp_t += e.amount
    l_rows.append(['合計', '', f'收入:{inc_t:,}  支出:{exp_t:,}  淨餘:{inc_t - exp_t:,}',
                   '', '', '', ''])
    story.append(mk_table(l_rows, col_widths=[65, 130, 38, 52, 65, 130, 60]))

    # ── 材料庫存 ─────────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph('材料庫存', h2_sty))
    m_rows = [['#', '材料名稱', '單位', '剩餘數量']]
    for i, m in enumerate(materials, 1):
        m_rows.append([i, m.name, m.unit, m.remaining_quantity])
    m_rows.append(['', f'共 {len(materials)} 項材料', '', ''])
    story.append(mk_table(m_rows, col_widths=[30, 200, 60, 80]))

    # ── 薪資彙總（月報）───────────────────────────────────────────────────
    if report_type == 'MONTHLY':
        story.append(PageBreak())
        story.append(Paragraph('薪資彙總', h2_sty))
        tax_v = get_tax_rate()
        s_rows = [['帳戶', '發薪方式', '工作收入', '保留金', '勞健保', '稅務支出', '固定薪資', '實領金額']]
        total_net = 0
        for u in users:
            tots = user_totals.get(u.id, {k: 0 for k, _ in REPORT_FIELDS})
            gross = sum(tots.get(k, 0) * prices.get(k, 0) for k, _ in REPORT_FIELDS)
            if gross == 0 and u.fixed_salary == 0:
                continue
            u_rates = get_user_all_retention_rates(u.id)
            ret_raw = sum(tots.get(f, 0) * u_rates[f] for f in RETENTION_FIELDS)
            retention = max(0.0, min(ret_raw, RETENTION_CAP))
            insurance = u.insurance_deduction
            not_enrolled = (u.insurance_deduction == 0 and not u.tax_exempt)
            tax = round(gross * tax_v / 100) if not_enrolled else 0
            net = int(gross - retention - insurance - tax + u.fixed_salary)
            total_net += net
            s_rows.append([u.display_name,
                           '領現' if u.payment_method == 'CASH' else '轉帳',
                           f'{int(gross):,}', f'{int(retention):,}',
                           f'{insurance:,}', f'{tax:,}',
                           f'{u.fixed_salary:,}', f'{net:,}'])
        s_rows.append(['薪資支出合計', '', '', '', '', '', '', f'{total_net:,}'])
        story.append(mk_table(s_rows))

    doc.build(story)
    buf.seek(0)
    return buf


def _run_auto_report(report_type: str, target_date):
    """生成日報或月報並上傳至 R2，記錄於 ReportArchive。"""
    try:
        # 避免重複生成
        existing = ReportArchive.query.filter_by(
            report_type=report_type, report_date=target_date).first()
        if existing:
            app.logger.info(f'Report {report_type} {target_date} already exists, skipping')
            return

        if report_type == 'DAILY':
            start_date = end_date = target_date
            label = target_date.strftime('%Y-%m-%d')
        else:
            start_date = target_date.replace(day=1)
            end_date   = target_date
            label      = target_date.strftime('%Y-%m')

        users    = User.query.order_by(User.id).all()
        reports  = (Report.query
                    .filter(Report.report_date >= start_date,
                            Report.report_date <= end_date,
                            Report.is_confirmed == True)
                    .all())
        ledger   = (LedgerEntry.query
                    .filter(LedgerEntry.entry_date >= start_date,
                            LedgerEntry.entry_date <= end_date)
                    .order_by(LedgerEntry.entry_date.asc()).all())
        materials = Material.query.order_by(Material.sort_order.asc()).all()
        prices    = get_item_prices()

        excel_buf = _report_excel(report_type, label, start_date, end_date,
                                  users, reports, ledger, materials, prices)
        pdf_buf   = _report_pdf(report_type, label, start_date, end_date,
                                users, reports, ledger, materials, prices)

        r2_excel = r2_pdf = None
        if _r2_client:
            prefix = 'reports/daily' if report_type == 'DAILY' else 'reports/monthly'
            r2_excel = f'{prefix}/{label}.xlsx'
            r2_pdf   = f'{prefix}/{label}.pdf'
            _r2_upload(excel_buf, r2_excel,
                       'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            _r2_upload(pdf_buf, r2_pdf, 'application/pdf')
        else:
            app.logger.warning('R2 not configured — report generated but not uploaded')

        archive = ReportArchive(
            report_type=report_type,
            report_date=target_date,
            period_start=start_date,
            period_end=end_date,
            r2_key_excel=r2_excel,
            r2_key_pdf=r2_pdf,
        )
        db.session.add(archive)

        admin = User.query.filter_by(role='ADMIN').first()
        if admin:
            add_audit(admin.id, 'AUTO_REPORT',
                      f'自動生成{"日報" if report_type == "DAILY" else "月報"} {label}')
        db.session.commit()
        app.logger.info(f'Auto report {report_type} {label} generated OK')
    except Exception as exc:
        app.logger.error(f'Auto report {report_type} {target_date} failed: {exc}')
        try:
            db.session.rollback()
        except Exception:
            pass


# ── 排程器（每天 23:59 日報；每月末 23:59 月報）────────────────────────
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    _scheduler = BackgroundScheduler(timezone='Asia/Taipei')

    def _daily_job():
        with app.app_context():
            _run_auto_report('DAILY', date.today())

    def _monthly_job():
        with app.app_context():
            _run_auto_report('MONTHLY', date.today())

    _scheduler.add_job(_daily_job,   CronTrigger(hour=23, minute=59, second=0,
                                                  timezone='Asia/Taipei'))
    _scheduler.add_job(_monthly_job, CronTrigger(day='last', hour=23, minute=59, second=30,
                                                  timezone='Asia/Taipei'))
    if not _scheduler.running:
        _scheduler.start()
except Exception as _e_sched:
    import logging as _log_sched
    _log_sched.warning(f'APScheduler init failed: {_e_sched}')


# ── 管理員路由：報表檔案庫 ──────────────────────────────────────────────

@app.route('/reports/archives')
@login_required
@admin_required
def report_archives():
    page = request.args.get('page', 1, type=int)
    f_type = request.args.get('report_type', '')
    q = ReportArchive.query
    if f_type in ('DAILY', 'MONTHLY'):
        q = q.filter(ReportArchive.report_type == f_type)
    pagination = q.order_by(ReportArchive.report_date.desc(),
                             ReportArchive.id.desc()).paginate(
        page=page, per_page=30, error_out=False)
    url_args = {k: v for k, v in request.args.items() if k != 'page'}
    return render_template('report_archives.html',
                           pagination=pagination,
                           entries=pagination.items,
                           f_type=f_type,
                           url_args=url_args)


@app.route('/reports/archives/<int:archive_id>/<fmt>')
@login_required
@admin_required
def report_archive_download(archive_id, fmt):
    if fmt not in ('excel', 'pdf'):
        abort(404)
    arc = ReportArchive.query.get_or_404(archive_id)
    r2_key = arc.r2_key_excel if fmt == 'excel' else arc.r2_key_pdf
    if not r2_key:
        flash('此報表無對應檔案（可能 R2 未設定）', 'warning')
        return redirect(url_for('report_archives'))
    if not _r2_client:
        flash('R2 儲存未設定', 'danger')
        return redirect(url_for('report_archives'))
    url = _r2_presigned_url(r2_key, expiry=1800)
    if not url:
        flash('無法產生下載連結', 'danger')
        return redirect(url_for('report_archives'))
    return redirect(url)


@app.route('/admin/manual-report', methods=['POST'])
@login_required
@admin_required
def manual_report():
    """手動觸發報表生成（測試用）。"""
    rtype = request.form.get('report_type', 'DAILY')
    rdate_str = request.form.get('report_date', '')
    if rtype not in ('DAILY', 'MONTHLY'):
        flash('無效的報表類型', 'danger')
        return redirect(url_for('report_archives'))
    try:
        rdate = date.fromisoformat(rdate_str) if rdate_str else date.today()
    except ValueError:
        flash('日期格式錯誤', 'danger')
        return redirect(url_for('report_archives'))

    # 若已存在則先刪除（允許重新生成）
    existing = ReportArchive.query.filter_by(report_type=rtype, report_date=rdate).first()
    if existing:
        if existing.r2_key_excel: _r2_delete(existing.r2_key_excel)
        if existing.r2_key_pdf:   _r2_delete(existing.r2_key_pdf)
        db.session.delete(existing)
        db.session.commit()

    _run_auto_report(rtype, rdate)
    flash(f'{"日報" if rtype == "DAILY" else "月報"} {rdate} 已重新生成', 'success')
    return redirect(url_for('report_archives'))


# ---------------------------------------------------------------------------
# Error pages
# ---------------------------------------------------------------------------

@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', code=403, message='您沒有權限存取此頁面'), 403


@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, message='頁面不存在'), 404


# ---------------------------------------------------------------------------
# One-time Migration: encrypt existing plaintext bank accounts
# (Remove this route after migration is confirmed complete)
# ---------------------------------------------------------------------------

@app.route('/admin/migrate-bank-encrypt')
@admin_required
def migrate_bank_encrypt():
    import traceback
    try:
        fernet_status = f'_fernet={_fernet!r}'
        if not _fernet:
            return f'BANK_ENCRYPT_KEY 未設定或無效，無法加密。狀態: {fernet_status}', 400
        users = User.query.filter(User.bank_account.isnot(None)).all()
        migrated = 0
        skipped = 0
        errors = []
        for u in users:
            acct = u.bank_account
            if not acct:
                continue
            try:
                _fernet.decrypt(acct.encode())
                skipped += 1
            except Exception:
                try:
                    u.bank_account = encrypt_bank(acct)
                    migrated += 1
                except Exception as e2:
                    errors.append(f'user {u.id}: {e2}')
        db.session.commit()
        msg = f'遷移完成：加密 {migrated} 筆，已加密略過 {skipped} 筆'
        if errors:
            msg += f'\n錯誤: {errors}'
        return msg, 200
    except Exception:
        return f'Migration error:\n{traceback.format_exc()}', 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
