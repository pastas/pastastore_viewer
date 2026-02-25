# -*- coding: utf-8 -*-

from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QComboBox,
    QSplitter,
    QGroupBox,
    QRadioButton,
    QButtonGroup,
    QCheckBox,
    QProgressDialog,
    QListWidget,
    QAbstractItemView,
    QApplication,
    QFileDialog,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsWkbTypes,
)
from qgis.gui import QgsMapTool, QgsRubberBand
import pandas as pd
import numpy as np

try:
    import pyqtgraph as pg
    from pyqtgraph import DateAxisItem

    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False

try:
    import brodata

    HAS_BRODATA = True
except ImportError:
    HAS_BRODATA = False


class BROMapExtentTool(QgsMapTool):
    """Map tool for drawing a rectangle extent on the QGIS canvas."""

    def __init__(self, canvas, on_finished, on_canceled=None):
        super(BROMapExtentTool, self).__init__(canvas)
        self.canvas = canvas
        self.on_finished = on_finished
        self.on_canceled = on_canceled
        self.start_point = None
        self.end_point = None
        self.rubber_band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self.rubber_band.setColor(QColor(31, 119, 180, 120))
        self.rubber_band.setStrokeColor(QColor(31, 119, 180, 220))
        self.rubber_band.setWidth(2)
        self.rubber_band.hide()

    def canvasPressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._clear()
            if self.on_canceled:
                self.on_canceled()
            return

        if event.button() != Qt.LeftButton:
            return

        self.start_point = self.toMapCoordinates(event.pos())
        self.end_point = self.start_point
        self._update_rubber_band()
        self.rubber_band.show()

    def canvasMoveEvent(self, event):
        if self.start_point is None:
            return
        self.end_point = self.toMapCoordinates(event.pos())
        self._update_rubber_band()

    def canvasReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self.start_point is None:
            return

        self.end_point = self.toMapCoordinates(event.pos())
        rect = self._normalized_rect(self.start_point, self.end_point)
        self._clear()

        if rect.width() > 0 and rect.height() > 0 and self.on_finished:
            self.on_finished(rect)

    def deactivate(self):
        self._clear()
        super(BROMapExtentTool, self).deactivate()

    def _update_rubber_band(self):
        if self.start_point is None or self.end_point is None:
            return

        rect = self._normalized_rect(self.start_point, self.end_point)
        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        self.rubber_band.addPoint(QgsPointXY(rect.xMinimum(), rect.yMinimum()))
        self.rubber_band.addPoint(QgsPointXY(rect.xMinimum(), rect.yMaximum()))
        self.rubber_band.addPoint(QgsPointXY(rect.xMaximum(), rect.yMaximum()))
        self.rubber_band.addPoint(QgsPointXY(rect.xMaximum(), rect.yMinimum()))
        self.rubber_band.addPoint(QgsPointXY(rect.xMinimum(), rect.yMinimum()))

    @staticmethod
    def _normalized_rect(start_point, end_point):
        rect = QgsRectangle(start_point, end_point)
        if hasattr(rect, "normalized"):
            return rect.normalized()
        rect.normalize()
        return rect

    def _clear(self):
        self.start_point = None
        self.end_point = None
        self.rubber_band.hide()
        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)


class BROImportDialog(QDialog):
    """Dialog for importing observation series from BRO."""

    class _ExtentDownloadCanceled(Exception):
        pass

    series_to_add = pyqtSignal(dict)  # {series_name: series_data}

    def __init__(self, parent=None, iface=None):
        super(BROImportDialog, self).__init__(parent)
        self.iface = iface
        self.downloaded_data = {}  # {series_name: DataFrame}
        self.series_metadata = {}  # {series_name: metadata_dict}
        self._global_filter_selection = {
            "status": [],
            "qualifier": [],
            "observation_type": [],
        }
        self._series_filter_selection = {}
        self.selection_mode = "id"  # "id" or "map"
        self.download_format = "csv"  # "xml" or "csv"
        self.progress_dialog = None  # Progress dialog for downloads
        self._map_select_tool = None
        self._previous_map_tool = None
        self._restore_dialog_after_map_select = False

        self.setWindowTitle("Import from BRO")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        self.resize(1200, 800)

        if not HAS_BRODATA:
            QMessageBox.warning(
                self,
                "Missing Dependency",
                "The 'brodata' package is not installed.\n\n"
                "Please install it using:\npip install brodata",
            )

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        # Input method selection
        input_group = QGroupBox("Data Source")
        input_layout = QVBoxLayout()

        # Radio buttons for selection method
        radio_layout = QHBoxLayout()
        self.btn_group = QButtonGroup()
        self.radio_id = QRadioButton("By ID")
        self.radio_map = QRadioButton("By Map Selection")
        self.radio_id.setChecked(True)
        self.btn_group.addButton(self.radio_id)
        self.btn_group.addButton(self.radio_map)
        self.radio_id.toggled.connect(self._on_selection_mode_changed)
        radio_layout.addWidget(self.radio_id)
        radio_layout.addWidget(self.radio_map)
        radio_layout.addStretch()
        input_layout.addLayout(radio_layout)

        # ID input
        id_layout = QHBoxLayout()
        id_layout.addWidget(QLabel("ID:"))
        self.le_id = QLineEdit()
        self.le_id.setPlaceholderText("Enter GMN-ID, GMW-ID, Well Code, or GLD-ID")
        id_layout.addWidget(self.le_id)
        self.btn_download = QPushButton("Download")
        self.btn_download.clicked.connect(self._download_by_id)
        id_layout.addWidget(self.btn_download)
        input_layout.addLayout(id_layout)

        # Format selection
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("Format of GLD-data:"))
        self.combo_format = QComboBox()
        self.combo_format.addItems(["XML", "CSV"])
        self.combo_format.setCurrentText("CSV")
        self.combo_format.currentTextChanged.connect(self._on_format_changed)
        format_layout.addWidget(self.combo_format)
        format_layout.addStretch()
        input_layout.addLayout(format_layout)

        # Download path selection
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("Download path (optional):"))
        self.le_download_path = QLineEdit()
        self.le_download_path.setPlaceholderText("Leave empty to skip saving files")
        path_layout.addWidget(self.le_download_path)
        self.btn_browse_path = QPushButton("Browse")
        self.btn_browse_path.clicked.connect(self._browse_download_path)
        path_layout.addWidget(self.btn_browse_path)
        input_layout.addLayout(path_layout)

        # Map selection button
        map_layout = QHBoxLayout()
        self.btn_map_select = QPushButton("Select Area on Map")
        self.btn_map_select.setEnabled(False)
        self.btn_map_select.clicked.connect(self._select_from_map)
        map_layout.addWidget(self.btn_map_select)
        map_layout.addStretch()
        input_layout.addLayout(map_layout)

        input_group.setLayout(input_layout)
        layout.addWidget(input_group)

        # Main splitter for series list and plot
        splitter = QSplitter(Qt.Horizontal)

        # Left side: Series list with metadata selection
        left_widget = QGroupBox("Downloaded Series")
        left_layout = QVBoxLayout()

        # Series table
        self.table_series = QTableWidget()
        self.table_series.setColumnCount(6)
        self.table_series.setHorizontalHeaderLabels(
            ["Select", "Name", "Location", "Count", "Start", "End"]
        )
        self.table_series.verticalHeader().setVisible(False)
        self.table_series.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table_series.horizontalHeader().setStretchLastSection(True)
        self.table_series.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_series.itemSelectionChanged.connect(self._on_series_selected)
        left_layout.addWidget(self.table_series)

        table_selection_layout = QHBoxLayout()
        self.btn_select_all_locations = QPushButton("Select All Locations")
        self.btn_select_all_locations.clicked.connect(self._select_all_locations)
        table_selection_layout.addWidget(self.btn_select_all_locations)
        self.btn_deselect_all_locations = QPushButton("Deselect All Locations")
        self.btn_deselect_all_locations.clicked.connect(self._deselect_all_locations)
        table_selection_layout.addWidget(self.btn_deselect_all_locations)
        table_selection_layout.addStretch()
        left_layout.addLayout(table_selection_layout)

        # Global metadata selectors
        metadata_group = QGroupBox("Metadata Options (Multi-select)")
        metadata_layout = QVBoxLayout()

        # Status selector
        metadata_layout.addWidget(QLabel("Status:"))
        self.list_status = QListWidget()
        self.list_status.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_status.setMaximumHeight(80)
        self.list_status.itemSelectionChanged.connect(self._on_metadata_changed)
        metadata_layout.addWidget(self.list_status)

        # Qualifier selector
        metadata_layout.addWidget(QLabel("Qualifier:"))
        self.list_qualifier = QListWidget()
        self.list_qualifier.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_qualifier.setMaximumHeight(80)
        self.list_qualifier.itemSelectionChanged.connect(self._on_metadata_changed)
        metadata_layout.addWidget(self.list_qualifier)

        # Observation type selector
        metadata_layout.addWidget(QLabel("Observation Type:"))
        self.list_obs_type = QListWidget()
        self.list_obs_type.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_obs_type.setMaximumHeight(60)
        self.list_obs_type.itemSelectionChanged.connect(self._on_metadata_changed)
        metadata_layout.addWidget(self.list_obs_type)

        # Apply filter changes only to currently selected series
        self.chk_only_this_series = QCheckBox("Only for this series")
        self.chk_only_this_series.setChecked(False)
        self.chk_only_this_series.toggled.connect(self._on_only_this_series_toggled)
        metadata_layout.addWidget(self.chk_only_this_series)

        metadata_group.setLayout(metadata_layout)
        left_layout.addWidget(metadata_group)

        left_widget.setLayout(left_layout)
        splitter.addWidget(left_widget)

        # Right side: Plot
        if HAS_PYQTGRAPH:
            right_widget = QGroupBox("Preview")
            right_layout = QVBoxLayout()

            self.plot_widget = pg.PlotWidget(axisItems={"bottom": DateAxisItem()})
            self.plot_widget.setBackground("w")
            self.plot_widget.showGrid(x=True, y=True, alpha=0.3)

            # Style axes
            for axis in ["bottom", "left"]:
                ax = self.plot_widget.getAxis(axis)
                ax.setPen("k")
                ax.setTextPen("k")

            self.plot_widget.setLabel("left", "Value")
            self.plot_widget.setLabel("bottom", "Time")

            right_layout.addWidget(self.plot_widget)
            right_widget.setLayout(right_layout)
            splitter.addWidget(right_widget)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

        # Bottom buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.btn_add_store = QPushButton("Add to Store")
        self.btn_add_store.clicked.connect(self._add_to_store)
        self.btn_add_store.setEnabled(False)
        button_layout.addWidget(self.btn_add_store)

        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.reject)
        button_layout.addWidget(self.btn_close)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def _on_selection_mode_changed(self, checked):
        """Handle selection mode change."""
        if self.radio_id.isChecked():
            self.selection_mode = "id"
            self.le_id.setEnabled(True)
            self.btn_download.setEnabled(True)
            self.btn_map_select.setEnabled(False)
            self._stop_map_selection(reset_button=False)
        else:
            self.selection_mode = "map"
            self.le_id.setEnabled(False)
            self.btn_download.setEnabled(False)
            self.btn_map_select.setEnabled(True)

    def _on_format_changed(self, format_text):
        """Handle format selection change."""
        self.download_format = format_text.lower()

    def _browse_download_path(self):
        """Browse for download path."""
        path = QFileDialog.getExistingDirectory(
            self, "Select Download Path", self.le_download_path.text()
        )
        if path:
            self.le_download_path.setText(path)

    def _download_by_id(self):
        """Download data from BRO by ID."""
        if not HAS_BRODATA:
            QMessageBox.warning(self, "Error", "brodata package is not installed.")
            return

        id_value = self.le_id.text().strip()
        if not id_value:
            QMessageBox.warning(self, "Error", "Please enter an ID.")
            return

        # Create progress dialog
        self.progress_dialog = QProgressDialog(
            "Downloading data from BRO...", "Cancel", 0, 100, self
        )
        self.progress_dialog.setWindowTitle("BRO Download")
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setValue(0)
        self.progress_dialog.show()
        QApplication.processEvents()  # Force UI update

        try:
            # Determine ID type and download
            id_lower = id_value.lower()

            # Try to determine ID type
            if id_lower.startswith("gmn"):
                # GMN ID - monitoring network
                self._download_gmn(id_value)
            elif id_lower.startswith("gmw"):
                # GMW ID - monitoring well
                self._download_gmw(id_value)
            elif id_lower.startswith("gld"):
                # GLD ID - groundwater level dossier
                self._download_gld(id_value)
            else:
                # Try as well code
                self._download_by_well_code(id_value)

            # Download complete
            if self.progress_dialog:
                self.progress_dialog.setValue(100)
                self.progress_dialog.close()
                self.progress_dialog = None

        except Exception as e:
            import traceback

            # Close progress dialog on error
            if self.progress_dialog:
                self.progress_dialog.close()
                self.progress_dialog = None

            QMessageBox.critical(self, "Error", f"Failed to download data:\n{str(e)}")
            print(traceback.format_exc())

    def _download_gmn(self, gmn_id):
        """Download data from a GMN (Grondwater Meetnet)."""
        try:
            # Update progress
            if self.progress_dialog:
                self.progress_dialog.setLabelText(
                    f"Downloading GMN metadata: {gmn_id}..."
                )
                self.progress_dialog.setValue(10)
                QApplication.processEvents()  # Force UI update

            # Get GMN data
            use_csv = self.download_format == "csv"
            gmn = brodata.gmn.GroundwaterMonitoringNetwork.from_bro_id(gmn_id)

            gmw_ids = gmn.measuringPoint.index.levels[0].unique()
            gmws = brodata.gmw.get_data_for_bro_ids(gmw_ids)

            total_tubes = len(gmn.measuringPoint.index)
            for idx, (gmw_id, tube_number) in enumerate(gmn.measuringPoint.index):
                if self.progress_dialog and self.progress_dialog.wasCanceled():
                    return
                series_name = f"{gmw_id}_{tube_number}"

                try:
                    # Update progress for each tube
                    progress = 10 + int((idx / total_tubes) * 80)
                    if self.progress_dialog:
                        self.progress_dialog.setLabelText(
                            f"Downloading GLD {idx + 1}/{total_tubes}: {series_name}..."
                        )
                        self.progress_dialog.setValue(progress)
                        QApplication.processEvents()  # Force UI update

                    df = brodata.gmw.get_tube_observations(
                        gmw_id, tube_number, as_csv=use_csv
                    )

                    # Store the data
                    self.downloaded_data[series_name] = df

                    # Store metadata
                    self.series_metadata[series_name] = self._metadata_from_gmw(
                        gmws[gmw_id], tube_number
                    )
                except Exception as e:
                    print(f"Error downloading tube {series_name}: {e}")
                    continue

            # Update progress
            if self.progress_dialog:
                self.progress_dialog.setLabelText("Updating table...")
                self.progress_dialog.setValue(95)
                QApplication.processEvents()  # Force UI update

            # Update table
            self._refresh_metadata_filter_lists(select_all=False)
            self._update_series_table()
            self.btn_add_store.setEnabled(True)

        except Exception as e:
            raise Exception(f"Failed to download GMN data: {str(e)}")

    def _download_gmw(self, gmw_id):
        """Download data from a GMW (Grondwater Monitoring Well)."""
        try:
            # Update progress
            if self.progress_dialog:
                self.progress_dialog.setLabelText(
                    f"Downloading GMW metadata: {gmw_id}..."
                )
                self.progress_dialog.setValue(10)
                QApplication.processEvents()  # Force UI update

            # Get GMW data
            use_csv = self.download_format == "csv"
            gmw = brodata.gmw.GroundwaterMonitoringWell.from_bro_id(gmw_id)

            # Download observations for each tube
            total_tubes = len(gmw.monitoringTube.index)
            for idx, tube_number in enumerate(gmw.monitoringTube.index):
                if self.progress_dialog and self.progress_dialog.wasCanceled():
                    return

                # Update progress for each tube
                progress = 10 + int((idx / total_tubes) * 80)
                if self.progress_dialog:
                    self.progress_dialog.setLabelText(
                        f"Downloading observations for tube {idx + 1}/{total_tubes} ({gmw_id}_{tube_number})..."
                    )
                    self.progress_dialog.setValue(progress)
                    QApplication.processEvents()  # Force UI update

                df = brodata.gmw.get_tube_observations(
                    gmw_id, tube_number, as_csv=use_csv
                )

                # Store the data
                series_name = f"{gmw_id}_{tube_number}"
                self.downloaded_data[series_name] = df

                # Store metadata
                self.series_metadata[series_name] = self._metadata_from_gmw(
                    gmw, tube_number
                )

            # Update progress
            if self.progress_dialog:
                self.progress_dialog.setLabelText("Updating table...")
                self.progress_dialog.setValue(95)
                QApplication.processEvents()  # Force UI update

            # Update table
            self._refresh_metadata_filter_lists(select_all=False)
            self._update_series_table()
            self.btn_add_store.setEnabled(True)

        except Exception as e:
            raise Exception(f"Failed to download GMW data: {str(e)}")

    def _metadata_from_gmw(self, gmw, tube_number):
        return {
            "GMW": gmw.broId,
            "tubeNumber": tube_number,
            "screenTopPosition": gmw.monitoringTube.at[
                tube_number, "screenTopPosition"
            ],
            "screenBottomPosition": gmw.monitoringTube.at[
                tube_number, "screenBottomPosition"
            ],
            "x": gmw.deliveredLocation.x,
            "y": gmw.deliveredLocation.y,
        }

    def _refresh_metadata_filter_lists(self, select_all=False):
        status_values = set()
        qualifier_values = set()
        obs_type_values = set()

        for data in self.downloaded_data.values():
            if not hasattr(data, "columns"):
                continue

            if "status" in data.columns:
                status_values.update(data["status"].dropna().astype(str).unique())
            if "qualifier" in data.columns:
                qualifier_values.update(data["qualifier"].dropna().astype(str).unique())
            if "observation_type" in data.columns:
                obs_type_values.update(
                    data["observation_type"].dropna().astype(str).unique()
                )

        self._set_filter_items(
            self.list_status,
            status_values,
            preferred_order=["volledigBeoordeeld", "voorlopig", "onbekend"],
            select_all=select_all,
        )
        self._set_filter_items(
            self.list_qualifier,
            qualifier_values,
            preferred_order=[
                "goedgekeurd",
                "afgekeurd",
                "nogNietBeoordeeld",
                "onbeslist",
                "onbekend",
            ],
            select_all=select_all,
        )
        self._set_filter_items(
            self.list_obs_type,
            obs_type_values,
            preferred_order=["reguliereMeting", "controleMeting"],
            select_all=select_all,
        )

    def _set_filter_items(
        self, list_widget, values, preferred_order=None, select_all=True
    ):
        ordered = []
        values_set = {str(value) for value in values if str(value) != ""}
        had_items_before = list_widget.count() > 0
        selected_before = {item.text() for item in list_widget.selectedItems()}

        if preferred_order:
            for value in preferred_order:
                if value in values_set:
                    ordered.append(value)
                    values_set.remove(value)

        ordered.extend(sorted(values_set))

        list_widget.blockSignals(True)
        try:
            list_widget.clear()
            list_widget.addItems(ordered)
            if select_all:
                for i in range(list_widget.count()):
                    list_widget.item(i).setSelected(True)
            elif had_items_before:
                for i in range(list_widget.count()):
                    item = list_widget.item(i)
                    if item.text() in selected_before:
                        item.setSelected(True)
            else:
                for i in range(list_widget.count()):
                    list_widget.item(i).setSelected(True)
        finally:
            list_widget.blockSignals(False)

        if not self.chk_only_this_series.isChecked():
            self._global_filter_selection = self._get_filter_selection_from_lists()

    def _get_filter_selection_from_lists(self):
        return {
            "status": [item.text() for item in self.list_status.selectedItems()],
            "qualifier": [item.text() for item in self.list_qualifier.selectedItems()],
            "observation_type": [
                item.text() for item in self.list_obs_type.selectedItems()
            ],
        }

    def _get_current_series_name(self):
        selected_items = self.table_series.selectedItems()
        if not selected_items:
            return None
        row = selected_items[0].row()
        name_item = self.table_series.item(row, 1)
        if not name_item:
            return None
        return name_item.text()

    def _apply_filter_selection_to_lists(self, filter_selection, select_all_if_empty=True):
        mapping = [
            (self.list_status, set(filter_selection.get("status", []))),
            (self.list_qualifier, set(filter_selection.get("qualifier", []))),
            (self.list_obs_type, set(filter_selection.get("observation_type", []))),
        ]

        for list_widget, selected_values in mapping:
            list_widget.blockSignals(True)
            try:
                for i in range(list_widget.count()):
                    item = list_widget.item(i)
                    if select_all_if_empty and not selected_values:
                        item.setSelected(True)
                    else:
                        item.setSelected(item.text() in selected_values)
            finally:
                list_widget.blockSignals(False)

    def _get_filters_for_series(self, series_name):
        return self._series_filter_selection.get(
            series_name,
            self._global_filter_selection,
        )

    def _select_all_locations(self):
        for i in range(self.table_series.rowCount()):
            chk = self.table_series.cellWidget(i, 0)
            if chk:
                chk.setChecked(True)

    def _deselect_all_locations(self):
        for i in range(self.table_series.rowCount()):
            chk = self.table_series.cellWidget(i, 0)
            if chk:
                chk.setChecked(False)

    def _on_only_this_series_toggled(self, checked):
        series_name = self._get_current_series_name()
        if not series_name:
            return

        if checked:
            if series_name not in self._series_filter_selection:
                self._series_filter_selection[series_name] = (
                    self._get_filter_selection_from_lists()
                )
        else:
            self._apply_filter_selection_to_lists(
                self._global_filter_selection,
                select_all_if_empty=True,
            )

        if series_name in self.downloaded_data:
            self._plot_series(series_name)

    def _download_gld(self, gld_id, update_progress=True):
        """Download GLD (Groundwater Level Dossier) data."""
        try:
            # Update progress
            if update_progress and self.progress_dialog:
                self.progress_dialog.setLabelText(f"Downloading GLD: {gld_id}...")
                self.progress_dialog.setValue(20)
                QApplication.processEvents()  # Force UI update

            # Get GLD data
            use_csv = self.download_format == "csv"
            if use_csv:
                df = brodata.gld.get_objects_as_csv(gld_id)
            else:
                gld = brodata.gld.GroundwaterLevelDossier.from_bro_id(
                    gld_id, as_csv=use_csv
                )
                df = gld.observation

            # Store the data
            series_name = gld_id

            # Extract timeseries data
            self.downloaded_data[series_name] = df

            # Update progress
            if update_progress and self.progress_dialog:
                self.progress_dialog.setLabelText(
                    f"Downloading GMW metadata for {gld_id}..."
                )
                self.progress_dialog.setValue(60)
                QApplication.processEvents()  # Force UI update

            # get well
            if use_csv:
                # we do not know the gmw id from the csv, so we cannot get metadata
                metadata = {}
            else:
                gmw_id = gld.groundwaterMonitoringWell
                gmw = brodata.gmw.GroundwaterMonitoringWell.from_bro_id(gmw_id)
                metadata = self._metadata_from_gmw(gmw, gld.tubeNumber)

            # Store metadata
            self.series_metadata[series_name] = metadata

            # Update progress
            if update_progress and self.progress_dialog:
                self.progress_dialog.setLabelText("Updating table...")
                self.progress_dialog.setValue(95)
                QApplication.processEvents()  # Force UI update

            # Update table
            self._refresh_metadata_filter_lists(select_all=False)
            self._update_series_table()
            self.btn_add_store.setEnabled(True)

        except Exception as e:
            raise Exception(f"Failed to download GLD {gld_id}: {str(e)}")

    def _download_by_well_code(self, well_code):
        """Download data by well code."""
        try:
            # Try to find the well by code
            # This might require searching in BRO
            QMessageBox.information(
                self,
                "Info",
                f"Searching for well code '{well_code}'...\n"
                "This functionality requires additional BRO API calls.",
            )
            # TODO: Implement well code search
        except Exception as e:
            raise Exception(f"Failed to find well by code: {str(e)}")

    def _select_from_map(self):
        """Select area from map to download data."""
        if not HAS_BRODATA:
            QMessageBox.warning(self, "Error", "brodata package is not installed.")
            return

        if not self.iface or not self.iface.mapCanvas():
            QMessageBox.warning(self, "Error", "QGIS map canvas is not available.")
            return

        if self._map_select_tool is not None:
            self._stop_map_selection(reset_button=True)
            return

        canvas = self.iface.mapCanvas()
        self._previous_map_tool = canvas.mapTool()
        self._map_select_tool = BROMapExtentTool(
            canvas,
            on_finished=self._on_map_extent_selected,
            on_canceled=self._on_map_extent_canceled,
        )
        canvas.setMapTool(self._map_select_tool)

        self._restore_dialog_after_map_select = not self.isMinimized()
        self.showMinimized()

        self.btn_map_select.setText("Cancel Map Selection")
        self.btn_map_select.setToolTip("Drag a rectangle on the map to select BRO data")

        if self.iface and self.iface.messageBar():
            self.iface.messageBar().pushMessage(
                "BRO Import",
                "Draw a rectangle on the map to select BRO wells. Right-click to cancel.",
                level=0,
            )

    def _on_map_extent_canceled(self):
        self._stop_map_selection(reset_button=True)

    def _on_map_extent_selected(self, rect):
        self._stop_map_selection(reset_button=True)

        try:
            canvas = self.iface.mapCanvas()
            source_crs = canvas.mapSettings().destinationCrs()
            extent_rd = self._transform_extent_to_rd(rect, source_crs)
            print(extent_rd)
            self.iface.messageBar().pushMessage(
                "BRO Import",
                f"Selected extent (RD): {extent_rd}",
                level=0,
            )
            self._download_from_extent(extent_rd)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Map Selection Error",
                f"Failed to process selected map extent:\n{str(e)}",
            )

    def _stop_map_selection(self, reset_button=True):
        if not self.iface or not self.iface.mapCanvas():
            self._map_select_tool = None
            self._previous_map_tool = None
            return

        canvas = self.iface.mapCanvas()
        if (
            self._map_select_tool is not None
            and canvas.mapTool() == self._map_select_tool
        ):
            if self._previous_map_tool is not None:
                canvas.setMapTool(self._previous_map_tool)
            else:
                self._map_select_tool.deactivate()

        self._map_select_tool = None
        self._previous_map_tool = None

        if reset_button:
            self.btn_map_select.setText("Select Area on Map")
            self.btn_map_select.setToolTip("")

        if self._restore_dialog_after_map_select:
            self.showNormal()
            self.raise_()
            self.activateWindow()
        self._restore_dialog_after_map_select = False

    def _transform_extent_to_rd(self, extent, source_crs):
        target_crs = QgsCoordinateReferenceSystem("EPSG:28992")
        if source_crs.authid() == target_crs.authid():
            return [
                extent.xMinimum(),
                extent.xMaximum(),
                extent.yMinimum(),
                extent.yMaximum(),
            ]

        transformer = QgsCoordinateTransform(
            source_crs,
            target_crs,
            QgsProject.instance().transformContext(),
        )
        transformed = transformer.transformBoundingBox(extent)
        return [
            transformed.xMinimum(),
            transformed.xMaximum(),
            transformed.yMinimum(),
            transformed.yMaximum(),
        ]

    def _on_extent_download_progress(self, current, total):
        if not self.progress_dialog:
            return

        if self.progress_dialog.wasCanceled():
            raise self._ExtentDownloadCanceled()

        try:
            current = int(current)
            total = int(total)
        except (TypeError, ValueError):
            return

        base_progress = 0
        max_progress = 100

        if total > 0:
            ratio = max(0.0, min(1.0, float(current) / float(total)))
            progress = base_progress + int(ratio * (max_progress - base_progress))
            self.progress_dialog.setLabelText(
                f"Downloading observations {min(current, total)}/{total}..."
            )
            self.progress_dialog.setValue(progress)
            QApplication.processEvents()

    def _download_from_extent(self, extent):
        to_path = self.le_download_path.text().strip() or None
        use_csv = self.download_format == "csv"

        self.progress_dialog = QProgressDialog(
            "Downloading data from selected map extent...", "Cancel", 0, 100, self
        )
        self.progress_dialog.setWindowTitle("BRO Extent Download")
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setValue(5)
        self.progress_dialog.show()
        QApplication.processEvents()

        try:
            gdf = None

            if self.progress_dialog:
                self.progress_dialog.setLabelText(
                    "Querying wells in selected extent..."
                )
                self.progress_dialog.setValue(0)
                QApplication.processEvents()
                if self.progress_dialog.wasCanceled():
                    return

            if hasattr(brodata, "gm") and hasattr(brodata.gm, "get_data_in_extent"):
                gdf = brodata.gm.get_data_in_extent(
                    extent,
                    as_csv=use_csv,
                    to_path=to_path,
                    silent=True,
                    progress_callback=self._on_extent_download_progress,
                )
            elif hasattr(brodata, "gmw") and hasattr(brodata.gmw, "get_data_in_extent"):
                gdf = brodata.gmw.get_data_in_extent(
                    extent=extent,
                    kind="gld",
                    combine=True,
                    as_csv=use_csv,
                    to_path=to_path,
                    silent=True,
                    progress_callback=self._on_extent_download_progress,
                )
            else:
                raise Exception(
                    "brodata extent API is not available. Update brodata to a newer version."
                )

            if self.progress_dialog and self.progress_dialog.wasCanceled():
                return

            if gdf is None or len(gdf) == 0:
                QMessageBox.information(
                    self,
                    "No Data",
                    "No BRO monitoring tubes with observations were found in the selected area.",
                )
                return

            if self.progress_dialog:
                self.progress_dialog.setLabelText(
                    "Processing downloaded observations..."
                )
                self.progress_dialog.setValue(100)
                QApplication.processEvents()

            added = self._ingest_extent_gdf(gdf)

            if self.progress_dialog:
                self.progress_dialog.setLabelText("Updating table...")
                self.progress_dialog.setValue(95)
                QApplication.processEvents()

            self._refresh_metadata_filter_lists(select_all=False)
            self._update_series_table()
            self.btn_add_store.setEnabled(len(self.downloaded_data) > 0)

            QMessageBox.information(
                self,
                "Extent Download Complete",
                f"Downloaded {added} series from the selected map extent.",
            )
        except self._ExtentDownloadCanceled:
            return
        except Exception as e:
            raise Exception(f"Failed to download data for selected extent: {str(e)}")
        finally:
            if self.progress_dialog:
                self.progress_dialog.setValue(100)
                self.progress_dialog.close()
                self.progress_dialog = None

    def _ingest_extent_gdf(self, gdf):
        added = 0

        for idx, row in gdf.iterrows():
            observation = row.get("observation")
            if observation is None:
                continue
            if hasattr(observation, "empty") and observation.empty:
                continue

            gmw_id = row.get("groundwaterMonitoringWell")
            tube_number = row.get("tubeNumber")
            gld_ids = row.get("groundwaterLevelDossier")

            if isinstance(gld_ids, (list, tuple)) and len(gld_ids) > 0:
                base_name = str(gld_ids[0])
            elif gmw_id is not None and tube_number is not None:
                base_name = f"{gmw_id}_{tube_number}"
            elif gmw_id is not None:
                base_name = str(gmw_id)
            else:
                base_name = str(idx)

            series_name = self._unique_series_name(base_name)
            self.downloaded_data[series_name] = observation

            metadata = {}
            if gmw_id is not None:
                metadata["GMW"] = gmw_id
            if tube_number is not None:
                metadata["tubeNumber"] = tube_number

            if isinstance(gld_ids, (list, tuple)) and len(gld_ids) > 0:
                metadata["groundwaterLevelDossier"] = list(gld_ids)
                metadata["bro_id"] = str(gld_ids[0])

            geometry = row.get("geometry")
            if (
                geometry is not None
                and hasattr(geometry, "x")
                and hasattr(geometry, "y")
            ):
                try:
                    metadata["x"] = float(geometry.x)
                    metadata["y"] = float(geometry.y)
                except Exception:
                    pass
            else:
                x_val = row.get("x")
                y_val = row.get("y")
                if x_val is not None and y_val is not None:
                    metadata["x"] = x_val
                    metadata["y"] = y_val

            self.series_metadata[series_name] = metadata
            added += 1

        return added

    def _unique_series_name(self, base_name):
        name = str(base_name)
        if name not in self.downloaded_data:
            return name

        i = 2
        while f"{name}_{i}" in self.downloaded_data:
            i += 1
        return f"{name}_{i}"

    def closeEvent(self, event):
        self._stop_map_selection(reset_button=False)
        super(BROImportDialog, self).closeEvent(event)

    def _update_series_table(self):
        """Update the series table with downloaded data."""
        self.table_series.setRowCount(0)

        for i, (name, df) in enumerate(self.downloaded_data.items()):
            self.table_series.insertRow(i)

            # Select checkbox
            chk = QCheckBox()
            chk.setChecked(True)
            self.table_series.setCellWidget(i, 0, chk)

            # Name
            self.table_series.setItem(i, 1, QTableWidgetItem(name))

            # Location
            metadata = self.series_metadata.get(name, {})
            x = metadata.get("x", "")
            y = metadata.get("y", "")
            location = f"{x}, {y}" if x and y else ""
            self.table_series.setItem(i, 2, QTableWidgetItem(location))

            # Count
            count = len(df)
            self.table_series.setItem(i, 3, QTableWidgetItem(str(count)))

            # Start and End dates
            if isinstance(df.index, pd.DatetimeIndex):
                start = df.index[0].strftime("%Y-%m-%d") if len(df) > 0 else ""
                end = df.index[-1].strftime("%Y-%m-%d") if len(df) > 0 else ""
            else:
                start = str(df.index[0]) if len(df) > 0 else ""
                end = str(df.index[-1]) if len(df) > 0 else ""

            self.table_series.setItem(i, 4, QTableWidgetItem(start))
            self.table_series.setItem(i, 5, QTableWidgetItem(end))

    def _on_series_selected(self):
        """Handle series selection to update plot."""
        if not HAS_PYQTGRAPH:
            return

        selected_items = self.table_series.selectedItems()
        if not selected_items:
            return

        # Get the selected series name
        row = selected_items[0].row()
        name_item = self.table_series.item(row, 1)
        if not name_item:
            return

        series_name = name_item.text()
        if series_name not in self.downloaded_data:
            return

        if self.chk_only_this_series.isChecked():
            filter_selection = self._series_filter_selection.get(series_name)
            if filter_selection is None:
                filter_selection = self._global_filter_selection
                self._series_filter_selection[series_name] = filter_selection.copy()
            self._apply_filter_selection_to_lists(
                filter_selection,
                select_all_if_empty=True,
            )
        else:
            self._apply_filter_selection_to_lists(
                self._global_filter_selection,
                select_all_if_empty=True,
            )

        # Plot the series
        self._plot_series(series_name)

    def _on_metadata_changed(self):
        """Handle metadata selection change to update plot."""
        current_selection = self._get_filter_selection_from_lists()

        series_name = self._get_current_series_name()
        if self.chk_only_this_series.isChecked() and series_name:
            self._series_filter_selection[series_name] = current_selection
        else:
            self._global_filter_selection = current_selection

        # Re-plot the currently selected series with new filters
        selected_items = self.table_series.selectedItems()
        if selected_items:
            row = selected_items[0].row()
            name_item = self.table_series.item(row, 1)
            if name_item:
                series_name = name_item.text()
                if series_name in self.downloaded_data:
                    self._plot_series(series_name)

    def _plot_series(self, series_name):
        """Plot a series in the preview widget."""
        if not HAS_PYQTGRAPH:
            return

        df = self.downloaded_data[series_name]
        self.plot_widget.clear()

        try:
            # Get selected filter values
            selected_status = [item.text() for item in self.list_status.selectedItems()]
            selected_qualifier = [
                item.text() for item in self.list_qualifier.selectedItems()
            ]
            selected_obs_type = [
                item.text() for item in self.list_obs_type.selectedItems()
            ]

            # Filter data if it has the relevant columns
            filtered_df = df.copy()
            if "status" in df.columns and selected_status:
                filtered_df = filtered_df[filtered_df["status"].isin(selected_status)]
            if "qualifier" in df.columns and selected_qualifier:
                filtered_df = filtered_df[
                    filtered_df["qualifier"].isin(selected_qualifier)
                ]
            if "observation_type" in df.columns and selected_obs_type:
                filtered_df = filtered_df[
                    filtered_df["observation_type"].isin(selected_obs_type)
                ]

            if len(filtered_df) == 0:
                self.plot_widget.setTitle(
                    f"Preview: {series_name} (no data)", color="k"
                )
                return

            def _get_xy(dataframe):
                if isinstance(dataframe.index, pd.DatetimeIndex):
                    x_values = dataframe.index.astype(np.int64) / 10**9
                else:
                    x_values = np.arange(len(dataframe))

                if isinstance(dataframe, pd.Series):
                    y_values = dataframe.values
                elif "value" in dataframe.columns:
                    y_values = dataframe["value"].values
                elif "stand" in dataframe.columns:
                    y_values = dataframe["stand"].values
                else:
                    y_values = dataframe.iloc[:, 0].values
                return x_values, y_values

            plot_item = self.plot_widget.getPlotItem()
            if plot_item.legend is not None:
                plot_item.legend.scene().removeItem(plot_item.legend)
                plot_item.legend = None
            self.plot_widget.addLegend(labelTextColor="k")

            combo_columns = [
                column
                for column in ["status", "qualifier", "observation_type"]
                if not isinstance(filtered_df, pd.Series)
                and column in filtered_df.columns
            ]

            if combo_columns:
                grouped = filtered_df.groupby(combo_columns, dropna=False, sort=True)
                ngroups = grouped.ngroups

                for idx, (combo, group) in enumerate(grouped):
                    group = group.sort_index()
                    x, y = _get_xy(group)

                    if not isinstance(combo, tuple):
                        combo = (combo,)
                    label_parts = []
                    for col_name, value in zip(combo_columns, combo):
                        value_text = "<NA>" if pd.isna(value) else str(value)
                        label_parts.append(f"{col_name}={value_text}")
                    label = " | ".join(label_parts)

                    color = pg.intColor(idx, hues=max(ngroups, 1))
                    self.plot_widget.plot(
                        x,
                        y,
                        pen=pg.mkPen(color=color, width=2),
                        name=label,
                    )
            else:
                x, y = _get_xy(filtered_df)
                color = pg.intColor(0, hues=1)
                self.plot_widget.plot(
                    x,
                    y,
                    pen=pg.mkPen(color=color, width=2),
                    name=series_name,
                )

            # Update title with filter info
            filter_info = ""
            if len(filtered_df) < len(df):
                filter_info = f" (Filtered: {len(filtered_df)}/{len(df)} points)"
            self.plot_widget.setTitle(f"Preview: {series_name}{filter_info}", color="k")

        except Exception as e:
            print(f"Error plotting series: {e}")

    def _add_to_store(self):
        """Add selected series to the pastastore."""
        # Get selected series
        selected_series = {}

        for i in range(self.table_series.rowCount()):
            chk = self.table_series.cellWidget(i, 0)
            if chk and chk.isChecked():
                name_item = self.table_series.item(i, 1)
                if name_item:
                    series_name = name_item.text()
                    if series_name in self.downloaded_data:
                        df = self.downloaded_data[series_name]
                        metadata = self.series_metadata.get(series_name, {})
                        metadata = metadata.copy()

                        filter_selection = self._get_filters_for_series(series_name)
                        metadata["status"] = filter_selection.get("status", [])
                        metadata["qualifier"] = filter_selection.get("qualifier", [])
                        metadata["observation_type"] = filter_selection.get(
                            "observation_type", []
                        )

                        selected_series[series_name] = {
                            "data": df,
                            "metadata": metadata,
                        }

        if not selected_series:
            QMessageBox.warning(self, "Warning", "No series selected.")
            return

        # Emit signal with selected series
        self.series_to_add.emit(selected_series)

        QMessageBox.information(
            self,
            "Success",
            f"Added {len(selected_series)} series to the store.",
        )

        self.accept()

    def get_selected_series(self):
        """Return the selected series data."""
        selected_series = {}

        for i in range(self.table_series.rowCount()):
            chk = self.table_series.cellWidget(i, 0)
            if chk and chk.isChecked():
                name_item = self.table_series.item(i, 1)
                if name_item:
                    series_name = name_item.text()
                    if series_name in self.downloaded_data:
                        df = self.downloaded_data[series_name]
                        metadata = self.series_metadata.get(series_name, {})
                        metadata = metadata.copy()

                        filter_selection = self._get_filters_for_series(series_name)
                        metadata["status"] = filter_selection.get("status", [])
                        metadata["qualifier"] = filter_selection.get("qualifier", [])
                        metadata["observation_type"] = filter_selection.get(
                            "observation_type", []
                        )

                        selected_series[series_name] = {
                            "data": df,
                            "metadata": metadata,
                        }

        return selected_series
