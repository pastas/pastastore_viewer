# -*- coding: utf-8 -*-
"""Tests for Tmin/Tmax observation and stresses date helper buttons in ModelEditorDialog."""

import sys
from unittest.mock import MagicMock
import numpy as np
import pandas as pd
import pastas as ps

# Setup QGIS mocks if in non-QGIS environment
class MockWidgetMeta(type):
    def __getattr__(cls, name):
        return MagicMock()

class MockWidget(metaclass=MockWidgetMeta):
    def __init__(self, *args, **kwargs):
        pass
    def __getattr__(self, name):
        return MagicMock()

try:
    import qgis.core
except ImportError:
    sys.modules["qgis"] = MagicMock()
    sys.modules["qgis.PyQt"] = MagicMock()

    QtWidgets_mock = MagicMock()
    for name in [
        "QDialog", "QVBoxLayout", "QFormLayout", "QLineEdit", "QDialogButtonBox",
        "QLabel", "QCheckBox", "QGroupBox", "QComboBox", "QMessageBox",
        "QWidget", "QHBoxLayout", "QListWidget", "QPushButton", "QTabWidget",
        "QTableWidget", "QTableWidgetItem", "QDateEdit", "QProgressDialog",
        "QApplication", "QFileDialog",
    ]:
        setattr(QtWidgets_mock, name, MockWidget)
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


class FakeQDate:
    def __init__(self, year, month, day):
        self.year = year
        self.month = month
        self.day = day

    def toString(self, fmt="yyyy-MM-dd"):
        return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"

    def toPyDate(self):
        import datetime
        return datetime.date(self.year, self.month, self.day)

    def __lt__(self, other):
        return self.toPyDate() < other.toPyDate()

    def __le__(self, other):
        return self.toPyDate() <= other.toPyDate()

    def __gt__(self, other):
        return self.toPyDate() > other.toPyDate()

    def __ge__(self, other):
        return self.toPyDate() >= other.toPyDate()

    def __eq__(self, other):
        return isinstance(other, FakeQDate) and self.toPyDate() == other.toPyDate()


class FakeQDateEdit:
    def __init__(self, initial_date=None):
        self._date = initial_date or FakeQDate(2020, 1, 1)
        self._min_date = FakeQDate(1900, 1, 1)
        self._max_date = FakeQDate(2100, 1, 1)

    def date(self):
        return self._date

    def setDate(self, d):
        self._date = d

    def minimumDate(self):
        return self._min_date

    def setMinimumDate(self, d):
        self._min_date = d

    def maximumDate(self):
        return self._max_date

    def setMaximumDate(self, d):
        self._max_date = d


def _setup_test_models():
    """Create test observation and two stresses with known different date ranges."""
    # oseries: 2015-06-01 to 2021-12-31
    obs_idx = pd.date_range("2015-06-01", "2021-12-31", freq="D")
    oseries = pd.Series(index=obs_idx, data=np.random.randn(len(obs_idx)), name="head")

    # prec: 2010-01-01 to 2022-01-01
    prec_idx = pd.date_range("2010-01-01", "2022-01-01", freq="D")
    prec = pd.Series(index=prec_idx, data=np.random.randn(len(prec_idx)), name="prec")

    # evap: 2012-01-01 to 2020-06-01
    evap_idx = pd.date_range("2012-01-01", "2020-06-01", freq="D")
    evap = pd.Series(index=evap_idx, data=np.random.randn(len(evap_idx)), name="evap")

    ml = ps.Model(oseries, name="date_test_model")
    sm1 = ps.StressModel(prec, rfunc=ps.Gamma(), name="prec", settings="prec")
    sm2 = ps.StressModel(evap, rfunc=ps.Gamma(), name="evap", settings="evap")
    ml.add_stressmodel(sm1)
    ml.add_stressmodel(sm2)

    class MockStore:
        def __init__(self, series_dict):
            self.series_dict = series_dict
            self.stresses = pd.DataFrame(index=list(series_dict.keys()))

        def get_stresses(self, name):
            return self.series_dict[name]

    store = MockStore({"prec": prec, "evap": evap})
    return ml, store, oseries, prec, evap


def test_get_observation_range():
    ml, store, oseries, prec, evap = _setup_test_models()

    class DummyEditor:
        pass

    editor = DummyEditor()
    editor.original_model = ml
    editor._get_observation_range = ModelEditorDialog._get_observation_range.__get__(editor, DummyEditor)

    first_obs, last_obs = editor._get_observation_range()
    assert first_obs == pd.Timestamp("2015-06-01")
    assert last_obs == pd.Timestamp("2021-12-31")


def test_get_stresses_common_range():
    ml, store, oseries, prec, evap = _setup_test_models()

    class DummyEditor:
        pass

    editor = DummyEditor()
    editor.original_model = ml
    editor.store = store
    editor.stressmodel_settings = [
        {"name": "prec", "inputs": ["prec"], "type": "StressModel"},
        {"name": "evap", "inputs": ["evap"], "type": "StressModel"},
    ]
    editor._get_all_stress_series = ModelEditorDialog._get_all_stress_series.__get__(editor, DummyEditor)
    editor._get_stresses_common_range = ModelEditorDialog._get_stresses_common_range.__get__(editor, DummyEditor)

    first_all, last_all = editor._get_stresses_common_range()
    # prec starts 2010-01-01, evap starts 2012-01-01 -> max(starts) is 2012-01-01
    assert first_all == pd.Timestamp("2012-01-01")
    # prec ends 2022-01-01, evap ends 2020-06-01 -> min(ends) is 2020-06-01
    assert last_all == pd.Timestamp("2020-06-01")


def test_set_tmin_and_tmax_buttons(monkeypatch):
    ml, store, oseries, prec, evap = _setup_test_models()

    import model_editor
    monkeypatch.setattr(model_editor, "QDate", FakeQDate)

    class DummyEditor:
        pass

    editor = DummyEditor()
    editor.original_model = ml
    editor.store = store
    editor.stressmodel_settings = [
        {"name": "prec", "inputs": ["prec"], "type": "StressModel"},
        {"name": "evap", "inputs": ["evap"], "type": "StressModel"},
    ]
    editor.de_tmin = FakeQDateEdit(FakeQDate(2018, 1, 1))
    editor.de_tmax = FakeQDateEdit(FakeQDate(2018, 1, 1))

    # Bind methods
    editor._get_observation_range = ModelEditorDialog._get_observation_range.__get__(editor, DummyEditor)
    editor._get_all_stress_series = ModelEditorDialog._get_all_stress_series.__get__(editor, DummyEditor)
    editor._get_stresses_common_range = ModelEditorDialog._get_stresses_common_range.__get__(editor, DummyEditor)
    editor.set_tmin_to_first_observation = ModelEditorDialog.set_tmin_to_first_observation.__get__(editor, DummyEditor)
    editor.set_tmin_to_first_all_stresses = ModelEditorDialog.set_tmin_to_first_all_stresses.__get__(editor, DummyEditor)
    editor.set_tmax_to_last_observation = ModelEditorDialog.set_tmax_to_last_observation.__get__(editor, DummyEditor)
    editor.set_tmax_to_last_all_stresses = ModelEditorDialog.set_tmax_to_last_all_stresses.__get__(editor, DummyEditor)

    # 1. Set tmin to first observation (2015-06-01)
    editor.set_tmin_to_first_observation()
    assert editor.de_tmin.date().toString() == "2015-06-01"

    # 2. Set tmin to first moment all stresses are available (2012-01-01)
    editor.set_tmin_to_first_all_stresses()
    assert editor.de_tmin.date().toString() == "2012-01-01"

    # 3. Set tmax to last observation (2021-12-31)
    editor.set_tmax_to_last_observation()
    assert editor.de_tmax.date().toString() == "2021-12-31"

    # 4. Set tmax to last moment all stresses are available (2020-06-01)
    editor.set_tmax_to_last_all_stresses()
    assert editor.de_tmax.date().toString() == "2020-06-01"


def test_missing_data_handling(monkeypatch):
    """Test graceful handling when no observation or stress series exist."""
    import model_editor
    monkeypatch.setattr(model_editor, "QDate", FakeQDate)

    class DummyEditor:
        pass

    editor = DummyEditor()
    editor.original_model = None
    editor.store = None
    editor.stressmodel_settings = []
    editor.de_tmin = FakeQDateEdit(FakeQDate(2018, 1, 1))
    editor.de_tmax = FakeQDateEdit(FakeQDate(2018, 1, 1))

    # Mock QMessageBox
    mock_msg = MagicMock()
    monkeypatch.setattr(model_editor.QMessageBox, "information", mock_msg)

    editor._get_observation_range = ModelEditorDialog._get_observation_range.__get__(editor, DummyEditor)
    editor._get_all_stress_series = ModelEditorDialog._get_all_stress_series.__get__(editor, DummyEditor)
    editor._get_stresses_common_range = ModelEditorDialog._get_stresses_common_range.__get__(editor, DummyEditor)
    editor.set_tmin_to_first_observation = ModelEditorDialog.set_tmin_to_first_observation.__get__(editor, DummyEditor)
    editor.set_tmin_to_first_all_stresses = ModelEditorDialog.set_tmin_to_first_all_stresses.__get__(editor, DummyEditor)
    editor.set_tmax_to_last_observation = ModelEditorDialog.set_tmax_to_last_observation.__get__(editor, DummyEditor)
    editor.set_tmax_to_last_all_stresses = ModelEditorDialog.set_tmax_to_last_all_stresses.__get__(editor, DummyEditor)

    editor.set_tmin_to_first_observation()
    assert mock_msg.called
    assert editor.de_tmin.date().toString() == "2018-01-01"  # Unchanged

    mock_msg.reset_mock()
    editor.set_tmin_to_first_all_stresses()
    assert mock_msg.called

    mock_msg.reset_mock()
    editor.set_tmax_to_last_observation()
    assert mock_msg.called

    mock_msg.reset_mock()
    editor.set_tmax_to_last_all_stresses()
    assert mock_msg.called


def test_bounds_expansion_when_setting_date(monkeypatch):
    """Test that minimumDate and maximumDate expand if the set date falls outside them."""
    import model_editor
    monkeypatch.setattr(model_editor, "QDate", FakeQDate)

    ml, store, oseries, prec, evap = _setup_test_models()

    class DummyEditor:
        pass

    editor = DummyEditor()
    editor.original_model = ml
    editor.store = store
    editor.stressmodel_settings = [
        {"name": "prec", "inputs": ["prec"], "type": "StressModel"},
        {"name": "evap", "inputs": ["evap"], "type": "StressModel"},
    ]
    # Set narrow bounds that would otherwise block the target date
    editor.de_tmin = FakeQDateEdit(FakeQDate(2015, 6, 1))
    editor.de_tmin.setMinimumDate(FakeQDate(2015, 6, 1))
    editor.de_tmin.setMaximumDate(FakeQDate(2021, 12, 31))

    editor._get_all_stress_series = ModelEditorDialog._get_all_stress_series.__get__(editor, DummyEditor)
    editor._get_stresses_common_range = ModelEditorDialog._get_stresses_common_range.__get__(editor, DummyEditor)
    editor.set_tmin_to_first_all_stresses = ModelEditorDialog.set_tmin_to_first_all_stresses.__get__(editor, DummyEditor)

    # All stresses start at 2012-01-01, which is earlier than 2015-06-01 minimumDate
    editor.set_tmin_to_first_all_stresses()
    assert editor.de_tmin.date().toString() == "2012-01-01"
    assert editor.de_tmin.minimumDate().toString() <= "2012-01-01"

