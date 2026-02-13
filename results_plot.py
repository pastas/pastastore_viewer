from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QWidget, QScrollArea, 
    QTableWidget, QTableWidgetItem, QHeaderView, QGraphicsProxyWidget,
    QPushButton, QHBoxLayout, QMenu, QAction
)
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject
import pyqtgraph as pg
from pyqtgraph import DateAxisItem
import numpy as np
import pandas as pd
import pastas as ps

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
        self.pixels_per_unit = 300 
        
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
        
        self.settings_btn.setMenu(self.settings_menu)
        self.toolbar_layout.addWidget(self.settings_btn)
        self.toolbar_layout.addStretch()
        self.main_layout.addLayout(self.toolbar_layout)
        
        # Scroll Area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(0)
        
        self.win = pg.GraphicsLayoutWidget()
        self.win.setBackground('w')
        self.scroll_layout.addWidget(self.win)
        self.scroll.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll)
        
        self.plot_results()

    def load_settings(self):
        proj = QgsProject.instance()
        self.show_warmup = proj.readBoolEntry("PastastoreViewer", "results_show_warmup", False)[0]
        self.show_stderr = proj.readBoolEntry("PastastoreViewer", "results_show_stderr", False)[0]

    def save_settings(self):
        proj = QgsProject.instance()
        proj.writeEntry("PastastoreViewer", "results_show_warmup", self.show_warmup)
        proj.writeEntry("PastastoreViewer", "results_show_stderr", self.show_stderr)

    def toggle_warmup(self, checked):
        self.show_warmup = checked
        self.save_settings()
        self.plot_results()

    def toggle_stderr(self, checked):
        self.show_stderr = checked
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
            
        x = series.index.view(np.int64) // 10**9
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
        noise = ml.noise() if ml.settings["noise"] else None
        rmin, rmax = get_series_stats_local(res)
        if noise is not None:
            nmin, nmax = get_series_stats_local(noise)
            ylims.append((min(rmin, nmin), max(rmax, nmax)))
        else:
            ylims.append((rmin, rmax))
            
        # Plot 2+: Contributions
        sm_contribs = ml.get_contributions(return_warmup=self.show_warmup)
        for c in sm_contribs:
            ylims.append(get_series_stats_local(c))
            
        ranges = [y[1] - y[0] if y[1] != y[0] else 0.001 for y in ylims]
        total_data_range = sum(ranges)
        num_plots = len(ylims)
        total_overhead = (num_plots * OVERHEAD) + ((num_plots - 1) * SPACING) + MARGINS
        
        available_data_height = (self.height() - 100) - total_overhead
        pixels_per_unit = max(100, min(available_data_height / total_data_range, 2000))
        
        sm_colors = ['#1f77b4', '#2ca02c', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
        h_list = []
        main_col_plots = []
        side_plots = []
        
        # Row 0: Obs & Sim
        p1 = self.win.addPlot(row=0, col=0, axisItems={'bottom': DateAxisItem()})
        try:
             r2_val = ml.stats.rsq()
             p1.setTitle(f"Observations & Simulation (R²: {r2_val:.3f})")
        except:
             p1.setTitle("Observations & Simulation (Not Solved)")
        p1.addLegend()
        p1.showGrid(x=True, y=True)
        h1 = int(ranges[0] * pixels_per_unit) + OVERHEAD
        p1.setMinimumHeight(h1)
        p1.setMaximumHeight(h1)
        p1.setYRange(ylims[0][0], ylims[0][1], padding=0)
        h_list.append(h1)
        main_col_plots.append(p1)
        
        ox, oy = self._prepare_data(obs)
        if ox is not None:
            p1.plot(ox, oy, pen=None, symbol='o', symbolSize=3, symbolBrush='k', name="Obs")
        sx, sy = self._prepare_data(sim)
        if sx is not None:
            p1.plot(sx, sy, pen=pg.mkPen('r', width=2), name="Sim")
            
        # Row 1: Residuals/Noise Plot
        p2 = self.win.addPlot(row=1, col=0, axisItems={'bottom': DateAxisItem()})
        p2.setTitle("Residuals & Noise")
        p2.showGrid(x=True, y=True)
        p2.setXLink(p1)
        h2 = int(ranges[1] * pixels_per_unit) + OVERHEAD
        p2.setMinimumHeight(h2)
        p2.setMaximumHeight(h2)
        p2.setYRange(ylims[1][0], ylims[1][1], padding=0)
        h_list.append(h2)
        main_col_plots.append(p2)
        
        rx, ry = self._prepare_data(res)
        if rx is not None:
            p2.plot(rx, ry, pen=pg.mkPen('k', width=1), name="Residuals")
        if noise is not None:
            nx, ny = self._prepare_data(noise)
            if nx is not None:
                p2.plot(nx, ny, pen=pg.mkPen('orange', width=1), name="Noise")

        # Row 0-1, Col 1: Parameters Table
        table_container = QWidget()
        table_container.setAttribute(Qt.WA_TranslucentBackground)
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
            val_str = f"{row['optimal']:.4f}" if not np.isnan(row['optimal']) else "-"
            params_table.setItem(i, 1, QTableWidgetItem(val_str))
            if self.show_stderr:
                stderr = row.get("stderr", np.nan)
                err_str = f"{stderr:.4f}" if not np.isnan(stderr) else "-"
                params_table.setItem(i, 2, QTableWidgetItem(err_str))
                
        params_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        params_table.setEditTriggers(QHeaderView.NoEditTriggers)
        params_table.setStyleSheet("background-color: white; gridline-color: #ddd;")
        
        table_container_layout.addWidget(params_table)
        
        proxy = QGraphicsProxyWidget()
        proxy.setWidget(table_container)
        self.win.addItem(proxy, row=0, col=1, rowspan=2)
        proxy.setMinimumWidth(250 + Y_AXIS_WIDTH if not self.show_stderr else 350 + Y_AXIS_WIDTH) 
        proxy.setMaximumWidth(350 + Y_AXIS_WIDTH if not self.show_stderr else 450 + Y_AXIS_WIDTH)

        # Rows 2+: Contributions and Step Responses
        for i, name in enumerate(sm_names):
            color = sm_colors[i % len(sm_colors)]
            row_idx = i + 2
            
            p_sm = self.win.addPlot(row=row_idx, col=0, axisItems={'bottom': DateAxisItem()})
            p_sm.setTitle(f"Contribution: {name}")
            p_sm.showGrid(x=True, y=True)
            p_sm.setXLink(p1)
            h_sm = int(ranges[row_idx] * pixels_per_unit) + OVERHEAD
            p_sm.setMinimumHeight(h_sm)
            p_sm.setMaximumHeight(h_sm)
            p_sm.setYRange(ylims[row_idx][0], ylims[row_idx][1], padding=0)
            h_list.append(h_sm)
            main_col_plots.append(p_sm)
            
            cx, cy = self._prepare_data(sm_contribs[i])
            if cx is not None:
                p_sm.plot(cx, cy, pen=pg.mkPen(color, width=1.5))
            
            p_rf = self.win.addPlot(row=row_idx, col=1)
            p_rf.setTitle(f"Step Response: {name}")
            p_rf.showGrid(x=True, y=True)
            p_rf.setMinimumHeight(h_sm)
            p_rf.setMaximumHeight(h_sm)
            side_plots.append(p_rf)
            
            try:
                p_current = ml.get_parameters()
                step = ml.get_step_response(name, p=p_current, add_0=True)
                if isinstance(step, (pd.Series, pd.DataFrame)):
                    y_step, x_step = step.values, np.arange(len(step))
                else:
                    y_step, x_step = step, np.arange(len(step))
                if len(y_step) > 0:
                    p_rf.plot(x_step, y_step, pen=pg.mkPen(color, width=2))
            except Exception as e:
                print(f"Error plotting step response for {name}: {e}")

        # Final layout
        total_calculated_height = sum(h_list) + (len(h_list) - 1) * SPACING + MARGINS
        self.win.setMinimumHeight(total_calculated_height)
        self.win.setMaximumHeight(total_calculated_height)
        self.win.ci.layout.setColumnStretchFactor(0, 3)
        self.win.ci.layout.setColumnStretchFactor(1, 1)

        for p in main_col_plots + side_plots:
            p.getAxis('left').setWidth(Y_AXIS_WIDTH)
            for axis in ['bottom', 'left']:
                ax = p.getAxis(axis)
                ax.setPen('k')
                ax.setTextPen('k')
        
        if main_col_plots:
            for p in main_col_plots[:-1]:
                ax = p.getAxis('bottom')
                ax.setStyle(showValues=False)
                ax.setHeight(0)

def get_stats(series):
    if series is None or series.empty: return 0.0, 0.001
    return float(series.min()), float(series.max())
