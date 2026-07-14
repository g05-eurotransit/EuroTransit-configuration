#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"
kubectl config use-context "kind-$KIND_CLUSTER_NAME" >/dev/null
kubectl get pods -A
kubectl -n eurotransit get cluster,kafka,deploy,svc,ingressroute
kubectl get events -A --sort-by=.lastTimestamp | tail -n 30
