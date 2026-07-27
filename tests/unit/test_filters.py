"""
Unit tests for Jinja2 template filters.
Imports filter functions directly from app (no HTTP, no DB).
"""
from datetime import datetime

from app import (
    money_filter,
    from_json_filter,
    qty_filter,
    mat_qty_filter,
    tw_time_filter,
)


class TestMoneyFilter:
    def test_integer_comma_format(self):
        assert money_filter(1234567) == '1,234,567'

    def test_zero(self):
        assert money_filter(0) == '0'

    def test_small_integer(self):
        assert money_filter(500) == '500'

    def test_float_whole(self):
        assert money_filter(1000.0) == '1,000'

    def test_float_with_cents(self):
        result = money_filter(1234.56)
        assert '1,234' in result and '56' in result

    def test_non_numeric(self):
        # Returns str(value) unchanged
        result = money_filter('abc')
        assert result == 'abc'


class TestFromJsonFilter:
    def test_valid_dict(self):
        result = from_json_filter('{"a": 1}')
        assert result == {'a': 1}

    def test_valid_list(self):
        result = from_json_filter('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_empty_string_returns_list(self):
        assert from_json_filter('') == []

    def test_none_returns_list(self):
        assert from_json_filter(None) == []

    def test_invalid_json_returns_list(self):
        assert from_json_filter('not-json') == []

    def test_valid_json_int(self):
        # A bare JSON integer is also valid JSON
        result = from_json_filter('42')
        assert result == 42


class TestQtyFilter:
    def test_zero_returns_empty(self):
        assert qty_filter(0) == ''

    def test_zero_float_returns_empty(self):
        assert qty_filter(0.0) == ''

    def test_none_returns_empty(self):
        assert qty_filter(None) == ''

    def test_integer_value(self):
        assert qty_filter(3) == '3'

    def test_whole_float(self):
        assert qty_filter(3.0) == '3'

    def test_decimal_value(self):
        assert qty_filter(3.5) == '3.5'


class TestMatQtyFilter:
    def test_none_returns_zero(self):
        assert mat_qty_filter(None) == '0'

    def test_whole_number(self):
        assert mat_qty_filter(1) == '1'

    def test_whole_float(self):
        assert mat_qty_filter(1.000) == '1'

    def test_decimal_trimmed(self):
        result = mat_qty_filter(1.5)
        assert result == '1.5'

    def test_trailing_zeros_stripped(self):
        result = mat_qty_filter(1.500)
        assert result == '1.5'


class TestTwTimeFilter:
    def test_none_returns_empty(self):
        assert tw_time_filter(None) == ''

    def test_formats_correctly(self):
        dt = datetime(2026, 7, 27, 14, 30, 0)
        assert tw_time_filter(dt) == '2026-07-27 14:30'

    def test_midnight(self):
        dt = datetime(2026, 1, 1, 0, 0, 0)
        assert tw_time_filter(dt) == '2026-01-01 00:00'
