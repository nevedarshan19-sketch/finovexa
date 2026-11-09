from __future__ import annotations

import base64
from pathlib import Path

import pytest

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import StoredFile
from app.services import file_store


@pytest.fixture()
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


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


def _data_url(text: str, mime: str = "text/csv") -> str:
    return f"data:{mime};base64," + base64.b64encode(text.encode("utf-8")).decode("ascii")


def _clients(client, headers):
    response = client.get("/api/accounting/senior/clients", headers=headers)
    assert response.status_code == 200, response.text
    return {row["business_name"]: row for row in response.json()["items"]}


def test_local_mode_round_trip(tmp_path, clean_db, monkeypatch):
    monkeypatch.setattr(settings, "FILE_STORAGE", "local")
    monkeypatch.setattr(settings, "ACCOUNTING_UPLOAD_DIR", str(tmp_path))
    with SessionLocal() as db:
        payload = b"ledger,total\ncash,10\n"
        name, digest, size = file_store.save_bytes(db, payload, "csv")
        assert size == len(payload)
        assert (tmp_path / name).read_bytes() == payload
        assert file_store.exists(db, name)
        assert file_store.read_bytes(db, name) == payload
        assert db.query(StoredFile).count() == 0
        response = file_store.build_download(
            db, name, filename="ledger.csv", media_type="text/csv"
        )
        assert response.body == payload
        assert "attachment" in response.headers["content-disposition"]


def test_database_mode_round_trip_and_temp_materialisation(tmp_path, clean_db, monkeypatch):
    monkeypatch.setattr(settings, "FILE_STORAGE", "database")
    monkeypatch.setattr(settings, "ACCOUNTING_UPLOAD_DIR", str(tmp_path / "does-not-exist"))
    with SessionLocal() as db:
        name, digest, size = file_store.save_bytes(db, b"%PDF-1.4 test", "pdf", content_type="application/pdf")
        db.commit()
        assert size == 13
        assert not (tmp_path / "does-not-exist" / name).exists()
        record = db.query(StoredFile).one()
        assert record.sha256 == digest
        assert record.content_type == "application/pdf"
        assert file_store.exists(db, name)
        assert file_store.read_bytes(db, name) == b"%PDF-1.4 test"
        with file_store.local_path(db, name) as path:
            materialised = Path(path)
            assert materialised.read_bytes() == b"%PDF-1.4 test"
        assert not materialised.exists()


def test_database_mode_serves_document_uploads(client, senior, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "FILE_STORAGE", "database")
    monkeypatch.setattr(settings, "ACCOUNTING_UPLOAD_DIR", str(tmp_path / "absent"))
    meridian = _clients(client, senior["headers"])["Meridian Traders"]
    upload = client.post(
        "/api/accounting/documents",
        headers=senior["headers"],
        json={
            "client_id": meridian["id"],
            "filename": "bill.csv",
            "title": "Purchase bill",
            "category": "purchase_bill",
            "data_url": _data_url("bill,total\nb1,1200\n"),
        },
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["id"]

    with SessionLocal() as db:
        record = db.query(StoredFile).one()
        assert record.size_bytes == len(b"bill,total\nb1,1200\n")
    assert not (tmp_path / "absent").exists()

    download = client.get(
        f"/api/accounting/documents/{document_id}/file", headers=senior["headers"]
    )
    assert download.status_code == 200, download.text
    assert download.content == b"bill,total\nb1,1200\n"
    assert "attachment" in download.headers["content-disposition"]


def test_database_mode_supports_tally_revalidate_and_source_download(
    client, senior, junior, monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "FILE_STORAGE", "database")
    monkeypatch.setattr(settings, "ACCOUNTING_UPLOAD_DIR", str(tmp_path / "absent"))
    meridian = _clients(client, senior["headers"])["Meridian Traders"]
    upload = client.post(
        "/api/accounting/tally-migration/batches",
        headers=junior["headers"],
        json={
            "client_id": meridian["id"],
            "tally_version": "TallyPrime 4.1",
            "financial_year": "2024-25",
            "import_type": "sales",
            "file_format": "csv",
            "filename": "sales.csv",
            "data_url": _data_url(
                "Voucher Type,Voucher No,Voucher Date,Party Name,Ledger Name,Debit,Credit,GST Rate,Narration\n"
                "Sales,S-1,2024-05-10,Ravi Traders,Ravi Traders,1180,0,18,Sale\n"
                "Sales,S-1,2024-05-10,Ravi Traders,Sales Account,0,1000,18,Sale\n"
                "Sales,S-1,2024-05-10,Ravi Traders,Output CGST,0,90,18,Sale\n"
                "Sales,S-1,2024-05-10,Ravi Traders,Output SGST,0,90,18,Sale\n"
            ),
        },
    )
    assert upload.status_code == 201, upload.text
    batch_id = upload.json()["id"]

    with SessionLocal() as db:
        assert db.query(StoredFile).count() == 1

    revalidate = client.post(
        f"/api/accounting/tally-migration/batches/{batch_id}/revalidate",
        headers=junior["headers"],
        json={},
    )
    assert revalidate.status_code == 200, revalidate.text

    source = client.get(
        f"/api/accounting/tally-migration/batches/{batch_id}/source",
        headers=junior["headers"],
    )
    assert source.status_code == 200, source.text
    assert source.content.startswith(b"Voucher Type,Voucher No")


def test_missing_file_returns_404(clean_db, monkeypatch):
    monkeypatch.setattr(settings, "FILE_STORAGE", "database")
    with SessionLocal() as db:
        name, _, _ = file_store.save_bytes(db, b"temporary", "csv")
        db.commit()
        db.query(StoredFile).delete()
        db.commit()
        with pytest.raises(file_store.StoredFileMissing):
            file_store.read_bytes(db, name)
        assert not file_store.exists(db, name)
