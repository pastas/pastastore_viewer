# -*- coding: utf-8 -*-
"""Tests for isolated imports in __init__.py."""

import os
import sys
import importlib.util
from unittest.mock import MagicMock

# Mocks for QGIS environment if missing
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

spec = importlib.util.spec_from_file_location(
    "pastastore_viewer_init",
    os.path.join(os.path.dirname(__file__), "..", "__init__.py"),
)
init_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(init_mod)

_isolated_import = init_mod._isolated_import
_DEPS_DIR = init_mod._DEPS_DIR


def test_isolated_import_removes_deps_dir_from_sys_path():
    """Test that _isolated_import temporarily prepends _DEPS_DIR to sys.path and removes it after."""
    if _DEPS_DIR in sys.path:
        sys.path.remove(_DEPS_DIR)

    assert _DEPS_DIR not in sys.path

    with _isolated_import():
        assert sys.path[0] == _DEPS_DIR

    assert _DEPS_DIR not in sys.path
