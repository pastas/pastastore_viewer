# Pastastore Viewer QGIS Plugin

This plugin allows you to visualize time series and models stored in a `pastastore` zip file directly in QGIS.

## Features
- Load a `pastastore` zip file.
- View `oseries`, `stresses`, and `models` as vector layers on the map.
- Interactive plots for time series and model results using `pyqtgraph`.
- Configurable coordinate column names (default 'x' and 'y').

## Installation
1. Ensure you have `pastastore` and `pyqtgraph` installed in your QGIS Python environment.
   - You can usually do this via the QGIS Python Console:
     ```python
     import subprocess
     subprocess.check_call(['pip', 'install', 'pastastore', 'pyqtgraph'])
     ```
2. Copy this folder into your QGIS plugins directory:
   - Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\pastastore_viewer`
3. Restart QGIS or use the "Plugin Reloader" plugin to load it.

## Usage
1. Click the **Load Pastastore** icon in the toolbar.
2. Select your `.zip` file.
3. Layers will be added to a group called "Pastastore".
4. Select a point on the map (make sure the layer is active) to view the plot in the side dock.

## Settings
You can change the expected coordinate column names in the **Settings** menu. The plugin will also try to automatically detect columns containing 'x' or 'y' if the defaults are not found.
