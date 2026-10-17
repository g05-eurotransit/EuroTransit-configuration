# EuroTransit operational Definition of Done

Evidence status as of 2026-10-12. This is an agent-prepared review checklist;
the team must author/approve its DoD and own architectural and operational choices.
Application behavior/design stays in the application repository; configuration
owns deployment, observation and operational proof. A tick records the stated
bounded evidence, not full production readiness.

## Design and async — Pillar A

- [ ] Team approves service boundaries and synchronous/asynchronous rationale.
- [ ] Team verifies coroutine failure domains and blocking-vs-suspending cost reasoning against the implemented pipeline.
- [x] Orders SIGTERM shows readiness refusal, consumer/server drain and preservation of accepted work; link: [AKS report](reliability/orders-shutdown-2026-10-12.md).
- [ ] Complete Pod endpoint-removal timing and review backlog/dependency-down lifecycle evidence from application #132.

## Consistency — Pillar B

- [ ] Team owns inventory CAP/PACELC reasoning and the partition sacrifice.
- [x] Crash during observed reservation SQL plus duplicate original events and HTTP retries preserves one-seat/one-charge invariants in a scoped independent audit; link: [Inventory report](reliability/inventory-kill-2026-10-12.md).
- [ ] Review automatic reconciliation and operator recovery objectives; correctness after replay does not prove automatic convergence.

## Resilience — Pillar C

- [x] Slow Payments opens the breaker while Catalog stays healthy; link: [Payments report](reliability/payments-latency-2026-10-12.md).
- [x] Checkout completes while Notifications is stopped; link: [degradation report](reliability/notifications-down-2026-10-12.md).
- [ ] Verify bulkhead isolation and bounded timeout/retry/jitter behavior beyond configuration inspection.
- [ ] Apply and demonstrate controlled overload rejection plus recovery; configuration #54 is a proposal, not live load-shedding proof.
- [ ] Enable reviewed critical-service replicas/PDBs and reserve failed-node capacity; current single-replica evacuation interrupts service.
- [ ] Verify meaningful startup/readiness/liveness behavior under downstream outages.

## Delivery, observation and proof — Pillar D

- [ ] Demonstrate GitOps-driven canary promotion, automatic abort and routing recovery with compatible immutable images and real SLIs.
- [ ] Demonstrate blue/green preview, promotion and fast rollback; preserve recorded release revisions.
- [ ] Team approves all-at-once/rolling strategy reasoning; link to canonical delivery design.
- [ ] Reconcile scrape-label correction and verify dashboards/gate selectors against real samples.
- [ ] Align terminal success and end-to-end latency SLIs/alerts with team-owned SLOs and error budgets.
- [x] A real reconciliation symptom alert fired during an injected fault; link: [observability audit](reliability/observability-verification-2026-10-12.md).
- [ ] Deploy tracing export/backend and inspect a real gateway-to-Kafka checkout trace.
- [ ] Verify CI credentials and history: immutable builds update Git; CI holds no cluster credentials.

## Chaos and recovery

- [x] Record executed Payments latency, Inventory crash, Kafka partition and temporary-HA CNPG failover with fault/cleanup evidence; link: [report index](reliability/chaos-experiment-reports.md).
- [x] Record the failed node evacuation and recovery rather than claiming continuous availability.
- [ ] Repeat real node/AZ loss with sufficient capacity and HA workloads.
- [ ] Define checkout RTO/RPO and verify automatic convergence; the CNPG read timing is not checkout completion RTO.
- [ ] Repeat primary failover under reviewed, persistent GitOps HA configuration.
- [ ] Team authors/reviews the final blameless postmortem and closes assigned actions.

## Agentic coding and final delivery

- [x] Record concrete agent mistakes and their corrections; link: [agent log](agent-log.md).
- [x] Record actual credentials/blast radius and the authorized test-session exception; link: [threat model](governance/agent-threat-model.md).
- [ ] Team verifies the log and threat model; establish a least-privilege experiment identity.
- [ ] Review and publish the proposed report/fix commits; retain restricted raw evidence.
- [ ] Record and commit the approximately five-minute demo link showing both releases and a real alert; [storyboard](reliability/demo-storyboard.md).
- [ ] Schedule the live presentation only after the remaining proof gates close.
