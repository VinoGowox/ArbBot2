#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root: sudo bash deploy/install_logrotate.sh"
  exit 1
fi

mkdir -p /var/log/arbbot
chown arbbot:arbbot /var/log/arbbot
chmod 750 /var/log/arbbot

cp deploy/arbbot-logrotate /etc/logrotate.d/arbbot
chmod 644 /etc/logrotate.d/arbbot

logrotate -d /etc/logrotate.d/arbbot || true

echo "Logrotate installed."
