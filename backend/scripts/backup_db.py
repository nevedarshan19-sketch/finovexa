"""Encrypted SQLite backup and restore.

Usage (run from backend/):

    python scripts/backup_db.py keygen --key-file backups/backup.key
    python scripts/backup_db.py create --key-file backups/backup.key
    python scripts/backup_db.py verify --key-file backups/backup.key --input backups/finovexa-....enc
    python scripts/backup_db.py restore --key-file backups/backup.key \
        --input backups/finovexa-....enc --target /tmp/restored.db

The key can also come from BACKUP_ENCRYPTION_KEY (URL-safe base64, 32 bytes).
Files are encrypted with AES-256-GCM. The payload is a JSON metadata record,
two newlines, then the raw SQLite snapshot. A restore verifies the hash and
SQLite integrity before writing the target.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"FVXBAK1\n"
NONCE_BYTES = 12
KEY_BYTES = 32
DEFAULT_DB = Path(__file__).resolve().parent.parent / "finovexa.db"
DEFAULT_BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_key(key_file: Path | None) -> bytes:
    if key_file is not None:
        raw = key_file.read_text(encoding="utf-8").strip()
    else:
        raw = os.environ.get("BACKUP_ENCRYPTION_KEY", "").strip()
    if not raw:
        raise SystemExit(
            "No backup key. Set BACKUP_ENCRYPTION_KEY or pass --key-file. "
            "Generate one once with: python scripts/backup_db.py keygen --key-file backups/backup.key"
        )
    try:
        key = base64.urlsafe_b64decode(raw.encode("ascii"))
    except Exception as exc:  # noqa: BLE001 - report a single clear configuration error
        raise SystemExit("BACKUP_ENCRYPTION_KEY must be URL-safe base64.") from exc
    if len(key) != KEY_BYTES:
        raise SystemExit(f"Backup key must decode to {KEY_BYTES} bytes.")
    return key


def _database_path() -> Path:
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        return DEFAULT_DB
    if not raw.startswith("sqlite:///"):
        raise SystemExit(
            "This tool encrypts SQLite files. For Postgres use the provider's encrypted "
            "backup service or pg_dump into the same AES-GCM envelope."
        )
    path = Path(raw[len("sqlite:///") :])
    return path if path.is_absolute() else (Path.cwd() / path).resolve()


def _snapshot(db_path: Path) -> bytes:
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")
    with tempfile.TemporaryDirectory() as directory:
        snapshot = Path(directory) / "snapshot.db"
        source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        target = sqlite3.connect(snapshot)
        try:
            source.backup(target)
            check = target.execute("PRAGMA integrity_check;").fetchone()
        finally:
            target.close()
            source.close()
        if not check or check[0] != "ok":
            raise SystemExit(f"SQLite integrity check failed before backup: {check}")
        return snapshot.read_bytes()


def _encrypt(payload: bytes, key: bytes) -> bytes:
    nonce = secrets.token_bytes(NONCE_BYTES)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, payload, MAGIC)


def _decrypt(blob: bytes, key: bytes) -> bytes:
    if not blob.startswith(MAGIC):
        raise SystemExit("Not a FINOVEXA encrypted backup.")
    nonce = blob[len(MAGIC) : len(MAGIC) + NONCE_BYTES]
    if len(nonce) != NONCE_BYTES:
        raise SystemExit("Backup file is truncated.")
    try:
        return AESGCM(key).decrypt(nonce, blob[len(MAGIC) + NONCE_BYTES :], MAGIC)
    except Exception as exc:  # noqa: BLE001 - wrong key and corruption both mean "cannot trust"
        raise SystemExit("Backup could not be decrypted: wrong key or corrupt file.") from exc


def create_backup(
    db_path: Path,
    output_dir: Path,
    key: bytes,
) -> Path:
    data = _snapshot(db_path)
    metadata = {
        "format": "finovexa-sqlite-aesgcm-v1",
        "created_at": _now(),
        "source": str(db_path),
        "database_sha256": hashlib.sha256(data).hexdigest(),
        "database_bytes": len(data),
    }
    payload = json.dumps(metadata, sort_keys=True).encode("utf-8") + b"\n\n" + data
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = output_dir / f"finovexa-{stamp}.db.enc"
    suffix = 1
    while target.exists():
        target = output_dir / f"finovexa-{stamp}-{suffix}.db.enc"
        suffix += 1
    target.write_bytes(_encrypt(payload, key))
    return target


def read_backup(backup: Path, key: bytes) -> tuple[dict, bytes]:
    payload = _decrypt(backup.read_bytes(), key)
    header, separator, data = payload.partition(b"\n\n")
    if not separator:
        raise SystemExit("Backup payload is malformed.")
    try:
        metadata = json.loads(header)
    except json.JSONDecodeError as exc:
        raise SystemExit("Backup metadata is malformed.") from exc
    if hashlib.sha256(data).hexdigest() != metadata.get("database_sha256"):
        raise SystemExit("Backup database hash does not match its metadata.")
    return metadata, data


def verify_backup(backup: Path, key: bytes) -> dict:
    metadata, data = read_backup(backup, key)
    with tempfile.TemporaryDirectory() as directory:
        probe = Path(directory) / "probe.db"
        probe.write_bytes(data)
        connection = sqlite3.connect(probe)
        try:
            check = connection.execute("PRAGMA integrity_check;").fetchone()
            tables = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table';"
            ).fetchone()
        finally:
            connection.close()
    if not check or check[0] != "ok":
        raise SystemExit(f"Restored database failed integrity check: {check}")
    return {**metadata, "integrity": check[0], "tables": tables[0] if tables else 0}


def restore_backup(backup: Path, target: Path, key: bytes) -> dict:
    metadata, data = read_backup(backup, key)
    if target.exists():
        raise SystemExit(f"Target already exists: {target}. Choose a new path or move it first.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    connection = sqlite3.connect(target)
    try:
        check = connection.execute("PRAGMA integrity_check;").fetchone()
    finally:
        connection.close()
    if not check or check[0] != "ok":
        target.unlink(missing_ok=True)
        raise SystemExit(f"Restored database failed integrity check: {check}")
    return {**metadata, "restored_to": str(target), "integrity": check[0]}


def keygen(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SystemExit(f"Refusing to overwrite existing key: {path}")
    path.write_text(base64.urlsafe_b64encode(secrets.token_bytes(KEY_BYTES)).decode("ascii"), encoding="utf-8")
    path.chmod(0o600)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Encrypted SQLite backup and restore.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    keygen_parser = subparsers.add_parser("keygen", help="Create a new backup key file.")
    keygen_parser.add_argument("--key-file", type=Path, required=True)

    create_parser = subparsers.add_parser("create", help="Create an encrypted backup.")
    create_parser.add_argument("--db", type=Path, default=None)
    create_parser.add_argument("--output-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    create_parser.add_argument("--key-file", type=Path, default=None)

    verify_parser = subparsers.add_parser("verify", help="Decrypt and verify a backup.")
    verify_parser.add_argument("--input", type=Path, required=True)
    verify_parser.add_argument("--key-file", type=Path, default=None)

    restore_parser = subparsers.add_parser("restore", help="Restore a backup to a new path.")
    restore_parser.add_argument("--input", type=Path, required=True)
    restore_parser.add_argument("--target", type=Path, required=True)
    restore_parser.add_argument("--key-file", type=Path, default=None)

    args = parser.parse_args()

    if args.command == "keygen":
        path = keygen(args.key_file)
        print(f"Backup key written to {path} (mode 600). Store it outside the repository.")
        return

    key = _load_key(args.key_file)
    if args.command == "create":
        created = create_backup(args.db or _database_path(), args.output_dir, key)
        print(f"Encrypted backup written to {created}")
    elif args.command == "verify":
        print(json.dumps(verify_backup(args.input, key), indent=2))
    elif args.command == "restore":
        print(json.dumps(restore_backup(args.input, args.target, key), indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
