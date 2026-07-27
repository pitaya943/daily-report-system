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


_DELETE_SQL = [
    'DELETE FROM ledger_entries',
    'DELETE FROM report_archives',
    'DELETE FROM user_retention_rates',
    'DELETE FROM audit_logs',
    'DELETE FROM material_requests',
    'DELETE FROM reports',
    'DELETE FROM users',
]


def _clean_tables():
    """Wipe transient test data using the CURRENT (outer) session and then remove it.

    Must be called while the session-scope app_context is active (i.e. from a
    fixture, not from inside ``with app.app_context()``).  Operating on the
    outer session ensures requests in the next test start with a fresh view.
    """
    from sqlalchemy import text
    for stmt in _DELETE_SQL:
        try:
            _db.session.execute(text(stmt))
        except Exception:
            pass
    try:
        _db.session.commit()
    except Exception:
        _db.session.rollback()
    # Discard the session so the next request gets a fresh one (clears identity-map cache)
    _db.session.remove()


@pytest.fixture(scope='session', autouse=True)
def clean_db_at_start(app):
    """Run ONCE before all tests to wipe any leftover data from previous pytest sessions."""
    _clean_tables()
    yield


@pytest.fixture(autouse=True)
def clean_user_data(app):
    """Delete all user-generated rows AFTER each test, then reset session and Flask-Login state.

    Flask 3.x binds ``flask.g`` to the APPLICATION context, not the request context.
    With a session-scope app fixture, ``g._login_user`` set during test N would bleed
    into test N+1.  We explicitly clear it here so every test starts with AnonymousUser.

    The flask-limiter also uses in-process memory storage, so we reset its counters
    here to prevent rate-limit bleed-over between tests.
    """
    yield
    _clean_tables()
    # Reset rate-limit counters (memory:// storage accumulates across tests)
    from app import limiter as _limiter
    try:
        _limiter.reset()
    except Exception:
        pass
    # Clear Flask-Login's per-app-context user cache (Flask 3.x: g is app-ctx scoped)
    from flask import g as flask_g
    try:
        delattr(flask_g, '_login_user')
    except AttributeError:
        pass


# ── User fixtures ────────────────────────────────────────────────────────────

def _make_user(**kwargs):
    """Create a User in the OUTER session and return a detached instance.

    Called directly from user fixtures (no nested app_context), so it operates
    on the same session that Flask's request handler will use — eliminating the
    cross-context visibility gap that caused stale identity-map issues.
    """
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
    from models import User
    u = User(**defaults)
    _db.session.add(u)
    _db.session.commit()
    # refresh then expunge: loads all attrs while session is open, detaches safely.
    _db.session.refresh(u)
    _db.session.expunge(u)
    return u


@pytest.fixture
def admin_user(app):
    return _make_user(display_name='admin_test', role='ADMIN', zone='西區')


@pytest.fixture
def west_user(app):
    return _make_user(display_name='west_user01', role='USER', zone='西區')


@pytest.fixture
def west_user2(app):
    return _make_user(display_name='west_user02', role='USER', zone='西區')


@pytest.fixture
def south_user(app):
    return _make_user(display_name='south_user01', role='USER', zone='南區')


@pytest.fixture
def bm_user(app):
    return _make_user(display_name='bm_user01', role='USER', zone='西區',
                      is_big_meter=True)


# ── Login helper ─────────────────────────────────────────────────────────────

def login(client, user_id_int, password='password'):
    """POST to /login using integer PK (not display_name)."""
    return client.post('/login', data={
        'user_id': str(user_id_int),
        'password': password,
    }, follow_redirects=True)
