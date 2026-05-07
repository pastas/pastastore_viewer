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
- server URL (bijv. `https://YOUR_RENDER_URL`)

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

## Deploy op Render

### Optie A: Render Blueprint (aanbevolen)

Gebruik [render.yaml](../render.yaml).

Stappen:
1. Push repository naar GitHub.
2. In Render: New + > Blueprint.
3. Kies repository en deploy.
4. Zet na deploy `LICENSE_ADMIN_TOKEN` (indien niet automatisch gegenereerd naar wens).

Blueprint configureert:
- Root directory `license_server`
- Build/start commands
- Health check `/health`
- Persistent disk `/var/data`
- `LICENSE_DB_PATH=/var/data/license_server.db`

### Optie B: Handmatig Web Service instellen

1. Push repository naar GitHub.
2. Maak in Render een nieuwe Web Service.
3. Root Directory: `license_server`.
4. Build Command:

```bash
pip install -r requirements.txt
```

5. Start Command:

```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

6. Environment Variables:
- `LICENSE_ADMIN_TOKEN`: sterk geheim token
- `LICENSE_DB_PATH`: `/var/data/license_server.db`

7. Health Check Path: `/health`

8. Voeg Persistent Disk toe en mount op `/var/data`.

## Eerste productie-checklist (Render)

Vervang in voorbeelden:
- `YOUR_RENDER_URL`
- `YOUR_ADMIN_TOKEN`

1. Health check:

```bash
curl https://YOUR_RENDER_URL/health
```

2. Eerste licentie aanmaken:

```bash
curl -X POST https://YOUR_RENDER_URL/admin/licenses \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" \
  -d '{"customer_name":"Waterbedrijf X","license_type":"proNL","days_valid":365,"max_devices":5}'
```

3. Activeer licentie in plugin.
4. Gebruik in plugin `Validate License Online`.
5. Controleer feature locks (free/pro/proNL).
