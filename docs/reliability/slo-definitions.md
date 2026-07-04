# SLO Definitions

Canonical checkout SLOs, SLIs, and error-budget semantics are defined in the sibling application repository at `../EuroTransit-application/docs/operations/slo-observability.md`.

This repository owns the Kubernetes/GitOps artifacts that make those SLOs observable and enforceable in the target environment. Do not duplicate application-level SLO decisions here unless the canonical source changes; map them to deployable configuration instead.

## Configuration Responsibilities

- Provision or reference Prometheus scrape configuration for gateway, Orders, Inventory, Payments, Kafka, and infrastructure metrics.
- Provide Grafana dashboard definitions or provisioning references for checkout latency, checkout success rate, RED metrics, USE/Golden Signals, Kafka lag, inventory correctness, and payment safety.
- Provide PrometheusRule or equivalent alert definitions for the symptom-based alerts defined by the application repository.
- Wire Alertmanager routing for the demo/proof environment.
- Preserve evidence links or screenshots after target-cluster validation.

## SLO-to-Artifact Map

| Canonical SLO / Signal | Configuration Artifact | Proof Expected |
| --- | --- | --- |
| Checkout success rate | PrometheusRule for burn-rate alerts; dashboard panel for successful confirmed checkouts / valid attempts | Alert fires under injected checkout failure and clears after recovery |
| Checkout latency | Dashboard panel and alert for p95 checkout latency | Trace and dashboard show where the order spent time |
| Checkout acceptance latency | Gateway and Orders RED panels | Fast acceptance remains visible during downstream degradation |
| Notification degradation | Dashboard/alert panel for checkout failures attributed to Notifications | Checkout remains successful while Notifications is down |

## Final Validation Gate

- The application SLO document and configuration alert/dashboard artifacts point to the same metric names before the demo.
- Alerts are tied to user-visible symptoms, not CPU or cause-only metrics.
- A release canary promotion/abort decision can be made from these dashboards and alerts.
