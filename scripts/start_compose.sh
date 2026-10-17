#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env.compose ]]; then .venv/bin/python scripts/configure_compose.py; fi
exec docker compose --env-file .env.compose up --build -d
