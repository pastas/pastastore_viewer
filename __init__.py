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
_REQUIRED_PACKAGES = ["pastastore", "pastas", "pyqtgraph"]
_RUNTIME_INSTALL_DONE = False



def _add_vendor_paths():
    """Add bundled dependency paths if present."""
    plugin_dir = os.path.dirname(__file__)
    deps_dir = os.path.join(plugin_dir, "dependencies")
    if os.path.isdir(deps_dir):
        if deps_dir not in sys.path:
            sys.path.insert(0, deps_dir)
        for entry in os.listdir(deps_dir):
            if entry.endswith((".whl", ".zip")):
                path = os.path.join(deps_dir, entry)
                if path not in sys.path:
                    sys.path.insert(0, path)


def _missing_packages():
    missing = []
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

    _add_vendor_paths()
    _RUNTIME_INSTALL_DONE = True


_add_vendor_paths()
_ensure_runtime_deps()

def classFactory(iface):
    """Load PastastoreViewer class from file PastastoreViewer.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    from .pastastore_viewer import PastastoreViewer
    return PastastoreViewer(iface)
