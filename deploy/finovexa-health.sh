#!/usr/bin/env bash
# Hourly resource and health snapshot for the FINOVEXA VM.
# Logs one JSON line to the journal; exits non-zero when a threshold is crossed.
set -uo pipefail

ALERTS=()
HEALTH=$(curl -fsS -m 5 http://127.0.0.1:8000/api/health 2>/dev/null | jq -r '.status // "unreachable"')
[[ "$HEALTH" == "ok" ]] || ALERTS+=("api_health=$HEALTH")

CONTAINER=$(docker inspect -f '{{.State.Health.Status}}' finovexa-api 2>/dev/null || echo missing)
[[ "$CONTAINER" == "healthy" ]] || ALERTS+=("container=$CONTAINER")

MEM_USED_MB=$(free -m | awk '/^Mem:/{print $3}')
MEM_TOTAL_MB=$(free -m | awk '/^Mem:/{print $2}')
MEM_PCT=$(( MEM_TOTAL_MB > 0 ? MEM_USED_MB * 100 / MEM_TOTAL_MB : 0 ))
(( MEM_PCT > 90 )) && ALERTS+=("memory_pct=$MEM_PCT")

SWAP_USED_MB=$(free -m | awk '/^Swap:/{print $3}')
DISK_PCT=$(df --output=pcent / | tail -1 | tr -dc '0-9')
DISK_AVAIL=$(df -h --output=avail / | tail -1 | tr -d ' ')
(( DISK_PCT > 75 )) && ALERTS+=("disk_pct=$DISK_PCT")

# Bytes since boot, loopback excluded.
read -r RX_B TX_B <<<"$(awk 'NR>2 && $1 !~ /lo:/ {gsub(":","",$1); rx+=$2; tx+=$10} END {print rx, tx}' /proc/net/dev)"

DB_BYTES=$(stat -c %s /opt/finovexa/data/finovexa.db 2>/dev/null || echo 0)
UPLOADS_BYTES=$(du -sb /opt/finovexa/data/uploads 2>/dev/null | cut -f1 || echo 0)
BACKUP_COUNT=$(find /opt/finovexa/backups /opt/finovexa/data/backups -name '*.enc' -o -name '*.tgz' 2>/dev/null | wc -l)

printf '{"event":"health","at":"%s","api":"%s","container":"%s","mem_used_mb":%s,"mem_total_mb":%s,"mem_pct":%s,"swap_used_mb":%s,"disk_pct":%s,"disk_avail":"%s","rx_mb":%s,"tx_mb":%s,"db_bytes":%s,"uploads_bytes":%s,"backups":%s,"alerts":%s}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$HEALTH" "$CONTAINER" \
  "$MEM_USED_MB" "$MEM_TOTAL_MB" "$MEM_PCT" "$SWAP_USED_MB" "$DISK_PCT" "$DISK_AVAIL" \
  "$((RX_B / 1048576))" "$((TX_B / 1048576))" "$DB_BYTES" "${UPLOADS_BYTES:-0}" "$BACKUP_COUNT" \
  "$(printf '%s\n' "${ALERTS[@]}" | jq -R 'select(length > 0)' | jq -sc .)"

(( ${#ALERTS[@]} == 0 )) || exit 1
