# Pastastore Viewer License Server (Strict Online)

Mini FastAPI licentieserver voor Pastastore Viewer met:
- Activeren per machine
- Device-limiet per licentie
- Strikt online validatie voor betaalde features

## Belangrijk

Deze variant gebruikt geen RSA-ondertekende offline bundles.
De plugin controleert Pro/ProNL altijd online via de server.
Bij geen serververbinding vallen betaalde features terug naar free-modus.

## Snel starten

1. Installeer dependencies:

```bash
pip install -r requirements.txt
```

2. Start de server:

```bash
uvicorn app:app --host 0.0.0.0 --port 8787
```

Of via Fly.io (gebruikt poort 8787 conform `fly.toml`):

```bash
fly deploy
```

3. Zet admin token:

```bash
set LICENSE_ADMIN_TOKEN=vervang-mij
```

4. Maak een licentie aan:

```bash
curl -X POST http://localhost:8787/admin/licenses ^
  -H "Content-Type: application/json" ^
  -H "X-Admin-Token: vervang-mij" ^
  -d "{\"customer_name\":\"Waterbedrijf X\",\"license_type\":\"proNL\",\"days_valid\":365,\"max_devices\":5}"
```

5. Activeer in plugin met:
- license key uit stap 4
- server URL (bijv. `https://pastastore-license-server.fly.dev`)

## API

### `GET /health`
Healthcheck.

### `POST /activate`
Activeert licentie op machine en retourneert entitlement.

### `POST /validate`
Valideert bestaande activatie online.

### `POST /deactivate`
Deactiveert machine voor licentie.

### `POST /admin/licenses`
Admin endpoint om licenties uit te geven.

## Data

Databasebestand:
- `license_server.db`

Tabellen:
- `licenses`
- `activations`

## Deploy op Fly.io

Fly.io heeft een **gratis tier** (3 kleine VMs) en ondersteunt persistent volumes — geschikt voor productiegebruik zonder maandelijkse vaste kosten bij laag gebruik.

### Vereisten

Installeer de Fly CLI:

```bash
# Windows (PowerShell)
pwsh -Command "iwr https://fly.io/install.ps1 -useb | iex"
```

Daarna inloggen:

```bash
fly auth login
```

### Stappen

1. **Ga naar de `license_server` map:**

```bash
cd license_server
```

2. **Initialiseer de Fly app** (eenmalig — sla `fly.toml` op in git):

```bash
fly launch --name pastastore-license-server --region ams --no-deploy
```

   Kies bij de prompt **geen** Postgres of Redis.

3. **Maak een persistent volume aan** (eenmalig):

```bash
fly volumes create license_data --region ams --size 1
```

4. **Stel het admin token in als secret:**

```bash
fly secrets set LICENSE_ADMIN_TOKEN=vervang-met-sterk-token
```

5. **Deploy:**

```bash
fly deploy
```

6. **Controleer de app URL:**

```bash
fly status
```

   De URL is `https://pastastore-license-server.fly.dev` (of de naam die je hebt gekozen).

### Updates deployen

```bash
fly deploy
```

Het volume blijft behouden tussen deploys.

## Eerste productie-checklist (Fly.io)

Vervang in voorbeelden:
- `YOUR_FLY_APP` door jouw app-naam (bijv. `pastastore-license-server`)
- `YOUR_ADMIN_TOKEN` door het token dat je met `fly secrets set` hebt ingesteld

1. Health check:

```bash
curl https://YOUR_FLY_APP.fly.dev/health
```

2. Eerste licentie aanmaken:

```bash
curl -X POST https://YOUR_FLY_APP.fly.dev/admin/licenses \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" \
  -d '{"customer_name":"Waterbedrijf X","license_type":"proNL","days_valid":365,"max_devices":5}'
```

3. Activeer licentie in plugin met URL `https://YOUR_FLY_APP.fly.dev`.
4. Gebruik in plugin `Validate License Online`.
5. Controleer feature locks (free/pro/proNL).

### Logs bekijken

```bash
fly logs
```

### App stoppen/starten

```bash
fly scale count 0   # stoppen
fly scale count 1   # starten
```
