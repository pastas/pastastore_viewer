# -*- coding: utf-8 -*-
from unittest.mock import MagicMock
import numpy as np
import pandas as pd
import pastas as ps
import pytest
from results_plot import _get_stress_name, calculate_subplot_heights


def test_get_stress_name_various_models():
    idx = pd.date_range("2020-01-01", periods=100)
    s1 = pd.Series(np.random.randn(100), index=idx, name="prec_1")
    s2 = pd.Series(np.random.randn(100), index=idx, name="evap_1")

    # StressModel
    sm1 = ps.StressModel(s1, rfunc=ps.Gamma(), name="sm1")
    assert _get_stress_name(sm1, 0) == "prec_1"
    assert _get_stress_name(sm1, 1) is None

    # RechargeModel
    rch = ps.RechargeModel(s1, s2, rfunc=ps.Gamma(), name="rch")
    assert _get_stress_name(rch, 0) == "prec_1"
    assert _get_stress_name(rch, 1) == "evap_1"
    assert _get_stress_name(rch, 2) is None

    # StepModel (no stresses)
    step = ps.StepModel(pd.Timestamp("2020-01-15"), rfunc=ps.Gamma(), name="step")
    assert _get_stress_name(step, 0) is None


def test_get_stress_name_time_series_object_without_len():
    """Verify that if sm.stress is a single TimeSeries object (no len), it does not crash."""
    mock_sm = MagicMock()
    mock_ts = MagicMock()
    mock_ts.name = "single_ts"
    # Make len(mock_ts) raise TypeError, simulating a TimeSeries object without len()
    del mock_ts.__len__
    
    mock_sm.stresses = None
    mock_sm.stress = mock_ts

    assert _get_stress_name(mock_sm, 0) == "single_ts"
    assert _get_stress_name(mock_sm, 1) is None


@pytest.mark.unit
def test_calculate_subplot_heights_fills_exact_height_and_equal_scale():
    ranges = [2.0, 0.5, 1.5, 0.8]
    available_height = 859
    title_overhead = 32
    bottom_axis_overhead = 20
    spacing = 10

    heights = calculate_subplot_heights(
        ranges,
        available_height,
        title_overhead=title_overhead,
        bottom_axis_overhead=bottom_axis_overhead,
        spacing=spacing,
    )

    assert len(heights) == len(ranges)
    assert sum(heights) + (len(ranges) - 1) * spacing == available_height

    overheads = [title_overhead] * (len(ranges) - 1) + [
        title_overhead + bottom_axis_overhead
    ]
    ppus = [(h - oh) / r for h, oh, r in zip(heights, overheads, ranges)]
    # All subplots share the same vertical scale within rounding error
    assert max(ppus) - min(ppus) < 2.5


@pytest.mark.unit
def test_calculate_subplot_heights_edge_cases():
    # Empty input
    assert calculate_subplot_heights([], 800) == []

    # Single plot fills full height
    assert calculate_subplot_heights([1.5], 600, spacing=10) == [600]

    # Very tiny range still gets minimum usable height and exact total
    heights = calculate_subplot_heights([10.0, 0.0001, 2.0], 800, spacing=10)
    assert sum(heights) + 2 * 10 == 800
    assert heights[1] >= 45
    assert all(h > 0 for h in heights)

    # Zero / NaN ranges do not crash and still fill height
    heights_nan = calculate_subplot_heights([0.0, np.nan, 1.0], 500, spacing=10)
    assert sum(heights_nan) + 2 * 10 == 500
    assert all(h > 0 for h in heights_nan)

    # Very small window never produces negative heights and stays within budget
    heights_small = calculate_subplot_heights([2.0, 1.0, 1.5, 0.5], 120, spacing=10)
    assert all(h >= 1 for h in heights_small)
    assert sum(heights_small) + 3 * 10 == 120
