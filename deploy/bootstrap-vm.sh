#!/usr/bin/env bash
# One-time VM preparation for the FINOVEXA API on a GCP e2-micro (Ubuntu 24.04).
# Idempotent: safe to re-run. No secrets are written here.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo bash bootstrap-vm.sh" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get install -y -qq \
  docker.io docker-compose-v2 \
  sqlite3 curl ca-certificates jq rsync \
  unattended-upgrades

systemctl enable --now docker
systemctl enable --now unattended-upgrades

install -d -m 0755 /opt/finovexa
install -d -m 0755 /opt/finovexa/src /opt/finovexa/backups /opt/finovexa/env
install -d -m 0755 /opt/finovexa/data /opt/finovexa/data/backups /opt/finovexa/data/uploads
# Container runs as UID/GID 1000; keep the data tree writable by that user.
chown -R 1000:1000 /opt/finovexa/data

# 2 GB swap absorbs the pandas/reportlab peaks on a 1 GB VM.
if [[ ! -f /swapfile ]]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
cat > /etc/sysctl.d/99-finovexa.conf <<'EOF'
vm.swappiness=10
vm.vfs_cache_pressure=50
EOF
sysctl --system >/dev/null

# Cap journal size so logs never crowd the 30 GB disk.
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/limits.conf <<'EOF'
[Journal]
SystemMaxUse=200M
RuntimeMaxUse=50M
EOF
systemctl restart systemd-journald

# Docker log rotation is also set per-service in docker-compose.yml.
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" },
  "live-restore": true
}
EOF
systemctl restart docker

echo "Bootstrap complete."
echo "Next: copy the source to /opt/finovexa/src, create /opt/finovexa/env/api.env, then run docker compose up -d --build."
