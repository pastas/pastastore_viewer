# -*- coding: utf-8 -*-
"""Tests for the stress date-range label in the stressmodels detail panel."""
import sys
import types
from unittest.mock import MagicMock
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Minimal PyQt5 / QGIS stubs (mirrors pattern from test_model_editor_dates.py)
# ---------------------------------------------------------------------------
class MockWidgetMeta(type):
    def __getattr__(cls, name):
        return MagicMock()


class MockWidget(metaclass=MockWidgetMeta):
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return MagicMock()


try:
    import qgis.core  # noqa: F401
except ImportError:
    sys.modules["qgis"] = MagicMock()
    sys.modules["qgis.PyQt"] = MagicMock()

    QtWidgets_mock = MagicMock()
    for _name in [
        "QDialog", "QVBoxLayout", "QFormLayout", "QLineEdit", "QDialogButtonBox",
        "QLabel", "QCheckBox", "QGroupBox", "QComboBox", "QMessageBox",
        "QWidget", "QHBoxLayout", "QListWidget", "QPushButton", "QTabWidget",
        "QTableWidget", "QTableWidgetItem", "QDateEdit", "QProgressDialog",
        "QApplication", "QFileDialog",
    ]:
        setattr(QtWidgets_mock, _name, MockWidget)
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

from model_editor import ModelEditorDialog  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_series(start, end, freq="D"):
    idx = pd.date_range(start, end, freq=freq)
    return pd.Series(np.ones(len(idx)), index=idx)


class _FakeLabel:
    def __init__(self):
        self._text = ""
        self._visible = True

    def setText(self, t):
        self._text = t

    def text(self):
        return self._text

    def setVisible(self, v):
        self._visible = v

    def isVisible(self):
        return self._visible


class _FakeFormLayout:
    """Returns a fresh stub label for every labelForField call."""
    def labelForField(self, widget):
        return _FakeLabel()


class _FakeList:
    def __init__(self, row=0):
        self._row = row

    def currentRow(self):
        return self._row


def _build_dialog(input_names, type_name="StressModel", series_map=None):
    """
    Instantiate ModelEditorDialog without calling __init__, then inject the
    minimal state needed to exercise *_update_stress_range_label* and
    *_get_stress_series_by_name*.
    """

    class _FakeModel:
        stressmodels = {}
        settings = {}
        parameters = pd.DataFrame(
            columns=["initial", "pmin", "pmax", "vary", "optimal", "stderr"]
        )
        oseries = types.SimpleNamespace(series=pd.Series(dtype=float))
        name = "test_model"

    class _FakeStore:
        def __init__(self, mapping):
            self._map = mapping

        def get_stresses(self, name):
            if name in self._map:
                return self._map[name]
            raise KeyError(name)

    dlg = object.__new__(ModelEditorDialog)
    dlg.original_model = _FakeModel()
    dlg.store = _FakeStore(series_map or {})
    dlg.stressmodel_settings = [
        {
            "name": "sm1",
            "type": type_name,
            "inputs": list(input_names),
            "rfunc": "Gamma",
            "up": True,
            "recharge": "Linear",
            "settings_kws": ["prec"] * len(input_names),
            "settings_custom": [{}] * len(input_names),
            "parameters": [],
        }
    ]
    dlg.lbl_stress_range = _FakeLabel()
    dlg.form_detail = _FakeFormLayout()
    dlg.list_stresses = _FakeList(row=0)
    return dlg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_label_shows_range_single_input():
    s = _make_series("2010-01-01", "2020-12-31")
    dlg = _build_dialog(["prec"], series_map={"prec": s})
    dlg._update_stress_range_label()
    text = dlg.lbl_stress_range.text()
    assert "2010-01-01" in text
    assert "2020-12-31" in text
    assert dlg.lbl_stress_range.isVisible()


def test_label_shows_range_two_inputs():
    s1 = _make_series("2000-01-01", "2015-06-30")
    s2 = _make_series("2005-03-01", "2020-09-30")
    dlg = _build_dialog(
        ["prec", "evap"],
        type_name="RechargeModel",
        series_map={"prec": s1, "evap": s2},
    )
    dlg._update_stress_range_label()
    text = dlg.lbl_stress_range.text()
    assert "2000-01-01" in text
    assert "2015-06-30" in text
    assert "2005-03-01" in text
    assert "2020-09-30" in text
    assert dlg.lbl_stress_range.isVisible()


def test_label_hidden_when_no_inputs():
    dlg = _build_dialog([], type_name="LinearTrend")
    dlg._update_stress_range_label()
    assert not dlg.lbl_stress_range.isVisible()
    assert dlg.lbl_stress_range.text() == ""


def test_label_no_data_when_series_missing():
    dlg = _build_dialog(["ghost_stress"], series_map={})
    dlg._update_stress_range_label()
    text = dlg.lbl_stress_range.text()
    # Should show "(no data)" indicator when input exists but series not found
    assert "no data" in text


def test_label_hidden_when_no_setting():
    dlg = _build_dialog(["prec"])
    dlg.stressmodel_settings = []
    dlg.list_stresses = _FakeList(row=-1)
    dlg._update_stress_range_label()
    assert not dlg.lbl_stress_range.isVisible()


def test_label_uses_series_original_attribute():
    """When the store returns an object with series_original, that attr is used."""
    raw = _make_series("1990-01-01", "2000-12-31")

    class _TimeSeries:
        series_original = raw

    dlg = _build_dialog(["prec"], series_map={"prec": _TimeSeries()})
    dlg._update_stress_range_label()
    text = dlg.lbl_stress_range.text()
    assert "1990-01-01" in text
    assert "2000-12-31" in text
