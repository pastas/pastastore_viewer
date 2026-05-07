# Pastastore Viewer QGIS Plugin

This plugin allows you to visualize time series and models stored in a `pastastore` zip file directly in QGIS.

## Features
- Load a `pastastore` zip file.
- View `oseries`, `stresses`, and `models` as vector layers on the map.
- Interactive plots for time series and model results using `pyqtgraph`.
- Configurable coordinate column names (default 'x' and 'y').

## Installation

### Dependencies
This plugin requires `pastastore`, `pastas`, and `pyqtgraph`. You have two options:

#### Option 1: Auto-install at runtime (recommended for end users)
The plugin will automatically prompt to download and install missing dependencies on first load. 
- **Requires:** QGIS Python with `pip` available (install `python3-pip` via OSGeo4W Setup if needed)
- **Installation location:** Plugin's local `dependencies/` folder (isolated from other plugins)
- **Offline:** Will fail with a clear message if no internet connection

#### Option 2: Pre-bundle dependencies (recommended for offline deployment)
Bundle dependencies inside the plugin so users do not need internet access:

1. From the OSGeo4W Shell (or using the Python interpreter bundled with QGIS):
   ```bash
   cd path/to/pastastore_viewer
   python bundle_deps.py
   ```
   This creates a `dependencies/` folder with `pastastore`, `pastas`, and `pyqtgraph` (without transitive dependencies—QGIS provides `numpy`, `pandas`, etc.).

2. Alternatively, install manually:
   ```bash
   python -m pip install --target dependencies --no-deps pastastore pastas pyqtgraph
   ```

### Plugin Installation
1. Copy this folder into your QGIS plugins directory:
   - Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\pastastore_viewer`
2. Restart QGIS or use the "Plugin Reloader" plugin to load it.

### Development
For local development in a virtual environment, use [requirements.txt](requirements.txt):
```bash
pip install -r requirements.txt
```

## Usage
1. Click the **Load Pastastore** icon in the toolbar.
2. Select your `.zip` file.
3. Layers will be added to a group called "Pastastore".
4. Select a point on the map (make sure the layer is active) to view the plot in the side dock.

## Settings
You can change the expected coordinate column names in the **Settings** menu. The plugin will also try to automatically detect columns containing 'x' or 'y' if the defaults are not found.

## Licensing (Free, Pro, ProNL)

The plugin now supports three tiers:
- Free: viewing and plotting data.
- Pro: model creation/editing workflows.
- ProNL: Pro + BRO/KNMI import workflows for Dutch data.

### Plugin side

Use the Plugin menu entries:
- Activate/Update License
- Validate License Online
- Deactivate License

The plugin uses a strict online workflow: paid features are enabled only after successful online activation/validation against the license server.

Without server connectivity, the plugin falls back to free-only mode for paid features.

### Server side

A reference FastAPI license server is included in [license_server/README.md](license_server/README.md).

Important:
- Deploy and configure the license server from [license_server/README.md](license_server/README.md).
