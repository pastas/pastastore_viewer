# -*- coding: utf-8 -*-
"""
/***************************************************************************
 PastastoreViewer
                                 A QGIS plugin
 Visualize time series and models from a PastaStore zip file.
 
 Copyright © 2024-2026 Pastastore Viewer Contributors. All rights reserved.
 This software is proprietary. See LICENSE.md for details.
 ***************************************************************************/
"""

import importlib
import importlib.util
import os
import subprocess
import sys
import threading
from contextlib import contextmanager

try:
    from .i18n_helper import tr as _i18n_tr
except (ImportError, ValueError):
    from i18n_helper import tr as _i18n_tr


_PLUGIN_DIR = os.path.dirname(__file__)
_DEPS_DIR = os.path.join(_PLUGIN_DIR, "dependencies")
_PLUGIN_TRANSLATOR = None


def _install_plugin_translator():
    """Install Dutch translations when QGIS locale is Dutch."""
    global _PLUGIN_TRANSLATOR
    try:
        from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTranslator

        locale = QSettings().value("locale/userLocale", "en")
        if not isinstance(locale, str):
            locale = "en"
        language = locale[:2].lower()
        if language != "nl":
            return None

        translator = QTranslator()
        qm_path = os.path.join(_PLUGIN_DIR, "i18n", "pastastore_viewer_nl.qm")
        if translator.load(qm_path):
            QCoreApplication.installTranslator(translator)
            return translator
    except Exception as err:
        import logging
        logging.getLogger(__name__).debug("Failed to install plugin translator: %s", err)
    return None


def _tr(message):
    try:
        return _i18n_tr(message)
    except Exception:
        return message


_BUNDLED_PACKAGES = {
    "pastas",
    "pastastore",
    "pyqtgraph",
    "brodata",
    "hydropandas",
    "tqdm",
}
_PLUGIN_DEPS_MODULES = {}


def _is_plugin_caller(frame):
    """Check if an import call originated from within pastastore_viewer or its dependencies."""
    while frame:
        fname = frame.f_code.co_filename
        if fname:
            abs_fname = os.path.abspath(fname)
            if abs_fname.lower().startswith(os.path.abspath(_PLUGIN_DIR).lower()):
                return True
        frame = frame.f_back
    return False


def _install_scoped_import_hook():
    """Install import hook to isolate bundled dependencies to pastastore_viewer only."""
    import builtins

    if getattr(_install_scoped_import_hook, "_installed", False):
        return

    # Pre-load dependencies into _PLUGIN_DEPS_MODULES
    if os.path.isdir(_DEPS_DIR):
        if _DEPS_DIR not in sys.path:
            sys.path.insert(0, _DEPS_DIR)

        try:
            for pkg_name in ["pastas", "pastastore", "pyqtgraph", "brodata", "hydropandas", "tqdm"]:
                try:
                    importlib.import_module(pkg_name)
                except Exception:
                    pass
        finally:
            if _DEPS_DIR in sys.path:
                sys.path.remove(_DEPS_DIR)

        for k, v in list(sys.modules.items()):
            if k.split(".")[0] in _BUNDLED_PACKAGES:
                mod_file = getattr(v, "__file__", "") or ""
                if os.path.abspath(mod_file).lower().startswith(os.path.abspath(_DEPS_DIR).lower()):
                    _PLUGIN_DEPS_MODULES[k] = sys.modules.pop(k)

    orig_import = builtins.__import__

    def scoped_import(name, globals=None, locals=None, fromlist=(), level=0):
        frame = sys._getframe(1)
        if _is_plugin_caller(frame):
            for k, v in _PLUGIN_DEPS_MODULES.items():
                if k not in sys.modules:
                    sys.modules[k] = v
            if _DEPS_DIR not in sys.path:
                sys.path.insert(0, _DEPS_DIR)
            try:
                return orig_import(name, globals, locals, fromlist, level)
            finally:
                if _DEPS_DIR in sys.path:
                    sys.path.remove(_DEPS_DIR)
        else:
            for k in list(_PLUGIN_DEPS_MODULES.keys()):
                if k in sys.modules and sys.modules[k] is _PLUGIN_DEPS_MODULES[k]:
                    sys.modules.pop(k, None)
            if _DEPS_DIR in sys.path:
                sys.path.remove(_DEPS_DIR)
            return orig_import(name, globals, locals, fromlist, level)

    builtins.__import__ = scoped_import
    _install_scoped_import_hook._installed = True


@contextmanager
def _isolated_import():
    """Temporarily prepend dependencies folder to sys.path for plugin imports only."""
    _install_scoped_import_hook()
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
        for path in reversed(added_paths):
            try:
                sys.path.remove(path)
            except ValueError:
                pass


_install_scoped_import_hook()
_PLUGIN_TRANSLATOR = _install_plugin_translator()


def classFactory(iface):
    """Load PastastoreViewer class from file PastastoreViewer.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    with _isolated_import():
        from .pastastore_viewer import PastastoreViewer
    return PastastoreViewer(iface)
