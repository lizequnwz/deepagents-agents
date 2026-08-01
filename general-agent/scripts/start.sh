#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "General Agent requires uv: https://docs.astral.sh/uv/" >&2
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
  "from general_agent.config import load_settings; s=load_settings(); assert not s.readiness_errors(); print('Configuration ready')"; then
  echo "General Agent configuration is invalid." >&2
  exit 1
fi

if [[ ! -w workspace || ! -w .data ]]; then
  echo "workspace/ and .data/ must be writable." >&2
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

.venv/bin/uvicorn general_agent.api:app \
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
  echo "The General Agent API did not become healthy." >&2
  exit 1
fi

echo "General Agent UI: http://${APP_HOST}:${APP_PORT}"
echo "General Agent API: http://${API_HOST}:${API_PORT}"

.venv/bin/streamlit run streamlit_app.py \
  --server.address "$APP_HOST" \
  --server.port "$APP_PORT" \
  --server.headless true
