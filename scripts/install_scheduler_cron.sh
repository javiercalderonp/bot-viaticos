#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
CRON_EXPR="${CRON_EXPR:-*/5 * * * *}"
CRON_LOG_FILE="${CRON_LOG_FILE:-/tmp/mvp_biaticos_scheduler_cron.log}"
CRON_MARKER="# biaticos_scheduler_job"

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

url="$SCHEDULER_URL"
if [[ "$SCHEDULER_DRY_RUN" == "true" ]]; then
  separator="?"
  if [[ "$url" == *"?"* ]]; then
    separator="&"
  fi
  url="${url}${separator}dry_run=true"
fi

curl_args=(
  /usr/bin/curl
  --silent
  --show-error
  --fail
  --max-time "$SCHEDULER_TIMEOUT_SECONDS"
  -X POST "$url"
)
if [[ -n "$SCHEDULER_ENDPOINT_TOKEN" ]]; then
  curl_args+=(-H "X-Scheduler-Token: $SCHEDULER_ENDPOINT_TOKEN")
fi

mkdir -p "$(dirname "$CRON_LOG_FILE")"

existing_cron="$(crontab -l 2>/dev/null || true)"

escaped_curl_cmd="$(printf '%q ' "${curl_args[@]}")"
escaped_log_file="$(printf '%q' "$CRON_LOG_FILE")"
CRON_CMD="${escaped_curl_cmd}>> ${escaped_log_file} 2>&1"
CRON_LINE="$CRON_EXPR $CRON_CMD $CRON_MARKER"
without_legacy="$(printf '%s\n' "$existing_cron" | grep -v "scripts/run_scheduler_job.sh" || true)"
without_marker="$(printf '%s\n' "$without_legacy" | grep -v "biaticos_scheduler_job" || true)"

if printf '%s\n' "$existing_cron" | grep -F "biaticos_scheduler_job" >/dev/null 2>&1; then
  echo "Cron ya existe:"
  echo "Se actualizará con la configuración actual."
fi

{
  printf '%s\n' "$without_marker"
  printf '%s\n' "$CRON_LINE"
} | crontab -

echo "Cron instalado:"
echo "$CRON_LINE"
