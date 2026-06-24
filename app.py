import io
import os
from datetime import datetime, date
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, send_file, abort)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, User, Report, Material, MaterialRequest, AuditLog

app = Flask(__name__)
app.config['SECRET_KEY'] = 'daily-report-secret-2026-yc'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///daily_report.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

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
    ('direct_13',           '直總-13'),
    ('direct_20',           '直總-20'),
    ('direct_25',           '直總-25'),
    ('direct_40',           '直總-40'),
    ('indirect_13',         '間接-13'),
    ('indirect_20',         '間接-20'),
    ('indirect_25',         '間接-25'),
    ('indirect_40',         '間接-40'),
    ('direct_special_group',   '直總—整組、拆泥、換由令(含表)'),
    ('indirect_special_group', '間接—拆泥、換由令(含表)'),
    ('downsize',            '大改小(不含表)'),
    ('original_downsize',   '原大改小(不含表)'),
    ('special',             '特殊'),
    ('mobilization',        '動員'),
    ('recheck',             '複查案'),
    ('soil_clearing',       '清土'),
]


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
        return redirect(url_for('summary') if current_user.role == 'ADMIN' else url_for('report'))
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
            return redirect(url_for('summary') if user.role == 'ADMIN' else url_for('report'))
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

    reports = q.order_by(Report.report_date.desc(), Report.created_at.desc()).all()
    users_dict = {u.id: u for u in User.query.all()}
    all_users = User.query.all() if current_user.role == 'ADMIN' else []

    return render_template('history.html',
                           reports=reports,
                           users_dict=users_dict,
                           all_users=all_users,
                           report_fields=REPORT_FIELDS,
                           start_date=start_date,
                           end_date=end_date,
                           selected_user_id=selected_user_id)


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
    return render_template('settings.html', all_users=all_users)


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

    if not display_name or not password:
        flash('名稱和密碼不能為空', 'danger')
    elif role not in ('ADMIN', 'USER'):
        flash('無效的角色', 'danger')
    elif User.query.filter_by(display_name=display_name).first():
        flash(f'名稱「{display_name}」已存在', 'danger')
    elif len(password) < 4:
        flash('密碼至少需要 4 個字元', 'danger')
    else:
        u = User(display_name=display_name,
                 password_hash=generate_password_hash(password),
                 role=role, is_active=True)
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


@app.route('/settings/users/<int:user_id>/password', methods=['POST'])
@admin_required
def settings_reset_password(user_id):
    target = db.session.get(User, user_id)
    if not target:
        abort(404)
    new_pw = request.form.get('new_password', '')
    if len(new_pw) < 4:
        flash('密碼至少需要 4 個字元', 'danger')
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
    all_materials = Material.query.order_by(Material.name).all()
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
        m = Material(name=name, unit=unit, remaining_quantity=qty)
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
        results = {'user_totals': user_totals, 'grand_total': grand,
                   'total_reports': len(reports)}

    return render_template('summary.html',
                           results=results,
                           all_users=all_users,
                           report_fields=REPORT_FIELDS,
                           selected_fields=selected_fields,
                           start_date=start_date,
                           end_date=end_date,
                           selected_user_id=selected_user_id,
                           confirm_filter=confirm_filter)


# ---------------------------------------------------------------------------
# Page 6: Confirmation (ADMIN)
# ---------------------------------------------------------------------------

@app.route('/confirmation')
@admin_required
def confirmation():
    pending_reports = (Report.query.filter_by(is_confirmed=False)
                       .order_by(Report.report_date.desc()).all())
    pending_materials = (MaterialRequest.query.filter_by(status='PENDING')
                         .order_by(MaterialRequest.created_at.desc()).all())
    users_dict = {u.id: u for u in User.query.all()}
    materials_dict = {m.id: m for m in Material.query.all()}

    return render_template('confirmation.html',
                           pending_reports=pending_reports,
                           pending_materials=pending_materials,
                           users_dict=users_dict,
                           materials_dict=materials_dict,
                           report_fields=REPORT_FIELDS)


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

    q = AuditLog.query
    if current_user.role == 'USER':
        q = q.filter_by(user_id=current_user.id)

    if start_date:
        q = q.filter(AuditLog.created_at >= datetime.fromisoformat(start_date))
    if end_date:
        q = q.filter(AuditLog.created_at <= datetime.fromisoformat(end_date + 'T23:59:59'))
    if action_type_filter:
        q = q.filter_by(action_type=action_type_filter)

    logs = q.order_by(AuditLog.created_at.desc()).limit(500).all()
    users_dict = {u.id: u for u in User.query.all()}
    all_action_types = [r[0] for r in db.session.query(AuditLog.action_type).distinct().all()]

    return render_template('audit.html',
                           logs=logs,
                           users_dict=users_dict,
                           all_action_types=all_action_types,
                           start_date=start_date,
                           end_date=end_date,
                           selected_action=action_type_filter)


# ---------------------------------------------------------------------------
# Page 8: Salary (ADMIN)
# ---------------------------------------------------------------------------

@app.route('/salary', methods=['GET', 'POST'])
@admin_required
def salary():
    salary_results = None
    form_data = {'prices': {k: 0.0 for k, _ in REPORT_FIELDS}}

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

        form_data = {'start_date': start_str, 'end_date': end_str, 'prices': prices}

        if start_str and end_str:
            try:
                sd = date.fromisoformat(start_str)
                ed = date.fromisoformat(end_str)
            except ValueError:
                flash('日期格式錯誤', 'danger')
                return render_template('salary.html', report_fields=REPORT_FIELDS,
                                       salary_results=None, form_data=form_data)

            reports = Report.query.filter(
                Report.is_confirmed == True,
                Report.report_date >= sd,
                Report.report_date <= ed
            ).all()

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

            for uid, data in user_data.items():
                subtotals = {k: data['totals'][k] * prices.get(k, 0) for k, _ in REPORT_FIELDS}
                data['subtotals'] = subtotals
                data['total_salary'] = sum(subtotals.values())

            grand = sum(d['total_salary'] for d in user_data.values())
            salary_results = {'start_date': start_str, 'end_date': end_str,
                              'user_data': user_data, 'grand_salary': grand, 'prices': prices}

            if action == 'export-excel':
                return _export_salary_excel(salary_results)
            elif action == 'export-pdf':
                return _export_salary_pdf(salary_results)

    return render_template('salary.html', report_fields=REPORT_FIELDS,
                           salary_results=salary_results, form_data=form_data)


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

    row = 3
    for uid, data in results['user_data'].items():
        ws.cell(row=row, column=1, value=f'帳戶：{data["username"]}').font = Font(bold=True, size=12)
        row += 1

        headers = ['工項', '只數', '單價 (NTD)', '小計 (NTD)']
        grey = PatternFill('solid', fgColor='4472C4')
        for c, h in enumerate(headers, 1):
            cell = ws.cell(row=row, column=c, value=h)
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = grey
            cell.alignment = Alignment(horizontal='center')
        row += 1

        for k, label in REPORT_FIELDS:
            ws.cell(row=row, column=1, value=label)
            ws.cell(row=row, column=2, value=data['totals'][k])
            ws.cell(row=row, column=3, value=results['prices'].get(k, 0))
            ws.cell(row=row, column=4, value=round(data['subtotals'][k], 2))
            row += 1

        total_cell = ws.cell(row=row, column=1, value='薪資總額')
        total_cell.font = Font(bold=True)
        salary_cell = ws.cell(row=row, column=4, value=round(data['total_salary'], 2))
        salary_cell.font = Font(bold=True)
        row += 2

    ws.cell(row=row, column=1, value='所有帳戶薪資總合計').font = Font(bold=True, size=12)
    ws.cell(row=row, column=4, value=round(results['grand_salary'], 2)).font = Font(bold=True, size=12)

    for col in ws.columns:
        max_len = max((len(str(cell.value)) for cell in col if cell.value), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len * 2.2 + 4, 60)

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

    font_name = 'Helvetica'
    for fp in ['C:/Windows/Fonts/msjh.ttc', 'C:/Windows/Fonts/msyh.ttc',
               'C:/Windows/Fonts/simsun.ttc']:
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

    story = []
    story.append(Paragraph(
        f'薪資明細  {results["start_date"]} ～ {results["end_date"]}',
        style('title', fontSize=16, alignment=1, spaceAfter=16, fontName=font_name)))

    for uid, data in results['user_data'].items():
        story.append(Paragraph(f'帳戶：{data["username"]}',
                               style('h2', fontSize=12, spaceBefore=10, spaceAfter=6)))
        tdata = [['工項', '只數', '單價(NTD)', '小計(NTD)']]
        for k, label in REPORT_FIELDS:
            tdata.append([label, str(data['totals'][k]),
                          f'{results["prices"].get(k, 0):.2f}',
                          f'{data["subtotals"][k]:.2f}'])
        tdata.append(['薪資總額', '', '', f'{data["total_salary"]:.2f}'])

        t = Table(tdata, colWidths=[230, 55, 90, 90])
        t.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4472C4')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#D9E1F2')),
            ('FONTNAME', (0, -1), (-1, -1), font_name),
        ]))
        story.append(t)
        story.append(Spacer(1, 10))

    story.append(Paragraph(
        f'所有帳戶薪資總合計：{results["grand_salary"]:.2f} NTD',
        style('grand', fontSize=13, spaceBefore=10, fontName=font_name)))

    doc.build(story)
    buf.seek(0)
    fname = f'salary_{results["start_date"]}_{results["end_date"]}.pdf'
    return send_file(buf, mimetype='application/pdf',
                     as_attachment=True, download_name=fname)


# ---------------------------------------------------------------------------
# Page 9: Personal Statistics (USER only)
# ---------------------------------------------------------------------------

@app.route('/personal-stats', methods=['GET', 'POST'])
@login_required
def personal_stats():
    if current_user.role == 'ADMIN':
        abort(403)

    totals_result = None
    salary_result = None
    form = request.form if request.method == 'POST' else {}
    action = form.get('action', '')

    stats_start = form.get('stats_start', '')
    stats_end = form.get('stats_end', '')
    stats_confirm = form.get('stats_confirm', 'all')
    salary_start = form.get('salary_start', '')
    salary_end = form.get('salary_end', '')

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
        totals_result = {'start': stats_start, 'end': stats_end,
                         'confirm_filter': stats_confirm,
                         'totals': totals, 'count': len(reports)}

    elif action == 'salary' and salary_start and salary_end:
        prices = {}
        for k, _ in REPORT_FIELDS:
            try:
                prices[k] = max(0.0, float(form.get(f'price_{k}', 0)))
            except (ValueError, TypeError):
                prices[k] = 0.0

        reports = Report.query.filter(
            Report.user_id == current_user.id,
            Report.is_confirmed == True,
            Report.report_date >= date.fromisoformat(salary_start),
            Report.report_date <= date.fromisoformat(salary_end)
        ).all()

        totals = {k: 0 for k, _ in REPORT_FIELDS}
        for r in reports:
            for k, _ in REPORT_FIELDS:
                totals[k] += getattr(r, k, 0)

        subtotals = {k: totals[k] * prices.get(k, 0) for k, _ in REPORT_FIELDS}
        salary_result = {'start': salary_start, 'end': salary_end,
                         'totals': totals, 'prices': prices,
                         'subtotals': subtotals,
                         'grand_total': sum(subtotals.values()),
                         'count': len(reports)}

    return render_template('personal_stats.html',
                           report_fields=REPORT_FIELDS,
                           totals_result=totals_result,
                           salary_result=salary_result,
                           stats_start=stats_start, stats_end=stats_end,
                           stats_confirm=stats_confirm,
                           salary_start=salary_start, salary_end=salary_end)


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
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='127.0.0.1', port=5000)
