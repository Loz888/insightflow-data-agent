#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/lib_env.sh
.venv/bin/python scripts/seed_data.py --initialize
