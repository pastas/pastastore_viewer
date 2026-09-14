import numpy as np
import pandas as pd
import pastas as ps
import pyqtgraph as pg
from pyqtgraph import DateAxisItem
from qgis.core import QgsProject
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QAction,
    QDialog,
    QFrame,
    QGraphicsProxyWidget,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from .plot_toolbar import PlotNavigationWidget
except (ImportError, ValueError):
    from plot_toolbar import PlotNavigationWidget


class ResultsPlotDialog(QDialog):
    """Dialog to display model results using pyqtgraph, mimicking pastas.ml.plots.results()."""

    def __init__(self, ml: ps.Model, parent=None):
        super(ResultsPlotDialog, self).__init__(parent)
        self.setWindowTitle(f"Results: {ml.name}")
        self.resize(1200, 900)

        self.ml = ml
        # Settings state with QGIS Project persistence
        self.load_settings()

        self.overhead = 55
        self.spacing = 10
        self.margins = 10
        self.y_axis_width = 40

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(60)
        self._resize_timer.timeout.connect(self.plot_results)

        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.setLayout(self.main_layout)

        # Toolbar
        self.toolbar_layout = QHBoxLayout()
        self.settings_btn = QPushButton("Settings")
        self.settings_menu = QMenu(self)

        # Warmup Toggle
        warmup_action = QAction("Show Warmup", self, checkable=True)
        warmup_action.setChecked(self.show_warmup)
        warmup_action.triggered.connect(self.toggle_warmup)
        self.settings_menu.addAction(warmup_action)

        # Std Error Toggle
        stderr_action = QAction("Show Std Error", self, checkable=True)
        stderr_action.setChecked(self.show_stderr)
        stderr_action.triggered.connect(self.toggle_stderr)
        self.settings_menu.addAction(stderr_action)

        # Split Contributions Toggle
        split_action = QAction("Split Contributions", self, checkable=True)
        split_action.setChecked(self.split_contributions)
        split_action.triggered.connect(self.toggle_split_contributions)
        self.settings_menu.addAction(split_action)

        # Block Response Toggle
        block_action = QAction("Show Block Response", self, checkable=True)
        block_action.setChecked(self.show_block_response)
        block_action.triggered.connect(self.toggle_block_response)
        self.settings_menu.addAction(block_action)

        self.settings_btn.setMenu(self.settings_menu)
        self.toolbar_layout.addWidget(self.settings_btn)
        self.plot_nav = PlotNavigationWidget(parent=self)
        self.toolbar_layout.addWidget(self.plot_nav)
        self.toolbar_layout.addStretch()
        self.main_layout.addLayout(self.toolbar_layout)

        # Scroll Area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(0)

        self.win = pg.GraphicsLayoutWidget()
        self.win.setBackground("w")
        self.win.ci.layout.setContentsMargins(0, 0, 0, 0)
        self.win.ci.layout.setSpacing(self.spacing)
        self.scroll_layout.addWidget(self.win)
        self.scroll.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll)

        self.plot_results()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_resize_timer"):
            self._resize_timer.start()

    def load_settings(self):
        proj = QgsProject.instance()
        self.show_warmup = proj.readBoolEntry(
            "PastastoreViewer", "results_show_warmup", False
        )[0]
        self.show_stderr = proj.readBoolEntry(
            "PastastoreViewer", "results_show_stderr", False
        )[0]
        self.split_contributions = proj.readBoolEntry(
            "PastastoreViewer", "results_split_contributions", False
        )[0]
        self.show_block_response = proj.readBoolEntry(
            "PastastoreViewer", "results_show_block_response", False
        )[0]

    def save_settings(self):
        proj = QgsProject.instance()
        proj.writeEntry("PastastoreViewer", "results_show_warmup", self.show_warmup)
        proj.writeEntry("PastastoreViewer", "results_show_stderr", self.show_stderr)
        proj.writeEntry(
            "PastastoreViewer", "results_split_contributions", self.split_contributions
        )
        proj.writeEntry(
            "PastastoreViewer", "results_show_block_response", self.show_block_response
        )

    def toggle_warmup(self, checked):
        self.show_warmup = checked
        self.save_settings()
        self.plot_results()

    def toggle_stderr(self, checked):
        self.show_stderr = checked
        self.save_settings()
        self.plot_results()

    def toggle_split_contributions(self, checked):
        self.split_contributions = checked
        self.save_settings()
        self.plot_results()

    def toggle_block_response(self, checked):
        self.show_block_response = checked
        self.save_settings()
        self.plot_results()

    def _prepare_data(self, series):
        if series is None or series.empty:
            return None, None

        if not self.show_warmup:
            warmup = self.ml.settings.get("warmup", 0)
            is_warmup = False
            if isinstance(warmup, bool):
                is_warmup = warmup
            elif isinstance(warmup, (int, float)):
                is_warmup = warmup > 0
            elif isinstance(warmup, (pd.Timedelta, np.timedelta64)):
                is_warmup = warmup.total_seconds() > 0

            if is_warmup:
                tmin = self.ml.settings.get("tmin")
                if tmin:
                    series = series.loc[tmin:]

        if series.empty:
            return None, None

        x = series.index.astype("datetime64[s]").astype(np.int64)
        y = series.values
        mask = ~np.isnan(y)
        return x[mask], y[mask]

    def plot_results(self):
        self.win.clear()
        ml = self.ml

        OVERHEAD = self.overhead
        SPACING = self.spacing
        MARGINS = self.margins
        Y_AXIS_WIDTH = self.y_axis_width

        # 1. Determine Y-limits for each plot
        sm_names = list(ml.stressmodels.keys())
        ylims = []

        # Helper to get range respecting warmup
        def get_series_stats_local(series):
            if not self.show_warmup:
                tmin = ml.settings.get("tmin")
                if tmin and not series.empty:
                    series = series.loc[tmin:]
            return get_stats(series)

        # Plot 0: Obs & Sim
        obs = ml.observations()
        sim = ml.simulate(return_warmup=self.show_warmup)
        omin, omax = get_series_stats_local(obs)
        smin, smax = get_series_stats_local(sim)
        ylims.append((min(omin, smin), max(omax, smax)))

        # Plot 1: Residuals & Noise
        res = ml.residuals()
        noise = None if ml.noisemodel is None else ml.noise()
        rmin, rmax = get_series_stats_local(res)
        if noise is not None:
            nmin, nmax = get_series_stats_local(noise)
            ylims.append((min(rmin, nmin), max(rmax, nmax)))
        else:
            ylims.append((rmin, rmax))

        # Plot 2+: Contributions
        sm_contribs = ml.get_contributions(
            return_warmup=self.show_warmup, split=self.split_contributions
        )
        for c in sm_contribs:
            ylims.append(get_series_stats_local(c))

        if not ylims:
            p = self.win.addPlot(row=0, col=0)
            p.setTitle("No data to display", color="r")
            self.win.setMinimumHeight(100)
            self.win.setMaximumHeight(100)
            return

        ranges = [y[1] - y[0] if y[1] != y[0] else 0.001 for y in ylims]
        total_data_range = sum(ranges)
        num_plots = len(ylims)

        # Use actual viewport height if available (after first show),
        # else fall back to dialog height minus toolbar (resize(1200,900) is set in __init__).
        viewport_h = self.scroll.viewport().height()
        if viewport_h < 50:
            toolbar_h = self.toolbar_layout.sizeHint().height() or 30
            m = self.main_layout.contentsMargins()
            viewport_h = max(self.height() - toolbar_h - m.top() - m.bottom() - 15, 200)

        total_overhead = (
            num_plots * OVERHEAD + max(num_plots - 1, 0) * SPACING + MARGINS
        )
        available_data_h = max(viewport_h - total_overhead, num_plots * 5)
        ppu = available_data_h / total_data_range if total_data_range > 0 else 50.0

        # Float heights — equal ppu guarantees equal vertical scale
        float_heights = [r * ppu + OVERHEAD for r in ranges]
        # Absorb any rounding gap in the last row so total == viewport_h exactly
        raw_sum = sum(float_heights) + max(num_plots - 1, 0) * SPACING + MARGINS
        float_heights[-1] += viewport_h - raw_sum
        row_heights = [max(30, int(round(h))) for h in float_heights]
        # After rounding, fix residual to last row
        rounded_sum = sum(row_heights) + max(num_plots - 1, 0) * SPACING + MARGINS
        row_heights[-1] += viewport_h - rounded_sum

        sm_colors = [
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
        h_list = []
        main_col_plots = []
        side_plots = []

        # Row 0: Obs & Sim
        p1 = self.win.addPlot(row=0, col=0, axisItems={"bottom": DateAxisItem()})
        try:
            r2_val = ml.stats.rsq()
            p1.setTitle(f"Observations & Simulation (R²: {r2_val:.3f})", color="k")
        except:
            p1.setTitle("Observations & Simulation (Not Solved)", color="k")
        p1.addLegend()
        p1.showGrid(x=True, y=True)
        h1 = row_heights[0]
        p1.setMinimumHeight(h1)
        p1.setMaximumHeight(h1)
        p1.setYRange(ylims[0][0], ylims[0][1], padding=0)
        h_list.append(h1)
        main_col_plots.append(p1)

        ox, oy = self._prepare_data(obs)
        if ox is not None:
            p1.plot(
                ox, oy, pen=None, symbol="o", symbolSize=3, symbolBrush="k", name="Obs"
            )
        sx, sy = self._prepare_data(sim)
        if sx is not None:
            p1.plot(sx, sy, pen=pg.mkPen("#1f77b4", width=2), name="Sim")

        # Row 1: Residuals/Noise Plot
        p2 = self.win.addPlot(row=1, col=0, axisItems={"bottom": DateAxisItem()})
        p2_title = "Residuals & Noise" if noise is not None else "Residuals"
        p2.setTitle(p2_title, color="k")
        p2.showGrid(x=True, y=True)
        p2.setXLink(p1)
        h2 = row_heights[1]
        p2.setMinimumHeight(h2)
        p2.setMaximumHeight(h2)
        p2.setYRange(ylims[1][0], ylims[1][1], padding=0)
        h_list.append(h2)
        main_col_plots.append(p2)

        rx, ry = self._prepare_data(res)
        if rx is not None:
            p2.plot(rx, ry, pen=pg.mkPen("k", width=1), name="Residuals")
        if noise is not None:
            nx, ny = self._prepare_data(noise)
            if nx is not None:
                p2.plot(nx, ny, pen=pg.mkPen("orange", width=1), name="Noise")

        # Row 0-1, Col 1: Parameters Table
        table_container = QWidget()
        table_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        table_container_layout = QVBoxLayout(table_container)
        table_container_layout.setContentsMargins(Y_AXIS_WIDTH, 0, 0, 0)

        params_table = QTableWidget()
        params = ml.parameters

        headers = ["Parameter", "Optimal"]
        if self.show_stderr:
            headers.append("Std Error")

        params_table.setRowCount(len(params))
        params_table.setColumnCount(len(headers))
        params_table.setHorizontalHeaderLabels(headers)

        for i, (idx, row) in enumerate(params.iterrows()):
            params_table.setItem(i, 0, QTableWidgetItem(str(idx)))
            val_str = f"{row['optimal']:.4f}" if not np.isnan(row["optimal"]) else "-"
            params_table.setItem(i, 1, QTableWidgetItem(val_str))
            if self.show_stderr:
                stderr = row.get("stderr", np.nan)
                err_str = f"{stderr:.4f}" if not np.isnan(stderr) else "-"
                params_table.setItem(i, 2, QTableWidgetItem(err_str))

        params_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        params_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        params_table.setStyleSheet("background-color: white; gridline-color: #ddd;")

        table_container_layout.addWidget(params_table)

        proxy = QGraphicsProxyWidget()
        proxy.setWidget(table_container)
        self.win.addItem(proxy, row=0, col=1, rowspan=2)
        proxy.setMinimumWidth(0)
        proxy.setMaximumWidth(
            350 + Y_AXIS_WIDTH if not self.show_stderr else 450 + Y_AXIS_WIDTH
        )

        # Rows 2+: Contributions and Step/Block Responses
        # Get contribution names to match with series
        contrib_names = [c.name for c in sm_contribs]

        # Pre-calculate all responses for plotting
        responses = []
        response_type = "block" if self.show_block_response else "step"
        add_zero = not self.show_block_response

        for sm_name, sm in self.ml.stressmodels.items():
            # plot the contribution
            nsplit = sm.nsplit if self.split_contributions else 1
            if nsplit == 0:
                nsplit = 1
            for istress in range(nsplit):
                resp = ml._get_response(
                    block_or_step=response_type,
                    name=sm_name,
                    add_0=add_zero,
                    istress=istress,
                )
                if (
                    hasattr(sm, "stress")
                    and sm.stress is not None
                    and istress < len(sm.stress)
                ):
                    stress_name = sm.stress[istress].name
                else:
                    stress_name = None
                response_x = resp.index.values if resp is not None else None
                response_data = resp.values if resp is not None else None

                responses.append((sm_name, stress_name, response_x, response_data))

        # Now plot contributions and responses with consistent x-limits
        for i, contrib_series in enumerate(sm_contribs):
            color = sm_colors[i % len(sm_colors)]
            row_idx = i + 2
            contrib_name = contrib_names[i]
            if i < len(responses):
                sm_name, stress_name, response_x, response_data = responses[i]
            else:
                sm_name, stress_name, response_x, response_data = None, None, None, None

            p_sm = self.win.addPlot(
                row=row_idx, col=0, axisItems={"bottom": DateAxisItem()}
            )
            p_sm.setTitle(f"Contribution: {contrib_name}", color="k")
            p_sm.showGrid(x=True, y=True)
            p_sm.setXLink(p1)
            h_sm = row_heights[row_idx]
            p_sm.setMinimumHeight(h_sm)
            p_sm.setMaximumHeight(h_sm)
            p_sm.setYRange(ylims[row_idx][0], ylims[row_idx][1], padding=0)
            h_list.append(h_sm)
            main_col_plots.append(p_sm)

            cx, cy = self._prepare_data(contrib_series)
            if cx is not None:
                p_sm.plot(cx, cy, pen=pg.mkPen(color, width=1.5))

            # Response plot (step or block)
            p_rf = self.win.addPlot(row=row_idx, col=1)
            response_title = (
                "Block Response" if self.show_block_response else "Step Response"
            )
            if stress_name:
                p_rf.setTitle(f"{response_title}: {sm_name} ({stress_name})", color="k")
            else:
                p_rf.setTitle(f"{response_title}: {sm_name}", color="k")
            p_rf.showGrid(x=True, y=True)
            if self.show_block_response:
                p_rf.setLogMode(x=True, y=False)
            p_rf.setMinimumHeight(h_sm)
            p_rf.setMaximumHeight(h_sm)
            side_plots.append(p_rf)

            if response_data is not None and len(response_data) > 0:
                x_resp = (
                    response_x
                    if response_x is not None
                    else np.arange(len(response_data))
                )
                p_rf.plot(x_resp, response_data, pen=pg.mkPen(color, width=2))
                # Tight x-limits around the data
                x_min = float(np.nanmin(x_resp))
                x_max = float(np.nanmax(x_resp))
                if np.isfinite(x_min) and np.isfinite(x_max) and x_min < x_max:
                    if self.show_block_response:
                        x_arr = np.asarray(x_resp)
                        mask = x_arr > 0
                        if np.any(mask):
                            log_x_min = float(np.log10(np.nanmin(x_arr[mask])))
                            log_x_max = float(np.log10(np.nanmax(x_arr[mask])))
                            p_rf.setXRange(log_x_min, log_x_max, padding=0)
                    else:
                        p_rf.setXRange(x_min, x_max, padding=0)

        # Set win to exactly fill the viewport — no empty space, no extra scroll
        win_height = sum(row_heights) + max(num_plots - 1, 0) * SPACING + MARGINS
        self.win.setMinimumHeight(win_height)
        self.win.setMaximumHeight(win_height)
        self.win.ci.layout.setColumnStretchFactor(0, 3)
        self.win.ci.layout.setColumnStretchFactor(1, 1)

        self._all_plots = main_col_plots + side_plots
        self.plot_nav.set_plots(self._all_plots)
        for p in self._all_plots:
            p.getAxis("left").setWidth(Y_AXIS_WIDTH)
            for axis in ["bottom", "left"]:
                ax = p.getAxis(axis)
                ax.setPen("k")
                ax.setTextPen("k")

        if main_col_plots:
            for i, p in enumerate(main_col_plots):
                if i < len(main_col_plots) - 1:
                    ax = p.getAxis("bottom")
                    ax.setStyle(showValues=False)
                    ax.setHeight(0)


def get_stats(series):
    if series is None or series.empty:
        return 0.0, 0.001
    return float(series.min()), float(series.max())
