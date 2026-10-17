# Catalog blue/green — Kind, 2026-10-17

## Result

**PASS for local preview, gated promotion and fast rollback.** The public
Catalog API returned valid, unchanged data for 1316/1316 requests; direct
preview checks returned valid data for 1042/1042 requests. The normal
pre-promotion AnalysisRun succeeded. The previous revision remained Ready at
promotion, and rollback reached a Healthy original revision in 1.575 seconds.

This used configuration revisions of the existing Catalog artifact
(`98bedf2`, local alias `eurotransit/catalog:kind-ha`), with only a Pod-template
annotation changed. No application image, checkout or payment was created.
Resources were applied directly to Kind; this does not supply GitOps history or
demonstrate delivery of a different application binary.

## Method and observed timeline

The operational question is whether the preview remains separate, the ordinary
gate and manual promotion control cutover, and the retained prior revision can
restore traffic promptly. Team owners review the hypothesis and acceptance
policy; the evidence below records actual controller and request behavior.

| UTC time | Observation |
| --- | --- |
| 21:51:01 | Preview `6579f67b8f` Ready; public Service still selects `7d4f57fb57` |
| 21:53:01 | Original preview gate `Successful`, with its 90-second delay and two measurements |
| 21:53:02 | Manual promotion selects `6579f67b8f`; previous revision still Ready |
| 21:53:12 | Restoring the previous Pod template completes fast rollback in 1.575 s |
| After rollback | Public traffic returns to `7d4f57fb57`; two active replicas are restored |

Both `/api/catalog/routes` and `/api/catalog/offers` were checked. Preview
traffic used a loopback port-forward bound to the candidate; those probes
stopped before promotion, avoiding a misleading claim that a bound port-forward
tracks later Service selector changes. Public requests continued through
Traefik during cutover and rollback.

Access logs independently show 83 public requests served by the candidate and
1233 by the original revision, with no unknown backend. The first public
candidate response appeared at 21:53:02 UTC, and 72 requests after the observed
rollback were served by the original revision. This proves actual traffic
movement in addition to Service selector updates.

## Capacity and verification corrections

The test temporarily requested one active replica and one preview replica.
With required app-wide anti-affinity, four Catalog Pods cannot fit on three
workers. Two active replicas were restored after rollback. This bounded
delivery proof does not establish two replicas per revision throughout overlap
or continued availability under an additional worker failure during that window.

An earlier attempt stopped because the collector indexed `spec.nodeName` on a
Pending Pod, where the field is legitimately absent. Cleanup restored the
original Catalog template. Its timeline, request samples and observations are
retained in `bluegreen-attempt1/`; the corrected observer handles an absent
node assignment, and the successful run used a fresh candidate revision.
No gate was skipped or weakened.

## Evidence

[Sanitized results and artifact hashes](evidence/2026-10-17/catalog-bluegreen.json)
include controller timelines, probe totals, backend routing attribution and
rollback timing. Raw results are private under
`load-results/kind-progressive-20261017T210750Z`. Temporary forwards and the
exclusive test lock were removed; original Catalog configuration and two Ready
active replicas were restored.
