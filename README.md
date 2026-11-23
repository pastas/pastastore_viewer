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

### Releasing a new version

1. Update `version=` and add an entry under `changelog=` in [metadata.txt](metadata.txt) (the QGIS plugin repository rejects duplicate version numbers).
2. *(Optional)* Run a test build first via **Actions > Publish QGIS Plugin > Run workflow** (leaving **Upload built plugin zip to plugins.qgis.org** unchecked) and test the downloaded `pastastore_viewer` zip in QGIS.
3. Commit and push the updated `metadata.txt` (and any other changes) to `main`.
4. On GitHub, go to **Releases > Draft a new release**:
   - Create a new tag matching `version` in `metadata.txt` (e.g. `0.1.2`), targeting `main`.
   - Enter a release title and notes, then click **Publish release**.
5. Publishing the release automatically runs the `Publish QGIS Plugin` workflow, which bundles dependencies via `bundle_deps.py`, builds `pastastore_viewer.zip`, uploads it as a workflow artifact, and publishes it to `plugins.qgis.org`.
6. Check the **Actions** tab to confirm the upload succeeded.

> **Note:** Draft releases do not trigger publishing until you click **Publish release**. Pre-releases *do* trigger the `published` event and will upload to `plugins.qgis.org`, so use a manual workflow run with **Upload built plugin zip to plugins.qgis.org** unchecked for test builds.

### How publishing is triggered

- **Manual (test build or publish)**: run the workflow from **Actions > Publish QGIS Plugin > Run workflow**.
  - Leave **Upload built plugin zip to plugins.qgis.org** unchecked (default) to build a downloadable `pastastore_viewer.zip` workflow artifact (`pastastore_viewer`) without publishing. Install it directly in QGIS via **Plugins > Manage and Install Plugins > Install from ZIP** (or, if macOS Safari auto-extracts it into a `pastastore_viewer/` folder, copy that folder into your QGIS profile's `python/plugins/` directory).
  - Check **Upload built plugin zip to plugins.qgis.org** to also publish the built zip to the QGIS plugin repository.
- **Automatic**: when a GitHub release is published (builds the artifact and publishes to the QGIS plugin repository).

The workflow runs `bundle_deps.py` to package dependencies, creates `pastastore_viewer.zip` containing the plugin folder, uploads it as a GitHub Actions artifact, and (when publishing) uploads it through the QGIS plugin API endpoint using the `QGIS_PLUGIN_TOKEN`.

