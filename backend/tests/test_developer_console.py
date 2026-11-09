from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.config import settings
from app.database import Base, engine
from app.main import app
from app.security import limiter


def _login(client, path: str, email: str, password: str):
    return client.post(path, json={"email": email, "password": password})


def _headers(response) -> dict:
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_developer_login_is_a_separate_portal(client):
    owner = _login(client, "/api/auth/login", "demo@finovexa.ai", "Demo1234!")
    assert owner.status_code == 200
    employee = _login(
        client, "/api/auth/employee/login", "employee@finovexa.ai", "Employee1234!"
    )
    assert employee.status_code == 200

    developer = _login(
        client, "/api/auth/developer/login", "developer@finovexa.ai", "Developer1234!"
    )
    assert developer.status_code == 200, developer.text
    body = developer.json()
    assert body["user"]["role"] == "developer"
    assert body["profile"] is None
    assert body["business"] is None

    assert (
        _login(
            client, "/api/auth/developer/login", "demo@finovexa.ai", "Demo1234!"
        ).status_code
        == 403
    )
    assert (
        _login(
            client,
            "/api/auth/developer/login",
            "employee@finovexa.ai",
            "Employee1234!",
        ).status_code
        == 403
    )
    assert (
        _login(
            client, "/api/auth/login", "developer@finovexa.ai", "Developer1234!"
        ).status_code
        == 403
    )
    assert (
        _login(
            client,
            "/api/auth/employee/login",
            "developer@finovexa.ai",
            "Developer1234!",
        ).status_code
        == 403
    )


def test_developer_console_is_least_privilege(client, demo, developer):
    employee = _login(
        client, "/api/auth/employee/login", "employee@finovexa.ai", "Employee1234!"
    )
    employee_headers = _headers(employee)

    assert client.get("/api/developer/overview", headers=demo["headers"]).status_code == 403
    assert client.get("/api/developer/overview", headers=employee_headers).status_code == 403
    for path in (
        "/api/dashboard",
        "/api/invoices",
        "/api/approvals",
        "/api/payments/overview",
        "/api/team/employees",
        "/api/employee/overview",
    ):
        assert client.get(path, headers=developer["headers"]).status_code == 403

    overview = client.get("/api/developer/overview", headers=developer["headers"])
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert body["counts"]["owners"] >= 1
    assert body["counts"]["employees"] >= 1
    assert body["counts"]["developers"] >= 1
    assert "accountant and customer logins" in body["developer"]["account_management"]
    serialized = json.dumps(body).lower()
    assert "developer1234" not in serialized
    assert "pbkdf2_sha256$" not in serialized


def test_developer_manages_owner_and_employee_accounts(client, developer):
    created_owner = client.post(
        "/api/developer/accounts",
        json={
            "role": "owner",
            "email": "new.owner@example.com",
            "password": "OwnerPass1234!",
            "full_name": "New Owner",
            "business_name": "New Business",
            "currency": "INR",
        },
        headers=developer["headers"],
    )
    assert created_owner.status_code == 201, created_owner.text
    owner_account = created_owner.json()["account"]
    assert owner_account["role"] == "owner"
    assert owner_account["business_name"] == "New Business"
    assert "password" not in json.dumps(created_owner.json()).lower()

    created_employee = client.post(
        "/api/developer/accounts",
        json={
            "role": "employee",
            "email": "new.employee@example.com",
            "password": "EmployeePass1234!",
            "full_name": "New Employee",
            "owner_id": owner_account["id"],
        },
        headers=developer["headers"],
    )
    assert created_employee.status_code == 201, created_employee.text
    employee_account = created_employee.json()["account"]
    assert employee_account["role"] == "employee"
    assert employee_account["owner_email"] == "new.owner@example.com"

    roster = client.get("/api/developer/accounts", headers=developer["headers"])
    assert roster.status_code == 200
    assert any(item["id"] == employee_account["id"] for item in roster.json()["items"])

    duplicate = client.post(
        "/api/developer/accounts",
        json={
            "role": "owner",
            "email": "new.owner@example.com",
            "password": "OwnerPass1234!",
            "full_name": "Duplicate Owner",
            "business_name": "Duplicate",
        },
        headers=developer["headers"],
    )
    assert duplicate.status_code == 409

    owner_login = _login(
        client, "/api/auth/login", "new.owner@example.com", "OwnerPass1234!"
    )
    assert owner_login.status_code == 200
    employee_login = _login(
        client, "/api/auth/employee/login", "new.employee@example.com", "EmployeePass1234!"
    )
    assert employee_login.status_code == 200

    reset = client.patch(
        f"/api/developer/accounts/{employee_account['id']}",
        json={"password": "RotatedPass1234!"},
        headers=developer["headers"],
    )
    assert reset.status_code == 200, reset.text
    assert "RotatedPass1234" not in reset.text
    assert (
        _login(
            client, "/api/auth/employee/login", "new.employee@example.com", "EmployeePass1234!"
        ).status_code
        == 401
    )
    assert (
        _login(
            client, "/api/auth/employee/login", "new.employee@example.com", "RotatedPass1234!"
        ).status_code
        == 200
    )

    renamed = client.patch(
        f"/api/developer/accounts/{employee_account['id']}",
        json={"email": "renamed.employee@example.com"},
        headers=developer["headers"],
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["account"]["email"] == "renamed.employee@example.com"
    assert (
        _login(
            client, "/api/auth/employee/login", "new.employee@example.com", "RotatedPass1234!"
        ).status_code
        == 401
    )
    assert (
        _login(
            client,
            "/api/auth/employee/login",
            "renamed.employee@example.com",
            "RotatedPass1234!",
        ).status_code
        == 200
    )

    duplicate_email = client.patch(
        f"/api/developer/accounts/{employee_account['id']}",
        json={"email": "new.owner@example.com"},
        headers=developer["headers"],
    )
    assert duplicate_email.status_code == 409

    disabled = client.patch(
        f"/api/developer/accounts/{employee_account['id']}",
        json={"is_active": False},
        headers=developer["headers"],
    )
    assert disabled.status_code == 200
    assert (
        _login(
            client,
            "/api/auth/employee/login",
            "renamed.employee@example.com",
            "RotatedPass1234!",
        ).status_code
        == 401
    )
    enabled = client.patch(
        f"/api/developer/accounts/{employee_account['id']}",
        json={"is_active": True},
        headers=developer["headers"],
    )
    assert enabled.status_code == 200
    assert (
        _login(
            client,
            "/api/auth/employee/login",
            "renamed.employee@example.com",
            "RotatedPass1234!",
        ).status_code
        == 200
    )

    self_update = client.patch(
        f"/api/developer/accounts/{developer['user']['id']}",
        json={"is_active": False},
        headers=developer["headers"],
    )
    assert self_update.status_code == 404

    invalid_owner = client.post(
        "/api/developer/accounts",
        json={
            "role": "owner",
            "email": "no.business@example.com",
            "password": "OwnerPass1234!",
            "full_name": "No Business",
        },
        headers=developer["headers"],
    )
    assert invalid_owner.status_code == 422
    invalid_employee = client.post(
        "/api/developer/accounts",
        json={
            "role": "employee",
            "email": "no.owner@example.com",
            "password": "EmployeePass1234!",
            "full_name": "No Owner",
        },
        headers=developer["headers"],
    )
    assert invalid_employee.status_code == 422


def test_disabling_an_owner_blocks_their_employee_sessions(client, developer):
    owner = client.post(
        "/api/developer/accounts",
        json={
            "role": "owner",
            "email": "blocked.owner@example.com",
            "password": "OwnerPass1234!",
            "full_name": "Blocked Owner",
            "business_name": "Blocked Business",
        },
        headers=developer["headers"],
    ).json()["account"]
    employee = client.post(
        "/api/developer/accounts",
        json={
            "role": "employee",
            "email": "blocked.employee@example.com",
            "password": "EmployeePass1234!",
            "full_name": "Blocked Employee",
            "owner_id": owner["id"],
        },
        headers=developer["headers"],
    ).json()["account"]

    employee_login = _login(
        client,
        "/api/auth/employee/login",
        "blocked.employee@example.com",
        "EmployeePass1234!",
    )
    assert employee_login.status_code == 200
    employee_headers = _headers(employee_login)
    assert client.get("/api/employee/overview", headers=employee_headers).status_code == 200

    disabled = client.patch(
        f"/api/developer/accounts/{owner['id']}",
        json={"is_active": False},
        headers=developer["headers"],
    )
    assert disabled.status_code == 200
    assert client.get("/api/employee/overview", headers=employee_headers).status_code == 401
    assert (
        _login(
            client, "/api/auth/login", "blocked.owner@example.com", "OwnerPass1234!"
        ).status_code
        == 401
    )

    still_present = client.get("/api/developer/accounts", headers=developer["headers"]).json()
    assert any(item["id"] == employee["id"] for item in still_present["items"])


def test_developer_security_log_is_scoped_to_account_events(client, developer):
    accounts = client.get("/api/developer/accounts", headers=developer["headers"]).json()["items"]
    owner = next(item for item in accounts if item["role"] == "owner")
    client.post(
        "/api/developer/accounts",
        json={
            "role": "employee",
            "email": "log.employee@example.com",
            "password": "EmployeePass1234!",
            "full_name": "Log Employee",
            "owner_id": owner["id"],
        },
        headers=developer["headers"],
    )
    log = client.get("/api/developer/security-log?limit=100", headers=developer["headers"])
    assert log.status_code == 200, log.text
    items = log.json()["items"]
    actions = {item["action"] for item in items}
    assert "auth.developer_login" in actions
    assert "developer.account_created" in actions
    assert all(
        action.startswith("auth.")
        or action.startswith("developer.")
        or action.startswith("team.")
        for action in actions
    )
    serialized = json.dumps(log.json()).lower()
    assert "employee1234" not in serialized
    assert "developer1234" not in serialized


def test_developer_manages_accountant_and_customer_logins(client, developer):
    senior = client.post(
        "/api/developer/accounts",
        json={
            "role": "senior_accountant",
            "email": "senior.new@example.com",
            "password": "SeniorPass1234!",
            "full_name": "Senior Accountant",
        },
        headers=developer["headers"],
    )
    assert senior.status_code == 201, senior.text
    senior_body = senior.json()
    assert senior_body["login_path"] == "/accountant/login"
    assert senior_body["account"]["role"] == "senior_accountant"
    senior_id = senior_body["account"]["id"]

    junior = client.post(
        "/api/developer/accounts",
        json={
            "role": "junior_accountant",
            "email": "junior.new@example.com",
            "password": "JuniorPass1234!",
            "full_name": "Junior Accountant",
        },
        headers=developer["headers"],
    )
    assert junior.status_code == 201, junior.text
    junior_id = junior.json()["account"]["id"]

    senior_login = _login(
        client, "/api/auth/accountant/login", "senior.new@example.com", "SeniorPass1234!"
    )
    assert senior_login.status_code == 200, senior_login.text
    assert senior_login.json()["user"]["role"] == "senior_accountant"
    assert (
        _login(
            client, "/api/auth/accountant/login", "junior.new@example.com", "JuniorPass1234!"
        ).status_code
        == 200
    )
    assert (
        _login(client, "/api/auth/login", "senior.new@example.com", "SeniorPass1234!").status_code
        == 403
    )

    rotated = client.patch(
        f"/api/developer/accounts/{senior_id}",
        json={
            "email": "senior.renamed@example.com",
            "password": "SeniorRotated1234!",
            "full_name": "Senior Renamed",
        },
        headers=developer["headers"],
    )
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["account"]["email"] == "senior.renamed@example.com"
    assert rotated.json()["account"]["full_name"] == "Senior Renamed"
    assert (
        _login(
            client, "/api/auth/accountant/login", "senior.new@example.com", "SeniorPass1234!"
        ).status_code
        == 401
    )
    assert (
        _login(
            client,
            "/api/auth/accountant/login",
            "senior.renamed@example.com",
            "SeniorRotated1234!",
        ).status_code
        == 200
    )

    disabled = client.patch(
        f"/api/developer/accounts/{junior_id}",
        json={"is_active": False},
        headers=developer["headers"],
    )
    assert disabled.status_code == 200
    assert (
        _login(
            client, "/api/auth/accountant/login", "junior.new@example.com", "JuniorPass1234!"
        ).status_code
        == 401
    )
    enabled = client.patch(
        f"/api/developer/accounts/{junior_id}",
        json={"is_active": True},
        headers=developer["headers"],
    )
    assert enabled.status_code == 200
    assert (
        _login(
            client, "/api/auth/accountant/login", "junior.new@example.com", "JuniorPass1234!"
        ).status_code
        == 200
    )

    filtered = client.get(
        "/api/developer/accounts?role=senior_accountant", headers=developer["headers"]
    )
    assert filtered.status_code == 200
    assert {item["role"] for item in filtered.json()["items"]} == {"senior_accountant"}
    assert "senior.renamed@example.com" in {
        item["email"] for item in filtered.json()["items"]
    }
    assert filtered.json()["login_paths"]["customer"] == "/client/login"

    customers = client.get(
        "/api/developer/accounts?role=customer", headers=developer["headers"]
    ).json()["items"]
    customer = next(item for item in customers if item["email"] == "client@finovexa.ai")
    customer_reset = client.patch(
        f"/api/developer/accounts/{customer['id']}",
        json={"password": "ClientRotated1234!"},
        headers=developer["headers"],
    )
    assert customer_reset.status_code == 200, customer_reset.text
    assert (
        _login(
            client, "/api/auth/customer/login", "client@finovexa.ai", "Client1234!"
        ).status_code
        == 401
    )
    customer_login = _login(
        client, "/api/auth/customer/login", "client@finovexa.ai", "ClientRotated1234!"
    )
    assert customer_login.status_code == 200, customer_login.text
    assert customer_login.json()["user"]["role"] == "customer"

    customer_create = client.post(
        "/api/developer/accounts",
        json={
            "role": "customer",
            "email": "new.client@example.com",
            "password": "ClientPass1234!",
            "full_name": "New Client",
        },
        headers=developer["headers"],
    )
    assert customer_create.status_code == 422

    overview = client.get("/api/developer/overview", headers=developer["headers"]).json()
    assert overview["counts"]["accountants"] >= 2
    assert overview["counts"]["customers"] >= 1


def test_production_bootstrap_creates_only_the_developer_login(monkeypatch):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    limiter._hits.clear()
    monkeypatch.setattr(settings, "ENV", "production")
    monkeypatch.setattr(settings, "AUTO_SEED", False)
    monkeypatch.setattr(settings, "DEMO_RESET_ENABLED", False)
    for name in (
        "INITIAL_OWNER_NAME",
        "INITIAL_OWNER_EMAIL",
        "INITIAL_OWNER_PASSWORD",
        "INITIAL_BUSINESS_NAME",
        "INITIAL_SENIOR_ACCOUNTANT_NAME",
        "INITIAL_SENIOR_ACCOUNTANT_EMAIL",
        "INITIAL_SENIOR_ACCOUNTANT_PASSWORD",
        "INITIAL_JUNIOR_ACCOUNTANT_NAME",
        "INITIAL_JUNIOR_ACCOUNTANT_EMAIL",
        "INITIAL_JUNIOR_ACCOUNTANT_PASSWORD",
    ):
        monkeypatch.setattr(settings, name, "")
    monkeypatch.setattr(settings, "DEVELOPER_NAME", "Platform Developer")
    monkeypatch.setattr(settings, "DEVELOPER_EMAIL", "developer@finovexa.ai")
    monkeypatch.setattr(settings, "DEVELOPER_PASSWORD", "Developer1234!")

    with TestClient(app) as client:
        developer = _login(
            client, "/api/auth/developer/login", "developer@finovexa.ai", "Developer1234!"
        )
        assert developer.status_code == 200, developer.text
        developer_headers = _headers(developer)

        overview = client.get("/api/developer/overview", headers=developer_headers).json()
        assert overview["environment"] == "production"
        assert overview["counts"] == {
            "owners": 0,
            "employees": 0,
            "accountants": 0,
            "customers": 0,
            "developers": 1,
            "active_accounts": 0,
            "inactive_accounts": 0,
            "auth_events_24h": 1,
        }

        owner = client.post(
            "/api/developer/accounts",
            json={
                "role": "owner",
                "email": "first.owner@example.com",
                "password": "OwnerPass1234!",
                "full_name": "First Owner",
                "business_name": "First Business",
            },
            headers=developer_headers,
        )
        assert owner.status_code == 201, owner.text
        owner_id = owner.json()["account"]["id"]

        accountant = client.post(
            "/api/developer/accounts",
            json={
                "role": "senior_accountant",
                "email": "first.accountant@example.com",
                "password": "AccountantPass1234!",
                "full_name": "First Accountant",
            },
            headers=developer_headers,
        )
        assert accountant.status_code == 201, accountant.text

        employee = client.post(
            "/api/developer/accounts",
            json={
                "role": "employee",
                "email": "first.employee@example.com",
                "password": "EmployeePass1234!",
                "full_name": "First Employee",
                "owner_id": owner_id,
            },
            headers=developer_headers,
        )
        assert employee.status_code == 201, employee.text

        owner_login = _login(
            client, "/api/auth/login", "first.owner@example.com", "OwnerPass1234!"
        )
        assert owner_login.status_code == 200, owner_login.text
        assert (
            client.get("/api/dashboard", headers=_headers(owner_login)).status_code == 200
        )
        assert (
            _login(
                client,
                "/api/auth/accountant/login",
                "first.accountant@example.com",
                "AccountantPass1234!",
            ).status_code
            == 200
        )
        assert (
            _login(
                client,
                "/api/auth/employee/login",
                "first.employee@example.com",
                "EmployeePass1234!",
            ).status_code
            == 200
        )
        assert (
            _login(client, "/api/auth/login", "demo@finovexa.ai", "Demo1234!").status_code
            == 401
        )
        assert (
            _login(
                client, "/api/auth/employee/login", "employee@finovexa.ai", "Employee1234!"
            ).status_code
            == 401
        )
