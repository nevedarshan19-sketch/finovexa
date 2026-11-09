from __future__ import annotations

from pathlib import Path

import pytest

from conftest import amount


DIST_INDEX = Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html"


def test_health_reports_safe_modes(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["modes"]["live_trading_enabled"] is False
    assert body["modes"]["paypal"] == "simulated"
    assert body["modes"]["llm"] == "deterministic_fallback"
    assert body["modes"]["developer_console"] == "configured"
    serialized = str(body).lower()
    assert "secret" not in serialized
    assert "password" not in serialized


def test_me_never_returns_passwords_or_demo_credentials(client, demo):
    response = client.get("/api/auth/me", headers=demo["headers"])
    assert response.status_code == 200
    body = response.json()
    assert "demo_credentials" not in body
    serialized = str(body).lower()
    assert "demo1234" not in serialized
    assert "password" not in serialized


def test_demo_login_and_profile(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "demo@finovexa.ai", "password": "Demo1234!"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["is_demo"] is True
    assert body["profile"]["currency"] == "INR"
    assert amount(body["profile"]["min_cash_reserve"]) == amount("300000.00")


def test_login_rejects_bad_password(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "demo@finovexa.ai", "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_endpoints_require_authentication(client):
    for path in ("/api/dashboard", "/api/invoices", "/api/approvals", "/api/ai/history"):
        assert client.get(path).status_code == 401


def test_tenant_isolation(client, demo, other):
    own = client.get("/api/invoices/1", headers=demo["headers"])
    assert own.status_code == 200

    foreign_invoice = client.get("/api/invoices/1", headers=other["headers"])
    assert foreign_invoice.status_code == 404

    foreign_approval = client.get("/api/approvals/1", headers=other["headers"])
    assert foreign_approval.status_code == 404

    other_invoices = client.get("/api/invoices", headers=other["headers"])
    assert other_invoices.status_code == 200
    assert other_invoices.json()["items"] == []

    other_dashboard = client.get("/api/dashboard", headers=other["headers"])
    assert other_dashboard.status_code == 200
    assert amount(other_dashboard.json()["metrics"]["revenue"]["value"]) == 0


def test_registration_hashes_password_and_rejects_duplicate(client):
    payload = {
        "email": "fresh-owner@example.com",
        "password": "Fresh1234!",
        "full_name": "Fresh Owner",
        "business_name": "Fresh Co",
        "currency": "INR",
    }
    created = client.post("/api/auth/register", json=payload)
    assert created.status_code == 201
    assert created.json()["user"]["is_demo"] is False

    duplicate = client.post("/api/auth/register", json=payload)
    assert duplicate.status_code == 409

    weak = client.post(
        "/api/auth/register",
        json={**payload, "email": "weak@example.com", "password": "onlyletters"},
    )
    assert weak.status_code == 422


@pytest.mark.skipif(not DIST_INDEX.is_file(), reason="frontend build not present")
def test_spa_shell_revalidates_instead_of_caching(client):
    for path in ("/", "/login", "/research"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache, must-revalidate"
