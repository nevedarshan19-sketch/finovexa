from __future__ import annotations

import os
import tempfile
from decimal import Decimal
from pathlib import Path

TEST_DIR = Path(tempfile.mkdtemp(prefix="finovexa-tests-"))
os.environ.update(
    {
        "ENV": "test",
        "DATABASE_URL": f"sqlite:///{TEST_DIR / 'finovexa-test.db'}",
        "AUTO_SEED": "true",
        "SECRET_KEY": "test-only-secret-key-4f1c9a2b7e3d",
        "DEMO_EMAIL": "demo@finovexa.ai",
        "DEMO_PASSWORD": "Demo1234!",
        "DEMO_RESET_ENABLED": "true",
        "SEED_DEMO_TRANSACTIONS": "true",
        "DEVELOPER_NAME": "Test Developer",
        "DEVELOPER_EMAIL": "developer@finovexa.ai",
        "DEVELOPER_PASSWORD": "Developer1234!",
        "LLM_PROVIDER": "none",
        "LLM_API_KEY": "",
        "PAYPAL_CLIENT_ID": "",
        "PAYPAL_CLIENT_SECRET": "",
        "UPSTOX_ACCESS_TOKEN": "",
        "METALS_API_KEY": "",
        "NEWS_API_KEY": "",
        "ACCOUNTING_UPLOAD_DIR": str(TEST_DIR / "accounting-uploads"),
        "DEMO_SENIOR_ACCOUNTANT_EMAIL": "senior@finovexa.ai",
        "DEMO_SENIOR_ACCOUNTANT_PASSWORD": "Senior1234!",
        "DEMO_JUNIOR_ACCOUNTANT_EMAIL": "junior@finovexa.ai",
        "DEMO_JUNIOR_ACCOUNTANT_PASSWORD": "Junior1234!",
        "DEMO_CLIENT_EMAIL": "client@finovexa.ai",
        "DEMO_CLIENT_PASSWORD": "Client1234!",
    }
)

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app
from app.security import limiter


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    limiter._hits.clear()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def demo(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "demo@finovexa.ai", "password": "Demo1234!"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "user": body["user"],
        "profile": body["profile"],
    }


@pytest.fixture()
def developer(client):
    response = client.post(
        "/api/auth/developer/login",
        json={"email": "developer@finovexa.ai", "password": "Developer1234!"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "user": body["user"],
    }


@pytest.fixture()
def other(client):
    response = client.post(
        "/api/auth/register",
        json={
            "email": "owner@second-business.example.com",
            "password": "Second1234!",
            "full_name": "Second Owner",
            "business_name": "Second Business",
            "currency": "INR",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return {
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "user": body["user"],
    }


def invoices_by_number(client, headers):
    response = client.get("/api/invoices?limit=100", headers=headers)
    assert response.status_code == 200, response.text
    return {item["number"]: item for item in response.json()["items"]}


def amount(value) -> Decimal:
    """JSON serializes Numeric columns as floats; normalise through str to compare cleanly."""
    return Decimal(str(value))


def approval_by_title(client, headers, needle, status="pending"):
    response = client.get(f"/api/approvals?status={status}&limit=100", headers=headers)
    assert response.status_code == 200, response.text
    for item in response.json()["items"]:
        if needle in item["title"]:
            return item
    raise AssertionError(f"No approval matching {needle!r} with status {status!r}")
