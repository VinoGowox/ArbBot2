#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  status)
    systemctl status arbbot.service --no-pager
    ;;
  start)
    sudo systemctl start arbbot.service
    ;;
  stop)
    sudo systemctl stop arbbot.service
    ;;
  restart)
    sudo systemctl restart arbbot.service
    ;;
  logs)
    journalctl -u arbbot.service -n 200 -f
    ;;
  env-edit)
    sudo nano /opt/arbbot/app/.env
    ;;
  *)
    echo "Usage: bash deploy/ops.sh {status|start|stop|restart|logs|env-edit}"
    exit 1
    ;;
esac
