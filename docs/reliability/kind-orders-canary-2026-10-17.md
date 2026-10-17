# Orders canary — Kind, 2026-10-17

## Result

**Controller/traffic proof passed with a documented capacity exception.
Financial closure is PARTIAL.** Automatic abort and restoration to stable
routing were observed, followed by successful ordinary analysis at 10%, 25%
and 50%, a 100% read-only check and final `Healthy` promotion.

All three checkout batches confirmed 30/30 orders, 90 total. The independent
provider evidence differs by batch and must not be collapsed into one green
result:

| Batch | Client outcomes | Independent provider/financial closure |
| --- | --- | --- |
| 10% | 30/30 confirmed | Original audit and verifier passed: 30 authorizations, no unmatched effect |
| 25% | 30/30 confirmed | Original audit remained incomplete; separate follow-up verified 30 authorizations and explicitly recorded one declined, zero-effect attempt |
| 50% | 30/30 confirmed | **NOT_VERIFIED:** 30 matching authorizations plus one unmatched successful €49.90 sandbox charge |
| 100% | 50/50 HTTP 200 reads | No additional checkout or payment created in this step |

The unmatched successful charge was preserved as blocking for financial
verification. Its request key/reference matched neither Kind nor the read-only
AKS ledger lookup. Its origin remains unknown. No amount-based exemption,
allowlist, success rewrite or monetary-state cleanup was used. Controller-only
testing continued on the unchanged application artifact, with that limitation
explicitly retained; this is not financial acceptance of a production release.

## Method and observations

The existing Orders artifact (`45357ef`, local alias `eurotransit/orders:kind-ha`)
was used throughout. Revisions changed only a Pod-template annotation. Argo
Rollouts chart 2.41.1/controller 1.9.1 adopted the existing Deployment with
`workloadRef`; no new image was built or published. Direct Kind application of
these resources is local controller proof, not GitOps/CI delivery evidence.

The pinned controller initially selected the legacy Traefik v2 API. Setting
`--traefik-api-group=traefik.io` and
`--traefik-api-version=traefik.io/v1alpha1` resolved `TrafficRoutingError`.
The source chart now also explicitly retains the configured replica counts.
Application ServiceMonitors preserve `app` and rollout-hash labels.

1. A test-only, impossible Prometheus condition on the candidate's real HTTP
   counter failed. The controller set `abort=true`, the AnalysisRun became
   `Failed`, and `orders-weighted` returned to stable 100/canary 0.
2. A fresh configuration revision then used the **ordinary eight gate
   definitions unchanged**, including five-minute initial observation, two
   measurements, minimum HTTP/terminal evidence, process age/continuity, p95 and
   zero error/exhaustion budgets. All three normal AnalysisRuns succeeded:
   48 successful metric measurements. These are demo promotion gates, not
   proof of the rolling production SLO.
3. Fresh fixtures and native k6 supplied each 30-order batch. HTTP polling
   traffic and Kafka processing exposure were measured separately. PromQL
   `increase()` values are estimates, not literal fractional orders.
4. After the 50% provider audit failed, controller-only promotion continued
   with 50 reads of an already confirmed order at 100%; no extra order was
   generated to bypass the financial finding. Final controller status was
   `Healthy` with stable hash `69475d8bcc` at 21:47:55 UTC.

Traefik access logs mapped actual backend IPs to ReplicaSet hashes:

| Configured canary weight | Stable requests | Canary requests | Observed canary share |
| --- | --- | --- | --- |
| 10% | 1018 | 109 | 9.7% |
| 25% | 800 | 267 | 25.0% |
| 50% | 529 | 526 | 49.9% |
| 100% explicit read check | 0 | 50 | 100% |

The counts cover Orders HTTP requests, including reads; they are not checkout
admission counts or Kafka partition weights. Timestamp granularity can place a
boundary request on either side of a promotion.

## Capacity exception and restoration

At final consolidation the controller requested two stable plus two new Pods.
The required app-wide anti-affinity could not place four Orders Pods on three
workers. The pending Pod alone received a UID-conditioned control-plane
toleration under the user's resource-exception authorization. No node taint,
ReplicaSet/Deployment template, image or analysis gate changed.

After the old stable Pods retired, that temporary Pod was normally deleted.
Its replacement used the original template on a worker. Orders returned to two
Ready replicas on workers, and the control-plane exception was removed. This
test does not establish that the default three-worker placement can accommodate
full four-Pod overlap without an exception; a normal delivery environment needs
the required topology/capacity.

## Evidence and remaining work

[Sanitized results](evidence/2026-10-17/orders-canary.json) include every normal
gate measurement, abort/promotion timeline, backend routing counts, capacity
exception/restoration and artifact hashes. Raw originals remain under
`load-results/kind-progressive-20261017T210750Z`, including the failed financial
audits. The [25% follow-up](provider-audit-declined-attempt-2026-10-17.md) explains
the separate declined-attempt correction; it did not exempt the successful
unmatched charge at 50%.

To close the full payment-sensitive release proof, attribute that successful
charge or repeat in an isolated sandbox/account window. A subsequent reviewed
GitOps release must also demonstrate real immutable application-version
delivery; configuration-only Kind revisions do not supply that history.
