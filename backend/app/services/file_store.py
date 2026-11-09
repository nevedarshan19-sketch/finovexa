from __future__ import annotations

import hashlib
import os
import secrets
import tempfile
from contextlib import contextmanager
from typing import Iterator
from urllib.parse import quote

from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..config import settings
from ..models import StoredFile

MODE_LOCAL = "local"
MODE_DATABASE = "database"


class StoredFileMissing(Exception):
    pass


def storage_mode() -> str:
    return MODE_DATABASE if settings.FILE_STORAGE.strip().lower() == MODE_DATABASE else MODE_LOCAL


def _safe_suffix(suffix: str) -> str:
    clean = suffix.strip().lstrip(".").lower()
    if clean and all(character.isalnum() or character in "._-" for character in clean):
        return clean
    return "bin"


def _stored_name(suffix: str) -> str:
    return f"{secrets.token_hex(16)}.{_safe_suffix(suffix)}"


def _local_path(stored_name: str) -> str:
    return os.path.join(settings.ACCOUNTING_UPLOAD_DIR, os.path.basename(stored_name))


def save_bytes(
    db: Session, raw: bytes, suffix: str, *, content_type: str = ""
) -> tuple[str, str, int]:
    stored_name = _stored_name(suffix)
    digest = hashlib.sha256(raw).hexdigest()
    if storage_mode() == MODE_DATABASE:
        db.add(
            StoredFile(
                stored_name=stored_name,
                content=raw,
                content_type=content_type,
                size_bytes=len(raw),
                sha256=digest,
            )
        )
        db.flush()
        return stored_name, digest, len(raw)

    directory = settings.ACCOUNTING_UPLOAD_DIR
    os.makedirs(directory, exist_ok=True)
    with open(_local_path(stored_name), "wb") as handle:
        handle.write(raw)
    return stored_name, digest, len(raw)


def _database_record(db: Session, stored_name: str) -> StoredFile | None:
    return (
        db.query(StoredFile)
        .filter(StoredFile.stored_name == os.path.basename(stored_name))
        .one_or_none()
    )


def exists(db: Session, stored_name: str) -> bool:
    if _database_record(db, stored_name) is not None:
        return True
    return os.path.isfile(_local_path(stored_name))


def read_bytes(db: Session, stored_name: str) -> bytes:
    record = _database_record(db, stored_name)
    if record is not None:
        return bytes(record.content)
    path = _local_path(stored_name)
    if os.path.isfile(path):
        with open(path, "rb") as handle:
            return handle.read()
    raise StoredFileMissing(stored_name)


@contextmanager
def local_path(db: Session, stored_name: str) -> Iterator[str]:
    """Yield a filesystem path, materialising a temporary copy for database files."""
    path = _local_path(stored_name)
    if os.path.isfile(path):
        yield path
        return
    raw = read_bytes(db, stored_name)
    descriptor, temp_path = tempfile.mkstemp(suffix=f".{_safe_suffix(os.path.splitext(stored_name)[1])}")
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)
    try:
        yield temp_path
    finally:
        if os.path.isfile(temp_path):
            os.unlink(temp_path)


def content_disposition(filename: str) -> str:
    plain = filename.encode("ascii", "ignore").decode("ascii").replace('"', "") or "download"
    return f"attachment; filename=\"{plain}\"; filename*=utf-8''{quote(filename)}"


def build_download(
    db: Session,
    stored_name: str,
    *,
    filename: str,
    media_type: str = "application/octet-stream",
    headers: dict[str, str] | None = None,
) -> Response:
    raw = read_bytes(db, stored_name)
    response_headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": content_disposition(filename),
        "Content-Length": str(len(raw)),
    }
    if headers:
        response_headers.update(headers)
    return Response(content=raw, media_type=media_type, headers=response_headers)
