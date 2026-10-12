# Issue #50: Orders canary guardrails

Issue: https://github.com/g05-eurotransit/EuroTransit-configuration/issues/50

Base: configuration `main` at `a6a5d9902a51c652d89ea2d97a73e172c7c9bbed`.

## Objective

Make Orders promotion decisions meaningful at demo traffic: sufficient evidence,
correct attribution, explicit error budgets, and documented Kafka exposure.

## Implementation sequence

1. Inspect the current chart, delivery runbook, application failure labels, and
   application PRs #127/#128. Read issue #46's runner changes for integration
   context without changing another worktree.
2. Define a low-volume analysis policy. Parameterize sample requirements,
   observation timing, and budgets in Helm values. Insufficient samples must
   prevent promotion. A sample guard alone does not make the existing 2% failure
   threshold meaningful; justify the selected checkout policy against expected
   business failures and actual fixture capacity. Keep high-volume/SLO claims
   distinct from demo evidence.
3. Correct the HTTP 5xx gate. A count budget for the canary is an acceptable demo
   policy if its lifetime scope, lazy-created series, and restart limitations
   are explicit. A ratio policy must address units, minimum samples, and the
   first-error visibility problem rather than merely replacing rate with increase.
4. Replace the DLT-reader counter with `orders_events_exhausted_total` and add
   a mandatory presence/coverage check. Missing required metrics must prevent
   promotion. Verify compatibility with application #127/#128; do not select
   an image tag without evidence that the artifact exists and includes both.
   If no compatible image can be established, preserve disabled delivery and
   document the concrete deployment prerequisite.
5. Update the delivery runbook: HTTP weights do not control Kafka partition
   assignment; record actual assignments and sample counts. Describe AKS
   capacity preflight and the relationship to #46 and #49. Keep #38 tracing
   as a separate prerequisite for tracing evidence, not an implementation task.
6. Verify Helm rendering with delivery enabled and disabled for kind and AKS,
   plus focused query/condition checks using synthetic counter scenarios where
   tooling permits. Cover healthy traffic, a real regression, expected business
   outcomes, insufficient samples, missing metrics, fresh series, and resets.
   Distinguish local verification from live cluster evidence.
7. Report changed files, chosen policy and rationale, checks, and outstanding
   integration prerequisites. Do not claim live promotion/abort evidence until
   run with the coordinated #46 harness.

## Ownership and boundaries

- Work only in `EuroTransit-configuration-issue50` on
  `fix/issue-50-orders-canary-guardrails`.
- Other sessions own #46–#49. Do not modify their worktrees, reset their changes,
  rewrite their harness, or perform concurrent cluster experiments.
- Application source is read-only for this task. Configuration operational docs
  should link to application contracts instead of duplicating them.
- No GitHub comments, push, PR publication, cloud changes, or deployment are
  included in this assignment. Prepare local reviewable changes and verification.

## Completion criteria

- HTTP error policy matches its declared units and observation scope.
- Checkout policy has an explicit evidence requirement and a defensible budget.
- Dead-letter failures are attributed to the emitting revision; absent required
  metrics cannot silently pass.
- The runbook states Kafka exposure and image/capacity prerequisites.
- Local checks pass; live validation dependencies on #46 are clearly recorded.

## Implementation progress

- Application `origin/dev` source confirms #127 (`4389f4f`) and #128
  (`3f04bcb`), including the six zero-registered exhaustion series and
  zero-registered checkout outcomes. Registry artifact availability is unverified.
- Chart policy now uses five-minute evidence, >=4 HTTP requests and >=4
  confirmed terminal outcomes, with strict zero absolute error budgets for
  the success-only fixture. Expected business failures invalidate that fixture;
  they are diagnosed separately rather than silently excluded from the gate.
- Per-instance coverage, process-age and observed reset/change checks prevent
  missing metrics and visible restart history from passing. Lifetime history
  lost before a scrape remains an explicit operational limitation.
- Runbook covers Kafka assignment, fixture/image/capacity prerequisites,
  actual evidence collection and independent #46/#49 integration ownership.
- Local Helm lint, enabled/disabled rendering for kind and AKS, and condition
  structure checks pass. `scripts/test-orders-canary-guardrails.py` generates
  actual rendered PromQL predicate tests for healthy/error/missing/low-sample/
  fresh-series/reset/duplicate-target scenarios. All 13 synthetic scenarios
  passed with `promtool` from `prom/prometheus:v3.5.0` in a temporary container
  with no network, a read-only fixture, and temporary test storage. No live
  cluster experiment ran.
