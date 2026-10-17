#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
source .env
set +a
.venv/bin/python scripts/seed_data.py --initialize
