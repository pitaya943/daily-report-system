import os

# Must be set BEFORE importing app so the module-level
# `with app.app_context(): _init_db(); _seed_materials_csv()` uses SQLite.
os.environ.setdefault('DATABASE_URL', 'sqlite:///test_daily_report.db')
os.environ.setdefault('SECRET_KEY', 'test-secret-key-not-for-production')
os.environ['TESTING'] = '1'          # suppresses APScheduler startup
os.environ['BANK_ENCRYPT_KEY'] = ''  # disables Fernet → plain-text passthrough
os.environ['R2_ACCOUNT_ID'] = ''     # disables R2 client
os.environ['R2_ACCESS_KEY_ID'] = ''
os.environ['R2_SECRET_ACCESS_KEY'] = ''
os.environ['R2_BUCKET_NAME'] = ''

import pytest
from werkzeug.security import generate_password_hash

from app import app as _flask_app
from models import db as _db


@pytest.fixture(scope='session')
def app():
    _flask_app.config.update({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'RATELIMIT_ENABLED': False,
        'SERVER_NAME': None,
    })
    with _flask_app.app_context():
        _db.create_all()
        yield _flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def clean_user_data(app):
    """Delete all user-generated rows after each test; keep Materials + SystemConfig."""
    yield
    with app.app_context():
        from models import (
            Report, MaterialRequest, AuditLog,
            UserRetentionRate, ReportArchive, LedgerEntry, User,
        )
        try:
            LedgerEntry.query.delete()
            ReportArchive.query.delete()
            UserRetentionRate.query.delete()
            AuditLog.query.delete()
            MaterialRequest.query.delete()
            Report.query.delete()
            User.query.delete()
            _db.session.commit()
        except Exception:
            _db.session.rollback()


# ── User fixtures ────────────────────────────────────────────────────────────

def _make_user(**kwargs):
    defaults = dict(
        password_hash=generate_password_hash('password'),
        is_active=True,
        fixed_salary=0,
        fixed_salary_every_period=False,
        insurance_deduction=0,
        tax_exempt=False,
        is_big_meter=False,
    )
    defaults.update(kwargs)
    from models import db, User
    u = User(**defaults)
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def admin_user(app):
    with app.app_context():
        return _make_user(display_name='admin_test', role='ADMIN', zone='西區')


@pytest.fixture
def west_user(app):
    with app.app_context():
        return _make_user(display_name='west_user01', role='USER', zone='西區')


@pytest.fixture
def west_user2(app):
    with app.app_context():
        return _make_user(display_name='west_user02', role='USER', zone='西區')


@pytest.fixture
def south_user(app):
    with app.app_context():
        return _make_user(display_name='south_user01', role='USER', zone='南區')


@pytest.fixture
def bm_user(app):
    with app.app_context():
        return _make_user(display_name='bm_user01', role='USER', zone='西區',
                          is_big_meter=True)


# ── Login helper ─────────────────────────────────────────────────────────────

def login(client, user_id_int, password='password'):
    """POST to /login using integer PK (not display_name)."""
    return client.post('/login', data={
        'user_id': str(user_id_int),
        'password': password,
    }, follow_redirects=True)
