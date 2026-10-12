# AKS bounded ramp and spike — 2026-10-12

## Execution and hypothesis

Both workstation scenarios used eight fresh one-seat fixtures, at most two VUs,
and bounded iteration pacing followed by a lower-rate recovery tail. The hypothesis
was that these modest concurrency changes would preserve checkout correctness
and produce confirmed orders in the recovery tail. No fault was injected and no
cluster workload was added. Orders used image `bad4c04`; Inventory and Payments
used `98bedf2` from the EuroTransit ACR namespace.

The preflights reported memory saturation. The operator explicitly authorized a
transient bypass of only the saturation gate for these two eight-attempt/two-VU
runs. Other capacity checks, fixture claims, run locking and deadlines remained
active. Repository runner code was unchanged; each run retains its original
preflight and `capacity-override.json`.

## Results

| Scenario | Run ID | UTC window | Confirmed | Confirmed recovery checkouts | HTTP 429 | Correctness |
| --- | --- | --- | --- | --- | --- | --- |
| ramp | `et-10c6c60aed4d4592` | 2026-10-12T21:27:37.680779+00:00–2026-10-12T21:27:52.250418+00:00 | 8/8 | 2 | 0 | `VERIFIED` |
| spike | `et-cb2fac324061419d` | 2026-10-12T21:28:10.622069+00:00–2026-10-12T21:28:26.596579+00:00 | 8/8 | 4 | 0 | `VERIFIED` |

Each run passed its harness checks and independently verified eight reservations,
eight owned SOLD seats, eight application authorizations and eight matching Stripe
sandbox charges, with no duplicate effects or unmatched provider charges. The
provider audit exhausted all charge pages in each run window with two seconds of
padding on either side. Correctness verifiers reported zero violations.

## Conclusion and limits

Both hypotheses held at this bounded concurrency. Neither run observed HTTP 429:
`overloadDemonstrated` is false, so controlled load shedding was not demonstrated.
These pacing experiments are not a capacity benchmark, do not establish production
SLO compliance, and do not prove recovery from overload that never occurred. The
operator saturation overrides are part of the experimental conditions.

Provider completeness applies to the audited windows, not to future charges.
Prometheus collection remains `NOT_VERIFIED` because Kafka consumer lag is absent;
this is separate from the passing per-order correctness audits.

## Evidence

Restricted artifacts are retained locally in
`load-results/ramp-20261012T212732Z` and `load-results/spike-20261012T212805Z`,
including run metadata, fixtures, capacity overrides, ledgers, summaries, database
snapshots, independent provider audits, telemetry and correctness reports.
Raw artifacts and credentials remain outside Git. Business records and fixture
claims remain intact.
