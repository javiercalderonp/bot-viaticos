#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

SCHEDULER_URL="${SCHEDULER_URL:-http://127.0.0.1:8000/jobs/reminders/run}"
SCHEDULER_ENDPOINT_TOKEN="${SCHEDULER_ENDPOINT_TOKEN:-}"
SCHEDULER_TIMEOUT_SECONDS="${SCHEDULER_TIMEOUT_SECONDS:-20}"
SCHEDULER_DRY_RUN="${SCHEDULER_DRY_RUN:-false}"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/logs}"

mkdir -p "$LOG_DIR"
timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

url="$SCHEDULER_URL"
if [[ "$SCHEDULER_DRY_RUN" == "true" ]]; then
  separator="?"
  if [[ "$url" == *"?"* ]]; then
    separator="&"
  fi
  url="${url}${separator}dry_run=true"
fi

curl_args=(
  --silent
  --show-error
  --fail
  --max-time "$SCHEDULER_TIMEOUT_SECONDS"
  -X POST "$url"
)

if [[ -n "$SCHEDULER_ENDPOINT_TOKEN" ]]; then
  curl_args+=(-H "X-Scheduler-Token: $SCHEDULER_ENDPOINT_TOKEN")
fi

response="$(curl "${curl_args[@]}")"
echo "[$timestamp] scheduler run ok: $response"
