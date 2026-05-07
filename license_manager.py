from __future__ import annotations

import getpass
import hashlib
import json
import platform
import socket
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FEATURE_PRO = "pro"
FEATURE_PRONL = "pronl"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _normalize_base_url(base_url: str) -> str:
    return base_url.strip().rstrip("/")


def _post_json(url: str, body: dict[str, Any], timeout: int = 10) -> dict[str, Any]:
    request = urllib.request.Request(
        url=url,
        method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read().decode("utf-8")
    return json.loads(data)


def _machine_id() -> str:
    raw = "|".join(
        [
            socket.gethostname(),
            str(uuid.getnode()),
            platform.system(),
            platform.machine(),
            getpass.getuser(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class LicenseState:
    valid: bool = False
    reason: str = "No license"
    license_type: str = "free"
    features: tuple[str, ...] = ()
    expires_at: str | None = None
    customer_name: str | None = None
    license_key: str | None = None


class LicenseManager:
    """Strict online license manager.

    Paid features are enabled only after successful online validation
    against the license server in the current QGIS session.
    """

    def __init__(self, plugin_dir: str, plugin_version: str):
        self.plugin_dir = Path(plugin_dir)
        self.plugin_version = plugin_version
        self.license_dir = self.plugin_dir / "license"
        self.license_dir.mkdir(parents=True, exist_ok=True)
        self.license_file = self.license_dir / "license_online.json"
        self.state = LicenseState()
        self._session_validated = False
        self._refresh_state()

    def refresh_state(self) -> None:
        self._refresh_state()

    @property
    def machine_id(self) -> str:
        return _machine_id()

    def has_feature(self, feature: str) -> bool:
        if not self.state.valid or not self._session_validated:
            return False

        features = set(self.state.features)
        if feature == FEATURE_PRO:
            return FEATURE_PRO in features or FEATURE_PRONL in features
        if feature == FEATURE_PRONL:
            return FEATURE_PRONL in features
        return feature in features

    def status_text(self) -> str:
        if not self.state.valid:
            return f"Free ({self.state.reason})"

        expiry = self.state.expires_at or "unknown"
        customer = self.state.customer_name or "unknown"
        return f"{self.state.license_type} - {customer} - expires {expiry}"

    def activate(self, license_key: str, server_url: str) -> tuple[bool, str]:
        key = (license_key or "").strip()
        base_url = _normalize_base_url(server_url or "")
        if not key:
            return False, "License key is missing."
        if not base_url:
            return False, "Server URL is missing."

        try:
            response = _post_json(
                f"{base_url}/activate",
                {
                    "license_key": key,
                    "machine_id": self.machine_id,
                    "device_name": socket.gethostname(),
                    "plugin_version": self.plugin_version,
                },
            )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            self.state = LicenseState(valid=False, reason=f"Activation failed: HTTP {exc.code}")
            self._session_validated = False
            return False, f"Activation failed ({exc.code}): {body or exc.reason}"
        except Exception as exc:
            self.state = LicenseState(valid=False, reason=f"Activation failed: {exc}")
            self._session_validated = False
            return False, f"Activation failed: {exc}"

        data = self._extract_entitlement(response)
        if not self._apply_online_entitlement(data):
            self._session_validated = False
            return False, f"Invalid license: {self.state.reason}"

        self._write_store({"license_key": key, "server_url": base_url})
        self._session_validated = True
        return True, "License activated (online)."

    def validate_online(self, force: bool = True) -> tuple[bool, str]:
        del force
        stored = self._read_store()
        if not stored:
            self._session_validated = False
            self.state = LicenseState(valid=False, reason="No local license settings")
            return False, "No local license settings found."

        license_key = stored.get("license_key")
        server_url = stored.get("server_url")
        if not license_key or not server_url:
            self._session_validated = False
            self.state = LicenseState(valid=False, reason="Missing license settings")
            return False, "Local license settings are incomplete."

        try:
            response = _post_json(
                f"{_normalize_base_url(server_url)}/validate",
                {
                    "license_key": license_key,
                    "machine_id": self.machine_id,
                },
            )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            self._session_validated = False
            self.state = LicenseState(valid=False, reason=f"Online validation failed: HTTP {exc.code}")
            return False, f"Validation failed ({exc.code}): {body or exc.reason}"
        except Exception as exc:
            self._session_validated = False
            self.state = LicenseState(valid=False, reason=f"Online validation failed: {exc}")
            return False, f"Validation failed: {exc}"

        data = self._extract_entitlement(response)
        if not self._apply_online_entitlement(data):
            self._session_validated = False
            return False, f"Invalid license: {self.state.reason}"

        self._session_validated = True
        return True, "Online validation completed."

    def deactivate(self) -> tuple[bool, str]:
        stored = self._read_store()
        if not stored:
            return False, "No local license found."

        license_key = stored.get("license_key")
        server_url = stored.get("server_url")

        if license_key and server_url:
            try:
                _post_json(
                    f"{_normalize_base_url(server_url)}/deactivate",
                    {
                        "license_key": license_key,
                        "machine_id": self.machine_id,
                    },
                )
            except Exception:
                pass

        if self.license_file.exists():
            self.license_file.unlink()

        self._session_validated = False
        self.state = LicenseState(valid=False, reason="No license")
        return True, "License deactivated and removed locally."

    def _extract_entitlement(self, response: dict[str, Any]) -> dict[str, Any]:
        payload = response.get("payload")
        if isinstance(payload, dict):
            return payload
        return response

    def _apply_online_entitlement(self, data: dict[str, Any]) -> bool:
        try:
            license_type = str(data.get("license_type") or "free")
            features = tuple(data.get("features") or [])
            expires_at = data.get("expires_at")
            customer_name = data.get("customer_name")
            license_key = data.get("license_key")
            machine_id = data.get("machine_id")

            if machine_id and machine_id != self.machine_id:
                self.state = LicenseState(valid=False, reason="License bound to another machine")
                return False

            if expires_at:
                expires = _parse_iso(expires_at)
                if expires < _utcnow():
                    self.state = LicenseState(valid=False, reason="License expired")
                    return False

            if not features and license_type == "proNL":
                features = (FEATURE_PRO, FEATURE_PRONL)
            elif not features and license_type == "pro":
                features = (FEATURE_PRO,)

            self.state = LicenseState(
                valid=True,
                reason="OK",
                license_type=license_type,
                features=features,
                expires_at=expires_at,
                customer_name=customer_name,
                license_key=license_key,
            )
            return True
        except Exception as exc:
            self.state = LicenseState(valid=False, reason=f"Invalid entitlement: {exc}")
            return False

    def _refresh_state(self) -> None:
        stored = self._read_store()
        if not stored:
            self.state = LicenseState(valid=False, reason="No local license settings")
            self._session_validated = False
            return

        self.state = LicenseState(
            valid=False,
            reason="Online validation required",
            license_key=stored.get("license_key"),
        )
        self._session_validated = False

    def _read_store(self) -> dict[str, Any] | None:
        if not self.license_file.exists():
            return None
        try:
            data = json.loads(self.license_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            return None
        return None

    def _write_store(self, data: dict[str, Any]) -> None:
        self.license_file.write_text(
            json.dumps(data, indent=2, sort_keys=True),
            encoding="utf-8",
        )
