#!/usr/bin/env bash
# Source only the caller's local config; never echo credentials.
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi
export LANGSMITH_TRACING=false
