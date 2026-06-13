#!/usr/bin/env bash

set -euo pipefail

HOST="${ASWITCH_HOST:-aswitch.local}"
USER_NAME="${ASWITCH_USER:-pi}"
REMOTE_DIR="${ASWITCH_REMOTE_DIR:-/home/${USER_NAME}/aswitch}"
LOCAL_ENV_FILE="${ASWITCH_ENV_FILE:-}"
RESTART_SERVICES="${ASWITCH_RESTART_SERVICES:-}"

if [[ -z "${LOCAL_ENV_FILE}" ]]; then
  echo "ASWITCH_ENV_FILE is required (example: env/pi-cam.env)"
  exit 1
fi

if [[ ! -f "${LOCAL_ENV_FILE}" ]]; then
  echo "Env file not found: ${LOCAL_ENV_FILE}"
  exit 1
fi

REMOTE_TMP="/tmp/aswitch.env"
REMOTE_ENV_FILE="${REMOTE_DIR}/.env"

echo "Pushing ${LOCAL_ENV_FILE} to ${USER_NAME}@${HOST}:${REMOTE_ENV_FILE}"

ssh "${USER_NAME}@${HOST}" "mkdir -p '${REMOTE_DIR}'"
scp "${LOCAL_ENV_FILE}" "${USER_NAME}@${HOST}:${REMOTE_TMP}"

if [[ -n "${RESTART_SERVICES}" ]]; then
  IFS=',' read -r -a SERVICES <<< "${RESTART_SERVICES}"
  REMOTE_CMD="sudo cp '${REMOTE_TMP}' '${REMOTE_ENV_FILE}' && sudo chown ${USER_NAME}:${USER_NAME} '${REMOTE_ENV_FILE}' && sudo chmod 0600 '${REMOTE_ENV_FILE}'"
  for service in "${SERVICES[@]}"; do
    trimmed="$(echo "${service}" | xargs)"
    if [[ -n "${trimmed}" ]]; then
      REMOTE_CMD="${REMOTE_CMD} && sudo systemctl restart '${trimmed}' && sudo systemctl --no-pager --full status '${trimmed}'"
    fi
  done
else
  REMOTE_CMD="sudo cp '${REMOTE_TMP}' '${REMOTE_ENV_FILE}' && sudo chown ${USER_NAME}:${USER_NAME} '${REMOTE_ENV_FILE}' && sudo chmod 0600 '${REMOTE_ENV_FILE}'"
fi

ssh -t "${USER_NAME}@${HOST}" "${REMOTE_CMD}"
