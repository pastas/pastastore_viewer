# -*- coding: utf-8 -*-
from unittest.mock import MagicMock
from model_editor import StressSettingsDialog
import pastas as ps


def test_stress_settings_dialog_parse_value():
    assert StressSettingsDialog._parse_value("0.0") == 0.0
    assert StressSettingsDialog._parse_value("1.5") == 1.5
    assert StressSettingsDialog._parse_value("None") is None
    assert StressSettingsDialog._parse_value("") is None
    assert StressSettingsDialog._parse_value("bfill") == "bfill"


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
