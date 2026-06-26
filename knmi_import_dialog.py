from qgis.PyQt.QtCore import Qt, QItemSelectionModel
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QComboBox,
    QSizePolicy,
    QDialogButtonBox,
    QMessageBox,
    QDialog,
    QMenu,
)

# -*- coding: utf-8 -*-

from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QGroupBox,
    QCheckBox,
    QDateTimeEdit,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QProgressDialog,
    QApplication,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
import pandas as pd
import numpy as np

from .i18n_helper import tr as _i18n_tr


def _tr(message):
    return _i18n_tr(message)


try:
    import pyqtgraph as pg
    from pyqtgraph import DateAxisItem

    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False

try:
    import hydropandas as hpd

    HAS_HYDROPANDAS = True
except ImportError:
    HAS_HYDROPANDAS = False


class KNMIImportDialog(QDialog):
    """Dialog for importing KNMI precipitation/evaporation stresses."""

    class _KNMIDownloadCanceled(Exception):
        pass

    stresses_to_add = pyqtSignal(dict)  # {name: {series, metadata}}

    def __init__(self, store, x_col="x", y_col="y", parent=None, iface=None):
        super(KNMIImportDialog, self).__init__(parent)
        self.iface = iface
        self.store = store
        self.x_col = x_col
        self.y_col = y_col
        self.downloaded_stresses = {}  # {name: {series, metadata}}
        self._knmi_progress_dialog = None
        self._knmi_progress_calls = 0
        self._knmi_progress_expected = 0

        self.setWindowTitle(_tr("Import from KNMI"))
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
        self.resize(1000, 700)

        if not HAS_HYDROPANDAS:
            QMessageBox.warning(
                self,
                "Missing Dependency",
                "The 'hydropandas' package is not installed.\n\n"
                "Please install/bundle it before using KNMI import.",
            )

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        self.lbl_info = QLabel(
            _tr("Download precipitation (RH) and evaporation (EV24) near oseries locations.")
        )
        self.lbl_info.setWordWrap(True)
        layout.addWidget(self.lbl_info)

        info_row = QHBoxLayout()
        self.lbl_locations = QLabel(_tr("Locations: -"))
        self.lbl_period = QLabel(_tr("Period: -"))
        info_row.addWidget(self.lbl_locations)
        info_row.addStretch()
        info_row.addWidget(self.lbl_period)
        layout.addLayout(info_row)

        options_group = QGroupBox(_tr("Download Options"))
        options_layout = QVBoxLayout()

        freq_row = QHBoxLayout()
        freq_row.addWidget(QLabel(_tr("Frequency:")))
        self.combo_frequency = QComboBox()
        self.combo_frequency.addItem(_tr("Daily"), "daily")
        self.combo_frequency.addItem(_tr("Hourly"), "hourly")
        self.combo_frequency.currentIndexChanged.connect(self._on_frequency_changed)
        freq_row.addWidget(self.combo_frequency)
        freq_row.addStretch()
        options_layout.addLayout(freq_row)

        vars_row = QHBoxLayout()
        vars_row.addWidget(QLabel(_tr("KNMI Variables:")))
        self.chk_var_rh = QCheckBox("RH")
        self.chk_var_rd = QCheckBox("RD")
        self.chk_var_ev24 = QCheckBox("EV24")
        self.chk_var_rh.setChecked(True)
        self.chk_var_ev24.setChecked(True)
        vars_row.addWidget(self.chk_var_rh)
        vars_row.addWidget(self.chk_var_rd)
        vars_row.addWidget(self.chk_var_ev24)
        vars_row.addStretch()
        options_layout.addLayout(vars_row)

        fill_row = QHBoxLayout()
        self.chk_fill_missing = QCheckBox(_tr("Fill Missing Observations"))
        self.chk_fill_missing.setChecked(True)
        fill_row.addWidget(self.chk_fill_missing)
        fill_row.addStretch()
        options_layout.addLayout(fill_row)

        period_row = QHBoxLayout()
        period_row.addWidget(QLabel(_tr("Minimum Time:")))
        self.dt_start = QDateTimeEdit()
        self.dt_start.setCalendarPopup(True)
        self.dt_start.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.dt_start.dateTimeChanged.connect(self._on_time_inputs_changed)
        period_row.addWidget(self.dt_start)
        period_row.addWidget(QLabel(_tr("Maximum Time:")))
        self.dt_end = QDateTimeEdit()
        self.dt_end.setCalendarPopup(True)
        self.dt_end.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.dt_end.dateTimeChanged.connect(self._on_time_inputs_changed)
        period_row.addWidget(self.dt_end)
        options_layout.addLayout(period_row)

        options_group.setLayout(options_layout)
        layout.addWidget(options_group)

        content_row = QHBoxLayout()

        self.table_stresses = QTableWidget()
        self.table_stresses.setColumnCount(7)
        self.table_stresses.setHorizontalHeaderLabels(
            ["Select", "Name", "Kind", "Station", "Count", "Start", "End"]
        )
        self.table_stresses.verticalHeader().setVisible(False)
        self.table_stresses.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.table_stresses.horizontalHeader().setStretchLastSection(True)
        self.table_stresses.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_stresses.itemSelectionChanged.connect(self._on_series_selected)
        content_row.addWidget(self.table_stresses, 1)

        if HAS_PYQTGRAPH:
            preview_group = QGroupBox("Preview")
            preview_layout = QVBoxLayout()
            self.plot_widget = pg.PlotWidget(axisItems={"bottom": DateAxisItem()})
            self.plot_widget.setBackground("w")
            self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
            for axis in ["bottom", "left"]:
                ax = self.plot_widget.getAxis(axis)
                ax.setPen("k")
                ax.setTextPen("k")
            self.plot_widget.setLabel("left", "Value")
            self.plot_widget.setLabel("bottom", "Time")
            preview_layout.addWidget(self.plot_widget)
            preview_group.setLayout(preview_layout)
            content_row.addWidget(preview_group, 1)

        layout.addLayout(content_row)

        button_layout = QHBoxLayout()
        self.btn_download = QPushButton(_tr("Download"))
        self.btn_download.clicked.connect(self.download_knmi)
        button_layout.addWidget(self.btn_download)

        self.btn_add_store = QPushButton(_tr("Add to Store"))
        self.btn_add_store.clicked.connect(self.add_to_store)
        self.btn_add_store.setEnabled(False)
        button_layout.addWidget(self.btn_add_store)

        button_layout.addStretch()

        self.btn_close = QPushButton(_tr("Close"))
        self.btn_close.clicked.connect(self.reject)
        button_layout.addWidget(self.btn_close)

        layout.addLayout(button_layout)
        self.setLayout(layout)

        self._initialize_defaults()

    def _get_oseries_locations(self):
        if not hasattr(self.store, "oseries") or len(self.store.oseries.index) == 0:
            raise ValueError("No oseries available.")

        oseries_meta = self.store.oseries.copy()
        if self.x_col not in oseries_meta.columns or self.y_col not in oseries_meta.columns:
            raise ValueError(
                "Could not find coordinate columns "
                f"'{self.x_col}' and '{self.y_col}' in oseries metadata."
            )

        locations = oseries_meta[[self.x_col, self.y_col]].dropna()
        if locations.empty:
            raise ValueError("No valid oseries coordinates available.")

        return locations

    def _get_oseries_timerange(self):
        try:
            if hasattr(self.store, "get_tmin_tmax"):
                tmintmax = self.store.get_tmin_tmax("oseries")
                tmin = pd.to_datetime(tmintmax.tmin.min())
                tmax = pd.to_datetime(tmintmax.tmax.max())
                if pd.notna(tmin) and pd.notna(tmax):
                    return tmin, tmax
        except Exception:
            pass

        tmin = None
        tmax = None
        for name in getattr(self.store, "oseries_names", []):
            try:
                s = self.store.get_oseries(name)
                if isinstance(s, pd.DataFrame):
                    s = s.iloc[:, 0]
                s = s.dropna()
                if s.empty:
                    continue
                smin = pd.to_datetime(s.index.min())
                smax = pd.to_datetime(s.index.max())
                tmin = smin if tmin is None else min(tmin, smin)
                tmax = smax if tmax is None else max(tmax, smax)
            except Exception:
                continue

        if tmin is None or tmax is None:
            raise ValueError("Could not determine oseries date range.")
        return tmin, tmax

    def _initialize_defaults(self):
        try:
            locations = self._get_oseries_locations()
            self.lbl_locations.setText(f"Locations: {len(locations)}")
        except Exception:
            self.lbl_locations.setText("Locations: 0")

        try:
            first_obs, last_obs = self._get_oseries_timerange()
            min_with_warmup = first_obs - pd.DateOffset(years=10)
        except Exception:
            last_obs = pd.Timestamp.now().floor("D")
            min_with_warmup = last_obs - pd.DateOffset(years=10)

        self.dt_start.setDateTime(min_with_warmup.to_pydatetime())
        self.dt_end.setDateTime(last_obs.to_pydatetime())
        self._on_frequency_changed()
        self._on_time_inputs_changed()

    def _on_time_inputs_changed(self):
        tmin = self.dt_start.dateTime().toPyDateTime()
        tmax = self.dt_end.dateTime().toPyDateTime()
        self.lbl_period.setText(
            f"Period: {pd.Timestamp(tmin).date()} to {pd.Timestamp(tmax).date()}"
        )

    def _on_frequency_changed(self):
        interval = self.combo_frequency.currentData()
        if interval == "hourly":
            # Hourly KNMI import only supports RH.
            self.chk_var_rh.setChecked(True)
            self.chk_var_rh.setEnabled(True)
            self.chk_var_rd.setChecked(False)
            self.chk_var_rd.setEnabled(False)
            self.chk_var_ev24.setChecked(False)
            self.chk_var_ev24.setEnabled(False)
        else:
            self.chk_var_rh.setEnabled(True)
            self.chk_var_rd.setEnabled(True)
            self.chk_var_ev24.setEnabled(True)
            if not any(
                [
                    self.chk_var_rh.isChecked(),
                    self.chk_var_rd.isChecked(),
                    self.chk_var_ev24.isChecked(),
                ]
            ):
                self.chk_var_rh.setChecked(True)
                self.chk_var_ev24.setChecked(True)

    def _selected_variables(self):
        vars_selected = []
        if self.chk_var_rh.isChecked():
            vars_selected.append("RH")
        if self.chk_var_rd.isChecked():
            vars_selected.append("RD")
        if self.chk_var_ev24.isChecked():
            vars_selected.append("EV24")
        return vars_selected

    def _obs_to_series(self, obs, preferred_col):
        if isinstance(obs, pd.Series):
            series = obs
        elif isinstance(obs, pd.DataFrame):
            if preferred_col in obs.columns:
                series = obs[preferred_col]
            else:
                numeric_cols = obs.select_dtypes(include=[np.number]).columns
                if len(numeric_cols) > 0:
                    series = obs[numeric_cols[0]]
                else:
                    series = obs.iloc[:, 0]
        else:
            series = pd.Series(obs)

        if not isinstance(series.index, pd.DatetimeIndex):
            series.index = pd.to_datetime(series.index, errors="coerce")
        series = pd.to_numeric(series, errors="coerce").dropna()
        series = series[~series.index.isna()].sort_index()
        return series

    def _on_series_selected(self):
        if not HAS_PYQTGRAPH:
            return
        selected_items = self.table_stresses.selectedItems()
        if not selected_items:
            self.plot_widget.clear()
            self.plot_widget.setTitle("Preview", color="k")
            return

        row = selected_items[0].row()
        name_item = self.table_stresses.item(row, 1)
        if not name_item:
            return
        self._plot_series(name_item.text())

    def _plot_series(self, series_name):
        if not HAS_PYQTGRAPH:
            return
        self.plot_widget.clear()

        data = self.downloaded_stresses.get(series_name)
        if not data:
            self.plot_widget.setTitle(f"Preview: {series_name} (missing)", color="k")
            return

        series = data.get("series")
        if series is None or len(series) == 0:
            self.plot_widget.setTitle(f"Preview: {series_name} (no data)", color="k")
            return

        s = series.dropna()
        if s.empty:
            self.plot_widget.setTitle(f"Preview: {series_name} (no data)", color="k")
            return

        x = s.index
        if pd.api.types.is_datetime64_any_dtype(x):
            x = x.astype('datetime64[s]').astype(np.int64)
        y = s.values

        self.plot_widget.setTitle(f"Preview: {series_name}", color="k")
        self.plot_widget.plot(
            x,
            y,
            pen=pg.mkPen("#1f77b4", width=2),
            symbol="o" if len(s) <= 5000 else None,
            symbolSize=4,
            symbolBrush="#1f77b4",
            connect="finite",
        )
        self.plot_widget.enableAutoRange(axis=self.plot_widget.plotItem.vb.XYAxes)

    def _on_knmi_download_progress(self, current, total):
        if not self._knmi_progress_dialog:
            return

        if self._knmi_progress_dialog.wasCanceled():
            raise self._KNMIDownloadCanceled()

        try:
            current = int(current)
            total = int(total)
        except (TypeError, ValueError):
            return

        self._knmi_progress_calls += 1
        if self._knmi_progress_expected > 0:
            ratio = max(
                0.0,
                min(1.0, float(self._knmi_progress_calls) / self._knmi_progress_expected),
            )
        else:
            ratio = max(0.0, min(1.0, float(current + 1) / max(total, 1)))

        progress = 5 + int(ratio * 85)
        self._knmi_progress_dialog.setLabelText(
            f"Downloading KNMI observations {min(current + 1, total)}/{total}..."
        )
        self._knmi_progress_dialog.setValue(progress)
        QApplication.processEvents()

    def download_knmi(self):
        if not HAS_HYDROPANDAS:
            QMessageBox.warning(
                self,
                "Missing Dependency",
                "hydropandas is not available.",
            )
            return

        try:
            locations = self._get_oseries_locations()
        except Exception as e:
            QMessageBox.warning(self, "Cannot Download", str(e))
            return

        interval = self.combo_frequency.currentData()
        fill_missing_obs = self.chk_fill_missing.isChecked()
        selected_vars = self._selected_variables()
        if not selected_vars:
            QMessageBox.warning(
                self,
                "No Variables",
                "Select at least one KNMI variable to download.",
            )
            return

        tmin = pd.Timestamp(self.dt_start.dateTime().toPyDateTime())
        tmax = pd.Timestamp(self.dt_end.dateTime().toPyDateTime())
        if tmax <= tmin:
            QMessageBox.warning(
                self,
                "Invalid Period",
                "Maximum time must be later than minimum time.",
            )
            return

        self.lbl_locations.setText(f"Locations: {len(locations)}")
        self.lbl_period.setText(f"Period: {tmin.date()} to {tmax.date()}")

        reply = QMessageBox.question(
            self,
            "Import KNMI Stresses",
            (
                f"Download {', '.join(selected_vars)} ({interval}) for "
                f"{len(locations)} oseries location(s) from {tmin.date()} to {tmax.date()}?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._knmi_progress_calls = 0
        self._knmi_progress_expected = max(1, len(locations) * len(selected_vars))

        self._knmi_progress_dialog = QProgressDialog(
            "Downloading KNMI stresses...", "Cancel", 0, 100, self
        )
        self._knmi_progress_dialog.setWindowTitle("KNMI Download")
        self._knmi_progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._knmi_progress_dialog.setMinimumDuration(0)
        self._knmi_progress_dialog.setValue(0)
        self._knmi_progress_dialog.show()
        QApplication.processEvents()

        self.downloaded_stresses = {}
        failed = []
        try:
            knmi_oc = hpd.read_knmi(
                locations=locations,
                meteo_vars=tuple(selected_vars),
                starts=tmin,
                ends=tmax,
                fill_missing_obs=fill_missing_obs,
                interval=interval,
                raise_exceptions=False,
                progress_callback=self._on_knmi_download_progress,
            )

            if self._knmi_progress_dialog and self._knmi_progress_dialog.wasCanceled():
                return

            if self._knmi_progress_dialog:
                self._knmi_progress_dialog.setLabelText("Processing downloaded observations...")
                self._knmi_progress_dialog.setValue(92)
                QApplication.processEvents()

            if knmi_oc is None or knmi_oc.empty:
                failed.append("No KNMI observations returned.")
            else:
                for obs_name, row in knmi_oc.iterrows():
                    try:
                        obs = row.get("obs", None)
                        if obs is None:
                            continue

                        meteo_var = row.get("meteo_var", None) or getattr(
                            obs, "meteo_var", None
                        )
                        if meteo_var is None:
                            meteo_var = selected_vars[0]

                        series = self._obs_to_series(obs, meteo_var)
                        if series.empty:
                            continue

                        kind = "evap" if meteo_var == "EV24" else "prec"
                        stress_name = str(obs_name)
                        if interval == "hourly" and not stress_name.endswith("_hourly"):
                            stress_name = f"{stress_name}_hourly"

                        base_name = stress_name
                        i = 1
                        while stress_name in self.downloaded_stresses:
                            i += 1
                            stress_name = f"{base_name}_{i}"

                        station_x = row.get("x", getattr(obs, "x", np.nan))
                        station_y = row.get("y", getattr(obs, "y", np.nan))
                        metadata = {
                            "x": station_x,
                            "y": station_y,
                            "source": "KNMI",
                            "kind": kind,
                            "meteo_var": meteo_var,
                            "interval": interval,
                            "fill_missing_obs": fill_missing_obs,
                            "station": row.get("station", getattr(obs, "station", None)),
                        }
                        self.downloaded_stresses[stress_name] = {
                            "series": series,
                            "metadata": metadata,
                        }
                    except Exception as e:
                        failed.append(f"{obs_name}: {str(e)}")

            self._populate_table()
            self.btn_add_store.setEnabled(len(self.downloaded_stresses) > 0)

            if self._knmi_progress_dialog:
                self._knmi_progress_dialog.setLabelText("Updating table...")
                self._knmi_progress_dialog.setValue(95)
                QApplication.processEvents()

            if self.table_stresses.rowCount() > 0:
                self.table_stresses.selectRow(0)

            if len(self.downloaded_stresses) == 0:
                QMessageBox.information(
                    self,
                    "KNMI Import",
                    "No KNMI stress series were downloaded.",
                )
            elif failed:
                QMessageBox.information(
                    self,
                    "KNMI Import",
                    f"Downloaded {len(self.downloaded_stresses)} stress series. "
                    f"Failed for {len(failed)} oseries.",
                )
        except self._KNMIDownloadCanceled:
            return
        finally:
            try:
                if self._knmi_progress_dialog:
                    self._knmi_progress_dialog.setValue(100)
                    self._knmi_progress_dialog.close()
            except Exception:
                pass
            self._knmi_progress_dialog = None
            self._knmi_progress_calls = 0
            self._knmi_progress_expected = 0

    def _populate_table(self):
        self.table_stresses.setRowCount(0)
        for i, (name, item) in enumerate(self.downloaded_stresses.items()):
            series = item["series"]
            meta = item["metadata"]

            self.table_stresses.insertRow(i)

            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check_item.setCheckState(Qt.CheckState.Checked)
            self.table_stresses.setItem(i, 0, check_item)

            self.table_stresses.setItem(i, 1, QTableWidgetItem(name))
            self.table_stresses.setItem(i, 2, QTableWidgetItem(str(meta.get("kind", ""))))
            self.table_stresses.setItem(i, 3, QTableWidgetItem(str(meta.get("station", ""))))
            self.table_stresses.setItem(i, 4, QTableWidgetItem(str(len(series))))
            self.table_stresses.setItem(i, 5, QTableWidgetItem(str(series.index.min())))
            self.table_stresses.setItem(i, 6, QTableWidgetItem(str(series.index.max())))

    def add_to_store(self):
        selected = {}
        for row in range(self.table_stresses.rowCount()):
            check_item = self.table_stresses.item(row, 0)
            name_item = self.table_stresses.item(row, 1)
            if check_item is None or name_item is None:
                continue
            if check_item.checkState() != Qt.CheckState.Checked:
                continue

            name = name_item.text()
            if name in self.downloaded_stresses:
                selected[name] = self.downloaded_stresses[name]

        if not selected:
            QMessageBox.warning(self, "No Selection", "Select at least one stress series.")
            return

        self.stresses_to_add.emit(selected)
        self.accept()
