from __future__ import annotations

from datetime import date, timedelta

from conftest import amount


def _new_customer(client, demo, suffix: str) -> dict:
    response = client.post(
        "/api/billing/customers",
        json={
            "name": f"Stage {suffix.title()} Buyer",
            "email": f"stage.{suffix}@example.com",
            "company": "Stage Traders",
            "phone": "9876543210",
            "state": "Maharashtra",
            "state_code": "27",
        },
        headers=demo["headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()["item"]


def _new_invoice(
    client, demo, *, number: str, customer_id: int, due_in_days: int, price: str = "1000.00"
) -> dict:
    today = date.today()
    response = client.post(
        "/api/invoices",
        json={
            "customer_id": customer_id,
            "number": number,
            "issue_date": (today - timedelta(days=40)).isoformat(),
            "due_date": (today + timedelta(days=due_in_days)).isoformat(),
            "tax_rate": "0",
            "items": [{"description": "Consulting", "quantity": "1", "unit_price": price}],
        },
        headers=demo["headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()


def _schedule(client, demo, **params) -> dict:
    response = client.get(
        "/api/recovery/reminder-schedule", params=params, headers=demo["headers"]
    )
    assert response.status_code == 200, response.text
    return response.json()


def _item(schedule: dict, number: str) -> dict:
    return next(item for item in schedule["items"] if item["invoice"]["number"] == number)


def test_reminder_schedule_maps_invoices_to_deadline_stages(client, demo):
    customer = _new_customer(client, demo, "ladder")
    today = date.today()
    cases = {
        "INV-STAGE-A": (4, "due_in_7"),
        "INV-STAGE-B": (0, "due_today"),
        "INV-STAGE-C": (-3, "overdue_1_7"),
        "INV-STAGE-D": (-10, "overdue_8_14"),
        "INV-STAGE-E": (-20, "overdue_15_plus"),
    }
    created = {
        number: _new_invoice(
            client,
            demo,
            number=number,
            customer_id=customer["id"],
            due_in_days=offset,
        )
        for number, (offset, _) in cases.items()
    }
    _new_invoice(
        client, demo, number="INV-STAGE-F", customer_id=customer["id"], due_in_days=30
    )

    body = _schedule(client, demo)
    assert body["as_of"] == today.isoformat()
    assert body["window_days"] == 7
    by_number = {item["invoice"]["number"]: item for item in body["items"]}
    for number, (offset, stage) in cases.items():
        item = by_number[number]
        assert item["stage"] == stage
        assert item["days_until_due"] == offset
        assert amount(item["outstanding"]) == amount(created[number]["outstanding"])
        assert item["share"]["text"].startswith("Hi Stage,")
        assert item["reminded"] is False
    assert "INV-STAGE-F" not in by_number
    assert body["summary"]["not_due_count"] >= 1

    assert [tile["key"] for tile in body["summary"]["by_stage"]] == [
        "due_in_7",
        "due_today",
        "overdue_1_7",
        "overdue_8_14",
        "overdue_15_plus",
    ]
    for tile in body["summary"]["by_stage"]:
        assert tile["count"] >= 1
        assert tile["unreminded_count"] == tile["count"]
    assert body["summary"]["actionable_count"] == len(body["items"])

    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    ranks = [rank[item["severity"]] for item in body["items"]]
    assert ranks == sorted(ranks)


def test_stage_reminder_dispatch_marks_the_stage_as_covered(client, demo):
    customer = _new_customer(client, demo, "dispatch")
    invoice = _new_invoice(
        client,
        demo,
        number="INV-STAGE-DISPATCH",
        customer_id=customer["id"],
        due_in_days=-10,
    )
    before = _item(_schedule(client, demo), "INV-STAGE-DISPATCH")
    assert before["reminded"] is False
    assert before["reminder_count"] == 0
    assert before["tone"] == "firm"

    draft = client.post(
        f"/api/recovery/reminder-draft/{invoice['id']}",
        json={"channel": "email", "stage": "overdue_8_14"},
        headers=demo["headers"],
    )
    assert draft.status_code == 200, draft.text
    draft_body = draft.json()
    assert draft_body["stage"] == "overdue_8_14"
    assert draft_body["current_stage"] == "overdue_8_14"
    assert draft_body["tone"] == "firm"
    assert draft_body["recipient"] == customer["email"]
    assert "10 day(s) ago" in draft_body["body"]

    approval = client.post(
        "/api/approvals/reminders",
        json={
            "invoice_id": invoice["id"],
            "channel": "email",
            "recipient": customer["email"],
            "subject": draft_body["subject"],
            "body": draft_body["body"],
            "stage": "overdue_8_14",
        },
        headers=demo["headers"],
    )
    assert approval.status_code == 201, approval.text
    approval_body = approval.json()
    assert approval_body["payload"]["stage"] == "overdue_8_14"

    approved = client.post(
        f"/api/approvals/{approval_body['id']}/approve",
        json={"confirm": True, "payload_hash": approval_body["payload_hash"]},
        headers=demo["headers"],
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"]["dispatch"] == "simulated"

    after = _item(_schedule(client, demo), "INV-STAGE-DISPATCH")
    assert after["reminded"] is True
    assert after["reminded_channels"] == ["email"]
    assert after["reminder_count"] == 1
    assert after["last_reminder_at"] is not None

    detail = client.get(f"/api/invoices/{invoice['id']}", headers=demo["headers"]).json()
    assert detail["reminders"][0]["stage"] == "overdue_8_14"


def test_share_links_are_built_from_customer_contacts_without_dispatching(client, demo):
    customer = _new_customer(client, demo, "share")
    invoice = _new_invoice(
        client,
        demo,
        number="INV-STAGE-SHARE",
        customer_id=customer["id"],
        due_in_days=3,
    )
    item = _item(_schedule(client, demo), "INV-STAGE-SHARE")
    share = item["share"]
    assert item["contact"]["email"] == customer["email"]
    assert item["contact"]["phone"] == customer["phone"]
    assert "INV-STAGE-SHARE" in share["text"]
    assert "INR 1,000.00" in share["text"]
    assert share["mailto_url"].startswith(f"mailto:{customer['email']}?subject=")
    assert share["whatsapp_url"].startswith("https://wa.me/919876543210?text=")
    assert share["sms_uri"].startswith("sms:+919876543210")

    detail = client.get(f"/api/invoices/{invoice['id']}", headers=demo["headers"]).json()
    assert detail["reminders"] == []


def test_reminder_schedule_is_owner_only(client):
    login = client.post(
        "/api/auth/employee/login",
        json={"email": "employee@finovexa.ai", "password": "Employee1234!"},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = client.get("/api/recovery/reminder-schedule", headers=headers)
    assert response.status_code == 403
