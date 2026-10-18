# Notifications stopped while checkout succeeds

## Steady state and proposed hypothesis

All application services were Ready after the preceding experiments. Proposed
hypothesis: stopping the entire Notifications JVM must leave checkout functional,
while notification consumption catches up after it resumes. The team must review
acceptable notification delay and this hypothesis.

## Fault and observations

An ephemeral container targeted only the Notifications process namespace and
used KILL (without privilege or host networking) to send SIGSTOP to Java PID 1.
The process was stopped from **22:39:55 to 22:40:20 UTC**. An independent
25-second timer and cleanup trap sent SIGCONT. No Deployment scaling, routing,
GitOps setting or business data changed. The netshoot image was digest-pinned.

The four sequential checkout attempts ran from **22:39:59.964 to
22:40:09.234 UTC**, entirely inside the stop interval. All received HTTP 202 and
reached CONFIRMED while Notifications could execute no code. The original
harness passed (exit 0). Original and final-state correctness verifications both
returned VERIFIED with zero violations. Independent Stripe audits found four
matching charges and no unmatched effects.

After SIGCONT, the broker-side `notifications` group description showed committed
offset equal to log end on all three `notification-requested` partitions:
97/97, 101/101 and 120/120. This proves group catch-up, not external email delivery
or exclusive processing of just these four messages. No consumer-offset reset or
manual event replay was used. The original pod UID was preserved.

One earlier attempt stopped at an ephemeral-container startup check before
SIGSTOP; it is excluded from failure evidence.

## Conclusion and evidence

Checkout independence from a completely stopped Notifications process held for
this bounded interval. Consumption caught up after resumption. This test does
not prove notification-history durability across restart or a third-party
notification delivery guarantee. Those are separate from checkout degradation.

Restricted injector log, group offsets and result:
`.resilience-evidence/chaos-20261012/notifications-down-20261012T223951Z`.
Original run: `load-results/notifications-down-20261012T223951Z`.
Final audit: `load-results/notifications-down-20261012T223951Z-final-audit-20261012T224038Z`.
Resource saturation was waived for bounded workstation traffic; other runner
checks remained active. Injector cleanup restored the running JVM.
