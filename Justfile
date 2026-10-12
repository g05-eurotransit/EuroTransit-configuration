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

# Direct harness entrypoint; use the operator launcher for AKS preflight and claims.
load-checkout:
    python3 load-tests/run.py

load-checkout-verify ledger evidence output:
    python3 load-tests/verify.py --ledger '{{ledger}}' --evidence '{{evidence}}' --output '{{output}}'

load-checkout-unit:
    node --test load-tests/tests/*.test.mjs
    python3 -m unittest discover -s load-tests/tests -p 'test_*.py'
