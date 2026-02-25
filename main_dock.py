# -*- coding: utf-8 -*-

from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QVBoxLayout,
    QWidget,
    QLabel,
    QPushButton,
    QListWidget,
    QTabWidget,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QToolButton,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.core import QgsApplication
import pandas as pd
import numpy as np


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
    select_models_for_oseries_requested = pyqtSignal(list)  # oseries names
    select_models_for_stresses_requested = pyqtSignal(list)  # stresses names
    select_oseries_for_models_requested = pyqtSignal(list)  # model names
    select_stresses_for_models_requested = pyqtSignal(list)  # model names
    edit_oseries_requested = pyqtSignal(str)  # oseries name
    create_model_requested = pyqtSignal(str)  # oseries name
    create_models_requested = pyqtSignal(list)  # oseries names
    import_bro_requested = pyqtSignal()  # Import from BRO

    def __init__(self, parent=None):
        super(PastastoreMainDock, self).__init__("Pastastore Viewer", parent)
        self.setObjectName("PastastoreMainDock")
        self.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)

        # State
        self.is_restoring = False
        self.x_col = "x"
        self.y_col = "y"
        self.crs_epsg = "28992"
        self.auto_zoom = False
        self.store_path = None
        self.is_updating_selection = False

        # Container widget
        self.container = QWidget()
        self.layout = QVBoxLayout()
        self.container.setLayout(self.layout)

        # Top Actions Layout
        top_layout = QHBoxLayout()

        # Filename/Path Edit (Left of Load Button)
        self.le_filename = QLineEdit()
        self.le_filename.setPlaceholderText("No store loaded")
        top_layout.addWidget(self.le_filename)

        # Load Button
        self.btn_load = QPushButton("Load Pastastore Zip")
        self.btn_load.clicked.connect(lambda: self.load_requested.emit(""))
        top_layout.addWidget(self.btn_load)

        # New Button
        self.btn_new = QPushButton("New Pastastore")
        self.btn_new.clicked.connect(lambda: self.new_requested.emit())
        top_layout.addWidget(self.btn_new)

        # Save Button
        self.btn_save = QPushButton("Save Pastastore Zip")
        self.btn_save.clicked.connect(lambda: self.save_requested.emit())
        top_layout.addWidget(self.btn_save)

        # Settings Button
        self.btn_settings = QPushButton("Settings")
        self.btn_settings.clicked.connect(lambda: self.settings_requested.emit())
        top_layout.addWidget(self.btn_settings)

        self.layout.addLayout(top_layout)

        # Tabs for lists
        self.tabs = QTabWidget()
        
        # Create oseries tab with toolbar
        oseries_widget = QWidget()
        oseries_layout = QVBoxLayout()
        oseries_layout.setContentsMargins(0, 0, 0, 0)
        
        # Oseries table
        self.table_oseries = QTableWidget()
        oseries_layout.addWidget(self.table_oseries)
        
        # Import button below oseries table
        oseries_button_layout = QHBoxLayout()
        self.btn_import = QToolButton()
        self.btn_import.setText("Import Data")
        self.btn_import.setIcon(QgsApplication.getThemeIcon("/mActionAdd.svg"))
        self.btn_import.setToolTip("Import data from external sources")
        self.btn_import.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        import_menu = QMenu()
        import_bro_action = import_menu.addAction("Download from BRO")
        import_bro_action.triggered.connect(lambda: self.import_bro_requested.emit())
        self.btn_import.setMenu(import_menu)
        self.btn_import.setPopupMode(QToolButton.InstantPopup)
        oseries_button_layout.addWidget(self.btn_import)
        oseries_button_layout.addStretch()
        oseries_layout.addLayout(oseries_button_layout)
        
        oseries_widget.setLayout(oseries_layout)
        
        self.table_stresses = QTableWidget()
        self.list_models = QListWidget()
        self.list_models.setSelectionMode(QListWidget.ExtendedSelection)
        self.list_models.setContextMenuPolicy(Qt.CustomContextMenu)

        for table in [self.table_oseries, self.table_stresses]:
            table.setSelectionBehavior(QTableWidget.SelectRows)
            table.setSelectionMode(QTableWidget.ExtendedSelection)
            # Allow resizing
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
            table.horizontalHeader().setStretchLastSection(True)
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.setSortingEnabled(True)
            table.setContextMenuPolicy(Qt.CustomContextMenu)

        self.tabs.addTab(oseries_widget, "Oseries")
        self.tabs.addTab(self.table_stresses, "Stresses")
        self.tabs.addTab(self.list_models, "Models")

        self.table_oseries.itemSelectionChanged.connect(
            lambda: self._on_selection_changed("oseries")
        )
        self.table_stresses.itemSelectionChanged.connect(
            lambda: self._on_selection_changed("stresses")
        )
        self.list_models.itemSelectionChanged.connect(
            lambda: self._on_selection_changed("models")
        )

        self.table_oseries.customContextMenuRequested.connect(
            self.show_oseries_context_menu
        )
        self.table_stresses.customContextMenuRequested.connect(
            self.show_stresses_context_menu
        )
        self.list_models.customContextMenuRequested.connect(
            self.show_model_context_menu
        )
        self.table_oseries.itemDoubleClicked.connect(self._on_oseries_double_clicked)
        self.list_models.itemDoubleClicked.connect(
            lambda item: self.edit_model_requested.emit(item.text())
        )

        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.layout.addWidget(self.tabs)
        self.setWidget(self.container)

    def _on_oseries_double_clicked(self, item):
        if item is None:
            return
        name_item = self.table_oseries.item(item.row(), 0)
        if name_item:
            self.create_model_requested.emit(name_item.text())

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
            create_model_action = QAction("Create Model", self)
            create_model_action.setIcon(
                QgsApplication.getThemeIcon("/mActionNewMemoryLayer.svg")
            )
            create_model_action.triggered.connect(
                lambda: self.create_model_requested.emit(names[0])
            )
            menu.addAction(create_model_action)

            edit_action = QAction("Edit Series", self)
            edit_action.setIcon(QgsApplication.getThemeIcon("/mActionEditTable.svg"))
            edit_action.triggered.connect(
                lambda: self.edit_oseries_requested.emit(names[0])
            )
            menu.addAction(edit_action)
        else:
            create_models_action = QAction("Create Models", self)
            create_models_action.setIcon(
                QgsApplication.getThemeIcon("/mActionNewMemoryLayer.svg")
            )
            create_models_action.triggered.connect(
                lambda: self.create_models_requested.emit(names)
            )
            menu.addAction(create_models_action)

        select_action = QAction("Select Models", self)
        select_action.setIcon(QgsApplication.getThemeIcon("/mActionSelect.svg"))
        select_action.triggered.connect(
            lambda: self.select_models_for_oseries_requested.emit(names)
        )
        menu.addAction(select_action)

        delete_action = QAction("Delete Oseries", self)
        delete_action.setIcon(QgsApplication.getThemeIcon("/mActionDeleteSelected.svg"))
        delete_action.triggered.connect(
            lambda: self.delete_oseries_requested.emit(names)
        )
        menu.addAction(delete_action)

        menu.exec_(self.table_oseries.mapToGlobal(position))

    def show_stresses_context_menu(self, position):
        from qgis.PyQt.QtWidgets import QMenu, QAction

        selected_items = self.table_stresses.selectedItems()
        if not selected_items:
            return

        # Get unique names from selection
        rows = sorted(list(set(item.row() for item in selected_items)))
        names = [self.table_stresses.item(row, 0).text() for row in rows]

        menu = QMenu()
        select_action = QAction("Select Models", self)
        select_action.setIcon(QgsApplication.getThemeIcon("/mActionSelect.svg"))
        select_action.triggered.connect(
            lambda: self.select_models_for_stresses_requested.emit(names)
        )
        menu.addAction(select_action)

        delete_action = QAction("Delete Stresses", self)
        delete_action.setIcon(QgsApplication.getThemeIcon("/mActionDeleteSelected.svg"))
        delete_action.triggered.connect(
            lambda: self.delete_stresses_requested.emit(names)
        )
        menu.addAction(delete_action)

        menu.exec_(self.table_stresses.mapToGlobal(position))

    def show_model_context_menu(self, position):
        from qgis.PyQt.QtWidgets import QMenu, QAction

        if not self.list_models.selectedItems():
            item = self.list_models.itemAt(position)
            if item is not None:
                self.list_models.setCurrentItem(item)

        items = self.list_models.selectedItems()
        if not items:
            return

        names = [i.text() for i in items]

        menu = QMenu()

        # Edit Action (Single selection only)
        if len(items) == 1:
            edit_action = QAction("Edit Model", self)
            edit_action.setIcon(QgsApplication.getThemeIcon("/mActionEditTable.svg"))
            edit_action.triggered.connect(
                lambda: self.edit_model_requested.emit(items[0].text())
            )
            menu.addAction(edit_action)

            results_action = QAction("Show Results", self)
            results_action.setIcon(QgsApplication.getThemeIcon("/mIconTable.svg"))
            results_action.triggered.connect(
                lambda: self.results_requested.emit(items[0].text())
            )
            menu.addAction(results_action)

        select_oseries_action = QAction("Select Oseries", self)
        select_oseries_action.setIcon(QgsApplication.getThemeIcon("/mActionSelect.svg"))
        select_oseries_action.triggered.connect(
            lambda: self.select_oseries_for_models_requested.emit(names)
        )
        menu.addAction(select_oseries_action)

        select_stresses_action = QAction("Select Stresses", self)
        select_stresses_action.setIcon(QgsApplication.getThemeIcon("/mActionSelect.svg"))
        select_stresses_action.triggered.connect(
            lambda: self.select_stresses_for_models_requested.emit(names)
        )
        menu.addAction(select_stresses_action)

        delete_action = QAction("Delete Model(s)", self)
        delete_action.setIcon(QgsApplication.getThemeIcon("/mActionDeleteSelected.svg"))
        delete_action.triggered.connect(
            lambda: self.delete_model_requested.emit(names)
        )
        menu.addAction(delete_action)

        menu.exec_(self.list_models.mapToGlobal(position))

    def populate_lists(self, store):
        """Fill tables/lists with data from the store."""
        self.table_oseries.setRowCount(0)
        self.table_stresses.setRowCount(0)
        self.list_models.clear()

        if store is None:
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
                            item.setData(Qt.DisplayRole, float(val))
                        else:
                            item.setText("")
                    else:
                        item.setText(str(val))
                    self.table_oseries.setItem(i, j + 1, item)
            self.table_oseries.setSortingEnabled(True)
            # Set Name column width
            self.table_oseries.setColumnWidth(0, 200)

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
                            item.setData(Qt.DisplayRole, float(val))
                        else:
                            item.setText("")
                    else:
                        item.setText(str(val))
                    self.table_stresses.setItem(i, j + 1, item)
            self.table_stresses.setSortingEnabled(True)
            # Set Name column width
            self.table_stresses.setColumnWidth(0, 200)

        # Models List (Keep as list as requested)
        if hasattr(store, "model_names") and len(store.model_names) > 0:
            self.list_models.addItems(store.model_names)

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
            items = self.list_models.selectedItems()
            return [item.text() for item in items]
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
            list_widget = self.list_models
            if switch_tab:
                self.tabs.setCurrentIndex(2)

        if list_widget:
            self.is_updating_selection = True
            try:
                list_widget.clearSelection()
                if not names:
                    return

                if isinstance(list_widget, (QTableWidget, QListWidget)):
                    from qgis.PyQt.QtCore import QItemSelectionModel

                    selection_model = list_widget.selectionModel()

                    if isinstance(list_widget, QTableWidget):
                        for row in range(list_widget.rowCount()):
                            item = list_widget.item(row, 0)
                            if item and item.text() in names:
                                index = list_widget.model().index(row, 0)
                                selection_model.select(
                                    index,
                                    QItemSelectionModel.Select
                                    | QItemSelectionModel.Rows,
                                )
                    else:  # QListWidget
                        for name in names:
                            items = list_widget.findItems(name, Qt.MatchExactly)
                            for item in items:
                                index = list_widget.indexFromItem(item)
                                selection_model.select(
                                    index, QItemSelectionModel.Select
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
            items = self.list_models.selectedItems()
            names = [item.text() for item in items]
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

