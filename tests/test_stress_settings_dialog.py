# -*- coding: utf-8 -*-
import types
from unittest.mock import MagicMock, patch
import numpy as np
import pandas as pd
from model_editor import ModelEditorDialog, StressSettingsDialog
import pastas as ps


def test_stress_settings_dialog_parse_value():
    assert StressSettingsDialog._parse_value("0.0") == 0.0
    assert StressSettingsDialog._parse_value("1.5") == 1.5
    assert StressSettingsDialog._parse_value("None") is None
    assert StressSettingsDialog._parse_value("") is None
    assert StressSettingsDialog._parse_value("bfill") == "bfill"


def test_stress_settings_dialog_format_timestamp():
    assert StressSettingsDialog._format_timestamp(None) == "-"
    assert StressSettingsDialog._format_timestamp(pd.NaT) == "-"
    assert StressSettingsDialog._format_timestamp(pd.Timestamp("2010-01-01")) == "2010-01-01"
    assert (
        StressSettingsDialog._format_timestamp(pd.Timestamp("2010-01-01 12:30:00"))
        == "2010-01-01 12:30:00"
    )


def test_stress_settings_dialog_shows_tmin_tmax_at_top():
    """StressSettingsDialog places First value and Last value at the top of the dialog."""
    import model_editor

    added_rows = []
    created_labels = []

    class FakeLabel:
        def __init__(self, text=""):
            self._text = text
            created_labels.append(self)

        def text(self):
            return self._text

    class FakeFormLayout:
        def __init__(self, *args, **kwargs):
            pass

        def setContentsMargins(self, *args):
            pass

        def setVerticalSpacing(self, *args):
            pass

        def addRow(self, label, field):
            added_rows.append((label, field))

    with patch.object(model_editor, "QLabel", FakeLabel), patch.object(
        model_editor, "QFormLayout", FakeFormLayout
    ):
        dlg = StressSettingsDialog(
            keyword="prec",
            stress_name="rain",
            tmin=pd.Timestamp("2010-01-01"),
            tmax=pd.Timestamp("2020-12-31 06:00:00"),
        )

    assert dlg.lbl_first_value.text() == "2010-01-01"
    assert dlg.lbl_last_value.text() == "2020-12-31 06:00:00"
    # Verify First value and Last value rows appear before Settings row
    row_labels = [lbl for lbl, _ in added_rows]
    assert row_labels[0] == "First value:"
    assert row_labels[1] == "Last value:"
    assert row_labels[2] == "Settings:"


def test_model_editor_get_stress_range():
    idx = pd.date_range("2005-01-01", "2015-12-31", freq="D")
    s = pd.Series(np.ones(len(idx)), index=idx)
    s.iloc[0] = np.nan
    s.iloc[-1] = np.nan

    class FakeStore:
        def __init__(self, mapping):
            self._map = mapping

        def get_stresses(self, name):
            if name in self._map:
                return self._map[name]
            raise KeyError(name)

    dlg = object.__new__(ModelEditorDialog)
    dlg.original_model = types.SimpleNamespace(stressmodels={})
    dlg.store = FakeStore({"rain": s})

    tmin, tmax = dlg._get_stress_range("rain")
    assert tmin == pd.Timestamp("2005-01-02")
    assert tmax == pd.Timestamp("2015-12-30")

    # Missing stress returns (None, None)
    assert dlg._get_stress_range("missing") == (None, None)
    assert dlg._get_stress_range("") == (None, None)


def test_model_editor_get_stress_range_series_original():
    raw = pd.Series(
        [1.0, 2.0],
        index=pd.DatetimeIndex(["1990-01-01", "2000-12-31"]),
    )

    class FakeTimeSeries:
        series_original = raw

    class FakeStore:
        def get_stresses(self, name):
            return FakeTimeSeries()

    dlg = object.__new__(ModelEditorDialog)
    dlg.original_model = types.SimpleNamespace(stressmodels={})
    dlg.store = FakeStore()

    assert dlg._get_stress_range("rain") == (
        pd.Timestamp("1990-01-01"),
        pd.Timestamp("2000-12-31"),
    )


def test_open_input_settings_passes_tmin_tmax():
    import model_editor

    s_prec = pd.Series(
        [1.0, 2.0],
        index=pd.DatetimeIndex(["2012-03-01", "2022-08-15"]),
    )
    s_evap = pd.Series(
        [0.5, 0.7],
        index=pd.DatetimeIndex(["2013-01-01", "2021-12-31"]),
    )

    class FakeStore:
        def get_stresses(self, name):
            return {"prec": s_prec, "evap": s_evap}[name]

    dlg = object.__new__(ModelEditorDialog)
    dlg.original_model = types.SimpleNamespace(stressmodels={})
    dlg.store = FakeStore()
    dlg.stressmodel_settings = [
        {
            "name": "recharge",
            "type": "RechargeModel",
            "inputs": ["prec", "evap"],
            "settings_kws": ["prec", "evap"],
            "settings_custom": [{}, {}],
        }
    ]
    dlg.list_stresses = MagicMock()
    dlg.list_stresses.currentRow.return_value = 0
    dlg.btn_input1_settings = MagicMock()
    dlg.btn_input2_settings = MagicMock()

    mock_dialog_cls = MagicMock()
    mock_dialog_cls.return_value.exec.return_value = False

    with patch.object(model_editor, "StressSettingsDialog", mock_dialog_cls):
        dlg._open_input_settings(0)
        _, kwargs0 = mock_dialog_cls.call_args
        assert kwargs0["stress_name"] == "prec"
        assert kwargs0["tmin"] == pd.Timestamp("2012-03-01")
        assert kwargs0["tmax"] == pd.Timestamp("2022-08-15")

        dlg._open_input_settings(1)
        _, kwargs1 = mock_dialog_cls.call_args
        assert kwargs1["stress_name"] == "evap"
        assert kwargs1["tmin"] == pd.Timestamp("2013-01-01")
        assert kwargs1["tmax"] == pd.Timestamp("2021-12-31")


def test_stress_settings_dialog_presets():
    dlg = StressSettingsDialog.__new__(StressSettingsDialog)
    dlg._updating = False
    dlg._custom_dict = {}
    dlg._field_widgets = {
        f: MagicMock() for f in StressSettingsDialog.FIELDS
    }
    dlg.cbo_keyword = MagicMock()
    dlg.cbo_keyword.currentText.return_value = "prec"

    # Test _get_preset
    prec_preset = dlg._get_preset("prec")
    assert prec_preset["sample_up"] == "bfill"

    # Test _populate_fields
    dlg._populate_fields("prec")
    dlg._field_widgets["sample_up"].setCurrentText.assert_called_with("bfill")

    # Test _on_keyword_changed to evap
    dlg.cbo_keyword.currentText.return_value = "evap"
    dlg._on_keyword_changed("evap")
    dlg._field_widgets["fill_nan"].setCurrentText.assert_called_with("interpolate")


def test_stress_settings_dialog_field_changed_switches_to_custom():
    dlg = StressSettingsDialog.__new__(StressSettingsDialog)
    dlg._updating = False
    dlg._custom_dict = {}
    dlg._field_widgets = {
        f: MagicMock() for f in StressSettingsDialog.FIELDS
    }
    for f in StressSettingsDialog.FIELDS:
        dlg._field_widgets[f].currentText.return_value = "mean"

    dlg.cbo_keyword = MagicMock()
    dlg.cbo_keyword.currentText.return_value = "prec"

    # User modifies a field
    dlg._on_field_changed("sample_up", "ffill")

    # Should set keyword to 'custom'
    dlg.cbo_keyword.setCurrentText.assert_called_with("custom")
    assert dlg._custom_dict["sample_up"] == "ffill"


def test_stress_settings_dialog_get_custom_dict():
    dlg = StressSettingsDialog.__new__(StressSettingsDialog)
    dlg._updating = False
    dlg._custom_dict = {"extra_key": 123}
    dlg._field_widgets = {
        f: MagicMock() for f in StressSettingsDialog.FIELDS
    }
    for f in StressSettingsDialog.FIELDS:
        dlg._field_widgets[f].currentText.return_value = "mean"
    dlg._field_widgets["sample_up"].currentText.return_value = "ffill"

    res = dlg.get_custom_dict()
    assert res["extra_key"] == 123
    assert res["sample_up"] == "ffill"
    assert res["sample_down"] == "mean"
