#!/usr/bin/env bash

set -euo pipefail

HOST="${ASWITCH_HOST:-aswitch.local}"
USER_NAME="${ASWITCH_USER:-pi}"
REMOTE_DIR="${ASWITCH_REMOTE_DIR:-/home/${USER_NAME}/aswitch}"
SERVICE_NAME="${ASWITCH_SERVICE:-aswitch.service}"
SERVICE_TEMPLATE="${ASWITCH_SERVICE_TEMPLATE:-${SERVICE_NAME}}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "Deploying to ${USER_NAME}@${HOST}:${REMOTE_DIR}"

ssh "${USER_NAME}@${HOST}" "mkdir -p '${REMOTE_DIR}'"

TMP_SERVICE_FILE="$(mktemp)"
trap 'rm -f "${TMP_SERVICE_FILE}"' EXIT

sed \
  -e "s|__ASWITCH_USER__|${USER_NAME}|g" \
  -e "s|__ASWITCH_REMOTE_DIR__|${REMOTE_DIR}|g" \
  "${SCRIPT_DIR}/${SERVICE_TEMPLATE}" > "${TMP_SERVICE_FILE}"

scp \
  "${ROOT_DIR}"/*.py \
  "${ROOT_DIR}/requirements.txt" \
  "${TMP_SERVICE_FILE}" \
  "${USER_NAME}@${HOST}:${REMOTE_DIR}/"

ssh -t "${USER_NAME}@${HOST}" "
  python3 -m venv '${REMOTE_DIR}/.venv' &&
  '${REMOTE_DIR}/.venv/bin/pip' install --upgrade pip &&
  '${REMOTE_DIR}/.venv/bin/pip' install -r '${REMOTE_DIR}/requirements.txt' &&
  sudo cp '${REMOTE_DIR}/$(basename "${TMP_SERVICE_FILE}")' '/etc/systemd/system/${SERVICE_NAME}' &&
  sudo systemctl daemon-reload &&
  sudo systemctl enable '${SERVICE_NAME}' &&
  sudo systemctl restart '${SERVICE_NAME}' &&
  sudo systemctl --no-pager --full status '${SERVICE_NAME}'
"
