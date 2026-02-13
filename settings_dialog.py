# -*- coding: utf-8 -*-

from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QDialogButtonBox

class PastastoreSettingsDialog(QDialog):
    def __init__(self, current_x='x', current_y='y', parent=None, **kwargs):
        super(PastastoreSettingsDialog, self).__init__(parent)
        self.setWindowTitle("Pastastore Settings")
        
        layout = QVBoxLayout()
        
        layout.addWidget(QLabel("X Coordinate Column Name:"))
        self.x_edit = QLineEdit(current_x)
        layout.addWidget(self.x_edit)
        
        layout.addWidget(QLabel("Y Coordinate Column Name:"))
        self.y_edit = QLineEdit(current_y)
        layout.addWidget(self.y_edit)
        
        layout.addWidget(QLabel("CRS (EPSG code):"))
        self.crs_edit = QLineEdit(str(kwargs.get('current_crs', 28992)))
        layout.addWidget(self.crs_edit)
        
        from qgis.PyQt.QtWidgets import QCheckBox
        self.cb_zoom = QCheckBox("Auto-pan to selection")
        self.cb_zoom.setChecked(kwargs.get('current_zoom', False))
        layout.addWidget(self.cb_zoom)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        
        layout.addWidget(buttons)
        self.setLayout(layout)
        
    def get_settings(self):
        return {
            'x': self.x_edit.text(),
            'y': self.y_edit.text(),
            'crs': self.crs_edit.text(),
            'zoom': self.cb_zoom.isChecked()
        }
