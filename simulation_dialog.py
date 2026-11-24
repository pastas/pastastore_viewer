# -*- coding: utf-8 -*-
# Copyright © 2024-2026 Pastastore Viewer Contributors. All rights reserved.
# This software is proprietary. See LICENSE.md for details.
"""Non-destructive scenario simulation dialog for Pastas models."""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pastas as ps
import pyqtgraph as pg
from pyqtgraph import DateAxisItem
from qgis.PyQt.QtCore import QDate, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

try:
    from .i18n_helper import tr as _i18n_tr
    from .model_analysis import (
        ScenarioConfig,
        ScenarioResult,
        StressOverride,
        get_model_common_stress_range,
        get_model_freq,
        get_model_full_stress_range,
        get_stressmodel_inputs,
        has_parameter_covariance,
        is_model_solved,
        load_ensemble_csv,
        run_scenario_simulation,
    )
    from .plot_toolbar import PlotNavigationWidget, create_fill_between_item
except (ImportError, ValueError):
    from i18n_helper import tr as _i18n_tr
    from model_analysis import (
        ScenarioConfig,
        ScenarioResult,
        StressOverride,
        get_model_common_stress_range,
        get_model_freq,
        get_model_full_stress_range,
        get_stressmodel_inputs,
        has_parameter_covariance,
        is_model_solved,
        load_ensemble_csv,
        run_scenario_simulation,
    )
    from plot_toolbar import PlotNavigationWidget, create_fill_between_item


def _tr(message: str) -> str:
    return _i18n_tr(message)


SCENARIO_COLORS = [
    "#d62728",
    "#2ca02c",
    "#ff7f0e",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#17becf",
    "#bcbd22",
]


def _ts_to_qdate(ts: pd.Timestamp | None) -> QDate:
    if ts is None or pd.isna(ts):
        return QDate.currentDate()
    d = pd.Timestamp(ts).date()
    return QDate(d.year, d.month, d.day)


def _qdate_to_ts(qd: QDate) -> pd.Timestamp:
    return pd.Timestamp(qd.toString("yyyy-MM-dd"))


class ModelSimulationDialog(QDialog):
    """Interactive dialog to simulate a Pastas model over custom periods and stress scenarios."""

    # Emitted when the user chooses to store a simulated series as an oseries in the store
    save_series_requested = pyqtSignal(str, object)  # (series_name, pd.Series)

    def __init__(self, ml: ps.Model, store=None, parent=None):
        super().__init__(parent)
        self.ml = ml
        self.store = store
        self.setWindowTitle(_tr("Simulate / Scenarios: {0}").format(ml.name))
        self.resize(1320, 860)

        self.stress_inputs = get_stressmodel_inputs(ml)
        self.available_stresses = self._get_available_stresses()
        self.baseline_result: ScenarioResult | None = None
        self.scenarios: list[tuple[ScenarioConfig, ScenarioResult]] = []
        self._override_rows: list[dict] = []
        self._sm_enable_checks: dict[str, QCheckBox] = {}
        self._scenario_counter = 1

        self._init_ui()
        self._run_baseline_and_plot()

    # ------------------------------------------------------------------
    # Store helpers
    # ------------------------------------------------------------------

    def _get_available_stresses(self) -> list[str]:
        if self.store is None or not hasattr(self.store, "stresses"):
            return []
        try:
            stresses = list(self.store.stresses.index)
        except Exception:
            return []

        # Sort by distance to model oseries if coordinates are present
        try:
            oseries_name = getattr(self.ml.oseries, "name", None)
            if (
                oseries_name
                and hasattr(self.store, "oseries")
                and oseries_name in self.store.oseries.index
            ):
                ox = float(self.store.oseries.loc[oseries_name, "x"])
                oy = float(self.store.oseries.loc[oseries_name, "y"])
                if np.isfinite(ox) and np.isfinite(oy):
                    def _dist(sname):
                        try:
                            sx = float(self.store.stresses.loc[sname, "x"])
                            sy = float(self.store.stresses.loc[sname, "y"])
                            if np.isfinite(sx) and np.isfinite(sy):
                                return float(np.hypot(sx - ox, sy - oy))
                        except Exception:
                            pass
                        return float("inf")

                    stresses.sort(key=_dist)
        except Exception:
            pass
        return stresses

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
                    "Note: This model is not solved yet. Simulations will use initial parameters."
                )
            )
            banner.setStyleSheet(
                "background: #fff3cd; color: #664d03; padding: 6px; border: 1px solid #ffecb5;"
            )
            root_layout.addWidget(banner)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter, 1)

        # ---- Left pane: Configuration ----
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(8)

        # 1. Period & Options
        grp_period = QGroupBox(_tr("Simulation Period & Settings"))
        form_period = QFormLayout(grp_period)

        cal_tmin = self.ml.settings.get("tmin")
        cal_tmax = self.ml.settings.get("tmax")
        common_tmin, common_tmax = get_model_common_stress_range(self.ml)

        self.de_tmin = QDateEdit()
        self.de_tmin.setCalendarPopup(True)
        self.de_tmin.setDisplayFormat("yyyy-MM-dd")
        self.de_tmin.setMinimumDate(QDate(1900, 1, 1))
        self.de_tmin.setMaximumDate(QDate(2150, 12, 31))
        self.de_tmin.setDate(_ts_to_qdate(cal_tmin or common_tmin))

        self.de_tmax = QDateEdit()
        self.de_tmax.setCalendarPopup(True)
        self.de_tmax.setDisplayFormat("yyyy-MM-dd")
        self.de_tmax.setMinimumDate(QDate(1900, 1, 1))
        self.de_tmax.setMaximumDate(QDate(2150, 12, 31))
        self.de_tmax.setDate(_ts_to_qdate(cal_tmax or common_tmax))

        preset_row = QHBoxLayout()
        btn_cal = QPushButton(_tr("Calibration"))
        btn_cal.setToolTip(_tr("Use model calibration tmin/tmax"))
        btn_cal.clicked.connect(self._preset_calibration_period)
        btn_common = QPushButton(_tr("All Stresses"))
        btn_common.setToolTip(_tr("Use full overlapping range of all stresses"))
        btn_common.clicked.connect(self._preset_common_stress_period)
        btn_extend = QPushButton(_tr("Extend End"))
        btn_extend.setToolTip(
            _tr("Keep calibration start and extend tmax to end of available stresses")
        )
        btn_extend.clicked.connect(self._preset_extend_end)
        preset_row.addWidget(btn_cal)
        preset_row.addWidget(btn_common)
        preset_row.addWidget(btn_extend)

        self.cbo_freq = QComboBox()
        self.cbo_freq.addItems(["D", "h", "7D", "14D", "30D"])
        self.cbo_freq.setEditable(True)
        self.cbo_freq.setCurrentText(get_model_freq(self.ml))

        self.chk_warmup = QCheckBox(_tr("Include Warmup Period"))
        self.chk_ci = QCheckBox(_tr("Show 95% Confidence Interval"))
        has_cov = has_parameter_covariance(self.ml)
        self.chk_ci.setEnabled(has_cov)
        if not has_cov:
            self.chk_ci.setToolTip(
                _tr("Parameter covariance (pcov) is not available for this model")
            )

        form_period.addRow(_tr("Tmin:"), self.de_tmin)
        form_period.addRow(_tr("Tmax:"), self.de_tmax)
        form_period.addRow(_tr("Presets:"), preset_row)
        form_period.addRow(_tr("Frequency:"), self.cbo_freq)
        form_period.addRow("", self.chk_warmup)
        form_period.addRow("", self.chk_ci)
        left_layout.addWidget(grp_period)

        # 2. Active Stressmodels
        grp_sms = QGroupBox(_tr("Active Stressmodels"))
        sms_layout = QVBoxLayout(grp_sms)
        for sm_name, sm in self.ml.stressmodels.items():
            chk = QCheckBox(f"{sm_name} ({sm.__class__.__name__})")
            chk.setChecked(True)
            self._sm_enable_checks[sm_name] = chk
            sms_layout.addWidget(chk)
        left_layout.addWidget(grp_sms)

        # 3. Stress Overrides
        grp_overrides = QGroupBox(_tr("Stress Overrides"))
        ov_layout = QVBoxLayout(grp_overrides)
        ov_layout.setSpacing(8)

        if not self.stress_inputs:
            ov_layout.addWidget(
                QLabel(_tr("This model has no external stress series inputs."))
            )
        else:
            for inp in self.stress_inputs:
                row_box = QGroupBox(f"{inp.sm_name}.{inp.arg_name}  ({inp.stress_name})")
                row_form = QFormLayout(row_box)
                row_form.setContentsMargins(6, 6, 6, 6)
                row_form.setSpacing(4)

                range_str = (
                    f"{inp.tmin.strftime('%Y-%m-%d')} → {inp.tmax.strftime('%Y-%m-%d')}"
                    if inp.tmin is not None and inp.tmax is not None
                    else "-"
                )
                lbl_rng = QLabel(range_str)
                lbl_rng.setStyleSheet("color: gray; font-size: 11px;")
                row_form.addRow(_tr("Current range:"), lbl_rng)

                cbo_mode = QComboBox()
                cbo_mode.addItem(_tr("Keep Original"), "original")
                cbo_mode.addItem(_tr("Store Stress"), "store")
                cbo_mode.addItem(_tr("Constant Value"), "constant")
                cbo_mode.addItem(_tr("Load from CSV"), "series")

                cbo_store = QComboBox()
                cbo_store.addItems(self.available_stresses)
                if inp.stress_name in self.available_stresses:
                    cbo_store.setCurrentText(inp.stress_name)
                cbo_store.setVisible(False)

                spn_const = QDoubleSpinBox()
                spn_const.setRange(-1e9, 1e9)
                spn_const.setDecimals(4)
                spn_const.setValue(0.0)
                spn_const.setVisible(False)

                csv_widget = QWidget()
                csv_hbox = QHBoxLayout(csv_widget)
                csv_hbox.setContentsMargins(0, 0, 0, 0)
                btn_csv = QPushButton(_tr("Browse..."))
                lbl_csv = QLabel(_tr("No file"))
                lbl_csv.setStyleSheet("color: gray;")
                csv_hbox.addWidget(btn_csv)
                csv_hbox.addWidget(lbl_csv, 1)
                csv_widget.setVisible(False)

                # Scale & offset row
                transform_row = QHBoxLayout()
                spn_scale = QDoubleSpinBox()
                spn_scale.setRange(-1000.0, 1000.0)
                spn_scale.setDecimals(3)
                spn_scale.setSingleStep(0.1)
                spn_scale.setValue(1.0)
                spn_offset = QDoubleSpinBox()
                spn_offset.setRange(-1e6, 1e6)
                spn_offset.setDecimals(4)
                spn_offset.setValue(0.0)
                transform_row.addWidget(QLabel(_tr("Scale:")))
                transform_row.addWidget(spn_scale)
                transform_row.addWidget(QLabel(_tr("Offset:")))
                transform_row.addWidget(spn_offset)

                # Splice date row
                splice_row = QHBoxLayout()
                chk_splice = QCheckBox(_tr("Apply from:"))
                de_splice = QDateEdit()
                de_splice.setCalendarPopup(True)
                de_splice.setDisplayFormat("yyyy-MM-dd")
                de_splice.setMinimumDate(QDate(1900, 1, 1))
                de_splice.setMaximumDate(QDate(2150, 12, 31))
                de_splice.setDate(_ts_to_qdate(cal_tmax or inp.tmax))
                de_splice.setEnabled(False)
                chk_splice.toggled.connect(de_splice.setEnabled)
                splice_row.addWidget(chk_splice)
                splice_row.addWidget(de_splice, 1)

                row_info = {
                    "input": inp,
                    "cbo_mode": cbo_mode,
                    "cbo_store": cbo_store,
                    "spn_const": spn_const,
                    "csv_widget": csv_widget,
                    "lbl_csv": lbl_csv,
                    "custom_series": None,
                    "spn_scale": spn_scale,
                    "spn_offset": spn_offset,
                    "chk_splice": chk_splice,
                    "de_splice": de_splice,
                }

                def _make_mode_handler(ri):
                    def _on_mode_change(_idx):
                        mode = ri["cbo_mode"].currentData()
                        ri["cbo_store"].setVisible(mode == "store")
                        ri["spn_const"].setVisible(mode == "constant")
                        ri["csv_widget"].setVisible(mode == "series")

                    return _on_mode_change

                def _make_csv_handler(ri):
                    def _on_browse():
                        fname, _ = QFileDialog.getOpenFileName(
                            self,
                            _tr("Select Stress Series CSV"),
                            "",
                            "Data Files (*.csv *.parquet *.xlsx *.xls);;All Files (*)",
                        )
                        if not fname:
                            return
                        try:
                            df = load_ensemble_csv(fname)
                            ri["custom_series"] = df.iloc[:, 0]
                            ri["lbl_csv"].setText(os.path.basename(fname))
                            ri["lbl_csv"].setToolTip(fname)
                        except Exception as exc:
                            QMessageBox.warning(
                                self,
                                _tr("CSV Error"),
                                _tr("Could not read stress file: {0}").format(str(exc)),
                            )

                    return _on_browse

                cbo_mode.currentIndexChanged.connect(_make_mode_handler(row_info))
                btn_csv.clicked.connect(_make_csv_handler(row_info))

                row_form.addRow(_tr("Source:"), cbo_mode)
                row_form.addRow("", cbo_store)
                row_form.addRow("", spn_const)
                row_form.addRow("", csv_widget)
                row_form.addRow(_tr("Transform:"), transform_row)
                row_form.addRow("", splice_row)

                self._override_rows.append(row_info)
                ov_layout.addWidget(row_box)

        left_layout.addWidget(grp_overrides)

        # 4. Scenario Controls
        grp_scen = QGroupBox(_tr("Scenarios"))
        scen_layout = QVBoxLayout(grp_scen)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(_tr("Name:")))
        self.le_scenario_name = QLineEdit(f"Scenario {self._scenario_counter}")
        name_row.addWidget(self.le_scenario_name, 1)
        scen_layout.addLayout(name_row)

        btn_row = QHBoxLayout()
        self.btn_run_scenario = QPushButton(_tr("Run Scenario"))
        self.btn_run_scenario.clicked.connect(self.run_current_scenario)
        self.btn_remove_scenario = QPushButton(_tr("Remove"))
        self.btn_remove_scenario.clicked.connect(self.remove_selected_scenario)
        self.btn_reset = QPushButton(_tr("Reset"))
        self.btn_reset.clicked.connect(self.reset_overrides)
        btn_row.addWidget(self.btn_run_scenario)
        btn_row.addWidget(self.btn_remove_scenario)
        btn_row.addWidget(self.btn_reset)
        scen_layout.addLayout(btn_row)

        self.list_scenarios = QListWidget()
        self.list_scenarios.setMaximumHeight(130)
        self.list_scenarios.itemChanged.connect(lambda _item: self._update_plots())
        scen_layout.addWidget(self.list_scenarios)

        left_layout.addWidget(grp_scen)
        left_layout.addStretch()

        left_scroll.setWidget(left_widget)
        left_scroll.setMinimumWidth(360)
        splitter.addWidget(left_scroll)

        # ---- Right pane: Plots & Export ----
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 4, 4, 4)

        top_bar = QHBoxLayout()
        self.plot_nav = PlotNavigationWidget(parent=self)
        top_bar.addWidget(self.plot_nav)

        self.chk_show_diff = QCheckBox(_tr("Show Difference vs Baseline"))
        self.chk_show_diff.setChecked(True)
        self.chk_show_diff.toggled.connect(self._update_plots)
        top_bar.addWidget(self.chk_show_diff)

        top_bar.addStretch()

        self.btn_export_csv = QPushButton(_tr("Export CSV"))
        self.btn_export_csv.clicked.connect(self.export_csv)
        top_bar.addWidget(self.btn_export_csv)

        self.btn_save_oseries = QPushButton(_tr("Save as Oseries"))
        self.btn_save_oseries.setEnabled(self.store is not None)
        self.btn_save_oseries.clicked.connect(self.save_simulation_to_store)
        top_bar.addWidget(self.btn_save_oseries)

        right_layout.addLayout(top_bar)

        self.win = pg.GraphicsLayoutWidget()
        self.win.setBackground("w")
        right_layout.addWidget(self.win, 1)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setWordWrap(True)
        right_layout.addWidget(self.lbl_summary)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

    # ------------------------------------------------------------------
    # Presets & Config Collection
    # ------------------------------------------------------------------

    def _preset_calibration_period(self):
        cal_tmin = self.ml.settings.get("tmin")
        cal_tmax = self.ml.settings.get("tmax")
        if cal_tmin is not None:
            self.de_tmin.setDate(_ts_to_qdate(cal_tmin))
        if cal_tmax is not None:
            self.de_tmax.setDate(_ts_to_qdate(cal_tmax))

    def _preset_common_stress_period(self):
        tmin, tmax = get_model_common_stress_range(self.ml)
        if tmin is not None:
            self.de_tmin.setDate(_ts_to_qdate(tmin))
        if tmax is not None:
            self.de_tmax.setDate(_ts_to_qdate(tmax))

    def _preset_extend_end(self):
        cal_tmin = self.ml.settings.get("tmin")
        _, max_tmax = get_model_full_stress_range(self.ml)
        if cal_tmin is not None:
            self.de_tmin.setDate(_ts_to_qdate(cal_tmin))
        if max_tmax is not None:
            self.de_tmax.setDate(_ts_to_qdate(max_tmax))

    def reset_overrides(self):
        self._preset_calibration_period()
        for chk in self._sm_enable_checks.values():
            chk.setChecked(True)
        for ri in self._override_rows:
            ri["cbo_mode"].setCurrentIndex(0)
            ri["spn_scale"].setValue(1.0)
            ri["spn_offset"].setValue(0.0)
            ri["chk_splice"].setChecked(False)
            ri["custom_series"] = None
            ri["lbl_csv"].setText(_tr("No file"))

    def _collect_config(self) -> ScenarioConfig:
        name = self.le_scenario_name.text().strip() or f"Scenario {self._scenario_counter}"
        disabled = [
            sm_name
            for sm_name, chk in self._sm_enable_checks.items()
            if not chk.isChecked()
        ]
        overrides: list[StressOverride] = []
        for ri in self._override_rows:
            inp = ri["input"]
            overrides.append(
                StressOverride(
                    sm_name=inp.sm_name,
                    arg_name=inp.arg_name,
                    index=inp.index,
                    mode=ri["cbo_mode"].currentData(),
                    store_stress_name=ri["cbo_store"].currentText() or None,
                    constant_value=float(ri["spn_const"].value()),
                    custom_series=ri["custom_series"],
                    scale=float(ri["spn_scale"].value()),
                    offset=float(ri["spn_offset"].value()),
                    apply_from=(
                        _qdate_to_ts(ri["de_splice"].date())
                        if ri["chk_splice"].isChecked()
                        else None
                    ),
                )
            )
        return ScenarioConfig(
            name=name,
            tmin=_qdate_to_ts(self.de_tmin.date()),
            tmax=_qdate_to_ts(self.de_tmax.date()),
            freq=self.cbo_freq.currentText().strip() or get_model_freq(self.ml),
            return_warmup=self.chk_warmup.isChecked(),
            disabled_stressmodels=disabled,
            overrides=overrides,
            compute_ci=self.chk_ci.isChecked(),
        )

    # ------------------------------------------------------------------
    # Execution & Plotting
    # ------------------------------------------------------------------

    def _run_baseline_and_plot(self):
        try:
            base_cfg = ScenarioConfig(
                name=_tr("Baseline"),
                tmin=self.ml.settings.get("tmin"),
                tmax=self.ml.settings.get("tmax"),
                freq=get_model_freq(self.ml),
                return_warmup=False,
            )
            self.baseline_result = run_scenario_simulation(
                self.ml, base_cfg, store=self.store
            )
        except Exception as exc:
            self.baseline_result = None
            self.lbl_summary.setText(
                _tr("Baseline simulation warning: {0}").format(str(exc))
            )
        self._update_plots()

    def run_current_scenario(self):
        cfg = self._collect_config()
        if cfg.tmax is not None and cfg.tmin is not None and pd.Timestamp(cfg.tmax) < pd.Timestamp(cfg.tmin):
            QMessageBox.warning(
                self,
                _tr("Invalid Period"),
                _tr("Tmax must be on or after Tmin."),
            )
            return

        # Recompute baseline over the requested window if possible for accurate diffing
        baseline_for_diff = (
            self.baseline_result.simulation if self.baseline_result is not None else None
        )
        try:
            ext_base_cfg = ScenarioConfig(
                name=_tr("Baseline"),
                tmin=cfg.tmin,
                tmax=cfg.tmax,
                freq=cfg.freq,
                return_warmup=cfg.return_warmup,
            )
            ext_base = run_scenario_simulation(self.ml, ext_base_cfg, store=self.store)
            baseline_for_diff = ext_base.simulation
        except Exception:
            pass

        try:
            result = run_scenario_simulation(
                self.ml,
                cfg,
                store=self.store,
                baseline_sim=baseline_for_diff,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                _tr("Simulation Error"),
                _tr("Failed to simulate scenario '{0}':\n{1}").format(cfg.name, str(exc)),
            )
            return

        # Replace scenario if same name exists, otherwise append
        existing_idx = next(
            (i for i, (c, _) in enumerate(self.scenarios) if c.name == cfg.name),
            None,
        )
        if existing_idx is not None:
            self.scenarios[existing_idx] = (cfg, result)
        else:
            self.scenarios.append((cfg, result))
            item = QListWidgetItem(cfg.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.list_scenarios.addItem(item)
            self._scenario_counter += 1
            self.le_scenario_name.setText(f"Scenario {self._scenario_counter}")

        if result.warnings:
            self.lbl_summary.setText(" | ".join(result.warnings))

        self._update_plots()

    def remove_selected_scenario(self):
        row = self.list_scenarios.currentRow()
        if row < 0 or row >= len(self.scenarios):
            return
        self.scenarios.pop(row)
        self.list_scenarios.takeItem(row)
        self._update_plots()

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

    def _update_plots(self):
        self.win.clear()
        plots = []

        p_main = self.win.addPlot(row=0, col=0, axisItems={"bottom": DateAxisItem()})
        p_main.setTitle(_tr("Simulation Scenarios — {0}").format(self.ml.name), color="k")
        p_main.showGrid(x=True, y=True, alpha=0.3)
        p_main.addLegend()
        for ax_name in ("left", "bottom"):
            ax = p_main.getAxis(ax_name)
            ax.setPen("k")
            ax.setTextPen("k")
        plots.append(p_main)

        # Observations
        try:
            obs = self.ml.observations()
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

        # Baseline
        if self.baseline_result is not None:
            bx, by = self._series_to_xy(self.baseline_result.simulation)
            if bx is not None:
                p_main.plot(
                    bx,
                    by,
                    pen=pg.mkPen("#1f77b4", width=2),
                    name=_tr("Baseline"),
                )

        # Scenarios
        visible_scenarios: list[tuple[int, ScenarioResult]] = []
        for idx, (_cfg, res) in enumerate(self.scenarios):
            item = self.list_scenarios.item(idx)
            if item is not None and item.checkState() != Qt.CheckState.Checked:
                continue
            visible_scenarios.append((idx, res))
            color = SCENARIO_COLORS[idx % len(SCENARIO_COLORS)]

            # Optional CI band
            if res.ci is not None and res.ci.shape[1] >= 2:
                lx, ly = self._series_to_xy(res.ci.iloc[:, 0])
                ux, uy = self._series_to_xy(res.ci.iloc[:, 1])
                if lx is not None and ux is not None and len(lx) == len(ux):
                    qcol = pg.mkColor(color)
                    qcol.setAlpha(45)
                    fill = create_fill_between_item(
                        pg, ux, uy, ly, brush=pg.mkBrush(qcol)
                    )
                    if fill is not None:
                        p_main.addItem(fill)

            sx, sy = self._series_to_xy(res.simulation)
            if sx is not None:
                p_main.plot(
                    sx,
                    sy,
                    pen=pg.mkPen(color, width=2),
                    name=res.name,
                )

        # Optional Difference plot
        if self.chk_show_diff.isChecked() and any(
            res.difference is not None for _, res in visible_scenarios
        ):
            p_diff = self.win.addPlot(row=1, col=0, axisItems={"bottom": DateAxisItem()})
            p_diff.setTitle(_tr("Difference vs Baseline (Scenario − Baseline)"), color="k")
            p_diff.showGrid(x=True, y=True, alpha=0.3)
            p_diff.addLegend()
            p_diff.setXLink(p_main)
            p_diff.addLine(y=0, pen=pg.mkPen("k", style=Qt.PenStyle.DashLine))
            for ax_name in ("left", "bottom"):
                ax = p_diff.getAxis(ax_name)
                ax.setPen("k")
                ax.setTextPen("k")

            for idx, res in visible_scenarios:
                if res.difference is None:
                    continue
                color = SCENARIO_COLORS[idx % len(SCENARIO_COLORS)]
                dx, dy = self._series_to_xy(res.difference)
                if dx is not None:
                    p_diff.plot(dx, dy, pen=pg.mkPen(color, width=1.8), name=res.name)
            plots.append(p_diff)
            self.win.ci.layout.setRowStretchFactor(0, 3)
            self.win.ci.layout.setRowStretchFactor(1, 1)

        self.plot_nav.set_plots(plots)

        # Summary stats text
        parts = []
        for _idx, res in visible_scenarios:
            s = res.simulation.dropna()
            if s.empty:
                continue
            txt = f"{res.name}: min={s.min():.3f}, mean={s.mean():.3f}, max={s.max():.3f}"
            if res.difference is not None and not res.difference.dropna().empty:
                d = res.difference.dropna()
                txt += f" | Δmean={d.mean():+.3f}, Δmax={d.abs().max():.3f}"
            parts.append(txt)
        if parts:
            self.lbl_summary.setText("   •   ".join(parts))

    # ------------------------------------------------------------------
    # Export & Save
    # ------------------------------------------------------------------

    def export_csv(self):
        cols = {}
        if self.baseline_result is not None:
            cols["Baseline"] = self.baseline_result.simulation
        for _cfg, res in self.scenarios:
            cols[res.name] = res.simulation
            if res.difference is not None:
                cols[f"{res.name}_diff"] = res.difference
        if not cols:
            return

        fname, _ = QFileDialog.getSaveFileName(
            self,
            _tr("Export Simulations to CSV"),
            f"{self.ml.name}_scenarios.csv",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not fname:
            return
        try:
            df = pd.DataFrame(cols)
            df.to_csv(fname)
            QMessageBox.information(
                self,
                _tr("Export Complete"),
                _tr("Saved simulation data to:\n{0}").format(fname),
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                _tr("Export Error"),
                _tr("Failed to export CSV: {0}").format(str(exc)),
            )

    def save_simulation_to_store(self):
        if not self.scenarios:
            QMessageBox.information(
                self,
                _tr("No Scenario"),
                _tr("Run at least one scenario before saving."),
            )
            return
        row = self.list_scenarios.currentRow()
        if row < 0 or row >= len(self.scenarios):
            row = len(self.scenarios) - 1
        cfg, res = self.scenarios[row]

        default_name = f"{self.ml.name}_{cfg.name}".replace(" ", "_")
        name, ok = QInputDialog.getText(
            self,
            _tr("Save Simulation as Oseries"),
            _tr("Oseries name:"),
            text=default_name,
        )
        if not ok or not name.strip():
            return
        self.save_series_requested.emit(name.strip(), res.simulation.copy())
