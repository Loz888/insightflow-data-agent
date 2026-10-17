#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/lib_env.sh
unset INSIGHTFLOW_ADMIN_DATABASE_URL INSIGHTFLOW_TEST_ADMIN_DATABASE_URL
if [[ "${INSIGHTFLOW_ENABLE_PAID_EVAL:-0}" != 1 || "${INSIGHTFLOW_ENABLE_LIVE:-false}" != true ]]; then
  echo 'NOT RUN: real model disabled; explicitly enable and configure key, conservative prices and budgets.'
  exit 0
fi
if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  echo 'NOT RUN: DEEPSEEK_API_KEY not configured.'
  exit 0
fi
export INSIGHTFLOW_MODE=deepseek
.venv/bin/python - <<'PY'
from insightflow.agent.service import AgentService
from insightflow.config import Settings
import json
service=AgentService(Settings())
try:
    result=service.run("2026年9月已支付销售收入是多少？","live-demo")
    print(json.dumps({"answer":result["final_answer"],"error":result["error"],"usage":result["usage"]},ensure_ascii=False))
    if result["error"]:raise SystemExit(1)
finally:service.close()
PY
