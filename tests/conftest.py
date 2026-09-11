# -*- coding: utf-8 -*-
"""Pytest configuration and shared fixtures."""

import os
import sys
import pytest
import tempfile
from pathlib import Path

# Add parent directory to path to import plugin modules
PLUGIN_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PLUGIN_DIR))

# Mock QGIS and PyQt modules if not running inside QGIS environment
try:
    import qgis.core
except (ImportError, ModuleNotFoundError):
    from unittest.mock import MagicMock

    class MockWidgetMeta(type):
        def __getattr__(cls, name):
            return MagicMock()

    class MockWidget(metaclass=MockWidgetMeta):
        def __init__(self, *args, **kwargs):
            pass
        def __getattr__(self, name):
            return MagicMock()

    QtWidgets_mock = MagicMock()
    for name in ["QDialog", "QVBoxLayout", "QFormLayout", "QLineEdit", "QDialogButtonBox",
                 "QLabel", "QCheckBox", "QGroupBox", "QComboBox", "QMessageBox",
                 "QWidget", "QHBoxLayout", "QListWidget", "QPushButton", "QTabWidget",
                 "QTableWidget", "QTableWidgetItem", "QDateEdit", "QProgressDialog",
                 "QApplication", "QFileDialog"]:
        setattr(QtWidgets_mock, name, MockWidget)

    QtCore_mock = MagicMock()
    QtCore_mock.Qt = MagicMock()
    QtCore_mock.QDate = MagicMock()
    QtCore_mock.QCoreApplication.translate = lambda context, text: text
    QtCore_mock.QLocale = MagicMock()
    QtCore_mock.QSettings = MagicMock()


    sys.modules["qgis"] = MagicMock()
    sys.modules["qgis.core"] = MagicMock()
    sys.modules["qgis.gui"] = MagicMock()
    sys.modules["qgis.PyQt"] = MagicMock()
    sys.modules["qgis.PyQt.QtWidgets"] = QtWidgets_mock
    sys.modules["qgis.PyQt.QtCore"] = QtCore_mock
    sys.modules["qgis.PyQt.QtGui"] = MagicMock()

    sys.modules["PyQt5"] = MagicMock()
    sys.modules["PyQt5.QtCore"] = QtCore_mock
    sys.modules["PyQt5.QtWidgets"] = QtWidgets_mock
    sys.modules["PyQt5.QtGui"] = MagicMock()
    sys.modules["pyqtgraph"] = MagicMock()



@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def plugin_dir():
    """Return the plugin directory path."""
    return str(PLUGIN_DIR)


@pytest.fixture
def license_dir(temp_dir):
    """Create a temporary license directory."""
    license_path = Path(temp_dir) / "license"
    license_path.mkdir()
    return str(license_path)
