from __future__ import annotations

from app.database import SessionLocal
from app.models import AccountingVoucher, Expense, Invoice, Payment


def _login(client, path, email, password):
    response = client.post(path, json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    return {"headers": {"Authorization": f"Bearer {body['access_token']}"}, "user": body["user"]}


def _clients(client, headers):
    response = client.get("/api/accounting/senior/clients", headers=headers)
    assert response.status_code == 200, response.text
    return {row["business_name"]: row for row in response.json()["items"]}


def _summary(client, headers, client_id, *, role="senior", **params):
    response = client.get(
        f"/api/accounting/{role}/clients/{client_id}/business/summary",
        params=params,
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _transactions(client, headers, client_id, *, role="senior", **params):
    response = client.get(
        f"/api/accounting/{role}/clients/{client_id}/business/transactions",
        params=params,
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _source_counts(owner_id: int) -> dict:
    db = SessionLocal()
    try:
        return {
            "invoices": db.query(Invoice).filter(Invoice.user_id == owner_id).count(),
            "payments": db.query(Payment).filter(Payment.user_id == owner_id).count(),
            "refunds": db.query(Payment)
            .filter(
                Payment.user_id == owner_id,
                Payment.refund_of_payment_id.isnot(None),
            )
            .count(),
            "expenses": db.query(Expense).filter(Expense.user_id == owner_id).count(),
        }
    finally:
        db.close()


def test_business_view_matches_owner_ledger_and_never_writes(client, demo):
    senior = _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    owner_id = demo["user"]["id"]
    expected = _source_counts(owner_id)

    db = SessionLocal()
    try:
        invoices_before = db.query(Invoice).count()
        vouchers_before = (
            db.query(AccountingVoucher)
            .filter(AccountingVoucher.client_id == dn["id"])
            .count()
        )
    finally:
        db.close()

    summary = _summary(client, senior["headers"], dn["id"], days=30)
    assert summary["linked"] is True
    assert summary["business"]["business_name"] == "DN Ventures Pvt. Ltd"
    assert summary["period"]["days"] == 30
    assert set(summary["metrics"]) >= {
        "revenue",
        "cash_received",
        "expenses",
        "gross_profit",
        "net_profit",
        "invoice_count",
    }
    assert summary["counts"]["invoices"] == expected["invoices"]
    assert summary["counts"]["payments"] == expected["payments"]
    assert summary["counts"]["refunds"] == expected["refunds"]
    assert summary["counts"]["expenses"] == expected["expenses"]
    assert summary["counts"]["total"] == (
        expected["invoices"] + expected["payments"] + expected["expenses"]
    )
    assert summary["integration"]["inbox"]["total"] == 0
    assert "Tally exports read posted accounting vouchers only" in summary["tally"]["note"]

    history = _transactions(client, senior["headers"], dn["id"], limit=200)
    assert history["linked"] is True
    assert history["total"] == summary["counts"]["total"]
    assert history["summary"]["sale"]["count"] == expected["invoices"]
    assert history["summary"]["receipt"]["count"] + history["summary"]["refund"]["count"] == expected["payments"]
    assert history["summary"]["expense"]["count"] == expected["expenses"]
    assert all(item["accounting"]["inbox_status"] == "not_synced" for item in history["items"])
    assert history["items"] == sorted(
        history["items"],
        key=lambda item: (item["date"], item["source_type"], item["source_id"]),
        reverse=True,
    )

    db = SessionLocal()
    try:
        assert db.query(Invoice).count() == invoices_before
        assert (
            db.query(AccountingVoucher)
            .filter(AccountingVoucher.client_id == dn["id"])
            .count()
            == vouchers_before
        )
    finally:
        db.close()


def test_transaction_filters_search_and_paging(client):
    senior = _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    everything = _transactions(client, senior["headers"], dn["id"], limit=200)
    sample = everything["items"][0]

    by_type = _transactions(
        client,
        senior["headers"],
        dn["id"],
        transaction_type=sample["transaction_type"],
        limit=200,
    )
    assert by_type["total"] > 0
    assert all(item["transaction_type"] == sample["transaction_type"] for item in by_type["items"])

    searched = _transactions(
        client,
        senior["headers"],
        dn["id"],
        search=sample["reference"],
        limit=200,
    )
    assert searched["total"] >= 1
    assert all(sample["reference"].lower() in item["reference"].lower() for item in searched["items"])

    same_day = _transactions(
        client,
        senior["headers"],
        dn["id"],
        date_from=sample["date"],
        date_to=sample["date"],
        limit=200,
    )
    assert same_day["total"] >= 1
    assert all(item["date"] == sample["date"] for item in same_day["items"])

    page = _transactions(client, senior["headers"], dn["id"], limit=2, offset=1)
    assert page["total"] == everything["total"]
    assert page["offset"] == 1
    expected = everything["items"][1:3]
    assert page["items"] == expected


def test_accounting_statuses_follow_sync_draft_and_post(client):
    senior = _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")
    dn = _clients(client, senior["headers"])["DN Ventures Pvt. Ltd"]
    sync = client.post(
        f"/api/accounting/senior/clients/{dn['id']}/integration/sync",
        headers=senior["headers"],
    )
    assert sync.status_code == 200, sync.text

    after_sync = _transactions(client, senior["headers"], dn["id"], limit=200)
    synced = [item for item in after_sync["items"] if item["accounting"]["inbox_status"] == "pending"]
    assert synced

    generated = client.post(
        f"/api/accounting/senior/clients/{dn['id']}/integration/drafts/generate",
        json={"limit": 200},
        headers=senior["headers"],
    )
    assert generated.status_code == 200, generated.text
    draft = next(row for row in generated.json()["drafts"] if row["voucher_type"] == "sale")

    for action in ("submit", "approve", "post"):
        response = client.post(
            f"/api/accounting/senior/clients/{dn['id']}/integration/drafts/{draft['id']}/{action}",
            json={},
            headers=senior["headers"],
        )
        assert response.status_code == 200, response.text

    after_post = _transactions(client, senior["headers"], dn["id"], limit=200)
    posted = next(
        item for item in after_post["items"] if item["accounting"]["draft_id"] == draft["id"]
    )
    assert posted["accounting"]["inbox_status"] == "posted"
    assert posted["accounting"]["draft_status"] == "posted"
    assert posted["accounting"]["voucher_number"] == draft["number"]
    assert posted["accounting"]["voucher_id"] is not None


def test_business_view_permissions_and_unlinked_client(client, demo):
    senior = _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")
    junior = _login(client, "/api/auth/accountant/login", "junior@finovexa.ai", "Junior1234!")
    customer = _login(client, "/api/auth/customer/login", "client@finovexa.ai", "Client1234!")
    clients = _clients(client, senior["headers"])
    dn = clients["DN Ventures Pvt. Ltd"]
    sunrise = clients["Sunrise Interiors"]
    meridian = clients["Meridian Traders"]

    assert _summary(client, junior["headers"], dn["id"], role="junior")["linked"] is True
    assert _transactions(client, junior["headers"], dn["id"], role="junior")["total"] > 0

    assert client.get(
        f"/api/accounting/junior/clients/{sunrise['id']}/business/summary",
        headers=junior["headers"],
    ).status_code == 403
    assert client.get(
        f"/api/accounting/junior/clients/{sunrise['id']}/business/transactions",
        headers=junior["headers"],
    ).status_code == 403

    assert client.get(
        f"/api/accounting/senior/clients/{dn['id']}/business/summary",
        headers=demo["headers"],
    ).status_code == 403
    assert client.get(
        f"/api/accounting/senior/clients/{dn['id']}/business/transactions",
        headers=demo["headers"],
    ).status_code == 403
    assert client.get(
        f"/api/accounting/senior/clients/{dn['id']}/business/summary",
        headers=customer["headers"],
    ).status_code == 403
    assert client.get(
        "/api/accounting/senior/clients/999999/business/summary",
        headers=senior["headers"],
    ).status_code == 404

    unlinked_summary = _summary(client, senior["headers"], meridian["id"])
    assert unlinked_summary["linked"] is False
    assert unlinked_summary["business"] is None
    unlinked_history = _transactions(client, senior["headers"], meridian["id"])
    assert unlinked_history["linked"] is False
    assert unlinked_history["items"] == []
    assert unlinked_history["total"] == 0
