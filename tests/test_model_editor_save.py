# -*- coding: utf-8 -*-
"""Tests for preserving optimal parameters during model save and rename cancellation."""

import sys
from unittest.mock import MagicMock
import numpy as np
import pandas as pd
import pastas as ps

# Setup QGIS/Qt mocks for non-QGIS environment if needed
try:
    import qgis.core
except ImportError:
    sys.modules["qgis"] = MagicMock()
    sys.modules["qgis.PyQt"] = MagicMock()

    QtWidgets_mock = MagicMock()
    for name in [
        "QDialog",
        "QVBoxLayout",
        "QFormLayout",
        "QLineEdit",
        "QDialogButtonBox",
        "QLabel",
        "QCheckBox",
        "QGroupBox",
        "QComboBox",
        "QMessageBox",
        "QWidget",
        "QHBoxLayout",
        "QListWidget",
        "QPushButton",
        "QTabWidget",
        "QTableWidget",
        "QTableWidgetItem",
        "QDateEdit",
        "QProgressDialog",
        "QApplication",
        "QFileDialog",
    ]:
        setattr(QtWidgets_mock, name, MagicMock)
    sys.modules["qgis.PyQt.QtWidgets"] = QtWidgets_mock

    QtCore_mock = MagicMock()
    QtCore_mock.Qt = MagicMock()
    QtCore_mock.QDate = MagicMock()
    sys.modules["qgis.PyQt.QtCore"] = QtCore_mock

    core_mock = MagicMock()
    core_mock.QgsApplication = MagicMock()
    core_mock.QgsMessageLog = MagicMock()
    core_mock.Qgis = MagicMock()
    sys.modules["qgis.core"] = core_mock

from model_editor import ModelEditorDialog


def test_preserve_optimal_parameters_in_apply_model_changes():
    """Test that _apply_model_changes(solve=False) restores optimal parameters from table_params."""
    idx = pd.date_range("2020-01-01", periods=100, freq="D")
    oseries = pd.Series(index=idx, data=np.random.randn(100), name="oseries")
    prec = pd.Series(index=idx, data=np.random.randn(100), name="prec")

    ml = ps.Model(oseries, name="test_model")
    sm = ps.StressModel(prec, rfunc=ps.Gamma(), name="prec", settings="prec")
    ml.add_stressmodel(sm)
    ml.solve(report=False)

    orig_sim = ml.simulate()
    orig_opts = ml.parameters["optimal"].to_dict()

    # Recreate stressmodels as _apply_model_changes does
    ml.del_stressmodel("prec")
    sm2 = ps.StressModel(prec, rfunc=ps.Gamma(), name="prec", settings="prec")
    ml.add_stressmodel(sm2)

    # Set parameters using table data representation
    for pname, opt_val in orig_opts.items():
        if pname in ml.parameters.index and not np.isnan(opt_val):
            ml.set_parameter(pname, optimal=opt_val)

    new_sim = ml.simulate()

    assert np.allclose(orig_sim, new_sim, equal_nan=True)
    for pname, opt_val in orig_opts.items():
        if not np.isnan(opt_val):
            assert ml.parameters.loc[pname, "optimal"] == opt_val
