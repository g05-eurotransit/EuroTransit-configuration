#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"
kubectl config use-context "kind-$KIND_CLUSTER_NAME" >/dev/null
kubectl get events -A --sort-by=.lastTimestamp
for namespace in eurotransit keycloak traefik; do
  kubectl -n "$namespace" logs --all-containers --prefix --tail=100 -l app.kubernetes.io/part-of=eurotransit-marketplace || true
done
