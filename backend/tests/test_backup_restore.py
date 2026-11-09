from __future__ import annotations

import base64
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backup_db  # noqa: E402

KEY = b"k" * backup_db.KEY_BYTES


def _make_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO users (email) VALUES (?)",
            [("owner@example.com",), ("staff@example.com",)],
        )
        connection.commit()
    finally:
        connection.close()


def test_backup_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    _make_database(source)

    backup = backup_db.create_backup(source, tmp_path / "backups", KEY)
    assert backup.exists()
    blob = backup.read_bytes()
    assert blob.startswith(backup_db.MAGIC)
    assert b"SQLite format 3" not in blob

    metadata = backup_db.verify_backup(backup, KEY)
    assert metadata["integrity"] == "ok"
    assert metadata["tables"] == 1
    assert metadata["database_sha256"]

    target = tmp_path / "restored.db"
    result = backup_db.restore_backup(backup, target, KEY)
    assert result["integrity"] == "ok"

    connection = sqlite3.connect(target)
    try:
        rows = connection.execute("SELECT email FROM users ORDER BY id").fetchall()
    finally:
        connection.close()
    assert [row[0] for row in rows] == ["owner@example.com", "staff@example.com"]


def test_backup_rejects_wrong_key(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    _make_database(source)
    backup = backup_db.create_backup(source, tmp_path / "backups", KEY)

    wrong = b"x" * backup_db.KEY_BYTES
    with pytest.raises(SystemExit, match="wrong key or corrupt"):
        backup_db.verify_backup(backup, wrong)


def test_backup_rejects_tampering(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    _make_database(source)
    backup = backup_db.create_backup(source, tmp_path / "backups", KEY)

    blob = bytearray(backup.read_bytes())
    blob[-1] ^= 0xFF
    backup.write_bytes(bytes(blob))

    with pytest.raises(SystemExit, match="wrong key or corrupt"):
        backup_db.verify_backup(backup, KEY)


def test_restore_refuses_existing_target(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    _make_database(source)
    backup = backup_db.create_backup(source, tmp_path / "backups", KEY)
    target = tmp_path / "restored.db"
    target.write_bytes(b"existing")

    with pytest.raises(SystemExit, match="Target already exists"):
        backup_db.restore_backup(backup, target, KEY)
    assert target.read_bytes() == b"existing"


def test_keygen_refuses_to_overwrite(tmp_path: Path) -> None:
    key_file = tmp_path / "backup.key"
    backup_db.keygen(key_file)
    written = key_file.read_text(encoding="utf-8").strip()
    assert len(base64.urlsafe_b64decode(written.encode("ascii"))) == backup_db.KEY_BYTES

    with pytest.raises(SystemExit, match="Refusing to overwrite"):
        backup_db.keygen(key_file)
