from __future__ import annotations

import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import os

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("LICENSE_DB_PATH", BASE_DIR / "license_server.db"))
ADMIN_TOKEN = os.environ.get("LICENSE_ADMIN_TOKEN", "")


class ActivationRequest(BaseModel):
    license_key: str = Field(min_length=6, max_length=128)
    machine_id: str = Field(min_length=16, max_length=128)
    device_name: str = Field(default="unknown-device", max_length=200)
    plugin_version: str = Field(default="unknown", max_length=50)


class ValidationRequest(BaseModel):
    license_key: str = Field(min_length=6, max_length=128)
    machine_id: str = Field(min_length=16, max_length=128)


class DeactivationRequest(BaseModel):
    license_key: str = Field(min_length=6, max_length=128)
    machine_id: str = Field(min_length=16, max_length=128)


class CreateLicenseRequest(BaseModel):
    customer_name: str = Field(min_length=1, max_length=200)
    license_type: str = Field(pattern=r"^(pro|proNL)$")
    days_valid: int = Field(default=365, ge=1, le=3650)
    max_devices: int = Field(default=1, ge=1, le=100)


@dataclass
class LicenseRecord:
    id: str
    license_key: str
    customer_name: str
    license_type: str
    expires_at: str
    max_devices: int
    is_active: int


app = FastAPI(title="Pastastore Viewer License Server", version="2.0.0")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(dt_str: str) -> datetime:
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1] + "+00:00"
    return datetime.fromisoformat(dt_str)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS licenses (
                id TEXT PRIMARY KEY,
                license_key TEXT UNIQUE NOT NULL,
                customer_name TEXT NOT NULL,
                license_type TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                max_devices INTEGER NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS activations (
                id TEXT PRIMARY KEY,
                license_id TEXT NOT NULL,
                machine_id TEXT NOT NULL,
                device_name TEXT NOT NULL,
                plugin_version TEXT NOT NULL,
                activated_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                UNIQUE(license_id, machine_id),
                FOREIGN KEY(license_id) REFERENCES licenses(id) ON DELETE CASCADE
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def feature_list(license_type: str) -> list[str]:
    if license_type == "proNL":
        return ["pro", "pronl"]
    if license_type == "pro":
        return ["pro"]
    return []


def get_license_by_key(license_key: str) -> LicenseRecord | None:
    conn = db()
    try:
        row = conn.execute(
            """
            SELECT id, license_key, customer_name, license_type, expires_at, max_devices, is_active
            FROM licenses
            WHERE license_key = ?
            """,
            (license_key,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return None

    return LicenseRecord(
        id=row["id"],
        license_key=row["license_key"],
        customer_name=row["customer_name"],
        license_type=row["license_type"],
        expires_at=row["expires_at"],
        max_devices=int(row["max_devices"]),
        is_active=int(row["is_active"]),
    )


def count_activations(license_id: str) -> int:
    conn = db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM activations WHERE license_id = ?", (license_id,)
        ).fetchone()
        return int(row["n"])
    finally:
        conn.close()


def has_activation(license_id: str, machine_id: str) -> bool:
    conn = db()
    try:
        row = conn.execute(
            "SELECT id FROM activations WHERE license_id = ? AND machine_id = ?",
            (license_id, machine_id),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def upsert_activation(
    license_id: str,
    machine_id: str,
    device_name: str,
    plugin_version: str,
) -> None:
    now = isoformat_z(utcnow())
    conn = db()
    try:
        existing = conn.execute(
            "SELECT id FROM activations WHERE license_id = ? AND machine_id = ?",
            (license_id, machine_id),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE activations
                SET device_name = ?, plugin_version = ?, last_seen_at = ?
                WHERE license_id = ? AND machine_id = ?
                """,
                (device_name, plugin_version, now, license_id, machine_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO activations (
                    id, license_id, machine_id, device_name, plugin_version,
                    activated_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    license_id,
                    machine_id,
                    device_name,
                    plugin_version,
                    now,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def deactivate_activation(license_id: str, machine_id: str) -> int:
    conn = db()
    try:
        cur = conn.execute(
            "DELETE FROM activations WHERE license_id = ? AND machine_id = ?",
            (license_id, machine_id),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def build_entitlement(lic: LicenseRecord, machine_id: str) -> dict[str, Any]:
    now = utcnow()
    return {
        "license_id": lic.id,
        "license_key": lic.license_key,
        "customer_name": lic.customer_name,
        "license_type": lic.license_type,
        "features": feature_list(lic.license_type),
        "max_devices": lic.max_devices,
        "machine_id": machine_id,
        "issued_at": isoformat_z(now),
        "expires_at": lic.expires_at,
    }


def ensure_admin_token(token: str | None) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="LICENSE_ADMIN_TOKEN is not configured on the server.",
        )
    if not token or token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid admin token.")


def random_license_key() -> str:
    chunks = [secrets.token_hex(2).upper() for _ in range(4)]
    return "-".join(chunks)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/admin", response_class=HTMLResponse)
def admin_ui() -> str:
    return """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>License Admin</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 1000px; margin: 40px auto; padding: 0 20px; background: #f5f5f5; }
  h1 { color: #333; }
  .card { background: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
  input, select { padding: 8px; border: 1px solid #ccc; border-radius: 4px; width: 100%; box-sizing: border-box; margin-bottom: 8px; }
  button { padding: 7px 14px; background: #2563eb; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
  button:hover { background: #1d4ed8; }
  button.danger { background: #dc2626; padding: 4px 10px; font-size: 12px; }
  button.danger:hover { background: #b91c1c; }
  button.expand { background: #6b7280; padding: 4px 10px; font-size: 12px; }
  button.expand:hover { background: #4b5563; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { text-align: left; background: #f0f0f0; padding: 8px; border-bottom: 2px solid #ddd; white-space: nowrap; }
  td { padding: 8px; border-bottom: 1px solid #eee; vertical-align: middle; }
  .devices-row td { background: #f9fafb; padding: 0; }
  .devices-inner { padding: 12px 16px; }
  .devices-table { font-size: 13px; margin: 0; }
  .devices-table th { background: #eef2ff; font-size: 12px; }
  .devices-table td { border-bottom: 1px solid #e5e7eb; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: bold; }
  .badge-pro { background: #dbeafe; color: #1d4ed8; }
  .badge-pronl { background: #d1fae5; color: #065f46; }
  .badge-active { background: #dcfce7; color: #166534; }
  .badge-inactive { background: #fee2e2; color: #991b1b; }
  .msg { margin-top: 10px; padding: 8px; border-radius: 4px; display: none; font-size: 13px; }
  .ok { background: #dcfce7; color: #166534; }
  .err { background: #fee2e2; color: #991b1b; }
  label { font-size: 13px; font-weight: 600; color: #555; display: block; margin-bottom: 2px; }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .mono { font-family: monospace; font-size: 12px; }
</style>
</head>
<body>
<h1>Pastastore License Admin</h1>

<div class="card">
  <h2 style="margin-top:0">Admin Token</h2>
  <label for="token">Token</label>
  <input type="password" id="token" placeholder="Your LICENSE_ADMIN_TOKEN" />
  <button onclick="loadLicenses()">Load licenses</button>
  <div id="status" class="msg"></div>
</div>

<div class="card">
  <h2 style="margin-top:0">Create License</h2>
  <div class="row">
    <div>
      <label for="customer">Customer name</label>
      <input type="text" id="customer" placeholder="e.g. Waterbedrijf X" />
    </div>
    <div>
      <label for="ltype">License type</label>
      <select id="ltype">
        <option value="proNL">proNL (Pro + BRO/KNMI)</option>
        <option value="pro">pro</option>
      </select>
    </div>
    <div>
      <label for="days">Valid (days)</label>
      <input type="number" id="days" value="365" min="1" max="3650" />
    </div>
    <div>
      <label for="devices">Max devices</label>
      <input type="number" id="devices" value="1" min="1" max="100" />
    </div>
  </div>
  <button onclick="createLicense()">Create license</button>
  <div id="create-status" class="msg"></div>
</div>

<div class="card">
  <h2 style="margin-top:0">All Licenses</h2>
  <div id="licenses-table"><em style="color:#999">Enter token and click "Load licenses".</em></div>
</div>

<script>
const token = () => document.getElementById('token').value.trim();

const api = (path, opts={}) => fetch(path, {
  ...opts,
  headers: { 'X-Admin-Token': token(), 'Content-Type': 'application/json', ...(opts.headers||{}) }
});

const show = (id, msg, ok) => {
  const el = document.getElementById(id);
  el.textContent = msg;
  el.className = 'msg ' + (ok ? 'ok' : 'err');
  el.style.display = 'block';
};

const fmtDate = iso => new Date(iso).toLocaleString();

async function loadLicenses() {
  const res = await api('/admin/licenses');
  if (!res.ok) { show('status', 'Error: ' + res.status + ' ' + res.statusText, false); return; }
  const data = await res.json();
  show('status', 'Loaded ' + data.length + ' license(s).', true);
  if (!data.length) { document.getElementById('licenses-table').innerHTML = '<em>No licenses yet.</em>'; return; }

  let html = `<table><thead><tr>
    <th>Customer</th><th>Type</th><th>Key</th><th>Status</th>
    <th>Devices</th><th>Expires</th><th></th>
  </tr></thead><tbody>`;

  data.forEach(l => {
    const type = l.license_type === 'proNL'
      ? '<span class="badge badge-pronl">proNL</span>'
      : '<span class="badge badge-pro">pro</span>';
    const active = l.is_active
      ? '<span class="badge badge-active">active</span>'
      : '<span class="badge badge-inactive">inactive</span>';
    html += `<tr>
      <td>${l.customer_name}</td>
      <td>${type}</td>
      <td class="mono">${l.license_key}</td>
      <td>${active}</td>
      <td>${l.active_devices} / ${l.max_devices}</td>
      <td>${fmtDate(l.expires_at)}</td>
      <td><button class="expand" onclick="toggleDevices('${l.id}', this)">&#9654; Devices</button></td>
    </tr>
    <tr id="dev-row-${l.id}" class="devices-row" style="display:none">
      <td colspan="7"><div class="devices-inner" id="dev-${l.id}">Loading...</div></td>
    </tr>`;
  });

  html += '</tbody></table>';
  document.getElementById('licenses-table').innerHTML = html;
}

async function toggleDevices(licId, btn) {
  const row = document.getElementById('dev-row-' + licId);
  if (row.style.display !== 'none') {
    row.style.display = 'none';
    btn.innerHTML = '&#9654; Devices';
    return;
  }
  row.style.display = '';
  btn.innerHTML = '&#9660; Devices';
  await loadDevices(licId);
}

async function loadDevices(licId) {
  const container = document.getElementById('dev-' + licId);
  const res = await api('/admin/licenses/' + licId + '/activations');
  if (!res.ok) { container.textContent = 'Error loading devices.'; return; }
  const data = await res.json();
  if (!data.length) { container.innerHTML = '<em>No activated devices.</em>'; return; }

  let html = `<table class="devices-table"><thead><tr>
    <th>Device name</th><th>Machine ID</th><th>Plugin version</th>
    <th>Activated</th><th>Last seen</th><th></th>
  </tr></thead><tbody>`;
  data.forEach(d => {
    html += `<tr>
      <td>${d.device_name}</td>
      <td class="mono">${d.machine_id}</td>
      <td>${d.plugin_version}</td>
      <td>${fmtDate(d.activated_at)}</td>
      <td>${fmtDate(d.last_seen_at)}</td>
      <td><button class="danger" onclick="deactivateDevice('${licId}', '${d.machine_id}')">Deactivate</button></td>
    </tr>`;
  });
  html += '</tbody></table>';
  container.innerHTML = html;
}

async function deactivateDevice(licId, machineId) {
  if (!confirm('Deactivate this device?')) return;
  const res = await api('/admin/licenses/' + licId + '/activations/' + encodeURIComponent(machineId), { method: 'DELETE' });
  if (!res.ok) { alert('Failed to deactivate: ' + res.status); return; }
  await loadDevices(licId);
  await loadLicenses();
}

async function createLicense() {
  const body = JSON.stringify({
    customer_name: document.getElementById('customer').value.trim(),
    license_type: document.getElementById('ltype').value,
    days_valid: parseInt(document.getElementById('days').value),
    max_devices: parseInt(document.getElementById('devices').value),
  });
  const res = await api('/admin/licenses', { method: 'POST', body });
  if (!res.ok) { const t = await res.text(); show('create-status', 'Error: ' + t, false); return; }
  const data = await res.json();
  show('create-status', 'Created: ' + data.license_key, true);
  loadLicenses();
}
</script>
</body>
</html>
"""


@app.post("/activate")
def activate(req: ActivationRequest) -> dict[str, Any]:
    lic = get_license_by_key(req.license_key)
    if not lic:
        raise HTTPException(status_code=404, detail="License key not found.")

    if not lic.is_active:
        raise HTTPException(status_code=403, detail="License is inactive.")

    if parse_iso(lic.expires_at) < utcnow():
        raise HTTPException(status_code=403, detail="License expired.")

    already_active = has_activation(lic.id, req.machine_id)
    if not already_active:
        n_active = count_activations(lic.id)
        if n_active >= lic.max_devices:
            raise HTTPException(
                status_code=409,
                detail="Device limit reached for this license.",
            )

    upsert_activation(lic.id, req.machine_id, req.device_name, req.plugin_version)
    return build_entitlement(lic, req.machine_id)


@app.post("/validate")
def validate(req: ValidationRequest) -> dict[str, Any]:
    lic = get_license_by_key(req.license_key)
    if not lic:
        raise HTTPException(status_code=404, detail="License key not found.")

    if not lic.is_active:
        raise HTTPException(status_code=403, detail="License is inactive.")

    if parse_iso(lic.expires_at) < utcnow():
        raise HTTPException(status_code=403, detail="License expired.")

    if not has_activation(lic.id, req.machine_id):
        raise HTTPException(status_code=403, detail="Machine is not activated.")

    # Update last_seen_at only, preserve existing device_name/plugin_version
    now = isoformat_z(utcnow())
    conn = db()
    try:
        conn.execute(
            "UPDATE activations SET last_seen_at = ? WHERE license_id = ? AND machine_id = ?",
            (now, lic.id, req.machine_id),
        )
        conn.commit()
    finally:
        conn.close()

    return build_entitlement(lic, req.machine_id)


@app.post("/deactivate")
def deactivate(req: DeactivationRequest) -> dict[str, Any]:
    lic = get_license_by_key(req.license_key)
    if not lic:
        raise HTTPException(status_code=404, detail="License key not found.")

    removed = deactivate_activation(lic.id, req.machine_id)
    return {"deactivated": bool(removed)}


@app.post("/admin/licenses")
def create_license(
    req: CreateLicenseRequest,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    ensure_admin_token(x_admin_token)

    now = utcnow()
    expires = now + timedelta(days=req.days_valid)

    record = {
        "id": str(uuid.uuid4()),
        "license_key": random_license_key(),
        "customer_name": req.customer_name,
        "license_type": req.license_type,
        "expires_at": isoformat_z(expires),
        "max_devices": req.max_devices,
        "is_active": 1,
        "created_at": isoformat_z(now),
    }

    conn = db()
    try:
        conn.execute(
            """
            INSERT INTO licenses (
                id, license_key, customer_name, license_type,
                expires_at, max_devices, is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["license_key"],
                record["customer_name"],
                record["license_type"],
                record["expires_at"],
                record["max_devices"],
                record["is_active"],
                record["created_at"],
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "license_key": record["license_key"],
        "customer_name": record["customer_name"],
        "license_type": record["license_type"],
        "expires_at": record["expires_at"],
        "max_devices": record["max_devices"],
    }


@app.get("/admin/licenses")
def list_licenses(
    x_admin_token: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    ensure_admin_token(x_admin_token)

    conn = db()
    try:
        rows = conn.execute(
            """
            SELECT l.id, l.license_key, l.customer_name, l.license_type,
                   l.expires_at, l.max_devices, l.is_active, l.created_at,
                   COUNT(a.id) AS active_devices
            FROM licenses l
            LEFT JOIN activations a ON a.license_id = l.id
            GROUP BY l.id
            ORDER BY l.created_at DESC
            """
        ).fetchall()
    finally:
        conn.close()

    return [dict(row) for row in rows]


@app.get("/admin/licenses/{license_id}/activations")
def list_activations(
    license_id: str,
    x_admin_token: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    ensure_admin_token(x_admin_token)

    conn = db()
    try:
        rows = conn.execute(
            """
            SELECT machine_id, device_name, plugin_version, activated_at, last_seen_at
            FROM activations
            WHERE license_id = ?
            ORDER BY last_seen_at DESC
            """,
            (license_id,),
        ).fetchall()
    finally:
        conn.close()

    return [dict(row) for row in rows]


@app.delete("/admin/licenses/{license_id}/activations/{machine_id}")
def admin_deactivate(
    license_id: str,
    machine_id: str,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    ensure_admin_token(x_admin_token)

    removed = deactivate_activation(license_id, machine_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Activation not found.")
    return {"deactivated": True}
