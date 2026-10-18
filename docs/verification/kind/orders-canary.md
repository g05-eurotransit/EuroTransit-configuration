# Orders canary : Kind

## Result

**Controller/traffic proof passed with a documented capacity exception.
Run-scoped financial review is closed with manual operator confirmation.** Automatic abort and restoration to stable
routing were observed, followed by successful ordinary analysis at 10%, 25%
and 50%, a 100% read-only check and final `Healthy` promotion.

All three checkout batches confirmed 30/30 orders, 90 total. The independent
provider evidence differs by batch; automatic results and manual review are
reported separately:

| Batch | Client outcomes | Independent provider/financial closure |
| --- | --- | --- |
| 10% | 30/30 confirmed | Original audit and verifier passed: 30 authorizations, no unmatched effect |
| 25% | 30/30 confirmed | Original audit remained incomplete; separate follow-up verified 30 authorizations and explicitly recorded one declined, zero-effect attempt |
| 50% | 30/30 confirmed | 30 matching authorizations; operator accepted the additional €49.90 shared-sandbox payment as outside this test. Original automatic audit remains **NOT_VERIFIED** |
| 100% | 50/50 HTTP 200 reads | No additional checkout or payment created in this step |

The original automatic audit remains unchanged: it could not attribute the
additional successful charge to Kind or the read-only AKS ledger lookup.
Following review of the amount, timestamp and request key, the operator accepted
the shared-sandbox explanation and confirmed that no further investigation was
needed. This closes the run-scoped manual review; it is not independent proof
of the external payment's owner. No auditor exemption or monetary-state cleanup
was introduced. Controller-only testing had continued with the original finding
still open at execution time.

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

[Sanitized results](../evidence/2026-10-17/orders-canary.json) include every normal
gate measurement, abort/promotion timeline, backend routing counts, capacity
exception/restoration and artifact hashes. Raw originals remain under
`load-results/kind-progressive-20261017T210750Z`, including the failed financial
audits. The [25% follow-up](orders-canary.md) explains
the separate declined-attempt correction; it did not exempt the successful
unmatched charge at 50%.

The operator confirmation closes the shared-sandbox finding for this test; it
does not turn the original automatic audit into a pass. A subsequent reviewed
GitOps release must demonstrate real immutable application-version delivery;
configuration-only Kind revisions do not supply that history.

## Declined-attempt audit correction

The 25% canary batch accepted and confirmed all 30 orders. Its original provider
audit enumerated 30 matching authorizations and one unmatched Stripe Charge
object, marked the extraction `INCOMPLETE`, and caused the ordinary verifier to
return `NOT_VERIFIED`. Promotion stopped pending investigation. The original
audit, ledger, verification and time window remain unchanged.

Independent read-only Stripe inspection found the extra object was
`failed/card_declined`: `paid=false`, `captured=false`, `amount_captured=0`,
`amount_refunded=0`, with no balance transaction. Its reference and request key
matched no Kind payment or idempotency row. A `charge.failed` event corroborated
the status. Its owner remains unattributed; this evidence does not establish
which external actor submitted it. A window overlap with the previous batch
was investigated and ruled out.

## Correction and verification

The harness incorrectly treated every unmatched Charge object as an additional
financial effect. [Stripe defines `paid`](https://docs.stripe.com/api/charges/object)
as a successful charge or authorization for later capture. The corrected audit
lists unmatched failed attempts separately only when all of the explicit
zero-effect fields above are present. Successful, authorized, pending,
captured, refunded or insufficiently documented unmatched effects still block.
Failed records do not satisfy a run's expected successful authorization.
No financial invariant or canary threshold was waived.

Eleven unit tests cover the positive classification, redaction, missing proof,
contradictory payment/capture/refund fields, successful uncaptured authorizations,
expected authorizations, duplicate references and bounded exhaustive pagination.

A separate `provider-followup/` audit re-enumerated the **same original time
window** against the unchanged client ledger. It verified 30 successful
authorizations, zero unmatched monetary effects, and one explicitly recorded
unattributed failed attempt with zero financial effect. The normal collector and
financial verifier then returned `VERIFIED`. The original failed verification
was not overwritten or relabelled as an original pass.

This is a harness classification fix, with no application, payment request,
retry, provider key or monetary state change. The same candidate and ordinary
canary gates resumed at the successful 25% pause. The
[sanitized follow-up](../evidence/2026-10-17/canary-25-provider-followup.json)
retains ledger/artifact hashes; provider references and event request keys remain
private in the progressive run's evidence directory.
