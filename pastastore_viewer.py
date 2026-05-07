# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import (
    QCoreApplication,
    Qt,
    QVariant,
)
from qgis.PyQt.QtWidgets import (
    QAction,
    QFileDialog,
    QMessageBox,
    QProgressDialog,
    QApplication,
    QInputDialog,
)
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsLayerTreeLayer,
    QgsFeatureRequest,
    QgsCoordinateReferenceSystem,
    QgsGraduatedSymbolRenderer,
    QgsStyle,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling,
    QgsTextFormat,
)
import os.path
import json
import pandas as pd
import numpy as np

# Try to import pastastore and pyqtgraph
try:
    import pastastore as pst

    HAS_PASTASTORE = True
except ImportError:
    HAS_PASTASTORE = False

try:
    import pastas as ps

    HAS_PASTAS = True
except ImportError:
    HAS_PASTAS = False

try:
    import pyqtgraph as pg

    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False

from .main_dock import PastastoreMainDock
from .plot_dock import PastastorePlotDock
from .settings_dialog import PastastoreSettingsDialog
from .model_editor import ModelEditorDialog
from .results_plot import ResultsPlotDialog
from .diagnostics_plot import DiagnosticsPlotDialog
from .oseries_editor import OseriesEditorDialog
from .bro_import_dialog import BROImportDialog
from .knmi_import_dialog import KNMIImportDialog
from .bulk_models_dialog import BulkModelsDialog
from .license_manager import LicenseManager, FEATURE_PRO, FEATURE_PRONL


class PastastoreViewer:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.plugin_version = self._read_plugin_version()
        self.actions = []
        self.menu = self.tr("&Pastastore Viewer")
        self.store = None
        self.dock_widget = None
        self.plot_dock = None
        self.action = None
        self.license_action = None
        self.license_validate_action = None
        self.license_deactivate_action = None
        self.is_updating_selection = False
        self.store_modified = False
        self.bro_import_dialog = None
        self.knmi_import_dialog = None
        self.license_manager = LicenseManager(self.plugin_dir, self.plugin_version)

    def _read_plugin_version(self):
        metadata_file = os.path.join(self.plugin_dir, "metadata.txt")
        try:
            with open(metadata_file, "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip().startswith("version="):
                        return line.split("=", 1)[1].strip() or "0.1"
        except Exception:
            pass
        return "0.1"

    def tr(self, message):
        return QCoreApplication.translate("PastastoreViewer", message)

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.svg")

        # Main action
        self.action = QAction(
            QIcon(icon_path), self.tr("Pastastore Viewer"), self.iface.mainWindow()
        )
        self.action.setToolTip(self.tr("View Pastastore data"))
        self.action.triggered.connect(self.run)

        # Add to the Plugins menu
        self.iface.addPluginToMenu(self.menu, self.action)
        # Add to the Toolbar
        self.iface.addToolBarIcon(self.action)
        self.actions.append(self.action)

        self.license_action = QAction(
            self.tr("Activate/Update License"), self.iface.mainWindow()
        )
        self.license_action.triggered.connect(self.manage_license)
        self.iface.addPluginToMenu(self.menu, self.license_action)
        self.actions.append(self.license_action)

        self.license_validate_action = QAction(
            self.tr("Validate License Online"), self.iface.mainWindow()
        )
        self.license_validate_action.triggered.connect(self.validate_license_online)
        self.iface.addPluginToMenu(self.menu, self.license_validate_action)
        self.actions.append(self.license_validate_action)

        self.license_deactivate_action = QAction(
            self.tr("Deactivate License"), self.iface.mainWindow()
        )
        self.license_deactivate_action.triggered.connect(self.deactivate_license)
        self.iface.addPluginToMenu(self.menu, self.license_deactivate_action)
        self.actions.append(self.license_deactivate_action)

        # Connect to selection changes on map
        self.iface.mapCanvas().selectionChanged.connect(self.on_map_selection_changed)

        # Connect project signals for automatic restoration
        QgsProject.instance().readProject.connect(self.on_project_read)
        QgsProject.instance().cleared.connect(self.on_project_new)
        QgsProject.instance().projectSaved.connect(self.on_project_write)

        # Check if project is already loaded (e.g. plugin reload)
        if QgsProject.instance().fileName():
            self.on_project_read()

        self._update_license_ui()

    def unload(self):
        if not self._prompt_save_if_needed(allow_cancel=True):
            return

        for action in self.actions:
            self.iface.removePluginMenu(self.tr("&Pastastore Viewer"), action)
            self.iface.removeToolBarIcon(action)
        if self.dock_widget:
            self.iface.removeDockWidget(self.dock_widget)
        if self.plot_dock:
            self.iface.removeDockWidget(self.plot_dock)
        try:
            self.iface.mapCanvas().selectionChanged.disconnect(
                self.on_map_selection_changed
            )
            QgsProject.instance().readProject.disconnect(self.on_project_read)
            QgsProject.instance().cleared.disconnect(self.on_project_new)
            QgsProject.instance().projectSaved.disconnect(self.on_project_write)
        except:
            pass

    def create_dock(self):
        """Ensures the dock widgets are created and state is restored."""
        main_dock_created = False
        if not self.dock_widget:
            self.dock_widget = PastastoreMainDock(self.iface.mainWindow())
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock_widget)
            main_dock_created = True

            # Connect dock signals
            self.dock_widget.load_requested.connect(self.load_pastastore)
            self.dock_widget.new_requested.connect(self.new_pastastore)
            self.dock_widget.save_requested.connect(self.save_pastastore)
            self.dock_widget.item_selected.connect(self.on_item_selected)
            self.dock_widget.settings_requested.connect(self.open_settings)
            self.dock_widget.tab_changed.connect(self.on_tab_changed)
            self.dock_widget.delete_model_requested.connect(self.delete_models)
            self.dock_widget.delete_oseries_requested.connect(self.delete_oseries)
            self.dock_widget.delete_stresses_requested.connect(self.delete_stresses)
            self.dock_widget.edit_model_requested.connect(self.open_model_editor)
            self.dock_widget.results_requested.connect(self.open_results_plot)
            self.dock_widget.diagnostics_requested.connect(self.open_diagnostics_plot)
            self.dock_widget.mpl_results_requested.connect(self.open_mpl_results_plot)
            self.dock_widget.mpl_diagnostics_requested.connect(self.open_mpl_diagnostics_plot)
            self.dock_widget.add_model_column_requested.connect(self.compute_model_stat_column)
            self.dock_widget.map_plot_requested.connect(self.plot_model_values_on_map)
            self.dock_widget.select_models_for_oseries_requested.connect(
                self.select_models_for_oseries
            )
            self.dock_widget.select_models_for_stresses_requested.connect(
                self.select_models_for_stresses
            )
            self.dock_widget.select_oseries_for_models_requested.connect(
                self.select_oseries_for_models
            )
            self.dock_widget.select_stresses_for_models_requested.connect(
                self.select_stresses_for_models
            )
            self.dock_widget.edit_oseries_requested.connect(self.open_oseries_editor)
            self.dock_widget.create_model_requested.connect(
                self.create_model_from_oseries
            )
            self.dock_widget.create_models_requested.connect(
                self.create_models_from_oseries
            )
            self.dock_widget.import_bro_requested.connect(self.open_bro_import_dialog)
            self.dock_widget.import_knmi_requested.connect(self.open_knmi_import_dialog)

        if not self.plot_dock:
            self.plot_dock = PastastorePlotDock(self.iface.mainWindow())
            self.iface.addDockWidget(Qt.BottomDockWidgetArea, self.plot_dock)

            # Connect plot dock visibility signal if needed
            self.plot_dock.visibilityChanged.connect(
                self.plot_dock.save_state_to_project
            )

        if main_dock_created:
            self.dock_widget.restore_state_from_project()

        self._update_license_ui()

        return self.dock_widget

    def run(self):
        """Run method that loads the dock widgets."""
        self.license_manager.refresh_state()
        self.validate_license_online(silent=True)
        self.create_dock()

        if self.store is None:
            self._initialize_in_memory_store(notify=False)

        self.dock_widget.show()
        self.dock_widget.raise_()
        self.dock_widget.activateWindow()

        self.plot_dock.show()
        self.plot_dock.raise_()
        self.plot_dock.activateWindow()

    def _update_license_ui(self):
        status = self.license_manager.status_text()

        if self.license_action:
            self.license_action.setText(self.tr(f"License: {status}"))

        if self.dock_widget:
            self.dock_widget.set_license_capabilities(
                can_use_pro=self.license_manager.has_feature(FEATURE_PRO),
                can_use_pronl=self.license_manager.has_feature(FEATURE_PRONL),
            )

    def _require_feature(self, feature, feature_label):
        if self.license_manager.has_feature(feature):
            return True

        QMessageBox.information(
            self.iface.mainWindow(),
            "Paid feature",
            f"Deze actie vereist {feature_label}.\n\n"
            f"Huidige licentie: {self.license_manager.status_text()}\n"
            "Gebruik Plugin menu > Activate/Update License om te activeren.",
        )
        return False

    def manage_license(self):
        current_status = self.license_manager.status_text()
        key, ok = QInputDialog.getText(
            self.iface.mainWindow(),
            "Activate or update license",
            f"Huidige status: {current_status}\n\nVoer je licentiesleutel in:",
        )
        if not ok:
            return

        key = (key or "").strip()
        if not key:
            return

        server_url, ok = QInputDialog.getText(
            self.iface.mainWindow(),
            "License server URL",
            "Voer de licentieserver URL in (bijv. https://licenses.example.com):",
            text="http://localhost:8787",
        )
        if not ok:
            return

        success, message = self.license_manager.activate(key, server_url)
        if success:
            self.iface.messageBar().pushMessage("Success", message, level=0)
        else:
            QMessageBox.warning(self.iface.mainWindow(), "License", message)

        self._update_license_ui()

    def validate_license_online(self, silent=False):
        success, message = self.license_manager.validate_online(force=True)
        self._update_license_ui()

        if silent:
            return

        if success:
            self.iface.messageBar().pushMessage("Success", message, level=0)
        else:
            QMessageBox.warning(self.iface.mainWindow(), "License", message)

    def deactivate_license(self):
        reply = QMessageBox.question(
            self.iface.mainWindow(),
            "Deactivate license",
            "Deze machine deactiveren en lokale licentie verwijderen?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        success, message = self.license_manager.deactivate()
        if success:
            self.iface.messageBar().pushMessage("Success", message, level=0)
        else:
            QMessageBox.warning(self.iface.mainWindow(), "License", message)
        self._update_license_ui()

    def on_project_read(self):
        """Called when a project is loaded."""
        from qgis.PyQt.QtCore import QTimer

        QTimer.singleShot(200, self._deferred_on_project_read)

    def _deferred_on_project_read(self):
        # 1. Read visibility first
        is_open_str, ok = QgsProject.instance().readEntry(
            "PastastoreViewer", "is_open", "false"
        )
        plot_open_str, ok_p = QgsProject.instance().readEntry(
            "PastastoreViewer", "plot_dock_open", "false"
        )

        # 2. Ensure docks exist
        self.create_dock()

        # 3. Apply visibility
        if is_open_str == "true":
            self.dock_widget.show()
        else:
            self.dock_widget.hide()

        if plot_open_str == "true":
            self.plot_dock.show()
        else:
            self.plot_dock.hide()

    def on_project_new(self):
        """Called when a new project is created."""
        self.store = None
        self.store_modified = False
        if self.dock_widget:
            self.dock_widget.populate_lists(None)
            self.dock_widget.set_filename(None)
            self.dock_widget.close()
            self.dock_widget = None
        if self.plot_dock:
            self.plot_dock.clear_plot()
            self.plot_dock.close()
            self.plot_dock = None
        try:
            scope = "PastastoreViewer"
            QgsProject.instance().writeEntry(scope, "last_selected_category", "")
            QgsProject.instance().writeEntry(scope, "last_selected_names", "[]")
        except Exception:
            pass

    def on_project_write(self):
        """Called when the project is being saved."""
        self._prompt_save_if_needed()

    def _should_prompt_save(self):
        if not self.store:
            return False

        has_store_path = bool(self.dock_widget and self.dock_widget.store_path)
        connector = getattr(self.store, "conn", None)
        is_in_memory_store = (
            connector is not None and connector.__class__.__name__ == "DictConnector"
        )

        return self.store_modified or (is_in_memory_store and not has_store_path)

    def _get_save_prompt_text(self):
        if self.store_modified:
            return "The pastastore has been modified. Do you want to save it?"
        return (
            "The current pastastore is in-memory and has not been saved to a zip file. "
            "Do you want to save it now?"
        )

    def _prompt_save_if_needed(self, allow_cancel=False):
        if not self._should_prompt_save():
            return True

        buttons = QMessageBox.Yes | QMessageBox.No
        if allow_cancel:
            buttons |= QMessageBox.Cancel

        reply = QMessageBox.question(
            self.iface.mainWindow(),
            "Save Pastastore",
            self._get_save_prompt_text(),
            buttons,
            QMessageBox.Yes,
        )
        if allow_cancel and reply == QMessageBox.Cancel:
            return False

        if reply == QMessageBox.Yes:
            self.save_pastastore()
            if self._should_prompt_save():
                return False

        return True

    def open_settings(self):
        if not self.dock_widget:
            return
        dlg = PastastoreSettingsDialog(
            self.dock_widget.x_col,
            self.dock_widget.y_col,
            self.iface.mainWindow(),
            current_crs=self.dock_widget.crs_epsg,
            current_zoom=self.dock_widget.auto_zoom,
        )
        if dlg.exec_():
            settings = dlg.get_settings()
            self.dock_widget.x_col = settings["x"]
            self.dock_widget.y_col = settings["y"]
            self.dock_widget.crs_epsg = settings["crs"]
            self.dock_widget.auto_zoom = settings["zoom"]

            self.dock_widget.save_state_to_project()
            if self.store:
                self.load_layers_from_store()

    def load_pastastore(self, filename=None):
        if not HAS_PASTASTORE:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Error",
                "pastastore library not available. Bundle it in the plugin 'dependencies' folder or install it in the QGIS Python environment.",
            )
            return

        if not filename:
            filename, _ = QFileDialog.getOpenFileName(
                self.iface.mainWindow(),
                "Select Pastastore Zip File",
                "",
                "Zip Files (*.zip);;All Files (*)",
            )

        if filename:
            if self.store and self._should_warn_before_replacing_store():
                choice = QMessageBox(self.iface.mainWindow())
                choice.setWindowTitle("Pastastore already loaded")
                choice.setText(
                    "A pastastore is already loaded. Do you want to replace it or merge the new data?"
                )
                replace_btn = choice.addButton("Replace", QMessageBox.AcceptRole)
                merge_btn = choice.addButton("Merge", QMessageBox.ActionRole)
                choice.addButton(QMessageBox.Cancel)
                choice.exec_()

                if choice.clickedButton() == merge_btn:
                    self._merge_from_path(filename)
                elif choice.clickedButton() == replace_btn:
                    self._load_from_path(filename)
                else:
                    return
            else:
                self._load_from_path(filename)

            if self.dock_widget:
                self.dock_widget.save_state_to_project()

    def new_pastastore(self):
        if not HAS_PASTASTORE:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Error",
                "pastastore library not available. Bundle it in the plugin 'dependencies' folder or install it in the QGIS Python environment.",
            )
            return

        if self.store and self._should_warn_before_replacing_store():
            reply = QMessageBox.question(
                self.iface.mainWindow(),
                "Create New Pastastore",
                "A pastastore is already loaded. Create a new empty pastastore and replace the current one?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        self._initialize_in_memory_store(notify=True)

    def _store_has_content(self):
        if not self.store:
            return False

        try:
            has_oseries = hasattr(self.store, "oseries") and len(self.store.oseries.index) > 0
            has_stresses = hasattr(self.store, "stresses") and len(self.store.stresses.index) > 0
            has_models = hasattr(self.store, "model_names") and len(self.store.model_names) > 0
            return has_oseries or has_stresses or has_models
        except Exception:
            return False

    def _should_warn_before_replacing_store(self):
        if not self.store:
            return False

        has_store_path = bool(self.dock_widget and self.dock_widget.store_path)
        if has_store_path:
            return self.store_modified

        return self._store_has_content()

    def _initialize_in_memory_store(self, notify=False):
        try:
            self.store = pst.PastaStore()
            self.store_modified = False

            self.load_layers_from_store()
            if self.dock_widget:
                self.dock_widget.populate_lists(self.store)
                self.dock_widget.store_path = None
                self.dock_widget.le_filename.setText("In-memory pastastore")
                self.dock_widget.le_filename.setToolTip("In-memory pastastore")
                self._set_active_layer_for_current_tab()
                self.dock_widget.save_state_to_project()

            if notify:
                self.iface.messageBar().pushMessage(
                    "Success", "Created new empty pastastore.", level=0
                )
        except Exception as e:
            import traceback

            self.iface.messageBar().pushMessage(
                "Error", f"Failed to create new pastastore: {str(e)}", level=2
            )
            print(traceback.format_exc())

    def save_pastastore(self):
        if not self.store:
            self.iface.messageBar().pushMessage(
                "No Store", "Load a pastastore before saving.", level=1
            )
            return

        default_path = ""
        if self.dock_widget and self.dock_widget.store_path:
            default_path = self.dock_widget.store_path

        filename, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            "Save Pastastore Zip File",
            default_path,
            "Zip Files (*.zip);;All Files (*)",
        )

        if not filename:
            return

        try:
            busy = QProgressDialog(
                "Saving pastastore...", None, 0, 0, self.iface.mainWindow()
            )
            busy.setWindowTitle("Please wait")
            busy.setWindowModality(Qt.ApplicationModal)
            busy.setMinimumDuration(0)
            busy.setCancelButton(None)
            busy.show()
            QApplication.processEvents()

            if hasattr(self.store, "to_zip"):
                # Avoid tqdm writing to a missing stderr stream in some QGIS runtimes.
                self.store.to_zip(filename, progressbar=False, overwrite=True)
            elif hasattr(self.store, "to_file"):
                self.store.to_file(filename)
            else:
                raise AttributeError("Pastastore does not support saving to zip.")

            if self.dock_widget:
                self.dock_widget.set_filename(filename)
                self.dock_widget.save_state_to_project()

            self.store_modified = False
            self.iface.messageBar().pushMessage("Success", f"Saved {filename}", level=0)
        except Exception as e:
            import traceback

            self.iface.messageBar().pushMessage(
                "Error", f"Failed to save pastastore: {str(e)}", level=2
            )
            print(traceback.format_exc())
        finally:
            try:
                busy.close()
            except Exception:
                pass

    def _load_from_path(self, filename):
        if filename:
            import sys
            import io

            busy = QProgressDialog(
                "Loading pastastore...", None, 0, 0, self.iface.mainWindow()
            )
            busy.setWindowTitle("Please wait")
            busy.setWindowModality(Qt.ApplicationModal)
            busy.setMinimumDuration(0)
            busy.setCancelButton(None)
            busy.show()
            QApplication.processEvents()

            # Temporary redirection
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            if sys.stdout is None:
                sys.stdout = io.StringIO()
            if sys.stderr is None:
                sys.stderr = io.StringIO()

            import traceback
            from pastastore.base import BaseConnector

            try:
                # Reset the class-level _added_models list before loading a new
                # store. This list is shared across all connector instances, so
                # stale model names from a previously loaded store would otherwise
                # cause a KeyError when _trigger_links_update_if_needed runs on
                # the freshly created connector.
                BaseConnector._added_models = []
                self.store = pst.PastaStore.from_zip(filename)
                self.store_modified = False
                self.load_layers_from_store()
                if self.dock_widget:
                    self.dock_widget.populate_lists(self.store)
                    self.dock_widget.set_filename(filename)
                    # Set active layer based on current tab
                    self._set_active_layer_for_current_tab()
                    self._restore_selection_from_project()
                self.iface.messageBar().pushMessage(
                    "Success", f"Loaded {filename}", level=0
                )
            except Exception as e:
                err_msg = traceback.format_exc()
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Pastastore Load Error",
                    f"Failed to load store:\n\n{err_msg}",
                )
            finally:
                busy.close()
                sys.stdout = old_stdout
                sys.stderr = old_stderr

    def _merge_from_path(self, filename):
        if not self.store or not filename:
            return

        import sys
        import io

        busy = QProgressDialog(
            "Merging pastastore...", None, 0, 0, self.iface.mainWindow()
        )
        busy.setWindowTitle("Please wait")
        busy.setWindowModality(Qt.ApplicationModal)
        busy.setMinimumDuration(0)
        busy.setCancelButton(None)
        busy.show()
        QApplication.processEvents()

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        if sys.stdout is None:
            sys.stdout = io.StringIO()
        if sys.stderr is None:
            sys.stderr = io.StringIO()

        import traceback

        try:
            source_store = pst.PastaStore.from_zip(filename)
            counts = self._merge_store(source_store)

            self.load_layers_from_store()
            if self.dock_widget:
                self.dock_widget.populate_lists(self.store)
                self._set_active_layer_for_current_tab()

            msg = (
                f"Merged {filename} (oseries: {counts['oseries']}, "
                f"stresses: {counts['stresses']}, models: {counts['models']})"
            )
            self.store_modified = True
            self.iface.messageBar().pushMessage("Success", msg, level=0)
        except Exception:
            err_msg = traceback.format_exc()
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Pastastore Merge Error",
                f"Failed to merge store:\n\n{err_msg}",
            )
        finally:
            busy.close()
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    def _merge_store(self, source_store):
        counts = {"oseries": 0, "stresses": 0, "models": 0}

        if hasattr(source_store, "oseries") and len(source_store.oseries.index) > 0:
            for name in source_store.oseries.index:
                series_data = source_store.get_oseries(name)
                metadata = source_store.oseries.loc[name].to_dict()
                if self._add_oseries_to_store(series_data, name, metadata):
                    counts["oseries"] += 1

        if hasattr(source_store, "stresses") and len(source_store.stresses.index) > 0:
            for name in source_store.stresses.index:
                series_data = source_store.get_stresses(name)
                metadata = source_store.stresses.loc[name].to_dict()
                if self._add_stress_to_store(series_data, name, metadata):
                    counts["stresses"] += 1

        if hasattr(source_store, "model_names") and len(source_store.model_names) > 0:
            for name in source_store.model_names:
                model = source_store.get_models(name)
                self.store.add_model(model, overwrite=True)
                counts["models"] += 1

        return counts

    def _add_oseries_to_store(self, series_data, name, metadata):
        try:
            self.store.add_oseries(
                series_data, name=name, metadata=metadata, overwrite=True
            )
            return True
        except TypeError:
            self.store.add_oseries(series_data, name=name, metadata=metadata)
            return True

    def _add_stress_to_store(self, series_data, name, metadata):
        kind = self._get_stress_kind(metadata)
        if hasattr(self.store, "add_stresses"):
            try:
                self.store.add_stresses(
                    series_data, name=name, metadata=metadata, overwrite=True
                )
                return True
            except TypeError:
                if kind is not None:
                    try:
                        self.store.add_stresses(
                            series_data,
                            name=name,
                            kind=kind,
                            metadata=metadata,
                            overwrite=True,
                        )
                        return True
                    except TypeError:
                        self.store.add_stresses(
                            series_data, name=name, kind=kind, metadata=metadata
                        )
                        return True
                self.store.add_stresses(series_data, name=name, metadata=metadata)
                return True

        if hasattr(self.store, "add_stress"):
            try:
                self.store.add_stress(
                    series_data, name=name, metadata=metadata, overwrite=True
                )
                return True
            except TypeError:
                if kind is not None:
                    try:
                        self.store.add_stress(
                            series_data,
                            name=name,
                            kind=kind,
                            metadata=metadata,
                            overwrite=True,
                        )
                        return True
                    except TypeError:
                        self.store.add_stress(
                            series_data, name=name, kind=kind, metadata=metadata
                        )
                        return True
                self.store.add_stress(series_data, name=name, metadata=metadata)
                return True

        return False

    def _get_stress_kind(self, metadata):
        if not metadata:
            return None
        if "kind" in metadata and metadata["kind"]:
            return metadata["kind"]
        if "type" in metadata and metadata["type"]:
            return metadata["type"]
        return "stress"

    def load_layers_from_store(self):
        if not self.store:
            return
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup("Pastastore")
        if group:
            for child in group.children():
                if isinstance(child, QgsLayerTreeLayer):
                    QgsProject.instance().removeMapLayer(child.layerId())
        else:
            group = root.addGroup("Pastastore")

        # Add models first so they are on top (z-order)
        if hasattr(self.store, "model_names") and len(self.store.model_names) > 0:
            model_oseries = [
                self.store.get_models(m, return_dict=True)["oseries"]["name"]
                for m in self.store.model_names
            ]
            models = self.store.oseries.loc[model_oseries]
            models.index = self.store.model_names
            self._add_layer(models, "models", group)

        if hasattr(self.store, "stresses") and len(self.store.stresses.index) > 0:
            self._add_layer(self.store.stresses, "stresses", group)

        if len(self.store.oseries.index) > 0:
            self._add_layer(self.store.oseries, "oseries", group)

    def _add_layer(self, data, layer_name, group):
        try:
            if not hasattr(data, "columns"):
                if hasattr(data, "index"):
                    try:
                        df = pd.DataFrame(index=data.index)
                    except:
                        return
                    data_df = df
                else:
                    return
            else:
                data_df = data

            x_col = self.dock_widget.x_col if self.dock_widget else "x"
            y_col = self.dock_widget.y_col if self.dock_widget else "y"
            crs_epsg = self.dock_widget.crs_epsg if self.dock_widget else "28992"

            if x_col not in data_df.columns or y_col not in data_df.columns:
                potential_x = [c for c in data_df.columns if "x" in c.lower()]
                potential_y = [c for c in data_df.columns if "y" in c.lower()]
                if potential_x and potential_y:
                    x_col, y_col = potential_x[0], potential_y[0]
                else:
                    self.iface.messageBar().pushMessage(
                        "Missing Coordinates",
                        f"Could not find columns '{x_col}' and '{y_col}' in {layer_name}. "
                        "Please check your settings or the data.",
                        level=2,
                    )
                    return

            crs = QgsCoordinateReferenceSystem(f"EPSG:{crs_epsg}")
            layer = QgsVectorLayer(f"Point?crs={crs.authid()}", layer_name, "memory")
            layer.setCustomProperty("pastastore_type", layer_name)
            # Mark as plugin-managed to suppress scratch layer warning
            layer.setCustomProperty("skipMemoryLayersCheck", 1)
            pr = layer.dataProvider()
            fields = [QgsField("name", QVariant.String)]
            valid_cols = [
                c
                for c in data_df.columns
                if c.lower() not in [x_col.lower(), y_col.lower(), "name"]
            ]
            for col in valid_cols:
                fields.append(QgsField(str(col), QVariant.String))
            pr.addAttributes(fields)
            layer.updateFields()

            feats = []
            for idx, row in data_df.iterrows():
                feat = QgsFeature()
                try:
                    x, y = float(row[x_col]), float(row[y_col])
                    if np.isnan(x) or np.isnan(y):
                        continue
                    feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
                    attrs = [str(idx)] + [str(row[col]) for col in valid_cols]
                    feat.setAttributes(attrs)
                    feats.append(feat)
                except:
                    continue
            pr.addFeatures(feats)
            layer.updateExtents()

            symbol = layer.renderer().symbol()
            from qgis.PyQt.QtGui import QColor

            colors = {
                "oseries": Qt.blue,
                "stresses": Qt.red,
                "models": QColor(0, 128, 0),
            }
            color = colors.get(layer_name, Qt.black)
            symbol.setColor(color)

            if layer_name == "oseries":
                symbol.setSize(3.0)
                sl = symbol.symbolLayer(0)
                if sl:
                    sl.setFillColor(QColor(0, 0, 0, 0))
                    sl.setStrokeColor(color)
                    sl.setStrokeWidth(0.6)

            if layer_name == "models":
                symbol.setSize(5.0)
                sl = symbol.symbolLayer(0)
                if sl:
                    sl.setFillColor(QColor(0, 0, 0, 0))  # Hollow
                    sl.setStrokeColor(color)
                    sl.setStrokeWidth(0.6)

            QgsProject.instance().addMapLayer(layer, False)
            group.addLayer(layer)
        except Exception as e:
            import traceback

            err = traceback.format_exc()
            self.iface.messageBar().pushMessage(
                "Layer Error", f"Failed to add layer {layer_name}: {str(e)}", level=2
            )
            print(err)

    def on_item_selected(self, category, names):
        if names and self.plot_dock and not self.plot_dock.isVisible():
            self.plot_dock.show()
        self.plot_item(category, names)

        try:
            scope = "PastastoreViewer"
            QgsProject.instance().writeEntry(scope, "last_selected_category", category)
            QgsProject.instance().writeEntry(
                scope, "last_selected_names", json.dumps(names)
            )
        except Exception:
            pass

        if self.is_updating_selection:
            return

        layers = QgsProject.instance().mapLayersByName(category)
        if not layers:
            return
        layer = layers[0]

        self.is_updating_selection = True
        try:
            layer.removeSelection()
            if not names:
                self.iface.mapCanvas().refresh()
                return

            names_str = ",".join([f"'{n}'" for n in names])
            request = QgsFeatureRequest().setFilterExpression(
                f'"name" IN ({names_str})'
            )

            ids = []
            for feat in layer.getFeatures(request):
                ids.append(feat.id())

            layer.select(ids)
        finally:
            self.is_updating_selection = False

        auto_zoom = self.dock_widget.auto_zoom if self.dock_widget else True
        if ids and auto_zoom:
            self.iface.mapCanvas().setExtent(layer.boundingBoxOfSelected())
            self.iface.mapCanvas().refresh()

        if self.dock_widget:
            self.dock_widget.save_state_to_project()

    def _restore_selection_from_project(self):
        """Restore the last selected items and re-plot after project load."""
        if not self.dock_widget:
            return

        try:
            scope = "PastastoreViewer"
            category, _ = QgsProject.instance().readEntry(
                scope, "last_selected_category", ""
            )
            names_str, _ = QgsProject.instance().readEntry(
                scope, "last_selected_names", "[]"
            )
            if not category:
                return
            try:
                names = json.loads(names_str)
            except Exception:
                names = []
            if isinstance(names, str):
                names = [names]
            if names:
                self.dock_widget.select_items_in_list(category, names)
        except Exception:
            pass

    def on_tab_changed(self, active_category):
        categories = ["oseries", "stresses", "models"]
        for cat in categories:
            layers = QgsProject.instance().mapLayersByName(cat)
            pastastore_layer = None
            for layer in layers:
                if layer.customProperty("pastastore_type") == cat:
                    pastastore_layer = layer
                    break

            if not pastastore_layer:
                continue

            if cat == active_category:
                self.iface.setActiveLayer(pastastore_layer)
            else:
                self.is_updating_selection = True
                try:
                    pastastore_layer.removeSelection()
                finally:
                    self.is_updating_selection = False
        self.iface.mapCanvas().refresh()

    def _set_active_layer_for_current_tab(self):
        """Set the active QGIS layer based on the currently open tab."""
        if not self.dock_widget:
            return

        current_tab_index = self.dock_widget.tabs.currentIndex()
        categories = ["oseries", "stresses", "models"]

        if current_tab_index < len(categories):
            category = categories[current_tab_index]
            layers = QgsProject.instance().mapLayersByName(category)

            for layer in layers:
                if layer.customProperty("pastastore_type") == category:
                    self.iface.setActiveLayer(layer)
                    break

    def on_map_selection_changed(self):
        if self.is_updating_selection:
            return
        layer = self.iface.mapCanvas().currentLayer()
        if not layer or not self.store:
            return
        pst_type = layer.customProperty("pastastore_type")
        if not pst_type:
            return
        selected_feats = layer.selectedFeatures()
        names = [f["name"] for f in selected_feats]
        if self.dock_widget:
            if pst_type == "model_map_plot":
                self.dock_widget.select_items_in_list("models", names, switch_tab=True)
            else:
                self.dock_widget.select_items_in_list(pst_type, names)

    def plot_item(self, category, names):
        if not self.store:
            return
        if not names:
            if self.plot_dock:
                self.plot_dock.clear_plot(category=category)
            return

        if isinstance(names, str):
            names = [names]

        # Ask user if they want to plot more than 10 oseries/stresses
        if len(names) > 10 and category in ["oseries", "stresses"]:
            reply = QMessageBox.question(
                self.iface.mainWindow(),
                "Many Items Selected",
                f"You have selected {len(names)} {category}. Do you want to plot them?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                if self.plot_dock:
                    self.plot_dock.clear_plot(category=category)
                return

        try:
            if category == "oseries":
                data = self.store.get_oseries(names)
                title = (
                    f"Oseries: {', '.join(names)}"
                    if len(names) < 3
                    else f"Oseries ({len(names)} selected)"
                )
                if self.plot_dock:
                    self.plot_dock.plot_series(data, title=title)

            elif category == "stresses":
                data = self.store.get_stresses(names)
                title = (
                    f"Stress: {', '.join(names)}"
                    if len(names) < 3
                    else f"Stresses ({len(names)} selected)"
                )
                if self.plot_dock:
                    self.plot_dock.plot_series(data, title=title)

            elif category == "models":
                data_list = []
                for name in names:
                    try:
                        ml = self.store.get_models(name)
                        data_list.append(
                            {
                                "name": name,
                                "obs": ml.observations(),
                                "sim": ml.simulate(),
                                "r2": ml.stats.rsq(),
                            }
                        )
                    except:
                        continue

                if self.plot_dock:
                    self.plot_dock.plot_models(data_list)
        except Exception as e:
            self.iface.messageBar().pushMessage(
                "Error", f"Plot error: {str(e)}", level=2
            )

    def delete_models(self, names):
        if not self.store:
            return

        reply = QMessageBox.question(
            self.iface.mainWindow(),
            "Confirm Deletion",
            f"Are you sure you want to delete {len(names)} model(s)?\n\n{', '.join(names)}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            try:
                # 1. Delete from store
                self.store.del_models(names)

                # 2. Reload layers (simplest way to update QGIS map)
                self.load_layers_from_store()

                # 3. Refresh lists
                if self.dock_widget:
                    self.dock_widget.populate_lists(self.store)

                # 4. Clear plot if it was showing a deleted model
                if self.plot_dock:
                    self.plot_dock.clear_plot()

                self.store_modified = True
                self.iface.messageBar().pushMessage(
                    "Success", f"Deleted {len(names)} model(s)", level=0
                )

            except Exception as e:
                import traceback

                self.iface.messageBar().pushMessage(
                    "Error", f"Failed to delete models: {str(e)}", level=2
                )
                print(traceback.format_exc())

    def delete_oseries(self, names):
        if not self.store:
            return

        # Show names only if 10 or fewer
        if len(names) > 10:
            message = f"Are you sure you want to delete {len(names)} oseries?"
        else:
            message = f"Are you sure you want to delete {len(names)} oseries?\n\n{', '.join(names)}"

        reply = QMessageBox.question(
            self.iface.mainWindow(),
            "Confirm Deletion",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            try:
                # Delete from store
                for name in names:
                    self.store.del_oseries(name)

                # Reload layers
                self.load_layers_from_store()

                # Refresh lists
                if self.dock_widget:
                    self.dock_widget.populate_lists(self.store)

                # Clear plot if it was showing a deleted oseries
                if self.plot_dock:
                    self.plot_dock.clear_plot()

                self.store_modified = True
                self.iface.messageBar().pushMessage(
                    "Success", f"Deleted {len(names)} oseries", level=0
                )

            except Exception as e:
                import traceback

                self.iface.messageBar().pushMessage(
                    "Error", f"Failed to delete oseries: {str(e)}", level=2
                )
                print(traceback.format_exc())

    def delete_stresses(self, names):
        if not self.store:
            return

        # Show names only if 10 or fewer
        if len(names) > 10:
            message = f"Are you sure you want to delete {len(names)} stresses?"
        else:
            message = f"Are you sure you want to delete {len(names)} stresses?\n\n{', '.join(names)}"

        reply = QMessageBox.question(
            self.iface.mainWindow(),
            "Confirm Deletion",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            try:
                # Delete from store
                for name in names:
                    if hasattr(self.store, "del_stresses"):
                        self.store.del_stresses(name)
                    elif hasattr(self.store, "del_stress"):
                        self.store.del_stress(name)

                # Reload layers
                self.load_layers_from_store()

                # Refresh lists
                if self.dock_widget:
                    self.dock_widget.populate_lists(self.store)

                # Clear plot if it was showing a deleted stress
                if self.plot_dock:
                    self.plot_dock.clear_plot()

                self.store_modified = True
                self.iface.messageBar().pushMessage(
                    "Success", f"Deleted {len(names)} stresses", level=0
                )

            except Exception as e:
                import traceback

                self.iface.messageBar().pushMessage(
                    "Error", f"Failed to delete stresses: {str(e)}", level=2
                )
                print(traceback.format_exc())

    def open_model_editor(self, model_name):
        if not self.store:
            return
        if not self._require_feature(FEATURE_PRO, "Pro"):
            return

        try:
            # Get the model (create a copy/new instance to be safe)
            ml = self.store.get_models(model_name)

            while True:
                dlg = ModelEditorDialog(ml, self.store, self.iface.mainWindow())
                if not dlg.exec_():
                    # User closed the editor without saving
                    return

                new_model, new_name = dlg.get_model_data()

                existing = set(self.store.model_names or [])
                if new_name in existing:
                    overwrite = QMessageBox.question(
                        self.iface.mainWindow(),
                        "Model Exists",
                        f"A model named '{new_name}' already exists. Overwrite it?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No,
                    )

                    if overwrite == QMessageBox.No:
                        # Ask for new name
                        rename_cancelled = False
                        while True:
                            new_name, ok = QInputDialog.getText(
                                self.iface.mainWindow(),
                                "Rename Model",
                                "New model name:",
                                text=new_name,
                            )
                            if not ok:
                                # User cancelled rename - go back to editor
                                rename_cancelled = True
                                break
                            new_name = new_name.strip()
                            if not new_name:
                                continue
                            if new_name in existing:
                                QMessageBox.warning(
                                    self.iface.mainWindow(),
                                    "Name Exists",
                                    f"A model named '{new_name}' already exists."
                                    " Please choose another name.",
                                )
                                continue
                            break

                        if rename_cancelled:
                            # Update the model with current state and re-open editor
                            ml = new_model
                            continue

                        new_model.name = new_name

                self.store.add_model(new_model, overwrite=True)
                self.store_modified = True

                self.iface.messageBar().pushMessage(
                    "Success", f"Saved model: {new_name}", level=0
                )

                # Update UI
                if self.dock_widget:
                    self.dock_widget.populate_lists(self.store)
                    # Switch to models tab and select the saved model
                    self.dock_widget.tabs.setCurrentIndex(2)
                    self.dock_widget.select_items_in_list("models", [new_name])

                # Reload layers to reflect changes (e.g. if model results changed)
                # This might be heavy if many models, but safe.
                self.load_layers_from_store()

                # Successfully saved, exit the loop
                break

        except Exception as e:
            import traceback

            self.iface.messageBar().pushMessage(
                "Error", f"Failed to edit model: {str(e)}", level=2
            )
            print(traceback.format_exc())

    def create_model_from_oseries(self, oseries_name):
        if not self.store:
            return
        if not self._require_feature(FEATURE_PRO, "Pro"):
            return
        if not HAS_PASTAS:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Error",
                "pastas library not available. Bundle it in the plugin 'dependencies' folder or install it in the QGIS Python environment.",
            )
            return

        try:
            model_name = oseries_name
            existing = set(self.store.model_names or [])
            if model_name in existing:
                suffix = 2
                while f"{model_name}_{suffix}" in existing:
                    suffix += 1
                model_name = f"{model_name}_{suffix}"

            add_recharge = False
            # if there are stresses, with kind "prec" or "evap", we can offer to add a recharge component
            if len(self.store.stresses.index) > 0:
                if (
                    "prec" in self.store.stresses["kind"].values
                    and "evap" in self.store.stresses["kind"].values
                ):
                    add_recharge = True
            model = self.store.create_model(
                oseries_name, modelname=model_name, add_recharge=add_recharge
            )
            dlg = ModelEditorDialog(model, self.store, self.iface.mainWindow())
            if dlg.exec_():
                new_model, new_name = dlg.get_model_data()
                self.store.add_model(new_model, overwrite=True)
                self.store_modified = True

                self.iface.messageBar().pushMessage(
                    "Success", f"Created model: {new_name}", level=0
                )

                if self.dock_widget:
                    self.dock_widget.populate_lists(self.store)
                    # Switch to models tab and select the created model
                    self.dock_widget.tabs.setCurrentIndex(2)
                    self.dock_widget.select_items_in_list("models", [new_name])

                self.load_layers_from_store()

        except Exception as e:
            import traceback

            self.iface.messageBar().pushMessage(
                "Error", f"Failed to create model: {str(e)}", level=2
            )
            print(traceback.format_exc())

    def create_models_from_oseries(self, oseries_names):
        if not self.store:
            return
        if not self._require_feature(FEATURE_PRO, "Pro"):
            return
        if not HAS_PASTAS:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Error",
                "pastas library not available. Bundle it in the plugin 'dependencies' folder or install it in the QGIS Python environment.",
            )
            return
        if not oseries_names:
            return

        dlg = BulkModelsDialog(oseries_names, self.store, self.iface.mainWindow())
        if not dlg.exec_():
            return

        options = dlg.get_options()
        suffix = options["suffix"]
        add_recharge = options["add_recharge"]
        solve = options["solve"]
        tmin = options["tmin"]
        tmax = options["tmax"]
        overwrite = options["overwrite"]

        existing_models = set(self.store.model_names or [])
        oseries_to_create = oseries_names
        skipped_models = []
        if not overwrite:
            oseries_to_create = []
            for oseries_name in oseries_names:
                modelname = f"{oseries_name}{suffix}" if suffix else oseries_name
                if modelname in existing_models:
                    skipped_models.append(modelname)
                    continue
                oseries_to_create.append(oseries_name)

        if not oseries_to_create:
            if skipped_models:
                self.iface.messageBar().pushMessage(
                    "Info",
                    "All selected models already exist. Nothing created.",
                    level=1,
                )
            return

        failed = self.store.create_models_bulk(
            oseries_to_create,
            suffix=suffix,
            add_recharge=add_recharge,
            ignore_errors=True,
            solve=solve,
            tmin=tmin,
            tmax=tmax,
            progressbar=False,
        )

        created = sorted(list(set(self.store.model_names or []) - existing_models))
        if created:
            self.store_modified = True

        if failed:
            self.iface.messageBar().pushMessage(
                "Warning",
                f"Failed to create models for: {', '.join(failed)}. See console for details.",
                level=1,
            )
            print(f"Failed to create models for: {', '.join(failed)}")

        if self.dock_widget:
            selected_oseries = self.dock_widget.get_selected_names("oseries")
            self.dock_widget.populate_lists(self.store)
            self.dock_widget.tabs.setCurrentIndex(2)
            if created:
                self.dock_widget.select_items_in_list("models", created)
            if selected_oseries:
                self.dock_widget.select_items_in_list(
                    "oseries",
                    selected_oseries,
                    switch_tab=False,
                    trigger_signal=False,
                )

        self.load_layers_from_store()

        msg = f"Created {len(created)} model(s)"
        if solve and created:
            msg += " and solved"
        self.iface.messageBar().pushMessage("Success", msg, level=0)
        if skipped_models:
            self.iface.messageBar().pushMessage(
                "Info",
                f"Skipped {len(skipped_models)} existing model(s).",
                level=1,
            )

    def open_results_plot(self, model_name):
        if not self.store:
            return

        try:
            ml = self.store.get_models(model_name)
            dlg = ResultsPlotDialog(ml, self.iface.mainWindow())
            dlg.show()

            if not hasattr(self, "_result_plots"):
                self._result_plots = []
            self._result_plots.append(dlg)

            # Cleanup when closed
            dlg.finished.connect(
                lambda: (
                    self._result_plots.remove(dlg)
                    if dlg in self._result_plots
                    else None
                )
            )
        except Exception as e:
            import traceback

            self.iface.messageBar().pushMessage(
                "Error", f"Failed to show results: {str(e)}", level=2
            )
            print(traceback.format_exc())

    def open_diagnostics_plot(self, model_name):
        if not self.store:
            return

        try:
            ml = self.store.get_models(model_name)
            dlg = DiagnosticsPlotDialog(ml, self.iface.mainWindow())
            dlg.show()

            if not hasattr(self, "_diagnostics_plots"):
                self._diagnostics_plots = []
            self._diagnostics_plots.append(dlg)

            dlg.finished.connect(
                lambda: (
                    self._diagnostics_plots.remove(dlg)
                    if dlg in self._diagnostics_plots
                    else None
                )
            )
        except Exception as e:
            import traceback

            self.iface.messageBar().pushMessage(
                "Error", f"Failed to show diagnostics: {str(e)}", level=2
            )
            print(traceback.format_exc())

    def compute_model_stat_column(self, stat):
        """Compute a statistic for all models and populate the column in the dock."""
        if not self.store:
            return

        model_names = self.store.model_names
        n = len(model_names)

        progress = QProgressDialog(
            f"Computing {stat}…", "Cancel", 0, n, self.iface.mainWindow()
        )
        progress.setWindowTitle("Please wait")
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        QApplication.processEvents()

        values = {}
        for i, name in enumerate(model_names):
            if progress.wasCanceled():
                break
            progress.setLabelText(f"Computing {stat} for '{name}' ({i + 1}/{n})…")
            progress.setValue(i)
            QApplication.processEvents()
            try:
                ml = self.store.get_models(name)
                if not ml.parameters["optimal"].notna().any():
                    values[name] = float("nan")
                    continue
                val = getattr(ml.stats, stat)()
                values[name] = float(val)
            except Exception:
                values[name] = float("nan")

        progress.setValue(n)

        if self.dock_widget:
            self.dock_widget.set_model_column_values(stat, values)

    def plot_model_values_on_map(self, var_key, ramp_name="RdYlGn", invert=False):
        """Create a QGIS memory layer with model locations coloured by a stat or parameter."""
        if not self.store or not var_key:
            return

        # --- Determine value type and label ---
        if var_key.startswith("stat:"):
            stat_key = var_key[5:]
            label = next(
                (lbl for lbl, s in self.dock_widget.AVAILABLE_MODEL_STATS if s == stat_key),
                stat_key,
            )
            value_type = "stat"
        elif var_key.startswith("param:"):
            stat_key = var_key[6:]
            label = stat_key
            value_type = "param"
        else:
            return

        x_col = self.dock_widget.x_col if self.dock_widget else "x"
        y_col = self.dock_widget.y_col if self.dock_widget else "y"
        crs_epsg = self.dock_widget.crs_epsg if self.dock_widget else "28992"

        # --- Collect coordinates for each model ---
        try:
            model_oseries_names = {
                m: self.store.get_models(m, return_dict=True)["oseries"]["name"]
                for m in self.store.model_names
            }
        except Exception as e:
            self.iface.messageBar().pushMessage(
                "Map Plot Error", f"Could not read model locations: {e}", level=2
            )
            return

        # --- Collect values ---
        model_names = self.store.model_names
        n = len(model_names)
        progress = QProgressDialog(
            f"Computing {label}…", "Cancel", 0, n, self.iface.mainWindow()
        )
        progress.setWindowTitle("Please wait")
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        QApplication.processEvents()

        # --- Try to read cached stat values from the model table ---
        cached_values = {}  # {model_name: float}
        if value_type == "stat" and self.dock_widget:
            if stat_key in self.dock_widget._model_extra_cols:
                col_idx = self.dock_widget._model_extra_cols.index(stat_key) + 1
                table = self.dock_widget.table_models
                for row_i in range(table.rowCount()):
                    name_item = table.item(row_i, 0)
                    val_item = table.item(row_i, col_idx)
                    if name_item and val_item:
                        try:
                            cached_values[name_item.text()] = float(val_item.data(Qt.DisplayRole))
                        except (TypeError, ValueError):
                            pass

        records = []  # list of (name, x, y, value)
        for i, mname in enumerate(model_names):
            if progress.wasCanceled():
                break
            progress.setLabelText(f"Computing {label} for '{mname}' ({i + 1}/{n})…")
            progress.setValue(i)
            QApplication.processEvents()
            try:
                oseries_name = model_oseries_names.get(mname)
                if oseries_name is None:
                    continue
                row = self.store.oseries.loc[oseries_name]
                x = float(row[x_col])
                y = float(row[y_col])
                if np.isnan(x) or np.isnan(y):
                    continue
                if mname in cached_values:
                    val = cached_values[mname]
                elif value_type == "stat":
                    ml = self.store.get_models(mname)
                    if not ml.parameters["optimal"].notna().any():
                        val = float("nan")
                    else:
                        val = float(getattr(ml.stats, stat_key)())
                else:  # param
                    ml = self.store.get_models(mname)
                    params = ml.parameters["optimal"]
                    val = float(params.get(stat_key, float("nan")))
                records.append((mname, x, y, val))
            except Exception:
                pass

        progress.setValue(n)

        valid_records = [(n, x, y, v) for n, x, y, v in records if not np.isnan(v)]
        if not valid_records:
            self.iface.messageBar().pushMessage(
                "Map Plot", f"No valid values to plot for '{label}'.", level=1
            )
            return

        # --- Assign marker sizes for co-located models ---
        # Group by (x, y); sort names ascending so name_1 < name_2 < name_3.
        # name_3 (bottom) gets largest marker; name_1 (top) gets smallest.
        # Base size 5 pt, each deeper layer adds 3 pt.
        BASE_SIZE = 5.0
        SIZE_STEP = 3.0
        from collections import defaultdict
        loc_groups = defaultdict(list)
        for rec in valid_records:
            loc_groups[(rec[1], rec[2])].append(rec)
        # Sort each group by name ascending
        for key in loc_groups:
            loc_groups[key].sort(key=lambda r: r[0])

        # Cycling quadrant positions (QGIS QuadrantPosition enum):
        #   2=AboveRight, 0=AboveLeft, 6=BelowLeft, 8=BelowRight
        QUADRANT_CYCLE = [2, 0, 6, 8]
        # x/y sign per quadrant so the offset moves the label away from centre
        QUAD_SIGNS = [(1, 1), (-1, 1), (-1, -1), (1, -1)]

        records_with_size = []  # (name, x, y, value, marker_size, lbl_quadrant, lbl_off_x, lbl_off_y)
        for (x, y), group in loc_groups.items():
            for rank, (mname, rx, ry, val) in enumerate(group):
                # rank 0 = name_1 = smallest marker, rendered on top
                # rank n-1 = name_n = largest marker, rendered at bottom
                marker_size = BASE_SIZE + rank * SIZE_STEP
                quad_idx = rank % 4
                lbl_quadrant = QUADRANT_CYCLE[quad_idx]
                xsign, ysign = QUAD_SIGNS[quad_idx]
                # Push label outside circle: radius (mm) + 1 mm padding
                offset_mm = marker_size / 2.0 + 1.0
                lbl_off_x = xsign * offset_mm
                lbl_off_y = ysign * offset_mm
                records_with_size.append(
                    (mname, rx, ry, val, marker_size, lbl_quadrant, lbl_off_x, lbl_off_y)
                )

        # Sort so larger markers are added first (rendered first = underneath)
        records_with_size.sort(key=lambda r: -r[4])

        # --- Build memory layer ---
        layer_name = f"Models: {label}"
        crs = QgsCoordinateReferenceSystem(f"EPSG:{crs_epsg}")
        vl = QgsVectorLayer(f"Point?crs={crs.authid()}", layer_name, "memory")
        vl.setCustomProperty("skipMemoryLayersCheck", 1)
        vl.setCustomProperty("pastastore_type", "model_map_plot")
        pr = vl.dataProvider()
        pr.addAttributes([
            QgsField("name", QVariant.String),
            QgsField("value", QVariant.Double),
            QgsField("marker_size", QVariant.Double),
            QgsField("lbl_quadrant", QVariant.Int),
            QgsField("lbl_off_x", QVariant.Double),
            QgsField("lbl_off_y", QVariant.Double),
        ])
        vl.updateFields()

        feats = []
        for mname, x, y, val, msize, lbl_q, lbl_x, lbl_y in records_with_size:
            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
            feat.setAttributes([mname, val, msize, lbl_q, lbl_x, lbl_y])
            feats.append(feat)
        pr.addFeatures(feats)
        vl.updateExtents()

        # --- Graduated renderer with chosen colour ramp ---
        from qgis.core import QgsProperty, QgsSymbolLayer

        color_ramp = QgsStyle.defaultStyle().colorRamp(ramp_name)
        if color_ramp is None:
            color_ramp = QgsStyle.defaultStyle().colorRamp("RdYlGn")
        if color_ramp is None:
            color_ramp = QgsStyle.defaultStyle().colorRamp("Spectral")
        if invert and color_ramp is not None:
            color_ramp.invert()

        renderer = QgsGraduatedSymbolRenderer("value", [])
        renderer.setClassAttribute("value")
        renderer.setSourceColorRamp(color_ramp)
        n_classes = min(7, len(records_with_size))
        renderer.updateClasses(vl, QgsGraduatedSymbolRenderer.Quantile, n_classes)
        renderer.updateColorRamp(color_ramp)
        # Apply data-defined size override on every class symbol.
        # range_obj.symbol() returns a clone, so we must clone → modify → updateRangeSymbol.
        size_prop = QgsProperty.fromField("marker_size")
        for i, range_obj in enumerate(renderer.ranges()):
            sym = range_obj.symbol().clone()
            sym.setSize(BASE_SIZE)
            sl = sym.symbolLayer(0)
            if sl:
                sl.setDataDefinedProperty(QgsSymbolLayer.PropertySize, size_prop)
            renderer.updateRangeSymbol(i, sym)
        vl.setRenderer(renderer)

        # --- Labels (value with 3 decimal places, placed outside circles) ---
        label_settings = QgsPalLayerSettings()
        label_settings.enabled = True
        label_settings.fieldName = 'format_number("value", 3)'
        label_settings.isExpression = True
        label_settings.placement = QgsPalLayerSettings.OverPoint
        tf = QgsTextFormat()
        label_settings.setFormat(tf)
        # Data-defined quadrant and XY offset so labels sit outside their circle
        dp = label_settings.dataDefinedProperties()
        dp.setProperty(
            QgsPalLayerSettings.OffsetQuad,
            QgsProperty.fromField("lbl_quadrant"),
        )
        dp.setProperty(
            QgsPalLayerSettings.OffsetXY,
            QgsProperty.fromExpression('"lbl_off_x" || \',\' || "lbl_off_y"'),
        )
        label_settings.setDataDefinedProperties(dp)
        labeling = QgsVectorLayerSimpleLabeling(label_settings)
        vl.setLabelsEnabled(True)
        vl.setLabeling(labeling)

        # --- Add to project under Pastastore group ---
        root = QgsProject.instance().layerTreeRoot()
        group = root.findGroup("Pastastore")
        if group is None:
            group = root.addGroup("Pastastore")

        # Remove existing layer with same name
        for existing in QgsProject.instance().mapLayersByName(layer_name):
            QgsProject.instance().removeMapLayer(existing.id())

        QgsProject.instance().addMapLayer(vl, False)
        group.insertLayer(0, vl)
        self.iface.mapCanvas().refresh()

    def open_mpl_results_plot(self, model_name):
        if not self.store:
            return

        try:
            import matplotlib.pyplot as plt

            ml = self.store.get_models(model_name)
            ml.plots.results(split=True)
            plt.show()
        except Exception as e:
            import traceback

            self.iface.messageBar().pushMessage(
                "Error", f"Failed to show matplotlib results: {str(e)}", level=2
            )
            print(traceback.format_exc())

    def open_mpl_diagnostics_plot(self, model_name):
        if not self.store:
            return

        try:
            import matplotlib.pyplot as plt

            ml = self.store.get_models(model_name)
            ml.plots.diagnostics()
            plt.show()
        except Exception as e:
            import traceback

            self.iface.messageBar().pushMessage(
                "Error", f"Failed to show matplotlib diagnostics: {str(e)}", level=2
            )
            print(traceback.format_exc())

    def select_models_for_oseries(self, oseries_names):
        """Selects models in the dock that correspond to the given oseries names."""
        if not self.store:
            return

        try:
            matching_models = []
            # This could be slow if there are many models. Optimize if needed.
            # Does pastastore have a reverse look-up?
            # Not directly obvious, so we iterate for now.
            for m in self.store.model_names:
                # get_models returns a dict if return_dict=True which is fast metadata access usually
                meta = self.store.get_models(m, return_dict=True)
                if meta and "oseries" in meta and "name" in meta["oseries"]:
                    if meta["oseries"]["name"] in oseries_names:
                        matching_models.append(m)

            if matching_models:
                # Warn if more than 10 models
                if len(matching_models) > 10:
                    reply = QMessageBox.question(
                        self.iface.mainWindow(),
                        "Many Models Selected",
                        f"This will select {len(matching_models)} models. Continue?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No,
                    )
                    if reply == QMessageBox.No:
                        return

                self.dock_widget.select_items_in_list("models", matching_models)
                self.dock_widget.tabs.setCurrentIndex(2)  # Switch to models tab
            else:
                self.iface.messageBar().pushMessage(
                    "Info",
                    f"No models found for selected oseries: {oseries_names}.",
                    level=0,
                )

        except Exception as e:
            import traceback

            self.iface.messageBar().pushMessage(
                "Error", f"Failed to select models: {str(e)}", level=2
            )
            print(traceback.format_exc())

    def select_models_for_stresses(self, stress_names):
        """Selects models in the dock that use the given stress names."""
        if not self.store:
            return

        try:
            matching_models = []
            for m in self.store.model_names:
                meta = self.store.get_models(m, return_dict=True)
                if meta and "stressmodels" in meta:
                    # Check all stressmodels in this model
                    for sm_name, sm_data in meta["stressmodels"].items():
                        found = False

                        # Check regular stress models (StressModel)
                        if "stress" in sm_data:
                            # stress can be a list or single item
                            stress_list = (
                                sm_data["stress"]
                                if isinstance(sm_data["stress"], list)
                                else [sm_data["stress"]]
                            )
                            # Check if any stress name matches
                            for stress_info in stress_list:
                                if (
                                    isinstance(stress_info, dict)
                                    and "name" in stress_info
                                ):
                                    if stress_info["name"] in stress_names:
                                        matching_models.append(m)
                                        found = True
                                        break
                                elif (
                                    isinstance(stress_info, str)
                                    and stress_info in stress_names
                                ):
                                    matching_models.append(m)
                                    found = True
                                    break

                        # Check RechargeModel stresses (prec and evap)
                        if not found:
                            for key in ["prec", "evap"]:
                                if key in sm_data:
                                    stress_info = sm_data[key]
                                    if (
                                        isinstance(stress_info, dict)
                                        and "name" in stress_info
                                    ):
                                        if stress_info["name"] in stress_names:
                                            matching_models.append(m)
                                            found = True
                                            break
                                    elif (
                                        isinstance(stress_info, str)
                                        and stress_info in stress_names
                                    ):
                                        matching_models.append(m)
                                        found = True
                                        break

                        if found:
                            break

            if matching_models:
                # Warn if more than 10 models
                if len(matching_models) > 10:
                    reply = QMessageBox.question(
                        self.iface.mainWindow(),
                        "Many Models Selected",
                        f"This will select {len(matching_models)} models. Continue?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No,
                    )
                    if reply == QMessageBox.No:
                        return

                self.dock_widget.select_items_in_list("models", matching_models)
                self.dock_widget.tabs.setCurrentIndex(2)
            else:
                self.iface.messageBar().pushMessage(
                    "Info",
                    f"No models found for selected stresses: {stress_names}.",
                    level=0,
                )

        except Exception as e:
            import traceback

            self.iface.messageBar().pushMessage(
                "Error", f"Failed to select models: {str(e)}", level=2
            )
            print(traceback.format_exc())

    def select_oseries_for_models(self, model_names):
        """Selects oseries in the dock for the given model names."""
        if not self.store:
            return

        try:
            matching_oseries = []
            for m in model_names:
                meta = self.store.get_models(m, return_dict=True)
                if meta and "oseries" in meta and "name" in meta["oseries"]:
                    matching_oseries.append(meta["oseries"]["name"])

            matching_oseries = sorted(set(matching_oseries))

            if matching_oseries:
                if len(matching_oseries) > 10:
                    reply = QMessageBox.question(
                        self.iface.mainWindow(),
                        "Many Oseries Selected",
                        f"This will select {len(matching_oseries)} oseries. Continue?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No,
                    )
                    if reply == QMessageBox.No:
                        return

                self.dock_widget.select_items_in_list("oseries", matching_oseries)
                self.dock_widget.tabs.setCurrentIndex(0)
            else:
                self.iface.messageBar().pushMessage(
                    "Info",
                    f"No oseries found for selected models: {model_names}.",
                    level=0,
                )

        except Exception as e:
            import traceback

            self.iface.messageBar().pushMessage(
                "Error", f"Failed to select oseries: {str(e)}", level=2
            )
            print(traceback.format_exc())

    def select_stresses_for_models(self, model_names):
        """Selects stresses in the dock for the given model names."""
        if not self.store:
            return

        try:
            matching_stresses = []
            for m in model_names:
                meta = self.store.get_models(m, return_dict=True)
                if not meta or "stressmodels" not in meta:
                    continue

                for sm_name, sm_data in meta["stressmodels"].items():
                    # Regular stress models
                    if "stress" in sm_data:
                        stress_list = (
                            sm_data["stress"]
                            if isinstance(sm_data["stress"], list)
                            else [sm_data["stress"]]
                        )
                        for stress_info in stress_list:
                            if isinstance(stress_info, dict) and "name" in stress_info:
                                matching_stresses.append(stress_info["name"])
                            elif isinstance(stress_info, str):
                                matching_stresses.append(stress_info)

                    # RechargeModel stresses
                    for key in ["prec", "evap"]:
                        if key in sm_data:
                            stress_info = sm_data[key]
                            if isinstance(stress_info, dict) and "name" in stress_info:
                                matching_stresses.append(stress_info["name"])
                            elif isinstance(stress_info, str):
                                matching_stresses.append(stress_info)

            matching_stresses = sorted(set(matching_stresses))
            if hasattr(self.store, "stresses") and self.store.stresses is not None:
                available = set(self.store.stresses.index)
                matching_stresses = [s for s in matching_stresses if s in available]

            if matching_stresses:
                if len(matching_stresses) > 10:
                    reply = QMessageBox.question(
                        self.iface.mainWindow(),
                        "Many Stresses Selected",
                        f"This will select {len(matching_stresses)} stresses. Continue?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No,
                    )
                    if reply == QMessageBox.No:
                        return

                self.dock_widget.select_items_in_list("stresses", matching_stresses)
                self.dock_widget.tabs.setCurrentIndex(1)
            else:
                self.iface.messageBar().pushMessage(
                    "Info",
                    f"No stresses found for selected models: {model_names}.",
                    level=0,
                )

        except Exception as e:
            import traceback

            self.iface.messageBar().pushMessage(
                "Error", f"Failed to select stresses: {str(e)}", level=2
            )
            print(traceback.format_exc())

    def open_oseries_editor(self, oseries_name):
        """Open the oseries editor dialog."""
        if not self.store:
            return

        try:
            # Get the oseries data
            series_data = self.store.get_oseries(oseries_name)

            # Open editor dialog
            dlg = OseriesEditorDialog(
                oseries_name, series_data, self.iface.mainWindow()
            )

            if dlg.exec_():
                # Get modified series
                modified_series = dlg.get_modified_series()

                # Update in store
                # Note: pastastore doesn't have a direct update method, so we delete and re-add
                metadata = self.store.oseries.loc[oseries_name].to_dict()
                self.store.del_oseries(oseries_name)
                self.store.add_oseries(
                    modified_series, name=oseries_name, metadata=metadata
                )
                self.store_modified = True

                self.iface.messageBar().pushMessage(
                    "Success", f"Updated oseries: {oseries_name}", level=0
                )

                # Refresh plot if this oseries is currently selected
                if self.dock_widget:
                    current_tab = self.dock_widget.tabs.currentIndex()
                    if current_tab == 0:  # Oseries tab
                        # Re-trigger selection to refresh plot
                        self.dock_widget._on_selection_changed("oseries")

        except Exception as e:
            import traceback

            self.iface.messageBar().pushMessage(
                "Error", f"Failed to edit oseries: {str(e)}", level=2
            )
            print(traceback.format_exc())

    def open_bro_import_dialog(self):
        """Open the BRO import dialog."""
        if not self.store:
            self.iface.messageBar().pushMessage(
                "Warning", "Please load a pastastore first.", level=1
            )
            return
        if not self._require_feature(FEATURE_PRONL, "ProNL"):
            return

        try:
            if self.bro_import_dialog is not None and self.bro_import_dialog.isVisible():
                self.bro_import_dialog.raise_()
                self.bro_import_dialog.activateWindow()
                return

            # Open BRO import dialog
            dlg = BROImportDialog(self.iface.mainWindow(), self.iface)
            self.bro_import_dialog = dlg

            # Connect the signal to handle adding series to store
            dlg.series_to_add.connect(self._add_bro_series_to_store)
            dlg.finished.connect(lambda _: setattr(self, "bro_import_dialog", None))

            dlg.setModal(False)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()

        except Exception as e:
            import traceback

            self.iface.messageBar().pushMessage(
                "Error", f"Failed to open BRO import dialog: {str(e)}", level=2
            )
            print(traceback.format_exc())

    def open_knmi_import_dialog(self):
        """Open the KNMI import dialog."""
        if not self.store:
            self.iface.messageBar().pushMessage(
                "Warning", "Please load a pastastore first.", level=1
            )
            return
        if not self._require_feature(FEATURE_PRONL, "ProNL"):
            return

        try:
            if (
                self.knmi_import_dialog is not None
                and self.knmi_import_dialog.isVisible()
            ):
                self.knmi_import_dialog.raise_()
                self.knmi_import_dialog.activateWindow()
                return

            x_col = self.dock_widget.x_col if self.dock_widget else "x"
            y_col = self.dock_widget.y_col if self.dock_widget else "y"
            dlg = KNMIImportDialog(
                self.store,
                x_col=x_col,
                y_col=y_col,
                parent=self.iface.mainWindow(),
                iface=self.iface,
            )
            self.knmi_import_dialog = dlg

            dlg.stresses_to_add.connect(self._add_knmi_stresses_to_store)
            dlg.finished.connect(lambda _: setattr(self, "knmi_import_dialog", None))

            dlg.setModal(False)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()

        except Exception as e:
            import traceback

            self.iface.messageBar().pushMessage(
                "Error", f"Failed to open KNMI import dialog: {str(e)}", level=2
            )
            print(traceback.format_exc())

    def _add_bro_series_to_store(self, series_dict):
        """Add BRO series to the pastastore."""
        if not self.store:
            return

        try:
            added_count = 0
            for series_name, series_info in series_dict.items():
                df = series_info['data']
                metadata = series_info.get('metadata', {})

                # Convert DataFrame to Series if needed
                if isinstance(df, pd.DataFrame):
                    if 'value' in df.columns:
                        series = df['value']
                    elif 'stand' in df.columns:
                        series = df['stand']
                    else:
                        series = df.iloc[:, 0]
                else:
                    series = df

                # Add to store
                self.store.add_oseries(series, name=series_name, metadata=metadata)
                added_count += 1

            self.store_modified = True

            # Refresh the oseries list
            if self.dock_widget:
                self.dock_widget.populate_lists(self.store)
                # Switch to oseries tab
                self.dock_widget.tabs.setCurrentIndex(0)

            # Refresh map layers to show the new oseries
            self.load_layers_from_store()

            self.iface.messageBar().pushMessage(
                "Success", f"Added {added_count} series from BRO.", level=0
            )

        except Exception as e:
            import traceback

            self.iface.messageBar().pushMessage(
                "Error", f"Failed to add BRO series to store: {str(e)}", level=2
            )
            print(traceback.format_exc())

    def _add_knmi_stresses_to_store(self, stresses_dict):
        """Add selected KNMI stresses from dialog to the pastastore."""
        if not self.store:
            return

        try:
            added_count = 0
            for stress_name, stress_info in stresses_dict.items():
                series = stress_info.get("series")
                metadata = stress_info.get("metadata", {})
                if series is None:
                    continue
                if self._add_stress_to_store(series, stress_name, metadata):
                    added_count += 1

            if added_count > 0:
                self.store_modified = True
                self.load_layers_from_store()
                if self.dock_widget:
                    self.dock_widget.populate_lists(self.store)
                    self.dock_widget.tabs.setCurrentIndex(1)
                    self._set_active_layer_for_current_tab()

            self.iface.messageBar().pushMessage(
                "Success", f"Added {added_count} KNMI stress series.", level=0
            )

        except Exception as e:
            import traceback

            self.iface.messageBar().pushMessage(
                "Error", f"Failed to add KNMI stresses to store: {str(e)}", level=2
            )
            print(traceback.format_exc())
