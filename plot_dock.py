# -*- coding: utf-8 -*-

from qgis.PyQt.QtWidgets import (
    QDockWidget, QVBoxLayout, QWidget, QLabel, 
    QPushButton, QHBoxLayout
)
from qgis.PyQt.QtCore import Qt
try:
    import pyqtgraph as pg
    from pyqtgraph import DateAxisItem
except ImportError:
    pg = None

import pandas as pd
import numpy as np

class PastastorePlotDock(QDockWidget):
    """Dock widget for displaying Pastastore plots."""
    
    def __init__(self, parent=None):
        super(PastastorePlotDock, self).__init__("Pastastore Plot", parent)
        self.setObjectName("PastastorePlotDock")
        self.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea)
        
        # Container widget
        self.container = QWidget()
        self.layout = QVBoxLayout()
        self.container.setLayout(self.layout)
        
        # Zoom Buttons
        zoom_layout = QHBoxLayout()
        self.btn_zoom_in = QPushButton("+")
        self.btn_pan = QPushButton("Pan")
        self.btn_show_all = QPushButton("All")
        for btn in [self.btn_zoom_in, self.btn_pan, self.btn_show_all]:
            btn.setMaximumWidth(60)
            zoom_layout.addWidget(btn)
        zoom_layout.addStretch()
        self.layout.addLayout(zoom_layout)

        # Plot Widget
        if pg:
            self.plot_widget = pg.PlotWidget(axisItems={'bottom': DateAxisItem()})
            self.plot_widget.setBackground('w')
            self.plot_widget.showGrid(x=True, y=True)
            
            # Style axes to black
            for axis in ['bottom', 'left']:
                ax = self.plot_widget.getAxis(axis)
                ax.setPen('k')
                ax.setTextPen('k')
            
            self.layout.addWidget(self.plot_widget)
            
            # Connect zoom buttons
            self.btn_zoom_in.clicked.connect(self._enable_rect_zoom)
            self.btn_pan.clicked.connect(self._enable_pan_zoom)
            self.btn_show_all.clicked.connect(self.fit_plot)
        else:
            self.layout.addWidget(QLabel("pyqtgraph missing"))
            
        self.setWidget(self.container)

    def fit_plot(self):
        """Reset zoom to show all data with standard bounds."""
        if pg:
            vb = self.plot_widget.getViewBox()
            vb.enableAutoRange(axis=vb.XYAxes, enable=True)
            vb.autoRange(padding=0.02) 
            self._enable_pan_zoom()

    def clear_plot(self):
        if pg:
            self.plot_widget.clear()

    def _prepare_data(self, series):
        if series is None or series.empty:
            return None, None
            
        x = series.index
        if pd.api.types.is_datetime64_any_dtype(x):
            x = x.view(np.int64) // 10**9
        
        y = series.values
        if len(y.shape) > 1 and y.shape[1] == 1:
            y = y.flatten()
            
        mask = ~np.isnan(y)
        if len(y.shape) > 1:
             return np.array(x), np.array(y)
             
        return np.array(x[mask]), np.array(y[mask])

    def plot_series(self, data, title="Time Series"):
        if pg is None: return
        self.plot_widget.clear()
        self.plot_widget.setTitle(title, color='k')
        
        items = []
        if isinstance(data, dict):
            for name, df in data.items():
                items.append((name, df))
        elif isinstance(data, list):
            for i, d in enumerate(data):
                label = f"Series {i+1}"
                if hasattr(d, "name") and d.name: label = d.name
                items.append((label, d))
        else:
            label = "Series"
            if hasattr(data, "name") and data.name: label = data.name
            items.append((label, data))
            
        if len(items) > 1:
            legend = self.plot_widget.plotItem.legend
            if legend:
                legend.items = []
            else:
                self.plot_widget.addLegend()

        colors = ['b', 'r', 'g', 'c', 'm', 'y']
        for i, (name, series_data) in enumerate(items):
            if isinstance(series_data, pd.DataFrame) and not series_data.empty:
                plot_data = series_data.iloc[:, 0]
            else:
                plot_data = series_data
                
            x, y = self._prepare_data(plot_data)
            if x is not None:
                color = colors[i % len(colors)]
                symbol = 'o'
                if len(x) > 5000:
                    symbol = None
                    
                self.plot_widget.plot(x, y, pen=color, symbol=symbol, symbolSize=3, symbolBrush=color, name=str(name), connect='finite')

        self.fit_plot()

    def plot_model(self, obs, sim, title="Model", model_obj=None):
        if pg is None: return
        self.plot_widget.clear()
        self.plot_widget.setTitle(title, color='k')
        self.plot_widget.addLegend()
        
        ox, oy = self._prepare_data(obs)
        if ox is not None:
            self.plot_widget.plot(ox, oy, pen=None, symbol='o', symbolSize=5, symbolBrush='k', name="Observations", connect='finite')
            
        sx, sy = self._prepare_data(sim)
        if sx is not None:
            self.plot_widget.plot(sx, sy, pen=pg.mkPen('r', width=2), name="Simulation", connect='finite')
            
        if model_obj:
            try:
                r2 = model_obj.stats.rsq()
                self.plot_widget.setTitle(f"{title} (R²: {r2:.3f})", color='k')
            except:
                pass
        
        self.fit_plot()

    def _enable_rect_zoom(self):
        if pg:
            vb = self.plot_widget.getViewBox()
            vb.setMouseMode(vb.RectMode)

    def _enable_pan_zoom(self):
        if pg:
            vb = self.plot_widget.getViewBox()
            vb.setMouseMode(vb.PanMode)

    def save_state_to_project(self):
        """Saves dock visibility to project."""
        from qgis.core import QgsProject
        project = QgsProject.instance()
        scope = "PastastoreViewer"
        project.writeEntry(scope, "plot_dock_open", "true" if self.isVisible() else "false")
