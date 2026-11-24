# -*- coding: utf-8 -*-
# Copyright © 2024-2026 Pastastore Viewer Contributors. All rights reserved.
# This software is proprietary. See LICENSE.md for details.
"""Ensemble prediction and forecasting dialog powered by `pastas.forecast`."""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pastas as ps
import pyqtgraph as pg
from pyqtgraph import DateAxisItem
from qgis.PyQt.QtCore import QDate, Qt, QThread, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from .i18n_helper import tr as _i18n_tr
    from .model_analysis import (
        ForecastResult,
        align_historical_ensembles,
        build_synthetic_forecast,
        can_post_process_forecast,
        get_model_common_stress_range,
        get_model_freq,
        get_stressmodel_inputs,
        has_parameter_covariance,
        is_model_solved,
        load_ensemble_csv,
        run_ensemble_forecast,
    )
    from .plot_toolbar import PlotNavigationWidget, create_fill_between_item
except (ImportError, ValueError):
    from i18n_helper import tr as _i18n_tr
    from model_analysis import (
        ForecastResult,
        align_historical_ensembles,
        build_synthetic_forecast,
        can_post_process_forecast,
        get_model_common_stress_range,
        get_model_freq,
        get_stressmodel_inputs,
        has_parameter_covariance,
        is_model_solved,
        load_ensemble_csv,
        run_ensemble_forecast,
    )
    from plot_toolbar import PlotNavigationWidget, create_fill_between_item


def _tr(message: str) -> str:
    return _i18n_tr(message)


def _ts_to_qdate(ts: pd.Timestamp | None) -> QDate:
    if ts is None or pd.isna(ts):
        return QDate.currentDate()
    d = pd.Timestamp(ts).date()
    return QDate(d.year, d.month, d.day)


def _qdate_to_ts(qd: QDate) -> pd.Timestamp:
    return pd.Timestamp(qd.toString("yyyy-MM-dd"))


class _ForecastWorker(QThread):
    """Background worker thread running `run_ensemble_forecast` without blocking QGIS."""

    progress = pyqtSignal(int, str)
    finished_result = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        ml: ps.Model,
        forecasts_dict: dict,
        tmin: pd.Timestamp,
        tmax: pd.Timestamp,
        n_param_samples: int,
        post_process: bool,
        parent=None,
    ):
        super().__init__(parent)
        self.ml = ml
        self.forecasts_dict = forecasts_dict
        self.tmin = tmin
        self.tmax = tmax
        self.n_param_samples = n_param_samples
        self.post_process = post_process

    def run(self):
        try:
            res = run_ensemble_forecast(
                self.ml,
                self.forecasts_dict,
                tmin=self.tmin,
                tmax=self.tmax,
                n_param_samples=self.n_param_samples,
                post_process=self.post_process,
                progress_callback=lambda pct, msg: self.progress.emit(pct, msg),
            )
            self.finished_result.emit(res)
        except Exception as exc:
            self.failed.emit(str(exc))


class ModelForecastDialog(QDialog):
    """Interactive dialog for ensemble groundwater predictions via `pastas.forecast`."""

    def __init__(self, ml: ps.Model, store=None, parent=None):
        super().__init__(parent)
        self.ml = ml
        self.store = store
        self.setWindowTitle(_tr("Forecast / Predictions: {0}").format(ml.name))
        self.resize(1340, 880)

        self.stress_inputs = get_stressmodel_inputs(ml)
        self.forecast_result: ForecastResult | None = None
        self._worker: _ForecastWorker | None = None
        self._stress_rows: list[dict] = []

        self._init_ui()
        self._plot_historical_only()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(6, 6, 6, 6)
        root_layout.setSpacing(6)

        if not is_model_solved(self.ml):
            banner = QLabel(
                _tr(
                    "Warning: This model is not solved yet. Solve the model before running forecasts."
                )
            )
            banner.setStyleSheet(
                "background: #f8d7da; color: #842029; padding: 6px; border: 1px solid #f5c2c7;"
            )
            root_layout.addWidget(banner)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter, 1)

        # ---- Left pane: Forecast Configuration ----
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(8)

        # 1. Horizon
        grp_horizon = QGroupBox(_tr("Forecast Horizon"))
        form_h = QFormLayout(grp_horizon)

        cal_tmax = self.ml.settings.get("tmax")
        _, stress_tmax = get_model_common_stress_range(self.ml)
        default_start = None
        if cal_tmax is not None:
            default_start = pd.Timestamp(cal_tmax) + pd.Timedelta(days=1)
        elif stress_tmax is not None:
            default_start = pd.Timestamp(stress_tmax) + pd.Timedelta(days=1)
        else:
            default_start = pd.Timestamp.today().normalize()

        self.de_start = QDateEdit()
        self.de_start.setCalendarPopup(True)
        self.de_start.setDisplayFormat("yyyy-MM-dd")
        self.de_start.setMinimumDate(QDate(1900, 1, 1))
        self.de_start.setMaximumDate(QDate(2150, 12, 31))
        self.de_start.setDate(_ts_to_qdate(default_start))

        self.spn_horizon_days = QSpinBox()
        self.spn_horizon_days.setRange(1, 3650)
        self.spn_horizon_days.setValue(30)
        self.spn_horizon_days.setSuffix(_tr(" days"))

        horizon_presets = QHBoxLayout()
        for days in (14, 30, 90, 180, 365):
            btn = QPushButton(f"{days}d")
            btn.setMaximumWidth(48)
            btn.clicked.connect(lambda _chk=False, d=days: self.spn_horizon_days.setValue(d))
            horizon_presets.addWidget(btn)
        horizon_presets.addStretch()

        self.spn_lookback = QSpinBox()
        self.spn_lookback.setRange(30, 7300)
        self.spn_lookback.setValue(365)
        self.spn_lookback.setSuffix(_tr(" days"))
        self.spn_lookback.valueChanged.connect(self._refresh_plots)

        form_h.addRow(_tr("Start Date:"), self.de_start)
        form_h.addRow(_tr("Horizon:"), self.spn_horizon_days)
        form_h.addRow(_tr("Quick:"), horizon_presets)
        form_h.addRow(_tr("Plot Lookback:"), self.spn_lookback)
        left_layout.addWidget(grp_horizon)

        # 2. Forecast Stress Inputs
        grp_inputs = QGroupBox(_tr("Forecast Stress Inputs"))
        inp_layout = QVBoxLayout(grp_inputs)

        self.cbo_input_mode = QComboBox()
        self.cbo_input_mode.addItem(
            _tr("Historical Analogues (Climatology Ensemble)"), "historical"
        )
        self.cbo_input_mode.addItem(
            _tr("External Ensemble Files (CSV / Parquet / Excel)"), "csv"
        )
        self.cbo_input_mode.addItem(
            _tr("Synthetic / Deterministic Stress"), "synthetic"
        )
        self.cbo_input_mode.currentIndexChanged.connect(self._on_input_mode_changed)
        inp_layout.addWidget(self.cbo_input_mode)

        self.lbl_mode_hint = QLabel("")
        self.lbl_mode_hint.setWordWrap(True)
        self.lbl_mode_hint.setStyleSheet("color: #555; font-size: 11px;")
        inp_layout.addWidget(self.lbl_mode_hint)

        # Per-stress configuration widgets (shown for CSV & Synthetic modes)
        self.per_stress_container = QWidget()
        per_stress_layout = QVBoxLayout(self.per_stress_container)
        per_stress_layout.setContentsMargins(0, 4, 0, 0)
        per_stress_layout.setSpacing(6)

        for inp in self.stress_inputs:
            box = QGroupBox(f"{inp.sm_name}.{inp.arg_name}  ({inp.stress_name})")
            form_s = QFormLayout(box)
            form_s.setContentsMargins(6, 6, 6, 6)

            # CSV picker row
            csv_row_w = QWidget()
            csv_row = QHBoxLayout(csv_row_w)
            csv_row.setContentsMargins(0, 0, 0, 0)
            btn_browse = QPushButton(_tr("Load File..."))
            lbl_file = QLabel(_tr("Not loaded (will use climatology mean)"))
            lbl_file.setStyleSheet("color: gray; font-size: 11px;")
            csv_row.addWidget(btn_browse)
            csv_row.addWidget(lbl_file, 1)

            # Synthetic selector row
            cbo_synth = QComboBox()
            cbo_synth.addItem(_tr("Climatology Mean"), "climatology_mean")
            cbo_synth.addItem(_tr("Zero (Dry / No Pumping)"), "zero")
            cbo_synth.addItem(_tr("Constant Value"), "constant")

            spn_const = QDoubleSpinBox()
            spn_const.setRange(-1e9, 1e9)
            spn_const.setDecimals(4)
            spn_const.setValue(0.0)
            spn_const.setVisible(False)

            spn_scale = QDoubleSpinBox()
            spn_scale.setRange(-100.0, 100.0)
            spn_scale.setDecimals(2)
            spn_scale.setSingleStep(0.1)
            spn_scale.setValue(1.0)

            row_dict = {
                "input": inp,
                "box": box,
                "csv_row_w": csv_row_w,
                "lbl_file": lbl_file,
                "loaded_df": None,
                "cbo_synth": cbo_synth,
                "spn_const": spn_const,
                "spn_scale": spn_scale,
            }

            def _make_browse(rd):
                def _browse():
                    fname, _ = QFileDialog.getOpenFileName(
                        self,
                        _tr("Select Ensemble Forecast File"),
                        "",
                        "Data Files (*.csv *.parquet *.xlsx *.xls);;All Files (*)",
                    )
                    if not fname:
                        return
                    try:
                        df = load_ensemble_csv(fname)
                        rd["loaded_df"] = df
                        rd["lbl_file"].setText(
                            f"{os.path.basename(fname)} ({df.shape[1]} members)"
                        )
                        rd["lbl_file"].setStyleSheet("color: #198754; font-size: 11px;")
                        rd["lbl_file"].setToolTip(fname)
                        # Sync forecast start/horizon from first loaded file if helpful
                        self.de_start.setDate(_ts_to_qdate(df.index.min()))
                        span_days = max(1, int((df.index.max() - df.index.min()).days) + 1)
                        self.spn_horizon_days.setValue(span_days)
                    except Exception as exc:
                        QMessageBox.warning(
                            self,
                            _tr("File Error"),
                            _tr("Could not load ensemble file: {0}").format(str(exc)),
                        )

                return _browse

            def _make_synth_handler(rd):
                def _on_synth(_idx):
                    mode = rd["cbo_synth"].currentData()
                    rd["spn_const"].setVisible(mode == "constant")

                return _on_synth

            btn_browse.clicked.connect(_make_browse(row_dict))
            cbo_synth.currentIndexChanged.connect(_make_synth_handler(row_dict))

            form_s.addRow(_tr("Ensemble File:"), csv_row_w)
            form_s.addRow(_tr("Method:"), cbo_synth)
            form_s.addRow(_tr("Value:"), spn_const)
            form_s.addRow(_tr("Scale:"), spn_scale)

            self._stress_rows.append(row_dict)
            per_stress_layout.addWidget(box)

        inp_layout.addWidget(self.per_stress_container)
        left_layout.addWidget(grp_inputs)

        # 3. Uncertainty & Post-Processing
        grp_unc = QGroupBox(_tr("Uncertainty & Post-Processing"))
        form_u = QFormLayout(grp_unc)

        self.chk_param_unc = QCheckBox(_tr("Include Parameter Uncertainty"))
        has_cov = has_parameter_covariance(self.ml)
        self.chk_param_unc.setEnabled(has_cov)
        if not has_cov:
            self.chk_param_unc.setToolTip(
                _tr("Parameter covariance (pcov) is not available for this model")
            )

        self.spn_param_samples = QSpinBox()
        self.spn_param_samples.setRange(5, 500)
        self.spn_param_samples.setValue(25)
        self.spn_param_samples.setEnabled(False)
        self.chk_param_unc.toggled.connect(self.spn_param_samples.setEnabled)

        self.chk_post_process = QCheckBox(_tr("AR1 Noise Post-Processing"))
        can_pp = can_post_process_forecast(self.ml)
        self.chk_post_process.setEnabled(can_pp)
        self.chk_post_process.setChecked(can_pp)
        if not can_pp:
            self.chk_post_process.setToolTip(
                _tr(
                    "Requires a solved model with an ArNoiseModel (Pastas only supports AR1 post-processing)"
                )
            )

        form_u.addRow("", self.chk_param_unc)
        form_u.addRow(_tr("Parameter Samples:"), self.spn_param_samples)
        form_u.addRow("", self.chk_post_process)
        left_layout.addWidget(grp_unc)

        # 4. Threshold Exceedance
        grp_thresh = QGroupBox(_tr("Threshold Exceedance Probability"))
        form_t = QFormLayout(grp_thresh)
        self.chk_threshold = QCheckBox(_tr("Evaluate Threshold"))
        self.chk_threshold.toggled.connect(self._refresh_plots)

        self.cbo_thresh_dir = QComboBox()
        self.cbo_thresh_dir.addItem(_tr("Head below threshold (<)"), "below")
        self.cbo_thresh_dir.addItem(_tr("Head above threshold (>)"), "above")
        self.cbo_thresh_dir.currentIndexChanged.connect(self._refresh_plots)

        default_thresh = 0.0
        try:
            obs = self.ml.observations().dropna()
            if not obs.empty:
                default_thresh = float(obs.median())
        except Exception:
            pass
        self.spn_threshold = QDoubleSpinBox()
        self.spn_threshold.setRange(-1e6, 1e6)
        self.spn_threshold.setDecimals(3)
        self.spn_threshold.setSingleStep(0.1)
        self.spn_threshold.setValue(default_thresh)
        self.spn_threshold.valueChanged.connect(self._refresh_plots)

        form_t.addRow("", self.chk_threshold)
        form_t.addRow(_tr("Condition:"), self.cbo_thresh_dir)
        form_t.addRow(_tr("Threshold:"), self.spn_threshold)
        left_layout.addWidget(grp_thresh)

        # Run button & progress
        self.btn_run = QPushButton(_tr("Run Forecast"))
        self.btn_run.setEnabled(is_model_solved(self.ml) and len(self.stress_inputs) > 0)
        self.btn_run.clicked.connect(self.run_forecast)
        left_layout.addWidget(self.btn_run)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        left_layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("color: #444; font-size: 11px;")
        left_layout.addWidget(self.lbl_status)

        left_layout.addStretch()

        left_scroll.setWidget(left_widget)
        left_scroll.setMinimumWidth(360)
        splitter.addWidget(left_scroll)

        # ---- Right pane: Plot + Summary Table ----
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 4, 4, 4)

        top_bar = QHBoxLayout()
        self.plot_nav = PlotNavigationWidget(parent=self)
        top_bar.addWidget(self.plot_nav)

        self.chk_show_members = QCheckBox(_tr("Show Ensemble Members"))
        self.chk_show_members.setChecked(True)
        self.chk_show_members.toggled.connect(self._refresh_plots)
        top_bar.addWidget(self.chk_show_members)

        self.chk_show_ci95 = QCheckBox(_tr("95% Band"))
        self.chk_show_ci95.setChecked(True)
        self.chk_show_ci95.toggled.connect(self._refresh_plots)
        top_bar.addWidget(self.chk_show_ci95)

        self.chk_show_ci50 = QCheckBox(_tr("50% Band"))
        self.chk_show_ci50.setChecked(True)
        self.chk_show_ci50.toggled.connect(self._refresh_plots)
        top_bar.addWidget(self.chk_show_ci50)

        top_bar.addStretch()

        self.btn_export_summary = QPushButton(_tr("Export Summary CSV"))
        self.btn_export_summary.setEnabled(False)
        self.btn_export_summary.clicked.connect(self.export_summary_csv)
        top_bar.addWidget(self.btn_export_summary)

        self.btn_export_full = QPushButton(_tr("Export Ensemble CSV"))
        self.btn_export_full.setEnabled(False)
        self.btn_export_full.clicked.connect(self.export_full_csv)
        top_bar.addWidget(self.btn_export_full)

        right_layout.addLayout(top_bar)

        self.right_tabs = QTabWidget()
        right_layout.addWidget(self.right_tabs, 1)

        # Tab 0: Fan Chart Plot
        self.win = pg.GraphicsLayoutWidget()
        self.win.setBackground("w")
        self.right_tabs.addTab(self.win, _tr("Forecast Plot"))

        # Tab 1: Summary Table
        self.tbl_summary = QTableWidget()
        self.tbl_summary.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_summary.setAlternatingRowColors(True)
        self.right_tabs.addTab(self.tbl_summary, _tr("Forecast Table"))

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        self._on_input_mode_changed()

    def _on_input_mode_changed(self):
        mode = self.cbo_input_mode.currentData()
        if mode == "historical":
            self.lbl_mode_hint.setText(
                _tr(
                    "Builds an ensemble from matching calendar windows of every complete "
                    "historical year in the model's stresses (preserving prec/evap correlation)."
                )
            )
            self.per_stress_container.setVisible(False)
        elif mode == "csv":
            self.lbl_mode_hint.setText(
                _tr(
                    "Load multi-column forecast files (datetime index, 1 column per ensemble member). "
                    "Single-column stresses are automatically broadcast across all members."
                )
            )
            self.per_stress_container.setVisible(True)
            for rd in self._stress_rows:
                rd["csv_row_w"].setVisible(True)
                rd["cbo_synth"].setVisible(False)
                rd["spn_const"].setVisible(False)
                rd["spn_scale"].setVisible(False)
        else:
            self.lbl_mode_hint.setText(
                _tr(
                    "Generate a deterministic stress forecast per input (combine with parameter "
                    "uncertainty or AR1 post-processing for prediction bands)."
                )
            )
            self.per_stress_container.setVisible(True)
            for rd in self._stress_rows:
                rd["csv_row_w"].setVisible(False)
                rd["cbo_synth"].setVisible(True)
                rd["spn_const"].setVisible(rd["cbo_synth"].currentData() == "constant")
                rd["spn_scale"].setVisible(True)

    # ------------------------------------------------------------------
    # Forecast Execution
    # ------------------------------------------------------------------

    def _build_forecasts_dict(self, tmin: pd.Timestamp, tmax: pd.Timestamp) -> dict:
        mode = self.cbo_input_mode.currentData()
        freq = get_model_freq(self.ml)

        if mode == "historical":
            series_map = {inp.key: inp.series for inp in self.stress_inputs}
            aligned = align_historical_ensembles(series_map, tmin=tmin, tmax=tmax, freq=freq)
            forecasts: dict[str, dict[str, pd.DataFrame]] = {}
            for (sm_name, arg_name), df in aligned.items():
                forecasts.setdefault(sm_name, {})[arg_name] = df
            return forecasts

        forecasts = {}
        for rd in self._stress_rows:
            inp = rd["input"]
            if mode == "csv":
                if rd["loaded_df"] is not None:
                    df = rd["loaded_df"]
                else:
                    df = build_synthetic_forecast(
                        inp.series,
                        tmin=tmin,
                        tmax=tmax,
                        freq=freq,
                        mode="climatology_mean",
                    )
            else:
                synth_mode = rd["cbo_synth"].currentData()
                df = build_synthetic_forecast(
                    inp.series,
                    tmin=tmin,
                    tmax=tmax,
                    freq=freq,
                    mode=synth_mode,
                    constant_value=float(rd["spn_const"].value()),
                    scale=float(rd["spn_scale"].value()),
                )
            forecasts.setdefault(inp.sm_name, {})[inp.arg_name] = df
        return forecasts

    def run_forecast(self):
        if self._worker is not None and self._worker.isRunning():
            return

        tmin = _qdate_to_ts(self.de_start.date())
        horizon = int(self.spn_horizon_days.value())
        tmax = tmin + pd.Timedelta(days=max(horizon - 1, 0))

        try:
            forecasts_dict = self._build_forecasts_dict(tmin, tmax)
        except Exception as exc:
            QMessageBox.critical(
                self,
                _tr("Forecast Input Error"),
                _tr("Could not prepare forecast inputs:\n{0}").format(str(exc)),
            )
            return

        n_param = (
            int(self.spn_param_samples.value())
            if self.chk_param_unc.isChecked()
            else 0
        )
        post_process = self.chk_post_process.isChecked()

        self.btn_run.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.lbl_status.setText(_tr("Starting ensemble forecast..."))

        self._worker = _ForecastWorker(
            self.ml,
            forecasts_dict,
            tmin=tmin,
            tmax=tmax,
            n_param_samples=n_param,
            post_process=post_process,
            parent=self,
        )
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.finished_result.connect(self._on_worker_finished)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.start()

    def _on_worker_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        self.lbl_status.setText(msg)

    def _on_worker_finished(self, result: ForecastResult):
        self.forecast_result = result
        self.btn_run.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.btn_export_summary.setEnabled(True)
        self.btn_export_full.setEnabled(True)
        self.lbl_status.setText(
            _tr(
                "Completed: {0} ensemble member(s) × {1} parameter set(s) | "
                "{2} → {3} | Post-processed: {4}"
            ).format(
                result.n_ensemble_members,
                result.n_param_samples,
                result.forecast_start.strftime("%Y-%m-%d"),
                result.forecast_end.strftime("%Y-%m-%d"),
                _tr("Yes") if result.post_processed else _tr("No"),
            )
        )
        self._refresh_plots()
        self._populate_summary_table()

    def _on_worker_failed(self, err_msg: str):
        self.btn_run.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.lbl_status.setText(_tr("Forecast failed."))
        QMessageBox.critical(
            self,
            _tr("Forecast Error"),
            _tr("Forecast execution failed:\n{0}").format(err_msg),
        )

    # ------------------------------------------------------------------
    # Plotting & Table
    # ------------------------------------------------------------------

    @staticmethod
    def _series_to_xy(series: pd.Series | None):
        if series is None or series.empty:
            return None, None
        x = series.index.astype("datetime64[s]").astype(np.int64)
        y = np.asarray(series.values, dtype=float)
        mask = np.isfinite(y)
        if not np.any(mask):
            return None, None
        return x[mask], y[mask]

    def _plot_historical_only(self):
        self.win.clear()
        p = self.win.addPlot(row=0, col=0, axisItems={"bottom": DateAxisItem()})
        p.setTitle(_tr("Forecast — {0}").format(self.ml.name), color="k")
        p.showGrid(x=True, y=True, alpha=0.3)
        p.addLegend()
        for ax_name in ("left", "bottom"):
            ax = p.getAxis(ax_name)
            ax.setPen("k")
            ax.setTextPen("k")

        lookback_days = int(self.spn_lookback.value())
        t_start = _qdate_to_ts(self.de_start.date())
        hist_tmin = t_start - pd.Timedelta(days=lookback_days)

        try:
            obs = self.ml.observations().loc[hist_tmin:]
            ox, oy = self._series_to_xy(obs)
            if ox is not None:
                p.plot(
                    ox,
                    oy,
                    pen=None,
                    symbol="o",
                    symbolSize=4,
                    symbolBrush="k",
                    name=_tr("Observations"),
                )
        except Exception:
            pass

        try:
            sim = self.ml.simulate().loc[hist_tmin:]
            sx, sy = self._series_to_xy(sim)
            if sx is not None:
                p.plot(
                    sx,
                    sy,
                    pen=pg.mkPen("#1f77b4", width=2),
                    name=_tr("Historical Simulation"),
                )
        except Exception:
            pass

        self.plot_nav.set_plots([p])

    def _refresh_plots(self):
        res = self.forecast_result
        if res is None:
            self._plot_historical_only()
            return

        self.win.clear()
        plots = []

        p_main = self.win.addPlot(row=0, col=0, axisItems={"bottom": DateAxisItem()})
        p_main.setTitle(
            _tr("Ensemble Forecast — {0} ({1} members)").format(
                self.ml.name, res.n_ensemble_members
            ),
            color="k",
        )
        p_main.showGrid(x=True, y=True, alpha=0.3)
        p_main.addLegend()
        for ax_name in ("left", "bottom"):
            ax = p_main.getAxis(ax_name)
            ax.setPen("k")
            ax.setTextPen("k")
        plots.append(p_main)

        lookback_days = int(self.spn_lookback.value())
        hist_tmin = res.forecast_start - pd.Timedelta(days=lookback_days)

        # Historical observations & simulation
        try:
            obs = self.ml.observations().loc[hist_tmin : res.forecast_end]
            ox, oy = self._series_to_xy(obs)
            if ox is not None:
                p_main.plot(
                    ox,
                    oy,
                    pen=None,
                    symbol="o",
                    symbolSize=4,
                    symbolBrush="k",
                    name=_tr("Observations"),
                )
        except Exception:
            pass

        try:
            sim = self.ml.simulate().loc[hist_tmin : res.forecast_start]
            sx, sy = self._series_to_xy(sim)
            if sx is not None:
                p_main.plot(
                    sx,
                    sy,
                    pen=pg.mkPen("#1f77b4", width=2),
                    name=_tr("Historical Simulation"),
                )
        except Exception:
            pass

        # Forecast start marker
        start_epoch = int(res.forecast_start.value // 10**9)
        p_main.addLine(
            x=start_epoch,
            pen=pg.mkPen("#555555", width=1.5, style=Qt.PenStyle.DashLine),
        )

        # 95% total uncertainty band
        summary = res.summary
        if self.chk_show_ci95.isChecked():
            fx, low95 = self._series_to_xy(summary["ci95_low"])
            _, high95 = self._series_to_xy(summary["ci95_high"])
            if fx is not None and high95 is not None and len(fx) == len(high95):
                fill95 = create_fill_between_item(
                    pg, fx, high95, low95, brush=pg.mkBrush(214, 39, 40, 45)
                )
                if fill95 is not None:
                    p_main.addItem(fill95)

        # 50% total uncertainty band
        if self.chk_show_ci50.isChecked():
            fx, low50 = self._series_to_xy(summary["ci50_low"])
            _, high50 = self._series_to_xy(summary["ci50_high"])
            if fx is not None and high50 is not None and len(fx) == len(high50):
                fill50 = create_fill_between_item(
                    pg, fx, high50, low50, brush=pg.mkBrush(214, 39, 40, 85)
                )
                if fill50 is not None:
                    p_main.addItem(fill50)

        # Individual ensemble member spaghetti lines
        if self.chk_show_members.isChecked() and res.n_ensemble_members > 1:
            pen_mem = pg.mkPen(color=(120, 120, 120, 75), width=1)
            for col in res.member_means.columns:
                mx, my = self._series_to_xy(res.member_means[col])
                if mx is not None:
                    p_main.plot(mx, my, pen=pen_mem)

        # Overall predictive mean & median
        mx, my = self._series_to_xy(res.overall_mean)
        if mx is not None:
            p_main.plot(
                mx,
                my,
                pen=pg.mkPen("#d62728", width=2.5),
                name=_tr("Forecast Mean"),
            )
        if res.n_ensemble_members > 1:
            px, py = self._series_to_xy(summary["p50"])
            if px is not None:
                p_main.plot(
                    px,
                    py,
                    pen=pg.mkPen("#ff7f0e", width=1.8, style=Qt.PenStyle.DashLine),
                    name=_tr("Ensemble Median (P50)"),
                )

        # Threshold line + probability panel
        if self.chk_threshold.isChecked():
            thresh = float(self.spn_threshold.value())
            direction = self.cbo_thresh_dir.currentData()
            p_main.addLine(
                y=thresh,
                pen=pg.mkPen("#198754", width=1.8, style=Qt.PenStyle.DotLine),
            )

            prob_df = res.compute_exceedance_probability(thresh, direction=direction)
            p_prob = self.win.addPlot(row=1, col=0, axisItems={"bottom": DateAxisItem()})
            op_sym = "<" if direction == "below" else ">"
            p_prob.setTitle(
                _tr("Probability (Head {0} {1:.3f})").format(op_sym, thresh), color="k"
            )
            p_prob.showGrid(x=True, y=True, alpha=0.3)
            p_prob.addLegend()
            p_prob.setXLink(p_main)
            p_prob.setYRange(0.0, 100.0, padding=0.05)
            p_prob.getAxis("left").setLabel(_tr("Probability [%]"))
            for ax_name in ("left", "bottom"):
                ax = p_prob.getAxis(ax_name)
                ax.setPen("k")
                ax.setTextPen("k")

            px1, py1 = self._series_to_xy(prob_df["prob_parametric"] * 100.0)
            if px1 is not None:
                p_prob.plot(
                    px1,
                    py1,
                    pen=pg.mkPen("#198754", width=2),
                    name=_tr("Total (Parametric)"),
                )
            if res.n_ensemble_members > 1:
                px2, py2 = self._series_to_xy(prob_df["prob_empirical"] * 100.0)
                if px2 is not None:
                    p_prob.plot(
                        px2,
                        py2,
                        pen=pg.mkPen("#0d6efd", width=1.5, style=Qt.PenStyle.DashLine),
                        name=_tr("Ensemble Fraction"),
                    )
            plots.append(p_prob)
            self.win.ci.layout.setRowStretchFactor(0, 3)
            self.win.ci.layout.setRowStretchFactor(1, 1)

        self.plot_nav.set_plots(plots)
        self._populate_summary_table()

    def _populate_summary_table(self):
        res = self.forecast_result
        if res is None:
            return
        df = res.summary.copy()
        cols = ["mean", "std", "ci95_low", "ci95_high", "p05", "p50", "p95"]
        headers = [_tr("Date"), "Mean", "Std", "CI 95% Low", "CI 95% High", "P05", "P50", "P95"]

        if self.chk_threshold.isChecked():
            prob_df = res.compute_exceedance_probability(
                float(self.spn_threshold.value()),
                direction=self.cbo_thresh_dir.currentData(),
            )
            df["prob_pct"] = prob_df["prob_parametric"] * 100.0
            cols.append("prob_pct")
            headers.append(_tr("Prob [%]"))

        self.tbl_summary.setRowCount(len(df))
        self.tbl_summary.setColumnCount(len(headers))
        self.tbl_summary.setHorizontalHeaderLabels(headers)
        self.tbl_summary.verticalHeader().setVisible(False)

        for r, (dt_idx, row) in enumerate(df.iterrows()):
            self.tbl_summary.setItem(
                r, 0, QTableWidgetItem(pd.Timestamp(dt_idx).strftime("%Y-%m-%d"))
            )
            for c, col_name in enumerate(cols):
                val = row.get(col_name, np.nan)
                txt = f"{float(val):.3f}" if pd.notna(val) and np.isfinite(val) else "-"
                item = QTableWidgetItem(txt)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                self.tbl_summary.setItem(r, c + 1, item)

        self.tbl_summary.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_summary_csv(self):
        if self.forecast_result is None:
            return
        fname, _ = QFileDialog.getSaveFileName(
            self,
            _tr("Export Forecast Summary CSV"),
            f"{self.ml.name}_forecast_summary.csv",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not fname:
            return
        try:
            df = self.forecast_result.summary.copy()
            if self.chk_threshold.isChecked():
                prob_df = self.forecast_result.compute_exceedance_probability(
                    float(self.spn_threshold.value()),
                    direction=self.cbo_thresh_dir.currentData(),
                )
                df["prob_parametric"] = prob_df["prob_parametric"]
                df["prob_empirical"] = prob_df["prob_empirical"]
            df.to_csv(fname)
            QMessageBox.information(
                self,
                _tr("Export Complete"),
                _tr("Saved forecast summary to:\n{0}").format(fname),
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                _tr("Export Error"),
                _tr("Failed to export forecast summary: {0}").format(str(exc)),
            )

    def export_full_csv(self):
        if self.forecast_result is None:
            return
        fname, _ = QFileDialog.getSaveFileName(
            self,
            _tr("Export Full Ensemble Forecast CSV"),
            f"{self.ml.name}_forecast_ensemble.csv",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not fname:
            return
        try:
            self.forecast_result.member_means.to_csv(fname)
            QMessageBox.information(
                self,
                _tr("Export Complete"),
                _tr("Saved ensemble member forecasts to:\n{0}").format(fname),
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                _tr("Export Error"),
                _tr("Failed to export ensemble CSV: {0}").format(str(exc)),
            )

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(2000)
        super().closeEvent(event)
