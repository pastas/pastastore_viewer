# -*- coding: utf-8 -*-
"""Unit tests for Stripe payment integration and license server endpoints."""

import json
import os
import sys
import unittest.mock as mock
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Add license_server directory to sys.path
SERVER_DIR = Path(__file__).resolve().parent.parent / "license_server"
sys.path.insert(0, str(SERVER_DIR))

import app as license_app  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Fixture for FastAPI TestClient with temporary database."""
    db_path = tmp_path / "test_license_server.db"
    monkeypatch.setattr(license_app, "DB_PATH", db_path)
    license_app.init_db()
    with TestClient(license_app.app) as test_client:
        yield test_client


def test_init_db_adds_stripe_columns(tmp_path, monkeypatch):
    """Test that init_db creates table with stripe_session_id, stripe_customer_id, stripe_subscription_id, and auto_renew columns."""
    db_path = tmp_path / "test_schema.db"
    monkeypatch.setattr(license_app, "DB_PATH", db_path)
    license_app.init_db()

    conn = license_app.db()
    cursor = conn.execute("PRAGMA table_info(licenses)")
    columns = [row["name"] for row in cursor.fetchall()]
    conn.close()

    assert "stripe_session_id" in columns
    assert "stripe_customer_id" in columns
    assert "stripe_subscription_id" in columns
    assert "auto_renew" in columns


def test_calculate_price_cents():
    """Test price calculations for different license tiers and device counts."""
    assert license_app.calculate_price_cents("pro", 1) == 34900
    assert license_app.calculate_price_cents("pro", 3) == 69900
    assert license_app.calculate_price_cents("pro", 10) == 149900
    assert license_app.calculate_price_cents("proNL", 1) == 49900
    assert license_app.calculate_price_cents("proNL", 3) == 99900
    assert license_app.calculate_price_cents("proNL", 10) == 199900


def test_insert_and_get_by_stripe_session_id(client):
    """Test database helper insert_license_record and get_license_by_stripe_session_id."""
    record = license_app.insert_license_record(
        customer_name="Test Waterboard",
        license_type="proNL",
        days_valid=365,
        max_devices=3,
        stripe_session_id="cs_test_12345",
        stripe_customer_id="cus_test_67890",
        stripe_subscription_id="sub_test_111",
        auto_renew=1,
    )

    assert record["customer_name"] == "Test Waterboard"
    assert record["license_type"] == "proNL"
    assert record["stripe_session_id"] == "cs_test_12345"

    found = license_app.get_license_by_stripe_session_id("cs_test_12345")
    assert found is not None
    assert found.customer_name == "Test Waterboard"
    assert found.license_type == "proNL"
    assert found.max_devices == 3
    assert found.stripe_customer_id == "cus_test_67890"
    assert found.stripe_subscription_id == "sub_test_111"
    assert found.auto_renew == 1


def test_create_checkout_session_without_key(client, monkeypatch):
    """Test that /create-checkout-session returns demo success redirect if STRIPE_SECRET_KEY is missing."""
    monkeypatch.setattr(license_app, "STRIPE_SECRET_KEY", "")
    response = client.post(
        "/create-checkout-session",
        json={
            "license_type": "proNL",
            "max_devices": 1,
            "customer_name": "Test User",
            "customer_email": "test@example.com",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "/checkout/success?session_id=demo_session_" in data["checkout_url"]



def test_create_checkout_session_success(client, monkeypatch):
    """Test /create-checkout-session with mocked Stripe API in subscription mode."""
    monkeypatch.setattr(license_app, "STRIPE_SECRET_KEY", "sk_test_mock_123")

    mock_session = mock.MagicMock()
    mock_session.url = "https://checkout.stripe.com/pay/cs_test_abc123"
    mock_session.id = "cs_test_abc123"

    with mock.patch("stripe.checkout.Session.create", return_value=mock_session) as mock_create:
        response = client.post(
            "/create-checkout-session",
            json={
                "license_type": "proNL",
                "max_devices": 3,
                "customer_name": "Waternet B.V.",
                "customer_email": "info@waternet.nl",
            },
        )
        kwargs = mock_create.call_args.kwargs
        assert kwargs["mode"] == "subscription"

    assert response.status_code == 200
    data = response.json()
    assert data["checkout_url"] == "https://checkout.stripe.com/pay/cs_test_abc123"
    assert data["session_id"] == "cs_test_abc123"


def test_stripe_webhook_completed_event(client, monkeypatch):
    """Test that Stripe webhook automatically creates license upon checkout.session.completed."""
    monkeypatch.setattr(license_app, "STRIPE_WEBHOOK_SECRET", "")

    webhook_payload = {
        "id": "evt_test_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_session_999",
                "customer": "cus_999",
                "subscription": "sub_999",
                "customer_details": {
                    "email": "jan@example.nl",
                    "name": "Jan Jansen",
                },
                "metadata": {
                    "customer_name": "Jansen Advies",
                    "license_type": "proNL",
                    "max_devices": "5",
                    "days_valid": "365",
                },
            }
        },
    }

    response = client.post("/webhook/stripe", json=webhook_payload)
    assert response.status_code == 200
    assert response.json() == {"status": "success"}

    lic = license_app.get_license_by_stripe_session_id("cs_test_session_999")
    assert lic is not None
    assert lic.customer_name == "Jansen Advies"
    assert lic.license_type == "proNL"
    assert lic.max_devices == 5
    assert lic.stripe_subscription_id == "sub_999"
    assert lic.auto_renew == 1


def test_stripe_webhook_invoice_payment_succeeded(client, monkeypatch):
    """Test annual subscription renewal extends license expiry by +365 days."""
    monkeypatch.setattr(license_app, "STRIPE_WEBHOOK_SECRET", "")

    record = license_app.insert_license_record(
        customer_name="Renewal Customer",
        license_type="pro",
        days_valid=30,
        stripe_subscription_id="sub_renewal_123",
    )
    old_expiry = record["expires_at"]

    webhook_payload = {
        "id": "evt_inv_123",
        "type": "invoice.payment_succeeded",
        "data": {
            "object": {
                "billing_reason": "subscription_cycle",
                "subscription": "sub_renewal_123",
            }
        },
    }

    response = client.post("/webhook/stripe", json=webhook_payload)
    assert response.status_code == 200

    lic = license_app.get_license_by_stripe_subscription_id("sub_renewal_123")
    assert lic is not None
    assert lic.expires_at > old_expiry


def test_stripe_webhook_subscription_deleted(client, monkeypatch):
    """Test cancellation webhook sets auto_renew to 0."""
    monkeypatch.setattr(license_app, "STRIPE_WEBHOOK_SECRET", "")

    license_app.insert_license_record(
        customer_name="Cancel Customer",
        license_type="proNL",
        stripe_subscription_id="sub_cancel_123",
        auto_renew=1,
    )

    webhook_payload = {
        "id": "evt_sub_del",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_cancel_123",
                "status": "canceled",
                "cancel_at_period_end": True,
            }
        },
    }

    response = client.post("/webhook/stripe", json=webhook_payload)
    assert response.status_code == 200

    lic = license_app.get_license_by_stripe_subscription_id("sub_cancel_123")
    assert lic is not None
    assert lic.auto_renew == 0


def test_create_portal_session(client, monkeypatch):
    """Test /create-portal-session creates Stripe Customer Portal redirect URL."""
    monkeypatch.setattr(license_app, "STRIPE_SECRET_KEY", "sk_test_mock_123")

    record = license_app.insert_license_record(
        customer_name="Portal User",
        license_type="pro",
        stripe_customer_id="cus_portal_123",
    )

    mock_portal = mock.MagicMock()
    mock_portal.url = "https://billing.stripe.com/p/session/portal_123"

    with mock.patch("stripe.billing_portal.Session.create", return_value=mock_portal):
        response = client.post(
            "/create-portal-session",
            json={"license_key": record["license_key"]},
        )

    assert response.status_code == 200
    assert response.json()["portal_url"] == "https://billing.stripe.com/p/session/portal_123"


def test_checkout_success_page_rendering(client):
    """Test /checkout/success page renders correctly for existing session."""
    record = license_app.insert_license_record(
        customer_name="Gemeente Amsterdam",
        license_type="pro",
        days_valid=365,
        max_devices=1,
        stripe_session_id="cs_test_success_page",
    )

    response = client.get("/checkout/success?session_id=cs_test_success_page")
    assert response.status_code == 200
    html = response.text
    assert "Payment Successful!" in html
    assert record["license_key"] in html
    assert "Gemeente Amsterdam" in html
    assert "PRO" in html
    assert "Manage / Cancel Automatic Renewal" in html


def test_customer_license_info_and_deactivate_device(client):
    """Test customer self-service device info and deactivation endpoints."""
    record = license_app.insert_license_record(
        customer_name="Brabant Water",
        license_type="proNL",
        days_valid=365,
        max_devices=3,
    )
    key = record["license_key"]
    lic_id = record["id"]

    # Activate 2 devices
    license_app.upsert_activation(lic_id, "machine_hash_1111111111111111", "PC-OFFICE-1", "0.1.0")
    license_app.upsert_activation(lic_id, "machine_hash_2222222222222222", "LAPTOP-HOME-2", "0.1.0")

    # Fetch license info as customer
    res = client.post("/customer/license-info", json={"license_key": key})
    assert res.status_code == 200
    data = res.json()
    assert data["customer_name"] == "Brabant Water"
    assert data["max_devices"] == 3
    assert data["active_devices_count"] == 2
    assert len(data["activations"]) == 2

    # Customer deactivates LAPTOP-HOME-2
    deact_res = client.post(
        "/customer/deactivate-device",
        json={"license_key": key, "machine_id": "machine_hash_2222222222222222"},
    )
    assert deact_res.status_code == 200
    assert deact_res.json()["deactivated"] is True

    # Re-fetch license info to verify slot released
    res_after = client.post("/customer/license-info", json={"license_key": key})
    assert res_after.status_code == 200
    data_after = res_after.json()
    assert data_after["active_devices_count"] == 1
    assert len(data_after["activations"]) == 1
    assert data_after["activations"][0]["device_name"] == "PC-OFFICE-1"

