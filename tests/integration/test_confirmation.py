"""
Integration tests: confirmation flow (確認頁面).
"""
import pytest
from tests.conftest import login


def make_report(app, user_id, date='2026-07-20'):
    with app.app_context():
        from models import db, Report
        r = Report(user_id=user_id, report_date=date, direct_13=2.0,
                   is_confirmed=False, is_rejected=False)
        db.session.add(r)
        db.session.commit()
        return r.id


class TestConfirmationPage:
    def test_admin_can_view_confirmation(self, client, admin_user):
        login(client, admin_user.id)
        resp = client.get('/confirmation')
        assert resp.status_code == 200

    def test_user_cannot_view_confirmation(self, client, west_user):
        login(client, west_user.id)
        resp = client.get('/confirmation')
        assert resp.status_code in (302, 403)


class TestBatchConfirmReports:
    def test_batch_confirm_single(self, client, admin_user, west_user, app):
        rid = make_report(app, west_user.id)
        login(client, admin_user.id)
        resp = client.post('/confirmation/reports/batch', data={
            'ids': [str(rid)],
            'batch_action': 'confirm',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from models import Report, AuditLog
            r = Report.query.get(rid)
            assert r.is_confirmed is True
            log = AuditLog.query.filter_by(action_type='REPORT_CONFIRM').first()
            assert log is not None

    def test_batch_confirm_multiple(self, client, admin_user, west_user, app):
        rid1 = make_report(app, west_user.id, '2026-07-20')
        rid2 = make_report(app, west_user.id, '2026-07-21')
        login(client, admin_user.id)
        client.post('/confirmation/reports/batch', data={
            'ids': [str(rid1), str(rid2)],
            'batch_action': 'confirm',
        }, follow_redirects=True)
        with app.app_context():
            from models import Report
            assert Report.query.get(rid1).is_confirmed is True
            assert Report.query.get(rid2).is_confirmed is True

    def test_batch_reject_single(self, client, admin_user, west_user, app):
        rid = make_report(app, west_user.id)
        login(client, admin_user.id)
        client.post('/confirmation/reports/batch', data={
            'ids': [str(rid)],
            'batch_action': 'reject',
        }, follow_redirects=True)
        with app.app_context():
            from models import Report
            assert Report.query.get(rid).is_rejected is True

    def test_batch_confirm_empty_ids_flashes(self, client, admin_user):
        login(client, admin_user.id)
        resp = client.post('/confirmation/reports/batch', data={
            'ids': [],
            'batch_action': 'confirm',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert '勾選'.encode() in resp.data

    def test_already_confirmed_skipped(self, client, admin_user, west_user, app):
        """A report that is already confirmed must not be double-processed."""
        rid = make_report(app, west_user.id)
        with app.app_context():
            from models import db, Report
            r = Report.query.get(rid)
            r.is_confirmed = True
            db.session.commit()
        login(client, admin_user.id)
        client.post('/confirmation/reports/batch', data={
            'ids': [str(rid)],
            'batch_action': 'reject',  # try to reject already-confirmed
        }, follow_redirects=True)
        with app.app_context():
            from models import Report
            r = Report.query.get(rid)
            # should remain confirmed, not rejected
            assert r.is_confirmed is True
            assert r.is_rejected is False


class TestBatchReviewMaterials:
    def _make_material_request(self, app, user_id, mat_id, qty=2):
        with app.app_context():
            from models import db, MaterialRequest
            req = MaterialRequest(
                user_id=user_id, material_id=mat_id,
                requested_quantity=qty, status='PENDING',
            )
            db.session.add(req)
            db.session.commit()
            return req.id

    def test_approve_material_request_updates_inventory(self, client, admin_user, west_user, app):
        from decimal import Decimal
        with app.app_context():
            from models import Material
            mat = Material.query.filter(Material.remaining_quantity > 5).first()
            if mat is None:
                pytest.skip('no material with remaining>5 in seed data')
            mat_id = mat.id
            before_remaining = float(mat.remaining_quantity)
            before_cumulative = float(mat.cumulative_usage)

        req_id = self._make_material_request(app, west_user.id, mat_id, qty=2)
        login(client, admin_user.id)
        client.post('/confirmation/materials/batch', data={
            'ids': [str(req_id)],
            'batch_action': 'approve',
        }, follow_redirects=True)

        with app.app_context():
            from models import Material, MaterialRequest
            req = MaterialRequest.query.get(req_id)
            assert req.status == 'APPROVED'
            mat = Material.query.get(mat_id)
            assert float(mat.remaining_quantity) == pytest.approx(before_remaining - 2)
            assert float(mat.cumulative_usage) == pytest.approx(before_cumulative + 2)
            # Invariant check
            assert float(mat.received_quantity) == pytest.approx(
                float(mat.cumulative_usage) + float(mat.remaining_quantity)
            )

    def test_reject_material_request_no_inventory_change(self, client, admin_user, west_user, app):
        with app.app_context():
            from models import Material
            mat = Material.query.first()
            if mat is None:
                pytest.skip('no materials in DB')
            mat_id = mat.id
            before_remaining = float(mat.remaining_quantity)

        req_id = self._make_material_request(app, west_user.id, mat_id, qty=1)
        login(client, admin_user.id)
        client.post('/confirmation/materials/batch', data={
            'ids': [str(req_id)],
            'batch_action': 'reject',
        }, follow_redirects=True)

        with app.app_context():
            from models import Material, MaterialRequest
            req = MaterialRequest.query.get(req_id)
            assert req.status == 'REJECTED'
            mat = Material.query.get(mat_id)
            assert float(mat.remaining_quantity) == pytest.approx(before_remaining)
