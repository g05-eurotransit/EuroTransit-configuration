# Blameless incident review : draft for team authorship

**Incident:** Controlled Payments latency on the earlier deployed revision.
**Authors:** Team authors/reviewers pending. Agent-prepared factual timeline only.
**Status:** Recovery observed; recovery-policy judgment and assigned actions open.

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
See [the detailed report](aks-payments-latency-and-restart.md).

## Mechanism and response

Timeouts/retries and circuit breaking bounded waiting. The existing exhaustion
path records durable operator work instead of confirming an unknown payment
outcome. Fault removal alone did not resume every affected checkout. The agent,
under the user's explicit test authorization, removed/verified faults and used
scoped original-event replay. No business database correction was performed.
This is an observed mechanism and response, not a team-approved root-cause or
recovery-policy decision.

## Questions the team must resolve

- Does pending durable work with operator recovery meet the checkout recovery objective?
- How should redrive avoid extending an expired hold or producing incorrect compensation?
- Which symptom/age/incident SLIs should protect stranded accepted work and operator response?
- Which experiment identity and cleanup controls adequately bound fault-injection permissions?

## Proposed actions : owners and acceptance criteria pending

- [ ] Team reviews the proposed recovery objectives and the implemented automatic/operator policy; no failover RTO compliance is claimed by the existing report.
- [ ] Review the implemented exhausted-delivery/redrive/abandon/settle behavior against the [current application policy](https://github.com/g05-eurotransit/EuroTransit-application/blob/dev/docs/design/reservation-confirmation.md).
- [ ] Align terminal-outcome/end-to-end alerts; Kind verifies corrected scrape labels, while target-environment query mapping still needs review.
- [ ] Add a least-privilege experiment identity and review the documented credential exception.
- [ ] Review the [latency-only rerun](aks-payments-latency.md) and [compound-fault rerun](aks-payments-latency-and-restart.md); retain their distinct original verdicts.

The team must author and own the final postmortem, assign action owners and acceptance criteria and defend
the conclusions. This draft does not mark those judgments complete.
