from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
)
from qgis.PyQt.QtCore import Qt
import pyqtgraph as pg
from pyqtgraph import DateAxisItem
import numpy as np
import pastas as ps
from scipy.stats import norm, probplot
from .qt_compat import PEN_DASH_LINE

from pastastore._tqdm import tqdm as _tqdm_unused  # noqa: ensure deps available
from pastas.stats.core import acf as get_acf


class DiagnosticsPlotDialog(QDialog):
    """Dialog displaying model diagnostics using pyqtgraph.

    Mirrors pastas.ml.plots.diagnostics():
      - Top-left   : Residuals / noise time series
      - Bottom-left : Autocorrelation function (ACF)
      - Top-middle  : Histogram with normal PDF overlay
      - Bottom-middle: Q-Q probability plot
      - Top-right   : Residuals vs simulated (heteroscedasticity)
      - Bottom-right : sqrt(|Residuals|) vs simulated
    """

    ALPHA = 0.05  # significance level for ACF confidence intervals
    BINS = 50

    def __init__(self, ml: ps.Model, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Diagnostics: {ml.name}")
        self.resize(1100, 600)
        self.ml = ml

        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        self.setLayout(layout)

        self.win = pg.GraphicsLayoutWidget()
        self.win.setBackground("w")
        self.win.ci.layout.setContentsMargins(5, 5, 5, 5)
        self.win.ci.layout.setSpacing(8)
        layout.addWidget(self.win)

        self._build_plots()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _series_to_xy(self, series):
        """Return (x_epoch_seconds, y_values) arrays, NaN-stripped."""
        x = series.index.astype('datetime64[s]').astype(np.int64)
        y = series.values.astype(float)
        mask = np.isfinite(y)
        return x[mask], y[mask]

    def _styled(self, plot):
        """Apply common axis styling to a PlotItem."""
        plot.showGrid(x=True, y=True)
        for axis_name in ("left", "bottom", "top", "right"):
            ax = plot.getAxis(axis_name)
            ax.setPen("k")
            ax.setTextPen("k")
        return plot

    def _add_plot(self, row, col, **kwargs):
        p = self.win.addPlot(row=row, col=col, **kwargs)
        return self._styled(p)

    # ------------------------------------------------------------------
    # Build all sub-plots
    # ------------------------------------------------------------------

    def _build_plots(self):
        ml = self.ml

        # Determine whether we use noise or residuals
        if ml.noisemodel is not None:
            res = ml.noise().iloc[1:]
            series_label = "Noise"
        else:
            res = ml.residuals()
            series_label = "Residuals"

        sim = ml.simulate()

        # Align simulation to residual times for scatter plots
        sim_at_res = sim.reindex(res.index, method="nearest")

        # ---- Row 0, Col 0: time series ----
        p_ts = self._add_plot(0, 0, axisItems={"bottom": DateAxisItem()})
        n = res.size
        mu = res.mean()
        p_ts.setTitle(
            f"{series_label}  (n={n},  μ={mu:.3f})", color="k"
        )
        p_ts.getAxis("left").setLabel(series_label)

        x_ts, y_ts = self._series_to_xy(res)
        p_ts.addLine(y=0, pen=pg.mkPen("k", style=PEN_DASH_LINE))
        # Plot as connected line (with gap detection handled via finite mask above)
        p_ts.plot(x_ts, y_ts, pen=pg.mkPen("#1f77b4", width=1))

        # ---- Row 1, Col 0: ACF ----
        p_acf = self._add_plot(1, 0)
        p_acf.setTitle("Autocorrelation", color="k")
        p_acf.getAxis("bottom").setLabel("Lag [days]")
        p_acf.getAxis("left").setLabel("Autocorrelation [-]")
        p_acf.addLine(y=0, pen=pg.mkPen("k"))
        self._plot_acf(p_acf, res, self.ALPHA)


        # ---- Row 0, Col 1: Histogram ----
        p_hist = self._add_plot(0, 1)
        p_hist.setTitle("Histogram", color="k")
        p_hist.getAxis("bottom").setLabel("Value")
        p_hist.getAxis("left").setLabel("Probability density")
        self._plot_histogram(p_hist, res.values)

        # ---- Row 1, Col 1: Q-Q plot ----
        p_qq = self._add_plot(1, 1)
        p_qq.setTitle("Probability plot", color="k")
        p_qq.getAxis("bottom").setLabel("Theoretical quantiles")
        p_qq.getAxis("left").setLabel("Ordered values")
        self._plot_qq(p_qq, res.values)

        # ---- Row 0, Col 2: Residuals vs Sim ----
        p_hsc1 = self._add_plot(0, 2)
        p_hsc1.setTitle("Residuals vs Simulated", color="k")
        p_hsc1.getAxis("bottom").setLabel("Simulated values")
        p_hsc1.getAxis("left").setLabel(series_label)
        self._plot_scatter(p_hsc1, sim_at_res.values, res.values)

        # ---- Row 1, Col 2: sqrt(|Residuals|) vs Sim ----
        p_hsc2 = self._add_plot(1, 2)
        p_hsc2.setTitle("√|Residuals| vs Simulated", color="k")
        p_hsc2.getAxis("bottom").setLabel("Simulated values")
        p_hsc2.getAxis("left").setLabel("√|" + series_label + "|")
        self._plot_scatter(p_hsc2, sim_at_res.values, np.sqrt(np.abs(res.values)))

        # Column widths: left column wider (time series / ACF)
        self.win.ci.layout.setColumnStretchFactor(0, 3)
        self.win.ci.layout.setColumnStretchFactor(1, 2)
        self.win.ci.layout.setColumnStretchFactor(2, 2)

    # ------------------------------------------------------------------
    # Sub-plot implementations
    # ------------------------------------------------------------------

    def _plot_acf(self, plot, series, alpha=0.05):
        """Plot ACF bars and confidence band."""
        try:
            r = get_acf(series, full_output=True, alpha=alpha)
        except Exception:
            plot.setTitle("ACF (error computing)", color="r")
            return

        if r.empty:
            return

        lags = r.index.days.values.astype(float)
        acf_vals = r["acf"].values
        conf = r["conf"].rolling(10, min_periods=1).mean().values

        # Confidence band
        upper = conf
        lower = -conf
        fill = pg.FillBetweenItem(
            pg.PlotDataItem(lags, upper),
            pg.PlotDataItem(lags, lower),
            brush=pg.mkBrush(31, 119, 180, 80),
        )
        plot.addItem(fill)

        # ACF vlines via BarGraphItem (width = 0.3 days looks good)
        if len(lags) > 1:
            bar_width = float(lags[1] - lags[0]) * 0.4
        else:
            bar_width = 0.3
        bars = pg.BarGraphItem(
            x=lags, height=acf_vals, width=bar_width, brush="k", pen=pg.mkPen("k")
        )
        plot.addItem(bars)
        if len(lags):
            plot.setXRange(0, float(lags.max()), padding=0.02)

    def _plot_histogram(self, plot, values):
        """Histogram bars + normal PDF overlay."""
        vals = values[np.isfinite(values)]
        if len(vals) == 0:
            return

        counts, bin_edges = np.histogram(vals, bins=self.BINS, density=True)
        bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
        bin_width = bin_edges[1] - bin_edges[0]

        bars = pg.BarGraphItem(
            x=bin_centers,
            height=counts,
            width=bin_width * 0.9,
            brush=pg.mkBrush(31, 119, 180, 140),
            pen=pg.mkPen("w", width=0.5),
        )
        plot.addItem(bars)

        # Normal PDF
        x_pdf = np.linspace(vals.min(), vals.max(), 200)
        y_pdf = norm.pdf(x_pdf, vals.mean(), vals.std())
        plot.plot(x_pdf, y_pdf, pen=pg.mkPen("k", width=2, style=PEN_DASH_LINE))

    def _plot_qq(self, plot, values):
        """Q-Q probability plot against normal distribution."""
        vals = values[np.isfinite(values)]
        if len(vals) == 0:
            return

        (osm, osr), (slope, intercept, r) = probplot(vals, dist="norm")

        # Scatter: theoretical vs. ordered sample
        scatter = pg.ScatterPlotItem(
            x=osm, y=osr, size=5, brush=pg.mkBrush("#1f77b4"), pen=pg.mkPen(None)
        )
        plot.addItem(scatter)

        # Fit line
        x_line = np.array([osm[0], osm[-1]])
        y_line = slope * x_line + intercept
        plot.plot(x_line, y_line, pen=pg.mkPen("k", width=2))

        # R² annotation
        r2_label = pg.TextItem(f"R²={r**2:.2f}", color="k", anchor=(0.5, 1.0))
        r2_label.setPos(float(np.median(osm)), float(np.min(osr)))
        plot.addItem(r2_label)

    def _plot_scatter(self, plot, x_vals, y_vals):
        """Generic scatter for heteroscedasticity panels."""
        mask = np.isfinite(x_vals) & np.isfinite(y_vals)
        if not np.any(mask):
            return
        scatter = pg.ScatterPlotItem(
            x=x_vals[mask],
            y=y_vals[mask],
            size=5,
            brush=pg.mkBrush(31, 119, 180, 150),
            pen=pg.mkPen(None),
        )
        plot.addItem(scatter)
        plot.addLine(y=0, pen=pg.mkPen("k", style=PEN_DASH_LINE))
