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

### `POST /create-checkout-session`
Creates an annual recurring Stripe Checkout Session (`mode="subscription"`) for online purchases (iDEAL, Creditcard, Bancontact, Wero) with automatic VAT calculation and PDF invoicing.

### `POST /webhook/stripe`
Stripe Webhook endpoint. Handles:
- `checkout.session.completed`: Generates and registers new licenses in the database.
- `invoice.payment_succeeded`: Extends license validity by **+365 days** on each successful yearly renewal payment.
- `customer.subscription.updated` / `customer.subscription.deleted`: Updates `auto_renew` state upon cancellation.

### `POST /create-portal-session`
Creates a Stripe Billing Portal session (`stripe.billing_portal.Session`) allowing customers to manage their payment methods, view invoices, or cancel their automatic renewal.

### `GET /manage-subscription`
Customer portal lookup page where users enter their license key to open their Stripe Customer Portal.

### `GET /checkout/success`
Checkout completion page for customers. Displays their newly issued license key, copy button, activation steps in QGIS, link to download their Stripe PDF invoice, and button to manage or cancel automatic renewal.


## Stripe Environment Variables

Set the following environment variables in production (e.g. via `fly secrets set`):

- `STRIPE_SECRET_KEY`: Your Stripe secret key (`sk_live_...` or `sk_test_...`).
- `STRIPE_WEBHOOK_SECRET`: Webhook signing secret (`whsec_...`) from Stripe Dashboard -> Developers -> Webhooks.
- `STRIPE_SUCCESS_URL` (optional): Custom success URL template (defaults to `https://<domain>/checkout/success?session_id={CHECKOUT_SESSION_ID}`).
- `STRIPE_CANCEL_URL` (optional): Custom cancel URL (defaults to `https://<domain>/request-license`).

## Local Development & Testing Webhooks

1. Install the [Stripe CLI](https://stripe.com/docs/stripe-cli).
2. Forward webhooks to your local server:
   ```bash
   stripe listen --forward-to localhost:8000/webhook/stripe
   ```
3. Copy the outputted webhook signing secret (`whsec_...`) and run your FastAPI server:
   ```bash
   export STRIPE_SECRET_KEY="sk_test_..."
   export STRIPE_WEBHOOK_SECRET="whsec_..."
   uvicorn app:app --reload
   ```

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
  -Headers @{ "X-Admin-Token" = "YOUR_ADMIN_TOKEN" }
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
