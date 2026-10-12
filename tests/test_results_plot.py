# -*- coding: utf-8 -*-
from unittest.mock import MagicMock
import numpy as np
import pandas as pd
import pastas as ps
from results_plot import _get_stress_name


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
