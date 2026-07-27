"""
Unit tests for material inventory invariant:
    received_quantity == cumulative_usage + remaining_quantity

Tests use plain Python dicts to simulate Material state — no DB needed.
"""
from decimal import Decimal


def make_material(received=0, cumulative=0, remaining=0):
    return {
        'received_quantity': Decimal(str(received)),
        'cumulative_usage': Decimal(str(cumulative)),
        'remaining_quantity': Decimal(str(remaining)),
    }


def assert_invariant(m: dict):
    assert m['received_quantity'] == m['cumulative_usage'] + m['remaining_quantity'], (
        f"Invariant broken: received={m['received_quantity']}, "
        f"cumulative={m['cumulative_usage']}, remaining={m['remaining_quantity']}"
    )


def approve_request(m: dict, qty: Decimal) -> dict:
    """Simulate approving a material request: deduct from remaining, add to cumulative."""
    new_remaining = max(Decimal('0'), m['remaining_quantity'] - qty)
    actual_deducted = m['remaining_quantity'] - new_remaining
    return {
        'received_quantity': m['received_quantity'],
        'cumulative_usage': m['cumulative_usage'] + actual_deducted,
        'remaining_quantity': new_remaining,
    }


class TestMaterialInvariant:
    def test_new_material_invariant(self):
        m = make_material(received=100, cumulative=0, remaining=100)
        assert_invariant(m)

    def test_after_approve_request(self):
        m = make_material(received=50, cumulative=10, remaining=40)
        assert_invariant(m)
        m2 = approve_request(m, Decimal('5'))
        assert_invariant(m2)
        assert m2['remaining_quantity'] == Decimal('35')
        assert m2['cumulative_usage'] == Decimal('15')

    def test_approve_exact_remaining(self):
        m = make_material(received=10, cumulative=0, remaining=10)
        m2 = approve_request(m, Decimal('10'))
        assert_invariant(m2)
        assert m2['remaining_quantity'] == Decimal('0')

    def test_approve_more_than_remaining_clamped(self):
        # remaining=3 but someone approved qty=5 → remaining clamped to 0
        m = make_material(received=10, cumulative=7, remaining=3)
        m2 = approve_request(m, Decimal('5'))
        assert_invariant(m2)
        assert m2['remaining_quantity'] == Decimal('0')
        assert m2['cumulative_usage'] == Decimal('10')

    def test_multiple_approvals(self):
        m = make_material(received=100, cumulative=0, remaining=100)
        for i in range(5):
            m = approve_request(m, Decimal('10'))
            assert_invariant(m)
        assert m['cumulative_usage'] == Decimal('50')
        assert m['remaining_quantity'] == Decimal('50')

    def test_quarantine_trust_a(self):
        # 信任A：保留 A 的值（quarantine resolved without changing numbers）
        m = make_material(received=20, cumulative=5, remaining=15)
        # Trust A = no change to invariant fields
        assert_invariant(m)

    def test_quarantine_trust_b(self):
        # 信任B：用 B 的數值覆蓋 A；invariant must still hold after applying new values
        # Simulating: B says received=20, remaining=14 → cumulative must be 6
        received_b = Decimal('20')
        remaining_b = Decimal('14')
        cumulative_b = received_b - remaining_b
        m_b = {
            'received_quantity': received_b,
            'cumulative_usage': cumulative_b,
            'remaining_quantity': remaining_b,
        }
        assert_invariant(m_b)
