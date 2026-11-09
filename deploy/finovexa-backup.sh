#!/usr/bin/env bash
# Daily encrypted database + uploads backup, with optional off-box copy to GCS.
# Installed at /opt/finovexa/finovexa-backup.sh and run by finovexa-backup.timer.
set -euo pipefail

ENV_FILE=/opt/finovexa/env/backup.env
[[ -f "$ENV_FILE" ]] && set -a && . "$ENV_FILE" && set +a

DATA_DIR=/opt/finovexa/data
BACKUP_DIR=/opt/finovexa/backups
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
KEEP_DAYS=${KEEP_DAYS:-14}
BUCKET=${BACKUP_BUCKET:-}

mkdir -p "$BACKUP_DIR"

# 1. Encrypted SQLite snapshot via the in-container tool (AES-256-GCM, verified hash).
docker exec finovexa-api python scripts/backup_db.py create \
  --db /app/data/finovexa.db \
  --output-dir /app/data/backups >/dev/null

DB_FILE=$(ls -1t "$DATA_DIR"/backups/finovexa-*.db.enc | head -n 1)
DB_SHA=$(sha256sum "$DB_FILE" | cut -d' ' -f1)

# 2. Uploaded documents (small, but not reproducible from the database).
UPLOADS_ARCHIVE="$BACKUP_DIR/uploads-$STAMP.tgz"
tar -C "$DATA_DIR" -czf "$UPLOADS_ARCHIVE" uploads

# 3. Retention on the box.
find "$BACKUP_DIR" -name 'uploads-*.tgz' -mtime +"$KEEP_DAYS" -delete
find "$DATA_DIR/backups" -name 'finovexa-*.db.enc' -mtime +"$KEEP_DAYS" -delete

# 4. Off-box copy using the VM service account (storage-rw scope, no key file).
if [[ -n "$BUCKET" ]]; then
  TOKEN=$(curl -fsS -H 'Metadata-Flavor: Google' \
    'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token' \
    | jq -r .access_token)
  curl -fsS -X POST --data-binary "@$DB_FILE" \
    -H "Authorization: Bearer $TOKEN" \
    "https://storage.googleapis.com/upload/storage/v1/b/$BUCKET/o?uploadType=media&name=database/$(basename "$DB_FILE")" >/dev/null
  curl -fsS -X POST --data-binary "@$UPLOADS_ARCHIVE" \
    -H "Authorization: Bearer $TOKEN" \
    "https://storage.googleapis.com/upload/storage/v1/b/$BUCKET/o?uploadType=media&name=uploads/$(basename "$UPLOADS_ARCHIVE")" >/dev/null
  REMOTE=yes
else
  REMOTE=no
fi

printf '{"event":"backup","at":"%s","db":"%s","db_bytes":%s,"db_sha256":"%s","uploads":"%s","offsites":%s}\n' \
  "$STAMP" "$(basename "$DB_FILE")" "$(stat -c %s "$DB_FILE")" "$DB_SHA" \
  "$(basename "$UPLOADS_ARCHIVE")" "$REMOTE"

# Fail loudly if the newest backup cannot be decrypted and verified.
docker exec finovexa-api python scripts/backup_db.py verify \
  --input "/app/data/backups/$(basename "$DB_FILE")" >/dev/null
