from __future__ import annotations

import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
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

    upsert_activation(lic.id, req.machine_id, "unknown-device", "unknown")
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
