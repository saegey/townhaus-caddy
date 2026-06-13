#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CONFIG_DIR="/srv/storage/frigate-config"
CONFIG_TEMPLATE="$ROOT_DIR/config/config.template.yml"
CONFIG_FILE="$CONFIG_DIR/config.yml"

mkdir -p "$CONFIG_DIR"

# Seed runtime config on first start only; never overwrite existing runtime config.
if [[ ! -f "$CONFIG_FILE" ]]; then
  cp "$CONFIG_TEMPLATE" "$CONFIG_FILE"
  echo "Seeded Frigate config at $CONFIG_FILE from template."
fi

docker compose up -d
