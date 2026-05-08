#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root: sudo bash deploy/install_service.sh"
  exit 1
fi

cp deploy/arbbot.service /etc/systemd/system/arbbot.service
chmod 644 /etc/systemd/system/arbbot.service

systemctl daemon-reload
systemctl enable arbbot.service
systemctl restart arbbot.service
systemctl status arbbot.service --no-pager

echo "Service installed and restarted."
