"""
Integration tests: security — authorization enforcement and input validation.
"""
from datetime import date

import pytest
from tests.conftest import login, _db


ADMIN_ONLY_ROUTES = [
    ('/confirmation', 'GET'),
    ('/summary', 'GET'),
    # /settings and /audit are @login_required only (not admin-only); regular users can view them
]


class TestAdminOnlyRoutes:
    @pytest.mark.parametrize('path,method', ADMIN_ONLY_ROUTES)
    def test_user_gets_403_or_redirect(self, client, west_user, path, method):
        login(client, west_user.id)
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code in (302, 403), (
            f'Expected 302/403 for USER on {method} {path}, got {resp.status_code}'
        )

    def test_unauthenticated_gets_redirect(self, client):
        for path, _ in ADMIN_ONLY_ROUTES:
            resp = client.get(path, follow_redirects=False)
            assert resp.status_code == 302, (
                f'Expected 302 for unauthenticated on {path}, got {resp.status_code}'
            )


class TestCrossUserAccess:
    def test_user_cannot_delete_others_report(self, client, west_user, west_user2, app):
        from models import db, Report
        r = Report(user_id=west_user2.id, report_date=date(2026, 7, 15),
                   direct_13=1.0, is_confirmed=False)
        _db.session.add(r)
        _db.session.commit()
        rid = r.id

        login(client, west_user.id)
        resp = client.post(f'/history/{rid}/delete', follow_redirects=False)
        assert resp.status_code in (302, 403, 404, 405)
        assert Report.query.get(rid) is not None

    def test_user_can_delete_own_report(self, client, west_user, app):
        from models import Report
        r = Report(user_id=west_user.id, report_date=date(2026, 7, 15),
                   direct_13=1.0, is_confirmed=False)
        _db.session.add(r)
        _db.session.commit()
        _db.session.refresh(r)
        rid = r.id
        _db.session.expunge(r)

        login(client, west_user.id)
        # follow_redirects=False: the success redirect goes to /history which uses
        # collab_json::jsonb PostgreSQL syntax that fails on SQLite test DB.
        resp = client.post(f'/history/{rid}/delete', follow_redirects=False)
        assert resp.status_code in (200, 302)
        # r is expunged so identity-map is clean; this hits the DB directly.
        assert _db.session.get(Report, rid) is None


class TestInputValidation:
    def test_material_request_negative_qty_rejected(self, client, west_user, app):
        with app.app_context():
            from models import Material
            mat = Material.query.filter(Material.remaining_quantity > 0).first()
            if not mat:
                pytest.skip('no material with stock')
            mat_id = mat.id

        login(client, west_user.id)
        resp = client.post('/materials/request', data={
            'material_id': str(mat_id),
            'requested_quantity': '-1',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from models import MaterialRequest
            req = MaterialRequest.query.filter_by(user_id=west_user.id, material_id=mat_id).first()
            assert req is None

    def test_login_sql_injection_attempt(self, client):
        resp = client.post('/login', data={
            'user_id': "1 OR 1=1",
            'password': 'anything',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert '密碼錯誤'.encode() in resp.data

    def test_password_hash_not_in_response(self, client, west_user):
        login(client, west_user.id)
        resp = client.get('/report')
        assert b'$2b$' not in resp.data
        assert b'pbkdf2' not in resp.data.lower()

    def test_settings_page_accessible_to_admin(self, client, admin_user):
        login(client, admin_user.id)
        resp = client.get('/settings')
        assert resp.status_code == 200
