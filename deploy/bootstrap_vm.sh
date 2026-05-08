#!/usr/bin/env bash
set -euo pipefail

APP_USER="arbbot"
APP_GROUP="arbbot"
APP_DIR="/opt/arbbot"
REPO_DIR="${APP_DIR}/app"
PYTHON_BIN="python3"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root: sudo bash deploy/bootstrap_vm.sh"
  exit 1
fi

apt-get update
apt-get install -y python3 python3-venv python3-pip git curl ca-certificates

if ! id -u "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /home/${APP_USER} --shell /usr/sbin/nologin ${APP_USER}
fi

groupadd -f ${APP_GROUP}
usermod -a -G ${APP_GROUP} ${APP_USER}

mkdir -p ${APP_DIR}
chown -R ${APP_USER}:${APP_GROUP} ${APP_DIR}
chmod 750 ${APP_DIR}

if [[ ! -d "${REPO_DIR}" ]]; then
  echo "Create ${REPO_DIR} and copy project files there before continuing."
fi

if [[ ! -f "${REPO_DIR}/requirements.txt" ]]; then
  echo "requirements.txt not found at ${REPO_DIR}. Copy project first."
  exit 1
fi

if [[ ! -d "${REPO_DIR}/.venv" ]]; then
  sudo -u ${APP_USER} ${PYTHON_BIN} -m venv ${REPO_DIR}/.venv
fi

sudo -u ${APP_USER} ${REPO_DIR}/.venv/bin/python -m pip install --upgrade pip
sudo -u ${APP_USER} ${REPO_DIR}/.venv/bin/python -m pip install -r ${REPO_DIR}/requirements.txt

if [[ ! -f "${REPO_DIR}/.env" ]]; then
  cp ${REPO_DIR}/.env.example ${REPO_DIR}/.env
  chown ${APP_USER}:${APP_GROUP} ${REPO_DIR}/.env
  chmod 640 ${REPO_DIR}/.env
  echo "Created ${REPO_DIR}/.env from template. Please edit it before starting service."
fi

echo "Bootstrap complete. Next: install systemd unit and start service."
