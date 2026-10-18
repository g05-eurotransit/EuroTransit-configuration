# Promote, abort and roll back workloads

Use Argo Rollouts for Orders canary and Catalog blue/green. [GitOps](../platform/gitops.md) defines controller ownership and ordering; application [ADR-003](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/design/architecture-decisions.md#adr-003-progressive-delivery) owns the strategy rationale. [Kind delivery reports](../verification/README.md#kind) record measured controller behavior, not CI delivery of a new application binary.

## Prerequisites

```bash
kubectl -n argo-rollouts get deployment argo-rollouts
kubectl -n eurotransit get rollout,deployment
kubectl -n eurotransit get kafka,kafkatopic,kafkaconnect,kafkaconnector
```

Require healthy broker/topics, actual RUNNING connector tasks, successful baseline checkout, scrape targets with real samples and capacity for stable/candidate overlap plus the selected load Job. [Capacity qualification](../platform/capacity.md) and [controlled maintenance](gitops.md#controlled-maintenance) own those checks. Run Orders and Catalog exercises separately on the constrained cluster.

Before enabling the AKS load client, provision matching `eurotransit-load-test-credentials` in both namespaces through the sealing workflow. Its confidential client uses service-account `customer`, not a demo-user password. [Identity recovery](identity-recovery.md) covers failed or changed bootstrap Jobs.

The first controller migration uses `workloadRef` to adopt existing Deployments safely. Keep each Deployment until its Rollout is Healthy. Moving the Pod template into an independent Rollout and deleting the old Deployment is a separate reviewed migration, not part of ordinary promotion.

## Prepare controlled traffic

The configured k6 CronJob is suspended; create a finite Job only in the coordinated test window:

```bash
kubectl -n eurotransit create job --from=cronjob/progressive-delivery-k6 pd-k6-$(date +%s)
kubectl -n eurotransit logs -f job/<created-job-name>
```

The Job checks the Catalog preview/public route and expected offer before buying fresh one-seat fixtures through Traefik. Its configured two-VU, 45-minute default can create up to 360 real sandbox purchases and must fit both capacity and provider limits. Credentials use the technical client, with tokens refreshed for each checkout cycle.

Verify the Inventory bootstrap horizon and unused date/seat block before starting. Exact duration, pacing, fixture range and provider-token input live in [chart values](../../charts/eurotransit/values.yaml) and [the k6 template](../../charts/eurotransit/templates/progressive-delivery-jobs.yaml). Reusing a consumed block is not a valid rerun; select a reviewed non-overlapping block. Never delete business rows, outbox state or idempotency records to make fixtures reusable. The [general load runner](load-tests.md) is an alternative with explicit claims, collection and independent audit.

## Catalog blue/green

1. Change only the reviewed Catalog image reference and reconcile it through Git.
2. Verify preview health, real `catalog-preview` responses and the public route while traffic continues.
3. Promote the preview:

   ```bash
   kubectl argo rollouts promote catalog -n eurotransit
   ```

4. During the configured old-revision retention window, abort to demonstrate rollback and verify the public route returns to the retained revision. Record before/after image digests, preview/public results and rollback time.

The configured retention is the rollback opportunity, not a guarantee that any later image rollback preserves database compatibility.

## Orders canary

1. Verify the candidate exposes the metric families required by the deployed AnalysisTemplates. A source merge or successful render does not establish that its published image contains them.
2. Start controlled traffic and update only the reviewed Orders image reference. At each configured 10/25/50% pause inspect `orders-weighted`, candidate samples, AnalysisRuns and financial evidence before promotion.
3. Use `kubectl argo rollouts promote orders -n eurotransit` only after the ordinary gates pass. Record the 100% pause/read check and final Healthy state.
4. To check automatic abort wiring, temporarily make a real AnalysisTemplate threshold impossible, start a new candidate and observe Failed/Aborted plus stable-route recovery. Restore the ordinary threshold in Git immediately. This diagnostic is separate from a real regression causing the ordinary gate to abort.

```bash
kubectl -n eurotransit get rollout,analysisrun
kubectl -n eurotransit get traefikservice orders-weighted -o yaml
kubectl -n eurotransit describe rollout orders
kubectl -n eurotransit logs job/<k6-job>
```

## Gate interpretation

Exact thresholds/windows and routing configuration belong to [values](../../charts/eurotransit/values.yaml), [Orders rollout](../../charts/eurotransit/templates/progressive-delivery.yaml) and [analysis templates](../../charts/eurotransit/templates/progressive-delivery.yaml). They define a controlled demonstration policy, separate from the team's rolling production SLO.

The gate needs candidate-hash HTTP and terminal samples, zero lifetime error/exhaustion signals under its policy, latency evidence, healthy scrape targets and continuity without process/counter reset. Empty/missing data cannot promote. A failed k6 check, unavailable fixture, missing metric, insufficient sample population, restart or unobserved canary assignment blocks promotion. Reconciliation/database-wide gauges are diagnostic, not version-specific outcomes. Tracing is a separate delivery requirement, not implemented by these metric gates.

Compatible application artifacts must include producer-side exhausted-event attribution and zero registration of required checkout series. The DLT reader's `orders_events_dlt_total` identifies that reader, not the pod that exhausted retries. Inspect actual scraped series before the exercise. Gate PromQL must deduplicate overlapping scrape paths per instance rather than double-count a process.

## Kafka exposure and evidence

HTTP weights do not determine Kafka exposure. Stable/canary processes share the Orders consumer group; with two consumers and three balanced partitions, a canary can process roughly one-third or two-thirds of records despite a 10% HTTP weight. Assignments, skew and rebalances change that population. An HTTP-accepting revision can differ from the Kafka-processing revision.

For every step retain image digest, rollout hash, Pod UIDs/restarts, actual HTTP weights and samples, per-pod confirmed/failed/exhaustion counters, original load outcomes and independent provider evidence. Inspect the deployed group ID and assignments for both checkout/refund topics:

```bash
kafka-consumer-groups.sh --bootstrap-server <internal-bootstrap> \
  --describe --group <actual-orders-group> --members --verbose
```

Use configured broker authentication. Do not infer assignment from Pod counts, HTTP weights or database totals. [Readiness](../readiness.md) owns remaining release evidence; [reports](../verification/README.md) retain manual audit qualifications and original failed outcomes.
