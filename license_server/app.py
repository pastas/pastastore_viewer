from __future__ import annotations

import json
import os
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import stripe

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("LICENSE_DB_PATH", BASE_DIR / "license_server.db"))
ADMIN_TOKEN = os.environ.get("LICENSE_ADMIN_TOKEN", "")

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_SUCCESS_URL = os.environ.get("STRIPE_SUCCESS_URL", "")
STRIPE_CANCEL_URL = os.environ.get("STRIPE_CANCEL_URL", "")


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


class CreateCheckoutRequest(BaseModel):
    license_type: str = Field(pattern=r"^(pro|proNL)$")
    max_devices: int = Field(default=1, ge=1, le=100)
    customer_name: str = Field(min_length=1, max_length=200)
    customer_email: str = Field(min_length=3, max_length=200)


class CreatePortalRequest(BaseModel):
    license_key: str | None = Field(default=None, max_length=128)
    session_id: str | None = Field(default=None, max_length=200)


class CustomerLicenseInfoRequest(BaseModel):
    license_key: str = Field(min_length=1, max_length=128)


class CustomerDeactivateDeviceRequest(BaseModel):
    license_key: str = Field(min_length=1, max_length=128)
    machine_id: str = Field(min_length=1, max_length=128)




@dataclass
class LicenseRecord:
    id: str
    license_key: str
    customer_name: str
    license_type: str
    expires_at: str
    max_devices: int
    is_active: int
    stripe_session_id: str | None = None
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    auto_renew: int = 1



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
                created_at TEXT NOT NULL,
                stripe_session_id TEXT,
                stripe_customer_id TEXT,
                stripe_subscription_id TEXT,
                auto_renew INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        # Migrate existing table if columns are missing
        cursor = conn.execute("PRAGMA table_info(licenses)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "stripe_session_id" not in columns:
            conn.execute("ALTER TABLE licenses ADD COLUMN stripe_session_id TEXT")
        if "stripe_customer_id" not in columns:
            conn.execute("ALTER TABLE licenses ADD COLUMN stripe_customer_id TEXT")
        if "stripe_subscription_id" not in columns:
            conn.execute("ALTER TABLE licenses ADD COLUMN stripe_subscription_id TEXT")
        if "auto_renew" not in columns:
            conn.execute("ALTER TABLE licenses ADD COLUMN auto_renew INTEGER NOT NULL DEFAULT 1")

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


def insert_license_record(
    customer_name: str,
    license_type: str,
    days_valid: int = 365,
    max_devices: int = 1,
    stripe_session_id: str | None = None,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
    auto_renew: int = 1,
) -> dict[str, Any]:
    now = utcnow()
    expires = now + timedelta(days=days_valid)

    record = {
        "id": str(uuid.uuid4()),
        "license_key": random_license_key(),
        "customer_name": customer_name,
        "license_type": license_type,
        "expires_at": isoformat_z(expires),
        "max_devices": max_devices,
        "is_active": 1,
        "created_at": isoformat_z(now),
        "stripe_session_id": stripe_session_id,
        "stripe_customer_id": stripe_customer_id,
        "stripe_subscription_id": stripe_subscription_id,
        "auto_renew": auto_renew,
    }

    conn = db()
    try:
        conn.execute(
            """
            INSERT INTO licenses (
                id, license_key, customer_name, license_type,
                expires_at, max_devices, is_active, created_at,
                stripe_session_id, stripe_customer_id, stripe_subscription_id, auto_renew
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                record["stripe_session_id"],
                record["stripe_customer_id"],
                record["stripe_subscription_id"],
                record["auto_renew"],
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return record


def get_license_by_key(license_key: str) -> LicenseRecord | None:
    conn = db()
    try:
        row = conn.execute(
            """
            SELECT id, license_key, customer_name, license_type, expires_at, max_devices, is_active, stripe_session_id, stripe_customer_id, stripe_subscription_id, auto_renew
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
        stripe_session_id=row["stripe_session_id"],
        stripe_customer_id=row["stripe_customer_id"],
        stripe_subscription_id=row["stripe_subscription_id"],
        auto_renew=int(row["auto_renew"]) if row["auto_renew"] is not None else 1,
    )


def get_license_by_stripe_session_id(session_id: str) -> LicenseRecord | None:
    conn = db()
    try:
        row = conn.execute(
            """
            SELECT id, license_key, customer_name, license_type, expires_at, max_devices, is_active, stripe_session_id, stripe_customer_id, stripe_subscription_id, auto_renew
            FROM licenses
            WHERE stripe_session_id = ?
            """,
            (session_id,),
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
        stripe_session_id=row["stripe_session_id"],
        stripe_customer_id=row["stripe_customer_id"],
        stripe_subscription_id=row["stripe_subscription_id"],
        auto_renew=int(row["auto_renew"]) if row["auto_renew"] is not None else 1,
    )


def get_license_by_stripe_subscription_id(subscription_id: str) -> LicenseRecord | None:
    conn = db()
    try:
        row = conn.execute(
            """
            SELECT id, license_key, customer_name, license_type, expires_at, max_devices, is_active, stripe_session_id, stripe_customer_id, stripe_subscription_id, auto_renew
            FROM licenses
            WHERE stripe_subscription_id = ?
            """,
            (subscription_id,),
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
        stripe_session_id=row["stripe_session_id"],
        stripe_customer_id=row["stripe_customer_id"],
        stripe_subscription_id=row["stripe_subscription_id"],
        auto_renew=int(row["auto_renew"]) if row["auto_renew"] is not None else 1,
    )


def extend_license_expiry(license_id: str, days_to_add: int = 365) -> str:
    conn = db()
    try:
        row = conn.execute("SELECT expires_at FROM licenses WHERE id = ?", (license_id,)).fetchone()
        if not row:
            return ""
        current_exp = parse_iso(row["expires_at"])
        base_time = max(utcnow(), current_exp)
        new_exp = base_time + timedelta(days=days_to_add)
        new_exp_iso = isoformat_z(new_exp)
        conn.execute("UPDATE licenses SET expires_at = ?, is_active = 1 WHERE id = ?", (new_exp_iso, license_id))
        conn.commit()
        return new_exp_iso
    finally:
        conn.close()


def update_auto_renew(license_id: str, auto_renew: int) -> None:
    conn = db()
    try:
        conn.execute("UPDATE licenses SET auto_renew = ? WHERE id = ?", (auto_renew, license_id))
        conn.commit()
    finally:
        conn.close()



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


@app.get("/request-license", response_class=HTMLResponse)
def request_license_ui() -> str:
    return """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Request a License &mdash; Pastastore Viewer</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 900px; margin: 60px auto; padding: 0 20px; background: #f5f5f5; }
  h1 { color: #1e3a5f; }
  h2 { color: #374151; font-size: 18px; margin-top: 28px; }
  p { color: #555; line-height: 1.6; }
  .card { background: white; border-radius: 8px; padding: 28px; box-shadow: 0 1px 3px rgba(0,0,0,.12); margin-bottom: 20px; }
  .pricing-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 20px 0; }
  .pricing-card { border: 1px solid #e5e7eb; border-radius: 6px; padding: 16px; background: #f9fafb; }
  .pricing-card h3 { margin: 0 0 8px; color: #1e3a5f; font-size: 16px; }
  .pricing-card .price { font-size: 14px; font-weight: 600; color: #2563eb; margin: 8px 0; }
  .pricing-card ul { margin: 8px 0; padding-left: 16px; font-size: 13px; color: #555; }
  .pricing-card ul li { margin: 4px 0; }
  label { display: block; font-size: 13px; font-weight: 600; color: #444; margin: 14px 0 4px; }
  input, select, textarea { width: 100%; padding: 8px 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 14px; box-sizing: border-box; }
  textarea { resize: vertical; min-height: 80px; }
  button { margin-top: 20px; width: 100%; padding: 10px; background: #2563eb; color: white; border: none; border-radius: 4px; font-size: 15px; cursor: pointer; }
  button:hover { background: #1d4ed8; }
  .error { margin-top: 10px; color: #b91c1c; font-size: 13px; display: none; }
  .note { font-size: 12px; color: #888; margin-top: 16px; }
</style>
</head>
<body>
<div class="card">
  <h1>Request a Pastastore Viewer License</h1>
  <p>Fill in the form below to request a Pro or ProNL license. You will be contacted within 1-2 business days.</p>
  
  <h2>Pricing <span style="font-size: 14px; font-weight: normal; color: #666;">(excl. VAT / BTW)</span></h2>
  <div class="pricing-grid">
    <div class="pricing-card">
      <h3>Pro</h3>
      <p style="font-size: 13px; margin: 0 0 12px; color: #666;">Model solving & editing</p>
      <div class="price">€349/year (1 device) <span style="font-size: 12px; font-weight: normal; color: #666;">excl. VAT</span></div>
      <div class="price">€699/year (3 devices) <span style="font-size: 12px; font-weight: normal; color: #666;">excl. VAT</span></div>
      <div class="price">€1,499/year (10 devices) <span style="font-size: 12px; font-weight: normal; color: #666;">excl. VAT</span></div>
      <ul>
        <li>Create & solve models</li>
        <li>Full editing capabilities</li>
        <li>Online activation</li>
      </ul>
    </div>
    <div class="pricing-card">
      <h3>ProNL</h3>
      <p style="font-size: 13px; margin: 0 0 12px; color: #666;">Pro + Dutch data imports</p>
      <div class="price">€499/year (1 device) <span style="font-size: 12px; font-weight: normal; color: #666;">excl. VAT</span></div>
      <div class="price">€999/year (3 devices) <span style="font-size: 12px; font-weight: normal; color: #666;">excl. VAT</span></div>
      <div class="price">€1,999/year (10 devices) <span style="font-size: 12px; font-weight: normal; color: #666;">excl. VAT</span></div>
      <ul>
        <li>All Pro features</li>
        <li>BRO data import</li>
        <li>KNMI data import</li>
      </ul>
    </div>
  </div>
  
  <p style="font-size: 13px; color: #666; margin-top: 16px;"><em>All prices listed above are excluding VAT / BTW.</em></p>
  <p style="font-size: 13px; color: #666;"><strong>Need more devices?</strong> Contact us for custom plans. <strong>Education/Non-profit?</strong> Discounts available upon request.</p>

  <h2>License Request Form</h2>
    <form id="license-form" action="https://formspree.io/f/mpqbjbnv" method="POST">

    <label for="name">Full name *</label>
    <input type="text" id="name" name="name" required placeholder="Your name" />

    <label for="org">Organisation *</label>
    <input type="text" id="org" name="organisation" required placeholder="Company or institution" />

    <label for="email">E-mail address *</label>
    <input type="email" id="email" name="email" required placeholder="your@email.com" />

    <label for="ltype">License type *</label>
    <select id="ltype" name="license_type" required>
      <option value="">-- Select --</option>
      <option value="Pro">Pro &mdash; model solving &amp; editing</option>
      <option value="ProNL">ProNL &mdash; Pro + BRO/KNMI data import (Netherlands)</option>
    </select>

    <label for="devices">Number of devices</label>
    <input type="number" id="devices" name="devices" min="1" max="50" value="1" />

    <label for="remarks">Remarks</label>
    <textarea id="remarks" name="remarks" placeholder="Any additional information..."></textarea>

    <input type="hidden" name="_subject" value="Pastastore Viewer License Request" />

        <button id="submit-btn" type="submit">Submit request</button>
        <div id="form-error" class="error"></div>
  </form>
  <p class="note">Your information is used solely for license administration.</p>
</div>
<script>
const form = document.getElementById('license-form');
const submitBtn = document.getElementById('submit-btn');
const errorEl = document.getElementById('form-error');
const emailInput = document.getElementById('email');


form.addEventListener('submit', async (event) => {
    event.preventDefault();
    errorEl.style.display = 'none';
    errorEl.textContent = '';

    const originalText = submitBtn.textContent;
    submitBtn.disabled = true;
    submitBtn.textContent = 'Sending...';

    try {
        const formData = new FormData(form);
        // Hint Formspree which address to use for reply/autoresponse.
        formData.append('_replyto', emailInput.value.trim());
        formData.append('_autoresponse', 'Thanks! We received your license request and will contact you within 1-2 business days.');

        const res = await fetch(form.action, {
            method: 'POST',
            body: formData,
            headers: { Accept: 'application/json' },
        });

        if (res.ok) {
            window.location.href = '/request-license/thank-you';
            return;
        }

        errorEl.textContent = 'Submission failed. Please try again or email r.calje@artesia-water.nl.';
        errorEl.style.display = 'block';
    } catch (err) {
        errorEl.textContent = 'Network error. Please try again or email r.calje@artesia-water.nl.';
        errorEl.style.display = 'block';
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = originalText;
    }
});
</script>
</body>
</html>
"""


@app.get("/request-license/thank-you", response_class=HTMLResponse)
def request_license_thanks() -> str:
    return """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Thank you &mdash; Pastastore Viewer</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 600px; margin: 60px auto; padding: 0 20px; background: #f5f5f5; text-align: center; }
  .card { background: white; border-radius: 8px; padding: 40px; box-shadow: 0 1px 3px rgba(0,0,0,.12); }
  h1 { color: #166534; }
  p { color: #555; line-height: 1.6; }
</style>
</head>
<body>
<div class="card">
  <h1>&#10003; Request received!</h1>
  <p>Thank you for your interest in Pastastore Viewer. Your request has been submitted successfully.</p>
  <p>You will be contacted within 1-2 business days with payment information and your license key.</p>
</div>
</body>
</html>
"""


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
      <td style="white-space:nowrap">
        <button class="expand" onclick="toggleDevices('${l.id}', this)">&#9654; Devices</button>
        <button class="expand" style="margin-left:4px" onclick="toggleExpiry('${l.id}')">&#9998; Expiry</button>
        <button class="${l.is_active ? 'danger' : 'expand'}" style="margin-left:4px" onclick="toggleActive('${l.id}')">${l.is_active ? 'Deactivate' : 'Activate'}</button>
        <button class="danger" style="margin-left:4px;background:#7c3aed" onclick="deleteLicense('${l.id}', '${l.customer_name}')">Delete</button>
      </td>
    </tr>
    <tr id="exp-row-${l.id}" style="display:none">
      <td colspan="7" style="background:#fffbeb;padding:10px 16px">
        New expiry date: <input type="date" id="exp-input-${l.id}" value="${l.expires_at.substring(0,10)}" style="width:160px;display:inline-block;margin:0 8px" />
        <button onclick="saveExpiry('${l.id}')">Save</button>
        <span id="exp-status-${l.id}" style="margin-left:8px;font-size:12px"></span>
      </td>
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

async function toggleActive(licId) {
  const res = await api('/admin/licenses/' + licId + '/toggle-active', { method: 'PATCH' });
  if (!res.ok) { alert('Failed: ' + res.status); return; }
  loadLicenses();
}

async function toggleExpiry(licId) {
  const row = document.getElementById('exp-row-' + licId);
  row.style.display = (row.style.display !== 'none') ? 'none' : '';
}

async function saveExpiry(licId) {
  const val = document.getElementById('exp-input-' + licId).value;
  const statusEl = document.getElementById('exp-status-' + licId);
  if (!val) { statusEl.textContent = 'Pick a date.'; return; }
  const res = await api('/admin/licenses/' + licId + '/expires', {
    method: 'PATCH',
    body: JSON.stringify({ expires_at: val }),
  });
  if (!res.ok) { statusEl.style.color = '#dc2626'; statusEl.textContent = 'Error ' + res.status; return; }
  statusEl.style.color = '#166534';
  statusEl.textContent = 'Saved!';
  setTimeout(() => { document.getElementById('exp-row-' + licId).style.display = 'none'; loadLicenses(); }, 800);
}

async function deleteLicense(licId, customerName) {
  if (!confirm('Permanently DELETE the license for "' + customerName + '"?\\nThis cannot be undone.')) return;
  const res = await api('/admin/licenses/' + licId, { method: 'DELETE' });
  if (!res.ok) { alert('Failed to delete: ' + res.status); return; }
  loadLicenses();
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

    record = insert_license_record(
        customer_name=req.customer_name,
        license_type=req.license_type,
        days_valid=req.days_valid,
        max_devices=req.max_devices,
    )

    return {
        "license_key": record["license_key"],
        "customer_name": record["customer_name"],
        "license_type": record["license_type"],
        "expires_at": record["expires_at"],
        "max_devices": record["max_devices"],
    }


def calculate_price_cents(license_type: str, max_devices: int) -> int:
    if license_type == "pro":
        if max_devices == 1:
            return 34900
        elif max_devices == 3:
            return 69900
        elif max_devices == 10:
            return 149900
        else:
            return 34900 * max_devices
    else:  # proNL
        if max_devices == 1:
            return 49900
        elif max_devices == 3:
            return 99900
        elif max_devices == 10:
            return 199900
        else:
            return 49900 * max_devices


@app.post("/create-checkout-session")
def create_checkout_session(req: CreateCheckoutRequest, request: Request) -> dict[str, Any]:
    raise HTTPException(
        status_code=503,
        detail="Online payment is currently disabled. Please use the license request form on /request-license."
    )

    stripe.api_key = STRIPE_SECRET_KEY
    price_cents = calculate_price_cents(req.license_type, req.max_devices)

    success_url = (
        STRIPE_SUCCESS_URL
        or f"{base_url}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}"
    )
    cancel_url = STRIPE_CANCEL_URL or f"{base_url}/request-license"

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card", "ideal", "bancontact", "wero"],
            line_items=[
                {
                    "price_data": {
                        "currency": "eur",
                        "product_data": {
                            "name": f"Pastastore Viewer {req.license_type.upper()} ({req.max_devices} device{'s' if req.max_devices > 1 else ''})",
                            "description": f"Annual Recurring License ({req.max_devices} device limit)",
                        },
                        "unit_amount": price_cents,
                        "recurring": {"interval": "year"},
                    },
                    "quantity": 1,
                }
            ],
            mode="subscription",
            automatic_tax={"enabled": True},
            customer_email=req.customer_email,
            metadata={
                "customer_name": req.customer_name,
                "license_type": req.license_type,
                "max_devices": str(req.max_devices),
                "days_valid": "365",
            },
            success_url=success_url,
            cancel_url=cancel_url,
        )
        return {"checkout_url": session.url, "session_id": session.id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/webhook/stripe")
async def stripe_webhook(request: Request) -> dict[str, Any]:
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if STRIPE_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        except (ValueError, stripe.error.SignatureVerificationError) as e:
            raise HTTPException(status_code=400, detail=f"Webhook signature error: {str(e)}")
    else:
        try:
            event = json.loads(payload.decode("utf-8"))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

    event_type = event.get("type") if isinstance(event, dict) else event.type
    event_data = event.get("data", {}).get("object", {}) if isinstance(event, dict) else event.data.object

    if event_type == "checkout.session.completed":
        session_id = event_data.get("id")
        customer_id = event_data.get("customer")
        subscription_id = event_data.get("subscription")
        metadata = event_data.get("metadata", {})
        customer_details = event_data.get("customer_details", {})

        customer_name = (
            metadata.get("customer_name")
            or (customer_details.get("name") if isinstance(customer_details, dict) else getattr(customer_details, "name", None))
            or "Valued Customer"
        )
        license_type = metadata.get("license_type", "pro")
        max_devices = int(metadata.get("max_devices", "1"))
        days_valid = int(metadata.get("days_valid", "365"))

        if session_id:
            existing = get_license_by_stripe_session_id(session_id)
            if not existing:
                insert_license_record(
                    customer_name=customer_name,
                    license_type=license_type,
                    days_valid=days_valid,
                    max_devices=max_devices,
                    stripe_session_id=session_id,
                    stripe_customer_id=customer_id if isinstance(customer_id, str) else None,
                    stripe_subscription_id=subscription_id if isinstance(subscription_id, str) else None,
                    auto_renew=1,
                )

    elif event_type == "invoice.payment_succeeded":
        billing_reason = event_data.get("billing_reason")
        subscription_id = event_data.get("subscription")
        if billing_reason == "subscription_cycle" and subscription_id:
            lic = get_license_by_stripe_subscription_id(subscription_id)
            if lic:
                extend_license_expiry(lic.id, days_to_add=365)

    elif event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        sub_id = event_data.get("id")
        status = event_data.get("status")
        cancel_at_period_end = event_data.get("cancel_at_period_end", False)

        if sub_id:
            lic = get_license_by_stripe_subscription_id(sub_id)
            if lic:
                auto_renew = 0 if (cancel_at_period_end or status == "canceled") else 1
                update_auto_renew(lic.id, auto_renew)

    return {"status": "success"}


@app.post("/create-portal-session")
def create_portal_session(req: CreatePortalRequest, request: Request) -> dict[str, Any]:
    base_url = str(request.base_url).rstrip("/")

    if not STRIPE_SECRET_KEY:
        # Demo mode notice when Stripe key is not configured yet
        return {
            "demo": True,
            "portal_url": None,
            "message": (
                "In production with a live Stripe account (STRIPE_SECRET_KEY configured), "
                "clicking this button securely redirects the customer to their hosted Stripe Customer Portal (https://billing.stripe.com).\n\n"
                "There customers can:\n"
                "- Cancel or resume automatic annual renewal\n"
                "- Update credit card / iDEAL / SEPA payment details\n"
                "- View and download past PDF invoices"
            ),
        }



    customer_id = None

    if req.license_key:
        lic = get_license_by_key(req.license_key)
        if lic:
            customer_id = lic.stripe_customer_id
    elif req.session_id:
        lic = get_license_by_stripe_session_id(req.session_id)
        if lic:
            customer_id = lic.stripe_customer_id

    if not customer_id:
        raise HTTPException(
            status_code=404,
            detail="No active Stripe subscription found for the provided key or session ID.",
        )

    stripe.api_key = STRIPE_SECRET_KEY
    return_url = f"{base_url}/checkout/success"
    if req.session_id:
        return_url += f"?session_id={req.session_id}"

    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
        return {"portal_url": portal_session.url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))



@app.post("/customer/license-info")
def customer_license_info(req: CustomerLicenseInfoRequest) -> dict[str, Any]:
    lic = get_license_by_key(req.license_key)
    if not lic:
        raise HTTPException(status_code=404, detail="License key not found.")

    conn = db()
    try:
        rows = conn.execute(
            """
            SELECT machine_id, device_name, plugin_version, activated_at, last_seen_at
            FROM activations
            WHERE license_id = ?
            ORDER BY last_seen_at DESC
            """,
            (lic.id,),
        ).fetchall()
    finally:
        conn.close()

    activations = [dict(row) for row in rows]

    return {
        "customer_name": lic.customer_name,
        "license_type": lic.license_type,
        "max_devices": lic.max_devices,
        "active_devices_count": len(activations),
        "expires_at": lic.expires_at,
        "is_active": bool(lic.is_active),
        "auto_renew": bool(lic.auto_renew),
        "has_stripe_subscription": bool(lic.stripe_subscription_id or lic.stripe_customer_id),
        "activations": activations,
    }


@app.post("/customer/deactivate-device")
def customer_deactivate_device(req: CustomerDeactivateDeviceRequest) -> dict[str, Any]:
    lic = get_license_by_key(req.license_key)
    if not lic:
        raise HTTPException(status_code=404, detail="License key not found.")

    removed = deactivate_activation(lic.id, req.machine_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Device activation not found.")

    return {"deactivated": True, "machine_id": req.machine_id}


@app.post("/customer/toggle-auto-renew-demo")
def customer_toggle_auto_renew_demo(req: CustomerLicenseInfoRequest) -> dict[str, Any]:
    lic = get_license_by_key(req.license_key)
    if not lic:
        raise HTTPException(status_code=404, detail="License key not found.")
    new_state = 0 if lic.auto_renew else 1
    update_auto_renew(lic.id, new_state)
    return {"auto_renew": new_state}



@app.get("/manage-subscription", response_class=HTMLResponse)
def manage_subscription_ui() -> str:
    return """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Customer License &amp; Device Portal &mdash; Pastastore Viewer</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 800px; margin: 50px auto; padding: 0 20px; background: #f5f5f5; }
  h1 { color: #1e3a5f; text-align: center; margin-top: 0; }
  .card { background: white; border-radius: 8px; padding: 28px; box-shadow: 0 1px 3px rgba(0,0,0,.12); margin-bottom: 24px; }
  label { display: block; font-size: 13px; font-weight: 600; color: #444; margin: 16px 0 4px; }
  input { width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 14px; box-sizing: border-box; font-family: monospace; }
  button { margin-top: 14px; padding: 10px 16px; background: #2563eb; color: white; border: none; border-radius: 4px; font-size: 14px; font-weight: 600; cursor: pointer; }
  button:hover { background: #1d4ed8; }
  button.danger { background: #dc2626; padding: 4px 10px; font-size: 12px; }
  button.danger:hover { background: #b91c1c; }
  .error { margin-top: 12px; color: #b91c1c; font-size: 13px; display: none; }
  .info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 16px 0; background: #f9fafb; padding: 16px; border-radius: 6px; border: 1px solid #e5e7eb; font-size: 14px; }
  .info-item span { color: #6b7280; font-size: 12px; display: block; font-weight: 500; }
  .info-item strong { color: #1f2937; }
  table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }
  th { text-align: left; background: #f3f4f6; padding: 8px 12px; border-bottom: 2px solid #e5e7eb; }
  td { padding: 8px 12px; border-bottom: 1px solid #e5e7eb; vertical-align: middle; }
  .mono { font-family: monospace; font-size: 12px; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold; }
  .badge-active { background: #dcfce7; color: #166534; }
  .note { font-size: 12px; color: #666; margin-top: 16px; }
</style>
</head>
<body>
<h1>Customer License Portal</h1>

<div class="card">
  <h2 style="margin-top:0; font-size:18px;">Enter Your License Key</h2>
  <form id="lookup-form">
    <label for="key">License Key</label>
    <input type="text" id="key" required placeholder="XXXX-XXXX-XXXX-XXXX" />
    <button type="submit" id="lookup-btn">View License &amp; Active Computers</button>
    <div id="lookup-err" class="error"></div>
  </form>
</div>

<div id="portal-details" style="display:none;">
  <div class="card">
    <h2 style="margin-top:0; font-size:18px;">License Summary</h2>
    <div class="info-grid">
      <div class="info-item"><span>Customer</span><strong id="d-customer">-</strong></div>
      <div class="info-item"><span>License Type</span><strong id="d-type">-</strong></div>
      <div class="info-item"><span>Devices Used</span><strong id="d-devices">-</strong></div>
      <div class="info-item"><span>Expiration Date</span><strong id="d-expires">-</strong></div>
      <div class="info-item"><span>Renewal Status</span><strong id="d-renewal">-</strong></div>
    </div>
    <button id="stripe-portal-btn" style="background:#4b5563;" onclick="openStripePortal()">&#9889; Manage / Cancel Billing in Stripe Portal</button>
  </div>

  <div class="card">
    <h2 style="margin-top:0; font-size:18px;">Activated Computers</h2>
    <p class="note">Below are the computers currently activated under this license. Click <strong>Deactivate</strong> to free up a slot for another computer.</p>
    <div id="devices-list"></div>
  </div>
</div>

<script>
let currentKey = '';

document.getElementById('lookup-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const key = document.getElementById('key').value.trim();
  if (!key) return;
  currentKey = key;
  await loadLicenseInfo();
});

async function loadLicenseInfo() {
  const err = document.getElementById('lookup-err');
  const btn = document.getElementById('lookup-btn');
  err.style.display = 'none';
  btn.disabled = true;
  btn.textContent = 'Loading...';

  try {
    const res = await fetch('/customer/license-info', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ license_key: currentKey })
    });
    const data = await res.json();
    if (!res.ok) {
      let msg = 'License key not found.';
      if (typeof data.detail === 'string') {
        msg = data.detail;
      } else if (Array.isArray(data.detail) && data.detail.length > 0) {
        msg = data.detail.map(d => d.msg).join(', ');
      }
      err.textContent = msg;
      err.style.display = 'block';
      document.getElementById('portal-details').style.display = 'none';
      return;
    }


    document.getElementById('d-customer').textContent = data.customer_name;
    document.getElementById('d-type').textContent = data.license_type.toUpperCase();
    document.getElementById('d-devices').textContent = data.active_devices_count + ' / ' + data.max_devices + ' devices';
    document.getElementById('d-expires').textContent = new Date(data.expires_at).toLocaleDateString();
    document.getElementById('d-renewal').textContent = data.auto_renew ? 'Automatic Renewal Active' : 'Automatic Renewal Cancelled';

    renderDevices(data.activations);
    document.getElementById('portal-details').style.display = 'block';
  } catch (ex) {
    err.textContent = 'Network error. Please try again.';
    err.style.display = 'block';
  } finally {
    btn.disabled = false;
    btn.textContent = 'View License & Active Computers';
  }
}

function renderDevices(activations) {
  const el = document.getElementById('devices-list');
  if (!activations || !activations.length) {
    el.innerHTML = '<p style="color:#888; font-style:italic;">No computers are currently activated under this license.</p>';
    return;
  }

  let html = `<table><thead><tr>
    <th>Computer Name</th>
    <th>Plugin Version</th>
    <th>Activated Date</th>
    <th>Last Active</th>
    <th>Action</th>
  </tr></thead><tbody>`;

  activations.forEach(a => {
    const actDate = new Date(a.activated_at).toLocaleDateString();
    const lastDate = new Date(a.last_seen_at).toLocaleDateString();
    html += `<tr>
      <td><strong>${a.device_name}</strong><br><span class="mono" style="color:#888;font-size:10px">${a.machine_id.substring(0, 16)}...</span></td>
      <td>v${a.plugin_version}</td>
      <td>${actDate}</td>
      <td>${lastDate}</td>
      <td><button class="danger" onclick="deactivateDevice('${a.machine_id}', '${a.device_name}')">Deactivate</button></td>
    </tr>`;
  });

  html += '</tbody></table>';
  el.innerHTML = html;
}

async function deactivateDevice(machineId, deviceName) {
  if (!confirm('Deactivate license on computer "' + deviceName + '"?\\nThis machine will revert to free mode until re-activated.')) return;
  try {
    const res = await fetch('/customer/deactivate-device', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ license_key: currentKey, machine_id: machineId })
    });
    if (res.ok) {
      alert('Computer deactivated successfully! The device slot is now available.');
      await loadLicenseInfo();
    } else {
      const data = await res.json();
      alert('Failed: ' + (data.detail || 'Could not deactivate device'));
    }
  } catch (err) {
    alert('Network error while deactivating device.');
  }
}

async function openStripePortal() {
  try {
    const res = await fetch('/create-portal-session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ license_key: currentKey })
    });
    const data = await res.json();
    if (data.demo) {
      if (confirm("[DEMO MODE NOTICE]\\n\\n" + data.message + "\\n\\nWould you like to simulate toggling automatic renewal in Demo Mode now?")) {
        await toggleAutoRenewDemo();
      }
    } else if (res.ok && data.portal_url) {

      window.location.href = data.portal_url;
    } else {
      alert(data.detail || 'Stripe portal not available.');
    }
  } catch (err) {
    alert('Network error accessing Stripe portal.');
  }
}

async function toggleAutoRenewDemo() {
  try {
    const res = await fetch('/customer/toggle-auto-renew-demo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ license_key: currentKey })
    });
    if (res.ok) {
      alert('Demo auto-renew state toggled successfully!');
      await loadLicenseInfo();
    }
  } catch (err) {
    alert('Error toggling demo auto-renew state.');
  }
}

window.addEventListener('DOMContentLoaded', async () => {
  const params = new URLSearchParams(window.location.search);
  const k = params.get('key');
  if (k) {
    document.getElementById('key').value = k;
    currentKey = k;
    await loadLicenseInfo();
  }
});


</script>
</body>
</html>
"""




@app.get("/checkout/success", response_class=HTMLResponse)
def checkout_success(session_id: str | None = None) -> str:
    license_key = ""
    customer_name = "Valued Customer"
    license_type = "pro"
    max_devices = 1
    expires_at = "N/A"
    invoice_url = None

    if session_id:
        existing = get_license_by_stripe_session_id(session_id)
        if not existing and STRIPE_SECRET_KEY:
            try:
                stripe.api_key = STRIPE_SECRET_KEY
                sess = stripe.checkout.Session.retrieve(session_id)
                if sess and getattr(sess, "payment_status", "") == "paid":
                    metadata = getattr(sess, "metadata", {}) or {}
                    customer_details = getattr(sess, "customer_details", {}) or {}
                    cname = (
                        metadata.get("customer_name")
                        or (customer_details.get("name") if isinstance(customer_details, dict) else getattr(customer_details, "name", None))
                        or "Valued Customer"
                    )
                    ltype = metadata.get("license_type", "pro")
                    mdev = int(metadata.get("max_devices", "1"))
                    dvalid = int(metadata.get("days_valid", "365"))
                    created = insert_license_record(
                        customer_name=cname,
                        license_type=ltype,
                        days_valid=dvalid,
                        max_devices=mdev,
                        stripe_session_id=session_id,
                        stripe_customer_id=getattr(sess, "customer", None),
                    )
                    license_key = created["license_key"]
                    customer_name = created["customer_name"]
                    license_type = created["license_type"]
                    max_devices = created["max_devices"]
                    expires_at = created["expires_at"]
            except Exception:
                pass
        elif existing:
            license_key = existing.license_key
            customer_name = existing.customer_name
            license_type = existing.license_type
            max_devices = existing.max_devices
            expires_at = existing.expires_at

        if STRIPE_SECRET_KEY:
            try:
                stripe.api_key = STRIPE_SECRET_KEY
                sess = stripe.checkout.Session.retrieve(session_id, expand=["invoice"])
                if sess and getattr(sess, "invoice", None):
                    invoice_obj = sess.invoice
                    if isinstance(invoice_obj, dict):
                        invoice_url = invoice_obj.get("hosted_invoice_url") or invoice_obj.get("invoice_pdf")
                    else:
                        invoice_url = getattr(invoice_obj, "hosted_invoice_url", None) or getattr(invoice_obj, "invoice_pdf", None)
            except Exception:
                pass

    invoice_button_html = ""
    if invoice_url:
        invoice_button_html = f'<a href="{invoice_url}" target="_blank" class="btn btn-secondary">&#128196; Download PDF Invoice</a>'

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Payment Successful &mdash; Pastastore Viewer</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 650px; margin: 60px auto; padding: 0 20px; background: #f5f5f5; text-align: center; }}
  .card {{ background: white; border-radius: 8px; padding: 36px; box-shadow: 0 1px 3px rgba(0,0,0,.12); }}
  .icon {{ font-size: 48px; color: #166534; margin-bottom: 12px; }}
  h1 {{ color: #166534; margin-top: 0; }}
  p {{ color: #555; line-height: 1.6; }}
  .key-box {{ background: #f0fdf4; border: 2px dashed #166534; border-radius: 8px; padding: 16px; margin: 24px 0; font-family: monospace; font-size: 22px; font-weight: bold; color: #14532d; letter-spacing: 1px; word-break: break-all; position: relative; }}
  .btn {{ display: inline-block; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; cursor: pointer; margin: 6px; border: none; }}
  .btn-primary {{ background: #2563eb; color: white; }}
  .btn-primary:hover {{ background: #1d4ed8; }}
  .btn-secondary {{ background: #4b5563; color: white; }}
  .btn-secondary:hover {{ background: #374151; }}
  .details {{ text-align: left; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; padding: 16px; margin: 20px 0; font-size: 14px; }}
  .details-row {{ display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #f3f4f6; }}
  .details-row:last-child {{ border-bottom: none; }}
  .label {{ color: #6b7280; font-weight: 500; }}
  .val {{ font-weight: 600; color: #1f2937; }}
  .steps {{ text-align: left; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px; padding: 16px; font-size: 13px; color: #1e40af; margin-top: 24px; }}
  .steps ol {{ margin: 8px 0 0; padding-left: 20px; }}
  .steps li {{ margin: 4px 0; }}
</style>
</head>
<body>
<div class="card">
  <div class="icon">&#10004;</div>
  <h1>Payment Successful!</h1>
  <p>Thank you for purchasing Pastastore Viewer. Your license key has been generated and activated.</p>
  
  <div class="key-box">
    <span id="key-text">{license_key or 'Key Pending'}</span>
  </div>
  <button class="btn btn-primary" onclick="copyKey()">&#128203; Copy License Key</button>
  {invoice_button_html}
  <button class="btn btn-secondary" onclick="openPortal()">&#9889; Manage / Cancel Automatic Renewal</button>

  <div class="details">
    <div class="details-row"><span class="label">Customer Name:</span> <span class="val">{customer_name}</span></div>
    <div class="details-row"><span class="label">License Type:</span> <span class="val">{license_type.upper()}</span></div>
    <div class="details-row"><span class="label">Max Devices:</span> <span class="val">{max_devices}</span></div>
    <div class="details-row"><span class="label">Expiration Date:</span> <span class="val">{expires_at[:10] if len(expires_at) >= 10 else expires_at}</span></div>
    <div class="details-row"><span class="label">Annual Automatic Renewal:</span> <span class="val" style="color: #166534;">Active (Can be cancelled anytime)</span></div>
  </div>

  <div class="steps">
    <strong>How to activate in QGIS:</strong>
    <ol>
      <li>Open QGIS with the <strong>Pastastore Viewer</strong> plugin installed.</li>
      <li>Click the <strong>Pastastore Viewer</strong> toolbar button.</li>
      <li>Open <strong>Settings</strong> &rarr; <strong>License Manager</strong>.</li>
      <li>Paste your key above and click <strong>Validate License Online</strong>.</li>
    </ol>
  </div>
</div>
<script>
function copyKey() {{
  const key = document.getElementById('key-text').innerText;
  navigator.clipboard.writeText(key).then(() => {{
    alert('License key copied to clipboard!');
  }}).catch(() => {{
    const el = document.createElement('textarea');
    el.value = key;
    document.body.appendChild(el);
    el.select();
    document.execCommand('copy');
    document.body.removeChild(el);
    alert('License key copied!');
  }});
}}

async function openPortal() {{
  const sessId = new URLSearchParams(window.location.search).get('session_id');
  const keyEl = document.getElementById('key-text');
  const key = keyEl ? keyEl.innerText : '';
  try {{
    const res = await fetch('/create-portal-session', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ session_id: sessId, license_key: key }})
    }});
    const data = await res.json();
    if (data.demo) {{
      alert("[DEMO MODE NOTICE]\\n\\n" + data.message);
      if (key && key !== 'Key Pending') {{
        window.location.href = '/manage-subscription?key=' + encodeURIComponent(key);
      }}
    }} else if (res.ok && data.portal_url) {{

      window.location.href = data.portal_url;
    }} else {{
      alert(data.detail || 'Could not open subscription management portal.');
    }}
  }} catch (err) {{
    alert('Error opening subscription management portal.');
  }}
}}


</script>
</body>
</html>
"""




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


@app.patch("/admin/licenses/{license_id}/toggle-active")
def admin_toggle_active(
    license_id: str,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Toggle the is_active flag of a license."""
    ensure_admin_token(x_admin_token)

    conn = db()
    try:
        row = conn.execute(
            "SELECT is_active FROM licenses WHERE id = ?", (license_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="License not found.")
        new_state = 0 if row["is_active"] else 1
        conn.execute(
            "UPDATE licenses SET is_active = ? WHERE id = ?", (new_state, license_id)
        )
        conn.commit()
        return {"is_active": bool(new_state)}
    finally:
        conn.close()


@app.patch("/admin/licenses/{license_id}/expires")
def admin_update_expires(
    license_id: str,
    payload: dict[str, Any],
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Update the expiry date of a license. Body: {"expires_at": "YYYY-MM-DD"}"""
    ensure_admin_token(x_admin_token)

    new_date = payload.get("expires_at", "").strip()
    try:
        parsed = datetime.strptime(new_date, "%Y-%m-%d")  # noqa: DTZ007
        expires_iso = parsed.strftime("%Y-%m-%dT00:00:00Z")
    except ValueError:
        raise HTTPException(status_code=422, detail="expires_at must be YYYY-MM-DD")

    conn = db()
    try:
        cur = conn.execute(
            "UPDATE licenses SET expires_at = ? WHERE id = ?",
            (expires_iso, license_id),
        )
        conn.commit()
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="License not found.")
        return {"expires_at": expires_iso}
    finally:
        conn.close()


@app.delete("/admin/licenses/{license_id}")
def admin_delete_license(
    license_id: str,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Permanently delete a license and all its activations."""
    ensure_admin_token(x_admin_token)

    conn = db()
    try:
        conn.execute("DELETE FROM activations WHERE license_id = ?", (license_id,))
        cur = conn.execute("DELETE FROM licenses WHERE id = ?", (license_id,))
        conn.commit()
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="License not found.")
        return {"deleted": True}
    finally:
        conn.close()
