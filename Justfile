set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

kind-up:
    ./scripts/kind-up.sh

kind-up-observability:
    ENABLE_OBSERVABILITY=1 ./scripts/kind-up.sh

kind-test:
    ./scripts/kind-test.sh

kind-status:
    ./scripts/kind-status.sh

kind-logs:
    ./scripts/kind-logs.sh

kind-down:
    ./scripts/kind-down.sh

render-kind:
    ./scripts/render.sh kind

render-aks:
    ./scripts/render.sh aks
