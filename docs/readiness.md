# Delivery readiness

Kind has bounded evidence for HA worker loss, shutdown, admission refusal and progressive-delivery controllers. AKS remains a constrained single-instance environment. The repository does not yet demonstrate a complete production release: Kubernetes tracing and an immutable application release through CI and Argo CD remain open, and the asynchronous checkout SLO mapping is defined but not yet observed on a cluster.

This is the configuration acceptance record. The [application DoD](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/capstone-dod.md) owns project criteria; [verification results](verification/README.md) own experiment outcomes. A completed experiment with transient errors remains valid evidence of its measured impact and recovery.

## Evidence and remaining work

| Area | Available evidence | Remaining acceptance work |
| --- | --- | --- |
| Runtime manifests | Kind, Kind HA and AKS profiles; frontend, service routes, identity, databases, Kafka, connectors, monitoring and rollout resources | Verify the selected revision on its actual target; rendered resources alone do not establish health |
| Checkout resilience | Inventory automatic recovery, Kafka healing, isolated Notifications pause, Payments latency, graceful shutdown and controlled 429 recovery | Assess coverage against the application DoD; no additional fault family is introduced by this checklist |
| Node / primary loss | [Kind HA](verification/kind/ha-failover.md) records promotion, synchronous quorum, financial convergence and transient client impact; AKS drain records its capacity failure | Keep measured recovery separate from RTO/SLO compliance, which the report did not assess; review the applicable team-owned objective if claiming compliance |
| Progressive delivery | [Orders](verification/kind/progressive-delivery.md#orders-canary) weights, ordinary gates and automatic abort; [Catalog](verification/kind/progressive-delivery.md#catalog-bluegreen) preview, promotion and rollback | Demonstrate CI publication of a different immutable application version, configuration-repository update and Argo reconciliation; local configuration-only rollouts do not prove this path |
| Financial evidence | Independent run-scoped audits; canary 25% follow-up verified after zero-effect declined-attempt classification | Canary 50% has manual acceptance of an extra shared-sandbox payment; retain the original automatic NOT_VERIFIED result |
| Monitoring | Dashboards/rules exist; ServiceMonitor labels corrected in Kind; committed-offset lag measured; AKS reconciliation alert fired; checkout SLO panels and burn-rate/latency alerts use terminal outcomes and the end-to-end histogram, with rule logic unit-tested by promtool | Observe the checkout SLO panels and alerts on the selected environment |
| Tracing | Instrumentation and configured OTLP address exist | Deploy collector/backend, enable export and inspect a real gateway-to-Kafka trace |
| Gateway / security | JWT checks in services; Inventory and Payments lack public routes; sealed-secret workflow documented | Forward-auth stays disabled, an accepted gap for delivery recorded in the [application DoD](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/capstone-dod.md#remaining-acceptance-work). Review least-privilege runtime/experiment identities and credential history |
| Capacity | Kind HA uses separated replicas; AKS resource budgets are constrained | Preserve failed-node headroom on any target claiming HA. Standard Kind PDB values mismatch remains documented in deployment |
| Final delivery | [Postmortem](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/operations/payments-latency-postmortem.md), agent cases, threat model and demo storyboard exist | Team reviews the postmortem and the final DoD; attach the recorded demo and presentation material |

## Target deployment checks

Before reconciling AKS, follow [production setup](operations/aks.md): confirm DNS/TLS inputs, immutable ACR images and pull access, the controller-specific eleven-secret inventory, and the read-only private-repository credential. Controller/key bootstrap is cluster-admin-owned. Existing ciphertext must validate against the target controller; its presence in Git alone is insufficient.

After sync, verify Argo applications Healthy/Synced, no Pending/CrashLoopBackOff/OOMKilled workloads, measured node headroom, certificate Ready, exact OIDC issuer, public/protected/internal routing, PostgreSQL/Kafka/CDC health and real monitoring samples. Record the revision and rollback result. Use [deployment](platform/deployment.md) for environment differences and [GitOps topology](platform/gitops.md) for resource ownership.

Kind controller evidence does not establish AKS rollout execution, cross-host/AZ tolerance, uninterrupted checkout or a long-window availability result. No numeric recovery target is adopted by this document.
