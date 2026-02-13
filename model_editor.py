from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QDialogButtonBox,
    QLabel, QCheckBox, QGroupBox, QComboBox, QMessageBox, QWidget,
    QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QSplitter,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QDateEdit
)
from qgis.PyQt.QtCore import Qt, QDate
import pandas as pd
import numpy as np
import pastastore as pst
import pastas as ps
import pyqtgraph as pg
from pyqtgraph import DateAxisItem

class ModelEditorDialog(QDialog):
    """Dialog to edit a Pastas model with advanced stressmodel configuration."""

    def __init__(self, model: ps.Model, store: pst.PastaStore, parent=None):
        super(ModelEditorDialog, self).__init__(parent)
        self.setWindowTitle("Edit Model")
        self.resize(800, 800) 
        
        self.original_model = model
        self.store = store
        self.new_model = None
        
        # Helper to get available series
        self.available_stresses = []
        if hasattr(store, 'stresses'):
            self.available_stresses = sorted(store.stresses.index.tolist())
            
        # Data structure to hold current settings
        self.stressmodel_settings = self._parse_current_model(model)
        
        # UI Layout
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        
        # Plot Widget (Top)
        self.plot_widget = pg.PlotWidget(axisItems={'bottom': DateAxisItem()})
        self.plot_widget.setBackground('w')
        self.plot_widget.showGrid(x=True, y=True)
        for axis in ['bottom', 'left']:
            ax = self.plot_widget.getAxis(axis)
            ax.setPen('k')
            ax.setTextPen('k')
        self.layout.addWidget(self.plot_widget)
        
        # Middle: Tabs
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)
        
        # Tab 0: General Settings
        self.tab_general = QWidget()
        self.vbox_general = QVBoxLayout()
        self.tab_general.setLayout(self.vbox_general)
        
        self.group_general = QGroupBox("Model Settings")
        self.form_general = QFormLayout()
        
        self.le_name = QLineEdit(model.name)
        
        # Date Selectors for Tmin/Tmax
        self.de_tmin = QDateEdit()
        self.de_tmin.setCalendarPopup(True)
        self.de_tmax = QDateEdit()
        self.de_tmax.setCalendarPopup(True)
        
        # Set dates from model
        tmin = model.settings.get("tmin")
        tmax = model.settings.get("tmax")
        # Find absolute data bounds for calendar range
        obs = model.observations()
        if not obs.empty:
            abs_min = QDate.fromString(str(obs.index.min().date()), "yyyy-MM-dd")
            abs_max = QDate.fromString(str(obs.index.max().date()), "yyyy-MM-dd")
            self.de_tmin.setMinimumDate(abs_min)
            self.de_tmin.setMaximumDate(abs_max)
            self.de_tmax.setMinimumDate(abs_min)
            self.de_tmax.setMaximumDate(abs_max)
            
            if tmin: self.de_tmin.setDate(QDate.fromString(str(pd.to_datetime(tmin).date()), "yyyy-MM-dd"))
            else: self.de_tmin.setDate(abs_min)
            
            if tmax: self.de_tmax.setDate(QDate.fromString(str(pd.to_datetime(tmax).date()), "yyyy-MM-dd"))
            else: self.de_tmax.setDate(abs_max)
        
        # Frequency Dropdown
        self.cbo_freq = QComboBox()
        self.cbo_freq.addItems(["D", "H", "W", "M", "Y", "7D", "14D"])
        self.cbo_freq.setEditable(True) # Allow custom frequencies
        freq = model.settings.get("freq", "D")
        self.cbo_freq.setCurrentText(str(freq))
        
        self.form_general.addRow("Model Name:", self.le_name)
        self.form_general.addRow("Tmin:", self.de_tmin)
        self.form_general.addRow("Tmax:", self.de_tmax)
        self.form_general.addRow("Frequency:", self.cbo_freq)
        self.group_general.setLayout(self.form_general)
        self.vbox_general.addWidget(self.group_general)
        self.vbox_general.addStretch()
        self.tabs.addTab(self.tab_general, "General")

        # Tab 1: Stressmodels
        self.tab_stressmodels = QWidget()
        self.hbox_stresses = QHBoxLayout()
        self.tab_stressmodels.setLayout(self.hbox_stresses)
        self.tabs.addTab(self.tab_stressmodels, "Stressmodels")

        # Tab 2: Parameters
        self.tab_parameters = QWidget()
        self.vbox_params = QVBoxLayout()
        self.tab_parameters.setLayout(self.vbox_params)
        self.table_params = QTableWidget()
        self.table_params.setColumnCount(6)
        self.table_params.setHorizontalHeaderLabels(["initial", "optimal", "pmin", "pmax", "vary", "stderr"])
        self.table_params.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.vbox_params.addWidget(self.table_params)
        self.tabs.addTab(self.tab_parameters, "Parameters")
        
        # Master: List
        self.vbox_list = QVBoxLayout()
        self.list_stresses = QListWidget()
        self.list_stresses.currentRowChanged.connect(self.on_selection_changed)
        self.vbox_list.addWidget(self.list_stresses)
        
        self.hbox_list_btns = QHBoxLayout()
        self.btn_add = QPushButton("+")
        self.btn_remove = QPushButton("-")
        self.btn_add.clicked.connect(self.add_stressmodel)
        self.btn_remove.clicked.connect(self.remove_stressmodel)
        self.hbox_list_btns.addWidget(self.btn_add)
        self.hbox_list_btns.addWidget(self.btn_remove)
        self.vbox_list.addLayout(self.hbox_list_btns)
        
        self.hbox_stresses.addLayout(self.vbox_list, 1)
        
        # Detail: Configuration
        self.group_detail = QGroupBox("Configuration")
        self.form_detail = QFormLayout()
        self.group_detail.setLayout(self.form_detail)
        
        # Detail Widgets
        self.detail_name = QLineEdit()
        self.detail_name.editingFinished.connect(self.save_detail_name)
        
        self.detail_type = QComboBox()
        self.detail_type.addItems(["StressModel", "RechargeModel", "StepModel", "LinearTrend"])
        self.detail_type.currentTextChanged.connect(self.save_detail_type)
        
        self.detail_rfunc = QComboBox()
        self.detail_rfunc.addItems(["Gamma", "Exponential", "Hantush", "Polder", "One", "None"])
        self.detail_rfunc.currentTextChanged.connect(self.save_detail_rfunc)
        
        self.detail_recharge = QComboBox()
        self.detail_recharge.addItems(["Linear", "FlexModel", "Berendrecht"])
        self.detail_recharge.currentTextChanged.connect(self.save_detail_recharge)
        
        self.detail_up = QCheckBox("Up (Positive Response)")
        self.detail_up.toggled.connect(self.save_detail_up)
        
        # Inputs (Dynamic)
        self.detail_input1_lbl = QLabel("Input 1:")
        self.detail_input1 = QComboBox()
        self.detail_input1.addItems(self.available_stresses)
        self.detail_input1.currentTextChanged.connect(self.save_detail_input1)
        
        self.detail_input2_lbl = QLabel("Input 2 (Evap):")
        self.detail_input2 = QComboBox()
        self.detail_input2.addItems(self.available_stresses)
        self.detail_input2.currentTextChanged.connect(self.save_detail_input2)
        
        self.form_detail.addRow("Name:", self.detail_name)
        self.form_detail.addRow("Type:", self.detail_type)
        self.form_detail.addRow("Response Function:", self.detail_rfunc)
        self.form_detail.addRow("Recharge Type:", self.detail_recharge)
        self.form_detail.addRow("", self.detail_up)
        self.form_detail.addRow(self.detail_input1_lbl, self.detail_input1)
        self.form_detail.addRow(self.detail_input2_lbl, self.detail_input2)
        
        self.hbox_stresses.addWidget(self.group_detail, 2)
        
        # Statistics
        self.lbl_stats = QLabel("Stats: E.V.P.: - | R2: -")
        self.layout.addWidget(self.lbl_stats)
        
        # Bottom Buttons
        self.btn_solve = QPushButton("Solve")
        self.btn_solve.clicked.connect(self.solve_model)
        self.layout.addWidget(self.btn_solve)
        
        self.button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.button_box.button(QDialogButtonBox.Save).setText("Save Model")
        self.layout.addWidget(self.button_box)
        
        # Initialize UI
        self.populate_list()
        if self.stressmodel_settings:
            self.list_stresses.setCurrentRow(0)
        
        # Show stats and plot
        self.update_stats_label(model)
        self.update_plot(model)
        self.update_parameters_table(model)

    def update_parameters_table(self, model):
        self.table_params.setRowCount(0)
        if hasattr(model, 'parameters'):
            df = model.parameters
            # Order: initial, optimal, pmin, pmax, vary, stderr
            # Note: 'stderr' might be missing if not solved or from earlier version? 
            # Usually present after solve.
            self.table_params.setRowCount(len(df))
            for i, (idx, row) in enumerate(df.iterrows()):
                # Row Header
                self.table_params.setVerticalHeaderItem(i, QTableWidgetItem(str(idx)))
                
                # Cols
                cols = ["initial", "optimal", "pmin", "pmax", "vary", "stderr"]
                for j, col in enumerate(cols):
                    val = row.get(col, "")
                    item = QTableWidgetItem(str(val))
                    
                    # Editable columns: initial, pmin, pmax, vary
                    # Optimal and stderr are results (read-only mostly, but allow copy)
                    if col in ["optimal", "stderr"]:
                        item.setFlags(item.flags() ^ Qt.ItemIsEditable)
                    
                    self.table_params.setItem(i, j, item)
        
    def update_plot(self, model):
        self.plot_widget.clear()
        self.plot_widget.addLegend()
        
        # Plot Observations
        if hasattr(model, 'observations'):
            obs = model.observations()
            if obs is not None and not obs.empty:
                # Standard timestamp plotting (epoch)
                x = obs.index.view(np.int64) // 10**9
                y = obs.values
                self.plot_widget.plot(x, y, pen=None, symbol='o', symbolSize=5, symbolBrush='k', name="Observations")

        # Plot Simulation
        try:
            sim = model.simulate()
            if sim is not None and not sim.empty:
                x = sim.index.view(np.int64) // 10**9
                y = sim.values
                self.plot_widget.plot(x, y, pen=pg.mkPen('r', width=2), name="Simulation")
        except:
            pass

    def _parse_current_model(self, model):
        """Parse existing model structure into settings list."""
        settings = []
        for name, sm in model.stressmodels.items():
            entry = {
                'name': name, 
                'inputs': [], 
                'up': True, 
                'rfunc': 'Gamma', 
                'type': 'StressModel', 
                'recharge': 'Linear',
                'settings': sm.get_settings() # Current stress settings
            }
            
            # Determine Type
            cls_name = sm.__class__.__name__
            entry['type'] = cls_name
            
            # Rfunc
            if hasattr(sm, 'rfunc') and sm.rfunc:
                entry['rfunc'] = sm.rfunc.__class__.__name__
                # Retrieve 'up' from rfunc
                if hasattr(sm.rfunc, 'up'):
                    entry['up'] = bool(sm.rfunc.up)
            else:
                entry['rfunc'] = 'None'
                
            # Inputs
            if hasattr(sm, 'stress'):
                if isinstance(sm.stress, list):
                    for s in sm.stress:
                        if hasattr(s, 'name'): entry['inputs'].append(s.name)
                else: 
                     if hasattr(sm.stress, 'name'): entry['inputs'].append(sm.stress.name)
            
            # RechargeModel specific
            if cls_name == 'RechargeModel':
                 if hasattr(sm, 'prec'):
                     entry['inputs'] = []
                     if hasattr(sm.prec, 'name'): entry['inputs'].append(sm.prec.name)
                     if hasattr(sm.evap, 'name'): entry['inputs'].append(sm.evap.name)
                     entry['recharge'] = sm.recharge.__class__.__name__
            
            settings.append(entry)
        return settings

    def populate_list(self):
        self.list_stresses.clear()
        for s in self.stressmodel_settings:
            self.list_stresses.addItem(s['name'])
            
    def on_selection_changed(self, row):
        if row < 0 or row >= len(self.stressmodel_settings):
            self.group_detail.setEnabled(False)
            return
            
        self.group_detail.setEnabled(True)
        s = self.stressmodel_settings[row]
        
        # Block signals to prevent feedback loop
        self.detail_name.blockSignals(True)
        self.detail_type.blockSignals(True)
        self.detail_rfunc.blockSignals(True)
        self.detail_recharge.blockSignals(True)
        self.detail_up.blockSignals(True)
        self.detail_input1.blockSignals(True)
        self.detail_input2.blockSignals(True)
        
        self.detail_name.setText(s['name'])
        self.detail_type.setCurrentText(s['type'])
        
        # Update visibility based on Type
        self.update_detail_visibility(s['type'])
        
        if s['type'] != 'LinearTrend':
            self.detail_rfunc.setCurrentText(s['rfunc'])
            self.detail_recharge.setCurrentText(s.get('recharge', 'Linear'))
            self.detail_up.setChecked(s.get('up', True))
            
            if len(s['inputs']) > 0:
                self.detail_input1.setCurrentText(s['inputs'][0])
            if len(s['inputs']) > 1:
                self.detail_input2.setCurrentText(s['inputs'][1])
            
        self.detail_name.blockSignals(False)
        self.detail_type.blockSignals(False)
        self.detail_rfunc.blockSignals(False)
        self.detail_recharge.blockSignals(False)
        self.detail_up.blockSignals(False)
        self.detail_input1.blockSignals(False)
        self.detail_input2.blockSignals(False)

    def update_detail_visibility(self, type_name):
        # Default visibility
        self.detail_rfunc.setVisible(True)
        self.detail_up.setVisible(True)
        self.detail_input1.setVisible(True)
        self.detail_input2.setVisible(False)
        self.detail_input1_lbl.setVisible(True)
        self.detail_input2_lbl.setVisible(False)
        self.form_detail.labelForField(self.detail_rfunc).setVisible(True)
        self.detail_recharge.setVisible(False)
        self.form_detail.labelForField(self.detail_recharge).setVisible(False)
        
        if type_name == 'StressModel':
            self.detail_input1_lbl.setText("Stress:")
        elif type_name == 'RechargeModel':
            self.detail_input1_lbl.setText("Precipitation:")
            self.detail_input2_lbl.setText("Evaporation:")
            self.detail_input2.setVisible(True)
            self.detail_input2_lbl.setVisible(True)
            self.detail_up.setVisible(False) # Rfunc controls parameters mostly
            self.detail_recharge.setVisible(True)
            self.form_detail.labelForField(self.detail_recharge).setVisible(True)
        elif type_name == 'StepModel':
            self.detail_input1_lbl.setText("Step Start (Not Impl):")
            # StepModel needs more logic, keep simple for now
            self.detail_rfunc.setVisible(False)
            self.form_detail.labelForField(self.detail_rfunc).setVisible(False)
        elif type_name == 'LinearTrend':
            self.detail_rfunc.setVisible(False)
            self.detail_up.setVisible(False)
            self.detail_input1.setVisible(False)
            self.detail_input1_lbl.setVisible(False)
            self.form_detail.labelForField(self.detail_rfunc).setVisible(False)

    def get_current_setting(self):
        row = self.list_stresses.currentRow()
        if row >= 0:
            return self.stressmodel_settings[row]
        return None

    def save_detail_name(self):
        s = self.get_current_setting()
        if s:
            new_name = self.detail_name.text()
            s['name'] = new_name
            self.list_stresses.item(self.list_stresses.currentRow()).setText(new_name)

    def save_detail_type(self, text):
        s = self.get_current_setting()
        if s:
            s['type'] = text
            self.update_detail_visibility(text)
            
    def save_detail_rfunc(self, text):
        s = self.get_current_setting()
        if s: s['rfunc'] = text

    def save_detail_recharge(self, text):
        s = self.get_current_setting()
        if s: s['recharge'] = text

    def save_detail_up(self, checked):
        s = self.get_current_setting()
        if s: s['up'] = checked
        
    def save_detail_input1(self, text):
        s = self.get_current_setting()
        if s:
            if len(s['inputs']) == 0: s['inputs'].append(text)
            else: s['inputs'][0] = text
            
    def save_detail_input2(self, text):
        s = self.get_current_setting()
        if s:
            if len(s['inputs']) < 2: 
                while len(s['inputs']) < 2: s['inputs'].append(text)
            else: s['inputs'][1] = text

    def add_stressmodel(self):
        # Default new model
        name = f"stress_{len(self.stressmodel_settings)+1}"
        entry = {
            'name': name, 
            'type': 'StressModel', 
            'rfunc': 'Gamma', 
            'recharge': 'Linear',
            'up': True, 
            'inputs': [self.available_stresses[0] if self.available_stresses else ""]
        }
        self.stressmodel_settings.append(entry)
        self.list_stresses.addItem(name)
        self.list_stresses.setCurrentRow(len(self.stressmodel_settings)-1)

    def remove_stressmodel(self):
        row = self.list_stresses.currentRow()
        if row >= 0:
            del self.stressmodel_settings[row]
            self.list_stresses.takeItem(row)

    def update_stats_label(self, model):
        try:
             evp = model.stats.evp()
             r2 = model.stats.rsq()
             self.lbl_stats.setText(f"Stats: E.V.P.: {evp:.2f} | R2: {r2:.3f}")
        except:
             self.lbl_stats.setText("Stats: Not solved")

    def solve_model(self):
        try:
            model = self.original_model
            
            # Apply General settings
            tmin = self.de_tmin.date().toString("yyyy-MM-dd")
            tmax = self.de_tmax.date().toString("yyyy-MM-dd")
            freq = self.cbo_freq.currentText()
            
            # Reconstruct Stressmodels
            # We must remove all old ones and add new ones based on settings
            # Prone to error if names mismatch, so we delete loop safety
            for name in list(model.stressmodels.keys()):
                model.del_stressmodel(name)
                
            for s in self.stressmodel_settings:
                try:
                    name = s['name']
                    sm_type = s['type']
                    rfunc_name = s['rfunc']
                    inputs = s.get('inputs', [])
                    settings_dict = s.get('settings', {})
                    
                    # Rfunc class
                    rfunc = None
                    if rfunc_name != 'None' and hasattr(ps, rfunc_name):
                        rfunc = getattr(ps, rfunc_name)()
                        
                    if sm_type == 'StressModel':
                         if not inputs: continue
                         ts = self.store.get_stresses(inputs[0])
                         # Pass settings for the specific time series component
                         sm_settings = settings_dict.get(inputs[0])
                         sm = ps.StressModel(ts, rfunc=rfunc, name=name, up=s.get('up', True), settings=sm_settings)
                         model.add_stressmodel(sm)
                         
                    elif sm_type == 'RechargeModel':
                         if len(inputs) < 2: continue
                         prec = self.store.get_stresses(inputs[0])
                         evap = self.store.get_stresses(inputs[1])
                         
                         recharge = ps.rch.Linear()
                         if s.get('recharge') == 'FlexModel': recharge = ps.rch.FlexModel()
                         elif s.get('recharge') == 'Berendrecht': recharge = ps.rch.Berendrecht()
                         
                         # Pass list of settings: [precip, evap]
                         sm_settings = [settings_dict.get(inputs[0]), settings_dict.get(inputs[1])]
                         sm = ps.RechargeModel(prec, evap, rfunc=rfunc, name=name, recharge=recharge, settings=sm_settings)
                         model.add_stressmodel(sm)
                         
                    elif sm_type == 'LinearTrend':
                         sm = ps.LinearTrend(name=name)
                         model.add_stressmodel(sm)
                         
                except Exception as e:
                    print(f"Error adding {s['name']}: {e}")
            
            # Apply Parameters
            # Capture from table
            for i in range(self.table_params.rowCount()):
                pname = self.table_params.verticalHeaderItem(i).text()
                # Check if this parameter exists in the new model structure
                # We can try to set it, if it fails, ignore (param might be gone due to structure change)
                try:
                    # Get values
                    initial_item = self.table_params.item(i, 0)
                    pmin_item = self.table_params.item(i, 2)
                    pmax_item = self.table_params.item(i, 3)
                    vary_item = self.table_params.item(i, 4)
                    
                    if initial_item: 
                        val = float(initial_item.text())
                        model.set_parameter(name=pname, initial=val)
                    if pmin_item:
                         val = float(pmin_item.text())
                         model.set_parameter(name=pname, pmin=val)
                    if pmax_item:
                         val = float(pmax_item.text())
                         model.set_parameter(name=pname, pmax=val)
                    if vary_item:
                         val = vary_item.text().lower() == 'true'
                         model.set_parameter(name=pname, vary=val)
                         
                except Exception as e:
                    # Parameter might not be in the new model structure
                    pass

            # Solve
            model.solve(freq=freq, tmin=tmin, tmax=tmax, report=False)
            self.new_model = model
            self.update_stats_label(model)
            self.update_plot(model)
            self.update_parameters_table(model)
            
        except Exception as e:
            QMessageBox.critical(self, "Solve Error", str(e))
            self.lbl_stats.setText(f"Error: {str(e)}")

    def get_model_data(self):
        name = self.le_name.text()
        if self.new_model is None:
             self.solve_model()
             
        if self.new_model:
            self.new_model.name = name
            return self.new_model, name
        return self.original_model, name
