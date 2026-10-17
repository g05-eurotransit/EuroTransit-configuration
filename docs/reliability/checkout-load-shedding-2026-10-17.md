# Checkout load shedding — 2026-10-17

## Result

**PASS for the configured ingress refusal/recovery policy.** In run
`et-kind-shedding-2447131d97`, eight checkout attempts produced three HTTP 429
refusals and five HTTP 202 admissions, all five confirmed. Two confirmations
occurred in the harness's lower-rate recovery tail. k6/runner exit code was 0
and the original financial verifier passed. Complete independent Stripe sandbox
extraction found five authorizations and no unmatched charge.

Every refused idempotency key was absent from Orders; each refused fixture's
seat remained `AVAILABLE`. The original ledger, read-only refusal audit and
independent provider extraction jointly support absence of business effects for
these refusals. No request was replayed to manufacture recovery.

## Method and observations

Context `kind-eurotransit`, one Traefik 3.4.3 replica, two Orders replicas and
healthy CDC/PostgreSQL baseline. The existing Helm templates were rendered with
the installed values and an explicit checkout limit of one token per second,
burst one, grouped by request host. Only rendered ingress/middleware resources
were temporarily applied directly to Kind. This is **not GitOps delivery
evidence** and the deliberately low threshold is not production sizing.

The native k6 `spike` scenario used eight fresh, exclusively claimed fixtures,
two VUs and `EXPECT_OVERLOAD=true`. It exercised public Traefik endpoints and
retained expected refusals separately from failures. Independent probes covered
Catalog and polling of an existing confirmed order throughout the measured run.

| Check | Observation |
| --- | --- |
| Controlled refusals | 3/8 requests returned 429 |
| Admissions | 5/8 returned 202 and confirmed |
| Recovery tail | 2 confirmed checkouts |
| Catalog availability | 53/53 HTTP 200 |
| Order polling availability | 53/53 HTTP 200 |
| Refused keys in Orders | 0 |
| Refused seats | 3/3 still available |
| Independent payments | 5 unique authorizations; 0 unmatched charges |
| Cleanup | Original ingress restored; temporary rate-limit middleware removed |

An earlier setup attempt (`et-kind-shedding-ac6c9bb733`) stopped before k6 or
checkout traffic: this Helm version's `--show-only` output omitted the later
middleware document from its multi-document template. Cleanup restored the
ingress. The runner now renders the complete chart and selects validated
resource objects by kind/name, asserting that the enabled middleware is present.
Fresh fixture claims from that setup remain preserved. No passing results were
substituted into the failed attempt.

## Conclusion and reproduction

The fixed ingress policy rejects excess checkout arrivals promptly while
unrelated reads remain available, and checkout resumes after token refill.
The run demonstrates an intentionally low configured threshold, not exhaustion
of cluster resources, adaptive admission control, a bounded Kafka backlog or a
global quota across multiple Traefik replicas. These remain separate claims.

With the documented Kind profile, healthy CDC, host k6 and the owned Prometheus
port-forward on 19190, run `python3 scripts/kind-checkout-load-shedding.py`.
It uses at most eight sandbox checkouts, allocates fresh fixtures, audits accepted
orders and refused keys/seats, and restores the ingress in cleanup. Fixture
claims and business rows are retained. Raw artifacts remain private under
`load-results/et-kind-shedding-2447131d97`; [sanitized evidence and
hashes](evidence/2026-10-17/checkout-load-shedding.json) are versioned.
