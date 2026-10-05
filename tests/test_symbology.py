# -*- coding: utf-8 -*-
"""Tests for layer symbology preservation and reset functionality."""

import pytest
from settings_dialog import PastastoreSettingsDialog


def _has_qgis():
    try:
        import qgis.core
        return True
    except ImportError:
        return False


class TestSymbologyPreservation:
    def test_settings_dialog_has_reset_symbology_method(self):
        """Test that PastastoreSettingsDialog includes reset_symbology."""
        dialog = PastastoreSettingsDialog()
        assert hasattr(dialog, "reset_symbology")
        assert callable(dialog.reset_symbology)

    @pytest.mark.skipif(not _has_qgis(), reason="QGIS environment not available")
    def test_plugin_has_symbology_methods(self):
        """Test that PastastoreViewer has required symbology methods."""
        import sys
        from pathlib import Path
        root = str(Path(__file__).parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)

        import pastastore_viewer.pastastore_viewer as pv
        assert hasattr(pv.PastastoreViewer, "reset_layer_symbology")
        assert hasattr(pv.PastastoreViewer, "_find_pastastore_layer")
        assert hasattr(pv.PastastoreViewer, "_clear_layer_if_exists")
        assert hasattr(pv.PastastoreViewer, "_apply_default_symbology")
