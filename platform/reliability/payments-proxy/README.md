# Payments fault proxy

Build from the configuration root:

```bash
docker build -t eurotransit-payments-fault-proxy:local platform/reliability/payments-proxy
```

The Dockerfile pins Toxiproxy/Python base digests. The manual `Payments fault proxy image` workflow publishes the artifact without cluster credentials; use its digest in desired state. [Fault execution](../../../docs/operations/load-tests.md#fault-experiments) owns capacity, traffic routing, setup/teardown and audits.

The loopback lease API supports `POST /lease {"seconds":60}`, `DELETE /lease`, and `GET /lease`/`GET /health`. It does not expose the raw Toxiproxy admin API. Latency is fixed at 4000ms ±100ms downstream to real Payments. Renewal is rejected; leases are capped at 175s, reserving reset/scheduling margin within a 180s fault window. The in-container supervisor expires the fault independently of operator/client lifetime. On reset failure it terminates Toxiproxy and exits; Kubernetes restart reloads neutral configuration. Record such a restart as a recovery interruption, not uninterrupted availability. Prolonged pod/node failure remains a separate failure mode.
