# Chaos Experiment Reports

This file is the execution report template for the required chaos experiments. The canonical experiment plan lives in the sibling application repository at `../EuroTransit-application/docs/operations/chaos-experiments.md`.

Do not fill this document with expected results. Each section must be completed after the experiment runs, with links or references to dashboard screenshots, traces, logs, injected fault configuration, observed outcome, and follow-up changes.

## 1. Latency injection into Payments

Execution tooling: [temporary proxy and runbook](../../platform/reliability/payments-proxy/README.md). Record baseline, neutral proxy baseline, fault, recovery, and direct-route restoration separately. A capacity failure is not a completed experiment.

- **Run ID / application image digests / configuration revision:**
- **Preflight and approved hypothesis/SLO thresholds:**
- **Lease creation / independent expiry / explicit reset evidence:**
- **Breaker transitions / bounded retries / Catalog isolation:**
- **Reconciliation incidents and operator redrive, if required:**
- **Steady State (SLIs):**
- **Hypothesis:** Does the Orders circuit breaker open and the fallback engage, while Catalog browsing stays healthy?
- **Injected Fault:**
- **Observation:**
- **Evidence:**
- **Conclusion / Changes Made:**

## 2. Pod kill on Inventory mid-reservation

Use the same runbook with one UID-conditioned pod deletion. Record temporal overlap with an in-flight reservation before claiming "mid-reservation"; otherwise state "pod kill under contention".

- **Run ID / fixture / killed pod UID / replacement readiness:**
- **In-flight overlap evidence (or explicitly unavailable):**
- **HTTP retry and original-event replay source IDs:**
- **Read-only seat/reservation/authorization invariants:**
- **External provider audit for no-double-charge claim:**
- **Steady State (SLIs):**
- **Hypothesis:** Does idempotency plus the reservation model prevent oversell or double-charge?
- **Injected Fault:**
- **Observation:**
- **Evidence:**
- **Conclusion / Changes Made:**

## 3. Node / AZ-style disruption
- **Steady State (SLIs):**
- **Hypothesis:** Do PDBs and topology spread keep the critical path available?
- **Injected Fault:**
- **Observation:**
- **Evidence:**
- **Conclusion / Changes Made:**

## 4. Network partition / Kafka disruption
- **Steady State (SLIs):**
- **Hypothesis:** Does the async pipeline recover and converge once the partition heals? Does anything get lost or duplicated?
- **Injected Fault:**
- **Observation:**
- **Evidence:**
- **Conclusion / Changes Made:**

## 5. Pod-failover of the CloudNativePG primary
- **Steady State (SLIs):**
- **Hypothesis:** What is the observed impact on checkout, and does the system recover within your stated RTO?
- **Injected Fault:**
- **Observation:**
- **Evidence:**
- **Conclusion / Changes Made:**
