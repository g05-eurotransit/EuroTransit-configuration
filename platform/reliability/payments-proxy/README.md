# Payments latency and Inventory disruption

Issue #47 prepares equivalent fault tooling for the fixed-capacity AKS cluster; it does not install Chaos Mesh. Hypotheses, checkout SLOs and acceptable recovery times remain team decisions. Never fill experiment reports with expected results.

## Image and preparation

Build `docker build -t eurotransit-payments-fault-proxy:local platform/reliability/payments-proxy`.
The Dockerfile pins verified official Toxiproxy 2.12.0 and Python base digests. Publish with the manual `Payments fault proxy image` workflow, configured with `ACR_REGISTRY`, `ACR_USERNAME`, and `ACR_PASSWORD`. This CI has no cluster credentials. Use its reported digest in desired state; local build is not proof that AKS can pull it.

The opt-in Helm overlay is `values.yaml` here. Supply the derivative image digest. Preparation and teardown require distinct GitOps reconciliations:

1. Set `enabled=true, routeOrders=false`. Check capacity including 64Mi proxy and the additional Orders pod needed during rolling update; check startup and proxy Ready.
2. Set `routeOrders=true`. Wait for Argo Synced/Healthy and the Orders rollout. Run a neutral baseline through the proxy, requiring CONFIRMED orders and healthy Catalog.
3. Run one latency lease. Delete the lease after observations. Save recovery, including any DELIVERY_EXHAUSTED incidents and explicit operator redrive; automatic convergence is not guaranteed.
4. Set `routeOrders=false`, keep `enabled=true`. Wait for healthy direct Orders rollout and another successful checkout.
5. Set `enabled=false` and reconcile to prune the proxy. Never delete the proxy while Orders points at it.

Default chart rendering remains unchanged. The proxy uses 32Mi requested/64Mi limited, CPU25m/100m, no Kubernetes token, no privileged network access, and no public/admin Service. The lease API binds localhost inside the pod. Use `kubectl --context CONTEXT -n eurotransit port-forward --address 127.0.0.1 deployment/payments-fault-proxy 18474:8474`.

## Fault execution

First run #46's capacity/readiness preflight and collector. A fresh preflight must identify the same context, namespace and run. `scripts/reliability/fault.py` defaults to dry-run; `--execute` explicitly enables a mutation.

Example (after the neutral baseline, with the run already created by #46):

```bash
python3 scripts/reliability-runner.py preflight --context eurotransit --mode workstation --run-id "$RUN_ID" --extra-memory-mib 576 > "$OUTPUT_DIR/preflight.json"
python3 scripts/reliability/fault.py payments-latency --context eurotransit --run-id "$RUN_ID" --output-dir "$OUTPUT_DIR" --preflight "$OUTPUT_DIR/preflight.json" --seconds 60 --execute
python3 scripts/reliability/fault.py payments-reset --context eurotransit --run-id "$RUN_ID" --output-dir "$OUTPUT_DIR" --preflight "$OUTPUT_DIR/preflight.json" --execute
```

Reset deliberately remains available if a later capacity/preflight check fails. The fresh preflight run ID must match, and latency preparation reserves 576Mi for the proxy plus Orders rollout. Each fault is recorded before mutation; an ambiguous attempt must be investigated rather than blindly repeated. A separate run is required for each experiment.

The loopback lease API supports `POST /lease {"seconds":60}`, `DELETE /lease`, and `GET /lease`/`GET /health`. It does not expose the raw Toxiproxy admin API. Latency is fixed at 4000ms ±100ms downstream to real Payments. Renewal is rejected; leases are capped at 175s, reserving reset/scheduling margin within a 180s fault window. The in-container supervisor expires the fault independently of operator/client lifetime. On reset failure it terminates Toxiproxy and exits; Kubernetes restart reloads neutral configuration. Record such a restart as a recovery interruption, not uninterrupted availability. Prolonged pod/node failure remains a separate failure mode.

Payments breaker needs at least five actual calls within 20s (failure/slow threshold50%, open10s, half-open3). Traffic too low makes the experiment inconclusive. Capture Catalog simultaneously. Timeout3s, at most three remote attempts, and Kafka's bounded redelivery may result in persistent reconciliation incidents.

Inventory command selects exactly one Ready pod, records its UID and deletes using an API UID precondition. This is a single forced pod kill (`gracePeriodSeconds: 0`), not graceful shutdown or a disruption scheduler. The UID precondition limits it to the selected original pod. Wait for its replacement and collect evidence. A kill under contended traffic is not proof of killing mid-reservation: require temporal overlap from actual traces/logs before claiming that stronger result.

After collection, `scripts/reliability/replay-events.py` replays only original exported `order-placed` payloads, scoped to the run by the collector; at most20. Use the existing broker producer tool, explicitly choosing the verified broker pod. It defaults to no publication, saves hashes/source ids, and never writes SQL or fabricates payloads. Retry HTTP separately using the original idempotency keys. Event replay and HTTP retry demonstrate different invariants.

Read-only audit must check active/confirmed reservation uniqueness per order and seat/date, consistency between confirmed orders and seats, and payment authorization uniqueness for run orders. Provider-reference hashes are useful for correlating effects; application DB rows alone cannot prove that Stripe did not double-charge. Link sandbox provider audit evidence before claiming that result.

At current memory saturation, fault execution is blocked. Do not add nodes/memory or silently scale down unrelated workloads. A failed capacity gate is a recorded prerequisite failure, not an experiment result.
