import numpy as np
import pandas as pd
import pastas as ps
import pyqtgraph as pg
from pyqtgraph import DateAxisItem
from qgis.core import QgsProject
from qgis.PyQt.QtCore import QEvent, Qt
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

        self.title_overhead = 32
        self.bottom_axis_overhead = 20
        self.spacing = 10
        self.y_axis_width = 40
        self._plot_ranges = []
        self._row_plots = []
        self._params_proxy = None
        self._applied_height = None
        self._time_xlim = None
        self._main_ylims = []
        self._side_xlims = []

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
        self.plot_nav = PlotNavigationWidget(on_full=self._reset_view_ranges, parent=self)
        self.toolbar_layout.addWidget(self.plot_nav)
        self.toolbar_layout.addStretch()
        self.main_layout.addLayout(self.toolbar_layout)

        # Graphics layout filling the dialog directly
        self.win = pg.GraphicsLayoutWidget()
        self.win.setBackground("w")
        self.win.setFrameShape(QFrame.Shape.NoFrame)
        self.win.ci.layout.setContentsMargins(0, 0, 0, 0)
        self.win.ci.layout.setSpacing(self.spacing)
        self.win.installEventFilter(self)
        self.main_layout.addWidget(self.win)

        self.plot_results()

    def eventFilter(self, obj, event):
        resize_type = getattr(QEvent, "Resize", None)
        if resize_type is None:
            resize_type = getattr(getattr(QEvent, "Type", None), "Resize", 14)
        if obj is getattr(self, "win", None) and int(event.type()) == int(resize_type):
            h = event.size().height()
            if h > 0:
                self._apply_row_heights(h)
        return super().eventFilter(obj, event)

    def _get_available_height(self):
        """Return the vertical pixel height available for the subplots.

        Before the dialog is shown, child widgets have not been laid out yet,
        so compute the exact plot area height from the dialog height and
        toolbar size hint beforehand.
        """
        if self.isVisible() and self.win.height() > 0:
            return self.win.height()
        m = self.main_layout.contentsMargins()
        toolbar_h = self.toolbar_layout.sizeHint().height() or 30
        layout_spacing = self.main_layout.spacing()
        if layout_spacing < 0:
            layout_spacing = 6
        return max(
            self.height() - toolbar_h - m.top() - m.bottom() - layout_spacing,
            200,
        )

    def _apply_row_heights(self, available_height=None):
        """Resize subplot rows and parameter table in place to fill the height."""
        if not self._plot_ranges or not self._row_plots:
            return
        if available_height is None:
            available_height = self._get_available_height()
        available_height = int(available_height)
        if available_height <= 0 or available_height == self._applied_height:
            return

        row_heights = calculate_subplot_heights(
            self._plot_ranges,
            available_height,
            title_overhead=self.title_overhead,
            bottom_axis_overhead=self.bottom_axis_overhead,
            spacing=self.spacing,
        )
        for plots_in_row, h in zip(self._row_plots, row_heights):
            for p in plots_in_row:
                p.setMinimumHeight(h)
                p.setMaximumHeight(h)

        if self._params_proxy is not None and len(row_heights) >= 2:
            proxy_h = row_heights[0] + row_heights[1] + self.spacing
            self._params_proxy.setMinimumHeight(0)
            self._params_proxy.setMaximumHeight(proxy_h)

        self._applied_height = available_height

    def _reset_view_ranges(self):
        """Restore tight x-limits and equal-scale y-limits across all subplots."""
        if self._row_plots:
            for row, ylim in zip(self._row_plots, self._main_ylims):
                row[0].setYRange(ylim[0], ylim[1], padding=0)
            if self._time_xlim is not None:
                self._row_plots[0][0].setXRange(
                    self._time_xlim[0], self._time_xlim[1], padding=0
                )
        for p_rf, xlim in self._side_xlims:
            vb = p_rf.getViewBox()
            vb.enableAutoRange(axis=vb.YAxis, enable=True)
            vb.autoRange(padding=0.02)
            if xlim is not None:
                p_rf.setXRange(xlim[0], xlim[1], padding=0)

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
        self._plot_ranges = []
        self._row_plots = []
        self._params_proxy = None
        self._applied_height = None
        self._time_xlim = None
        self._main_ylims = []
        self._side_xlims = []
        ml = self.ml

        Y_AXIS_WIDTH = self.y_axis_width

        # 1. Determine Y-limits for each plot
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
            return

        self._plot_ranges = [y[1] - y[0] if y[1] != y[0] else 0.001 for y in ylims]

        DEFAULT_COLOR = "#1f77b4"  # Matplotlib C0
        main_col_plots = []
        side_plots = []
        time_x_arrays = []
        self._main_ylims = list(ylims)

        # Row 0: Obs & Sim
        p1 = self.win.addPlot(row=0, col=0, axisItems={"bottom": DateAxisItem()})
        try:
            r2_val = ml.stats.rsq()
            p1.setTitle(f"Observations & Simulation (R²: {r2_val:.3f})", color="k")
        except Exception:
            p1.setTitle("Observations & Simulation (Not Solved)", color="k")
        p1.addLegend()
        p1.showGrid(x=True, y=True)
        p1.setYRange(ylims[0][0], ylims[0][1], padding=0)
        main_col_plots.append(p1)
        self._row_plots.append([p1])

        ox, oy = self._prepare_data(obs)
        if ox is not None and len(ox) > 0:
            time_x_arrays.append(ox)
            p1.plot(
                ox, oy, pen=None, symbol="o", symbolSize=3, symbolBrush="k", name="Obs"
            )
        sx, sy = self._prepare_data(sim)
        if sx is not None and len(sx) > 0:
            time_x_arrays.append(sx)
            p1.plot(sx, sy, pen=pg.mkPen(DEFAULT_COLOR, width=2), name="Sim")

        # Row 1: Residuals/Noise Plot
        p2 = self.win.addPlot(row=1, col=0, axisItems={"bottom": DateAxisItem()})
        p2_title = "Residuals & Noise" if noise is not None else "Residuals"
        p2.setTitle(p2_title, color="k")
        p2.showGrid(x=True, y=True)
        p2.setXLink(p1)
        p2.setYRange(ylims[1][0], ylims[1][1], padding=0)
        main_col_plots.append(p2)
        self._row_plots.append([p2])

        rx, ry = self._prepare_data(res)
        if rx is not None and len(rx) > 0:
            time_x_arrays.append(rx)
            res_color = "k" if noise is not None else DEFAULT_COLOR
            p2.plot(rx, ry, pen=pg.mkPen(res_color, width=1), name="Residuals")
        if noise is not None:
            nx, ny = self._prepare_data(noise)
            if nx is not None and len(nx) > 0:
                time_x_arrays.append(nx)
                p2.plot(nx, ny, pen=pg.mkPen(DEFAULT_COLOR, width=1), name="Noise")

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
        self._params_proxy = proxy

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
                stress_name = _get_stress_name(sm, istress)
                response_x = resp.index.values if resp is not None else None
                response_data = resp.values if resp is not None else None

                responses.append((sm_name, stress_name, response_x, response_data))

        # Now plot contributions and responses with consistent x-limits
        for i, contrib_series in enumerate(sm_contribs):
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
            p_sm.setYRange(ylims[row_idx][0], ylims[row_idx][1], padding=0)
            main_col_plots.append(p_sm)

            cx, cy = self._prepare_data(contrib_series)
            if cx is not None and len(cx) > 0:
                time_x_arrays.append(cx)
                p_sm.plot(cx, cy, pen=pg.mkPen(DEFAULT_COLOR, width=1.5))

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
            side_plots.append(p_rf)
            self._row_plots.append([p_sm, p_rf])

            side_xlim = None
            if response_data is not None and len(response_data) > 0:
                x_resp = (
                    response_x
                    if response_x is not None
                    else np.arange(len(response_data))
                )
                p_rf.plot(x_resp, response_data, pen=pg.mkPen(DEFAULT_COLOR, width=2))
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
                            side_xlim = (log_x_min, log_x_max)
                            p_rf.setXRange(log_x_min, log_x_max, padding=0)
                    else:
                        side_xlim = (x_min, x_max)
                        p_rf.setXRange(x_min, x_max, padding=0)
            self._side_xlims.append((p_rf, side_xlim))

        # Tight x-limits around the plotted time-series data across all linked time graphs
        if time_x_arrays:
            t_min = min(float(np.nanmin(arr)) for arr in time_x_arrays)
            t_max = max(float(np.nanmax(arr)) for arr in time_x_arrays)
            if np.isfinite(t_min) and np.isfinite(t_max) and t_min < t_max:
                self._time_xlim = (t_min, t_max)
                p1.setXRange(t_min, t_max, padding=0)

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

        self._apply_row_heights()


def _round_to_target(float_vals, target):
    """Round non-negative floats to integers summing to ``target`` (largest remainder)."""
    floors = [int(np.floor(v)) for v in float_vals]
    remainder = int(target) - sum(floors)
    if remainder > 0:
        order = sorted(
            range(len(float_vals)),
            key=lambda i: float_vals[i] - floors[i],
            reverse=True,
        )
        for i in order[:remainder]:
            floors[i] += 1
    elif remainder < 0:
        order = sorted(
            range(len(float_vals)),
            key=lambda i: float_vals[i] - floors[i],
        )
        for i in order[:-remainder]:
            if floors[i] > 1:
                floors[i] -= 1
    return floors


def calculate_subplot_heights(
    ranges,
    available_height,
    title_overhead=32,
    bottom_axis_overhead=20,
    spacing=10,
    min_row_height=45,
):
    """Calculate integer pixel heights for stacked subplots with equal vertical scale.

    Each row receives ``title_overhead`` (plus ``bottom_axis_overhead`` for the
    bottom subplot, which displays the shared x-axis) plus data height
    proportional to its y-range so all subplots share the same pixels-per-unit
    scale while filling ``available_height`` exactly.
    """
    n = len(ranges)
    if n == 0:
        return []

    total_spacing = max(n - 1, 0) * spacing
    target_rows_h = int(round(available_height)) - total_spacing
    if target_rows_h <= 0:
        return [1] * n

    overheads = [title_overhead] * (n - 1) + [title_overhead + bottom_axis_overhead]
    min_heights = [max(oh + 10, min_row_height) for oh in overheads]

    if target_rows_h <= sum(min_heights):
        total_min = sum(min_heights)
        scale = target_rows_h / total_min
        raw = [max(1.0, mh * scale) for mh in min_heights]
        return _round_to_target(raw, max(target_rows_h, n))

    clean_ranges = [float(r) if (np.isfinite(r) and r > 0) else 0.001 for r in ranges]

    fixed = {}
    while True:
        free = [i for i in range(n) if i not in fixed]
        rem_h = target_rows_h - sum(fixed.values()) - sum(overheads[i] for i in free)
        rem_range = sum(clean_ranges[i] for i in free)
        ppu = rem_h / rem_range if rem_range > 0 else 0.0
        newly_fixed = False
        for i in free:
            if overheads[i] + clean_ranges[i] * ppu < min_heights[i]:
                fixed[i] = float(min_heights[i])
                newly_fixed = True
        if not newly_fixed:
            float_heights = [
                fixed[i] if i in fixed else overheads[i] + clean_ranges[i] * ppu
                for i in range(n)
            ]
            break

    return _round_to_target(float_heights, target_rows_h)


def get_stats(series):
    if series is None or series.empty:
        return 0.0, 0.001
    return float(series.min()), float(series.max())


def _get_stress_name(sm, istress=0):
    """Safely obtain the stress name for a stressmodel and stress index across Pastas versions."""
    stresses = getattr(sm, "stresses", None)
    if stresses is not None:
        if isinstance(stresses, (list, tuple)) and istress < len(stresses):
            return getattr(stresses[istress], "name", None)
    try:
        stress = getattr(sm, "stress", None)
    except Exception:
        stress = None
    if stress is not None:
        if isinstance(stress, (list, tuple)) and istress < len(stress):
            return getattr(stress[istress], "name", None)
        elif istress == 0 and hasattr(stress, "name"):
            return stress.name
    return None

