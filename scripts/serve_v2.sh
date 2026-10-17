#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python -m uvicorn insightflow.v2.api:app --host 127.0.0.1 --port "${INSIGHTFLOW_PORT:-8000}" --no-access-log
