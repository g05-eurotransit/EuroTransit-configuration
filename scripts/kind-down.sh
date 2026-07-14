#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_commands kind
kind delete cluster --name "$KIND_CLUSTER_NAME"
