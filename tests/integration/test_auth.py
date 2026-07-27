"""
Integration tests: authentication and authorization.
"""
import pytest
from tests.conftest import login


class TestLogin:
    def test_admin_login_success(self, client, admin_user):
        resp = login(client, admin_user.id)
        assert resp.status_code == 200
        # ADMIN is redirected to /confirmation
        assert '確認'.encode() in resp.data or b'confirmation' in resp.request.path.encode()

    def test_west_user_login_success(self, client, west_user):
        resp = login(client, west_user.id)
        assert resp.status_code == 200

    def test_wrong_password_rejected(self, client, west_user):
        resp = client.post('/login', data={
            'user_id': str(west_user.id),
            'password': 'wrong_password',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert '密碼錯誤'.encode() in resp.data  # '密碼錯誤'

    def test_nonexistent_user_id_rejected(self, client):
        resp = client.post('/login', data={
            'user_id': '99999',
            'password': 'password',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert '密碼錯誤'.encode() in resp.data

    def test_inactive_user_rejected(self, client, app):
        from models import db, User
        from werkzeug.security import generate_password_hash
        with app.app_context():
            u = User(display_name='inactive01', role='USER', zone='西區',
                     password_hash=generate_password_hash('password'),
                     is_active=False)
            db.session.add(u)
            db.session.commit()
            uid = u.id
        resp = client.post('/login', data={
            'user_id': str(uid),
            'password': 'password',
        }, follow_redirects=True)
        assert '密碼錯誤'.encode() in resp.data

    def test_logout_clears_session(self, client, west_user):
        login(client, west_user.id)
        client.get('/logout', follow_redirects=True)
        resp = client.get('/report', follow_redirects=False)
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']


class TestAuthorization:
    def test_unauthenticated_report_redirects(self, client):
        resp = client.get('/report', follow_redirects=False)
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_unauthenticated_confirmation_redirects(self, client):
        resp = client.get('/confirmation', follow_redirects=False)
        assert resp.status_code == 302

    def test_user_cannot_access_confirmation_admin_actions(self, client, west_user):
        login(client, west_user.id)
        # POST to batch confirm (admin-only)
        resp = client.post('/confirmation/reports/batch', data={
            'ids': ['1'],
            'batch_action': 'confirm',
        })
        assert resp.status_code in (302, 403)

    def test_user_cannot_add_material(self, client, west_user):
        login(client, west_user.id)
        resp = client.post('/materials/add', data={
            'name': 'X', 'unit': 'pcs',
            'received_quantity': '10', 'remaining_quantity': '10',
            'cumulative_usage': '0',
        })
        assert resp.status_code in (302, 403)

    def test_admin_report_redirects_to_confirmation(self, client, admin_user):
        resp = login(client, admin_user.id)
        # ADMIN -> /confirmation after login
        assert resp.status_code == 200

    def test_non_numeric_user_id_rejected(self, client):
        resp = client.post('/login', data={
            'user_id': 'abc',
            'password': 'password',
        }, follow_redirects=True)
        assert '密碼錯誤'.encode() in resp.data
