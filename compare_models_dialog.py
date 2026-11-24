# -*- coding: utf-8 -*-
# Copyright © 2024-2026 Pastastore Viewer Contributors. All rights reserved.
# This software is proprietary. See LICENSE.md for details.
"""Interactive dialog for comparing multiple Pastas models."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pastas as ps
import pyqtgraph as pg
from pyqtgraph import DateAxisItem
from qgis.core import QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QBrush, QColor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QAction,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsProxyWidget,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
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
        build_comparison_data,
        compute_fast_acf,
        compute_fast_diagnostics,
        compute_model_differences,
        is_model_solved,
    )
    from .plot_toolbar import PlotNavigationWidget
except (ImportError, ValueError):
    from i18n_helper import tr as _i18n_tr
    from model_analysis import (
        build_comparison_data,
        compute_fast_acf,
        compute_fast_diagnostics,
        compute_model_differences,
        is_model_solved,
    )
    from plot_toolbar import PlotNavigationWidget


def _tr(message: str) -> str:
    return _i18n_tr(message)


MODEL_COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
]

METRIC_LABELS = {
    "rsq": ("R²", "max"),
    "evp": ("EVP [%]", "max"),
    "rmse": ("RMSE", "min"),
    "nse": ("NSE", "max"),
    "kge": ("KGE", "max"),
    "aic": ("AIC", "min"),
    "aicc": ("AICc", "min"),
    "delta_aicc": ("ΔAICc", "min"),
    "bic": ("BIC", "min"),
}


class CompareModelsDialog(QDialog):
    """Modeless dialog to visually and statistically compare multiple Pastas models."""

    def __init__(
        self,
        models: list[ps.Model],
        names: list[str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.all_models = list(models)
        if names is not None and len(names) == len(models):
            self.all_names = list(names)
        else:
            raw_names = [m.name for m in models]
            if len(set(raw_names)) < len(raw_names):
                self.all_names = [f"{m.name}_{i}" for i, m in enumerate(models)]
            else:
                self.all_names = raw_names

        self.setWindowTitle(
            _tr("Compare Models ({0})").format(len(self.all_models))
        )
        self.resize(1280, 900)

        self.load_settings()
        self.comparison_data = None
        self._model_checkboxes: list[QCheckBox] = []
        self._overview_plots: list[pg.PlotItem] = []
        self._tables_dirty = True
        self._diag_plots_dirty = True
        self._diagnostics_loaded = False

        self._init_ui()
        self.refresh_all()

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    def load_settings(self):
        proj = QgsProject.instance()
        self.use_common_period = proj.readBoolEntry(
            "PastastoreViewer", "compare_common_period", False
        )[0]
        self.normalize_contributions = proj.readBoolEntry(
            "PastastoreViewer", "compare_normalize_contributions", False
        )[0]
        self.show_noise = proj.readBoolEntry(
            "PastastoreViewer", "compare_show_noise", False
        )[0]
        self.show_diff_vs_ref = proj.readBoolEntry(
            "PastastoreViewer", "compare_show_diff_vs_ref", False
        )[0]
        self.show_block_response = proj.readBoolEntry(
            "PastastoreViewer", "compare_show_block_response", False
        )[0]
        self.show_stderr = proj.readBoolEntry(
            "PastastoreViewer", "compare_show_stderr", False
        )[0]

    def save_settings(self):
        proj = QgsProject.instance()
        proj.writeEntry(
            "PastastoreViewer", "compare_common_period", self.use_common_period
        )
        proj.writeEntry(
            "PastastoreViewer",
            "compare_normalize_contributions",
            self.normalize_contributions,
        )
        proj.writeEntry("PastastoreViewer", "compare_show_noise", self.show_noise)
        proj.writeEntry(
            "PastastoreViewer", "compare_show_diff_vs_ref", self.show_diff_vs_ref
        )
        proj.writeEntry(
            "PastastoreViewer",
            "compare_show_block_response",
            self.show_block_response,
        )
        proj.writeEntry("PastastoreViewer", "compare_show_stderr", self.show_stderr)

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # Toolbar row
        toolbar = QHBoxLayout()
        self.btn_settings = QPushButton(_tr("Settings"))
        self.settings_menu = QMenu(self)

        self.act_common_period = QAction(_tr("Use Common Period"), self, checkable=True)
        self.act_common_period.setChecked(self.use_common_period)
        self.act_common_period.triggered.connect(self._toggle_common_period)
        self.settings_menu.addAction(self.act_common_period)

        self.act_normalize = QAction(
            _tr("Normalize Contributions"), self, checkable=True
        )
        self.act_normalize.setChecked(self.normalize_contributions)
        self.act_normalize.triggered.connect(self._toggle_normalize)
        self.settings_menu.addAction(self.act_normalize)

        self.act_noise = QAction(_tr("Show Noise (if available)"), self, checkable=True)
        self.act_noise.setChecked(self.show_noise)
        self.act_noise.triggered.connect(self._toggle_noise)
        self.settings_menu.addAction(self.act_noise)

        self.act_diff = QAction(
            _tr("Show Difference vs Reference"), self, checkable=True
        )
        self.act_diff.setChecked(self.show_diff_vs_ref)
        self.act_diff.triggered.connect(self._toggle_diff)
        self.settings_menu.addAction(self.act_diff)

        self.act_block = QAction(_tr("Show Block Response"), self, checkable=True)
        self.act_block.setChecked(self.show_block_response)
        self.act_block.triggered.connect(self._toggle_block)
        self.settings_menu.addAction(self.act_block)

        self.act_stderr = QAction(
            _tr("Show Std Error in Parameters"), self, checkable=True
        )
        self.act_stderr.setChecked(self.show_stderr)
        self.act_stderr.triggered.connect(self._toggle_stderr)
        self.settings_menu.addAction(self.act_stderr)

        self.btn_settings.setMenu(self.settings_menu)
        toolbar.addWidget(self.btn_settings)

        self.plot_nav = PlotNavigationWidget(parent=self)
        toolbar.addWidget(self.plot_nav)

        toolbar.addWidget(QLabel(_tr("Reference:")))
        self.cbo_reference = QComboBox()
        self.cbo_reference.addItems(self.all_names)
        self.cbo_reference.setEnabled(self.show_diff_vs_ref)
        self.cbo_reference.currentIndexChanged.connect(self._render_overview)
        toolbar.addWidget(self.cbo_reference)

        toolbar.addStretch()

        self.btn_export_csv = QPushButton(_tr("Export Tables (CSV)"))
        self.btn_export_csv.clicked.connect(self.export_tables_csv)
        toolbar.addWidget(self.btn_export_csv)

        self.btn_mpl = QPushButton(_tr("Open in Matplotlib"))
        self.btn_mpl.clicked.connect(self.open_in_matplotlib)
        toolbar.addWidget(self.btn_mpl)

        main_layout.addLayout(toolbar)

        # Model visibility toggles
        models_bar = QHBoxLayout()
        models_bar.addWidget(QLabel(_tr("Models:")))
        for i, mname in enumerate(self.all_names):
            color = MODEL_COLORS[i % len(MODEL_COLORS)]
            chk = QCheckBox(mname)
            chk.setChecked(True)
            chk.setStyleSheet(f"QCheckBox {{ color: {color}; font-weight: bold; }}")
            chk.toggled.connect(self.refresh_all)
            self._model_checkboxes.append(chk)
            models_bar.addWidget(chk)
        models_bar.addStretch()
        main_layout.addLayout(models_bar)

        # Tabs
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs, 1)

        # Tab 0: Overview plots
        self.tab_overview = QWidget()
        ov_layout = QVBoxLayout(self.tab_overview)
        ov_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.win_overview = pg.GraphicsLayoutWidget()
        self.win_overview.setBackground("w")
        self.win_overview.ci.layout.setContentsMargins(0, 0, 0, 0)
        self.win_overview.ci.layout.setSpacing(10)
        self.scroll_layout.addWidget(self.win_overview)
        self.scroll.setWidget(self.scroll_content)
        ov_layout.addWidget(self.scroll)
        self.tabs.addTab(self.tab_overview, _tr("Overview"))

        # Tab 1: Tables (Metrics, Parameters, Diagnostics)
        self.tab_tables = QWidget()
        tbl_layout = QVBoxLayout(self.tab_tables)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Metrics group
        w_met = QWidget()
        l_met = QVBoxLayout(w_met)
        l_met.setContentsMargins(0, 0, 0, 0)
        l_met.addWidget(QLabel(_tr("Fit Metrics (best value highlighted)")))
        self.tbl_metrics = QTableWidget()
        self.tbl_metrics.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_metrics.setAlternatingRowColors(True)
        l_met.addWidget(self.tbl_metrics)
        splitter.addWidget(w_met)

        # Parameters group
        w_par = QWidget()
        l_par = QVBoxLayout(w_par)
        l_par.setContentsMargins(0, 0, 0, 0)
        l_par.addWidget(QLabel(_tr("Model Parameters")))
        self.tbl_params = QTableWidget()
        self.tbl_params.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_params.setAlternatingRowColors(True)
        l_par.addWidget(self.tbl_params)
        splitter.addWidget(w_par)

        # Diagnostics group
        w_diag = QWidget()
        l_diag = QVBoxLayout(w_diag)
        l_diag.setContentsMargins(0, 0, 0, 0)
        l_diag.addWidget(QLabel(_tr("Diagnostic Tests (P-values; >= 0.05 passes)")))
        self.tbl_diagnostics = QTableWidget()
        self.tbl_diagnostics.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.tbl_diagnostics.setAlternatingRowColors(True)
        l_diag.addWidget(self.tbl_diagnostics)
        splitter.addWidget(w_diag)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 2)
        tbl_layout.addWidget(splitter)
        self.tabs.addTab(self.tab_tables, _tr("Metrics & Parameters"))

        # Tab 2: Diagnostics plots (ACF + residual density)
        self.tab_diag_plots = QWidget()
        dp_layout = QVBoxLayout(self.tab_diag_plots)
        dp_layout.setContentsMargins(0, 0, 0, 0)
        self.win_diag = pg.GraphicsLayoutWidget()
        self.win_diag.setBackground("w")
        self.win_diag.ci.layout.setContentsMargins(6, 6, 6, 6)
        self.win_diag.ci.layout.setSpacing(10)
        dp_layout.addWidget(self.win_diag)
        self.tabs.addTab(self.tab_diag_plots, _tr("Diagnostics Comparison"))
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _on_tab_changed(self, index: int):
        if index == 1 and self._tables_dirty:
            self._ensure_diagnostics_loaded()
            self._render_tables()
            self._tables_dirty = False
        elif index == 2 and self._diag_plots_dirty:
            self._render_diag_plots()
            self._diag_plots_dirty = False

    def _ensure_diagnostics_loaded(self):
        if self._diagnostics_loaded or self.comparison_data is None:
            return
        self.comparison_data.diagnostics = compute_fast_diagnostics(
            self.comparison_data.models,
            self.comparison_data.model_names,
            tmin=getattr(self, "_active_tmin", None),
            tmax=getattr(self, "_active_tmax", None),
        )
        self._diagnostics_loaded = True

    # ------------------------------------------------------------------
    # Active model selection & toggles
    # ------------------------------------------------------------------

    def _get_active_models(self) -> list[tuple[int, str, ps.Model, str]]:
        """Return list of (orig_idx, name, model, hex_color) for checked models."""
        active = []
        for i, chk in enumerate(self._model_checkboxes):
            if chk.isChecked():
                color = MODEL_COLORS[i % len(MODEL_COLORS)]
                active.append((i, self.all_names[i], self.all_models[i], color))
        return active

    def _toggle_common_period(self, checked):
        self.use_common_period = bool(checked)
        self.save_settings()
        self.refresh_all()

    def _toggle_normalize(self, checked):
        self.normalize_contributions = bool(checked)
        self.save_settings()
        self._render_overview()

    def _toggle_noise(self, checked):
        self.show_noise = bool(checked)
        self.save_settings()
        self._render_overview()
        self._diag_plots_dirty = True
        if self.tabs.currentIndex() == 2:
            self._render_diag_plots()
            self._diag_plots_dirty = False

    def _toggle_diff(self, checked):
        self.show_diff_vs_ref = bool(checked)
        self.cbo_reference.setEnabled(self.show_diff_vs_ref)
        self.save_settings()
        self._render_overview()

    def _toggle_block(self, checked):
        self.show_block_response = bool(checked)
        self.save_settings()
        self._render_overview()

    def _toggle_stderr(self, checked):
        self.show_stderr = bool(checked)
        self.save_settings()
        self._tables_dirty = True
        if self.tabs.currentIndex() == 1:
            self._ensure_diagnostics_loaded()
            self._render_tables()
            self._tables_dirty = False

    # ------------------------------------------------------------------
    # Refresh pipeline
    # ------------------------------------------------------------------

    def refresh_all(self):
        active = self._get_active_models()
        self._tables_dirty = True
        self._diag_plots_dirty = True
        self._diagnostics_loaded = False

        if len(active) < 2:
            self.comparison_data = None
            self.win_overview.clear()
            p = self.win_overview.addPlot(row=0, col=0)
            p.setTitle(_tr("Select at least two models to compare"), color="k")
            self.win_diag.clear()
            self.tbl_metrics.setRowCount(0)
            self.tbl_params.setRowCount(0)
            self.tbl_diagnostics.setRowCount(0)
            return

        active_names = [a[1] for a in active]
        active_models = [a[2] for a in active]

        # Keep reference combobox synced with active models
        prev_ref = self.cbo_reference.currentText()
        self.cbo_reference.blockSignals(True)
        self.cbo_reference.clear()
        self.cbo_reference.addItems(active_names)
        if prev_ref in active_names:
            self.cbo_reference.setCurrentText(prev_ref)
        self.cbo_reference.blockSignals(False)

        # Compute common period cheaply before calling build_comparison_data once
        req_tmin = None
        req_tmax = None
        if self.use_common_period:
            tmins = []
            tmaxs = []
            for ml in active_models:
                try:
                    t0 = ml.get_tmin()
                    t1 = ml.get_tmax()
                    if t0 is not None and pd.notna(t0):
                        tmins.append(pd.Timestamp(t0))
                    if t1 is not None and pd.notna(t1):
                        tmaxs.append(pd.Timestamp(t1))
                except Exception:
                    pass
            if tmins and tmaxs:
                c0, c1 = max(tmins), min(tmaxs)
                if c0 < c1:
                    req_tmin, req_tmax = c0, c1
                else:
                    req_tmin, req_tmax = min(tmins), max(tmaxs)

        self._active_tmin = req_tmin
        self._active_tmax = req_tmax
        self.comparison_data = build_comparison_data(
            active_models,
            names=active_names,
            tmin=req_tmin,
            tmax=req_tmax,
            include_diagnostics=False,
        )

        self._render_overview()
        if self.tabs.currentIndex() == 1:
            self._ensure_diagnostics_loaded()
            self._render_tables()
            self._tables_dirty = False
        elif self.tabs.currentIndex() == 2:
            self._render_diag_plots()
            self._diag_plots_dirty = False

    # ------------------------------------------------------------------
    # Plot helpers
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

    @staticmethod
    def _style_plot(plot: pg.PlotItem, y_axis_width: int = 48):
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.getAxis("left").setWidth(y_axis_width)
        for axis_name in ("bottom", "left"):
            ax = plot.getAxis(axis_name)
            ax.setPen("k")
            ax.setTextPen("k")

    # ------------------------------------------------------------------
    # Tab 0: Overview
    # ------------------------------------------------------------------

    def _render_overview(self):
        self.win_overview.clear()
        self._overview_plots = []
        active = self._get_active_models()
        data = self.comparison_data
        if data is None or len(active) < 2:
            return

        tmin = getattr(self, "_active_tmin", None)
        tmax = getattr(self, "_active_tmax", None)
        unique_sms = data.unique_stressmodels

        # Row 0: Observations & Simulations
        p_sim = self.win_overview.addPlot(
            row=0, col=0, axisItems={"bottom": DateAxisItem()}
        )
        p_sim.setTitle(_tr("Observations & Simulations"), color="k")
        p_sim.addLegend()
        p_sim.setMinimumHeight(240)
        self._style_plot(p_sim)

        if data.same_oseries:
            obs0 = active[0][2].observations(tmin=tmin, tmax=tmax)
            ox, oy = self._series_to_xy(obs0)
            if ox is not None:
                p_sim.plot(
                    ox,
                    oy,
                    pen=None,
                    symbol="o",
                    symbolSize=4,
                    symbolBrush="k",
                    name=str(obs0.name or _tr("Observations")),
                )

        for _, mname, ml, color in active:
            if not data.same_oseries:
                obs = ml.observations(tmin=tmin, tmax=tmax)
                ox, oy = self._series_to_xy(obs)
                if ox is not None:
                    p_sim.plot(
                        ox,
                        oy,
                        pen=None,
                        symbol="o",
                        symbolSize=4,
                        symbolBrush=color,
                        name=f"{mname} (Obs)",
                    )
            try:
                sim = ml.simulate(tmin=tmin, tmax=tmax)
                sx, sy = self._series_to_xy(sim)
                if sx is not None:
                    p_sim.plot(sx, sy, pen=pg.mkPen(color, width=2), name=mname)
            except Exception:
                pass

        main_plots = [p_sim]
        side_plots = []

        # Row 1: Residuals/Noise OR Difference vs Reference
        p_res = self.win_overview.addPlot(
            row=1, col=0, axisItems={"bottom": DateAxisItem()}
        )
        p_res.setXLink(p_sim)
        p_res.addLegend()
        p_res.setMinimumHeight(160)
        self._style_plot(p_res)
        p_res.addLine(y=0, pen=pg.mkPen("k", style=Qt.PenStyle.DashLine))

        if self.show_diff_vs_ref:
            ref_name = self.cbo_reference.currentText()
            p_res.setTitle(
                _tr("Simulation Difference vs '{0}'").format(ref_name), color="k"
            )
            try:
                diffs = compute_model_differences(
                    [a[2] for a in active],
                    [a[1] for a in active],
                    reference_name=ref_name,
                    tmin=tmin,
                    tmax=tmax,
                )
                color_map = {a[1]: a[3] for a in active}
                for mname, dser in diffs.items():
                    dx, dy = self._series_to_xy(dser)
                    if dx is not None:
                        p_res.plot(
                            dx,
                            dy,
                            pen=pg.mkPen(color_map[mname], width=1.8),
                            name=dser.name,
                        )
            except Exception:
                pass
        else:
            p_res.setTitle(
                _tr("Noise (fallback: Residuals)")
                if self.show_noise
                else _tr("Residuals"),
                color="k",
            )
            for _, mname, ml, color in active:
                try:
                    if self.show_noise and ml.noisemodel is not None:
                        ser = ml.noise(tmin=tmin, tmax=tmax)
                    else:
                        ser = ml.residuals(tmin=tmin, tmax=tmax)
                    rx, ry = self._series_to_xy(ser)
                    if rx is not None:
                        p_res.plot(rx, ry, pen=pg.mkPen(color, width=1.2), name=mname)
                except Exception:
                    pass

        main_plots.append(p_res)

        # Row 0-1 Col 1: Compact Metrics Table
        compact_metrics_widget = self._build_compact_metrics_table(data)
        proxy = QGraphicsProxyWidget()
        proxy.setWidget(compact_metrics_widget)
        self.win_overview.addItem(proxy, row=0, col=1, rowspan=2)
        proxy.setMinimumWidth(260)
        proxy.setMaximumWidth(480)

        # Rows 2+: Contributions & Step/Block Responses
        resp_type = "block" if self.show_block_response else "step"
        resp_label = _tr("Block Response") if self.show_block_response else _tr("Step Response")

        for idx_sm, sm_name in enumerate(unique_sms):
            row_idx = idx_sm + 2

            p_con = self.win_overview.addPlot(
                row=row_idx, col=0, axisItems={"bottom": DateAxisItem()}
            )
            title = f"{_tr('Contribution')}: {sm_name}"
            if self.normalize_contributions:
                title += f" ({_tr('normalized')})"
            p_con.setTitle(title, color="k")
            p_con.setXLink(p_sim)
            p_con.setMinimumHeight(150)
            self._style_plot(p_con)

            p_rf = self.win_overview.addPlot(row=row_idx, col=1)
            p_rf.setTitle(f"{resp_label}: {sm_name}", color="k")
            p_rf.setMinimumHeight(150)
            self._style_plot(p_rf)
            if self.show_block_response:
                p_rf.setLogMode(x=True, y=False)

            for _, mname, ml, color in active:
                if sm_name not in ml.stressmodels:
                    continue
                try:
                    con = ml.get_contribution(sm_name, tmin=tmin, tmax=tmax)
                    if self.normalize_contributions and not con.empty:
                        if con.mean() < 0:
                            con = con - con.max()
                        else:
                            con = con - con.min()
                    cx, cy = self._series_to_xy(con)
                    if cx is not None:
                        p_con.plot(cx, cy, pen=pg.mkPen(color, width=1.5), name=mname)
                except Exception:
                    pass

                try:
                    if resp_type == "block":
                        resp = ml.get_block_response(sm_name, add_0=False)
                    else:
                        resp = ml.get_step_response(sm_name, add_0=True)
                    if resp is not None and not resp.empty:
                        rx = np.asarray(resp.index.values, dtype=float)
                        ry = np.asarray(resp.values, dtype=float)
                        mask = np.isfinite(rx) & np.isfinite(ry)
                        if self.show_block_response:
                            mask &= rx > 0
                        if np.any(mask):
                            p_rf.plot(
                                rx[mask],
                                ry[mask],
                                pen=pg.mkPen(color, width=2),
                                name=mname,
                            )
                except Exception:
                    pass

            main_plots.append(p_con)
            side_plots.append(p_rf)

        total_h = 250 + 170 + len(unique_sms) * 165 + 40
        viewport_h = max(self.scroll.viewport().height(), 600)
        self.win_overview.setMinimumHeight(max(total_h, viewport_h))
        self.win_overview.ci.layout.setColumnStretchFactor(0, 3)
        self.win_overview.ci.layout.setColumnStretchFactor(1, 1)

        self._overview_plots = main_plots + side_plots
        self.plot_nav.set_plots(self._overview_plots)

    def _build_compact_metrics_table(self, data) -> QWidget:
        container = QWidget()
        container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(4, 4, 4, 4)

        tbl = QTableWidget()
        compact_keys = [
            k for k in ("rsq", "evp", "rmse", "delta_aicc", "bic") if k in data.metrics.index
        ]
        self._populate_metrics_table(tbl, data.metrics.loc[compact_keys], data.model_names)
        tbl.setStyleSheet("background-color: white; gridline-color: #ddd;")
        vbox.addWidget(tbl)
        return container

    # ------------------------------------------------------------------
    # Tab 1: Tables
    # ------------------------------------------------------------------

    def _populate_metrics_table(
        self,
        table: QTableWidget,
        metrics_df: pd.DataFrame,
        model_names: list[str],
    ):
        table.setRowCount(len(metrics_df.index))
        table.setColumnCount(len(model_names) + 1)
        table.setHorizontalHeaderLabels([_tr("Metric")] + list(model_names))
        table.verticalHeader().setVisible(False)

        best_brush = QBrush(QColor(212, 237, 218))

        for r, stat_key in enumerate(metrics_df.index):
            label, goal = METRIC_LABELS.get(stat_key, (str(stat_key), None))
            lbl_item = QTableWidgetItem(label)
            table.setItem(r, 0, lbl_item)

            row_vals = metrics_df.loc[stat_key]
            valid_vals = row_vals.dropna()
            best_val = None
            if not valid_vals.empty and goal in ("max", "min"):
                best_val = float(valid_vals.max() if goal == "max" else valid_vals.min())

            for c, mname in enumerate(model_names):
                val = row_vals.get(mname, np.nan)
                if pd.notna(val) and np.isfinite(val):
                    txt = f"{float(val):.3f}"
                    item = QTableWidgetItem(txt)
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                    if best_val is not None and np.isclose(float(val), best_val, rtol=1e-6, atol=1e-9):
                        item.setBackground(best_brush)
                else:
                    item = QTableWidgetItem("-")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(r, c + 1, item)

        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    def _render_tables(self):
        data = self.comparison_data
        if data is None:
            return

        # 1. Metrics
        self._populate_metrics_table(self.tbl_metrics, data.metrics, data.model_names)

        # 2. Parameters
        p_opt = data.parameters_optimal
        p_err = data.parameters_stderr
        self.tbl_params.setRowCount(len(p_opt.index))
        self.tbl_params.setColumnCount(len(data.model_names) + 1)
        self.tbl_params.setHorizontalHeaderLabels(
            [_tr("Parameter")] + list(data.model_names)
        )
        self.tbl_params.verticalHeader().setVisible(False)

        for r, pname in enumerate(p_opt.index):
            self.tbl_params.setItem(r, 0, QTableWidgetItem(str(pname)))
            for c, mname in enumerate(data.model_names):
                val = p_opt.loc[pname, mname] if mname in p_opt.columns else np.nan
                if pd.notna(val) and np.isfinite(val):
                    txt = f"{float(val):.4g}"
                    if self.show_stderr and pname in p_err.index and mname in p_err.columns:
                        err = p_err.loc[pname, mname]
                        if pd.notna(err) and np.isfinite(err):
                            txt += f" ± {float(err):.3g}"
                    item = QTableWidgetItem(txt)
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                else:
                    item = QTableWidgetItem("-")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.tbl_params.setItem(r, c + 1, item)

        self.tbl_params.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )

        # 3. Diagnostics P-values
        diag = data.diagnostics
        self.tbl_diagnostics.setRowCount(len(diag.index))
        self.tbl_diagnostics.setColumnCount(len(data.model_names) + 1)
        self.tbl_diagnostics.setHorizontalHeaderLabels(
            [_tr("Test")] + list(data.model_names)
        )
        self.tbl_diagnostics.verticalHeader().setVisible(False)

        pass_brush = QBrush(QColor(212, 237, 218))
        fail_brush = QBrush(QColor(248, 215, 218))

        for r, test_name in enumerate(diag.index):
            self.tbl_diagnostics.setItem(r, 0, QTableWidgetItem(str(test_name)))
            for c, mname in enumerate(data.model_names):
                val = diag.loc[test_name, mname] if mname in diag.columns else np.nan
                if pd.notna(val) and np.isfinite(val):
                    fval = float(val)
                    item = QTableWidgetItem(f"{fval:.3f}")
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                    item.setBackground(pass_brush if fval >= 0.05 else fail_brush)
                else:
                    item = QTableWidgetItem("-")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.tbl_diagnostics.setItem(r, c + 1, item)

        self.tbl_diagnostics.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )

    # ------------------------------------------------------------------
    # Tab 2: Diagnostics plots (ACF + Residual distributions)
    # ------------------------------------------------------------------

    def _render_diag_plots(self):
        self.win_diag.clear()
        active = self._get_active_models()
        if len(active) < 2:
            return

        tmin = getattr(self, "_active_tmin", None)
        tmax = getattr(self, "_active_tmax", None)

        p_acf = self.win_diag.addPlot(row=0, col=0)
        p_acf.setTitle(_tr("Autocorrelation (ACF)"), color="k")
        p_acf.getAxis("bottom").setLabel(_tr("Lag [days]"))
        p_acf.getAxis("left").setLabel(_tr("Autocorrelation [-]"))
        p_acf.addLegend()
        p_acf.addLine(y=0, pen=pg.mkPen("k"))
        self._style_plot(p_acf)

        p_hist = self.win_diag.addPlot(row=0, col=1)
        p_hist.setTitle(_tr("Residual / Noise Distribution"), color="k")
        p_hist.getAxis("bottom").setLabel(_tr("Value"))
        p_hist.getAxis("left").setLabel(_tr("Density"))
        p_hist.addLegend()
        p_hist.addLine(x=0, pen=pg.mkPen("k", style=Qt.PenStyle.DashLine))
        self._style_plot(p_hist)

        for _, mname, ml, color in active:
            if not is_model_solved(ml):
                continue
            try:
                if self.show_noise and ml.noisemodel is not None:
                    ser = ml.noise(tmin=tmin, tmax=tmax).iloc[1:]
                else:
                    ser = ml.residuals(tmin=tmin, tmax=tmax)
                vals = ser.dropna().to_numpy(dtype=float)
                if len(vals) < 5:
                    continue

                # Fast ACF curve (avoids O(lags * N^2) pure-Python slotting without Numba)
                try:
                    r = compute_fast_acf(ser.dropna())
                    if not r.empty:
                        lags = r.index.days.values.astype(float)
                        p_acf.plot(
                            lags,
                            r["acf"].to_numpy(dtype=float),
                            pen=pg.mkPen(color, width=2),
                            symbol="o",
                            symbolSize=4,
                            symbolBrush=color,
                            name=mname,
                        )
                except Exception:
                    pass

                # Density curve via histogram step line
                counts, edges = np.histogram(vals, bins=30, density=True)
                centers = 0.5 * (edges[:-1] + edges[1:])
                p_hist.plot(
                    centers,
                    counts,
                    pen=pg.mkPen(color, width=2),
                    name=f"{mname} (σ={np.std(vals):.3f})",
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def export_tables_csv(self):
        if self.comparison_data is None:
            return
        self._ensure_diagnostics_loaded()
        folder = QFileDialog.getExistingDirectory(
            self, _tr("Select Directory to Export Comparison CSVs")
        )
        if not folder:
            return
        try:
            import os

            self.comparison_data.metrics.to_csv(
                os.path.join(folder, "comparison_metrics.csv")
            )
            self.comparison_data.parameters_optimal.to_csv(
                os.path.join(folder, "comparison_parameters.csv")
            )
            if not self.comparison_data.diagnostics.empty:
                self.comparison_data.diagnostics.to_csv(
                    os.path.join(folder, "comparison_diagnostics.csv")
                )
            QMessageBox.information(
                self,
                _tr("Export Complete"),
                _tr("Exported comparison CSV files to:\n{0}").format(folder),
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                _tr("Export Error"),
                _tr("Failed to export comparison tables: {0}").format(str(exc)),
            )

    def open_in_matplotlib(self):
        active = self._get_active_models()
        if len(active) < 2:
            return
        try:
            import matplotlib.pyplot as plt

            tmin = getattr(self, "_active_tmin", None)
            tmax = getattr(self, "_active_tmax", None)
            mc = ps.CompareModels(
                [a[2] for a in active],
                names=[a[1] for a in active],
                tmin=tmin,
                tmax=tmax,
            )
            mc.plot(normalized=self.normalize_contributions)
            plt.show()
        except Exception as exc:
            QMessageBox.critical(
                self,
                _tr("Matplotlib Error"),
                _tr("Failed to show Matplotlib comparison: {0}").format(str(exc)),
            )
