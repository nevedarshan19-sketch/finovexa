from __future__ import annotations

from datetime import date, timedelta

from conftest import amount


def _login(client, path, email, password):
    response = client.post(path, json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    return {"headers": {"Authorization": f"Bearer {body['access_token']}"}, "user": body["user"]}


def _owner(client):
    return _login(client, "/api/auth/login", "demo@finovexa.ai", "Demo1234!")


def _senior(client):
    return _login(client, "/api/auth/accountant/login", "senior@finovexa.ai", "Senior1234!")


def _catalogue(client, headers):
    response = client.get("/api/tax/gst/catalogue", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _catalogue_item(client, headers, sku="CH-ERG"):
    rows = _catalogue(client, headers)["items"]
    return next(row for row in rows if row["sku"] == sku)


def _history(client, headers):
    response = client.get("/api/tax/gst/catalogue/history", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _senior_client(client, senior):
    rows = client.get("/api/accounting/senior/clients", headers=senior["headers"]).json()["items"]
    return next(row for row in rows if row["business_name"] == "DN Ventures Pvt. Ltd")


def _invoice(client, headers, product_id, number, issue_date=None):
    customer_id = client.get("/api/invoices?limit=1", headers=headers).json()["items"][0][
        "customer"
    ]["id"]
    issue = issue_date or date.today()
    payload = {
        "customer_id": customer_id,
        "number": number,
        "issue_date": issue.isoformat(),
        "due_date": (issue + timedelta(days=20)).isoformat(),
        "tax_rate": "18",
        "items": [
            {
                "description": "Ergo Pro Task Chair",
                "quantity": "1",
                "unit_price": "1000",
                "product_id": product_id,
            }
        ],
    }
    response = client.post("/api/invoices", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_owner_edit_is_applied_and_fully_audited(client, demo):
    item = _catalogue_item(client, demo["headers"])
    assert amount(item["gst_rate"]) == amount("18")

    response = client.patch(
        f"/api/tax/gst/catalogue/{item['id']}",
        headers=demo["headers"],
        json={
            "gst_rate": 12,
            "hsn_sac": "9401",
            "item_type": "goods",
            "hsn_verified": True,
            "effective_from": date.today().isoformat(),
            "reason": "GST notification 12/2026",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert amount(body["item"]["gst_rate"]) == amount("12")
    change = body["change"]
    assert change["status"] == "applied"
    assert amount(change["old_gst_rate"]) == amount("18")
    assert amount(change["new_gst_rate"]) == amount("12")
    assert change["reason"] == "GST notification 12/2026"
    assert change["requested_by_role"] == "owner"
    assert change["requested_by"]["id"] == demo["user"]["id"]

    history = _history(client, demo["headers"])["items"]
    assert history[0]["id"] == change["id"]
    assert amount(history[0]["old_gst_rate"]) == amount("18")


def test_change_requires_reason_valid_rate_and_actual_difference(client, demo):
    item = _catalogue_item(client, demo["headers"])
    path = f"/api/tax/gst/catalogue/{item['id']}"

    missing_reason = client.patch(path, headers=demo["headers"], json={"gst_rate": 12})
    assert missing_reason.status_code == 422

    short_reason = client.patch(
        path, headers=demo["headers"], json={"gst_rate": 12, "reason": "x"}
    )
    assert short_reason.status_code == 422

    unconfigured = client.patch(
        path, headers=demo["headers"], json={"gst_rate": 17, "reason": "Testing invalid rate"}
    )
    assert unconfigured.status_code == 400

    unchanged = client.patch(
        path, headers=demo["headers"], json={"gst_rate": 18, "reason": "No actual change"}
    )
    assert unchanged.status_code == 400

    assert amount(_catalogue_item(client, demo["headers"])["gst_rate"]) == amount("18")


def test_future_effective_date_keeps_earlier_invoices_on_old_rate(client, demo):
    item = _catalogue_item(client, demo["headers"])
    future = date.today() + timedelta(days=30)
    response = client.patch(
        f"/api/tax/gst/catalogue/{item['id']}",
        headers=demo["headers"],
        json={"gst_rate": 12, "effective_from": future.isoformat(), "reason": "Rate cut from next month"},
    )
    assert response.status_code == 200, response.text

    before = _invoice(client, demo["headers"], item["id"], "INV-GST-EFF-1")
    assert amount(before["tax"]) == amount("180")
    assert amount(before["total"]) == amount("1180")
    assert before["items"][0]["gst_rate"] in (18, 18.0)

    after = _invoice(
        client,
        demo["headers"],
        item["id"],
        "INV-GST-EFF-2",
        issue_date=future + timedelta(days=1),
    )
    assert amount(after["tax"]) == amount("120")
    assert amount(after["total"]) == amount("1120")


def test_issued_invoice_keeps_its_gst_snapshot_after_catalogue_change(client, demo):
    item = _catalogue_item(client, demo["headers"])
    issued = _invoice(client, demo["headers"], item["id"], "INV-GST-LOCK-1")
    assert amount(issued["tax"]) == amount("180")

    response = client.patch(
        f"/api/tax/gst/catalogue/{item['id']}",
        headers=demo["headers"],
        json={"gst_rate": 12, "reason": "Rate change after invoice issued"},
    )
    assert response.status_code == 200, response.text

    stored = client.get(f"/api/invoices/{issued['id']}", headers=demo["headers"]).json()
    assert stored["items"][0]["gst_rate"] in (18, 18.0)
    assert amount(stored["tax"]) == amount("180")
    assert amount(stored["total"]) == amount("1180")

    fresh = _invoice(client, demo["headers"], item["id"], "INV-GST-LOCK-2")
    assert amount(fresh["tax"]) == amount("120")


def test_accountant_needs_grant_and_owner_approval(client, demo):
    senior = _senior(client)
    dn = _senior_client(client, senior)
    item = _catalogue_item(client, demo["headers"])
    senior_path = f"/api/accounting/senior/clients/{dn['id']}/gst-catalogue"

    denied = client.patch(
        f"{senior_path}/{item['id']}",
        headers=senior["headers"],
        json={"gst_rate": 12, "reason": "Senior accountant review"},
    )
    assert denied.status_code == 403

    read = client.get(senior_path, headers=senior["headers"])
    assert read.status_code == 200, read.text
    assert read.json()["can_edit"] is False
    assert read.json()["business"]["business_name"] == "DN Ventures Pvt. Ltd"

    granted = client.put(
        f"{senior_path}/permission", headers=senior["headers"], json={"enabled": True}
    )
    assert granted.status_code == 200, granted.text

    mode = client.put(
        "/api/tax/gst/catalogue/settings",
        headers=demo["headers"],
        json={"approval_mode": "owner_approval"},
    )
    assert mode.status_code == 200, mode.text

    proposed = client.patch(
        f"{senior_path}/{item['id']}",
        headers=senior["headers"],
        json={"gst_rate": 12, "reason": "Client supplied notification copy"},
    )
    assert proposed.status_code == 200, proposed.text
    payload = proposed.json()
    assert payload["change"]["status"] == "pending_approval"
    assert payload["change"]["requested_by_role"] == "accountant"
    assert amount(payload["item"]["gst_rate"]) == amount("18")

    export_allowed = client.get(f"{senior_path}/export", headers=senior["headers"])
    assert export_allowed.status_code == 200

    pending = _catalogue(client, demo["headers"])["pending_changes"]
    assert [row["id"] for row in pending] == [payload["change"]["id"]]

    approved = client.post(
        f"/api/tax/gst/catalogue/changes/{payload['change']['id']}/decision",
        headers=demo["headers"],
        json={"approve": True, "note": "Checked against notification"},
    )
    assert approved.status_code == 200, approved.text
    assert amount(approved.json()["item"]["gst_rate"]) == amount("12")
    assert approved.json()["change"]["status"] == "approved"
    assert approved.json()["change"]["decided_by"]["id"] == demo["user"]["id"]


def test_rejected_proposal_leaves_catalogue_untouched(client, demo):
    senior = _senior(client)
    dn = _senior_client(client, senior)
    senior_path = f"/api/accounting/senior/clients/{dn['id']}/gst-catalogue"
    item = _catalogue_item(client, demo["headers"])

    client.put(f"{senior_path}/permission", headers=senior["headers"], json={"enabled": True})
    client.put(
        "/api/tax/gst/catalogue/settings",
        headers=demo["headers"],
        json={"approval_mode": "owner_approval"},
    )
    proposed = client.patch(
        f"{senior_path}/{item['id']}",
        headers=senior["headers"],
        json={"gst_rate": 28, "reason": "Proposal to confirm"},
    )
    assert proposed.status_code == 200, proposed.text
    change_id = proposed.json()["change"]["id"]

    rejected = client.post(
        f"/api/tax/gst/catalogue/changes/{change_id}/decision",
        headers=demo["headers"],
        json={"approve": False, "note": "Not applicable"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["change"]["status"] == "rejected"
    assert amount(_catalogue_item(client, demo["headers"])["gst_rate"]) == amount("18")


def test_billing_product_gst_edit_requires_reason_and_is_audited(client, demo):
    products = client.get("/api/billing/products?limit=100", headers=demo["headers"]).json()["items"]
    chair = next(row for row in products if row["sku"] == "CH-ERG")

    blocked = client.put(
        f"/api/billing/products/{chair['id']}",
        headers=demo["headers"],
        json={"default_gst_rate": 12},
    )
    assert blocked.status_code == 400
    assert "reason" in blocked.json()["detail"].lower()

    name_only = client.put(
        f"/api/billing/products/{chair['id']}",
        headers=demo["headers"],
        json={"name": "Ergo Pro Task Chair (2026)"},
    )
    assert name_only.status_code == 200, name_only.text
    assert name_only.json()["item"]["name"] == "Ergo Pro Task Chair (2026)"

    updated = client.put(
        f"/api/billing/products/{chair['id']}",
        headers=demo["headers"],
        json={
            "default_gst_rate": 12,
            "hsn_sac": "9401",
            "gst_change_reason": "Supplier bulletin 12/2026",
        },
    )
    assert updated.status_code == 200, updated.text
    assert amount(updated.json()["item"]["default_gst_rate"]) == amount("12")

    history = client.get(
        f"/api/tax/gst/catalogue/history?product_id={chair['id']}", headers=demo["headers"]
    ).json()["items"]
    assert history[0]["reason"] == "Supplier bulletin 12/2026"
    assert amount(history[0]["old_gst_rate"]) == amount("18")
    assert amount(history[0]["new_gst_rate"]) == amount("12")
