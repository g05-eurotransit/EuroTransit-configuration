# Observability Platform

This document owns the platform-side observability stack.

## Required Coverage

- RED metrics for application services.
- USE metrics for infrastructure.
- Checkout latency and success-rate dashboards.
- Symptom-based alerts tied to SLOs.
- Distributed tracing for the money path.

Service instrumentation conventions are coordinated with the application repository; dashboards, alert rules, and platform deployment live here.

## Current Manifests

- kube-prometheus-stack values live in `platform/kube-prometheus-stack/values.yaml`.
- Checkout symptom alerts live in `platform/kube-prometheus-stack/prometheus-rules.yaml`.
- Application ServiceMonitors are rendered from `charts/eurotransit/templates/servicemonitors.yaml`.
- Orders, Inventory and Payments outbox relays live in `platform/connectors`;
  their `KafkaConnect` and `KafkaConnector` status exposes worker, connector,
  task, and automatic-restart health through Strimzi.
- Chaos Mesh installation values live in `platform/chaos-mesh/values.yaml`; experiment manifests are still pending.

## Money-Path Proof Checklist

- Public Orders route rejects unauthenticated checkout.
- Catalog route is reachable according to the selected public/auth policy.
- Inventory and Payments have no public ingress.
- A checkout flow carries one `X-Correlation-Id` through Orders, Inventory, Payments, Kafka events, and Notifications where applicable.
- Duplicate order placement with the same idempotency key does not create a second logical order.
- Inventory idempotency retention is configured for 30 minutes while seat holds still expire after 10 minutes.
- Orders and Payments idempotency retention are configured for 24 hours.
- Payment sandbox credentials are loaded from Kubernetes secret material, not source code.
- Notifications outage does not fail an already confirmed checkout.
