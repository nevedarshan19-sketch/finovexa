from __future__ import annotations

import pytest

from app.database import SessionLocal
from app.models import AccountingBusinessTransaction, AuditEvent, utcnow


def _login(client, path, email, password):
    response = client.post(path, json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    return {"headers": {"Authorization": f"Bearer {body['access_token']}"}, "user": body["user"]}


@pytest.fixture()
def senior(client):
    return _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")


@pytest.fixture()
def junior(client):
    return _login(client, "/api/auth/accountant/login", "junior@finovexa.ai", "Junior1234!")


def _clients(client, headers):
    response = client.get("/api/accounting/senior/clients", headers=headers)
    assert response.status_code == 200, response.text
    return {row["business_name"]: row for row in response.json()["items"]}


def _options(client, headers):
    response = client.get("/api/accounting/senior/business-options", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_seeded_link_and_status(client, demo, senior, junior):
    clients = _clients(client, senior["headers"])
    dn_ventures = clients["DN Ventures Pvt. Ltd"]
    meridian = clients["Meridian Traders"]
    assert dn_ventures["integration"]["status"] == "linked"
    assert meridian["integration"]["status"] == "not_linked"

    detail = client.get(
        f"/api/accounting/senior/clients/{meridian['id']}", headers=senior["headers"]
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["integration"]["linked"] is False

    assert client.get(
        "/api/accounting/senior/business-options", headers=junior["headers"]
    ).status_code == 403

    owner_status = client.get("/api/integration/accounting", headers=demo["headers"])
    assert owner_status.status_code == 200, owner_status.text
    body = owner_status.json()
    assert body["linked"] is True
    assert body["business"]["business_name"] == "DN Ventures Pvt. Ltd"
    assert body["counts"]["total"] == 0
    assert "settings" not in body


def test_link_unlink_audit_and_owner_isolation(client, senior, junior, other):
    clients = _clients(client, senior["headers"])
    sunrise = clients["Sunrise Interiors"]
    meridian = clients["Meridian Traders"]
    target = next(
        option for option in _options(client, senior["headers"])
        if option["business_name"] == "Second Business"
    )
    assert target["linked_client_id"] is None

    linked = client.post(
        f"/api/accounting/senior/clients/{sunrise['id']}/integration/link",
        json={"business_profile_id": target["business_profile_id"]},
        headers=senior["headers"],
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["linked"] is True
    assert linked.json()["business"]["business_name"] == "Second Business"

    assert client.post(
        f"/api/accounting/senior/clients/{meridian['id']}/integration/link",
        json={"business_profile_id": target["business_profile_id"]},
        headers=senior["headers"],
    ).status_code == 409

    assert client.post(
        f"/api/accounting/senior/clients/{sunrise['id']}/integration/link",
        json={"business_profile_id": target["business_profile_id"]},
        headers=junior["headers"],
    ).status_code == 403

    owner = client.get("/api/integration/accounting", headers=other["headers"])
    assert owner.status_code == 200, owner.text
    assert owner.json()["linked"] is True
    assert owner.json()["business"]["business_name"] == "Second Business"

    db = SessionLocal()
    try:
        row = AccountingBusinessTransaction(
            client_id=sunrise["id"],
            business_profile_id=target["business_profile_id"],
            source_type="invoice",
            source_id=9001,
            source_ref="SL-9001",
            transaction_date=utcnow().date(),
            financial_year="2026-27",
            transaction_type="sale",
            party_name="Owner-only customer",
            source_hash="a" * 64,
            total_amount=1180,
            taxable_value=1000,
        )
        db.add(row)
        db.commit()
    finally:
        db.close()

    own = client.get("/api/integration/accounting/transactions", headers=other["headers"])
    assert own.status_code == 200, own.text
    assert own.json()["total"] == 1
    assert own.json()["items"][0]["source_ref"] == "SL-9001"

    unrelated = client.get("/api/integration/accounting/transactions", headers=senior["headers"])
    # A senior is not a business owner, so the owner-only router still evaluates its guard.
    assert unrelated.status_code == 403

    unlinked = client.post(
        f"/api/accounting/senior/clients/{sunrise['id']}/integration/unlink",
        headers=senior["headers"],
    )
    assert unlinked.status_code == 200, unlinked.text
    assert unlinked.json()["linked"] is False
    assert unlinked.json()["status"] == "not_linked"

    db = SessionLocal()
    try:
        preserved = (
            db.query(AccountingBusinessTransaction)
            .filter(AccountingBusinessTransaction.client_id == sunrise["id"])
            .count()
        )
        assert preserved == 1
        actions = {
            event.action
            for event in db.query(AuditEvent)
            .filter(AuditEvent.entity_type == "accounting_client")
            .all()
        }
    finally:
        db.close()
    assert "accounting.integration_linked" in actions
    assert "accounting.integration_unlinked" in actions


def test_owner_cannot_manage_links(client, demo):
    assert client.get(
        "/api/accounting/senior/clients/1/integration", headers=demo["headers"]
    ).status_code == 403
    assert client.post(
        "/api/accounting/senior/clients/1/integration/link",
        json={"business_profile_id": 1},
        headers=demo["headers"],
    ).status_code == 403
    assert client.get("/api/accounting/senior/business-options", headers=demo["headers"]).status_code == 403
