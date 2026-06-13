#!/usr/bin/env bash

set -euo pipefail

HOST="${ASWITCH_HOST:-aswitch.local}"
USER_NAME="${ASWITCH_USER:-pi}"
LOCAL_CONF="${ASWITCH_SHAIRPORT_CONF:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/shairport-sync.conf}"
REMOTE_TMP="/tmp/shairport-sync.conf"
REMOTE_CONF="${ASWITCH_SHAIRPORT_REMOTE_CONF:-/etc/shairport-sync.conf}"
SERVICE_NAME="${ASWITCH_SHAIRPORT_SERVICE:-shairport-sync}"

echo "Deploying ${LOCAL_CONF} to ${USER_NAME}@${HOST}:${REMOTE_CONF}"

scp "${LOCAL_CONF}" "${USER_NAME}@${HOST}:${REMOTE_TMP}"

ssh -t "${USER_NAME}@${HOST}" "
  sudo cp '${REMOTE_TMP}' '${REMOTE_CONF}' &&
  sudo chown root:root '${REMOTE_CONF}' &&
  sudo chmod 0644 '${REMOTE_CONF}' &&
  sudo systemctl restart '${SERVICE_NAME}' &&
  sudo systemctl --no-pager --full status '${SERVICE_NAME}'
"
