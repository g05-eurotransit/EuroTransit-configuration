# CloudNativePG primary pod failover

## Steady state and proposed hypothesis

The normal AKS deployment has one PostgreSQL instance. For this experiment only,
its owning Argo Application policy was saved and automatic reconciliation paused;
CNPG instances increased to two, leaving the CNPG operator running. Existing
controller pauses remained unchanged. The physical standby on a different node
was Ready and had replayed a fixed pre-test WAL position before injection.
Replication was asynchronous; this is not a synchronous zero-RPO configuration.

Proposed hypothesis: CNPG promotes the Ready standby after a primary-pod crash,
restores database-backed checkout reads, and accepted checkout work converges
without duplicate effects. The team must approve an RTO; no team-owned RTO was
specified for this run, so timings below are measurements, not an RTO pass.

## Fault and observed recovery

Run `et-pg-cc251ce6b763` made six ramp attempts with two VUs. At
**22:34:32.563 UTC**, a UID-conditioned force deletion killed primary
`eurotransit-postgres-1`, UID `110fb912-8613-4ea5-8872-8ed47878f774`.
Its Ready physical standby `eurotransit-postgres-4` became the new primary.

| Observation | Result |
| --- | --- |
| First sample naming new primary | 22:34:36.073 UTC, approximately 3.51s after injection |
| Orders GET sample at that time | HTTP 500 |
| First subsequent Orders GET HTTP 200 | 22:34:37.673 UTC, approximately 5.11s after injection |
| Client verdict | Failed, exit 99 |
| Attempts | Three HTTP 202 accepted; three HTTP 500 |
| Accepted work without intervention | Two CONFIRMED; one RESERVING with DELIVERY_EXHAUSTED incident |
| Failed-request key audit | Only the three accepted requests had idempotency records |
| Scoped recovery | Exact three original order-placed events replayed once |
| Final accepted-order audit | 3/3 CONFIRMED, VERIFIED, zero violations |
| Independent Stripe audit | Three matching sandbox charges, zero unmatched charges |

Sampling is approximately once per second and includes request overhead. A
successful GET does not establish successful new checkout completion. The
nonterminal order remained RESERVING throughout twelve further observations;
its failed pre-replay audit is preserved. Operator replay was required for final
money-path convergence. The unchanged original ledger retains the HTTP failures.
The connector status endpoint showed all three Debezium connector tasks RUNNING.

Cleanup restored one CNPG instance and the exact original Argo sync policy.
CNPG retained the promoted primary, and subsequently reported healthy 1/1.
No manual PVC deletion, SQL business correction or consumer-offset reset was
performed. Standby setup was temporary runtime instrumentation, not a GitOps
HA deployment or proof that the ordinary single-instance deployment tolerates
primary failure.

Two preceding setups injected no fault: a conservative moving-WAL lag check
was corrected to a fixed physical-replica position, and a later client setup
failed the seat-map precheck. They are excluded from failover evidence and their
setup changes were restored before this run.

## Conclusion and evidence

Primary promotion and database-backed read recovery were automatic. Continuous
checkout availability and automatic completion of every accepted order did not
hold. Final money-path correctness held after explicit recovery. Adopt reviewed
HA configuration, define the checkout recovery objective and improve exhausted
work recovery before treating this as a complete availability proof.

Restricted state snapshots, WAL check, primary observations, idempotency-key
audit and cleanup: `.resilience-evidence/chaos-20261012/postgres-failover-20261012T223334Z`.
Original run: `load-results/postgres-failover-20261012T223334Z`.
Failed automatic-convergence audit:
`load-results/postgres-accepted-orders-final-audit-20261012T223720Z`.
Recovered final audit:
`load-results/postgres-after-replay-final-audit-20261012T223758Z`.
