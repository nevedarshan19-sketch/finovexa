from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Customer, Invoice, Product, User
from app.seed import provision_initial_accounts


@pytest.fixture()
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


def configure(monkeypatch, **values):
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)


def configure_all(monkeypatch):
    configure(
        monkeypatch,
        INITIAL_OWNER_NAME="Darshan Neve",
        INITIAL_OWNER_EMAIL="Owner@Finovexa.example",
        INITIAL_OWNER_PASSWORD="OwnerStrong123!",
        INITIAL_BUSINESS_NAME="Neve Trading Co",
        INITIAL_SENIOR_ACCOUNTANT_NAME="Anita Desai",
        INITIAL_SENIOR_ACCOUNTANT_EMAIL="senior@finovexa.example",
        INITIAL_SENIOR_ACCOUNTANT_PASSWORD="SeniorStrong123!",
        INITIAL_JUNIOR_ACCOUNTANT_NAME="Rahul Mehta",
        INITIAL_JUNIOR_ACCOUNTANT_EMAIL="junior@finovexa.example",
        INITIAL_JUNIOR_ACCOUNTANT_PASSWORD="JuniorStrong123!",
    )


def test_provision_creates_accounts_without_business_records(clean_db, monkeypatch):
    configure_all(monkeypatch)
    with SessionLocal() as db:
        statuses = provision_initial_accounts(db)
        assert statuses == {
            "owner": "created",
            "senior_accountant": "created",
            "junior_accountant": "created",
        }
        owner = db.query(User).filter(User.email == "owner@finovexa.example").one()
        assert owner.role == "owner"
        assert owner.is_demo is False
        assert owner.profile is not None
        assert owner.profile.business_name == "Neve Trading Co"
        assert owner.profile.opening_cash_balance == 0
        senior = db.query(User).filter(User.email == "senior@finovexa.example").one()
        junior = db.query(User).filter(User.email == "junior@finovexa.example").one()
        assert senior.role == "senior_accountant"
        assert junior.role == "junior_accountant"
        assert senior.is_demo is False and junior.is_demo is False
        assert db.query(Customer).count() == 0
        assert db.query(Product).count() == 0
        assert db.query(Invoice).count() == 0


def test_provision_is_idempotent_and_never_overwrites(clean_db, monkeypatch):
    configure_all(monkeypatch)
    with SessionLocal() as db:
        provision_initial_accounts(db)
        owner = db.query(User).filter(User.email == "owner@finovexa.example").one()
        original_hash = owner.password_hash
        assert provision_initial_accounts(db) == {
            "owner": "exists",
            "senior_accountant": "exists",
            "junior_accountant": "exists",
        }
        db.refresh(owner)
        assert owner.password_hash == original_hash
        assert db.query(User).count() == 3


def test_provision_skips_missing_values_and_rejects_weak_password(clean_db, monkeypatch):
    configure(
        monkeypatch,
        INITIAL_OWNER_NAME="Owner",
        INITIAL_OWNER_EMAIL="owner@finovexa.example",
        INITIAL_OWNER_PASSWORD="short",
        INITIAL_SENIOR_ACCOUNTANT_EMAIL="",
        INITIAL_SENIOR_ACCOUNTANT_PASSWORD="",
        INITIAL_JUNIOR_ACCOUNTANT_EMAIL="not-an-email",
        INITIAL_JUNIOR_ACCOUNTANT_PASSWORD="JuniorStrong123!",
    )
    with SessionLocal() as db:
        statuses = provision_initial_accounts(db)
        assert statuses == {
            "owner": "invalid_password",
            "senior_accountant": "not_configured",
            "junior_accountant": "invalid_email",
        }
        assert db.query(User).count() == 0


def test_provision_rejects_reserved_email_domains(clean_db, monkeypatch):
    """A reserved TLD would create an account the login schema rejects."""
    configure(
        monkeypatch,
        INITIAL_OWNER_EMAIL="owner@finovexa.test",
        INITIAL_OWNER_PASSWORD="OwnerStrong123!",
        INITIAL_SENIOR_ACCOUNTANT_EMAIL="",
        INITIAL_JUNIOR_ACCOUNTANT_EMAIL="",
    )
    with SessionLocal() as db:
        statuses = provision_initial_accounts(db)
        assert statuses["owner"] == "invalid_email"
        assert db.query(User).count() == 0


def test_provision_refuses_to_take_over_an_existing_email(clean_db, monkeypatch):
    configure_all(monkeypatch)
    with SessionLocal() as db:
        provision_initial_accounts(db)
        configure(monkeypatch, INITIAL_JUNIOR_ACCOUNTANT_EMAIL="owner@finovexa.example")
        assert provision_initial_accounts(db)["junior_accountant"] == "conflict"
        assert db.query(User).filter(User.email == "owner@finovexa.example").one().role == "owner"


def test_provisioned_accounts_can_sign_in(clean_db, monkeypatch):
    configure_all(monkeypatch)
    with TestClient(app) as client:
        owner = client.post(
            "/api/auth/login",
            json={"email": "owner@finovexa.example", "password": "OwnerStrong123!"},
        )
        assert owner.status_code == 200, owner.text
        assert owner.json()["user"]["role"] == "owner"

        senior = client.post(
            "/api/auth/accountant/login",
            json={"email": "senior@finovexa.example", "password": "SeniorStrong123!"},
        )
        assert senior.status_code == 200, senior.text
        assert senior.json()["user"]["role"] == "senior_accountant"

        junior = client.post(
            "/api/auth/accountant/login",
            json={"email": "junior@finovexa.example", "password": "JuniorStrong123!"},
        )
        assert junior.status_code == 200, junior.text
        assert junior.json()["user"]["role"] == "junior_accountant"
