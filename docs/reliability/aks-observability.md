# Observability verification

## Observed evidence

Prometheus scraped terminal checkout counters, failure reasons, stage and
acceptance-to-terminal histograms, HTTP acceptance counters, breaker states and
per-partition Spring Kafka client lag. The updated collector obtained all of its
required metric families for the Kafka final audit: status COLLECTED, no missing
series. This is telemetry coverage, not a 30-day SLO verdict or exclusive run
attribution.

The real `ReconciliationRecordOpen` alert had firing samples at **22:00:30,
22:01:00 and 22:01:30 UTC**, following the Payments experiment's pending work and
exhausted delivery. Its pending/firing time series and evaluated rule definitions
were collected from Prometheus. This establishes one symptom alert under an
injected failure; no synthetic alert or reduced threshold was used. Later
snapshots were inactive after recovery. Alert delivery to a human recipient was
not exercised.

## Gaps found before the final demonstration

| Area | Finding | Required follow-up |
| --- | --- | --- |
| Dashboard/alert/gate selectors | Live samples carry `application`, but lack the `app` label used by several configuration queries. | Proposed ServiceMonitor `targetLabels: [app]`; verify actual samples and queries after GitOps reconciliation. |
| Success SLO | Current fast-burn expression uses HTTP 5xx across Orders requests, while the canonical SLO concerns confirmed valid checkout attempts. | Team must settle valid-attempt exclusions and align the terminal-outcome denominator, including pending work and gateway rejections. |
| Latency SLO | Current latency alert uses HTTP endpoint duration, while the canonical 2s target concerns asynchronous acceptance-to-terminal duration. | Map the alert/dashboard to the existing end-to-end histogram after team review. |
| Kafka lag | Client lag is available; no broker committed-offset exporter is installed. | Collector fallback records its source; add exporter coverage if stopped groups must remain measurable. |
| Tracing | Trace IDs exist in application logs; OTLP export is disabled and no OTEL Collector/trace backend Service exists in monitoring. | Deploy reviewed tracing infrastructure, enable export, then demonstrate queryable cross-service/Kafka spans for a real order. |
| Alert coverage | Fast burn, latency, pipeline and reconciliation groups are loaded; several documented alerts are absent or use selectors without samples. | Align canonical SLO mapping and validate each intended rule with real series and controlled symptoms. |

The canonical SLO decisions remain in the application repository's
`docs/operations/slo-observability.md`. Its statement that Orders Prometheus
scraping is blocked is outdated relative to the live evidence above; the team
should update it alongside the final SLO mapping. Targets and error budgets are
not redefined by this report.

## Evidence

Restricted Prometheus rule snapshots, historical ALERTS series and platform
service inventory: `.resilience-evidence/chaos-20261012/observability`.
Kafka telemetry: `load-results/kafka-disruption-20261012T222044Z-final-audit-20261012T222233Z/telemetry.json`.
Proposed collector, scrape-label and rollout-schema fixes are on the separate
local branch `fix/reliability-proof-prerequisites`. A green render or strict
server dry-run is not live SLO or tracing proof.
