from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QLineEdit,
    QCheckBox,
    QDateEdit,
    QDialogButtonBox,
    QLabel,
)
from qgis.PyQt.QtCore import QDate
import pandas as pd
from .i18n_helper import tr as _i18n_tr


def _tr(message):
    return _i18n_tr(message)


class BulkModelsDialog(QDialog):
    """Dialog to configure bulk model creation."""

    def __init__(self, oseries_names, store, parent=None):
        super(BulkModelsDialog, self).__init__(parent)
        self.oseries_names = oseries_names
        self.store = store

        self.setWindowTitle(_tr("Create Models"))
        self.resize(420, 270)

        layout = QVBoxLayout()
        self.setLayout(layout)

        info = QLabel(_tr("Create models for {n} oseries.").format(n=len(oseries_names)))
        layout.addWidget(info)

        form = QFormLayout()
        layout.addLayout(form)

        self.le_suffix = QLineEdit()
        self.le_suffix.setPlaceholderText(_tr("Optional suffix (e.g. _v2)"))
        form.addRow(_tr("Model name suffix:"), self.le_suffix)

        self.chk_overwrite = QCheckBox(_tr("Overwrite existing models"))
        self.chk_overwrite.setChecked(False)
        form.addRow("", self.chk_overwrite)

        self.chk_recharge = QCheckBox(_tr("Add recharge component"))
        self.chk_recharge.setChecked(True)
        form.addRow("", self.chk_recharge)

        self.chk_solve = QCheckBox(_tr("Solve models after creation"))
        self.chk_solve.setChecked(False)
        self.chk_solve.toggled.connect(self._toggle_solve_fields)
        form.addRow("", self.chk_solve)

        self.de_tmin = QDateEdit()
        self.de_tmin.setCalendarPopup(True)
        self.de_tmin.setDisplayFormat("yyyy-MM-dd")
        form.addRow(_tr("Solve tmin:"), self.de_tmin)

        self.de_tmax = QDateEdit()
        self.de_tmax.setCalendarPopup(True)
        self.de_tmax.setDisplayFormat("yyyy-MM-dd")
        form.addRow(_tr("Solve tmax:"), self.de_tmax)

        default_tmin, default_tmax = self._get_default_dates()
        if default_tmin:
            self.de_tmin.setDate(default_tmin)
        if default_tmax:
            self.de_tmax.setDate(default_tmax)

        self._toggle_solve_fields(False)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _toggle_solve_fields(self, enabled):
        self.de_tmin.setEnabled(enabled)
        self.de_tmax.setEnabled(enabled)

    def _get_default_dates(self):
        if not self.store or not self.oseries_names:
            return None, None

        dates = []
        try:
            data = self.store.get_oseries(self.oseries_names)
        except Exception:
            return None, None

        def collect(series):
            if series is None or series.empty:
                return
            idx = series.index
            if len(idx) == 0:
                return
            dates.append(pd.Timestamp(idx.min()).date())
            dates.append(pd.Timestamp(idx.max()).date())

        if isinstance(data, dict):
            for series in data.values():
                collect(series)
        elif hasattr(data, "index"):
            collect(data)

        if not dates:
            return None, None

        min_date = min(dates)
        max_date = max(dates)
        return QDate(min_date.year, min_date.month, min_date.day), QDate(
            max_date.year, max_date.month, max_date.day
        )

    def get_options(self):
        suffix = self.le_suffix.text().strip()
        add_recharge = self.chk_recharge.isChecked()
        solve = self.chk_solve.isChecked()
        tmin = self.de_tmin.date().toString("yyyy-MM-dd") if solve else None
        tmax = self.de_tmax.date().toString("yyyy-MM-dd") if solve else None

        return {
            "suffix": suffix,
            "add_recharge": add_recharge,
            "solve": solve,
            "tmin": tmin,
            "tmax": tmax,
            "overwrite": self.chk_overwrite.isChecked(),
        }
