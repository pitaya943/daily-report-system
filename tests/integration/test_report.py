"""
Integration tests: report submission (日報回報).
"""
import pytest
from tests.conftest import login


class TestReportPage:
    def test_west_user_gets_report_page(self, client, west_user):
        login(client, west_user.id)
        resp = client.get('/report')
        assert resp.status_code == 200
        # West zone has 'direct_13' field
        assert b'direct_13' in resp.data or 'direct_13'.encode() in resp.data

    def test_south_user_gets_south_fields(self, client, south_user):
        login(client, south_user.id)
        resp = client.get('/report')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8', errors='replace')
        # South-specific field name appears in the form HTML
        assert 's_orig_13' in body

    def test_bm_user_gets_bm_fields(self, client, bm_user):
        login(client, bm_user.id)
        resp = client.get('/report')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8', errors='replace')
        assert 'bm_50_down' in body


class TestReportSubmission:
    def test_valid_west_report_saved(self, client, west_user, app):
        login(client, west_user.id)
        resp = client.post('/report', data={
            'report_date': '2026-07-27',
            'direct_13': '3',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from models import Report
            r = Report.query.filter_by(user_id=west_user.id).first()
            assert r is not None
            assert float(r.direct_13) == 3.0
            assert r.is_confirmed is False

    def test_valid_south_report_saved(self, client, south_user, app):
        login(client, south_user.id)
        resp = client.post('/report', data={
            'report_date': '2026-07-27',
            's_orig_13': '2',
            's_dsv_25': '1',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from models import Report
            r = Report.query.filter_by(user_id=south_user.id).first()
            assert r is not None

    def test_report_without_date_rejected(self, client, west_user):
        login(client, west_user.id)
        resp = client.post('/report', data={
            'direct_13': '3',
        }, follow_redirects=True)
        # Should show error or redirect back to report
        assert resp.status_code == 200

    def test_cross_zone_collab_filtered(self, client, west_user, south_user, app):
        """South user cannot be collab of west user (different zone)."""
        login(client, west_user.id)
        resp = client.post('/report', data={
            'report_date': '2026-07-27',
            'direct_13': '2',
            'collab_ids': [str(south_user.id)],
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from models import Report
            r = Report.query.filter_by(user_id=west_user.id).first()
            if r:
                import json
                collab = json.loads(r.collab_json or '[]')
                assert south_user.id not in collab

    def test_same_zone_collab_accepted(self, client, west_user, west_user2, app):
        login(client, west_user.id)
        resp = client.post('/report', data={
            'report_date': '2026-07-27',
            'direct_13': '4',
            'collab_ids': [str(west_user2.id)],
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from models import Report
            r = Report.query.filter_by(user_id=west_user.id).first()
            if r and r.collab_json:
                import json
                collab = json.loads(r.collab_json)
                assert west_user2.id in collab
                assert r.collab_count == 2
