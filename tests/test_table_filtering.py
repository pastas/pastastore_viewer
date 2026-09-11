# -*- coding: utf-8 -*-
"""Unit tests for column filtering in PastastoreMainDock."""

import pytest


def _has_qgis():
    """Check if QGIS environment is available."""
    try:
        from unittest.mock import MagicMock
        import qgis.core
        if isinstance(qgis.core, MagicMock) or getattr(qgis.core, "__is_mock__", False):
            return False
        from qgis.PyQt.QtWidgets import QWidget
        from qgis.PyQt.QtGui import QPixmap
        return True
    except (ImportError, ModuleNotFoundError, AttributeError):
        return False



@pytest.mark.unit
class TestMatchFilterValue:
    """Test match_filter_value helper function."""

    @pytest.fixture
    def match_func(self):
        """Return the filter matching static method."""
        if _has_qgis():
            from main_dock import PastastoreMainDock
            return PastastoreMainDock._match_filter_value

        # Standalone implementation matching PastastoreMainDock._match_filter_value
        def _match(val_str, filter_str):
            if val_str is None:
                val_str = ""
            else:
                val_str = str(val_str).strip()

            filter_str = filter_str.strip()
            if not filter_str:
                return True

            ops = [(">=", 2), ("<=", 2), ("!=", 2), (">", 1), ("<", 1), ("=", 1)]
            matched_op = None
            op_len = 0
            for op_str, length in ops:
                if filter_str.startswith(op_str):
                    matched_op = op_str
                    op_len = length
                    break

            if matched_op:
                target_str = filter_str[op_len:].strip()
                try:
                    val_num = float(val_str)
                    target_num = float(target_str)
                    if matched_op == ">=":
                        return val_num >= target_num
                    elif matched_op == "<=":
                        return val_num <= target_num
                    elif matched_op == ">":
                        return val_num > target_num
                    elif matched_op == "<":
                        return val_num < target_num
                    elif matched_op == "=":
                        return val_num == target_num
                    elif matched_op == "!=":
                        return val_num != target_num
                except ValueError:
                    val_lower = val_str.lower()
                    target_lower = target_str.lower()
                    if matched_op == "=":
                        return val_lower == target_lower
                    elif matched_op == "!=":
                        return val_lower != target_lower
                    elif matched_op == ">=":
                        return val_lower >= target_lower
                    elif matched_op == "<=":
                        return val_lower <= target_lower
                    elif matched_op == ">":
                        return val_lower > target_lower
                    elif matched_op == "<":
                        return val_lower < target_lower

            return filter_str.lower() in val_str.lower()

        return _match

    def test_empty_filter(self, match_func):
        """Empty filter string should match any value."""
        assert match_func("anything", "") is True
        assert match_func("123", "   ") is True
        assert match_func(None, "") is True

    def test_substring_matching(self, match_func):
        """Test case-insensitive substring matching."""
        assert match_func("PB01_01", "pb01") is True
        assert match_func("Groundwater", "water") is True
        assert match_func("PB01_01", "xyz") is False

    def test_numeric_greater_than(self, match_func):
        """Test numeric comparison > and >=."""
        assert match_func("150.5", "> 100") is True
        assert match_func("50", "> 100") is False
        assert match_func("100", ">= 100") is True
        assert match_func("99.9", ">= 100") is False

    def test_numeric_less_than(self, match_func):
        """Test numeric comparison < and <=."""
        assert match_func("0.75", "< 0.8") is True
        assert match_func("0.95", "< 0.8") is False
        assert match_func("0.8", "<= 0.8") is True
        assert match_func("0.81", "<= 0.8") is False

    def test_numeric_equality(self, match_func):
        """Test numeric comparison = and !=."""
        assert match_func("42.0", "= 42") is True
        assert match_func("43.0", "= 42") is False
        assert match_func("43.0", "!= 42") is True
        assert match_func("42.0", "!= 42") is False

    def test_string_equality_and_comparison(self, match_func):
        """Test string fallbacks for comparison operators."""
        assert match_func("alpha", "= alpha") is True
        assert match_func("alpha", "= ALPHA") is True
        assert match_func("alpha", "!= beta") is True
        assert match_func("beta", "> alpha") is True
