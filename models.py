from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timedelta


def _tw_now():
    return datetime.utcnow() + timedelta(hours=8)

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    display_name = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(10), nullable=False)  # 'ADMIN' or 'USER'
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=_tw_now)
    updated_at = db.Column(db.DateTime, default=_tw_now)

    payment_method      = db.Column(db.String(10), nullable=False, default='TRANSFER')  # CASH or TRANSFER
    insurance_deduction = db.Column(db.Integer,   nullable=False, default=0)           # NTD per pay period; 0 = not enrolled
    tax_exempt          = db.Column(db.Boolean,   nullable=False, default=False)       # if True and not enrolled, skip tax deduction
    retention_offset    = db.Column(db.Integer,   nullable=False, default=0)           # ADMIN adjustment to YTD retention
    bank_account        = db.Column(db.String(200), nullable=True,  default=None)       # encrypted Fernet token (~88 chars); plaintext fallback = 14 digits
    fixed_salary        = db.Column(db.Integer,   nullable=False, default=0)           # fixed monthly salary paid on 10th payday
    zone                = db.Column(db.String(10), nullable=False, default='西區')     # '西區' or '南區'
    is_big_meter        = db.Column(db.Boolean,   nullable=False, default=False)       # 大表用戶：使用大表工項計價，獨立管理

    @property
    def username(self):
        return f"uid_{self.id}"


class Report(db.Model):
    __tablename__ = 'reports'
    __table_args__ = (
        db.Index('ix_reports_user_date',       'user_id', 'report_date'),
        db.Index('ix_reports_date_confirmed',  'report_date', 'is_confirmed'),
        db.Index('ix_reports_user_confirmed',  'user_id', 'is_confirmed'),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    report_date = db.Column(db.Date, nullable=False)
    # ── 共用欄位（兩區皆使用，精確到 0.1 支）
    direct_13 = db.Column(db.Numeric(8, 1), default=0)
    direct_20 = db.Column(db.Numeric(8, 1), default=0)
    direct_25 = db.Column(db.Numeric(8, 1), default=0)
    direct_40 = db.Column(db.Numeric(8, 1), default=0)
    indirect_13 = db.Column(db.Numeric(8, 1), default=0)
    indirect_20 = db.Column(db.Numeric(8, 1), default=0)
    indirect_25 = db.Column(db.Numeric(8, 1), default=0)
    indirect_40 = db.Column(db.Numeric(8, 1), default=0)
    switch_valve_40 = db.Column(db.Numeric(8, 1), default=0)
    direct_fixed_40 = db.Column(db.Numeric(8, 1), default=0)
    indirect_fixed_40 = db.Column(db.Numeric(8, 1), default=0)
    pipe_repair = db.Column(db.Numeric(8, 1), default=0)
    mobilization = db.Column(db.Numeric(8, 1), default=0)
    recheck = db.Column(db.Numeric(8, 1), default=0)
    soil_clearing = db.Column(db.Numeric(8, 1), default=0)
    # ── 西區專屬
    original_change = db.Column(db.Numeric(8, 1), default=0)
    dsv_13 = db.Column(db.Numeric(8, 1), default=0)
    dsv_20 = db.Column(db.Numeric(8, 1), default=0)
    dsv_25 = db.Column(db.Numeric(8, 1), default=0)
    isv_13 = db.Column(db.Numeric(8, 1), default=0)
    isv_20 = db.Column(db.Numeric(8, 1), default=0)
    isv_25 = db.Column(db.Numeric(8, 1), default=0)
    sw_13  = db.Column(db.Numeric(8, 1), default=0)
    sw_20  = db.Column(db.Numeric(8, 1), default=0)
    sw_25  = db.Column(db.Numeric(8, 1), default=0)
    dfix_13 = db.Column(db.Numeric(8, 1), default=0)
    dfix_20 = db.Column(db.Numeric(8, 1), default=0)
    dfix_25 = db.Column(db.Numeric(8, 1), default=0)
    ifix_13 = db.Column(db.Numeric(8, 1), default=0)
    ifix_20 = db.Column(db.Numeric(8, 1), default=0)
    ifix_25 = db.Column(db.Numeric(8, 1), default=0)
    # ── 共用 APP 工項（西區/南區一般用戶）
    app_item = db.Column(db.Numeric(8, 1), default=0)
    # ── 南區專屬
    s_orig_13 = db.Column(db.Numeric(8, 1), default=0)
    s_orig_20 = db.Column(db.Numeric(8, 1), default=0)
    s_orig_25 = db.Column(db.Numeric(8, 1), default=0)
    s_orig_40 = db.Column(db.Numeric(8, 1), default=0)
    s_dsv_13  = db.Column(db.Numeric(8, 1), default=0)
    s_dsv_20  = db.Column(db.Numeric(8, 1), default=0)
    s_dsv_25  = db.Column(db.Numeric(8, 1), default=0)
    s_dsv_40  = db.Column(db.Numeric(8, 1), default=0)
    s_isv_13  = db.Column(db.Numeric(8, 1), default=0)
    s_isv_20  = db.Column(db.Numeric(8, 1), default=0)
    s_isv_25  = db.Column(db.Numeric(8, 1), default=0)
    s_isv_40  = db.Column(db.Numeric(8, 1), default=0)
    s_sw_13   = db.Column(db.Numeric(8, 1), default=0)
    s_sw_20   = db.Column(db.Numeric(8, 1), default=0)
    s_sw_25   = db.Column(db.Numeric(8, 1), default=0)
    s_dfix_13 = db.Column(db.Numeric(8, 1), default=0)
    s_dfix_20 = db.Column(db.Numeric(8, 1), default=0)
    s_dfix_25 = db.Column(db.Numeric(8, 1), default=0)
    s_ifix_13 = db.Column(db.Numeric(8, 1), default=0)
    s_ifix_20 = db.Column(db.Numeric(8, 1), default=0)
    s_ifix_25 = db.Column(db.Numeric(8, 1), default=0)
    # ── 大表工項（大表用戶專屬，25 欄）
    bm_50_down       = db.Column(db.Numeric(8, 1), default=0)
    bm_75_down       = db.Column(db.Numeric(8, 1), default=0)
    bm_100_down      = db.Column(db.Numeric(8, 1), default=0)
    bm_150_down      = db.Column(db.Numeric(8, 1), default=0)
    bm_200_down      = db.Column(db.Numeric(8, 1), default=0)
    bm_250_down      = db.Column(db.Numeric(8, 1), default=0)
    bm_300_down      = db.Column(db.Numeric(8, 1), default=0)
    bm_50_up         = db.Column(db.Numeric(8, 1), default=0)
    bm_75_up         = db.Column(db.Numeric(8, 1), default=0)
    bm_100_up        = db.Column(db.Numeric(8, 1), default=0)
    bm_150_up        = db.Column(db.Numeric(8, 1), default=0)
    bm_200_up        = db.Column(db.Numeric(8, 1), default=0)
    bm_250_up        = db.Column(db.Numeric(8, 1), default=0)
    bm_rm_screw50    = db.Column(db.Numeric(8, 1), default=0)
    bm_rm_noscrew50  = db.Column(db.Numeric(8, 1), default=0)
    bm_rm_75         = db.Column(db.Numeric(8, 1), default=0)
    bm_rm_100        = db.Column(db.Numeric(8, 1), default=0)
    bm_rm_150        = db.Column(db.Numeric(8, 1), default=0)
    bm_rm_200        = db.Column(db.Numeric(8, 1), default=0)
    bm_hole          = db.Column(db.Numeric(8, 1), default=0)
    bm_clean_big     = db.Column(db.Numeric(8, 1), default=0)
    bm_truck         = db.Column(db.Numeric(8, 1), default=0)
    bm_mobilization  = db.Column(db.Numeric(8, 1), default=0)
    bm_recheck       = db.Column(db.Numeric(8, 1), default=0)
    bm_app           = db.Column(db.Numeric(8, 1), default=0)
    bm_40_fen        = db.Column(db.Numeric(8, 1), default=0)
    # ── 共同作業
    collab_count = db.Column(db.Integer, nullable=False, default=1)   # 含提交者的總人數
    collab_json  = db.Column(db.Text, nullable=True)                   # JSON list of additional collab user_ids
    # ── 狀態欄位
    is_confirmed = db.Column(db.Boolean, default=False)
    confirmed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    confirmed_at = db.Column(db.DateTime, nullable=True)
    is_rejected  = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=_tw_now)
    updated_at = db.Column(db.DateTime, default=_tw_now)


class Material(db.Model):
    __tablename__ = 'materials'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    unit = db.Column(db.String(20), nullable=False)
    remaining_quantity = db.Column(db.Integer, default=0)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=_tw_now)
    updated_at = db.Column(db.DateTime, default=_tw_now)


class MaterialRequest(db.Model):
    __tablename__ = 'material_requests'
    __table_args__ = (
        db.Index('ix_mat_req_user_id', 'user_id'),
        db.Index('ix_mat_req_status',  'status'),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    material_id = db.Column(db.Integer, db.ForeignKey('materials.id'), nullable=False)
    requested_quantity = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(10), default='PENDING')  # PENDING, APPROVED, REJECTED
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=_tw_now)


class SystemConfig(db.Model):
    __tablename__ = 'system_config'
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(200), nullable=False)


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    __table_args__ = (
        db.Index('ix_audit_logs_created_at',  'created_at'),
        db.Index('ix_audit_logs_user_id',     'user_id'),
        db.Index('ix_audit_logs_action_type', 'action_type'),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action_type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=_tw_now)


class UserRetentionRate(db.Model):
    """Per-user per-field retention rate overrides. Absence = use global rate."""
    __tablename__ = 'user_retention_rates'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    field = db.Column(db.String(50), nullable=False)
    rate = db.Column(db.Integer, nullable=False, default=0)


class ReportArchive(db.Model):
    __tablename__ = 'report_archives'
    __table_args__ = (
        db.Index('ix_report_archive_date', 'report_date'),
        db.Index('ix_report_archive_type', 'report_type'),
    )
    id           = db.Column(db.Integer, primary_key=True)
    report_type  = db.Column(db.String(10), nullable=False)   # 'DAILY' / 'MONTHLY'
    report_date  = db.Column(db.Date, nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    period_end   = db.Column(db.Date, nullable=False)
    r2_key_excel = db.Column(db.String(300), nullable=True)
    r2_key_pdf   = db.Column(db.String(300), nullable=True)
    source       = db.Column(db.String(10), nullable=False, default='auto')  # 'auto' / 'manual'
    generated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # NULL = 自動排程
    generated_at = db.Column(db.DateTime, default=_tw_now)


class LedgerEntry(db.Model):
    __tablename__ = 'ledger_entries'
    __table_args__ = (
        db.Index('ix_ledger_date', 'entry_date'),
        db.Index('ix_ledger_type', 'entry_type'),
    )
    id           = db.Column(db.Integer, primary_key=True)
    entry_date   = db.Column(db.Date, nullable=False)
    description  = db.Column(db.String(200), nullable=False)
    amount       = db.Column(db.Integer, nullable=False)       # NTD，正=收入，負=支出
    entry_type   = db.Column(db.String(10), nullable=False)    # 'INCOME' / 'EXPENSE'
    category     = db.Column(db.String(50), nullable=True)
    note         = db.Column(db.Text, nullable=True)
    receipt_key  = db.Column(db.String(300), nullable=True)    # R2 object key (path in bucket)
    receipt_name = db.Column(db.String(200), nullable=True)    # original filename
    created_by   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    payer_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # NULL = 公司
    created_at   = db.Column(db.DateTime, default=_tw_now)
    updated_at   = db.Column(db.DateTime, default=_tw_now)
