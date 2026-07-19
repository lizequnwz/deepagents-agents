#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
STREAMLIT_HOST="${STREAMLIT_HOST:-127.0.0.1}"
STREAMLIT_PORT="${STREAMLIT_PORT:-8501}"
API_PID=""
STREAMLIT_PID=""

cleanup() {
  status="$1"
  trap - EXIT INT TERM

  if [[ -n "${STREAMLIT_PID}" ]] && kill -0 "${STREAMLIT_PID}" 2>/dev/null; then
    kill "${STREAMLIT_PID}" 2>/dev/null || true
  fi
  if [[ -n "${API_PID}" ]] && kill -0 "${API_PID}" 2>/dev/null; then
    kill "${API_PID}" 2>/dev/null || true
  fi

  [[ -z "${STREAMLIT_PID}" ]] || wait "${STREAMLIT_PID}" 2>/dev/null || true
  [[ -z "${API_PID}" ]] || wait "${API_PID}" 2>/dev/null || true

  if [[ "${status}" -eq 0 ]]; then
    echo
    echo "Data Analytics Agent stopped."
  fi
  exit "${status}"
}

trap 'cleanup $?' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

wait_for_service() {
  label="$1"
  url="$2"
  pid="$3"
  attempt=1

  while [[ "${attempt}" -le 60 ]]; do
    if ! kill -0 "${pid}" 2>/dev/null; then
      echo "${label} exited before becoming ready." >&2
      return 1
    fi
    if curl --fail --silent --show-error "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
    attempt=$((attempt + 1))
  done

  echo "Timed out waiting for ${label} at ${url}." >&2
  return 1
}

port_is_open() {
  host="$1"
  port="$2"
  uv run python -c \
    "import socket; s=socket.socket(); s.settimeout(0.2); raise SystemExit(0 if s.connect_ex(('${host}', ${port})) == 0 else 1)"
}

cd "${PROJECT_ROOT}"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it from https://docs.astral.sh/uv/." >&2
  exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required for local service health checks." >&2
  exit 1
fi
if [[ ! -f ".env" ]]; then
  echo ".env is missing. Copy .env.example to .env and add OPENAI_API_KEY." >&2
  exit 1
fi

echo "Preparing the locked Python environment…"
uv sync --locked

if ! uv run python -c \
  'from data_analytics_agent.api import Services; services = Services(); errors = services.settings.readiness_errors(); summaries = services.source_summaries() if not errors else []; errors += ([] if any(item.ready for item in summaries) else ["No configured data source is ready."]); print("\n".join(f"  - {error}" for error in errors)); raise SystemExit(1 if errors else 0)'
then
  echo "Startup checks failed. Resolve the items above and try again." >&2
  exit 1
fi

if port_is_open "${API_HOST}" "${API_PORT}"; then
  echo "Port ${API_PORT} is already in use on ${API_HOST}." >&2
  exit 1
fi
if port_is_open "${STREAMLIT_HOST}" "${STREAMLIT_PORT}"; then
  echo "Port ${STREAMLIT_PORT} is already in use on ${STREAMLIT_HOST}." >&2
  exit 1
fi

export API_BASE_URL="${API_BASE_URL:-http://${API_HOST}:${API_PORT}}"
export APP_BASE_URL="${APP_BASE_URL:-http://${STREAMLIT_HOST}:${STREAMLIT_PORT}}"
export PYTHONUNBUFFERED=1

echo "Starting FastAPI at ${API_BASE_URL}…"
uv run uvicorn data_analytics_agent.api:app \
  --host "${API_HOST}" \
  --port "${API_PORT}" &
API_PID="$!"
wait_for_service "FastAPI" "${API_BASE_URL}/health" "${API_PID}"

echo "Starting Streamlit at ${APP_BASE_URL}…"
uv run streamlit run streamlit_app.py \
  --server.address="${STREAMLIT_HOST}" \
  --server.port="${STREAMLIT_PORT}" &
STREAMLIT_PID="$!"
wait_for_service \
  "Streamlit" \
  "${APP_BASE_URL}/_stcore/health" \
  "${STREAMLIT_PID}"

echo
echo "Data Analytics Agent is ready:"
echo "  App: ${APP_BASE_URL}"
echo "  API: ${API_BASE_URL}"
echo
echo "Press Ctrl+C to stop both services."

while kill -0 "${API_PID}" 2>/dev/null \
  && kill -0 "${STREAMLIT_PID}" 2>/dev/null
do
  sleep 1
done

if ! kill -0 "${API_PID}" 2>/dev/null; then
  echo "FastAPI stopped unexpectedly." >&2
else
  echo "Streamlit stopped unexpectedly." >&2
fi
exit 1
