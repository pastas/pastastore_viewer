# -*- coding: utf-8 -*-
"""Tests for TarsoModel support in model editor."""

import sys
from unittest.mock import MagicMock

# Setup QGIS mocks to allow importing model_editor in non-QGIS environments
class MockWidget:
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
    for name in ["QDialog", "QVBoxLayout", "QFormLayout", "QLineEdit", "QDialogButtonBox",
                 "QLabel", "QCheckBox", "QGroupBox", "QComboBox", "QMessageBox",
                 "QWidget", "QHBoxLayout", "QListWidget", "QPushButton", "QTabWidget",
                 "QTableWidget", "QTableWidgetItem", "QDateEdit", "QProgressDialog",
                 "QApplication", "QFileDialog"]:
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

import pytest
import pandas as pd
import pastas as ps

# Now import model_editor
from model_editor import ModelEditorDialog


def test_tarso_model_parsing():
    """Test parsing a Pastas model containing a TarsoModel."""
    # Create dummy time series
    idx = pd.date_range("2020-01-01", periods=100, freq="D")
    oseries = pd.Series(index=idx, data=0.0, name="oseries")
    prec = pd.Series(index=idx, data=1.0, name="prec")
    evap = pd.Series(index=idx, data=0.5, name="evap")

    # Create model
    ml = ps.Model(oseries)
    
    # Create TarsoModel
    sm = ps.TarsoModel(prec, evap, oseries=oseries, name="tarso_test")
    ml.add_stressmodel(sm)

    # Instantiate dummy editor
    class DummyEditor:
        pass
    editor = DummyEditor()
    editor._parse_current_model = ModelEditorDialog._parse_current_model.__get__(editor, DummyEditor)

    settings = editor._parse_current_model(ml)
    
    assert len(settings) == 1
    s = settings[0]
    assert s["name"] == "tarso_test"
    assert s["type"] == "TarsoModel"
    assert "prec" in s["inputs"]
    assert "evap" in s["inputs"]


def test_tarso_model_reconstruction():
    """Test reconstructing a TarsoModel from settings."""
    idx = pd.date_range("2020-01-01", periods=100, freq="D")
    oseries = pd.Series(index=idx, data=0.0, name="oseries")
    prec = pd.Series(index=idx, data=1.0, name="prec")
    evap = pd.Series(index=idx, data=0.5, name="evap")

    # Create empty model
    ml = ps.Model(oseries)

    # Dummy editor representing the UI dialog state
    class DummyEditor:
        pass
    editor = DummyEditor()
    
    # Mock store to return our time series
    class MockStore:
        def get_stresses(self, name):
            if name == "prec":
                return prec
            elif name == "evap":
                return evap
            return None
    editor.store = MockStore()

    # Reconstructed setting dictionary for TarsoModel
    editor.stressmodel_settings = [
        {
            "name": "tarso_recon",
            "type": "TarsoModel",
            "rfunc": "Exponential",
            "inputs": ["prec", "evap"],
            "settings": {},
        }
    ]

    # Replicate the core loop of _apply_model_changes for reconstruction
    for s in editor.stressmodel_settings:
        name = s["name"]
        sm_type = s["type"]
        rfunc_name = s["rfunc"]
        inputs = s.get("inputs", [])
        settings_dict = s.get("settings", {})

        # Rfunc class
        rfunc = None
        if rfunc_name != "None" and hasattr(ps, rfunc_name):
            rfunc = getattr(ps, rfunc_name)()

        if sm_type == "TarsoModel":
            prec_series = editor.store.get_stresses(inputs[0])
            evap_series = editor.store.get_stresses(inputs[1])

            sm_settings = [
                settings_dict.get(inputs[0]),
                settings_dict.get(inputs[1]),
            ]

            oseries_data = ml.oseries.series

            sm = ps.TarsoModel(
                prec_series,
                evap_series,
                oseries=oseries_data,
                rfunc=rfunc,
                name=name,
                settings=sm_settings,
            )
            ml.add_stressmodel(sm)

    # Verify reconstruction
    assert "tarso_recon" in ml.stressmodels
    recon_sm = ml.stressmodels["tarso_recon"]
    assert isinstance(recon_sm, ps.TarsoModel)
    assert recon_sm.name == "tarso_recon"


def test_tarso_model_ui_behavior():
    """Test that selecting TarsoModel enforces Exponential rfunc and disables the combobox."""
    # Instantiate dummy editor
    class DummyEditor:
        def __init__(self):
            self.detail_rfunc = MagicMock()
            self.detail_input1_lbl = MagicMock()
            self.detail_input2_lbl = MagicMock()
            self.detail_input1 = MagicMock()
            self.detail_input2 = MagicMock()
            self.detail_up = MagicMock()
            self.detail_recharge = MagicMock()
            self.form_detail = MagicMock()
            
            # Setup current settings storage
            self._current_setting = {
                "type": "StressModel",
                "rfunc": "Gamma",
                "inputs": [],
            }
            
        def get_current_setting(self):
            return self._current_setting

    editor = DummyEditor()
    # Bind the methods
    editor.save_detail_type = ModelEditorDialog.save_detail_type.__get__(editor, DummyEditor)
    editor.update_detail_visibility = ModelEditorDialog.update_detail_visibility.__get__(editor, DummyEditor)

    # Change type to TarsoModel
    editor.save_detail_type("TarsoModel")

    # Assert settings were updated to Exponential
    assert editor._current_setting["type"] == "TarsoModel"
    assert editor._current_setting["rfunc"] == "Exponential"

    # Assert UI combobox received the update and was disabled
    editor.detail_rfunc.setCurrentText.assert_called_with("Exponential")
    editor.detail_rfunc.setEnabled.assert_called_with(False)

    # Change type back to StressModel
    editor.save_detail_type("StressModel")
    editor.detail_rfunc.setEnabled.assert_called_with(True)


def test_msg_icon_critical():
    """Verify that QMessageBox.Icon.Critical resolves successfully."""
    from qgis.PyQt.QtWidgets import QMessageBox
    assert QMessageBox.Icon.Critical is not None
