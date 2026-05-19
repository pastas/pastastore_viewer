from qgis.PyQt.QtWidgets import QWidget, QHBoxLayout, QPushButton, QSizePolicy
from qgis.PyQt.QtCore import Qt, QEvent
from qgis.core import QgsApplication
from .qt_compat import ALIGN_LEFT, SIZE_POLICY_FIXED


class PlotNavigationWidget(QWidget):
    """Reusable plot navigation buttons for pyqtgraph plots."""

    def __init__(
        self,
        plots=None,
        on_rect=None,
        on_pan=None,
        on_full=None,
        default_mode="rect",
        parent=None,
    ):
        super(PlotNavigationWidget, self).__init__(parent)
        self._plots = list(plots) if plots else []
        self._on_rect = on_rect
        self._on_pan = on_pan
        self._on_full = on_full
        self._mode = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setAlignment(ALIGN_LEFT)

        self.btn_zoom = QPushButton()
        self.btn_zoom.setIcon(QgsApplication.getThemeIcon("/mActionZoomIn.svg"))
        self.btn_zoom.setToolTip("Zoom to Rectangle")
        self.btn_pan = QPushButton()
        self.btn_pan.setIcon(QgsApplication.getThemeIcon("/mActionPan.svg"))
        self.btn_pan.setToolTip("Pan")
        self.btn_zoom_all = QPushButton()
        self.btn_zoom_all.setIcon(
            QgsApplication.getThemeIcon("/mActionZoomFullExtent.svg")
        )
        self.btn_zoom_all.setToolTip("Zoom to Full Extent")

        self.btn_zoom.setCheckable(True)
        self.btn_pan.setCheckable(True)
        self.btn_zoom.setSizePolicy(SIZE_POLICY_FIXED, SIZE_POLICY_FIXED)
        self.btn_pan.setSizePolicy(SIZE_POLICY_FIXED, SIZE_POLICY_FIXED)
        self.btn_zoom_all.setSizePolicy(SIZE_POLICY_FIXED, SIZE_POLICY_FIXED)
        self.btn_zoom.setMaximumWidth(40)
        self.btn_pan.setMaximumWidth(40)
        self.btn_zoom_all.setMaximumWidth(40)

        self.btn_zoom.clicked.connect(lambda: self.set_mode("rect", trigger=True))
        self.btn_pan.clicked.connect(lambda: self.set_mode("pan", trigger=True))
        self.btn_zoom_all.clicked.connect(self.fit_all)

        layout.addWidget(self.btn_zoom)
        layout.addWidget(self.btn_pan)
        layout.addWidget(self.btn_zoom_all)

        if default_mode is not None:
            self.set_mode(default_mode, trigger=False)

    def set_plots(self, plots):
        self._plots = list(plots) if plots else []

    def set_callbacks(self, on_rect=None, on_pan=None, on_full=None):
        self._on_rect = on_rect
        self._on_pan = on_pan
        self._on_full = on_full

    def set_mode(self, mode, trigger=True):
        self._mode = mode
        self.btn_zoom.setChecked(mode == "rect")
        self.btn_pan.setChecked(mode == "pan")

        if not trigger:
            return
        if mode == "rect":
            if self._on_rect:
                self._on_rect()
            else:
                self._default_rect()
        elif mode == "pan":
            if self._on_pan:
                self._on_pan()
            else:
                self._default_pan()

    def fit_all(self):
        if self._on_full:
            self._on_full()
        else:
            self._default_full()

    def _default_rect(self):
        for plot in self._plots:
            vb = plot.getViewBox()
            vb.setMouseMode(vb.RectMode)

    def _default_pan(self):
        for plot in self._plots:
            vb = plot.getViewBox()
            vb.setMouseMode(vb.PanMode)

    def _default_full(self):
        for plot in self._plots:
            vb = plot.getViewBox()
            vb.enableAutoRange(axis=vb.XYAxes, enable=True)
            vb.autoRange(padding=0.02)

    # ------------------------------------------------------------------
    # Overlay support
    # ------------------------------------------------------------------

    def attach_to(self, widget, offset=(4, 4)):
        """Re-parent and overlay this toolbar at the top-left of *widget*."""
        self._anchor_widget = widget
        self._anchor_offset = offset
        self.setParent(widget)
        self.setStyleSheet(
            "PlotNavigationWidget {"
            "  background: rgba(255,255,255,200);"
            "  border-radius: 4px;"
            "  padding: 2px;"
            "}"
        )
        self.adjustSize()
        self.move(offset[0], offset[1])
        self.raise_()
        self.show()
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        resize_type = getattr(QEvent, "Resize", None)
        if resize_type is None:
            resize_type = getattr(getattr(QEvent, "Type", None), "Resize", 14)

        if obj is getattr(self, "_anchor_widget", None) and int(event.type()) == int(resize_type):
            self.move(self._anchor_offset[0], self._anchor_offset[1])
            self.raise_()
        return False
