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


def _get_bundled_package_names():
    """Get top-level package names inside the dependencies directory."""
    names = set()
    if os.path.isdir(_DEPS_DIR):
        for entry in os.listdir(_DEPS_DIR):
            entry_path = os.path.join(_DEPS_DIR, entry)
            if (
                os.path.isdir(entry_path)
                and not entry.endswith((".dist-info", ".egg-info"))
                and entry != "__pycache__"
            ):
                names.add(entry)
            elif os.path.isfile(entry_path) and entry.endswith(".py"):
                names.add(entry[:-3])
    return names


@contextmanager
def _isolated_import():
    """Temporarily prepend dependencies folder to sys.path for plugin imports only."""
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
        # Remove added paths from sys.path so dependencies/ folder is not accessible to other plugins
        for path in reversed(added_paths):
            try:
                sys.path.remove(path)
            except ValueError:
                pass


_PLUGIN_TRANSLATOR = _install_plugin_translator()


def classFactory(iface):
    """Load PastastoreViewer class from file PastastoreViewer.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    with _isolated_import():
        from .pastastore_viewer import PastastoreViewer
    return PastastoreViewer(iface)
