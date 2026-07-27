"""
Unit tests for collab (共同作業) distribution formulas.
No DB — tests the mathematical rules only.
"""


def collab_count(collab_ids: list) -> int:
    return 1 + len(collab_ids)


def distribute_qty(qty: float, count: int) -> float:
    return qty / count


def filter_collab_ids(raw_ids, submitter_id, valid_ids, max_collabs=6):
    """Mirror the backend filter: remove submitter, keep only valid, cap at 6."""
    filtered = [i for i in raw_ids if i != submitter_id and i in valid_ids]
    return filtered[:max_collabs]


class TestCollabCount:
    def test_no_collab(self):
        assert collab_count([]) == 1

    def test_one_collab(self):
        assert collab_count([42]) == 2

    def test_six_collabs(self):
        assert collab_count(list(range(6))) == 7

    def test_max_cap_enforced(self):
        raw = list(range(10))
        capped = raw[:6]
        assert len(capped) == 6
        assert collab_count(capped) == 7


class TestDistribution:
    def test_exact_split(self):
        assert distribute_qty(6, 2) == 3.0

    def test_fractional_split(self):
        result = distribute_qty(1, 3)
        assert abs(result - 1 / 3) < 1e-9

    def test_single_person(self):
        assert distribute_qty(5.5, 1) == 5.5

    def test_zero_qty(self):
        assert distribute_qty(0, 3) == 0.0


class TestCollabFilter:
    def test_submitter_excluded(self):
        raw_ids = [1, 2, 3]
        valid = {1, 2, 3}
        result = filter_collab_ids(raw_ids, submitter_id=1, valid_ids=valid)
        assert 1 not in result

    def test_invalid_ids_excluded(self):
        raw_ids = [10, 99, 20]
        valid = {10, 20}
        result = filter_collab_ids(raw_ids, submitter_id=0, valid_ids=valid)
        assert result == [10, 20]

    def test_cap_at_six(self):
        raw_ids = list(range(1, 10))
        valid = set(raw_ids)
        result = filter_collab_ids(raw_ids, submitter_id=0, valid_ids=valid)
        assert len(result) == 6
