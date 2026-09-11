# Pastastore Viewer QGIS Plugin

**⚠️ PROPRIETARY SOFTWARE**

This plugin is proprietary. Modification and redistribution are **strictly prohibited**. 
See [LICENSE](LICENSE) for details.


You may use free features without a license; Pro features require a valid paid license.

---

This plugin allows you to visualize time series and models stored in a `pastastore` zip file directly in QGIS.

## Features
- Load a `pastastore` zip file.
- View `oseries`, `stresses`, and `models` as vector layers on the map.
- Interactive plots for time series and model results using `pyqtgraph`.
- Configurable coordinate column names (default 'x' and 'y').

## Installation


### Dependencies
This plugin requires `pastastore`, `pastas`, and `pyqtgraph` to be bundled in the plugin's `dependencies/` folder before use. The plugin does not auto-install dependencies at runtime.

#### Bundling dependencies (required)
Bundle dependencies inside the plugin so users do not need internet access and to ensure compatibility:

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

## Publish to QGIS Plugin Repository

This repository includes a GitHub Actions workflow to publish the plugin to the QGIS plugin repository.

Workflow file:
- `.github/workflows/publish-qgis-plugin.yml`

### Required GitHub repository secrets

- `QGIS_PLUGIN_TOKEN`: plugin upload token created on [plugins.qgis.org](https://plugins.qgis.org)

### How publishing is triggered

- **Manual**: run the workflow from **Actions > Publish QGIS Plugin > Run workflow**
- **Automatic**: when a GitHub release is published

The workflow runs `bundle_deps.py` to package dependencies, creates `pastastore_viewer.zip` containing the plugin folder, and uploads it through the QGIS plugin API endpoint using the `QGIS_PLUGIN_TOKEN`.

