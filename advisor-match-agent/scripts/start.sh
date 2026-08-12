#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "Advisor Match requires uv: https://docs.astral.sh/uv/" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Missing .env. Copy .env.example to .env and configure MODEL_NAME." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8001}"
APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8502}"

uv sync --locked --all-groups

if ! .venv/bin/python -c \
  "from advisor_match.config import load_settings; s=load_settings(); assert not s.readiness_errors(); print('Configuration ready')"; then
  echo "Advisor Match configuration is invalid." >&2
  exit 1
fi

for port in "$API_PORT" "$APP_PORT"; do
  if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port $port is already in use." >&2
    exit 1
  fi
done

API_PID=""
cleanup() {
  if [[ -n "$API_PID" ]] && kill -0 "$API_PID" >/dev/null 2>&1; then
    kill "$API_PID" >/dev/null 2>&1 || true
    wait "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

.venv/bin/uvicorn advisor_match.api:app \
  --host "$API_HOST" \
  --port "$API_PORT" \
  --workers 1 &
API_PID=$!

READY=0
for _ in {1..60}; do
  if curl --fail --silent "http://${API_HOST}:${API_PORT}/health" >/dev/null; then
    READY=1
    break
  fi
  if ! kill -0 "$API_PID" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

if [[ "$READY" -ne 1 ]]; then
  echo "The Advisor Match API did not become healthy." >&2
  exit 1
fi

echo "Advisor Match UI: http://${APP_HOST}:${APP_PORT}"
echo "Advisor Match API: http://${API_HOST}:${API_PORT}"
echo "Advisor Match logs are written to stdout/stderr."

.venv/bin/streamlit run streamlit_app.py \
  --server.address "$APP_HOST" \
  --server.port "$APP_PORT" \
  --server.headless true
