# Chaos Experiment Reports

This file is the execution report template for the required chaos experiments. The canonical experiment plan lives in the sibling application repository at `../EuroTransit-application/docs/operations/chaos-experiments.md`.

Do not fill this document with expected results. Each section must be completed after the experiment runs, with links or references to dashboard screenshots, traces, logs, injected fault configuration, observed outcome, and follow-up changes.

## 1. Latency injection into Payments
- **Steady State (SLIs):**
- **Hypothesis:** Does the Orders circuit breaker open and the fallback engage, while Catalog browsing stays healthy?
- **Injected Fault:**
- **Observation:**
- **Evidence:**
- **Conclusion / Changes Made:**

## 2. Pod kill on Inventory mid-reservation
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
