# Checkout ingress load shedding

## Behavior and scope

`ingress.checkoutRateLimit.enabled` adds a Traefik token-bucket middleware only
to `POST /api/orders` and `POST /api/orders/`. Requests without an available
token receive HTTP 429 before reaching Orders. Catalog, order polling, seat-map
reads and refund endpoints continue through their existing routes. The checkout
route keeps secure headers, optional forward authentication and the existing
stable or weighted Orders service. No application code or image change is needed.

The feature is disabled by default. `average / period` defines token refill rate
and `burst` defines bucket capacity. Default values (10 requests per second,
burst 20) are initial configuration values, not measured safe capacity; the team
must choose and justify enabled values from observed behavior. Enabled values
require positive integer average/burst and an integer period in ms, s or m.
See the [official Traefik RateLimit documentation](https://doc.traefik.io/traefik/v3.3/middlewares/http/ratelimit/).

Buckets group requests by host, shared by clients of that host on each Traefik
replica. This avoids treating a spoofable forwarded client header as a quota
identity. It is not a distributed/global quota: multiple gateway replicas have
independent buckets, and the localhost alias has its own host bucket. Reloads or
restarts can refill buckets. Unauthenticated requests and idempotent replays also
consume quota; when forward authentication is enabled, shedding runs before it.
This policy protects ingress volume rather than providing per-customer fairness.

A fixed ingress rate limit does not bound Kafka backlog or react to a slower
downstream. Bulkheads and timeouts remain separate protections. Direct internal
Orders calls bypass the ingress policy. Do not claim this proves adaptive
admission control or guarantees stability at arbitrary downstream capacity.

## Controlled live experiment

The team owns the hypothesis and threshold choice. A proposed bounded experiment
is: above the configured refill rate, checkout receives 429 without business
effects, while Catalog/polling remain healthy; after reducing input rate, new
checkouts confirm. This is a proposal, not a completed chaos or load experiment.

1. Enable through a reviewed GitOps values change and wait for Argo CD sync:

   ```yaml
   ingress:
     checkoutRateLimit:
       enabled: true
       average: 1
       period: 1s
       burst: 1
   ```

   This deliberately low demonstration threshold is not a production sizing
   recommendation. Record actual Traefik replica count, values and revisions.
   Keep the canary success-only demonstration separate: expected ingress refusals
   can invalidate its request/sample gates.

2. Prepare eight new available fixtures, complete capacity preflight and run the
   native harness from the configuration checkout (Python/k6 installed):

   ```bash
   EXPECT_OVERLOAD=true python3 scripts/reliability-runner.py run \
     --context eurotransit --mode workstation \
     --harness "$PWD/load-tests/run.py" \
     --fixtures /absolute/path/fresh-fixtures.json \
     --output /absolute/path/new-shedding-run \
     --public-url https://g05.cpo2026.it \
     --issuer https://g05.cpo2026.it/realms/eurotransit \
     --scenario spike --max-attempts 8 --max-vus 2
   ```

   Supply `CLIENT_SECRET` through the environment as described in the
   [runner runbook](load-tests.md). The launcher forwards `EXPECT_OVERLOAD`
   to native, Docker and Job execution when explicitly supplied. Absence of 429
   fails with `expected_overload_not_observed`; all-refusal runs fail because a
   confirmed recovery checkout is required. A passing run proves the configured
   policy at the observed traffic, not exhaustion of underlying cluster resources.

3. Collect database and independent provider evidence using the existing runner
   and Stripe sandbox audit. Run the verifier. For every refused iteration, also
   verify absence of its ledger `idempotencyKey` in Orders `idempotency_keys`
   using read-only SQL; there should be no acceptance/outbox or provider effect
   attributable to those requests. The existing collector primarily scopes by
   accepted order IDs and does not independently certify all refused keys.

4. Record 429 count, response latency, successful recovery checkouts, Catalog
   probes, accepted terminal outcomes and provider audit. Traefik generates the
   refusals, so Orders HTTP metrics do not count them. Use the harness ledger
   plus gateway access logs/metrics for 429 evidence. Do not infer absence of
   refusals from Orders metrics. Preserve missing telemetry explicitly.

5. Restore the intended values or disable the feature through GitOps. Do not
   remove fixture claims or delete business records to repeat the experiment.

## Validation

`python3 scripts/test-checkout-load-shedding.py` renders kind/AKS configurations,
checking opt-in defaults, exact route scope, localhost, auth, stable/canary
service selection and invalid values. Add `--docker` to run the rendered rules
and middleware with actual Traefik v3.4.3 and a local mock backend: immediate
429, refused requests never reaching the backend, unaffected reads/refunds and
successful checkout after token refill. These local tests are wired into CI;
they do not inject load or deploy middleware on AKS.
