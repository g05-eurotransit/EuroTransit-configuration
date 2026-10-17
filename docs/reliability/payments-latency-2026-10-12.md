# Payments latency experiment — 2026-10-12

## Steady state and hypothesis

The preceding bounded ramp/spike runs confirmed all 16 orders with unique
reservations and independently audited provider effects. Orders ran `bad4c04`;
Inventory and Payments ran `98bedf2` from the EuroTransit ACR namespace.

Proposed hypothesis: a slow Payments dependency opens the Orders Payments
breaker, bounds remote waiting and leaves Catalog available. Removing the fault
should allow recovery; automatic convergence and operator-assisted recovery
are assessed separately. This observed report requires team review of the
hypothesis, acceptable impact and conclusions.

## Fault and observations

An ephemeral container in the single Payments pod network namespace used only
the `NET_ADMIN` capability to attach a `netem` filter to IPv4 TCP source port
8080. HTTP responses were delayed by 4000ms from **21:54:24 to 21:55:09 UTC**.
The injector removed the qdisc after 45 seconds independently of the client.
A subsequent read-only check found the original `noqueue` qdisc and Payments
readiness HTTP 200. No host network, Service routing or GitOps settings changed.
The official netshoot image was pinned to digest
`sha256:147f2c4cb0aa7a741151bce2bfef71d9e1a04631636e24665ee2a5ed799feb47`.
The terminated ephemeral-container records remain on the pod; they run no work.

Resource-saturation overrides were authorized for bounded workstation traffic:
six attempts with two VUs during the fault, then two sequential recovery attempts.
Other runner checks and fixture/run ownership remained active. No new application
replica or application image was introduced.

| Observation | Result |
| --- | --- |
| First observed Payments breaker OPEN | 21:54:36 UTC |
| Breaker sample coverage | 129 one-second observations; CLOSED, OPEN and HALF_OPEN seen |
| Catalog probes | 129/129 HTTP 200; p95 137.5ms |
| Fault-run client result | Harness failed; six orders remained PAYMENT_PENDING at collection |
| First recovery run | Harness failed; one confirmed, one PAYMENT_PENDING |
| Exhausted-delivery behavior | Durable DELIVERY_EXHAUSTED reconciliation incidents |
| Automatic convergence after fault removal | Not demonstrated; affected orders required explicit replay |
| Final state after replay | 8/8 CONFIRMED |
| Final independent Stripe audit | 8 matching sandbox charges, no unmatched charges |
| Final correctness audit | VERIFIED, zero violations |

The initial client ledgers and failed harness verdicts remain unchanged. Recovery
replayed only exact collector-exported original events for the two run-owned
order sets (six and two events), through the existing broker. No SQL business
records were edited. The first replay's six orders converged; the second recovered
the remaining pending order. The already confirmed order was safely skipped.

The final audit uses a clearly labelled derived final-state ledger, based on
fresh authenticated API observations after replay, and a single provider window
covering both source runs and recovery. It does not turn either original load
test into a passing harness result. Provider completeness applies to that bounded
window, not future charges. The original collector did not capture Kafka lag;
the later [Kafka audit](kafka-disruption-2026-10-12.md) identifies the existing
client metric and documents the collector correction.

## Conclusion and follow-up

Breaker activation and Catalog isolation held. The safe fallback was durable
pending work plus an explicit reconciliation incident after bounded retries;
it was not a cached success or an automatic confirmation. This experiment
does not establish an automatic recovery RTO. Operations must be able to detect
and recover these incidents; the team must decide whether that outcome meets
its recovery objective before marking the full hypothesis successful.

## Evidence

Restricted injection metadata, logs, breaker/Catalog observations and recovery
scripts are retained under
`/home/matteo/projects/.resilience-evidence/chaos-20261012`.
Source load artifacts are in `load-results/payments-latency-20261012T215402Z`
and its `-recovery` directory. The final cross-run audit is in
`load-results/payments-final-audit-20261012T220058Z`.
Raw artifacts, provider references and credentials are excluded from Git.
