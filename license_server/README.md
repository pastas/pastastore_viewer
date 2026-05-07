# Pastastore Viewer License Server (Strict Online)

Mini FastAPI license server for Pastastore Viewer with:
- Per-machine activation
- Device limit per license
- Strict online validation for paid features

## Important

This variant does not use RSA-signed offline bundles.
The plugin always validates Pro/ProNL features online via the server.
If the server is unreachable, paid features fall back to free mode.

## API

### `GET /health`
Health check.

### `POST /activate`
Activates a license on a machine and returns the entitlement.

### `POST /validate`
Validates an existing activation online.

### `POST /deactivate`
Deactivates a machine for a license.

### `GET /admin`\nBrowser-based admin UI — list and create licenses without PowerShell.\n\n### `POST /admin/licenses`
Admin endpoint to issue licenses.

### `GET /admin/licenses`
Admin endpoint to list all licenses with active device count.

## Data

Database file:
- `license_server.db`

Tables:
- `licenses`
- `activations`

## Deploy to Fly.io

Fly.io has a **free tier** (3 small VMs) and supports persistent volumes — suitable for production use without fixed monthly costs at low usage.

### Requirements

Install the Fly CLI:

```bash
# Windows (PowerShell)
pwsh -Command "iwr https://fly.io/install.ps1 -useb | iex"
```

Then log in:

```bash
fly auth login
```

### Steps

1. **Navigate to the `license_server` folder:**

```bash
cd license_server
```

2. **Initialize the Fly app** (once — commit `fly.toml` to git):

```bash
fly launch --name pastastore-license-server --region ams --no-deploy
```

   When prompted, choose **no** Postgres or Redis.

3. **Create a persistent volume** (once):

```bash
fly volumes create license_data --region ams --size 1
```

   Note: Fly will show a warning about "2 or more volumes" for high availability.
   This setup intentionally uses 1 machine + 1 volume so all writes go to the same SQLite database.
   The warning is expected and not an error.

4. **Set the admin token as a secret:**

```bash
fly secrets set LICENSE_ADMIN_TOKEN=replace-with-strong-token
```

5. **Deploy:**

```bash
fly deploy
```

6. **Check the app URL:**

```bash
fly status
```

   The URL will be `https://pastastore-license-server.fly.dev` (or the name you chose).

### Deploying updates

```bash
fly deploy
```

The volume is preserved between deploys.

## First production checklist (Fly.io)

Replace in examples:
- `YOUR_ADMIN_TOKEN` with the token set via `fly secrets set`

1. Health check:

```powershell
Invoke-RestMethod https://pastastore-license-server.fly.dev/health
```

2. Create first license:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "https://pastastore-license-server.fly.dev/admin/licenses" `
  -Headers @{ "Content-Type" = "application/json"; "X-Admin-Token" = "YOUR_ADMIN_TOKEN" } `
  -Body '{"customer_name":"Example Customer","license_type":"proNL","days_valid":365,"max_devices":5}'
```

3. List all licenses:

```powershell
Invoke-RestMethod `
  -Uri "https://pastastore-license-server.fly.dev/admin/licenses" `
  -Headers @{ "X-Admin-Token" = "REDACTED_ADMIN_TOKEN" }
```
4. Activate license in plugin with URL `https://pastastore-license-server.fly.dev`.
5. Use `Validate License Online` in the plugin.
6. Verify feature locks (free/pro/proNL).

### View logs

```bash
fly logs
```

### Stop/start app

```bash
fly scale count 0   # stop
fly scale count 1   # start
```

Tip for SQLite consistency: keep it at 1 machine (`fly scale count 1`) so all requests always hit the same database.
