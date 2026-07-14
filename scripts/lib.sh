#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${EUROTRANSIT_APP_DIR:-$(cd "$ROOT_DIR/.." && pwd)/EuroTransit-application}"
KIND_CLUSTER_NAME="${KIND_CLUSTER_NAME:-eurotransit}"

require_commands() {
  local missing=0 command
  for command in "$@"; do
    if ! command -v "$command" >/dev/null 2>&1; then
      echo "Missing required command: $command" >&2
      missing=1
    fi
  done
  test "$missing" -eq 0
}

require_app_repo() {
  if [[ ! -f "$APP_DIR/settings.gradle.kts" ]]; then
    echo "EuroTransit-application not found at $APP_DIR" >&2
    echo "Set EUROTRANSIT_APP_DIR to its checkout path." >&2
    exit 1
  fi
}

wait_for_deployments() {
  local namespace="$1"
  kubectl -n "$namespace" wait deployment --all --for=condition=Available --timeout=8m
}
