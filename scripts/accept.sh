#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/lib_env.sh
unset DEEPSEEK_API_KEY
# Python owns a previously absent child directory under a fresh external container.
umask 077
base_dir="${INSIGHTFLOW_REPORT_BASE:-${XDG_STATE_HOME:-$HOME/.local/state}/insightflow/acceptance}"
mkdir -p "$base_dir"
base="$(mktemp -d "$base_dir/run.XXXXXX")"
echo "Acceptance output: $base/report"
exec .venv/bin/python scripts/accept.py --output "$base/report"
