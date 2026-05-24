#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Pull latest stable image, recreate container, then clean old dangling images.
docker compose pull
docker compose up -d
docker image prune -f
