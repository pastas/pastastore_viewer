from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QWidget, QScrollArea, 
    QTableWidget, QTableWidgetItem, QHeaderView, QGraphicsProxyWidget
)
from qgis.PyQt.QtCore import Qt
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
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.setLayout(self.layout)
        
        # Scroll Area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(0)
        
        # Graphics Layout
        self.win = pg.GraphicsLayoutWidget()
        self.win.setBackground('w')
        self.win.ci.setContentsMargins(10, 10, 10, 10)
        self.win.ci.setSpacing(10)
        
        self.scroll_layout.addWidget(self.win)
        self.scroll.setWidget(self.scroll_content)
        self.layout.addWidget(self.scroll)
        
        self.plot_results()

    def _prepare_data(self, series):
        if series is None or series.empty:
            return None, None
        x = series.index.view(np.int64) // 10**9
        y = series.values
        mask = ~np.isnan(y)
        return x[mask], y[mask]

    def plot_results(self):
        ml = self.ml
        
        # Constants for layout
        OVERHEAD = 55   # Title + Axis
        SPACING = 10    # Space between subplots
        MARGINS = 20    # Top + Bottom
        
        # 1. Determine Y-limits for each plot (mimicking Pastas logic)
        sm_names = list(ml.stressmodels.keys())
        ylims = []
        
        # Plot 0: Obs & Sim
        obs = ml.observations()
        sim = ml.simulate()
        v1 = pd.concat([obs, sim])
        ylims.append((float(v1.min()), float(v1.max())))
        
        # Plot 1: Residuals & Noise
        res = ml.residuals()
        noise = ml.noise() if ml.settings["noise"] else None
        if noise is not None:
            v2 = pd.concat([res, noise])
            ylims.append((float(v2.min()), float(v2.max())))
        else:
            ylims.append((float(res.min()), float(res.max())))
            
        # Plot 2+: Contributions
        sm_contribs = []
        for name in sm_names:
            c = ml.get_contribution(name)
            sm_contribs.append(c)
            ylims.append((float(c.min()), float(c.max())))
            
        # 2. Calculate PIXELS_PER_UNIT
        ranges = [y[1] - y[0] if y[1] != y[0] else 0.001 for y in ylims]
        total_data_range = sum(ranges)
        
        num_plots = len(ylims)
        total_overhead = (num_plots * OVERHEAD) + ((num_plots - 1) * SPACING) + MARGINS
        
        # Try to fit in current window height, with a fallback minimum scale
        # Dialog height is 900, use ~800 for available space
        target_total_height = self.height() - 60 
        available_data_height = target_total_height - total_overhead
        
        # PIXELS_PER_UNIT = pixels per 1 unit of data (e.g. meter)
        pixels_per_unit = available_data_height / total_data_range
        
        # Clamp to reasonable values (e.g. at least 100px/unit, at most 2000px/unit)
        pixels_per_unit = max(100, min(pixels_per_unit, 2000))
        
        # Color sequence for stressmodels
        sm_colors = ['#1f77b4', '#2ca02c', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
        
        # 3. Create Plots
        h_list = []
        
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
        
        rx, ry = self._prepare_data(res)
        if rx is not None:
            p2.plot(rx, ry, pen=pg.mkPen('k', width=1), name="Residuals")
        if noise is not None:
            nx, ny = self._prepare_data(noise)
            if nx is not None:
                p2.plot(nx, ny, pen=pg.mkPen('orange', width=1), name="Noise")

        # Row 0-1, Col 1: Parameters Table
        params_table = QTableWidget()
        params = ml.parameters
        params_table.setRowCount(len(params))
        params_table.setColumnCount(2)
        params_table.setHorizontalHeaderLabels(["Parameter", "Optimal"])
        for i, (idx, row) in enumerate(params.iterrows()):
            params_table.setItem(i, 0, QTableWidgetItem(str(idx)))
            val_str = f"{row['optimal']:.4f}" if not np.isnan(row['optimal']) else "-"
            params_table.setItem(i, 1, QTableWidgetItem(val_str))
        
        params_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        params_table.setEditTriggers(QHeaderView.NoEditTriggers)
        params_table.setStyleSheet("background-color: white; gridline-color: #ddd;")
        
        proxy = QGraphicsProxyWidget()
        proxy.setWidget(params_table)
        self.win.addItem(proxy, row=0, col=1, rowspan=2)
        proxy.setMinimumWidth(250)
        proxy.setMaximumWidth(350)

        # Rows 2+: Contributions and Step Responses
        row_offset = 2
        for i, name in enumerate(sm_names):
            color = sm_colors[i % len(sm_colors)]
            
            # Contribution Plot
            p_sm = self.win.addPlot(row=row_offset + i, col=0, axisItems={'bottom': DateAxisItem()})
            p_sm.setTitle(f"Contribution: {name}")
            p_sm.showGrid(x=True, y=True)
            p_sm.setXLink(p1)
            
            h_sm = int(ranges[row_offset + i] * pixels_per_unit) + OVERHEAD
            p_sm.setMinimumHeight(h_sm)
            p_sm.setMaximumHeight(h_sm)
            p_sm.setYRange(ylims[row_offset + i][0], ylims[row_offset + i][1], padding=0)
            h_list.append(h_sm)
            
            cx, cy = self._prepare_data(sm_contribs[i])
            if cx is not None:
                p_sm.plot(cx, cy, pen=pg.mkPen(color, width=1.5))
            
            # Step Response
            p_rf = self.win.addPlot(row=row_offset + i, col=1)
            p_rf.setTitle(f"Step Response: {name}")
            p_rf.showGrid(x=True, y=True)
            p_rf.setMinimumHeight(h_sm)
            p_rf.setMaximumHeight(h_sm)
            
            try:
                p = ml.get_parameters()
                step = ml.get_step_response(name, p=p, add_0=True)
                if isinstance(step, (pd.Series, pd.DataFrame)):
                    y_step, x_step = step.values, np.arange(len(step))
                else:
                    y_step, x_step = step, np.arange(len(step))
                if len(y_step) > 0:
                    p_rf.plot(x_step, y_step, pen=pg.mkPen(color, width=2))
            except Exception as e:
                print(f"Error plotting step response for {name}: {e}")

        # Final height for container
        total_calculated_height = sum(h_list) + (len(h_list) - 1) * SPACING + MARGINS
        self.win.setMinimumHeight(total_calculated_height)
        self.win.setMaximumHeight(total_calculated_height)

        # Column stretch: Main plots (col 0) are 3x wider than right side (col 1)
        self.win.ci.layout.setColumnStretchFactor(0, 3)
        self.win.ci.layout.setColumnStretchFactor(1, 1)

        # Style axes
        for item in self.win.ci.items:
            if isinstance(item, pg.PlotItem):
                for axis in ['bottom', 'left']:
                    ax = item.getAxis(axis)
                    ax.setPen('k')
                    ax.setTextPen('k')
