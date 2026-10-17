# Provider audit: declined attempt classification — 2026-10-17

## Finding

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
[sanitized follow-up](evidence/2026-10-17/canary-25-provider-followup.json)
retains ledger/artifact hashes; provider references and event request keys remain
private in the progressive run's evidence directory.
