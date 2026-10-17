#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/lib_env.sh
unset INSIGHTFLOW_ADMIN_DATABASE_URL INSIGHTFLOW_TEST_ADMIN_DATABASE_URL
unset DEEPSEEK_API_KEY INSIGHTFLOW_ENABLE_PAID_EVAL
export INSIGHTFLOW_MODE=mock
.venv/bin/python scripts/demo_mock.py
