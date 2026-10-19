# Testing and tooling

EuroTransit verification combines checks of the deployment tooling, bounded traffic against Kind or AKS, controlled faults, and audits of the resulting orders, seats and payments. Each experiment records its environment, revisions, client outcomes, recovery and evidence limits. The [verification index](README.md) contains the executed results; this page explains how to follow and reproduce the work.

## From a test run to a verdict

[![Checkout testing and evidence workflow](../diagrams/testing/testing-tooling.svg)](https://g05-eurotransit.github.io/EuroTransit-configuration/testing/testing-tooling.html)

The diagram follows the checkout harness. HA, shutdown, notification and delivery experiments use their own runbooks and collectors, linked below. Fault injection is an optional operator action during a bounded workload; it is not performed automatically by k6 or CI.

1. Select the environment, scenario, source revisions and immutable images. Allocate unused route/date/seat fixtures and a run ID. Declare the expected behavior using the application [fault hypotheses](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/verification/strategy.md) and [SLO definitions](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/design/slo.md).
2. Run the capacity and readiness preflight. The operational runner checks fixture availability and coordinates fixture claims and the run lock. A blocked prerequisite prevents execution; it is recorded separately from an experiment result.
3. Run bounded k6 traffic from a workstation container or an admitted Kubernetes Job. For a fault experiment, follow the selected runbook to inject the fault, observe its impact and restore the dependency. Record operator recovery when automatic recovery does not complete.
4. Collect the client ledger, pod/image snapshots, durable order/reservation/payment state and available telemetry. The checkout collector uses read-only SQL scoped to the run's order IDs and fixtures. Missing telemetry stays explicitly incomplete.
5. Independently enumerate Stripe sandbox effects for the run window. The audit reads the first collection's run metadata and payment-reference hashes, then queries Stripe. Collect again with `--provider-evidence` to merge the audit into sanitized evidence.
6. Run the correctness verifier and write the scenario report. Retain both the original client verdict and any later recovery audit. Link sanitized artifacts and state the scope of each conclusion.

Exact commands, credentials, capacity bounds and cleanup are maintained in the [load-test procedure](../operations/load-tests.md). The [harness contract](../../load-tests/README.md) defines fixtures, scenarios, output fields and verification rules.

## Tools and responsibilities

| Tool or entry point | Role | Output or check |
| --- | --- | --- |
| [Kind setup and smoke scripts](../operations/kind.md), Docker, Kind, kubectl, Helm and Just | Build/load local images, render and deploy the selected profile, check the marketplace | Workload readiness, gateway/authentication checks and connector health; HA experiments remain separate |
| [GitOps procedure](../operations/gitops.md), Argo CD and [progressive delivery](../operations/progressive-delivery.md) | Reconcile reviewed manifests and exercise rollout controllers | Sync/health observations, canary or blue/green promotion/abort evidence |
| [Operational runner](../../scripts/reliability-runner.py), Python and kubectl | Preflight, fixture ownership, workstation/Job launch, collection | `preflight.json`, `run.json`, pod snapshots, `orders.jsonl`, `summary.json`, `evidence.json` |
| [Checkout harness](../../load-tests/README.md), k6 and its Python wrapper | Generate bounded requests and poll accepted orders | Per-attempt HTTP outcomes, acceptance latency and poll-observed confirmation time |
| [Fault executor](../../scripts/reliability/fault.py), optional [Payments proxy](../../platform/reliability/payments-proxy/README.md) and scenario scripts | Apply the selected fault and record restoration | Fault identity, duration, target and recovery observations; explicit execution required |
| [Provider audit](../../scripts/reliability/provider-audit.py) | Read the independent Stripe sandbox charge window | Restricted `provider-audit.json`, coverage and attribution checks |
| [Correctness verifier](../../load-tests/verify.py) | Compare the ledger with durable state and independent provider evidence | `verification.json`: `VERIFIED` or `NOT_VERIFIED`, with violations |
| [Prometheus and Grafana](../platform/observability.md), logs and Kafka lag | Measure symptoms and recovery over the run window | Counters, duration buckets, alerts and committed lag where available; report tracing gaps |

The workstation runs the containerized harness outside the target cluster. The optional Job requires its own capacity admission. Operator collection permissions, including PostgreSQL pod exec, are separate from the runner Job, which has no Kubernetes service-account token. Credentials enter through the documented environment/Secret mechanisms; restricted canonical events and raw provider references stay outside Git.

## Which procedure explains each experiment?

| Test family | Method and tooling | Recorded results |
| --- | --- | --- |
| Baseline, seat contention, HTTP request replay, ramp/spike | [k6 scenarios and assertions](../../load-tests/README.md), [execution and audit](../operations/load-tests.md) | [AKS checkout](aks/checkout.md) |
| Payments latency, Inventory kill, Kafka interruption, Notifications pause and event replay | [Fault execution and replay](../operations/load-tests.md#fault-execution), environment-specific methods in the reports | [AKS dependencies](aks/dependencies.md), [Kind notification lag](kind/notifications-lag.md), [Payments recovery incident](incidents/payments-recovery.md) |
| Worker loss and PostgreSQL primary failover | [HA procedure](../operations/ha-experiment.md), scenario collector and financial audit | [Kind HA](kind/ha-failover.md), [AKS recovery](aks/recovery.md) |
| Orders shutdown and drain | Shutdown method, workload and timeline in each environment's report | [Kind shutdown](kind/orders-shutdown.md), [AKS recovery](aks/recovery.md) |
| Checkout admission and recovery after refusal | [Load-shedding procedure](../operations/load-shedding.md) | [Kind load shedding](kind/checkout-load-shedding.md) |
| Orders canary and Catalog blue/green | [Progressive-delivery procedure](../operations/progressive-delivery.md), rollout controller and provider audit | [Kind delivery](kind/progressive-delivery.md) |
| Monitoring, alert injection and CDC recovery | [Observability wiring](../platform/observability.md), [CDC reference](../platform/cdc.md), report-specific queries and recovery steps | [Kind monitoring](kind/observability.md), [AKS monitoring](aks/observability.md), [CDC slots incident](incidents/cdc-slots.md) |

Application unit/integration tests, service behavior and local regression evidence live in the [application verification documentation](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/verification/README.md). Configuration owns cluster execution and operational proof.

## Automated checks of the tooling

These workflows validate scripts, manifests and verifier behavior. They do not establish that a fault experiment passed on Kind or AKS.

| Workflow | Checks |
| --- | --- |
| [Checkout load harness](../../.github/workflows/load-tests.yml) | Node scenario/configuration tests, Python verifier tests and a harness image build; image publication requires manual dispatch |
| [Reliability tooling checks](../../.github/workflows/reliability-tests.yml) | Runner, provider-audit and fault contracts, production Helm lint, and local Docker checks of ingress refusal/recovery and proxy expiry/restart |
| [Kind HA profile checks](../../.github/workflows/kind-ha.yml) | Shell syntax, Kind/Kind HA rendering, Helm lint, failure-domain invariants, experiment audit logic and verifier tests |

The application [smoke workflow](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/.github/workflows/smoke-tests.yml) owns CI orchestration of application smoke tests. Configuration's [Kind procedure](../operations/kind.md) documents local setup and smoke execution.

## Reading the evidence

`summary.json` records the client run outcome. `evidence.json` records extracted state; `extraction: COMPLETE` means collection completed. The verifier assesses correctness, and an absent or incomplete provider audit leaves financial correctness `NOT_VERIFIED`. The report preserves these distinctions alongside the scenario-specific observations.

A client timeout remains a failed client observation even when a later audit finds the order confirmed. Poll-observed confirmation time is an upper bound and differs from the server checkout-duration SLI. Ramp/spike runs have bounded attempts and concurrency; they do not establish maximum sustainable throughput. Kind nodes share one host, so worker loss does not establish physical-host or availability-zone tolerance. Use the applicable declared objective before claiming RTO/SLO compliance.

Follow [verification results](README.md) to the reports and their JSON/CSV artifacts. [Readiness](../readiness.md) tracks unresolved acceptance work, including telemetry and recovery gaps.
