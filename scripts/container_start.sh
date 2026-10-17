#!/bin/sh
set -eu
python scripts/migrate_v2.py --seed-empty
unset INSIGHTFLOW_ADMIN_DATABASE_URL INSIGHTFLOW_TEST_ADMIN_DATABASE_URL
exec python -m uvicorn insightflow.v2.api:app --host 0.0.0.0 --port 8000 --no-access-log
