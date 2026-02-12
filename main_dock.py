# -*- coding: utf-8 -*-

from qgis.PyQt.QtWidgets import (
    QDockWidget, QVBoxLayout, QWidget, QLabel, 
    QPushButton, QListWidget, QTabWidget, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QHBoxLayout,
    QLineEdit
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
import pandas as pd
import numpy as np

class PastastoreMainDock(QDockWidget):
    """Main Dock widget for loading and browsing Pastastore data."""
    
    load_requested = pyqtSignal(str) # path (optional)
    item_selected = pyqtSignal(str, list) # category, names (list)
    settings_requested = pyqtSignal()

    def __init__(self, parent=None):
        super(PastastoreMainDock, self).__init__("Pastastore Viewer", parent)
        self.setObjectName("PastastoreMainDock")
        self.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)
        
        # State
        self.is_restoring = False
        self.x_col = 'x'
        self.y_col = 'y'
        self.crs_epsg = '28992'
        self.auto_zoom = False
        self.store_path = None

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
        
        # Settings Button
        self.btn_settings = QPushButton("Settings")
        self.btn_settings.clicked.connect(lambda: self.settings_requested.emit())
        top_layout.addWidget(self.btn_settings)

        self.layout.addLayout(top_layout)
        
        # Tabs for lists
        self.tabs = QTabWidget()
        self.table_oseries = QTableWidget()
        self.table_stresses = QTableWidget()
        self.list_models = QListWidget()
        
        for table in [self.table_oseries, self.table_stresses]:
            table.setSelectionBehavior(QTableWidget.SelectRows)
            table.setSelectionMode(QTableWidget.ExtendedSelection)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            table.setEditTriggers(QTableWidget.NoEditTriggers)
        
        self.tabs.addTab(self.table_oseries, "Oseries")
        self.tabs.addTab(self.table_stresses, "Stresses")
        self.tabs.addTab(self.list_models, "Models")
        
        self.table_oseries.itemSelectionChanged.connect(lambda: self._on_selection_changed("oseries"))
        self.table_stresses.itemSelectionChanged.connect(lambda: self._on_selection_changed("stresses"))
        self.list_models.itemClicked.connect(lambda item: self.item_selected.emit("models", [item.text()]))
        
        self.layout.addWidget(self.tabs)
        self.setWidget(self.container)

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
            self.table_oseries.setRowCount(len(df.index))
            for i, idx in enumerate(df.index):
                self.table_oseries.setItem(i, 0, QTableWidgetItem(str(idx)))
                for j, col in enumerate(df.columns):
                     val = df.loc[idx, col]
                     self.table_oseries.setItem(i, j+1, QTableWidgetItem(str(val)))
            
        # Stresses Table
        if hasattr(store, 'stresses') and len(store.stresses.index) > 0:
            df = store.stresses
            cols = ["Name"] + df.columns.tolist()
            self.table_stresses.setColumnCount(len(cols))
            self.table_stresses.setHorizontalHeaderLabels(cols)
            self.table_stresses.setRowCount(len(df.index))
            for i, idx in enumerate(df.index):
                self.table_stresses.setItem(i, 0, QTableWidgetItem(str(idx)))
                for j, col in enumerate(df.columns):
                    val = df.loc[idx, col]
                    self.table_stresses.setItem(i, j+1, QTableWidgetItem(str(val)))
            
        # Models List (Keep as list as requested)
        if hasattr(store, 'models') and len(store.models) > 0:
            self.list_models.addItems(store.models)

    def select_item_in_list(self, category, name):
        """Programmatically select an item in the corresponding list."""
        list_widget = None
        if category == "oseries":
            list_widget = self.table_oseries
            self.tabs.setCurrentIndex(0)
        elif category == "stresses":
            list_widget = self.table_stresses
            self.tabs.setCurrentIndex(1)
        elif category == "models":
            list_widget = self.list_models
            self.tabs.setCurrentIndex(2)
            
        if list_widget:
            if isinstance(list_widget, QTableWidget):
                items = list_widget.findItems(name, Qt.MatchExactly)
                if items:
                    list_widget.setCurrentItem(items[0])
            else:
                items = list_widget.findItems(name, Qt.MatchExactly)
                if items:
                    list_widget.setCurrentItem(items[0])

    def _on_selection_changed(self, category):
        if category == "oseries":
            items = self.table_oseries.selectedItems()
            names = sorted(list(set([self.table_oseries.item(item.row(), 0).text() for item in items])))
        elif category == "stresses":
            items = self.table_stresses.selectedItems()
            names = sorted(list(set([self.table_stresses.item(item.row(), 0).text() for item in items])))
        else:
            return
            
        self.item_selected.emit(category, names)

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
            self.auto_zoom = (zoom_str.lower() == 'true')
            
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
