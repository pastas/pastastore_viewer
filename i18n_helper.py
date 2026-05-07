# -*- coding: utf-8 -*-

import os
import xml.etree.ElementTree as ET

from qgis.PyQt.QtCore import QCoreApplication, QLocale, QSettings


_NL_TRANSLATIONS = None


def _is_dutch_locale():
    settings = QSettings()
    candidates = [
        settings.value("locale/userLocale", ""),
        settings.value("locale/globalLocale", ""),
        QLocale().name(),
        QLocale.system().name(),
    ]

    for locale in candidates:
        if isinstance(locale, str) and locale[:2].lower() == "nl":
            return True

    # Fallback heuristic: if QGIS translates "Edit" to Dutch, UI language is Dutch.
    try:
        qgis_edit = QCoreApplication.translate("Qgis", "Edit")
        if isinstance(qgis_edit, str) and qgis_edit.lower().startswith("bewerk"):
            return True
    except Exception:
        pass
    return False


def _normalize_key(text):
    if text is None:
        return ""
    lines = [line.strip() for line in str(text).splitlines()]
    return "\n".join(lines).strip()


def _load_nl_translations():
    global _NL_TRANSLATIONS
    if _NL_TRANSLATIONS is not None:
        return _NL_TRANSLATIONS

    translations = {}
    ts_path = os.path.join(os.path.dirname(__file__), "i18n", "pastastore_viewer_nl.ts")
    if not os.path.exists(ts_path):
        _NL_TRANSLATIONS = translations
        return translations

    try:
        tree = ET.parse(ts_path)
        root = tree.getroot()

        for context in root.findall("context"):
            name_node = context.find("name")
            if name_node is None or (name_node.text or "") != "PastastoreViewer":
                continue

            for msg in context.findall("message"):
                src_node = msg.find("source")
                tr_node = msg.find("translation")
                if src_node is None or tr_node is None:
                    continue
                if tr_node.get("type", "") in ("unfinished", "obsolete", "vanished"):
                    continue

                source = src_node.text or ""
                translated = tr_node.text or ""
                if not source or not translated:
                    continue

                translations[source] = translated
                source_norm = _normalize_key(source)
                if source_norm and source_norm not in translations:
                    translations[source_norm] = translated
    except Exception:
        pass

    _NL_TRANSLATIONS = translations
    return translations


def tr(message, context="PastastoreViewer"):
    translated = QCoreApplication.translate(context, message)
    if translated and translated != message:
        return translated

    if not _is_dutch_locale():
        return message

    table = _load_nl_translations()
    if message in table:
        return table[message]

    key = _normalize_key(message)
    return table.get(key, message)
