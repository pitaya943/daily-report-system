import io
import os
from datetime import datetime, date, timedelta
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, send_file, abort)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, User, Report, Material, MaterialRequest, AuditLog, SystemConfig, UserRetentionRate

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'daily-report-secret-2026-yc-local')

_db_url = os.environ.get('DATABASE_URL', 'sqlite:///daily_report.db')
# Supabase / Railway may return "postgres://" which SQLAlchemy 1.4+ rejects
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

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
    # Seed / correct default SystemConfig entries
    try:
        for _key, _default in [('retention_rate', '20'), ('tax_rate', '3')]:
            cfg = db.session.get(SystemConfig, _key)
            if not cfg:
                db.session.add(SystemConfig(key=_key, value=_default))
            elif _key == 'tax_rate' and cfg.value == '5':
                # 舊預設值 5% → 修正為 3%
                cfg.value = '3'
        db.session.commit()
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
    users_dict = {u.id: u for u in User.query.all()}
    all_users = User.query.all() if current_user.role == 'ADMIN' else []
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

    new_vals = parse_report_values(request.form)
    diff = report_diff(r, new_vals)
    was_confirmed = r.is_confirmed

    for key, _ in REPORT_FIELDS:
        setattr(r, key, new_vals[key])
    r.updated_at = datetime.utcnow()

    if was_confirmed:
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
    all_users = User.query.order_by(User.created_at).all() if current_user.role == 'ADMIN' else []
    ytd_by_user = {u.id: get_ytd_retention(u.id) for u in all_users}

    # 批次載入各帳戶客製保留金費率，供 Modal 使用
    global_rate = int(get_retention_rate())
    uid_list = [u.id for u in all_users]
    all_custom = (UserRetentionRate.query
                  .filter(UserRetentionRate.user_id.in_(uid_list)).all()
                  if uid_list else [])
    custom_map = {}
    for cr in all_custom:
        custom_map.setdefault(cr.user_id, {})[cr.field] = cr.rate
    user_ret_rates = {
        u.id: {
            'rates': {f: custom_map.get(u.id, {}).get(f, global_rate) for f in RETENTION_FIELDS},
            'is_custom': bool(custom_map.get(u.id))
        }
        for u in all_users
    }

    return render_template('settings.html', all_users=all_users,
                           retention_rate=global_rate,
                           tax_rate=get_tax_rate(),
                           ytd_by_user=ytd_by_user,
                           user_ret_rates=user_ret_rates,
                           retention_fields_labeled=RETENTION_FIELDS_LABELED)


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
        payment_method = request.form.get('payment_method', 'TRANSFER')
        if payment_method not in ('CASH', 'TRANSFER'):
            payment_method = 'TRANSFER'
        u = User(display_name=display_name,
                 password_hash=generate_password_hash(password),
                 role=role, is_active=True,
                 payment_method=payment_method)
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
    method = request.form.get('payment_method', 'TRANSFER')
    if method not in ('CASH', 'TRANSFER'):
        method = 'TRANSFER'
    old = target.payment_method
    target.payment_method = method
    target.updated_at = datetime.utcnow()
    label = '領現' if method == 'CASH' else '轉帳'
    add_audit(current_user.id, 'ACCOUNT_UPDATE',
              f'更新「{target.display_name}」發薪方式：{old} → {method}')
    db.session.commit()
    flash(f'「{target.display_name}」發薪方式已更新為「{label}」', 'success')
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
        Report.query.filter_by(user_id=user_id).delete()
        MaterialRequest.query.filter_by(user_id=user_id).delete()
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
    pending_pagination = (Report.query
                          .filter(Report.is_confirmed == False, Report.is_rejected == False)
                          .order_by(Report.report_date.asc(), Report.id.asc())
                          .paginate(page=page, per_page=20, error_out=False))
    pending_materials = (MaterialRequest.query.filter_by(status='PENDING')
                         .order_by(MaterialRequest.created_at.asc()).all())
    users_dict = {u.id: u for u in User.query.all()}
    materials_dict = {m.id: m for m in Material.query.all()}
    url_args = {k: v for k, v in request.args.items() if k != 'page'}

    return render_template('confirmation.html',
                           pending_pagination=pending_pagination,
                           pending_reports=pending_pagination.items,
                           pending_materials=pending_materials,
                           users_dict=users_dict,
                           materials_dict=materials_dict,
                           report_fields=REPORT_FIELDS,
                           url_args=url_args)


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
    users_dict = {u.id: u for u in User.query.all()}
    all_users = User.query.order_by(User.display_name).all() if current_user.role == 'ADMIN' else []
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
    form_data = {'prices': {k: DEFAULT_PRICES.get(k, 0.0) for k, _ in REPORT_FIELDS},
                 'is_25th_payday': False}

    if request.method == 'POST':
        action = request.form.get('action', 'calculate')
        start_str = request.form.get('start_date', '')
        end_str = request.form.get('end_date', '')

        prices = {}
        for key, _ in REPORT_FIELDS:
            try:
                prices[key] = max(0.0, float(request.form.get(f'price_{key}', 0)))
            except (ValueError, TypeError):
                prices[key] = 0.0

        # 25號發薪才扣勞健保
        is_25th_payday = request.form.get('is_25th_payday') == '1'

        form_data = {'start_date': start_str, 'end_date': end_str,
                     'prices': prices, 'is_25th_payday': is_25th_payday}

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

            # 本期前已確認回報，用於計算保留金上限 (Jan 1 ~ period_start - 1 day)
            year_start = date(sd.year, 1, 1)
            pre_reports = Report.query.filter(
                Report.is_confirmed == True,
                Report.report_date >= year_start,
                Report.report_date < sd
            ).all()
            pre_ret_by_user = {}
            for pr in pre_reports:
                uid = pr.user_id
                if uid not in pre_ret_by_user:
                    pre_ret_by_user[uid] = {f: 0 for f in RETENTION_FIELDS}
                for f in RETENTION_FIELDS:
                    pre_ret_by_user[uid][f] += getattr(pr, f, 0)

            users_dict = {u.id: u for u in User.query.all()}
            user_data = {}
            for r in reports:
                uid = r.user_id
                if uid not in user_data:
                    uname = users_dict[uid].display_name if uid in users_dict else '(已刪除)'
                    user_data[uid] = {'username': uname,
                                      'totals': {k: 0 for k, _ in REPORT_FIELDS}}
                for k, _ in REPORT_FIELDS:
                    user_data[uid]['totals'][k] += getattr(r, k, 0)

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
                data['ytd_retention'] = get_ytd_retention(uid)
                data['payment_method'] = u.payment_method if u else 'TRANSFER'

                # 勞健保：只在 25 號發薪時扣，且帳戶需已投保
                ins = (u.insurance_deduction if u and u.insurance_deduction > 0 else 0) if is_25th_payday else 0
                data['insurance_deduction'] = ins

                # 稅務支出：未投保且未設免稅者
                not_enrolled = (u.insurance_deduction == 0 and not u.tax_exempt) if u else True
                data['tax_deduction'] = round(data['gross_salary'] * tax_rate / 100) if not_enrolled else 0
                data['final_salary'] = data['net_salary'] - ins - data['tax_deduction']

            grand_gross = sum(d['gross_salary'] for d in user_data.values())
            grand_period_retention = sum(d['period_retention'] for d in user_data.values())
            grand_ytd_retention = sum(d['ytd_retention'] for d in user_data.values())
            grand_insurance = sum(d['insurance_deduction'] for d in user_data.values())
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
                              'grand_tax': grand_tax,
                              'tax_rate': tax_rate,
                              'is_25th_payday': is_25th_payday,
                              'transfer_total': transfer_total,
                              'cash_total': cash_total,
                              'cash_bills': cash_bills,
                              'prices': prices}

            if action == 'export-excel':
                return _export_salary_excel(salary_results)
            elif action == 'export-pdf':
                return _export_salary_pdf(salary_results)

    return render_template('salary.html', report_fields=REPORT_FIELDS,
                           salary_results=salary_results, form_data=form_data,
                           all_active_users=all_active_users,
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
        ins_d = data.get('insurance_deduction', 0)
        if ins_d > 0:
            tdata.append(['勞健保扣除', '', '', f'-{ins_d:,.0f}'])
        tdata.append(['本期實領金額', '', '', f'{data["final_salary"]:,.0f}'])

        subtotal_row = 1 + n_fields
        retention_row = subtotal_row + 1
        extra = 1 if ins_d > 0 else 0
        ins_row = retention_row + 1 if ins_d > 0 else None
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


# ---------------------------------------------------------------------------
# Page 9: Personal Statistics (USER and ADMIN)
# ---------------------------------------------------------------------------

@app.route('/personal-stats', methods=['GET', 'POST'])
@login_required
def personal_stats():
    totals_result = None
    salary_result = None
    form = request.form if request.method == 'POST' else {}
    action = form.get('action', '')

    stats_start = form.get('stats_start', '')
    stats_end = form.get('stats_end', '')
    stats_confirm = form.get('stats_confirm', 'all')
    salary_start = form.get('salary_start', '')
    salary_end = form.get('salary_end', '')

    # 今年度累積保留金（固定顯示，已確認回報）
    ytd_retention = get_ytd_retention(current_user.id)
    # 此帳戶的客製保留金費率（stats / salary 兩個 action 共用）
    my_ret_rates = get_user_all_retention_rates(current_user.id)

    if action == 'stats' and stats_start and stats_end:
        q = Report.query.filter(
            Report.user_id == current_user.id,
            Report.report_date >= date.fromisoformat(stats_start),
            Report.report_date <= date.fromisoformat(stats_end)
        )
        if stats_confirm == 'confirmed':
            q = q.filter_by(is_confirmed=True)
        elif stats_confirm == 'unconfirmed':
            q = q.filter_by(is_confirmed=False)
        reports = q.all()
        totals = {k: 0 for k, _ in REPORT_FIELDS}
        for r in reports:
            for k, _ in REPORT_FIELDS:
                totals[k] += getattr(r, k, 0)
        period_retention = sum(totals.get(f, 0) * my_ret_rates[f] for f in RETENTION_FIELDS)
        totals_result = {'start': stats_start, 'end': stats_end,
                         'confirm_filter': stats_confirm,
                         'totals': totals, 'count': len(reports),
                         'period_retention': period_retention}

    elif action == 'salary' and salary_start and salary_end:
        prices = {}
        for k, _ in REPORT_FIELDS:
            try:
                prices[k] = max(0.0, float(form.get(f'price_{k}', 0)))
            except (ValueError, TypeError):
                prices[k] = 0.0

        deduct_ins = form.get('deduct_insurance') == '1'

        sd_ps = date.fromisoformat(salary_start)
        reports = Report.query.filter(
            Report.user_id == current_user.id,
            Report.is_confirmed == True,
            Report.report_date >= sd_ps,
            Report.report_date <= date.fromisoformat(salary_end)
        ).all()

        totals = {k: 0 for k, _ in REPORT_FIELDS}
        for r in reports:
            for k, _ in REPORT_FIELDS:
                totals[k] += getattr(r, k, 0)

        subtotals = {k: totals[k] * prices.get(k, 0) for k, _ in REPORT_FIELDS}
        grand_total = sum(subtotals.values())

        # 保留金上限邏輯
        year_start = date(sd_ps.year, 1, 1)
        pre_reports = Report.query.filter(
            Report.user_id == current_user.id,
            Report.is_confirmed == True,
            Report.report_date >= year_start,
            Report.report_date < sd_ps
        ).all()
        pre_totals = {f: sum(getattr(r, f, 0) for r in pre_reports) for f in RETENTION_FIELDS}
        pre_calc = sum(pre_totals.get(f, 0) * my_ret_rates[f] for f in RETENTION_FIELDS)
        ytd_before = min(RETENTION_CAP, max(0.0, pre_calc + current_user.retention_offset))
        period_ret_raw = sum(totals.get(f, 0) * my_ret_rates[f] for f in RETENTION_FIELDS)
        period_retention = max(0.0, min(period_ret_raw, RETENTION_CAP - ytd_before))

        ins_amount = current_user.insurance_deduction if deduct_ins else 0
        not_enrolled = (current_user.insurance_deduction == 0 and not current_user.tax_exempt)
        tax_rate = get_tax_rate()
        tax_amount = round(grand_total * tax_rate / 100) if not_enrolled else 0
        salary_result = {'start': salary_start, 'end': salary_end,
                         'totals': totals, 'prices': prices,
                         'subtotals': subtotals,
                         'grand_total': grand_total,
                         'period_retention': period_retention,
                         'insurance_deduction': ins_amount,
                         'tax_deduction': tax_amount,
                         'tax_rate': tax_rate,
                         'not_enrolled': not_enrolled,
                         'final_salary': grand_total - period_retention - ins_amount - tax_amount,
                         'deduct_insurance': deduct_ins,
                         'count': len(reports)}

    return render_template('personal_stats.html',
                           report_fields=REPORT_FIELDS,
                           default_prices=DEFAULT_PRICES,
                           totals_result=totals_result,
                           salary_result=salary_result,
                           ytd_retention=ytd_retention,
                           now_year=date.today().year,
                           stats_start=stats_start, stats_end=stats_end,
                           stats_confirm=stats_confirm,
                           salary_start=salary_start, salary_end=salary_end,
                           my_insurance=current_user.insurance_deduction)


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
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
