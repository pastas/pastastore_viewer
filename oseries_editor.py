# -*- coding: utf-8 -*-

from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QGraphicsRectItem,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QInputDialog,
    QSplitter,
)
from qgis.PyQt.QtCore import Qt, QDateTime, QRectF
from qgis.PyQt.QtGui import QColor, QPen
import pandas as pd
import numpy as np

try:
    import pyqtgraph as pg
    from pyqtgraph import DateAxisItem

    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False


class SelectionViewBox(pg.ViewBox):
    """ViewBox that supports rectangle selection."""

    def __init__(self, on_select=None, *args, **kwargs):
        super(SelectionViewBox, self).__init__(*args, **kwargs)
        self.on_select = on_select
        self.selection_enabled = True
        self._rb_origin = None
        self._rb_item = QGraphicsRectItem(self)
        self._rb_item.setPen(QPen(QColor(255, 255, 0, 200), 1))
        self._rb_item.setBrush(QColor(255, 255, 0, 40))
        self._rb_item.setZValue(1e9)
        self._rb_item.hide()

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
        if self.selection_enabled and ev.button() == Qt.LeftButton:
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

    def __init__(self, oseries_name, series_data, parent=None):
        super(OseriesEditorDialog, self).__init__(parent)
        self.oseries_name = oseries_name
        coerced_series = self._coerce_series(series_data)
        self.original_data = coerced_series.copy()
        self.series_data = coerced_series.copy()
        self.selected_points = []
        self._plot_x = None
        self._plot_y = None
        self._plot_index = None
        self._selected_mask = None
        self._syncing_selection = False

        self.setWindowTitle(f"Edit Oseries: {oseries_name}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        self.resize(1200, 700)

        self.setup_ui()
        self.populate_table()
        self.plot_data()

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

    def setup_ui(self):
        layout = QVBoxLayout()

        if HAS_PYQTGRAPH:
            zoom_layout = QHBoxLayout()
            self.btn_select = QPushButton("Select")
            self.btn_zoom_in = QPushButton("+")
            self.btn_pan = QPushButton("Pan")
            self.btn_show_all = QPushButton("All")
            self.btn_remove = QPushButton("Remove Selected")
            self.btn_add = QPushButton("Add Observation")
            self.btn_modify = QPushButton("Modify Selected")
            self.btn_select.setCheckable(True)
            self.btn_zoom_in.setCheckable(True)
            self.btn_pan.setCheckable(True)
            self.btn_select.setMaximumWidth(70)
            self.btn_zoom_in.setMaximumWidth(60)
            self.btn_pan.setMaximumWidth(60)
            self.btn_show_all.setMaximumWidth(60)
            self.btn_select.clicked.connect(self._enable_select_mode)
            self.btn_zoom_in.clicked.connect(self._enable_rect_zoom)
            self.btn_pan.clicked.connect(self._enable_pan_zoom)
            self.btn_show_all.clicked.connect(self.fit_plot)
            self.btn_remove.clicked.connect(self.remove_selected)
            self.btn_add.clicked.connect(self.add_point)
            self.btn_modify.clicked.connect(self.modify_selected)
            zoom_layout.addWidget(self.btn_select)
            zoom_layout.addWidget(self.btn_zoom_in)
            zoom_layout.addWidget(self.btn_pan)
            zoom_layout.addWidget(self.btn_show_all)
            zoom_layout.addStretch()
            zoom_layout.addWidget(self.btn_remove)
            zoom_layout.addWidget(self.btn_add)
            zoom_layout.addWidget(self.btn_modify)
            layout.addLayout(zoom_layout)

        # Create splitter for plot and table
        splitter = QSplitter(Qt.Horizontal)

        # Plot widget
        if HAS_PYQTGRAPH:
            self.view_box = SelectionViewBox(on_select=self._on_rect_selected)
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

            self.plot_widget.setTitle(f"Oseries: {self.oseries_name}", color="k")
            splitter.addWidget(self.plot_widget)

            # Enable point selection
            self.scatter_plot = None

        # Table widget
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["DateTime", "Value"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setColumnWidth(0, 120)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        splitter.addWidget(self.table)

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

    def populate_table(self):
        """Populate table with series data."""
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        # Get non-NaN values
        valid_data = self.series_data.dropna()

        self.table.setRowCount(len(valid_data))
        for i, (timestamp, value) in enumerate(valid_data.items()):
            # DateTime
            if isinstance(timestamp, pd.Timestamp):
                dt_text = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            else:
                dt_text = str(timestamp)
            dt_item = QTableWidgetItem(dt_text)
            dt_item.setData(Qt.UserRole, timestamp)
            dt_item.setFlags(dt_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(i, 0, dt_item)

            # Value - format safely to handle unexpected value containers
            val_item = QTableWidgetItem(self._format_value(value))
            self.table.setItem(i, 1, val_item)

        self.table.setSortingEnabled(True)

    def plot_data(self):
        """Plot the time series data."""
        if not HAS_PYQTGRAPH:
            return

        self.plot_widget.clear()

        # Get valid data
        valid_data = self.series_data.dropna()
        if valid_data.empty:
            return

        # Prepare data
        x = valid_data.index
        if pd.api.types.is_datetime64_any_dtype(x):
            x = x.view(np.int64) // 10**9
        y = valid_data.values

        self._plot_x = np.array(x)
        self._plot_y = np.array(y)
        self._plot_index = valid_data.index
        self._selected_mask = np.zeros(len(valid_data), dtype=bool)

        # Plot as scatter for easier selection
        self.scatter_plot = pg.ScatterPlotItem(
            x=x,
            y=y,
            size=8,
            pen=pg.mkPen(None),
            brush=pg.mkBrush(0, 0, 255, 120),
            symbol="o",
        )
        self.plot_widget.addItem(self.scatter_plot)

        # Also add line
        self.plot_widget.plot(x, y, pen=pg.mkPen("b", width=1), connect="finite")

    def _on_rect_selected(self, xmin, xmax, ymin, ymax):
        if self._plot_x is None or self._plot_y is None:
            return
        mask = (
            (self._plot_x >= xmin)
            & (self._plot_x <= xmax)
            & (self._plot_y >= ymin)
            & (self._plot_y <= ymax)
        )
        self._selected_mask = mask
        self._update_plot_selection()
        self._select_table_rows_from_mask()

    def _update_plot_selection(self):
        if not self.scatter_plot or self._selected_mask is None:
            return
        default_brush = pg.mkBrush(0, 0, 255, 120)
        selected_brush = pg.mkBrush(255, 165, 0, 180)
        brushes = [
            selected_brush if sel else default_brush for sel in self._selected_mask
        ]
        self.scatter_plot.setBrush(brushes)

    def _select_table_rows_from_mask(self):
        if self._plot_index is None or self._selected_mask is None:
            return
        if self._syncing_selection:
            return
        selected_times = set(self._plot_index[self._selected_mask])
        first_selected_item = None
        self._syncing_selection = True
        self.table.blockSignals(True)
        try:
            self.table.clearSelection()
            from qgis.PyQt.QtCore import QItemSelectionModel

            selection_model = self.table.selectionModel()
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item and item.data(Qt.UserRole) in selected_times:
                    if first_selected_item is None:
                        first_selected_item = item
                    index = self.table.model().index(row, 0)
                    selection_model.select(
                        index, QItemSelectionModel.Select | QItemSelectionModel.Rows
                    )
            if first_selected_item is not None:
                self.table.scrollToItem(
                    first_selected_item, QTableWidget.PositionAtCenter
                )
        finally:
            self.table.blockSignals(False)
            self._syncing_selection = False

    def _on_table_selection_changed(self):
        if self._syncing_selection:
            return
        if self._plot_index is None:
            return
        selected_rows = sorted(set(item.row() for item in self.table.selectedItems()))
        selected_times = set()
        for row in selected_rows:
            item = self.table.item(row, 0)
            if item:
                selected_times.add(item.data(Qt.UserRole))

        self._selected_mask = np.array(
            [ts in selected_times for ts in self._plot_index], dtype=bool
        )
        self._update_plot_selection()

    def _enable_rect_zoom(self):
        if not HAS_PYQTGRAPH:
            return
        self.view_box.enable_zoom_mode()
        self.btn_select.setChecked(False)
        self.btn_zoom_in.setChecked(True)
        self.btn_pan.setChecked(False)

    def _enable_pan_zoom(self):
        if not HAS_PYQTGRAPH:
            return
        self.view_box.enable_pan_mode()
        self.btn_select.setChecked(False)
        self.btn_zoom_in.setChecked(False)
        self.btn_pan.setChecked(True)

    def _enable_select_mode(self):
        if not HAS_PYQTGRAPH:
            return
        self.view_box.enable_select_mode()
        self.btn_select.setChecked(True)
        self.btn_zoom_in.setChecked(False)
        self.btn_pan.setChecked(False)

    def fit_plot(self):
        if not HAS_PYQTGRAPH:
            return
        self.view_box.enableAutoRange(axis=self.view_box.XYAxes, enable=True)
        self.view_box.autoRange(padding=0.02)

    def remove_selected(self):
        """Remove selected points from the series."""
        selected_rows = sorted(
            set(item.row() for item in self.table.selectedItems()), reverse=True
        )

        if not selected_rows:
            QMessageBox.warning(self, "No Selection", "Please select points to remove.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Removal",
            f"Remove {len(selected_rows)} point(s)?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            for row in selected_rows:
                timestamp = self.table.item(row, 0).data(Qt.UserRole)
                self.series_data.loc[timestamp] = np.nan

            self.populate_table()
            self.plot_data()

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

        if dialog.exec_():
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
            self.series_data.loc[timestamp] = value
            self.series_data = self.series_data.sort_index()
            self.populate_table()
            self.plot_data()

    def modify_selected(self):
        """Modify the value of selected points."""
        selected_rows = sorted(set(item.row() for item in self.table.selectedItems()))

        if not selected_rows:
            QMessageBox.warning(self, "No Selection", "Please select points to modify.")
            return

        if len(selected_rows) > 1:
            QMessageBox.warning(
                self, "Multiple Selection", "Please select only one point to modify."
            )
            return

        row = selected_rows[0]
        timestamp_item = self.table.item(row, 0)
        timestamp = timestamp_item.data(Qt.UserRole)
        timestamp_str = timestamp_item.text()
        current_value = float(self.table.item(row, 1).text())

        value, ok = QInputDialog.getDouble(
            self,
            "Modify Point",
            f"Enter new value for {timestamp_str}:",
            value=current_value,
            decimals=4,
        )

        if ok:
            self.series_data.loc[timestamp] = value
            self.populate_table()
            self.plot_data()

    def reset_data(self):
        """Reset data to original."""
        reply = QMessageBox.question(
            self,
            "Confirm Reset",
            "Reset all changes to original data?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self.series_data = self.original_data.copy()
            self.populate_table()
            self.plot_data()

    def get_modified_series(self):
        """Return the modified series."""
        return self.series_data
