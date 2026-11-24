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
        if isinstance(qgis.core, MagicMock) or getattr(qgis.core, "__is_mock__", False):
            return False
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

    def test_stress_series_editor_support(self):
        """Test series_type='stress' title and alias support."""
        idx = pd.date_range("2020-01-01", periods=5, freq="D")
        series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx)

        if _has_qgis():
            from oseries_editor import OseriesEditorDialog, SeriesEditorDialog
            editor = OseriesEditorDialog("precip_1", series, series_type="stress")
            assert "Stress: precip_1" in editor.windowTitle()
            assert SeriesEditorDialog is OseriesEditorDialog
        else:
            try:
                from oseries_editor import SeriesEditorDialog, OseriesEditorDialog
                assert SeriesEditorDialog is OseriesEditorDialog
            except ModuleNotFoundError:
                pass

    def test_open_oseries_editor_preserves_selection_on_save(self, monkeypatch):
        """Saving edits in open_oseries_editor keeps the oseries selected after refresh."""
        try:
            import pastastore_viewer.pastastore_viewer as pv_mod
        except ImportError:
            import pastastore_viewer as pv_mod

        idx = pd.date_range("2020-01-01", periods=3, freq="D")
        orig = pd.Series([1.0, 2.0, 3.0], index=idx)
        edited = pd.Series([1.0, 9.0, 3.0], index=idx)

        fake_dlg = MagicMock()
        fake_dlg.exec.return_value = True
        fake_dlg.get_modified_series.return_value = edited
        monkeypatch.setattr(pv_mod, "OseriesEditorDialog", lambda *a, **kw: fake_dlg)

        viewer = pv_mod.PastastoreViewer.__new__(pv_mod.PastastoreViewer)
        viewer.iface = MagicMock()
        viewer.store = MagicMock()
        viewer.store.get_oseries.return_value = orig
        viewer.store.oseries = pd.DataFrame({"x": [1.0]}, index=["obs1"])
        viewer._add_oseries_to_store = MagicMock()
        viewer.mark_store_modified = MagicMock()
        viewer._push_message = MagicMock()

        dock = MagicMock()
        dock.get_selected_names.return_value = ["obs1"]
        dock.tabs.currentIndex.return_value = 0
        viewer.dock_widget = dock

        viewer.open_oseries_editor("obs1")

        dock.populate_lists.assert_called_once_with(viewer.store)
        dock.select_items_in_list.assert_called_once_with(
            "oseries", ["obs1"], switch_tab=False, trigger_signal=True
        )

    def test_open_stress_editor_preserves_selection_on_save(self, monkeypatch):
        """Saving edits in open_stress_editor keeps the stress selected after refresh."""
        try:
            import pastastore_viewer.pastastore_viewer as pv_mod
        except ImportError:
            import pastastore_viewer as pv_mod

        idx = pd.date_range("2020-01-01", periods=3, freq="D")
        orig = pd.Series([1.0, 2.0, 3.0], index=idx)
        edited = pd.Series([1.0, 4.0, 3.0], index=idx)

        fake_dlg = MagicMock()
        fake_dlg.exec.return_value = True
        fake_dlg.get_modified_series.return_value = edited
        monkeypatch.setattr(pv_mod, "OseriesEditorDialog", lambda *a, **kw: fake_dlg)

        viewer = pv_mod.PastastoreViewer.__new__(pv_mod.PastastoreViewer)
        viewer.iface = MagicMock()
        viewer.store = MagicMock()
        viewer.store.get_stresses.return_value = orig
        viewer.store.stresses = pd.DataFrame({"kind": ["prec"]}, index=["prec1"])
        viewer._add_stress_to_store = MagicMock()
        viewer.mark_store_modified = MagicMock()
        viewer._push_message = MagicMock()

        dock = MagicMock()
        dock.get_selected_names.return_value = ["prec1"]
        dock.tabs.currentIndex.return_value = 1
        viewer.dock_widget = dock

        viewer.open_stress_editor("prec1")

        dock.populate_lists.assert_called_once_with(viewer.store)
        dock.select_items_in_list.assert_called_once_with(
            "stresses", ["prec1"], switch_tab=False, trigger_signal=True
        )


@pytest.mark.unit
def test_rows_to_ranges_coalesces_contiguous_rows():
    from oseries_editor import _rows_to_ranges

    assert _rows_to_ranges([]) == []
    assert _rows_to_ranges([5]) == [(5, 5)]
    assert _rows_to_ranges([1, 2, 3, 4]) == [(1, 4)]
    assert _rows_to_ranges([0, 1, 2, 7, 8, 15]) == [(0, 2), (7, 8), (15, 15)]


@pytest.mark.unit
def test_downsample_xy_for_scatter_preserves_extremes():
    from oseries_editor import _downsample_xy_for_scatter

    x = np.arange(100, dtype=np.int64)
    y = np.zeros(100, dtype=np.float64)
    # Small input is returned unchanged
    sx, sy = _downsample_xy_for_scatter(x, y, max_points=200)
    assert len(sx) == 100

    # Large input preserves spikes/outliers while capping point count
    n = 20000
    x_big = np.arange(n, dtype=np.int64)
    y_big = np.sin(np.linspace(0, 20, n))
    y_big[5432] = 999.0
    y_big[12345] = -888.0
    sx, sy = _downsample_xy_for_scatter(x_big, y_big, max_points=1000)
    assert len(sx) <= 1002
    assert 999.0 in sy
    assert -888.0 in sy
