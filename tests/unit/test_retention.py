"""
Unit tests for retention (保留金) calculation logic.
No DB access — tests the pure math formulas and field-count invariants.
"""
from app import (
    WEST_RETENTION_FIELDS, SOUTH_RETENTION_FIELDS,
    DEFAULT_PRICES_WEST, DEFAULT_PRICES_SOUTH,
    RETENTION_CAP, RETENTION_RATE,
)


def calc_retention_raw(totals: dict, prices: dict, ret_fields: list, rate: float) -> float:
    return sum(float(totals.get(k, 0)) * prices.get(k, 0) * (rate / 100) for k in ret_fields)


def apply_cap(raw: float, ytd_before: float, cap: float = RETENTION_CAP) -> float:
    """period_retention = max(0, min(raw, cap - ytd_before))"""
    return max(0.0, min(raw, cap - ytd_before))


class TestRetentionCap:
    def test_cap_clamps_high_value(self):
        # ytd_before=0, raw=70000 → clamped to 60000
        result = apply_cap(raw=70000, ytd_before=0, cap=RETENTION_CAP)
        assert result == RETENTION_CAP

    def test_cap_allows_exact_cap(self):
        result = apply_cap(raw=RETENTION_CAP, ytd_before=0, cap=RETENTION_CAP)
        assert result == RETENTION_CAP

    def test_cap_floor_at_zero(self):
        # ytd_before already at cap → period retention = 0
        result = apply_cap(raw=5000, ytd_before=RETENTION_CAP, cap=RETENTION_CAP)
        assert result == 0.0

    def test_cap_negative_raw_clamped(self):
        result = apply_cap(raw=-100, ytd_before=0, cap=RETENTION_CAP)
        assert result == 0.0

    def test_period_caps_at_remaining_room(self):
        # ytd_before=55000, raw=8000 → only 5000 room left
        result = apply_cap(raw=8000, ytd_before=55000, cap=RETENTION_CAP)
        assert result == 5000.0

    def test_period_within_room(self):
        result = apply_cap(raw=3000, ytd_before=10000, cap=RETENTION_CAP)
        assert result == 3000.0


class TestRetentionOffset:
    def test_offset_positive(self):
        # calculated=50000, offset=+1000 → ytd=51000 (not over cap)
        raw_ytd = 50000 + 1000
        result = min(raw_ytd, RETENTION_CAP)
        assert result == 51000

    def test_offset_exceeds_cap(self):
        raw_ytd = 59000 + 2000  # =61000
        result = min(raw_ytd, RETENTION_CAP)
        assert result == RETENTION_CAP


class TestRetentionFields:
    def test_west_has_8_fields(self):
        assert len(WEST_RETENTION_FIELDS) == 8

    def test_south_has_28_fields(self):
        assert len(SOUTH_RETENTION_FIELDS) == 28

    def test_west_fields_are_subset_of_prices(self):
        for f in WEST_RETENTION_FIELDS:
            assert f in DEFAULT_PRICES_WEST, f'{f} missing from DEFAULT_PRICES_WEST'

    def test_south_fields_are_subset_of_prices(self):
        for f in SOUTH_RETENTION_FIELDS:
            assert f in DEFAULT_PRICES_SOUTH, f'{f} missing from DEFAULT_PRICES_SOUTH'


class TestRetentionCalc:
    def test_basic_west_retention(self):
        totals = {'direct_13': 10}
        raw = calc_retention_raw(totals, DEFAULT_PRICES_WEST, WEST_RETENTION_FIELDS, RETENTION_RATE)
        expected = 10 * DEFAULT_PRICES_WEST['direct_13'] * (RETENTION_RATE / 100)
        assert abs(raw - expected) < 0.001

    def test_non_retention_field_excluded(self):
        # mobilization is NOT in WEST_RETENTION_FIELDS
        totals = {'mobilization': 5}
        raw = calc_retention_raw(totals, DEFAULT_PRICES_WEST, WEST_RETENTION_FIELDS, RETENTION_RATE)
        assert raw == 0.0

    def test_collab_retention_split(self):
        # qty=6, collab_count=3 → each person's qty=2 → each pays retention on 2
        qty = 6
        collab_count = 3
        each_qty = qty / collab_count
        totals_each = {'direct_13': each_qty}
        raw = calc_retention_raw(totals_each, DEFAULT_PRICES_WEST, WEST_RETENTION_FIELDS, RETENTION_RATE)
        expected = each_qty * DEFAULT_PRICES_WEST['direct_13'] * (RETENTION_RATE / 100)
        assert abs(raw - expected) < 0.001
