#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

export CUT_HOST="${CUT_HOST:-0.0.0.0}"
export CUT_PORT="${CUT_PORT:-8080}"

exec python -m uvicorn app.main:app --host "$CUT_HOST" --port "$CUT_PORT"
