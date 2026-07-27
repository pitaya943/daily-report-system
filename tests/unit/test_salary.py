"""
Unit tests for salary calculation logic.
All tests use constants imported directly from app — no DB, no HTTP.
"""
from app import (
    WEST_REPORT_FIELDS, SOUTH_REPORT_FIELDS, BIG_METER_FIELDS,
    DEFAULT_PRICES_WEST, DEFAULT_PRICES_SOUTH, DEFAULT_PRICES_BM,
    WEST_RETENTION_FIELDS, SOUTH_RETENTION_FIELDS,
    RETENTION_CAP, RETENTION_RATE,
)


# ── Pure salary formula helpers (mirror the /salary route logic) ─────────────

def calc_gross(totals: dict, prices: dict, zone_fields: list) -> float:
    return sum(float(totals.get(k, 0)) * prices.get(k, 0) for k, _ in zone_fields)


def calc_retention_raw(totals: dict, prices: dict, ret_fields: list, rate: float) -> float:
    return sum(float(totals.get(k, 0)) * prices.get(k, 0) * (rate / 100) for k in ret_fields)


def calc_period_retention(raw: float, ytd_before: float, cap: float = RETENTION_CAP) -> float:
    return max(0.0, min(raw, cap - ytd_before))


def calc_tax(gross: float, rate: float, insurance: float, tax_exempt: bool) -> int:
    if tax_exempt or insurance > 0:
        return 0
    return round(gross * rate / 100)


def calc_final(gross: float, retention: float, fixed: float,
               insurance: float, tax: int) -> float:
    return (gross - retention) + fixed - insurance - tax


# ── Tests ────────────────────────────────────────────────────────────────────

class TestWestGross:
    def test_single_field(self):
        totals = {'direct_13': 3}
        gross = calc_gross(totals, DEFAULT_PRICES_WEST, WEST_REPORT_FIELDS)
        assert gross == 3 * DEFAULT_PRICES_WEST['direct_13']

    def test_multiple_fields(self):
        totals = {'direct_13': 2, 'mobilization': 1, 'recheck': 5}
        expected = (2 * DEFAULT_PRICES_WEST['direct_13']
                    + 1 * DEFAULT_PRICES_WEST['mobilization']
                    + 5 * DEFAULT_PRICES_WEST['recheck'])
        assert calc_gross(totals, DEFAULT_PRICES_WEST, WEST_REPORT_FIELDS) == expected

    def test_zero_fields_excluded(self):
        totals = {'direct_13': 0, 'direct_20': 2}
        gross = calc_gross(totals, DEFAULT_PRICES_WEST, WEST_REPORT_FIELDS)
        assert gross == 2 * DEFAULT_PRICES_WEST['direct_20']

    def test_empty_totals(self):
        assert calc_gross({}, DEFAULT_PRICES_WEST, WEST_REPORT_FIELDS) == 0.0


class TestSouthGross:
    def test_south_uses_south_prices(self):
        totals = {'s_orig_13': 2, 's_dsv_25': 1}
        gross = calc_gross(totals, DEFAULT_PRICES_SOUTH, SOUTH_REPORT_FIELDS)
        expected = (2 * DEFAULT_PRICES_SOUTH['s_orig_13']
                    + 1 * DEFAULT_PRICES_SOUTH['s_dsv_25'])
        assert gross == expected

    def test_south_price_differs_from_west(self):
        # direct_13 is 140 in south vs 120 in west
        assert DEFAULT_PRICES_SOUTH['direct_13'] != DEFAULT_PRICES_WEST['direct_13']
        totals = {'direct_13': 1}
        west_g = calc_gross(totals, DEFAULT_PRICES_WEST, WEST_REPORT_FIELDS)
        south_g = calc_gross(totals, DEFAULT_PRICES_SOUTH, SOUTH_REPORT_FIELDS)
        assert south_g > west_g


class TestBMGross:
    def test_bm_field(self):
        totals = {'bm_50_down': 2}
        gross = calc_gross(totals, DEFAULT_PRICES_BM, BIG_METER_FIELDS)
        assert gross == 2 * DEFAULT_PRICES_BM['bm_50_down']

    def test_bm_mobilization(self):
        totals = {'bm_mobilization': 1}
        gross = calc_gross(totals, DEFAULT_PRICES_BM, BIG_METER_FIELDS)
        assert gross == DEFAULT_PRICES_BM['bm_mobilization']


class TestCollabSplit:
    def test_2_person_split_exact(self):
        qty = 6
        collab_count = 2
        each = qty / collab_count
        assert each == 3.0

    def test_3_person_split_fractional(self):
        qty = 1
        collab_count = 3
        each = qty / collab_count
        assert abs(each - 1 / 3) < 1e-9

    def test_collab_count_formula(self):
        # collab_count = 1 (self) + len(collab_ids)
        collab_ids = [10, 11, 12]
        collab_count = 1 + len(collab_ids)
        assert collab_count == 4

    def test_max_collab_limit(self):
        # Backend enforces [:6] on collab_ids
        raw_ids = list(range(1, 10))
        collab_ids = raw_ids[:6]
        assert len(collab_ids) == 6
        assert 1 + len(collab_ids) == 7


class TestFixedSalary:
    def test_fixed_added_when_10th(self):
        gross, retention, fixed, insurance, tax = 10000, 2000, 5000, 0, 0
        final = calc_final(gross, retention, fixed, insurance, tax)
        assert final == 13000

    def test_fixed_zero_when_not_applied(self):
        final = calc_final(10000, 2000, 0, 0, 0)
        assert final == 8000

    def test_insurance_deducted_correctly(self):
        final = calc_final(10000, 2000, 0, 834, 0)
        assert final == 7166

    def test_insurance_not_deducted_when_zero(self):
        assert calc_final(10000, 0, 0, 0, 0) == 10000


class TestTax:
    def test_tax_calculated_from_gross(self):
        tax = calc_tax(gross=10000, rate=3.0, insurance=0, tax_exempt=False)
        assert tax == 300

    def test_tax_zero_when_enrolled(self):
        tax = calc_tax(gross=10000, rate=3.0, insurance=834, tax_exempt=False)
        assert tax == 0

    def test_tax_zero_when_exempt(self):
        tax = calc_tax(gross=10000, rate=3.0, insurance=0, tax_exempt=True)
        assert tax == 0

    def test_tax_rounding(self):
        tax = calc_tax(gross=10001, rate=3.0, insurance=0, tax_exempt=False)
        assert tax == round(10001 * 3.0 / 100)


class TestNetFinal:
    def test_net_formula(self):
        gross, retention = 20000, 4000
        net = gross - retention
        assert net == 16000

    def test_final_all_components(self):
        # gross=15000, ret=3000, fixed=2000, ins=834, tax=450
        final = calc_final(15000, 3000, 2000, 834, 450)
        assert final == (15000 - 3000) + 2000 - 834 - 450

    def test_bm_no_retention(self):
        # BM user: retention = 0
        gross = 5000
        final = calc_final(gross, 0, 0, 0, 0)
        assert final == gross
