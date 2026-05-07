# -*- coding: utf-8 -*-
"""
/***************************************************************************
 PastastoreViewer
                                 A QGIS plugin
 Visualize time series and models from a PastaStore zip file.
 ***************************************************************************/
"""

import importlib
import importlib.util
import os
import subprocess
import sys
import threading
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


def _clear_import_cache():
    """Clear Python import caches after installing new packages."""
    try:
        importlib.invalidate_caches()
        # Clear any cached imports of our packages
        for name in _REQUIRED_PACKAGES:
            if name in sys.modules:
                del sys.modules[name]
            # Also clear submodules
            to_remove = [k for k in sys.modules.keys() if k.startswith(name + ".")]
            for k in to_remove:
                del sys.modules[k]
    except Exception:
        pass


def _missing_packages():
    missing = []
    _clear_import_cache()
    with _isolated_import():
        for name in _REQUIRED_PACKAGES:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
    return missing


def _install_packages_threaded(missing, deps_dir):
    """Install packages in a background thread to prevent QGIS blocking/restart."""
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

    # Sanitize environment to prevent subprocess from triggering QGIS restart
    env = os.environ.copy()
    # Remove variables that might interfere with subprocess
    for key in ["PYTHONPATH", "QGIS_PREFIX_PATH", "QT_PLUGIN_PATH"]:
        env.pop(key, None)

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            universal_newlines=True,
        )
        stdout, stderr = process.communicate(timeout=300)
        return process.returncode == 0, stdout, stderr
    except subprocess.TimeoutExpired:
        process.kill()
        return False, "", "Installation timed out after 5 minutes."
    except Exception as exc:
        return False, "", str(exc)


def _handle_install_result(success, stdout, stderr, missing, progress):
    """Handle installation result in main thread."""
    from qgis.PyQt.QtWidgets import QMessageBox

    try:
        progress.close()
    except Exception:
        pass

    if not success:
        QMessageBox.critical(
            None,
            "Install failed",
            f"Failed to install required packages ({', '.join(missing)})",
        )
        return

    # Clear caches after successful installation
    _clear_import_cache()

    # Verify installation by checking again
    still_missing = _missing_packages()
    if still_missing:
        QMessageBox.warning(
            None,
            "Installation verification failed",
            f"Installation completed but packages still missing: {', '.join(still_missing)}",
        )
        return

    global _RUNTIME_INSTALL_DONE
    _RUNTIME_INSTALL_DONE = True
    QMessageBox.information(
        None,
        "Installation successful",
        f"Successfully installed: {', '.join(missing)}",
    )


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

    # Show progress dialog
    from qgis.PyQt.QtWidgets import QProgressDialog
    from qgis.PyQt.QtCore import Qt, QTimer

    progress = QProgressDialog(
        f"Installing {', '.join(missing)}...\n\nPlease wait.",
        "Cancel",
        0,
        0,
        None,
    )
    progress.setWindowTitle("Installing Dependencies")
    progress.setWindowModality(Qt.ApplicationModal)
    progress.setMinimumDuration(0)
    progress.show()

    # Run installation in background thread
    def run_install():
        success, stdout, stderr = _install_packages_threaded(missing, deps_dir)
        # Signal main thread to check results
        QTimer.singleShot(0, lambda: _handle_install_result(success, stdout, stderr, missing, progress))

    thread = threading.Thread(target=run_install, daemon=True)
    thread.start()


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
