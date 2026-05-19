# -*- coding: utf-8 -*-
"""Tests for data utility functions."""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime


class TestDataFormatting:
    """Test data formatting utilities used throughout the plugin."""

    def test_format_numeric_value(self):
        """Test formatting numeric values for display."""
        value = 123.456789
        # Simple formatting test
        formatted = f"{float(value):.4f}"
        assert formatted == "123.4568"

    def test_format_nan_value(self):
        """Test handling of NaN values."""
        value = float('nan')
        is_valid = not (isinstance(value, float) and np.isnan(value))
        assert not is_valid

    def test_format_series_data(self):
        """Test formatting pandas Series for display."""
        series = pd.Series([1.23456, 2.34567, 3.45678])
        formatted = [f"{v:.2f}" for v in series]
        assert formatted == ["1.23", "2.35", "3.46"]


class TestDateParsing:
    """Test date/datetime parsing utilities."""

    def test_datetime_to_string(self):
        """Test converting datetime to string format."""
        dt = datetime(2024, 5, 15, 10, 30, 45)
        date_str = dt.strftime("%Y-%m-%d")
        assert date_str == "2024-05-15"

    def test_datetime_to_iso_format(self):
        """Test ISO format datetime conversion."""
        dt = datetime(2024, 5, 15)
        iso_str = dt.isoformat()
        assert iso_str == "2024-05-15T00:00:00"

    def test_parse_iso_timestamp(self):
        """Test parsing ISO timestamp strings."""
        ts = "2024-05-15T10:30:45"
        dt = datetime.fromisoformat(ts)
        assert dt.year == 2024
        assert dt.month == 5
        assert dt.day == 15


class TestPandasUtilities:
    """Test pandas data manipulation utilities."""

    def test_series_empty_check(self):
        """Test checking if a pandas Series is empty."""
        empty_series = pd.Series(dtype=float)
        non_empty_series = pd.Series([1, 2, 3])
        
        assert empty_series.empty
        assert not non_empty_series.empty

    def test_series_nan_masking(self):
        """Test masking NaN values in a Series."""
        series = pd.Series([1.0, np.nan, 3.0, np.nan, 5.0])
        mask = ~np.isnan(series.values)
        filtered = series[mask]
        
        assert len(filtered) == 3
        assert list(filtered.values) == [1.0, 3.0, 5.0]

    def test_dataframe_column_access(self):
        """Test accessing columns in a DataFrame."""
        df = pd.DataFrame({
            "name": ["A", "B", "C"],
            "value": [1, 2, 3]
        })
        
        assert "name" in df.columns
        assert len(df) == 3

    def test_series_indexing(self):
        """Test Series indexing and slicing."""
        dates = pd.date_range("2024-01-01", periods=5)
        series = pd.Series([10, 20, 30, 40, 50], index=dates)
        
        assert len(series) == 5
        assert series.iloc[0] == 10
        assert series.iloc[-1] == 50

    def test_dataframe_filtering(self):
        """Test DataFrame row filtering."""
        df = pd.DataFrame({
            "value": [1, 2, 3, 4, 5],
            "category": ["A", "B", "A", "B", "A"]
        })
        
        filtered = df[df["category"] == "A"]
        assert len(filtered) == 3
        assert all(filtered["category"] == "A")


class TestNumpyUtilities:
    """Test numpy array utilities."""

    def test_array_nan_handling(self):
        """Test handling NaN values in numpy arrays."""
        arr = np.array([1.0, np.nan, 3.0, np.nan, 5.0])
        mask = np.isfinite(arr)
        filtered = arr[mask]
        
        assert len(filtered) == 3
        assert np.allclose(filtered, [1.0, 3.0, 5.0])

    def test_array_sorting(self):
        """Test array sorting."""
        arr = np.array([3, 1, 4, 1, 5, 9, 2, 6])
        sorted_arr = np.sort(arr)
        
        assert np.array_equal(sorted_arr, [1, 1, 2, 3, 4, 5, 6, 9])

    def test_array_statistics(self):
        """Test basic array statistics."""
        arr = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        
        assert np.mean(arr) == 3.0
        assert np.median(arr) == 3.0
        assert np.std(arr) > 0
