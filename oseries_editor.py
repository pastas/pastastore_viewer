# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
from qgis.core import QgsApplication
from qgis.PyQt.QtCore import (
    QAbstractTableModel,
    QDateTime,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QRectF,
    Qt,
)
from qgis.PyQt.QtGui import QColor, QPen
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QAction,
    QDialog,
    QGraphicsRectItem,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
)

try:
    from .plot_toolbar import PlotNavigationWidget
except (ImportError, ValueError):
    from plot_toolbar import PlotNavigationWidget


try:
    import pyqtgraph as pg
    from pyqtgraph import DateAxisItem

    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False


_TableModelBase = (
    QAbstractTableModel if isinstance(QAbstractTableModel, type) else object
)


def _format_scalar_value(value):
    """Format a scalar measurement value safely for display."""
    if isinstance(value, pd.Series):
        if not value.empty:
            value = value.iloc[0]
    elif isinstance(value, (np.ndarray, list, tuple)):
        if len(value) > 0:
            value = value[0]

    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)


def _rows_to_ranges(rows):
    """Convert sorted integer row indices into inclusive (start, end) ranges."""
    if len(rows) == 0:
        return []
    arr = np.asarray(rows, dtype=np.int64)
    breaks = np.flatnonzero(np.diff(arr) != 1)
    starts = np.r_[0, breaks + 1]
    ends = np.r_[breaks, len(arr) - 1]
    return [(int(arr[s]), int(arr[e])) for s, e in zip(starts, ends)]


def _downsample_xy_for_scatter(x, y, max_points=5000):
    """Return (x, y) keeping all points when len <= max_points, else min/max per bin.

    Preserves local extremes (outliers/peaks) in O(N) vectorized NumPy time so
    scatter rendering stays interactive even for 100k+ measurements.
    """
    n = len(x)
    if n <= max_points or max_points < 2:
        return x, y

    n_bins = max_points // 2
    bin_size = n // n_bins
    usable = bin_size * n_bins
    y_2d = y[:usable].reshape(n_bins, bin_size)
    offsets = np.arange(n_bins, dtype=np.int64) * bin_size
    min_idx = offsets + np.argmin(y_2d, axis=1)
    max_idx = offsets + np.argmax(y_2d, axis=1)

    idx = np.empty(n_bins * 2, dtype=np.int64)
    idx[0::2] = np.minimum(min_idx, max_idx)
    idx[1::2] = np.maximum(min_idx, max_idx)

    if usable < n:
        tail_y = y[usable:]
        t_min = usable + int(np.argmin(tail_y))
        t_max = usable + int(np.argmax(tail_y))
        idx = np.concatenate([idx, [min(t_min, t_max), max(t_min, t_max)]])

    return x[idx], y[idx]


class SeriesTableModel(_TableModelBase):
    """Virtual table model backed directly by pandas Index and NumPy arrays.

    Avoids allocating O(N) QTableWidgetItems so opening, sorting, selecting, and
    editing series with 100k+ measurements remains instantaneous.
    """

    def __init__(self, on_value_edited=None, on_after_sort=None, parent=None):
        if _TableModelBase is not object:
            super().__init__(parent)
        self._index = pd.Index([])
        self._values = np.array([], dtype=float)
        self._order = np.array([], dtype=np.int64)
        self._inv_order = np.array([], dtype=np.int64)
        self._sort_column = 0
        self._sort_ascending = True
        self._on_value_edited = on_value_edited
        self._on_after_sort = on_after_sort

    def set_data(self, index, values):
        """Replace underlying valid-data arrays and apply current sort order."""
        if _TableModelBase is not object:
            self.beginResetModel()
        self._index = index
        self._values = np.asarray(values)
        self._rebuild_order()
        if _TableModelBase is not object:
            self.endResetModel()

    def _rebuild_order(self):
        n = len(self._index)
        if n == 0:
            self._order = np.array([], dtype=np.int64)
            self._inv_order = np.array([], dtype=np.int64)
            return

        if self._sort_column == 0:
            if self._index.is_monotonic_increasing:
                order = (
                    np.arange(n, dtype=np.int64)
                    if self._sort_ascending
                    else np.arange(n - 1, -1, -1, dtype=np.int64)
                )
            else:
                order = np.argsort(self._index.to_numpy(), kind="mergesort").astype(
                    np.int64
                )
                if not self._sort_ascending:
                    order = order[::-1].copy()
        else:
            order = np.argsort(self._values, kind="mergesort").astype(np.int64)
            if not self._sort_ascending:
                order = order[::-1].copy()

        self._order = order
        inv = np.empty(n, dtype=np.int64)
        inv[order] = np.arange(n, dtype=np.int64)
        self._inv_order = inv

    def rowCount(self, parent=None):
        if parent is not None and parent.isValid():
            return 0
        return len(self._order)

    def columnCount(self, parent=None):
        if parent is not None and parent.isValid():
            return 0
        return 2

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (
            role == Qt.ItemDataRole.DisplayRole
            and orientation == Qt.Orientation.Horizontal
        ):
            return "DateTime" if section == 0 else "Value"
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._order):
            return None
        pos = int(self._order[row])
        col = index.column()

        if col == 0:
            if role == Qt.ItemDataRole.DisplayRole:
                ts = self._index[pos]
                if isinstance(ts, pd.Timestamp):
                    return ts.strftime("%Y-%m-%d %H:%M:%S")
                return str(ts)
            if role == Qt.ItemDataRole.UserRole:
                return self._index[pos]
            return None

        if col == 1:
            if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
                return _format_scalar_value(self._values[pos])
            if role == Qt.ItemDataRole.UserRole:
                return float(self._values[pos])
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 1:
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if (
            not index.isValid()
            or index.column() != 1
            or role != Qt.ItemDataRole.EditRole
        ):
            return False
        try:
            val = float(value)
        except (TypeError, ValueError):
            return False

        row = index.row()
        if row < 0 or row >= len(self._order):
            return False
        pos = int(self._order[row])
        self._values[pos] = val
        if _TableModelBase is not object:
            self.dataChanged.emit(index, index)
        if self._on_value_edited is not None:
            self._on_value_edited(pos, val)
        return True

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        self._sort_column = column
        self._sort_ascending = order == Qt.SortOrder.AscendingOrder
        if _TableModelBase is not object:
            self.layoutAboutToBeChanged.emit()
        self._rebuild_order()
        if _TableModelBase is not object:
            self.layoutChanged.emit()
        if self._on_after_sort is not None:
            self._on_after_sort()

    def update_value_at_plot_pos(self, pos, value):
        """Update a single value in place without resetting the model."""
        if pos < 0 or pos >= len(self._values):
            return
        self._values[pos] = value
        if _TableModelBase is not object:
            row = int(self._inv_order[pos])
            idx = self.index(row, 1)
            self.dataChanged.emit(idx, idx)

    def plot_positions_for_rows(self, rows):
        """Map table row indices to underlying valid-data / plot positions."""
        if len(rows) == 0 or len(self._order) == 0:
            return np.array([], dtype=np.int64)
        return self._order[rows]

    def rows_for_plot_mask(self, mask):
        """Map boolean mask over valid-data / plot positions to sorted table rows."""
        if len(self._inv_order) == 0 or mask is None or not np.any(mask):
            return np.array([], dtype=np.int64)
        rows = self._inv_order[mask]
        if len(rows) > 1:
            rows = np.sort(rows)
        return rows

    def timestamp_at_row(self, row):
        pos = int(self._order[row])
        return self._index[pos]

    def value_at_row(self, row):
        pos = int(self._order[row])
        return float(self._values[pos])


class SelectionViewBox(pg.ViewBox):
    """ViewBox that supports rectangle selection and double-click to clear selection."""

    def __init__(self, on_select=None, on_double_click=None, *args, **kwargs):
        super(SelectionViewBox, self).__init__(*args, **kwargs)
        self.on_select = on_select
        self.on_double_click = on_double_click
        self.selection_enabled = True
        self._rb_origin = None
        self._rb_item = QGraphicsRectItem(self)
        self._rb_item.setPen(QPen(QColor(255, 255, 0, 200), 1))
        self._rb_item.setBrush(QColor(255, 255, 0, 40))
        self._rb_item.setZValue(1e9)
        self._rb_item.hide()

    def mouseDoubleClickEvent(self, ev):
        if self.selection_enabled and ev.button() == Qt.MouseButton.LeftButton:
            ev.accept()
            if self.on_double_click:
                self.on_double_click()
        else:
            super(SelectionViewBox, self).mouseDoubleClickEvent(ev)

    def enable_select_mode(self):
        self.selection_enabled = True
        self.setMouseMode(self.RectMode)

    def enable_zoom_mode(self):
        self.selection_enabled = False
        self.setMouseMode(self.RectMode)

    def enable_pan_mode(self):
        self.selection_enabled = False
        self.setMouseMode(self.PanMode)

    def mouseDragEvent(self, ev, axis=None):
        if self.selection_enabled and ev.button() == Qt.MouseButton.LeftButton:
            ev.accept()
            if ev.isStart():
                self._rb_origin = self.mapFromScene(ev.buttonDownScenePos())
                self._rb_item.setRect(QRectF(self._rb_origin, self._rb_origin))
                self._rb_item.show()
            elif ev.isFinish():
                self._rb_item.hide()
                if self._rb_origin is not None and self.on_select:
                    p1 = self.mapToView(self._rb_origin)
                    p2 = self.mapToView(self.mapFromScene(ev.scenePos()))
                    xmin, xmax = sorted([p1.x(), p2.x()])
                    ymin, ymax = sorted([p1.y(), p2.y()])
                    self.on_select(xmin, xmax, ymin, ymax)
                self._rb_origin = None
            else:
                if self._rb_origin is None:
                    return
                current_pos = self.mapFromScene(ev.scenePos())
                rect = QRectF(self._rb_origin, current_pos).normalized()
                self._rb_item.setRect(rect)
        else:
            super(SelectionViewBox, self).mouseDragEvent(ev, axis=axis)


class OseriesEditorDialog(QDialog):
    """Dialog for editing observation series data."""

    MAX_SCATTER_POINTS = 5000

    def __init__(self, oseries_name, series_data, parent=None, series_type="oseries"):
        super(OseriesEditorDialog, self).__init__(parent)
        self.oseries_name = oseries_name
        self.series_type = series_type
        coerced_series = self._coerce_series(series_data)
        self.original_data = coerced_series.copy()
        self.series_data = coerced_series.copy()
        self.selected_points = []
        self._valid_positions = np.array([], dtype=np.int64)
        self._plot_x = None
        self._plot_y = None
        self._plot_x_sorted = True
        self._plot_index = None
        self._selected_mask = None
        self._syncing_selection = False
        self._scatter_shows_all = False
        self.line_plot = None
        self.scatter_plot = None
        self.selected_scatter = None

        type_title = "Stress" if series_type == "stress" else "Oseries"
        self.setWindowTitle(f"Edit {type_title}: {oseries_name}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
        self.resize(1200, 700)

        self.setup_ui()
        self._refresh_all(reset_view=True)
        self.update_save_button_state()

    def _coerce_series(self, series_data):
        """Ensure we have a single pandas Series for the editor."""
        if isinstance(series_data, pd.Series):
            return series_data

        if isinstance(series_data, pd.DataFrame):
            if "value" in series_data.columns:
                return series_data["value"]
            if series_data.shape[1] == 1:
                return series_data.iloc[:, 0]
            return series_data.iloc[:, 0]

        return pd.Series(series_data)

    def _format_value(self, value):
        """Format a value safely for display in the table."""
        return _format_scalar_value(value)

    def _ensure_float_series(self):
        """Ensure numeric series_data can hold float values and NaN cleanly."""
        if not pd.api.types.is_float_dtype(self.series_data.dtype):
            try:
                self.series_data = self.series_data.astype(float)
            except (TypeError, ValueError):
                pass

    def setup_ui(self):
        layout = QVBoxLayout()

        if HAS_PYQTGRAPH:
            zoom_layout = QHBoxLayout()
            self.btn_select = QPushButton()
            self.btn_select.setIcon(QgsApplication.getThemeIcon("/mActionSelect.svg"))
            self.btn_select.setToolTip("Select Points")
            self.plot_nav = PlotNavigationWidget(
                on_rect=self._enable_rect_zoom,
                on_pan=self._enable_pan_zoom,
                on_full=self.fit_plot,
                default_mode=None,
                parent=self,
            )
            self.btn_remove = QPushButton()
            self.btn_remove.setIcon(
                QgsApplication.getThemeIcon("/mActionDeleteSelected.svg")
            )
            self.btn_remove.setToolTip("Remove Selected Points")
            self.btn_add = QPushButton()
            self.btn_add.setIcon(
                QgsApplication.getThemeIcon("/mActionNewAttribute.svg")
            )
            self.btn_add.setToolTip("Add Observation")
            self.btn_modify = QPushButton()
            self.btn_modify.setIcon(
                QgsApplication.getThemeIcon("/mActionEditTable.svg")
            )
            self.btn_modify.setToolTip("Modify Selected Point")
            self.btn_offset = QPushButton()
            self.btn_offset.setIcon(
                QgsApplication.getThemeIcon("/mActionCalculateField.svg")
            )
            self.btn_offset.setToolTip("Add Offset to Selected Measurements")
            self.btn_select.setCheckable(True)
            self.btn_select.setMaximumWidth(40)
            self.btn_select.clicked.connect(self._enable_select_mode)
            self.btn_remove.clicked.connect(self.remove_selected)
            self.btn_add.clicked.connect(self.add_point)
            self.btn_modify.clicked.connect(self.modify_selected)
            self.btn_offset.clicked.connect(self.add_offset_to_selected)
            zoom_layout.addWidget(self.btn_select)
            zoom_layout.addWidget(self.plot_nav)
            zoom_layout.addStretch()
            zoom_layout.addWidget(self.btn_remove)
            zoom_layout.addWidget(self.btn_add)
            zoom_layout.addWidget(self.btn_modify)
            zoom_layout.addWidget(self.btn_offset)
            layout.addLayout(zoom_layout)

        # Create splitter for plot and table
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Plot widget
        if HAS_PYQTGRAPH:
            self.view_box = SelectionViewBox(
                on_select=self._on_rect_selected,
                on_double_click=self.clear_selection,
            )
            self.plot_widget = pg.PlotWidget(
                viewBox=self.view_box, axisItems={"bottom": DateAxisItem()}
            )
            self.plot_widget.setBackground("w")
            self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
            self.view_box.enable_select_mode()

            # Style axes
            for axis in ["bottom", "left"]:
                ax = self.plot_widget.getAxis(axis)
                ax.setPen("k")
                ax.setTextPen("k")

            type_title = (
                "Stress"
                if getattr(self, "series_type", "oseries") == "stress"
                else "Oseries"
            )
            self.plot_widget.setTitle(f"{type_title}: {self.oseries_name}", color="k")

            # Reusable plot items updated in-place via setData()
            self.line_plot = self.plot_widget.plot(
                [], [], pen=pg.mkPen("#1f77b4", width=1), connect="finite"
            )
            self.line_plot.setDownsampling(auto=True, method="peak")
            self.line_plot.setClipToView(True)

            self.scatter_plot = pg.ScatterPlotItem(
                x=[],
                y=[],
                size=7,
                pen=pg.mkPen(None),
                brush=pg.mkBrush(31, 119, 180, 120),
                symbol="o",
                pxMode=True,
            )
            self.plot_widget.addItem(self.scatter_plot)

            self.selected_scatter = pg.ScatterPlotItem(
                x=[],
                y=[],
                size=8,
                pen=pg.mkPen(None),
                brush=pg.mkBrush(255, 165, 0, 210),
                symbol="o",
                pxMode=True,
            )
            self.selected_scatter.setZValue(10)
            self.plot_widget.addItem(self.selected_scatter)

            self.view_box.sigXRangeChanged.connect(self._update_visible_scatter)
            splitter.addWidget(self.plot_widget)

        # Virtual table view backed by SeriesTableModel
        self.table_model = SeriesTableModel(
            on_value_edited=self._on_model_value_edited,
            on_after_sort=self._on_table_sorted,
            parent=self,
        )
        self.table = QTableView()
        self.table.setModel(self.table_model)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.table.setColumnWidth(0, 130)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)
        if self.table.selectionModel() is not None:
            self.table.selectionModel().selectionChanged.connect(
                self._on_table_selection_changed
            )
        self.table.setMinimumWidth(0)
        splitter.addWidget(self.table)

        splitter.setChildrenCollapsible(True)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([960, 240])
        layout.addWidget(splitter)

        if HAS_PYQTGRAPH:
            self._enable_select_mode()

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.btn_reset = QPushButton("Reset to Original")
        self.btn_reset.clicked.connect(self.reset_data)
        button_layout.addWidget(self.btn_reset)

        self.btn_save = QPushButton("Save")
        self.btn_save.clicked.connect(self.accept)
        button_layout.addWidget(self.btn_save)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        button_layout.addWidget(self.btn_cancel)

        layout.addLayout(button_layout)
        self.setLayout(layout)
        self.update_save_button_state()
        self._update_modify_button_state()

    def _sync_valid_data(self):
        """Extract non-NaN positions, index, epoch-x, and y arrays once."""
        notna_mask = self.series_data.notna().to_numpy()
        self._valid_positions = np.flatnonzero(notna_mask)

        if len(self._valid_positions) == 0:
            self._plot_index = self.series_data.index[:0]
            self._plot_x = np.array([], dtype=np.float64)
            self._plot_y = np.array([], dtype=np.float64)
            self._plot_x_sorted = True
            self._selected_mask = np.zeros(0, dtype=bool)
            return

        self._plot_index = self.series_data.index[self._valid_positions]
        if pd.api.types.is_datetime64_any_dtype(self._plot_index):
            self._plot_x = (
                self._plot_index.astype("datetime64[s]").astype(np.int64).to_numpy()
            )
        else:
            self._plot_x = np.asarray(self._plot_index)

        raw_y = self.series_data.to_numpy()[self._valid_positions]
        try:
            self._plot_y = np.asarray(raw_y, dtype=np.float64)
        except (TypeError, ValueError):
            self._plot_y = np.asarray(raw_y)

        self._plot_x_sorted = bool(
            len(self._plot_x) < 2 or np.all(self._plot_x[:-1] <= self._plot_x[1:])
        )
        self._selected_mask = np.zeros(len(self._valid_positions), dtype=bool)

    def _refresh_all(self, reset_view=False):
        """Refresh cached arrays, virtual table model, and plot items in one pass."""
        self._sync_valid_data()
        self._syncing_selection = True
        try:
            self.table_model.set_data(self._plot_index, self._plot_y.copy())
        finally:
            self._syncing_selection = False
        self._update_plot_items(reset_view=reset_view)
        self._update_modify_button_state()

    def update_save_button_state(self):
        """Update the enabled state of the Save button based on unsaved changes."""
        if hasattr(self, "btn_save"):
            self.btn_save.setEnabled(self._has_unsaved_changes())

    def _get_selected_table_rows(self):
        """Return sorted 1D array of selected visual row indices."""
        sel_model = self.table.selectionModel()
        if sel_model is None:
            return np.array([], dtype=np.int64)
        ranges = sel_model.selection()
        if not ranges:
            return np.array([], dtype=np.int64)
        chunks = [
            np.arange(r.top(), r.bottom() + 1, dtype=np.int64) for r in ranges
        ]
        if len(chunks) == 1:
            return chunks[0]
        return np.unique(np.concatenate(chunks))

    def _get_selected_row_count(self):
        """Return number of selected rows without allocating full arrays for single ranges."""
        sel_model = self.table.selectionModel()
        if sel_model is None:
            return 0
        ranges = sel_model.selection()
        if not ranges:
            return 0
        if len(ranges) == 1:
            return ranges[0].bottom() - ranges[0].top() + 1
        return len(self._get_selected_table_rows())

    def _get_selected_plot_positions(self):
        """Return underlying valid-data indices corresponding to selected table rows."""
        rows = self._get_selected_table_rows()
        if len(rows) == 0:
            return np.array([], dtype=np.int64)
        return self.table_model.plot_positions_for_rows(rows)

    def _update_modify_button_state(self):
        """Enable 'Modify Selected Point' button only if exactly one point is selected."""
        if hasattr(self, "btn_modify"):
            self.btn_modify.setEnabled(self._get_selected_row_count() == 1)

    def clear_selection(self):
        """Clear point selection in table and plot."""
        self._syncing_selection = True
        try:
            self.table.clearSelection()
        finally:
            self._syncing_selection = False
        if self._plot_index is not None:
            self._selected_mask = np.zeros(len(self._plot_index), dtype=bool)
            self._update_plot_selection()
        self._update_modify_button_state()

    def _on_model_value_edited(self, pos, val):
        """Handle inline edit in Value column in O(1) without rebuilding table/plot."""
        self._ensure_float_series()
        self.series_data.iloc[self._valid_positions[pos]] = val
        if self._plot_y is not None and pos < len(self._plot_y):
            self._plot_y[pos] = val
            self._update_plot_items(reset_view=False)
            self._update_plot_selection()
        self.update_save_button_state()

    def _on_table_sorted(self):
        """Keep visual selection synced with the selected measurements after sorting."""
        if self._selected_mask is not None and np.any(self._selected_mask):
            self._select_table_rows_from_mask(scroll=False)

    def populate_table(self):
        """Populate virtual table model with series data."""
        self._sync_valid_data()
        self._syncing_selection = True
        try:
            self.table_model.set_data(self._plot_index, self._plot_y.copy())
        finally:
            self._syncing_selection = False
        self._update_modify_button_state()

    def plot_data(self):
        """Update the time series plot."""
        if not HAS_PYQTGRAPH:
            return
        if self._plot_x is None:
            self._sync_valid_data()
        self._update_plot_items(reset_view=False)

    def _update_plot_items(self, reset_view=False):
        """Update reusable curve and scatter items in place."""
        if not HAS_PYQTGRAPH or self.line_plot is None:
            return

        self._scatter_shows_all = False
        if self._plot_x is None or len(self._plot_x) == 0:
            self.line_plot.setData([], [])
            self.scatter_plot.setData([], [])
            self.selected_scatter.setData([], [])
            return

        self.line_plot.setData(self._plot_x, self._plot_y, skipFiniteCheck=True)
        if reset_view:
            self.fit_plot()
        self._update_visible_scatter()
        self._update_plot_selection()

    def _update_visible_scatter(self):
        """Render scatter dots for visible points, peak-downsampling when zoomed out."""
        if not HAS_PYQTGRAPH or self.scatter_plot is None:
            return
        if self._plot_x is None or len(self._plot_x) == 0:
            self.scatter_plot.setData([], [])
            return

        n = len(self._plot_x)
        if n <= self.MAX_SCATTER_POINTS:
            if not self._scatter_shows_all:
                self.scatter_plot.setData(x=self._plot_x, y=self._plot_y)
                self._scatter_shows_all = True
            return

        self._scatter_shows_all = False
        xmin, xmax = self.view_box.viewRange()[0]
        if self._plot_x_sorted:
            lo = int(np.searchsorted(self._plot_x, xmin, side="left"))
            hi = int(np.searchsorted(self._plot_x, xmax, side="right"))
            vis_x = self._plot_x[lo:hi]
            vis_y = self._plot_y[lo:hi]
        else:
            vis_mask = (self._plot_x >= xmin) & (self._plot_x <= xmax)
            vis_x = self._plot_x[vis_mask]
            vis_y = self._plot_y[vis_mask]

        if len(vis_x) == 0:
            self.scatter_plot.setData([], [])
            return

        sx, sy = _downsample_xy_for_scatter(
            vis_x, vis_y, max_points=self.MAX_SCATTER_POINTS
        )
        self.scatter_plot.setData(x=sx, y=sy)

    def _on_rect_selected(self, xmin, xmax, ymin, ymax):
        if self._plot_x is None or self._plot_y is None or len(self._plot_x) == 0:
            return
        mask = (
            (self._plot_x >= xmin)
            & (self._plot_x <= xmax)
            & (self._plot_y >= ymin)
            & (self._plot_y <= ymax)
        )
        self._selected_mask = mask
        self._update_plot_selection()
        self._select_table_rows_from_mask(scroll=True)

    def _update_plot_selection(self):
        """Highlight only the selected points via dedicated overlay scatter item."""
        if not HAS_PYQTGRAPH or self.selected_scatter is None:
            return
        if (
            self._plot_x is None
            or self._selected_mask is None
            or not np.any(self._selected_mask)
        ):
            self.selected_scatter.setData([], [])
            return

        sel_x = self._plot_x[self._selected_mask]
        sel_y = self._plot_y[self._selected_mask]
        sx, sy = _downsample_xy_for_scatter(
            sel_x, sel_y, max_points=self.MAX_SCATTER_POINTS
        )
        self.selected_scatter.setData(x=sx, y=sy)

    def _select_table_rows(self, rows, scroll_hint=None):
        """Apply selection to table in one batched QItemSelection call."""
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return

        self._syncing_selection = True
        try:
            if len(rows) == 0:
                selection_model.clearSelection()
                return

            selection = QItemSelection()
            last_col = self.table_model.columnCount() - 1
            for start_row, end_row in _rows_to_ranges(rows):
                top_left = self.table_model.index(start_row, 0)
                bottom_right = self.table_model.index(end_row, last_col)
                selection.select(top_left, bottom_right)

            selection_model.select(
                selection,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )
            if scroll_hint is not None:
                first_index = self.table_model.index(int(rows[0]), 0)
                self.table.scrollTo(first_index, scroll_hint)
        finally:
            self._syncing_selection = False
            self._update_modify_button_state()

    def _select_table_rows_from_mask(self, scroll=True):
        if self._plot_index is None or self._selected_mask is None:
            return
        if self._syncing_selection:
            return
        rows = self.table_model.rows_for_plot_mask(self._selected_mask)
        hint = QAbstractItemView.ScrollHint.PositionAtCenter if scroll else None
        self._select_table_rows(rows, scroll_hint=hint)

    def _on_table_selection_changed(self, *_args):
        if self._syncing_selection:
            return
        if self._plot_index is None:
            self._update_modify_button_state()
            return

        plot_positions = self._get_selected_plot_positions()
        mask = np.zeros(len(self._plot_index), dtype=bool)
        if len(plot_positions) > 0:
            mask[plot_positions] = True
        self._selected_mask = mask
        self._update_plot_selection()
        self._update_modify_button_state()

    def _enable_rect_zoom(self):
        if not HAS_PYQTGRAPH:
            return
        self.view_box.enable_zoom_mode()
        self.btn_select.setChecked(False)
        self.plot_nav.set_mode("rect", trigger=False)

    def _enable_pan_zoom(self):
        if not HAS_PYQTGRAPH:
            return
        self.view_box.enable_pan_mode()
        self.btn_select.setChecked(False)
        self.plot_nav.set_mode("pan", trigger=False)

    def _enable_select_mode(self):
        if not HAS_PYQTGRAPH:
            return
        self.view_box.enable_select_mode()
        self.btn_select.setChecked(True)
        self.plot_nav.set_mode(None, trigger=False)

    def fit_plot(self):
        if not HAS_PYQTGRAPH:
            return
        self.view_box.enableAutoRange(axis=self.view_box.XYAxes, enable=True)
        self.view_box.autoRange(padding=0.02)

    def remove_selected(self):
        """Remove selected points from the series."""
        plot_positions = self._get_selected_plot_positions()

        if len(plot_positions) == 0:
            QMessageBox.warning(self, "No Selection", "Please select points to remove.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Removal",
            f"Remove {len(plot_positions)} point(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._ensure_float_series()
            iloc_positions = self._valid_positions[plot_positions]
            self.series_data.iloc[iloc_positions] = np.nan

            self._refresh_all(reset_view=False)
            self.update_save_button_state()

    def add_point(self):
        """Add a new point to the series."""
        from qgis.PyQt.QtWidgets import QDateTimeEdit, QDoubleSpinBox

        dialog = QDialog(self)
        dialog.setWindowTitle("Add Observation")
        layout = QVBoxLayout()

        # DateTime picker
        dt_edit = QDateTimeEdit()
        dt_edit.setCalendarPopup(True)
        dt_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        dt_edit.setDateTime(QDateTime.currentDateTime())
        layout.addWidget(dt_edit)

        # Value input
        value_edit = QDoubleSpinBox()
        value_edit.setDecimals(4)
        value_edit.setRange(-1e12, 1e12)
        value_edit.setValue(0.0)
        layout.addWidget(value_edit)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(dialog.accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(dialog.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        dialog.setLayout(layout)

        if dialog.exec():
            qdt = dt_edit.dateTime()
            timestamp = pd.Timestamp(
                year=qdt.date().year(),
                month=qdt.date().month(),
                day=qdt.date().day(),
                hour=qdt.time().hour(),
                minute=qdt.time().minute(),
                second=qdt.time().second(),
            )

            value = value_edit.value()
            self._ensure_float_series()
            self.series_data.loc[timestamp] = value
            self.series_data = self.series_data.sort_index()
            self._refresh_all(reset_view=False)
            self._restore_selection_by_timestamps([timestamp])
            self.update_save_button_state()

    def add_offset_to_selected(self):
        """Add a value/offset to selected measurements (or all if none selected)."""
        plot_positions = self._get_selected_plot_positions()

        if len(plot_positions) == 0:
            if len(self._valid_positions) == 0:
                QMessageBox.warning(
                    self, "No Data", "No measurements available to edit."
                )
                return

            reply = QMessageBox.question(
                self,
                "No Selection",
                "No points selected. Do you want to add an offset to ALL measurements in the series?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

            plot_positions = np.arange(len(self._valid_positions), dtype=np.int64)

        count = len(plot_positions)
        offset, ok = QInputDialog.getDouble(
            self,
            "Add Offset to Measurements",
            f"Enter value to add to {count} measurement(s) (use negative to subtract):",
            value=0.0,
            decimals=4,
        )

        if ok and offset != 0.0:
            self._ensure_float_series()
            iloc_positions = self._valid_positions[plot_positions]
            self.series_data.iloc[iloc_positions] = (
                self.series_data.iloc[iloc_positions].astype(float) + offset
            )
            selected_mask = np.zeros(len(self._valid_positions), dtype=bool)
            selected_mask[plot_positions] = True

            self._refresh_all(reset_view=False)
            self._selected_mask = selected_mask
            self._update_plot_selection()
            self._select_table_rows_from_mask(scroll=False)
            self.update_save_button_state()

    def _restore_selection_by_timestamps(self, timestamps):
        """Restore row selection in table and plot scatter for given timestamps."""
        if not timestamps or self._plot_index is None or len(self._plot_index) == 0:
            return
        mask = np.asarray(self._plot_index.isin(timestamps), dtype=bool)
        self._selected_mask = mask
        self._update_plot_selection()
        rows = self.table_model.rows_for_plot_mask(mask)
        self._select_table_rows(
            rows, scroll_hint=QAbstractItemView.ScrollHint.EnsureVisible
        )

    def _show_table_context_menu(self, position):
        menu = QMenu(self)
        selected_count = self._get_selected_row_count()

        act_offset = QAction("Add Offset to Selected...", self)
        if hasattr(QgsApplication, "getThemeIcon"):
            icon = QgsApplication.getThemeIcon("/mActionCalculateField.svg")
            if not icon.isNull():
                act_offset.setIcon(icon)
        act_offset.triggered.connect(self.add_offset_to_selected)
        menu.addAction(act_offset)

        act_modify = QAction("Modify Selected Point...", self)
        act_modify.setEnabled(selected_count == 1)
        if hasattr(QgsApplication, "getThemeIcon"):
            icon = QgsApplication.getThemeIcon("/mActionEditTable.svg")
            if not icon.isNull():
                act_modify.setIcon(icon)
        act_modify.triggered.connect(self.modify_selected)
        menu.addAction(act_modify)

        act_remove = QAction("Remove Selected Points", self)
        if hasattr(QgsApplication, "getThemeIcon"):
            icon = QgsApplication.getThemeIcon("/mActionDeleteSelected.svg")
            if not icon.isNull():
                act_remove.setIcon(icon)
        act_remove.triggered.connect(self.remove_selected)
        menu.addAction(act_remove)

        act_add = QAction("Add Observation...", self)
        if hasattr(QgsApplication, "getThemeIcon"):
            icon = QgsApplication.getThemeIcon("/mActionNewAttribute.svg")
            if not icon.isNull():
                act_add.setIcon(icon)
        act_add.triggered.connect(self.add_point)
        menu.addAction(act_add)

        menu.exec(self.table.viewport().mapToGlobal(position))

    def modify_selected(self):
        """Modify the value of selected points."""
        selected_rows = self._get_selected_table_rows()

        if len(selected_rows) == 0:
            QMessageBox.warning(self, "No Selection", "Please select points to modify.")
            return

        if len(selected_rows) > 1:
            self.add_offset_to_selected()
            return

        row = int(selected_rows[0])
        pos = int(self.table_model.plot_positions_for_rows(np.array([row]))[0])
        timestamp = self.table_model.timestamp_at_row(row)
        timestamp_str = (
            timestamp.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(timestamp, pd.Timestamp)
            else str(timestamp)
        )
        current_value = self.table_model.value_at_row(row)

        value, ok = QInputDialog.getDouble(
            self,
            "Modify Point",
            f"Enter new value for {timestamp_str}:",
            value=current_value,
            decimals=4,
        )

        if ok:
            self._ensure_float_series()
            self.series_data.iloc[self._valid_positions[pos]] = value
            self._plot_y[pos] = value
            self.table_model.update_value_at_plot_pos(pos, value)
            self._update_plot_items(reset_view=False)
            self._update_plot_selection()
            self.update_save_button_state()

    def reset_data(self):
        """Reset data to original."""
        reply = QMessageBox.question(
            self,
            "Confirm Reset",
            "Reset all changes to original data?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.series_data = self.original_data.copy()
            self._refresh_all(reset_view=True)
            self.update_save_button_state()

    def get_modified_series(self):
        """Return the modified series."""
        return self.series_data

    def _has_unsaved_changes(self):
        """Return True when measurements differ from the original series."""
        return not self.series_data.equals(self.original_data)

    def keyPressEvent(self, event):
        """Map Delete key to the same behavior as 'Remove Selected Points'."""
        if event.key() == Qt.Key.Key_Delete:
            if self._get_selected_row_count() > 0:
                self.remove_selected()
                event.accept()
                return
        super(OseriesEditorDialog, self).keyPressEvent(event)

    def reject(self):
        """Prompt to keep or discard edits before rejecting the dialog."""
        if not self._has_unsaved_changes():
            super(OseriesEditorDialog, self).reject()
            return

        reply = QMessageBox.question(
            self,
            "Unsaved Changes",
            "Some measurements were edited. Keep these changes?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.accept()
            return

        if reply == QMessageBox.StandardButton.No:
            self.series_data = self.original_data.copy()
            super(OseriesEditorDialog, self).reject()
            return


# Alias for generic series editor usage
SeriesEditorDialog = OseriesEditorDialog
