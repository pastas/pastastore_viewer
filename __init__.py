# -*- coding: utf-8 -*-
"""
/***************************************************************************
 PastastoreViewer
                                 A QGIS plugin
 Visualize time series and models from a PastaStore zip file.
 ***************************************************************************/
"""

import importlib.util
import os
import subprocess
import sys
from contextlib import contextmanager

_REQUIRED_PACKAGES = ["pastastore", "pastas", "pyqtgraph"]
_RUNTIME_INSTALL_DONE = False
_PLUGIN_DIR = os.path.dirname(__file__)
_DEPS_DIR = os.path.join(_PLUGIN_DIR, "dependencies")


@contextmanager
def _isolated_import():
    """Temporarily prepend dependencies folder to sys.path for imports only."""
    added_paths = []
    if os.path.isdir(_DEPS_DIR):
        if _DEPS_DIR not in sys.path:
            sys.path.insert(0, _DEPS_DIR)
            added_paths.append(_DEPS_DIR)

        for entry in os.listdir(_DEPS_DIR):
            if entry.endswith((".whl", ".zip")):
                path = os.path.join(_DEPS_DIR, entry)
                if path not in sys.path:
                    sys.path.insert(0, path)
                    added_paths.append(path)

    try:
        yield
    finally:
        # Remove added paths in reverse order
        for path in reversed(added_paths):
            try:
                sys.path.remove(path)
            except ValueError:
                pass


def _add_vendor_paths():
    """Add bundled dependency paths permanently (legacy fallback)."""
    if os.path.isdir(_DEPS_DIR):
        if _DEPS_DIR not in sys.path:
            sys.path.insert(0, _DEPS_DIR)
        for entry in os.listdir(_DEPS_DIR):
            if entry.endswith((".whl", ".zip")):
                path = os.path.join(_DEPS_DIR, entry)
                if path not in sys.path:
                    sys.path.insert(0, path)


def _missing_packages():
    missing = []
    with _isolated_import():
        for name in _REQUIRED_PACKAGES:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
    return missing


def _ensure_runtime_deps():
    global _RUNTIME_INSTALL_DONE
    if _RUNTIME_INSTALL_DONE:
        return

    missing = _missing_packages()
    if not missing:
        _RUNTIME_INSTALL_DONE = True
        return

    try:
        from qgis.PyQt.QtWidgets import QMessageBox
    except Exception:
        return

    reply = QMessageBox.question(
        None,
        "Install dependencies",
        "This plugin needs extra Python packages to run.\n"
        "Do you want to download and install them now?",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )
    if reply != QMessageBox.Yes:
        return

    try:
        import pip  # noqa: F401
    except Exception:
        QMessageBox.critical(
            None,
            "pip not available",
            "pip is not available in this QGIS Python. "
            "Install 'python3-pip' via OSGeo4W Setup and try again.",
        )
        return

    plugin_dir = os.path.dirname(__file__)
    deps_dir = os.path.join(plugin_dir, "dependencies")
    os.makedirs(deps_dir, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--target",
        deps_dir,
    ]
    cmd.extend(missing)

    exit_code = subprocess.call(cmd)
    if exit_code != 0:
        QMessageBox.critical(
            None,
            "Install failed",
            "Failed to install required packages. "
            "Check your internet connection and try again.",
        )
        return

    _RUNTIME_INSTALL_DONE = True


# Check and prompt for runtime dependencies
_ensure_runtime_deps()


def classFactory(iface):
    """Load PastastoreViewer class from file PastastoreViewer.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    # Import with isolated sys.path to reduce exposure to other plugins
    with _isolated_import():
        from .pastastore_viewer import PastastoreViewer
    return PastastoreViewer(iface)
