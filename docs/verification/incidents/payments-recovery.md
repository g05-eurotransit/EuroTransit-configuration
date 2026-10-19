# Payments latency incident timeline

**Incident:** Controlled Payments latency on the earlier deployed revision.
**Postmortem:** the team's [Payments latency postmortem](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/operations/payments-latency-postmortem.md) owns the cause, conclusions and follow-up actions. This page keeps the factual timeline it draws on.

## Observed impact

A four-second Payments response delay exposed a recovery gap: bounded retries
protected the system and Catalog, but accepted checkout work remained pending
with durable DELIVERY_EXHAUSTED incidents. The fault-run's six orders exceeded
the client deadline. Of two later recovery attempts, one confirmed and one stayed
pending. All eight eventually confirmed after scoped replay of their original
events; an independent sandbox audit verified eight charges and no duplicates.
No measured loss or oversell was found in that final audit.

## Detection and fault-relative timeline

- T+0 s: Payments-only response delay enabled, with independent 45s expiry.
- T+12 s: First observed Payments breaker OPEN.
- T+37 s: HALF_OPEN first observed; closed/open/half-open states were sampled.
- T+45 s: Injector removed the delay and restored the original qdisc.
- After healing: original client run failed; reconciliation incidents remained.
- Controlled recovery: exact original six events replayed, then the second run's two events.
- T+366 to T+426 s: Historical Prometheus samples show ReconciliationRecordOpen firing.
- T+394 s onward: labelled cross-run final-state audit collected; all eight CONFIRMED and provider verification passed.

Catalog returned 200 in all 129 probes, p95 137.5ms. Shutdown, replay and provider
extraction logs are retained; original failed client verdicts were not overwritten.
See [the detailed report](../aks/dependencies.md#payments-latency-and-restart).

## Mechanism and response

Timeouts/retries and circuit breaking bounded waiting. The existing exhaustion
path records durable operator work instead of confirming an unknown payment
outcome. Fault removal alone did not resume every affected checkout. The agent,
under the user's explicit test authorization, removed/verified faults and used
scoped original-event replay. No business database correction was performed.

## Resolution

The [postmortem](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/operations/payments-latency-postmortem.md) answers the open questions this page listed: the recovery objectives the team adopted, the redrive and abandonment policy, the alert thresholds, and the experiment identity, which remains an open action. The [compound-fault rerun](../aks/dependencies.md#payments-latency-and-restart) is its evidence for the corrections; the [latency-only rerun](../aks/dependencies.md#payments-latency) keeps its own verdict.
