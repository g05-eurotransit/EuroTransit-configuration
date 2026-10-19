# Checkout load and correctness harness

Configuration-owned operational harness for [application #123](https://github.com/g05-eurotransit/EuroTransit-application/issues/123). This repository also owns
cluster execution, fixture allocation, resource preflight and evidence collection
(#46), plus fault/event injection (#47). Application service unit/integration tests
and metrics instrumentation remain in the application repository. No workload, cluster or provider mutation is
performed by CI. Executing the harness **creates real test orders and consumes seats**.

## Execution contract

Run `python3 load-tests/run.py` (k6 on PATH), `just load-checkout`, or use
`eurotransitregistry.azurecr.io/eurotransit/load-tests:<full configuration SHA>`.
The configuration `Checkout load harness` workflow validates on PR/main and
publishes only on manual dispatch using this repository's ACR credentials.

Container default entrypoint runs the same wrapper; do not override it with `k6 run`.
The wrapper accepts an optional absolute script filename.

Supply `PUBLIC_URL`, `TOKEN_URL`, `CLIENT_ID`, `CLIENT_SECRET` via an existing secret,
unique safe `RUN_ID`, `FIXTURES_FILE`, and writable `OUTPUT_DIR` (default `/results`).
`SCENARIO` is `baseline` (default), `ramp`, `spike`, `contention` or `request-replay`.
`MAX_ATTEMPTS` defaults to 20 (hard bound 1 to 10000); `MAX_VUS` defaults to 2 (hard cap 4);
`POLL_TIMEOUT_SECONDS` defaults to 30 (hard bound 300). Optional test-provider
`PAYMENT_METHOD_TOKEN` defaults to `tok_visa`; this is never exported.
`ALLOW_INSECURE_TLS=true` is only for local certificates; TLS validation is on by default.

Fixtures use `{ "version": 1, "fixtures": [{ "routeId": "rt-to-mi-001",
"offerId": "of-001", "travelDate": "2099-01-01", "seatId": "1A", "unitPrice": 24.90 }] }`.
Fixture currency defaults to EUR; optional `currency` overrides it with an uppercase
ISO code and is checked against durable order/payment/provider evidence.
Choose **actual provisioned future dates**, not the illustrative date above.
[`fixtures/example.json`](fixtures/example.json) is an editable example, not a
provisioned dataset: replace the date and verify availability before running it.
Allocate at least MAX_ATTEMPTS distinct route/date/seat tuples except contention,
which intentionally competes for one fixture. Preflight checks current Catalog
price and available seats. Allocation never wraps or deletes business records.
Only one run may own a fixture block: #46 serializes allocation; a run ID is not a lock.

Baseline runs sequentially. Ramp/spike use bounded shared iterations and change
pacing from a low-rate phase to an unpaced bounded-concurrency phase, then a recovery
tail; these are resource-safe concurrency experiments, **not a capacity benchmark**.
Raise from 2 to 4 VUs only after #46's resource gate; do not increase cluster memory.
Catalog is probed throughout each checkout/poll cycle. HTTP timeout is 10s (poll 5s),
all polling has a finite deadline. Tokens refresh before expiry. No client retry loop
amplifies overload. Expected overload is only 429 in ramp/spike; baseline requires
CONFIRMED and fails on FAILED, malformed responses, lookup failure or timeout.
Ramp/spike require at least one confirmed checkout in the low-rate recovery tail;
all429 never passes. `overloadDemonstrated` reports whether a429 occurred; set
`EXPECT_OVERLOAD=true` for an overload experiment, so absence of controlled refusal
fails rather than silently claiming overload handling was demonstrated. Contention requires exactly one CONFIRMED; losers must report SEATS_UNAVAILABLE.
Request replay checks same payload/key gives the original ID and changed payload/key gives409.

## Results and evidence

Stdout events use `ET_RESULT ` followed by JSON with `type` and `runId`.
Events: `run_started`, `order_result`, `assertion_failure`, `run_summary`,
`run_finished`, `runner_finished`. `order_result` carries iteration, fixture,
idempotencyKey, correlationId, optional orderId/status/failureCode,
httpStatus, acceptanceMs, observedConfirmationMs and outcome.
The wrapper always writes `orders.jsonl` and `summary.json`; an incomplete ledger fails.
Missing/partial k6 summary fails. No token, JWT, secret, provider reference or email is emitted.

Acceptance latency and poll-observed time-to-confirmation are distinct metrics.
Polling measures an upper bound; it does **not** replace the server
`orders_checkout_e2e_duration_seconds` SLI, which survives Kafka redelivery.
Use the canonical team SLOs in [application SLOs](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/design/slo.md); a small
successful sample is not evidence of the 30-day SLO. Throughput and expected
refusals remain separate from terminal/technical failures and timeouts.

[Verification results](../docs/verification/README.md) record observed outcomes and their individual audit limits.

Run `python3 load-tests/verify.py --ledger <orders.jsonl> --evidence <evidence.json>
--output <verification.json>`. Configuration's read-only collector emits:
`{runId, extraction:"COMPLETE", orders:[], reservations:[], payments:[], inventory:[],
outboxEvents:[], providerEffects:{extraction:"COMPLETE",authorizations:[]}}`.
Rows use projected SQL snake_case names: Orders `id,status,route_id,travel_date,seats`; Inventory reservations
`order_id,reservation_id,status,route_id,travel_date`; seats `route_id,travel_date,seat_id,status,reservation_id`;
Payments `order_id,status,amount,currency,provider_reference_hash`.
Provider audit authorizations require `order_id,status:"SUCCEEDED",amount,currency,provider_reference_hash`.
Hash raw provider references with SHA256 consistently; raw references are accepted only
for trusted local test evidence. Audit evidence must exhaustively enumerate provider
effects for the run, not reconstruct them from Payments rows. If provider audit is
unavailable, export INCOMPLETE and report NOT_VERIFIED, never claim no double-charge.
The verifier fails on unresolved orders, duplicate authorizations/provider effects,
seat ownership conflicts, oversell, charged contention losers, missing or mismatched evidence.

For event replay, #47 reads the **exact original** `order-placed` outbox envelope
from restricted canonical-events.json and republishes it using aggregate_id as key.
Only run-owned accepted order IDs are allowed; preserve eventId, orderId and payload;
never create fake events or delete rows. Capture evidence before and after, prove no
additional successful authorization/reservation, and record consumption/duplicate
counter changes. Replaying a terminal order alone does not prove mid-stage crash safety.

## Scope and overload observations

The harness observes the deployed application.
It does not change Orders admission, database/HTTP pools, timeouts, retry policy,
or checkout persistence. Any operational hardening belongs in a separate,
evidence-based proposal in the application repository.

Ramp/spike record controlled refusals separately from technical failures and
require successful recovery. `EXPECT_OVERLOAD=true` requires at least one observed
429; without that observation the report does not claim load shedding. These tests
measure the current system rather than supplying new overload controls.
Use the verification index for executed experiments and readiness for unresolved acceptance.

`just load-checkout-unit` runs allocator/outcome/verifier tests in configuration.
The application repository's `ResilienceMetricsTest` verifies actual registry
gauges and the exported end-to-end histogram.

## Instrumentation prerequisite

The deployed Orders image must expose the canonical [checkout SLIs](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/design/slo.md) and actual Resilience4j registry metrics. Missing buckets, breaker state or committed lag remain unavailable evidence, not zero. The [platform monitoring reference](../docs/platform/observability.md) owns target wiring.

## Review findings

Independent agent review reproduced false positives in the initial verifier:
confirmed client outcomes could disagree with durable order state, and matching
provider references could conceal wrong amounts or incomplete provider evidence.
The corrected verifier checks status, scenario, scope, fixture ownership, amount,
currency and independent provider effects; regression cases are in
`tests/test_verify.py`. Team reproduction remains required before claiming team-owned
verification. These checks are not a chaos experiment.
