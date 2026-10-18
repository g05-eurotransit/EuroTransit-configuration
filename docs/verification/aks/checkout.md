# AKS checkout verification

Fault-free checkout runs verified sequential purchases, one-seat contention, HTTP replay and bounded ramp/spike pacing. The five-order baseline has only a manual provider check and remains `NOT_VERIFIED` by the automated correctness verifier. Other cases have their own independent provider audits; those audits do not verify the newer baseline.

## Method and scope

Runs used the configuration-owned workstation k6/Python harness through public AKS ingress, finite fresh fixtures and persistent claims. No fault or extra cluster workload was introduced. Except for the complementary earlier baseline, deployed images were Orders `bad4c04`, Inventory/Payments `98bedf2`. Common fixtures used Torino to Milano (`rt-to-mi-001`), offer `of-001`, travel date 2026-10-19 and EUR 24.90 per seat.

Each independent audit enumerated all Stripe sandbox charge pages in its own run window with two-second padding and matched amount, currency and reference to durable order/payment evidence. Completeness applies to that window, not future effects. Raw artifacts and credentials remain private; business records and fixture claims were preserved.

## Baseline

Run `et-e88ff2ff5e6f415e`, harness revision `71191ac`, submitted five sequential purchases with one VU for seats 2B, 2C, 2D, 3A and 3B.

| Observation | Result |
| --- | --- |
| Client harness | 5/5 confirmed, zero assertions, exit 0 |
| Database audit | Five confirmed Orders/reservations, five matching SOLD seats and five AUTHORIZED payment records |
| Provider check | Team manually reported five matching charges and no duplicates; no machine-readable provider audit imported |
| Automated correctness | `NOT_VERIFIED` because independent provider evidence is missing |
| Acceptance / poll-observed confirmation p95 | 124.3 ms / 2261.8 ms |
| Instrumentation | End-to-end histogram buckets and circuit-breaker series present in actual Prometheus queries |

Restricted artifacts: `load-results/baseline-20261012T203537Z` (metadata, ledger, summary, evidence, telemetry, verification and Pod snapshots). Import a complete provider audit before claiming automated verification. Namespace/time-scoped Prometheus queries may include other traffic and do not verify individual orders.

### Complementary provider-audited baseline

A separate earlier baseline had 20/20 accepted and confirmed orders, 20 matching reservations/SOLD seats, 20 authorizations and 20 independently enumerated provider charges, zero unmatched effects and a `VERIFIED` final correctness audit. Acceptance/observed confirmation p95 was 146.7/2279.3 ms. Its application revision lacked end-to-end histogram and breaker series, so telemetry remained `NOT_VERIFIED`.

Restricted artifacts: `.resilience-evidence/aks-baseline-20261006T215039Z`. Its provider audit cannot be inherited by the five-order run.

## Contention

Hypothesis: five independent requests for one available seat produce one purchase and no losing charges. Run `et-8954366acc8f4d4b`, harness revision `412adc4`, used two VUs with distinct keys for seat 3C. Capacity preflight passed with `saturated=false`; faults remained prohibited.

| Observation | Result |
| --- | --- |
| Client outcome | Five HTTP 202; one confirmation and four `FAILED / SEATS_UNAVAILABLE`; zero assertions, exit 0 |
| Financial/seat audit | One winning reservation/SOLD seat, one authorization and one matching provider charge; no losing authorization, duplicate or unmatched charge |
| Correctness | `VERIFIED`, zero violations |
| Telemetry | Checkout/breaker series present; `NOT_VERIFIED` because consumer lag was absent |

The bounded hypothesis held. This does not prove mid-stage crash safety, Kafka replay or higher-concurrency capacity. Artifacts: `load-results/contention-20261012T211324Z`, including original fixtures, ledger, provider audit and unchanged-run-window final collection.

## Request replay

Hypothesis: same-key/same-payload returns the original order; changed payload conflicts. Run `et-d21995eaaa5d4093` used one VU and five iterations on seats 3D, 4A, 4B, 4C and 4D. Each iteration submitted, replayed, changed the amount under the same key and polled the original order.

| Observation | Result |
| --- | --- |
| Client outcome | Five confirmed originals; five identical replays returned HTTP 202 and the original ID; five changed-payload requests returned 409; zero assertions, exit 0 |
| Financial/seat audit | Five matching reservations/SOLD seats, authorizations and independent provider charges; zero duplicate or unmatched effects |
| Correctness | `VERIFIED`, zero violations |
| Telemetry | Checkout/breaker series present; consumer lag absent, hence `NOT_VERIFIED` |

A recorded operator override bypassed only saturation after preflight reported `saturated=true`; other checks, claims, locking and deadlines remained active. It does not establish safe capacity. Sequential HTTP replay does not prove simultaneous first-request idempotency or event redelivery safety.

Artifacts: `load-results/request-replay-20261012T212438Z`, including the original `capacity-override.json`, ledger, database evidence and complete provider audit.

## Ramp and spike

Hypothesis: modest concurrency/pacing changes preserve correctness and confirmed recovery-tail purchases. Each run used eight fresh fixtures, at most two VUs and a lower-rate recovery tail. The recorded saturation overrides affected only that gate; repository runner code and all other admission bounds remained unchanged.

| Scenario | Run | Duration | Confirmed | Recovery-tail confirmations | HTTP 429 | Correctness |
| --- | --- | --- | --- | --- | --- | --- |
| Ramp | `et-10c6c60aed4d4592` | 14.57 s | 8/8 | 2 | 0 | `VERIFIED` |
| Spike | `et-cb2fac324061419d` | 15.97 s | 8/8 | 4 | 0 | `VERIFIED` |

Each run independently matched eight reservations, SOLD seats, authorizations and provider charges, with zero duplicates, unmatched effects or correctness violations. Neither observed 429, so `overloadDemonstrated=false`: overload refusal/recovery was not demonstrated. Telemetry remained `NOT_VERIFIED` because consumer lag was absent.

Artifacts: `load-results/ramp-20261012T212732Z` and `load-results/spike-20261012T212805Z`, including their separate capacity overrides, ledgers, provider audits and verification.

## Interpretation

These are bounded correctness observations, not a capacity benchmark, injected-failure result or rolling 30-day SLO assessment. Poll-observed confirmation includes polling delay and cannot replace the server end-to-end histogram. Use the [runner](../../operations/load-tests.md) for reproduction, [load-shedding report](../kind/checkout-load-shedding.md) for measured controlled 429 behavior and [verification index](../README.md) for fault evidence.
