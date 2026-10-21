# Kind observability verification

## Measured availability of signals

This check reads actual Prometheus results and workload configuration, rather
than inferring observability from rendered manifests. It runs separately from
the team's SLO decisions. Positive canary analysis provides additional real
query/decision evidence in the progressive-delivery report.

At 21:23 UTC the cluster exposed checkout terminal counters, the accepted-to-
terminal histogram, nonterminal-age and reconciliation gauges, and Spring Kafka
consumer fetch-lag series. The five application ServiceMonitors now retain the
Service `app` label, and Catalog/Orders retain the rollout hash. The pinned
Prometheus reloader checks configuration every three minutes by default;
ServiceMonitor changes must actually appear in loaded configuration and samples
before evaluating a gate.

Committed-offset `kafka_consumergroup_lag` was absent in this initial snapshot.
Spring fetch-position lag is available but does not replace committed offsets
or cover a stopped consumer. A Kind-only Strimzi Kafka Exporter and PodMonitor
were subsequently activated and verified. Six real lag series cover the six
populated Orders/Notifications partitions. The [bounded Notifications
pause](notifications-lag.md) observed total committed lag
0 → 2 → 0 in both the exporter and Prometheus, while two checkouts confirmed.
The three Kafka brokers retained their UIDs and restart counts. This closes the
missing committed-lag signal in this Kind profile; it does not claim a new Kafka
partition experiment or automatically deploy the exporter on AKS.

## SLO mapping gaps

The canonical targets remain in application
[checkout SLO specification](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/design/slo.md); this experiment does not redefine them.

| Existing artifact | Finding | Required correction |
| --- | --- | --- |
| Checkout dashboard success panel / `CheckoutFastBurn` | Uses Orders HTTP 5xx ratio, including reads; HTTP 202 can succeed while the later checkout fails or stalls | Map to the team's valid-attempt/confirmed-checkout definition, with explicit pending and ingress-refusal semantics |
| Checkout dashboard p95 / `CheckoutLatencyHigh` | Uses HTTP request duration across Orders APIs, including polling; omits queueing and asynchronous completion | Use the actual end-to-end checkout histogram with the canonical outcome/population definition |
| Acceptance p99 panel | Selects POST duration rather than end-to-end duration | Keep as the separately named acceptance SLI; verify gateway coverage too |
| Reconciliation/age alerts | Durable gauges are present | Preserve the previous alert-firing evidence; check deployed thresholds against the team's adopted recovery objectives |

The distinction is visible in real samples: the 21:23 observation measured
successful end-to-end p95 around 1.8 seconds versus Orders HTTP p95 around
8 ms. These are distinct measurements, not interchangeable SLOs. A short
healthy interval cannot establish 30-day compliance, and a missing or empty
series is not zero errors. During progressive delivery, duplicate scrape paths
also require per-instance counter deduplication, as already done by the canary
gates.

**Follow-up correction (2026-10-20).** The checkout dashboard, `CheckoutFastBurn`,
the new `CheckoutSlowBurn` and `CheckoutLatencyHigh` now use terminal outcomes and
`orders_checkout_e2e_duration_seconds`, with the valid-attempt population defined in
the application SLO specification; the [alert policy](../../platform/observability.md#checkout-slo-alert-policy)
lists the thresholds. The findings above remain the record of this Kind run.

| Check | Result |
| --- | --- |
| promtool unit tests (six cases) | Pass: business refusals burn no budget; 50% system failures fire both burn alerts; 1% stays quiet; one pod scraped through two Services counts once; 20% of confirmed checkouts over 2 s fire the latency alert, 2% do not |
| Negative control | Summing instead of deduplicating per instance makes the two-Service case fire |
| Compose samples (`main` at `53ef866`, provider replaced locally by `stripe-mock`) | 43 checkouts: 40 `confirmed`, 3 `seats_unavailable`. Success SLI 100% (refusals excluded; 93% if counted). Real label shapes match the queries, including `le="2.0"` and `reason` |
| Latency on the same samples | First 20 checkouts after a cold start: 7.5 s mean, none within 2 s. Next 20: all within 1.43 s. End-to-end p95 9.2 s while the old HTTP p95 query returned 0.61 s; the latency rule expression evaluated true |
| Old success panel | Returned no data: with no 5xx series, the HTTP ratio is empty |

The rules were evaluated as queries on compose, which loads no rule files; firing on
Kind or AKS is not demonstrated by this follow-up.

## Distributed tracing

All five workload templates declare `MANAGEMENT_TRACING_EXPORT_OTLP_ENABLED=false`
and point to `otel-collector.monitoring.svc.cluster.local:4318/v1/traces`.
No collector, Tempo, Jaeger or Zipkin Service exists in this Kind cluster.
**A queryable gateway-to-Kafka trace is therefore not demonstrated here.**
Trace IDs in logs are not a substitute for an exported trace tree. Existing
compose evidence in the application documentation has its own scope; it must
not be relabelled as Kubernetes tracing evidence.

## Evidence and ownership

Private real query results and selected, non-secret environment fields are in
the progressive run's `observability-before-exporter.json`. The
[sanitized observation](../evidence/2026-10-17/observability-verification.json)
includes the initial queries and subsequent exporter verification. Team owners must
review the SLO denominator/outcome semantics and tracing deployment; the agent
has not marked those judgments or the final DoD as approved.
