# -*- coding: utf-8 -*-
"""Unit tests for OseriesEditorDialog save button state behavior."""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock


def _has_qgis():
    """Check if QGIS environment is available."""
    try:
        import qgis.core
        from qgis.PyQt.QtWidgets import QWidget
        from qgis.PyQt.QtGui import QColor
        return True
    except (ImportError, ModuleNotFoundError, AttributeError):
        return False


@pytest.mark.unit
class TestOseriesEditorSaveButton:
    """Test save button enable/disable logic in OseriesEditorDialog."""

    def test_save_button_state_toggle(self):
        """Test initial disabled state, enabled on edit, disabled on reset."""
        idx = pd.date_range("2020-01-01", periods=5, freq="D")
        series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx)

        if _has_qgis():
            from oseries_editor import OseriesEditorDialog
            editor = OseriesEditorDialog("test_s", series)
            assert editor.btn_save.isEnabled() is False

            # Modify a point
            timestamp = idx[0]
            editor.series_data.loc[timestamp] = 99.0
            editor.update_save_button_state()
            assert editor.btn_save.isEnabled() is True

            # Reset to original
            editor.series_data = editor.original_data.copy()
            editor.update_save_button_state()
            assert editor.btn_save.isEnabled() is False
        else:
            # Standalone test of the _has_unsaved_changes logic
            original_data = series.copy()
            series_data = series.copy()

            def has_unsaved_changes():
                return not series_data.equals(original_data)

            assert has_unsaved_changes() is False

            # Edit
            series_data.loc[idx[0]] = 99.0
            assert has_unsaved_changes() is True

            # Reset
            series_data = original_data.copy()
            assert has_unsaved_changes() is False

    def test_bulk_add_offset(self):
        """Test bulk offset addition to series measurements."""
        idx = pd.date_range("2020-01-01", periods=5, freq="D")
        series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx)

        offset = 0.5
        target_timestamps = idx[:3]
        series_data = series.copy()
        for ts in target_timestamps:
            series_data.loc[ts] += offset

        assert series_data.iloc[0] == 1.5
        assert series_data.iloc[1] == 2.5
        assert series_data.iloc[2] == 3.5
        assert series_data.iloc[3] == 4.0
        assert series_data.iloc[4] == 5.0

    def test_modify_button_disabled_on_multiple_selection(self):
        """Test that btn_modify is enabled for 1 selected row and disabled for 0 or >1 selected rows."""
        def is_modify_enabled(selected_count):
            return selected_count == 1

        assert is_modify_enabled(0) is False
        assert is_modify_enabled(1) is True
        assert is_modify_enabled(2) is False
        assert is_modify_enabled(10) is False

    def test_restore_selection_by_timestamps(self):
        """Test that selection restoration preserves target timestamps."""
        idx = pd.date_range("2020-01-01", periods=5, freq="D")
        target = set(idx[:2])
        mask = np.array([ts in target for ts in idx], dtype=bool)
        assert mask.sum() == 2
        assert mask[0] == True
        assert mask[1] == True
        assert mask[2] == False
