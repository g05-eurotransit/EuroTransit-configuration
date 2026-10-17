# Notifications degradation and committed lag — 2026-10-17

## Result

**PASS.** Two checkout orders confirmed while the Notifications process was
paused. Both passed the original financial verifier and complete independent
Stripe sandbox audit: two authorizations, no unmatched charge. Committed
Notifications lag rose from zero to two and recovered to zero after the pause.
Prometheus recorded both the increase and recovery. The same Notifications Pod
and container survived, with no restart.

## Method and observations

After the delivery experiments, the Kind-only Strimzi Kafka Exporter and
PodMonitor were activated. All three broker Pod UIDs and restart counts remained
unchanged. Six committed-offset lag series appeared: three populated partitions
for Orders and three for Notifications. Empty refund/DLT partitions were not
invented as zero-valued observations.

The proposed operational question, consistent with the existing Notifications
failure boundary, is whether checkout completes independently while lag exposes
the delayed notification work and returns to steady state after recovery. The
experiment used two fresh, exclusively claimed fixtures and native k6.

A single Notifications process received SIGSTOP at 21:57:16.409 UTC. A separate
host watchdog checked container identity and sent SIGCONT at 21:57:31.513 UTC.
The 15-second pause stayed below the configured liveness failure window; normal
cleanup also ensured resumption. No broker, node or database fault was injected.

| Signal | Observation |
| --- | --- |
| Checkouts observed confirmed before SIGCONT | 2/2 |
| Independent provider authorizations | 2; no unmatched effect |
| Direct exporter total notification lag | 0 → 2 → 0 |
| Prometheus total notification lag | 0 → 2 → 0 |
| Maximum lag on one partition | 1; the two pending records occupied different partitions |
| Notifications identity/restarts | Same Pod UID and container ID; restart count unchanged |

The Prometheus query used `kafka_consumergroup_lag`, which measures committed
offset lag. It does not substitute Spring fetch-position lag. Scraping was every
30 seconds; the saved range query has a five-second evaluation step, which
repeats stored samples rather than creating five-second scrape resolution.

After resumption the pipeline caught up without replay, redrive or business-row
cleanup. The experiment also verifies successful checkouts on the fully
promoted Orders revision after its temporary control-plane placement was removed.
No SLO compliance over 30 days or universal notification fault tolerance is
inferred from two requests.

## Evidence

[Sanitized result and hashes](evidence/2026-10-17/notifications-committed-lag.json)
and [Prometheus total-lag CSV](evidence/2026-10-17/notifications-committed-lag.csv)
are versioned. Raw artifacts remain under
`load-results/kind-progressive-20261017T210750Z/et-kind-notifylag-4f19d482`.
The owned forward, watchdog and exclusive lock were removed; fixture claims and
business/audit rows remain. Final Kind smoke and complete preflight passed.
