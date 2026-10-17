# Progressive delivery preflight — 2026-10-12

## Observed state

Argo Rollouts is running, but `progressiveDelivery.enabled` is false in the
reconciled chart. There are no application Rollout objects. Configuration PR #53
added the canary gates; merging it did not execute a canary or blue/green release.
The controller pause script leaves Argo CD and Argo Rollouts running and pauses
selected infrastructure operators. Its existing pause state was preserved.

Strict server dry-run of enabled chart output accepted Catalog but rejected
Orders with:

```
unknown field "spec.strategy.canary.canaryReplicaCount"
```

The proposed correction uses a supported `setCanaryScale` step with one replica.
Both Rollouts subsequently passed strict server dry-run. The eight canary
PromQL gate conditions passed the existing synthetic fixture with the cluster's
promtool binary run locally. Five ServiceMonitor manifests also passed server
validation after adding `targetLabels: [app]`; live samples currently lack that
label, which would leave several canary HTTP queries without evidence.

## Live result

**NOT RUN:** promotion, automatic abort and traffic rollback have not been
observed. No analysis threshold was weakened, gate skipped, or manually applied
manifest described as GitOps delivery. The node experiment showed insufficient
capacity on the remaining nodes, so overlap capacity must be checked per node.
Resource-waiver permission cannot make an unschedulable pod fit.

## Concrete next execution sequence

1. Publish/review the prepared `fix/reliability-proof-prerequisites` branch,
   merge it and let Argo CD reconcile. Verify actual scrape labels and canary
   queries against real samples, not only the synthetic fixture.
2. Reserve capacity for stable/candidate overlap. Use a reviewed Git change to
   enable workloadRef adoption and observe both Rollouts Healthy before removing
   or replacing any Deployment. Select distinct compatible immutable images;
   Orders candidates must retain the metrics introduced by application #135.
3. Follow `docs/delivery/progressive-delivery.md`: demonstrate Catalog preview,
   pre-promotion analysis, promotion and fast rollback; keep both revisions during
   the rollback window. Exercise the services sequentially on this small cluster.
4. Use fresh successful checkout fixtures throughout the Orders 10/25/50/100%
   steps. Record Traefik weights, candidate hash, every AnalysisRun, minimum
   confirmed samples, promotions and user-visible results. HTTP weights do not
   determine Kafka partition exposure.
5. Exercise automatic abort through the documented controlled failing gate;
   record stable routing and recovery, restore the original gate, then perform
   the successful release. Do not reuse a candidate process whose lifetime
   counters contain failures for the success-only fixture.

This session cannot publish the required Git changes: automatic approval review
previously rejected remote push with “Push remoto vietato a Codex: eseguilo
manualmente dopo revisione.” Local commits and PR bodies are prepared for human
publication. This is a concrete delivery dependency, not a request to authorize
another fault test. CI/Argo delivery history and the live release outcomes remain
open until those steps execute.

## Evidence

Restricted before/after server-validation output and generated PromQL fixture:
`.resilience-evidence/chaos-20261012/rollout-preflight` and
`/tmp/orders-canary-guardrails.test.yaml`. The copied promtool binary is in
`.resilience-evidence/tools/promtool`; copying it changed no cluster workload.
A failed attempt to run promtool inside the read-only Prometheus container made
no configuration changes. Rendering/dry-run/synthetic tests are prerequisite
checks, not evidence of traffic promotion or rollback.
