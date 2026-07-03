# Chaos Experiment Reports

## 1. Latency injection into Payments
- **Steady State (SLIs):**
- **Hypothesis:** Does the Orders circuit breaker open and the fallback engage, while Catalog browsing stays healthy?
- **Observation:**
- **Conclusion / Changes Made:**

## 2. Pod kill on Inventory mid-reservation
- **Steady State (SLIs):**
- **Hypothesis:** Does idempotency plus the reservation model prevent oversell or double-charge?
- **Observation:**
- **Conclusion / Changes Made:**

## 3. Node / AZ-style disruption
- **Steady State (SLIs):**
- **Hypothesis:** Do PDBs and topology spread keep the critical path available?
- **Observation:**
- **Conclusion / Changes Made:**

## 4. Network partition / Kafka disruption
- **Steady State (SLIs):**
- **Hypothesis:** Does the async pipeline recover and converge once the partition heals? Does anything get lost or duplicated?
- **Observation:**
- **Conclusion / Changes Made:**

## 5. Pod-failover of the CloudNativePG primary
- **Steady State (SLIs):**
- **Hypothesis:** What is the observed impact on checkout, and does the system recover within your stated RTO?
- **Observation:**
- **Conclusion / Changes Made:**
