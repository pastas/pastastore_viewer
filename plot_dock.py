from qgis.PyQt.QtCore import Qt

# -*- coding: utf-8 -*-
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QLabel,
    QVBoxLayout,
    QWidget,
)

try:
    from .plot_toolbar import PlotNavigationWidget
except (ImportError, ValueError):
    from plot_toolbar import PlotNavigationWidget


try:
    import pyqtgraph as pg
    from pyqtgraph import DateAxisItem
except ImportError:
    pg = None

import numpy as np
import pandas as pd


class PastastorePlotDock(QDockWidget):
    """Dock widget for displaying Pastastore plots."""

    def __init__(self, parent=None):
        super(PastastorePlotDock, self).__init__("Pastastore Plot", parent)
        self.setObjectName("PastastorePlotDock")
        self.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea
        )

        # Container widget
        self.container = QWidget()
        self.layout = QVBoxLayout()
        self.container.setLayout(self.layout)

        # Plot Widget
        if pg:
            self.plot_widget = pg.PlotWidget(axisItems={"bottom": DateAxisItem()})
            self.plot_widget.setBackground("w")
            self.plot_widget.showGrid(x=True, y=True, alpha=0.3)

            # Style axes to black
            for axis in ["bottom", "left"]:
                ax = self.plot_widget.getAxis(axis)
                ax.setPen("k")
                ax.setTextPen("k")

            self.layout.addWidget(self.plot_widget)

            self.plot_nav = PlotNavigationWidget()
            self.plot_nav.set_plots([self.plot_widget])
            self.plot_nav.attach_to(self.plot_widget)
        else:
            self.plot_nav = PlotNavigationWidget()
            self.layout.addWidget(QLabel("pyqtgraph missing"))

        self.setWidget(self.container)

    def fit_plot(self):
        """Reset zoom to show all data with standard bounds."""
        if pg:
            self.plot_nav.fit_all()

    def clear_plot(self, category="data"):
        if pg:
            self.plot_widget.clear()
            self.plot_widget.setTitle(f"No {category} selected", color="k")

    def _prepare_data(self, series):
        if series is None or series.empty:
            return None, None

        x = series.index
        if pd.api.types.is_datetime64_any_dtype(x):
            x = x.astype("datetime64[s]").astype(np.int64)

        y = series.values
        if len(y.shape) > 1 and y.shape[1] == 1:
            y = y.flatten()

        mask = ~np.isnan(y)
        if len(y.shape) > 1:
            return np.array(x), np.array(y)

        return np.array(x[mask]), np.array(y[mask])

    def plot_series(self, data, title="Time Series"):
        if pg is None:
            return
        self.plot_widget.clear()
        self.plot_widget.setTitle(title, color="k")

        items = []
        if isinstance(data, dict):
            for name, df in data.items():
                items.append((name, df))
        elif isinstance(data, list):
            for i, d in enumerate(data):
                label = f"Series {i + 1}"
                if hasattr(d, "name") and d.name:
                    label = d.name
                items.append((label, d))
        else:
            label = "Series"
            if hasattr(data, "name") and data.name:
                label = data.name
            items.append((label, data))

        if len(items) > 1:
            legend = self.plot_widget.plotItem.legend
            if legend:
                legend.items = []
            else:
                self.plot_widget.addLegend()
        else:
            # Remove legend if only 1 item to avoid redundancy
            legend = self.plot_widget.plotItem.legend
            if legend:
                legend.scene().removeItem(legend)
                self.plot_widget.plotItem.legend = None

        colors = [
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
        for i, (name, series_data) in enumerate(items):
            if isinstance(series_data, pd.DataFrame) and not series_data.empty:
                plot_data = series_data.iloc[:, 0]
            else:
                plot_data = series_data

            x, y = self._prepare_data(plot_data)
            if x is not None:
                color = colors[i % len(colors)]
                symbol = "o" if len(x) < 10 else None

                self.plot_widget.plot(
                    x,
                    y,
                    pen=color,
                    symbol=symbol,
                    symbolSize=3,
                    symbolBrush=color,
                    name=str(name),
                    connect="finite",
                )

        self.fit_plot()

    def plot_model(self, obs, sim, title="Model", model_obj=None):
        if pg is None:
            return
        self.plot_widget.clear()
        self.plot_widget.setTitle(title, color="k")
        self.plot_widget.addLegend()

        ox, oy = self._prepare_data(obs)
        if ox is not None:
            self.plot_widget.plot(
                ox,
                oy,
                pen=None,
                symbol="o",
                symbolSize=5,
                symbolBrush="k",
                name="Observations",
                connect="finite",
            )

        sx, sy = self._prepare_data(sim)
        if sx is not None:
            self.plot_widget.plot(
                sx,
                sy,
                pen=pg.mkPen("#1f77b4", width=2),
                name="Simulation",
                connect="finite",
            )

        if model_obj:
            try:
                r2 = model_obj.stats.rsq()
                self.plot_widget.setTitle(f"{title} (R²: {r2:.3f})", color="k")
            except Exception as err:
                import logging
                logging.getLogger(__name__).debug("Setting plot title with R² failed: %s", err)

        self.fit_plot()

    def plot_models(self, data_list):
        """Plot multiple models.
        data_list: list of dicts with keys 'name', 'obs', 'sim', 'r2'
        """
        if pg is None:
            return
        self.plot_widget.clear()

        if not data_list:
            return

        if len(data_list) == 1:
            d = data_list[0]
            # specific title for single model
            title = f"Model: {d['name']}"
            if d.get("r2") is not None:
                title += f" (R²: {d['r2']:.3f})"
            self.plot_widget.setTitle(title, color="k")
        else:
            self.plot_widget.setTitle(f"Models ({len(data_list)} selected)", color="k")

        self.plot_widget.addLegend()

        colors = [
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

        for i, d in enumerate(data_list):
            if len(data_list) == 1:
                obs_color = "k"
                sim_color = "#1f77b4"
                name = d["name"]  # Keep name simple
                obs_label = "Observations"
                sim_label = "Simulation"
            else:
                color = colors[i % len(colors)]
                obs_color = color
                sim_color = color
                name = d["name"]
                obs_label = f"{name} (Obs)"
                sim_label = f"{name} (Sim)"

            # Observations
            if d.get("obs") is not None:
                ox, oy = self._prepare_data(d["obs"])
                if ox is not None:
                    self.plot_widget.plot(
                        ox,
                        oy,
                        pen=None,
                        symbol="o",
                        symbolSize=5,
                        symbolBrush=obs_color,
                        name=obs_label,
                        connect="finite",
                    )

            # Simulation
            if d.get("sim") is not None:
                sx, sy = self._prepare_data(d["sim"])
                if sx is not None:
                    # Simulation gets the same color as observations or red for single
                    self.plot_widget.plot(
                        sx,
                        sy,
                        pen=pg.mkPen(sim_color, width=2),
                        name=sim_label,
                        connect="finite",
                    )

        self.fit_plot()

    def save_state_to_project(self):
        """Saves dock visibility to project."""
        from qgis.core import QgsProject

        project = QgsProject.instance()
        scope = "PastastoreViewer"
        project.writeEntry(
            scope, "plot_dock_open", "true" if self.isVisible() else "false"
        )
