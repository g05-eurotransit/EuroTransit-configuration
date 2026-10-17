# Payments latency without probe disruption — 2026-10-17

## Question and preceding evidence

Configuration [#60](https://github.com/g05-eurotransit/EuroTransit-configuration/pull/60)
reports that five of six orders confirmed automatically on Orders `45357ef`.
The sixth had an authorization but exhausted delivery; redrive arrived after its
hold expired, and operator abandonment refunded it and ended it FAILED. It was
not a sixth confirmed order.

That experiment delayed all Payments TCP responses from port 8080 by 4000ms.
Readiness and liveness also use port 8080, with a 2s timeout; Payments became
NotReady and restarted. The report explicitly calls this latency plus restart,
with approximately 75s total disruption. It does not isolate a 45s dependency
latency fault. The observed exhaustion alone therefore does not demonstrate a
new Payments defect or justify extending the bounded recovery policy.

The proposed hypothesis for this verification is the same bounded latency case:
Orders' breaker opens while Catalog stays available, then accepted orders
converge without operator action after the fault heals. Team review owns this
hypothesis and the acceptable latency/error-budget impact.

## Controlled verification

Run `et-pay-pure-74a6ce370600` used six fresh fixtures, two VUs and the existing
configuration-owned k6 runner. Orders already ran `45357ef`, containing #139 and
#141. No application image, retry budget, probe or GitOps configuration changed.
Health checks passed; the existing user authorization waived only resource
saturation for bounded workstation traffic, not health or fixture ownership.

An ephemeral netshoot container, pinned to
`sha256:147f2c4cb0aa7a741151bce2bfef71d9e1a04631636e24665ee2a5ed799feb47`,
used only NET_ADMIN with other capabilities dropped, no privilege or host
networking. Its qdisc delayed outbound IPv4 TCP responses from port 8080 **only
to the captured Orders pod IP /32**. The kubelet and monitoring destinations
were outside that filter. Both pod UIDs/IP scope were checked; this method must
be invalidated if the target Orders pod is replaced during a run.

The filter matches transport traffic, including TCP handshake packets; it is
not an application handler sleep or a URL-specific delay. Its independent timer
removed it after 45s. Logs contain actual delayed packet counts and restoration
to `qdisc noqueue`, from **08:56:36 to 08:57:21 UTC**. No replica, resource limit,
Service routing, business SQL row or consumer offset was changed.

## Observations

| Observation | Result |
| --- | --- |
| First Payments breaker OPEN | 08:57:01.261 UTC |
| First HALF_OPEN | 08:57:18.262 UTC |
| First CLOSED after OPEN | 08:57:23.368 UTC |
| Catalog probes | 50/50 HTTP 200; nearest-rank p95 145.82ms |
| Payments readiness samples | 50/50 Ready |
| Payments container restarts | 5 before, 5 after; same Pod UID |
| First authorization persisted | 08:56:44.198 UTC, during the fault |
| Confirmation audit events | Six, from 08:57:22.658 to 08:57:27.426 UTC |
| Last confirmation after fault removal | Approximately 6.43s |
| Operator redrive, replay or compensation | None |
| Run-owned reconciliation rows | Zero, including resolved records |
| Final correctness audit | VERIFIED, zero violations |
| Independent Stripe sandbox extraction | All pages read; six matching charges, zero unmatched charges |

The first authorization existed well before healing while Orders still awaited
a usable response. Its automatic retry converged under the existing idempotent
money path. The scoped final database/provider verification found no duplicate
reservation, charge or seat ownership violation. Its guarantee is bounded to
this evidence window, not all future traffic.

The **original client harness failed with exit 99**: two of six client polling
cycles exceeded their completion deadline, recording ACCEPTED/PAYMENT_PENDING.
The other four completed within their polling windows. The original ledger and
failed verdict are unchanged. A separate, explicitly labelled derived final-state
audit uses fresh API/database observations after automatic convergence; it does
not convert the original client run into a pass or demonstrate the normal
checkout latency SLO during an injected four-second delay.

## Conclusion and follow-up

The bounded pure-latency hypothesis held for breaker containment, Catalog
isolation and automatic final convergence of all six orders with unique payment
and reservation effects. The client completion-deadline criterion failed for two
orders. No new operational Orders/Payments change is proposed from this result.

Keep #60 as the historical compound-fault/runbook result. Longer outages,
Payments process crashes and service restart recovery remain distinct cases;
this run neither makes them pass nor proves every provider failure safe. The
injection-method correction is to scope delayed traffic to Orders, preserving
probes, rather than increasing liveness timeouts or retry budgets to mask it.
Team review must assess the original operator response window and SLO impact.

## Evidence and cleanup

[Sanitized verification summary](evidence/2026-10-17/payments-pure-latency-summary.json)
contains aggregate outcomes, timestamps and source artifact hashes only.
Restricted fault metadata, logs, packet counters, pod samples and reconciliation
SELECT output are under `.resilience-evidence/payments-20261017/payments-pure-latency-20261017T085630Z`
in the workspace. Source run artifacts are in
`load-results/payments-pure-latency-20261017T085630Z`; the verified derived audit
is `load-results/payments-pure-latency-20261017T085630Z-final-audit-20261017T085745Z`.
Raw provider references, order IDs and credentials are not published.

The fault container terminated after its independent cleanup. The added
19180/19190 port-forwards were removed after collection; user-owned forwards and
existing controller pauses were preserved. No permanent rollout or deployment
was performed.
