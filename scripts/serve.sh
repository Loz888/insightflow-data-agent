#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/lib_env.sh
unset INSIGHTFLOW_ADMIN_DATABASE_URL INSIGHTFLOW_TEST_ADMIN_DATABASE_URL
exec .venv/bin/python -m uvicorn insightflow.api.app:app --host 127.0.0.1 --port 8000
