from qgis.PyQt.QtCore import Qt, QItemSelectionModel
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QComboBox,
    QSizePolicy,
    QDialogButtonBox,
    QMessageBox,
    QDialog,
    QMenu,
)

# -*- coding: utf-8 -*-

from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QVBoxLayout,
    QWidget,
    QLabel,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QToolButton,
    QComboBox,
    QGroupBox,
    QCheckBox,
    QGridLayout,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QLinearGradient, QPainter, QPixmap
from qgis.core import QgsApplication, QgsStyle
import pandas as pd
import numpy as np

from .i18n_helper import tr as _i18n_tr


if hasattr(QToolButton, "InstantPopup"):
    TOOLBUTTON_POPUP_INSTANT = QToolButton.ToolButtonPopupMode.InstantPopup
else:
    TOOLBUTTON_POPUP_INSTANT = QToolButton.ToolButtonPopupMode.InstantPopup


def _tr(message):
    return _i18n_tr(message)


class PastastoreMainDock(QDockWidget):
    """Main Dock widget for loading and browsing Pastastore data."""

    load_requested = pyqtSignal(str)  # path (optional)
    new_requested = pyqtSignal()
    item_selected = pyqtSignal(str, list)  # category, names (list)
    settings_requested = pyqtSignal()
    save_requested = pyqtSignal()
    tab_changed = pyqtSignal(str)
    delete_model_requested = pyqtSignal(list)  # names (list)
    delete_oseries_requested = pyqtSignal(list)  # names (list)
    delete_stresses_requested = pyqtSignal(list)  # names (list)
    edit_model_requested = pyqtSignal(str)  # model name
    results_requested = pyqtSignal(str)  # model name
    diagnostics_requested = pyqtSignal(str)  # model name
    mpl_results_requested = pyqtSignal(str)  # model name (matplotlib)
    mpl_diagnostics_requested = pyqtSignal(str)  # model name (matplotlib)
    add_model_column_requested = pyqtSignal(str)  # stat name to compute
    map_plot_requested = pyqtSignal(str, str, bool)  # var_key, ramp_name, invert
    select_models_for_oseries_requested = pyqtSignal(list)  # oseries names
    select_models_for_stresses_requested = pyqtSignal(list)  # stresses names
    select_oseries_for_models_requested = pyqtSignal(list)  # model names
    select_stresses_for_models_requested = pyqtSignal(list)  # model names
    edit_oseries_requested = pyqtSignal(str)  # oseries name
    edit_stress_requested = pyqtSignal(str)  # stress name
    create_model_requested = pyqtSignal(str)  # oseries name
    create_models_requested = pyqtSignal(list)  # oseries names
    import_bro_requested = pyqtSignal()  # Import from BRO
    import_knmi_requested = pyqtSignal()  # Import stresses from KNMI

    def __init__(self, parent=None):
        super(PastastoreMainDock, self).__init__(_tr("Pastastore Viewer"), parent)
        self.setObjectName("PastastoreMainDock")
        self.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)

        # State
        self.is_restoring = False
        self.x_col = "x"
        self.y_col = "y"
        self.crs_epsg = "28992"
        self.auto_zoom = False
        self.store_path = None
        self.is_updating_selection = False
        self.filter_widgets = {}

        # Container widget
        self.container = QWidget()
        self.layout = QVBoxLayout()
        self.container.setLayout(self.layout)

        # Filename/Path Edit (full-width row)
        self.le_filename = QLineEdit()
        self.le_filename.setPlaceholderText(_tr("No store loaded"))
        self.layout.addWidget(self.le_filename)

        # Top Actions Layout (compact grid to allow narrower dock width)
        top_layout = QGridLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setHorizontalSpacing(4)
        top_layout.setVerticalSpacing(4)

        # Load Button
        self.btn_load = QPushButton(_tr("Load"))
        self.btn_load.setToolTip(_tr("Load Pastastore Zip"))
        self.btn_load.clicked.connect(lambda: self.load_requested.emit(""))
        top_layout.addWidget(self.btn_load, 0, 0)

        # New Button
        self.btn_new = QPushButton(_tr("New"))
        self.btn_new.setToolTip(_tr("Create New Pastastore"))
        self.btn_new.clicked.connect(lambda: self.new_requested.emit())
        top_layout.addWidget(self.btn_new, 0, 1)

        # Save Button
        self.btn_save = QPushButton(_tr("Save"))
        self.btn_save.setToolTip(_tr("Save Pastastore Zip"))
        self.btn_save.clicked.connect(lambda: self.save_requested.emit())
        top_layout.addWidget(self.btn_save, 1, 0)

        # Settings Button
        self.btn_settings = QPushButton(_tr("Settings"))
        self.btn_settings.clicked.connect(lambda: self.settings_requested.emit())
        top_layout.addWidget(self.btn_settings, 1, 1)

        # Let action buttons shrink when the dock is resized narrower.
        for btn in [self.btn_load, self.btn_new, self.btn_save, self.btn_settings]:
            btn.setMinimumWidth(0)
            btn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

        self.layout.addLayout(top_layout)

        # Tabs for lists
        self.tabs = QTabWidget()
        
        # Create oseries tab with toolbar
        oseries_widget = QWidget()
        oseries_layout = QVBoxLayout()
        oseries_layout.setContentsMargins(0, 0, 0, 0)
        
        # Oseries filter & table
        self.table_oseries = QTableWidget()
        oseries_layout.addWidget(self._create_filter_bar("oseries"))
        oseries_layout.addWidget(self.table_oseries)
        
        # Import button below oseries table
        oseries_button_layout = QHBoxLayout()
        self.btn_import = QToolButton()
        self.btn_import.setText(_tr("Import"))
        self.btn_import.setIcon(QgsApplication.getThemeIcon("/mActionAdd.svg"))
        self.btn_import.setToolTip(_tr("Import data from external sources"))
        self.btn_import.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        import_menu = QMenu()
        import_bro_action = import_menu.addAction(_tr("Download from BRO"))
        import_bro_action.triggered.connect(lambda: self.import_bro_requested.emit())
        self.btn_import.setMenu(import_menu)
        self.btn_import.setPopupMode(TOOLBUTTON_POPUP_INSTANT)
        oseries_button_layout.addWidget(self.btn_import)
        oseries_button_layout.addStretch()
        oseries_layout.addLayout(oseries_button_layout)
        
        oseries_widget.setLayout(oseries_layout)
        
        # Create stresses tab with toolbar
        stresses_widget = QWidget()
        stresses_layout = QVBoxLayout()
        stresses_layout.setContentsMargins(0, 0, 0, 0)

        self.table_stresses = QTableWidget()
        stresses_layout.addWidget(self._create_filter_bar("stresses"))
        stresses_layout.addWidget(self.table_stresses)

        stresses_button_layout = QHBoxLayout()
        self.btn_import_stresses = QToolButton()
        self.btn_import_stresses.setText(_tr("Import"))
        self.btn_import_stresses.setIcon(QgsApplication.getThemeIcon("/mActionAdd.svg"))
        self.btn_import_stresses.setToolTip(
            _tr("Import stress data from external sources")
        )
        self.btn_import_stresses.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        stresses_import_menu = QMenu()
        import_knmi_action = stresses_import_menu.addAction(_tr("Download from KNMI"))
        import_knmi_action.triggered.connect(
            lambda: self.import_knmi_requested.emit()
        )
        self.btn_import_stresses.setMenu(stresses_import_menu)
        self.btn_import_stresses.setPopupMode(TOOLBUTTON_POPUP_INSTANT)
        stresses_button_layout.addWidget(self.btn_import_stresses)
        stresses_button_layout.addStretch()
        stresses_layout.addLayout(stresses_button_layout)

        stresses_widget.setLayout(stresses_layout)

        # Models tab
        self._model_extra_cols = []  # list of extra stat column names

        models_widget = QWidget()
        models_layout = QVBoxLayout()
        models_layout.setContentsMargins(0, 0, 0, 0)

        self.table_models = QTableWidget()
        self.table_models.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_models.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table_models.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_models.horizontalHeader().setStretchLastSection(True)
        self.table_models.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_models.setSortingEnabled(True)
        self.table_models.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_models.setColumnCount(2)
        self.table_models.setHorizontalHeaderLabels(["Name", "Oseries"])
        # Right-click on header to add/remove stat columns
        self.table_models.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_models.horizontalHeader().customContextMenuRequested.connect(
            self._show_models_header_menu
        )
        models_layout.addWidget(self._create_filter_bar("models"))
        models_layout.addWidget(self.table_models)

        # Map plot pane
        map_plot_group = QGroupBox(_tr("Plot on Map"))
        map_plot_layout = QVBoxLayout()
        map_plot_layout.setContentsMargins(4, 4, 4, 4)
        map_plot_layout.setSpacing(4)

        var_row = QHBoxLayout()
        var_row.addWidget(QLabel(_tr("Variable:")))
        self.combo_map_var = QComboBox()
        self.combo_map_var.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo_map_var.setMinimumContentsLength(4)
        self.combo_map_var.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        var_row.addWidget(self.combo_map_var, 1)
        map_plot_layout.addLayout(var_row)

        ramp_row = QHBoxLayout()
        ramp_row.addWidget(QLabel(_tr("Color ramp:")))
        self.combo_map_ramp = QComboBox()
        self.combo_map_ramp.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        ramp_names = [
            "RdYlGn", "Turbo", "Viridis", "Plasma", "Magma", "Inferno",
            "RdYlBu", "Spectral", "Blues", "Reds",
        ]
        for ramp_name in ramp_names:
            self.combo_map_ramp.addItem(ramp_name, ramp_name)
        ramp_row.addWidget(self.combo_map_ramp, 1)
        self.chk_map_invert = QCheckBox(_tr("Invert"))
        self.chk_map_invert.setChecked(False)
        ramp_row.addWidget(self.chk_map_invert)
        map_plot_layout.addLayout(ramp_row)

        self.lbl_ramp_preview = QLabel()
        self.lbl_ramp_preview.setFixedHeight(18)
        self.lbl_ramp_preview.setMinimumWidth(0)
        self.lbl_ramp_preview.setScaledContents(True)
        self.lbl_ramp_preview.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        map_plot_layout.addWidget(self.lbl_ramp_preview)
        self.combo_map_ramp.currentIndexChanged.connect(self._update_ramp_preview)
        self.chk_map_invert.toggled.connect(self._update_ramp_preview)
        self._update_ramp_preview()

        self.btn_map_plot = QPushButton(_tr("Plot on Map"))
        self.btn_map_plot.setMinimumWidth(0)
        self.btn_map_plot.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.btn_map_plot.clicked.connect(
            lambda: self.map_plot_requested.emit(
                self.combo_map_var.currentData() or "",
                self.combo_map_ramp.currentData() or "Turbo",
                self.chk_map_invert.isChecked(),
            )
        )
        map_plot_layout.addWidget(self.btn_map_plot)

        map_plot_group.setLayout(map_plot_layout)
        models_layout.addWidget(map_plot_group)

        models_widget.setLayout(models_layout)

        for table in [self.table_oseries, self.table_stresses]:
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            # Allow resizing
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            table.horizontalHeader().setStretchLastSection(True)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setSortingEnabled(True)
            table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        self.tabs.addTab(oseries_widget, _tr("Oseries"))
        self.tabs.addTab(stresses_widget, _tr("Stresses"))
        self.tabs.addTab(models_widget, _tr("Models"))

        self.table_oseries.itemSelectionChanged.connect(
            lambda: self._on_selection_changed("oseries")
        )
        self.table_stresses.itemSelectionChanged.connect(
            lambda: self._on_selection_changed("stresses")
        )
        self.table_models.itemSelectionChanged.connect(
            lambda: self._on_selection_changed("models")
        )

        self.table_oseries.customContextMenuRequested.connect(
            self.show_oseries_context_menu
        )
        self.table_stresses.customContextMenuRequested.connect(
            self.show_stresses_context_menu
        )
        self.table_models.customContextMenuRequested.connect(
            self.show_model_context_menu
        )
        self.table_oseries.itemDoubleClicked.connect(self._on_oseries_double_clicked)
        self.table_models.itemDoubleClicked.connect(self._on_model_double_clicked)

        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.layout.addWidget(self.tabs)
        self.setMinimumWidth(0)
        self.setWidget(self.container)

    def _on_oseries_double_clicked(self, item):
        if item is None:
            return
        name_item = self.table_oseries.item(item.row(), 0)
        if name_item:
            self.create_model_requested.emit(name_item.text())

    def _on_model_double_clicked(self, item):
        if item is None:
            return
        name_item = self.table_models.item(item.row(), 0)
        if name_item:
            self.edit_model_requested.emit(name_item.text())

    def set_license_capabilities(self, can_use_pro, can_use_pronl):
        del can_use_pro  # reserved for future UI controls

        self.btn_import.setEnabled(can_use_pronl)
        self.btn_import_stresses.setEnabled(can_use_pronl)

        if can_use_pronl:
            self.btn_import.setToolTip(_tr("Import data from external sources"))
            self.btn_import_stresses.setToolTip(
                _tr("Import stress data from external sources")
            )
        else:
            locked = _tr("ProNL license required")
            self.btn_import.setToolTip(locked)
            self.btn_import_stresses.setToolTip(locked)

    # Available statistics for model columns
    AVAILABLE_MODEL_STATS = [
        ("EVP [%]", "evp"),
        ("R²", "rsq"),
        ("RMSE", "rmse"),
        ("NSE", "nse"),
        ("KGE", "kge"),
        ("AIC", "aic"),
        ("BIC", "bic"),
        ("Pearson r", "pearsonr"),
    ]

    @staticmethod
    def _exec_menu(menu, global_pos):
        if hasattr(menu, "exec_"):
            return menu.exec(global_pos)
        return menu.exec(global_pos)

    def _show_models_header_menu(self, position):
        from qgis.PyQt.QtWidgets import QMenu, QAction

        menu = QMenu()

        add_menu = QMenu(_tr("Add column"), self)
        for label, stat in self.AVAILABLE_MODEL_STATS:
            if stat not in self._model_extra_cols:
                action = QAction(label, self)
                action.triggered.connect(
                    lambda checked, s=stat: self._request_add_column(s)
                )
                add_menu.addAction(action)
        if add_menu.isEmpty():
            add_menu.setEnabled(False)
        menu.addMenu(add_menu)

        if self._model_extra_cols:
            remove_menu = QMenu(_tr("Remove column"), self)
            for stat in self._model_extra_cols:
                label = next(
                    (lbl for lbl, s in self.AVAILABLE_MODEL_STATS if s == stat), stat
                )
                action = QAction(label, self)
                action.triggered.connect(
                    lambda checked, s=stat: self._remove_model_column(s)
                )
                remove_menu.addAction(action)
            menu.addMenu(remove_menu)

        self._exec_menu(menu, self.table_models.horizontalHeader().mapToGlobal(position))

    def _get_table_for_category(self, category):
        if category == "oseries":
            return self.table_oseries
        elif category == "stresses":
            return self.table_stresses
        elif category == "models":
            return self.table_models
        return None

    def _create_filter_bar(self, category):
        group = QGroupBox(_tr("Filter"))
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(4)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(4)

        combo_col = QComboBox()
        combo_col.setToolTip(_tr("Select column to filter"))
        combo_col.addItem(_tr("All Columns"), "")
        combo_col.setMinimumWidth(0)

        le_filter = QLineEdit()
        le_filter.setPlaceholderText(_tr("Filter text or > < = expression..."))
        if hasattr(le_filter, "setClearButtonEnabled"):
            le_filter.setClearButtonEnabled(True)
        le_filter.setMinimumWidth(0)

        btn_toggle = QToolButton()
        btn_toggle.setText(_tr("Columns"))
        btn_toggle.setToolTip(_tr("Open per-column filter dialog"))
        try:
            filter_icon = QgsApplication.getThemeIcon("/mActionFilter.svg")
            if not filter_icon.isNull():
                btn_toggle.setIcon(filter_icon)
                btn_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        except Exception:
            pass

        btn_clear = QToolButton()
        btn_clear.setText(_tr("Clear"))
        btn_clear.setToolTip(_tr("Clear all filters"))

        lbl_count = QLabel()
        lbl_count.setStyleSheet("color: gray; font-size: 11px;")

        top_row.addWidget(combo_col)
        top_row.addWidget(le_filter, 1)

        bottom_row.addWidget(btn_toggle)
        bottom_row.addWidget(btn_clear)
        bottom_row.addStretch()
        bottom_row.addWidget(lbl_count)

        layout.addLayout(top_row)
        layout.addLayout(bottom_row)

        self.filter_widgets[category] = {
            "group": group,
            "combo_col": combo_col,
            "le_filter": le_filter,
            "btn_toggle": btn_toggle,
            "btn_clear": btn_clear,
            "lbl_count": lbl_count,
            "column_filters": {},
        }

        le_filter.textChanged.connect(lambda text, cat=category: self._apply_filter(cat))
        combo_col.currentIndexChanged.connect(lambda index, cat=category: self._apply_filter(cat))
        btn_toggle.clicked.connect(
            lambda checked=False, cat=category: self._open_column_filters_popup(cat)
        )
        btn_clear.clicked.connect(lambda checked=False, cat=category: self._clear_filter(cat))

        group.setLayout(layout)
        return group

    def _open_column_filters_popup(self, category):
        table = self._get_table_for_category(category)
        if not table or category not in self.filter_widgets:
            return

        fw = self.filter_widgets[category]
        headers = []
        for c in range(table.columnCount()):
            item = table.horizontalHeaderItem(c)
            headers.append(item.text() if item else f"Column {c}")

        dlg = QDialog(self)
        dlg.setWindowTitle(_tr("Column Filters"))
        dlg.setModal(True)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        editors = {}
        current = fw.get("column_filters", {})
        for i, header_text in enumerate(headers):
            lbl = QLabel(f"{header_text}:")
            le = QLineEdit()
            le.setPlaceholderText(_tr("Filter {0}...").format(header_text))
            if hasattr(le, "setClearButtonEnabled"):
                le.setClearButtonEnabled(True)
            le.setText(current.get(header_text, ""))

            row = i // 2
            col = (i % 2) * 2
            grid.addWidget(lbl, row, col)
            grid.addWidget(le, row, col + 1)
            editors[header_text] = le

        layout.addLayout(grid)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        clear_btn = buttons.addButton(_tr("Clear All"), QDialogButtonBox.ButtonRole.ResetRole)
        clear_btn.clicked.connect(lambda: [le.clear() for le in editors.values()])
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        dlg.adjustSize()

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_filters = fw.get("column_filters", {}).copy()
        for header_text, le in editors.items():
            new_filters[header_text] = le.text()
        fw["column_filters"] = new_filters

        self._update_column_filter_button(category)
        self._apply_filter(category)

    def _update_column_filter_button(self, category):
        fw = self.filter_widgets.get(category)
        if not fw:
            return

        count = 0
        for value in fw.get("column_filters", {}).values():
            if str(value).strip():
                count += 1

        btn = fw.get("btn_toggle")
        if not btn:
            return

        if count > 0:
            btn.setText(_tr("Columns ({0})").format(count))
        else:
            btn.setText(_tr("Columns"))

    def _update_filter_controls(self, category):
        table = self._get_table_for_category(category)
        if not table or category not in self.filter_widgets:
            return

        fw = self.filter_widgets[category]
        combo_col = fw["combo_col"]
        saved_texts = fw.get("column_filters", {})

        combo_col.blockSignals(True)
        current_sel = combo_col.currentData()
        combo_col.clear()
        combo_col.addItem(_tr("All Columns"), "")

        cols_count = table.columnCount()
        col_headers = []
        for c in range(cols_count):
            item = table.horizontalHeaderItem(c)
            header_text = item.text() if item else f"Column {c}"
            col_headers.append(header_text)
            combo_col.addItem(header_text, header_text)

        idx = combo_col.findData(current_sel)
        if idx >= 0:
            combo_col.setCurrentIndex(idx)
        else:
            combo_col.setCurrentIndex(0)
        combo_col.blockSignals(False)

        fw["column_filters"] = {
            header_text: saved_texts.get(header_text, "") for header_text in col_headers
        }

        self._update_column_filter_button(category)
        self._apply_filter(category)

    def _clear_filter(self, category):
        if category not in self.filter_widgets:
            return
        fw = self.filter_widgets[category]
        fw["le_filter"].blockSignals(True)
        fw["le_filter"].clear()
        fw["le_filter"].blockSignals(False)

        fw["column_filters"] = {
            key: "" for key in fw.get("column_filters", {})
        }

        fw["combo_col"].blockSignals(True)
        fw["combo_col"].setCurrentIndex(0)
        fw["combo_col"].blockSignals(False)

        self._update_column_filter_button(category)
        self._apply_filter(category)

    @staticmethod
    def _match_filter_value(val_str, filter_str):
        if val_str is None:
            val_str = ""
        else:
            val_str = str(val_str).strip()

        filter_str = filter_str.strip()
        if not filter_str:
            return True

        ops = [(">=", 2), ("<=", 2), ("!=", 2), (">", 1), ("<", 1), ("=", 1)]
        matched_op = None
        op_len = 0
        for op_str, length in ops:
            if filter_str.startswith(op_str):
                matched_op = op_str
                op_len = length
                break

        if matched_op:
            target_str = filter_str[op_len:].strip()
            try:
                val_num = float(val_str)
                target_num = float(target_str)
                if matched_op == ">=":
                    return val_num >= target_num
                elif matched_op == "<=":
                    return val_num <= target_num
                elif matched_op == ">":
                    return val_num > target_num
                elif matched_op == "<":
                    return val_num < target_num
                elif matched_op == "=":
                    return val_num == target_num
                elif matched_op == "!=":
                    return val_num != target_num
            except ValueError:
                val_lower = val_str.lower()
                target_lower = target_str.lower()
                if matched_op == "=":
                    return val_lower == target_lower
                elif matched_op == "!=":
                    return val_lower != target_lower
                elif matched_op == ">=":
                    return val_lower >= target_lower
                elif matched_op == "<=":
                    return val_lower <= target_lower
                elif matched_op == ">":
                    return val_lower > target_lower
                elif matched_op == "<":
                    return val_lower < target_lower

        return filter_str.lower() in val_str.lower()

    def _apply_filter(self, category):
        table = self._get_table_for_category(category)
        if not table or category not in self.filter_widgets:
            return

        fw = self.filter_widgets[category]
        main_text = fw["le_filter"].text().strip()
        target_col = fw["combo_col"].currentData()
        col_filters = fw.get("column_filters", {})

        total_rows = table.rowCount()
        if total_rows == 0:
            fw["lbl_count"].setText("")
            return

        col_index_map = {}
        for c in range(table.columnCount()):
            header_item = table.horizontalHeaderItem(c)
            header_name = header_item.text() if header_item else f"Column {c}"
            col_index_map[header_name] = c

        visible_count = 0
        table.setSortingEnabled(False)
        for row in range(total_rows):
            row_matches = True

            if main_text:
                if target_col:
                    col_idx = col_index_map.get(target_col)
                    if col_idx is not None:
                        item = table.item(row, col_idx)
                        cell_text = item.text() if item else ""
                        if not self._match_filter_value(cell_text, main_text):
                            row_matches = False
                else:
                    any_match = False
                    for c in range(table.columnCount()):
                        item = table.item(row, c)
                        cell_text = item.text() if item else ""
                        if self._match_filter_value(cell_text, main_text):
                            any_match = True
                            break
                    if not any_match:
                        row_matches = False

            if row_matches:
                for header_name, raw_filter in col_filters.items():
                    col_filter_text = str(raw_filter).strip()
                    if col_filter_text:
                        col_idx = col_index_map.get(header_name)
                        if col_idx is not None:
                            item = table.item(row, col_idx)
                            cell_text = item.text() if item else ""
                            if not self._match_filter_value(cell_text, col_filter_text):
                                row_matches = False
                                break

            table.setRowHidden(row, not row_matches)
            if row_matches:
                visible_count += 1

        table.setSortingEnabled(True)

        self._update_column_filter_button(category)

        if main_text or any(str(val).strip() for val in col_filters.values()):
            fw["lbl_count"].setText(f"{visible_count} / {total_rows}")
        else:
            fw["lbl_count"].setText(f"{total_rows}")

    def _request_add_column(self, stat):
        if stat not in self._model_extra_cols:
            self._model_extra_cols.append(stat)
            # Add the column to the table with placeholder values
            label = next(
                (lbl for lbl, s in self.AVAILABLE_MODEL_STATS if s == stat), stat
            )
            col = self.table_models.columnCount()
            self.table_models.insertColumn(col)
            self.table_models.setHorizontalHeaderItem(col, QTableWidgetItem(label))
            for row in range(self.table_models.rowCount()):
                self.table_models.setItem(row, col, QTableWidgetItem("…"))
            self._update_filter_controls("models")
            # Ask pastastore_viewer to compute and fill the values
            self.add_model_column_requested.emit(stat)

    def _remove_model_column(self, stat):
        if stat not in self._model_extra_cols:
            return
        idx = self._model_extra_cols.index(stat)
        self._model_extra_cols.remove(stat)
        # +2 because columns 0,1 are Name and Oseries
        self.table_models.removeColumn(idx + 2)
        self._update_filter_controls("models")

    def set_model_column_values(self, stat, values):
        """Fill a stat column with computed values. values is a dict {model_name: value}."""
        if stat not in self._model_extra_cols:
            return
        col = self._model_extra_cols.index(stat) + 2  # +2 for Name + Oseries
        self.table_models.setSortingEnabled(False)
        for row in range(self.table_models.rowCount()):
            name_item = self.table_models.item(row, 0)
            if name_item is None:
                continue
            name = name_item.text()
            val = values.get(name)
            cell = QTableWidgetItem()
            if val is not None and not (isinstance(val, float) and np.isnan(val)):
                cell.setData(Qt.ItemDataRole.DisplayRole, float(val))
            else:
                cell.setText("-")
            self.table_models.setItem(row, col, cell)
        self.table_models.setSortingEnabled(True)
        self._apply_filter("models")

    def show_oseries_context_menu(self, position):
        from qgis.PyQt.QtWidgets import QMenu, QAction

        selected_items = self.table_oseries.selectedItems()
        if not selected_items:
            return

        # Get unique names from selection (row-based)
        rows = sorted(list(set(item.row() for item in selected_items)))
        names = [self.table_oseries.item(row, 0).text() for row in rows]

        menu = QMenu()

        # Create Model(s) - at the top
        if len(names) == 1:
            create_model_action = QAction(_tr("Create Model"), self)
            create_model_action.setIcon(
                QgsApplication.getThemeIcon("/mActionNewMemoryLayer.svg")
            )
            create_model_action.triggered.connect(
                lambda: self.create_model_requested.emit(names[0])
            )
            menu.addAction(create_model_action)

            edit_action = QAction(_tr("Edit Series"), self)
            edit_action.setIcon(QgsApplication.getThemeIcon("/mActionEditTable.svg"))
            edit_action.triggered.connect(
                lambda: self.edit_oseries_requested.emit(names[0])
            )
            menu.addAction(edit_action)
        else:
            create_models_action = QAction(_tr("Create Models"), self)
            create_models_action.setIcon(
                QgsApplication.getThemeIcon("/mActionNewMemoryLayer.svg")
            )
            create_models_action.triggered.connect(
                lambda: self.create_models_requested.emit(names)
            )
            menu.addAction(create_models_action)

        select_action = QAction(_tr("Select Models"), self)
        select_action.setIcon(QgsApplication.getThemeIcon("/mActionSelect.svg"))
        select_action.triggered.connect(
            lambda: self.select_models_for_oseries_requested.emit(names)
        )
        menu.addAction(select_action)

        delete_action = QAction(_tr("Delete Oseries"), self)
        delete_action.setIcon(QgsApplication.getThemeIcon("/mActionDeleteSelected.svg"))
        delete_action.triggered.connect(
            lambda: self.delete_oseries_requested.emit(names)
        )
        menu.addAction(delete_action)

        self._exec_menu(menu, self.table_oseries.mapToGlobal(position))

    def show_stresses_context_menu(self, position):
        from qgis.PyQt.QtWidgets import QMenu, QAction

        selected_items = self.table_stresses.selectedItems()
        if not selected_items:
            return

        # Get unique names from selection
        rows = sorted(list(set(item.row() for item in selected_items)))
        names = [self.table_stresses.item(row, 0).text() for row in rows]

        menu = QMenu()

        if len(names) == 1:
            edit_action = QAction(_tr("Edit Series"), self)
            edit_action.setIcon(QgsApplication.getThemeIcon("/mActionEditTable.svg"))
            edit_action.triggered.connect(
                lambda: self.edit_stress_requested.emit(names[0])
            )
            menu.addAction(edit_action)

        select_action = QAction(_tr("Select Models"), self)
        select_action.setIcon(QgsApplication.getThemeIcon("/mActionSelect.svg"))
        select_action.triggered.connect(
            lambda: self.select_models_for_stresses_requested.emit(names)
        )
        menu.addAction(select_action)

        delete_action = QAction(_tr("Delete Stresses"), self)
        delete_action.setIcon(QgsApplication.getThemeIcon("/mActionDeleteSelected.svg"))
        delete_action.triggered.connect(
            lambda: self.delete_stresses_requested.emit(names)
        )
        menu.addAction(delete_action)

        self._exec_menu(menu, self.table_stresses.mapToGlobal(position))

    def show_model_context_menu(self, position):
        from qgis.PyQt.QtWidgets import QMenu, QAction

        item = self.table_models.itemAt(position)
        if item is not None:
            row = item.row()
            if not self.table_models.item(row, 0) in [
                self.table_models.selectedItems()[i]
                if self.table_models.selectedItems()
                else None
                for i in range(len(self.table_models.selectedItems()))
            ]:
                self.table_models.selectRow(row)

        rows = sorted(
            set(i.row() for i in self.table_models.selectedItems())
        )
        if not rows:
            return
        names = [self.table_models.item(r, 0).text() for r in rows if self.table_models.item(r, 0)]
        if not names:
            return

        menu = QMenu()

        # Edit Action (Single selection only)
        if len(names) == 1:
            edit_action = QAction(_tr("View Model"), self)
            edit_action.setIcon(QgsApplication.getThemeIcon("/mActionEditTable.svg"))
            edit_action.triggered.connect(
                lambda: self.edit_model_requested.emit(names[0])
            )
            menu.addAction(edit_action)

            results_action = QAction(_tr("Show Results"), self)
            results_action.setIcon(QgsApplication.getThemeIcon("/mIconTable.svg"))
            results_action.triggered.connect(
                lambda: self.results_requested.emit(names[0])
            )
            menu.addAction(results_action)

            diagnostics_action = QAction(_tr("Show Diagnostics"), self)
            diagnostics_action.setIcon(QgsApplication.getThemeIcon("/mIconTable.svg"))
            diagnostics_action.triggered.connect(
                lambda: self.diagnostics_requested.emit(names[0])
            )
            menu.addAction(diagnostics_action)

            mpl_menu = QMenu("Matplotlib", self)
            mpl_results_action = QAction(_tr("Show Results"), self)
            mpl_results_action.triggered.connect(
                lambda: self.mpl_results_requested.emit(names[0])
            )
            mpl_menu.addAction(mpl_results_action)

            mpl_diag_action = QAction(_tr("Show Diagnostics"), self)
            mpl_diag_action.triggered.connect(
                lambda: self.mpl_diagnostics_requested.emit(names[0])
            )
            mpl_menu.addAction(mpl_diag_action)
            menu.addMenu(mpl_menu)

        select_oseries_action = QAction(_tr("Select Oseries"), self)
        select_oseries_action.setIcon(QgsApplication.getThemeIcon("/mActionSelect.svg"))
        select_oseries_action.triggered.connect(
            lambda: self.select_oseries_for_models_requested.emit(names)
        )
        menu.addAction(select_oseries_action)

        select_stresses_action = QAction(_tr("Select Stresses"), self)
        select_stresses_action.setIcon(QgsApplication.getThemeIcon("/mActionSelect.svg"))
        select_stresses_action.triggered.connect(
            lambda: self.select_stresses_for_models_requested.emit(names)
        )
        menu.addAction(select_stresses_action)

        delete_action = QAction(_tr("Delete Model(s)"), self)
        delete_action.setIcon(QgsApplication.getThemeIcon("/mActionDeleteSelected.svg"))
        delete_action.triggered.connect(
            lambda: self.delete_model_requested.emit(names)
        )
        menu.addAction(delete_action)

        self._exec_menu(menu, self.table_models.mapToGlobal(position))

    def populate_lists(self, store):
        """Fill tables/lists with data from the store."""
        self.table_oseries.setRowCount(0)
        self.table_stresses.setRowCount(0)
        self.table_models.setSortingEnabled(False)
        self.table_models.setRowCount(0)

        if store is None:
            self._update_filter_controls("oseries")
            self._update_filter_controls("stresses")
            self._update_filter_controls("models")
            return

        # Oseries Table
        if len(store.oseries.index) > 0:
            df = store.oseries
            cols = ["Name"] + df.columns.tolist()
            self.table_oseries.setColumnCount(len(cols))
            self.table_oseries.setHorizontalHeaderLabels(cols)
            self.table_oseries.setSortingEnabled(False)
            self.table_oseries.setRowCount(len(df.index))
            for i, idx in enumerate(df.index):
                self.table_oseries.setItem(i, 0, QTableWidgetItem(str(idx)))
                for j, col in enumerate(df.columns):
                    val = store.oseries.loc[idx, col]
                    item = QTableWidgetItem()
                    if isinstance(val, (int, float, np.integer, np.floating)):
                        if not np.isnan(val):
                            item.setData(Qt.ItemDataRole.DisplayRole, float(val))
                        else:
                            item.setText("")
                    else:
                        item.setText(str(val))
                    self.table_oseries.setItem(i, j + 1, item)
            self.table_oseries.setSortingEnabled(True)
            # Set a compact default Name column width.
            self.table_oseries.setColumnWidth(0, 120)

        # Stresses Table
        if hasattr(store, "stresses") and len(store.stresses.index) > 0:
            df = store.stresses
            cols = ["Name"] + df.columns.tolist()
            self.table_stresses.setColumnCount(len(cols))
            self.table_stresses.setHorizontalHeaderLabels(cols)
            self.table_stresses.setSortingEnabled(False)
            self.table_stresses.setRowCount(len(df.index))
            for i, idx in enumerate(df.index):
                self.table_stresses.setItem(i, 0, QTableWidgetItem(str(idx)))
                for j, col in enumerate(df.columns):
                    val = store.stresses.loc[idx, col]
                    item = QTableWidgetItem()
                    if isinstance(val, (int, float, np.integer, np.floating)):
                        if not np.isnan(val):
                            item.setData(Qt.ItemDataRole.DisplayRole, float(val))
                        else:
                            item.setText("")
                    else:
                        item.setText(str(val))
                    self.table_stresses.setItem(i, j + 1, item)
            self.table_stresses.setSortingEnabled(True)
            # Set a compact default Name column width.
            self.table_stresses.setColumnWidth(0, 120)

        # Models Table
        if hasattr(store, "model_names") and len(store.model_names) > 0:
            model_names = sorted(store.model_names)
            # Build oseries-name lookup from store metadata
            oseries_lookup = {}
            try:
                # oseries_models is {oseries_name: [model_name, ...]}
                for oname, mnames in store.oseries_models.items():
                    for mname in mnames:
                        oseries_lookup[mname] = oname
            except Exception:
                pass
            # Rebuild column headers preserving extra cols
            headers = ["Name", "Oseries"] + [
                next((lbl for lbl, s in self.AVAILABLE_MODEL_STATS if s == stat), stat)
                for stat in self._model_extra_cols
            ]
            self.table_models.setColumnCount(len(headers))
            self.table_models.setHorizontalHeaderLabels(headers)
            self.table_models.setRowCount(len(model_names))
            for i, name in enumerate(model_names):
                self.table_models.setItem(i, 0, QTableWidgetItem(name))
                oseries_name = str(oseries_lookup.get(name, ""))
                self.table_models.setItem(i, 1, QTableWidgetItem(oseries_name))
                for j, stat in enumerate(self._model_extra_cols):
                    self.table_models.setItem(i, j + 2, QTableWidgetItem("…"))
            self.table_models.setColumnWidth(0, 120)
            self.table_models.setColumnWidth(1, 120)
            self.table_models.setSortingEnabled(True)
            # Re-request computation for all extra cols
            for stat in self._model_extra_cols:
                self.add_model_column_requested.emit(stat)

            # Populate map plot combo with stats + parameters from store
            try:
                param_names = list(store.get_parameters(progressbar=False).columns)
            except Exception:
                param_names = []
            self.populate_map_plot_combo(param_names)

        self._update_filter_controls("oseries")
        self._update_filter_controls("stresses")
        self._update_filter_controls("models")

    def _update_ramp_preview(self):
        """Render a gradient pixmap for the currently selected color ramp."""
        ramp_name = self.combo_map_ramp.currentData() or "Turbo"
        invert = self.chk_map_invert.isChecked()
        ramp = QgsStyle.defaultStyle().colorRamp(ramp_name)
        if ramp is None:
            self.lbl_ramp_preview.clear()
            return
        if invert:
            ramp.invert()
        w, h = 256, 18
        pixmap = QPixmap(w, h)
        painter = QPainter(pixmap)
        gradient = QLinearGradient(0, 0, w, 0)
        for i in range(21):
            t = i / 20
            c = ramp.color(t)
            gradient.setColorAt(t, c)
        painter.fillRect(pixmap.rect(), gradient)
        painter.end()
        self.lbl_ramp_preview.setPixmap(pixmap)

    def populate_map_plot_combo(self, param_names=None):
        """Fill the map-plot variable combobox with available stats and parameters."""
        self.combo_map_var.blockSignals(True)
        self.combo_map_var.clear()
        for label, stat in self.AVAILABLE_MODEL_STATS:
            self.combo_map_var.addItem(label, f"stat:{stat}")
        if param_names:
            self.combo_map_var.insertSeparator(self.combo_map_var.count())
            for pname in param_names:
                self.combo_map_var.addItem(pname, f"param:{pname}")
        self.combo_map_var.blockSignals(False)

    def get_selected_names(self, category):
        if category == "oseries":
            items = self.table_oseries.selectedItems()
            return sorted(
                list(
                    set(
                        [
                            self.table_oseries.item(item.row(), 0).text()
                            for item in items
                        ]
                    )
                )
            )
        if category == "stresses":
            items = self.table_stresses.selectedItems()
            return sorted(
                list(
                    set(
                        [
                            self.table_stresses.item(item.row(), 0).text()
                            for item in items
                        ]
                    )
                )
            )
        if category == "models":
            rows = sorted(set(i.row() for i in self.table_models.selectedItems()))
            return [
                self.table_models.item(r, 0).text()
                for r in rows
                if self.table_models.item(r, 0)
            ]
        return []

    def select_items_in_list(
        self, category, names, switch_tab=True, trigger_signal=True
    ):
        """Programmatically select items in the corresponding list."""
        list_widget = None
        if category == "oseries":
            list_widget = self.table_oseries
            if switch_tab:
                self.tabs.setCurrentIndex(0)
        elif category == "stresses":
            list_widget = self.table_stresses
            if switch_tab:
                self.tabs.setCurrentIndex(1)
        elif category == "models":
            list_widget = self.table_models
            if switch_tab:
                self.tabs.setCurrentIndex(2)

        if list_widget:
            self.is_updating_selection = True
            try:
                list_widget.clearSelection()
                if not names:
                    return

                if isinstance(list_widget, QTableWidget):
                    selection_model = list_widget.selectionModel()

                    if isinstance(list_widget, QTableWidget):
                        for row in range(list_widget.rowCount()):
                            item = list_widget.item(row, 0)
                            if item and item.text() in names:
                                index = list_widget.model().index(row, 0)
                                selection_model.select(
                                    index,
                                    QItemSelectionModel.SelectionFlag.Select
                                    | QItemSelectionModel.SelectionFlag.Rows,
                                )
                    else:  # QTableWidget (models)
                        for row in range(list_widget.rowCount()):
                            item = list_widget.item(row, 0)
                            if item and item.text() in names:
                                index = list_widget.model().index(row, 0)
                                selection_model.select(
                                    index,
                                    QItemSelectionModel.SelectionFlag.Select
                                    | QItemSelectionModel.SelectionFlag.Rows,
                                )

                    if isinstance(list_widget, QTableWidget):
                        selected = list_widget.selectedItems()
                        if selected:
                            list_widget.scrollToItem(selected[0])
                    else:
                        selected = list_widget.selectedItems()
                        if selected:
                            list_widget.scrollToItem(selected[0])
            finally:
                self.is_updating_selection = False
                if trigger_signal:
                    # Trigger selection once
                    self._on_selection_changed(category)

    def _on_selection_changed(self, category):
        if self.is_updating_selection:
            return
        if category == "oseries":
            items = self.table_oseries.selectedItems()
            names = sorted(
                list(
                    set(
                        [
                            self.table_oseries.item(item.row(), 0).text()
                            for item in items
                        ]
                    )
                )
            )
        elif category == "stresses":
            items = self.table_stresses.selectedItems()
            names = sorted(
                list(
                    set(
                        [
                            self.table_stresses.item(item.row(), 0).text()
                            for item in items
                        ]
                    )
                )
            )
        elif category == "models":
            rows = sorted(set(i.row() for i in self.table_models.selectedItems()))
            names = [
                self.table_models.item(r, 0).text()
                for r in rows
                if self.table_models.item(r, 0)
            ]
        else:
            return

        self.item_selected.emit(category, names)

    def _on_tab_changed(self, index):
        categories = ["oseries", "stresses", "models"]
        if index < len(categories):
            category = categories[index]
            self.tab_changed.emit(category)
            # Also trigger selection update for the new tab
            self._on_selection_changed(category)

    def set_filename(self, filename):
        if filename:
            self.le_filename.setText(filename)
            self.le_filename.setToolTip(filename)
            self.store_path = filename
        else:
            self.le_filename.clear()
            self.le_filename.setToolTip("")
            self.store_path = None

    def save_state_to_project(self):
        """Saves dock state and settings to the QGIS project."""
        if self.is_restoring:
            return

        from qgis.core import QgsProject

        project = QgsProject.instance()
        scope = "PastastoreViewer"

        project.writeEntry(scope, "x_col", self.x_col)
        project.writeEntry(scope, "y_col", self.y_col)
        project.writeEntry(scope, "crs_epsg", self.crs_epsg)
        project.writeEntry(scope, "auto_zoom", "true" if self.auto_zoom else "false")
        project.writeEntry(scope, "is_open", "true" if self.isVisible() else "false")

        if self.store_path:
            project.writeEntry(scope, "store_path", self.store_path)

    def restore_state_from_project(self):
        """Restores dock state and settings from project entries."""
        self.is_restoring = True
        try:
            from qgis.core import QgsProject

            project = QgsProject.instance()
            scope = "PastastoreViewer"

            self.x_col = project.readEntry(scope, "x_col", "x")[0]
            self.y_col = project.readEntry(scope, "y_col", "y")[0]
            self.crs_epsg = project.readEntry(scope, "crs_epsg", "28992")[0]

            zoom_str, ok = project.readEntry(scope, "auto_zoom", "false")
            self.auto_zoom = zoom_str.lower() == "true"

            path, ok = project.readEntry(scope, "store_path", "")
            if path:
                self.load_requested.emit(path)
        finally:
            self.is_restoring = False
            try:
                self.visibilityChanged.disconnect(self.save_state_to_project)
            except:
                pass
            self.visibilityChanged.connect(self.save_state_to_project)

