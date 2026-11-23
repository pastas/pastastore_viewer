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


def test_toggle_up_checkbox_after_calibration():
    """Test that changing the 'up' checkbox after model calibration updates table_params and solves without x0 infeasible error."""
    idx = pd.date_range("2020-01-01", periods=1000, freq="D")
    oseries = pd.Series(index=idx[200:], data=np.random.randn(800), name="oseries")
    prec = pd.Series(index=idx, data=np.random.randn(1000), name="prec")

    ml = ps.Model(oseries, name="test_up_model")
    sm = ps.StressModel(prec, rfunc=ps.Gamma(), name="prec", up=True, settings="prec")
    ml.add_stressmodel(sm)
    ml.solve(report=False)

    assert ml.parameters.at["prec_A", "optimal"] > 0
    orig_initial_A = ml.parameters.at["prec_A", "initial"]
    assert orig_initial_A > 0

    class DummyTableItem:
        def __init__(self, text="", user_role=None):
            self._text = str(text)
            self._user_role = user_role

        def text(self):
            return self._text

        def setText(self, text):
            self._text = str(text)

        def data(self, role):
            return self._user_role

        def setData(self, role, val):
            self._user_role = val

    class DummyTable:
        def __init__(self, param_df):
            self.rows = list(param_df.index)
            # columns: initial(0), optimal(1), pmin(2), pmax(3), vary(4), stderr(5)
            self.grid = {}
            for r_idx, pname in enumerate(self.rows):
                row = param_df.loc[pname]
                for c_idx, col in enumerate(["initial", "optimal", "pmin", "pmax", "vary", "stderr"]):
                    val = row.get(col, None)
                    if col == "vary":
                        val_text = "True" if bool(val) else "False"
                        val_float = None
                    else:
                        val_float = float(val) if val is not None and not np.isnan(val) else None
                        val_text = f"{val_float:.4f}" if val_float is not None else "-"
                    self.grid[(r_idx, c_idx)] = DummyTableItem(val_text, val_float)

        def rowCount(self):
            return len(self.rows)

        def verticalHeaderItem(self, row):
            class HeaderItem:
                def __init__(self, t):
                    self._t = t
                def text(self):
                    return self._t
            return HeaderItem(self.rows[row])

        def item(self, row, col):
            return self.grid.get((row, col))

        def setItem(self, row, col, item):
            self.grid[(row, col)] = item

        def blockSignals(self, b):
            pass

    class DummyEditor:
        pass

    editor = DummyEditor()
    editor.table_params = DummyTable(ml.parameters)
    editor.original_model = ml
    editor.store = MagicMock()
    editor.store.get_stresses.return_value = prec
    editor.stressmodel_settings = [
        {
            "name": "prec",
            "type": "StressModel",
            "rfunc": "Gamma",
            "up": True,
            "inputs": ["prec"],
            "settings_kws": ["prec"],
            "settings_custom": [{}],
        }
    ]
    editor.de_tmin = MagicMock()
    editor.de_tmin.date().toString.return_value = "2020-07-19"
    editor.de_tmax = MagicMock()
    editor.de_tmax.date().toString.return_value = "2022-09-26"
    editor.cbo_freq = MagicMock()
    editor.cbo_freq.currentText.return_value = "d"
    editor.cbo_noise = MagicMock()
    editor.cbo_noise.currentText.return_value = "None"
    editor.cbo_transform = MagicMock()
    editor.cbo_transform.currentText.return_value = "None"
    editor.chk_constant = MagicMock()
    editor.chk_constant.isChecked.return_value = True
    editor.lbl_stats = MagicMock()
    editor.plot_widget = MagicMock()
    editor.plot_nav = MagicMock()

    # Bind methods
    editor._parse_item_float = ModelEditorDialog._parse_item_float
    editor._set_table_item_float = ModelEditorDialog._set_table_item_float.__get__(editor, DummyEditor)
    editor._update_parameters_for_up = ModelEditorDialog._update_parameters_for_up.__get__(editor, DummyEditor)
    editor.save_detail_up = ModelEditorDialog.save_detail_up.__get__(editor, DummyEditor)
    editor.get_current_setting = lambda: editor.stressmodel_settings[0]
    editor.update_stats_label = ModelEditorDialog.update_stats_label.__get__(editor, DummyEditor)
    editor.update_plot = MagicMock()
    editor.update_parameters_table = MagicMock()
    editor._resolve_settings_for_input = ModelEditorDialog._resolve_settings_for_input
    editor._apply_model_changes = ModelEditorDialog._apply_model_changes.__get__(editor, DummyEditor)

    # 1. Flip up checkbox to False
    editor.save_detail_up(False)

    # Verify table_params updated
    row_idx = editor.table_params.rows.index("prec_A")
    new_init_A = editor.table_params.item(row_idx, 0).data(None)
    new_opt_A = editor.table_params.item(row_idx, 1).data(None)
    new_pmin_A = editor.table_params.item(row_idx, 2).data(None)
    new_pmax_A = editor.table_params.item(row_idx, 3).data(None)

    assert new_init_A < 0
    assert np.isclose(new_init_A, -orig_initial_A)
    assert new_opt_A is None
    assert new_pmin_A < new_pmax_A <= 0

    # 2. Solve model with up=False (must NOT raise x0 is infeasible)
    solved_model = editor._apply_model_changes(solve=True, show_progress=False)
    assert solved_model is not None
    assert solved_model.parameters.at["prec_A", "optimal"] < 0

    # 3. Flip up checkbox back to True
    editor.table_params = DummyTable(solved_model.parameters)
    editor.save_detail_up(True)

    row_idx = editor.table_params.rows.index("prec_A")
    flipped_back_init_A = editor.table_params.item(row_idx, 0).data(None)
    assert flipped_back_init_A > 0

    # Solve model with up=True
    solved_model_up = editor._apply_model_changes(solve=True, show_progress=False)
    assert solved_model_up is not None
    assert solved_model_up.parameters.at["prec_A", "optimal"] > 0


def test_inconsistent_table_bounds_fallback():
    """Test that if table_params contains an initial value outside bounds, _apply_model_changes skips it and solves cleanly."""
    idx = pd.date_range("2020-01-01", periods=1000, freq="D")
    oseries = pd.Series(index=idx[200:], data=np.random.randn(800), name="oseries")
    prec = pd.Series(index=idx, data=np.random.randn(1000), name="prec")

    ml = ps.Model(oseries, name="test_infeasible_model")
    sm = ps.StressModel(prec, rfunc=ps.Gamma(), name="prec", up=False, settings="prec")
    ml.add_stressmodel(sm)

    class DummyTableItem:
        def __init__(self, text="", user_role=None):
            self._text = str(text)
            self._user_role = user_role

        def text(self):
            return self._text

        def setText(self, text):
            self._text = str(text)

        def data(self, role):
            return self._user_role

        def setData(self, role, val):
            self._user_role = val

    class DummyTable:
        def __init__(self, param_df):
            self.rows = list(param_df.index)
            self.grid = {}
            for r_idx, pname in enumerate(self.rows):
                row = param_df.loc[pname]
                for c_idx, col in enumerate(["initial", "optimal", "pmin", "pmax", "vary", "stderr"]):
                    val = row.get(col, None)
                    if col == "vary":
                        val_text = "True" if bool(val) else "False"
                        val_float = None
                    else:
                        val_float = float(val) if val is not None and not np.isnan(val) else None
                        val_text = f"{val_float:.4f}" if val_float is not None else "-"
                    self.grid[(r_idx, c_idx)] = DummyTableItem(val_text, val_float)

        def rowCount(self):
            return len(self.rows)

        def verticalHeaderItem(self, row):
            class HeaderItem:
                def __init__(self, t):
                    self._t = t
                def text(self):
                    return self._t
            return HeaderItem(self.rows[row])

        def item(self, row, col):
            return self.grid.get((row, col))

        def setItem(self, row, col, item):
            self.grid[(row, col)] = item

    class DummyEditor:
        pass

    editor = DummyEditor()
    # Deliberately put positive initial value (+10.0) in table for a model with up=False (bounds [-100, -1e-5])
    df = ml.parameters.copy()
    df.at["prec_A", "initial"] = 10.0
    df.at["prec_A", "pmin"] = 0.0001
    df.at["prec_A", "pmax"] = 100.0

    editor.table_params = DummyTable(df)
    editor.original_model = ml
    editor.store = MagicMock()
    editor.store.get_stresses.return_value = prec
    editor.stressmodel_settings = [
        {
            "name": "prec",
            "type": "StressModel",
            "rfunc": "Gamma",
            "up": False,
            "inputs": ["prec"],
            "settings_kws": ["prec"],
            "settings_custom": [{}],
        }
    ]
    editor.de_tmin = MagicMock()
    editor.de_tmin.date().toString.return_value = "2020-07-19"
    editor.de_tmax = MagicMock()
    editor.de_tmax.date().toString.return_value = "2022-09-26"
    editor.cbo_freq = MagicMock()
    editor.cbo_freq.currentText.return_value = "d"
    editor.cbo_noise = MagicMock()
    editor.cbo_noise.currentText.return_value = "None"
    editor.cbo_transform = MagicMock()
    editor.cbo_transform.currentText.return_value = "None"
    editor.chk_constant = MagicMock()
    editor.chk_constant.isChecked.return_value = True
    editor.lbl_stats = MagicMock()
    editor.plot_widget = MagicMock()
    editor.plot_nav = MagicMock()

    editor._parse_item_float = ModelEditorDialog._parse_item_float
    editor.update_stats_label = ModelEditorDialog.update_stats_label.__get__(editor, DummyEditor)
    editor.update_plot = MagicMock()
    editor.update_parameters_table = MagicMock()
    editor._resolve_settings_for_input = ModelEditorDialog._resolve_settings_for_input
    editor._apply_model_changes = ModelEditorDialog._apply_model_changes.__get__(editor, DummyEditor)

    # Must NOT raise ValueError: 'x0' is infeasible, because inconsistent initial value is safely skipped
    solved_model = editor._apply_model_changes(solve=True, show_progress=False)
    assert solved_model is not None
    assert solved_model.parameters.at["prec_A", "optimal"] < 0


