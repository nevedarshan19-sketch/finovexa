#!/usr/bin/env bash
# Rebuild and restart the API from /opt/finovexa/src. Run on the VM.
set -euo pipefail

cd /opt/finovexa/src/deploy
docker compose build --pull api
docker compose up -d --no-deps api

for _ in $(seq 1 30); do
  if curl -fsS -m 3 http://127.0.0.1:8000/api/health >/dev/null; then
    echo "API healthy after restart"
    exit 0
  fi
  sleep 2
done

echo "API did not become healthy; showing recent logs" >&2
docker compose logs --tail=50 api >&2
exit 1
