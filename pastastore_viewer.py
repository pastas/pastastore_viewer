# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import (
    QSettings,
    QTranslator,
    qVersion,
    QCoreApplication,
    Qt,
    QVariant,
)
from qgis.PyQt.QtWidgets import (
    QAction,
    QFileDialog,
    QMessageBox,
    QDockWidget,
    QProgressDialog,
    QApplication,
)
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsFields,
    QgsWkbTypes,
    QgsLayerTreeLayer,
    QgsFeatureRequest,
    QgsCoordinateReferenceSystem,
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
    import pyqtgraph as pg

    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False

from .main_dock import PastastoreMainDock
from .plot_dock import PastastorePlotDock
from .settings_dialog import PastastoreSettingsDialog
from .model_editor import ModelEditorDialog
from .results_plot import ResultsPlotDialog
from .oseries_editor import OseriesEditorDialog


class PastastoreViewer:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = self.tr("&Pastastore Viewer")
        self.store = None
        self.dock_widget = None
        self.plot_dock = None
        self.action = None
        self.is_updating_selection = False

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

        # Connect to selection changes on map
        self.iface.mapCanvas().selectionChanged.connect(self.on_map_selection_changed)

        # Connect project signals for automatic restoration
        QgsProject.instance().readProject.connect(self.on_project_read)
        QgsProject.instance().cleared.connect(self.on_project_new)

        # Check if project is already loaded (e.g. plugin reload)
        if QgsProject.instance().fileName():
            self.on_project_read()

    def unload(self):
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
            self.dock_widget.item_selected.connect(self.on_item_selected)
            self.dock_widget.settings_requested.connect(self.open_settings)
            self.dock_widget.tab_changed.connect(self.on_tab_changed)
            self.dock_widget.delete_model_requested.connect(self.delete_models)
            self.dock_widget.edit_model_requested.connect(self.open_model_editor)
            self.dock_widget.results_requested.connect(self.open_results_plot)
            self.dock_widget.select_models_for_oseries_requested.connect(
                self.select_models_for_oseries
            )
            self.dock_widget.select_models_for_stresses_requested.connect(
                self.select_models_for_stresses
            )
            self.dock_widget.edit_oseries_requested.connect(self.open_oseries_editor)

        if not self.plot_dock:
            self.plot_dock = PastastorePlotDock(self.iface.mainWindow())
            self.iface.addDockWidget(Qt.BottomDockWidgetArea, self.plot_dock)

            # Connect plot dock visibility signal if needed
            self.plot_dock.visibilityChanged.connect(
                self.plot_dock.save_state_to_project
            )

        if main_dock_created:
            self.dock_widget.restore_state_from_project()

        return self.dock_widget

    def run(self):
        """Run method that loads the dock widgets."""
        self.create_dock()
        self.dock_widget.show()
        self.dock_widget.raise_()
        self.dock_widget.activateWindow()

        self.plot_dock.show()
        self.plot_dock.raise_()
        self.plot_dock.activateWindow()

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
                self.iface.mainWindow(), "Error", "pastastore library not installed."
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
            self._load_from_path(filename)
            if self.dock_widget:
                self.dock_widget.save_state_to_project()

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

            try:
                self.store = pst.PastaStore.from_zip(filename)
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
            self.dock_widget.select_items_in_list(pst_type, names)
        self.plot_item(pst_type, names)

    def plot_item(self, category, names):
        if not self.store:
            return
        if not names:
            if self.plot_dock:
                self.plot_dock.clear_plot(category=category)
            return

        if isinstance(names, str):
            names = [names]

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

                self.iface.messageBar().pushMessage(
                    "Success", f"Deleted {len(names)} model(s)", level=0
                )

            except Exception as e:
                import traceback

                self.iface.messageBar().pushMessage(
                    "Error", f"Failed to delete models: {str(e)}", level=2
                )
                print(traceback.format_exc())

    def open_model_editor(self, model_name):
        if not self.store:
            return

        try:
            # Get the model (create a copy/new instance to be safe)
            ml = self.store.get_models(model_name)

            dlg = ModelEditorDialog(ml, self.store, self.iface.mainWindow())
            if dlg.exec_():
                new_model, new_name = dlg.get_model_data()

                # Save to store
                # If name changed, we might want to delete the old one?
                # User said "optionally with a new name", implying Save As behavior.
                # If name is different, we add as new.
                # If name is same, we overwrite.

                # Check if name exists if different
                if new_name != model_name:
                    # If user wants to rename, we probably should keep it simple and just add new model.
                    # Or ask? Let's just add it.
                    pass
                else:
                    # Overwrite: remove old one first?
                    # pastastore.add_model with overwrite=True usually handles it?
                    # But add_model adds a *new* model structure usually.
                    # Here we have a pastas Model object.
                    pass

                self.store.add_model(new_model, overwrite=True)

                # If name changed and user wanted to RENAME, we would delete old one.
                # But "Save with new name" usually implies keeping old one?
                # Let's assume "Save As" behavior (keep old) unless name is same.

                self.iface.messageBar().pushMessage(
                    "Success", f"Saved model: {new_name}", level=0
                )

                # Update UI
                if self.dock_widget:
                    self.dock_widget.populate_lists(self.store)

                # Reload layers to reflect changes (e.g. if model results changed)
                # This might be heavy if many models, but safe.
                self.load_layers_from_store()

        except Exception as e:
            import traceback

            self.iface.messageBar().pushMessage(
                "Error", f"Failed to edit model: {str(e)}", level=2
            )
            print(traceback.format_exc())

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
