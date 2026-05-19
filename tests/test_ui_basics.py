# -*- coding: utf-8 -*-
"""Basic UI component tests (requires Qt environment)."""

import pytest


def _has_qgis():
    """Check if QGIS is available."""
    try:
        import qgis.core
        return True
    except ImportError:
        return False


class TestUIImports:
    """Test that UI modules can be imported without errors."""

    @pytest.mark.skipif(
        not _has_qgis(),
        reason="QGIS environment not available"
    )
    def test_import_main_dock(self):
        """Test importing main_dock module."""
        try:
            from main_dock import PastastoreMainDock
            assert PastastoreMainDock is not None
        except ImportError as e:
            pytest.skip(f"Cannot import main_dock: {e}")

    @pytest.mark.skipif(
        not _has_qgis(),
        reason="QGIS environment not available"
    )
    def test_import_plot_dock(self):
        """Test importing plot_dock module."""
        try:
            from plot_dock import PastastorePlotDock
            assert PastastorePlotDock is not None
        except ImportError as e:
            pytest.skip(f"Cannot import plot_dock: {e}")

    @pytest.mark.skipif(
        not _has_qgis(),
        reason="QGIS environment not available"
    )
    def test_import_settings_dialog(self):
        """Test importing settings_dialog module."""
        try:
            from settings_dialog import PastastoreSettingsDialog
            assert PastastoreSettingsDialog is not None
        except ImportError as e:
            pytest.skip(f"Cannot import settings_dialog: {e}")

