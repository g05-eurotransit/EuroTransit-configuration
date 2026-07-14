# Kind incident report: payment authorized, order failed

## Summary

On 2026-07-14, during a checkout in the local Kind environment, Stripe test
mode successfully authorized a payment, but Orders subsequently marked the
order as `FAILED`.

The failure happened after the external payment authorization and its local
database commit. Payments then attempted to publish the `payment-authorized`
event to Kafka, but the topic did not exist. The Kafka producer waited for
topic metadata while the Orders-to-Payments call exceeded its three-second
timeout. Orders therefore treated the checkout as failed and compensated the
Inventory reservation.

This incident produced a cross-service consistency gap:

```text
Orders:   FAILED
Payments: AUTHORIZED
Inventory reservation: CANCELLED
Stripe:   authorized test-mode charge
```

No real money was moved because Payments was configured with a Stripe
test-mode key (`sk_test_...`).

## Incident scope

- Environment: local Kind cluster
- Date: 2026-07-14
- Affected checkout correlation ID:
  `67e62693-32fc-437f-889c-96178618d3f8`
- Affected order ID:
  `7e73b139-0440-4478-b88f-01f6d2f14e40`
- Payment idempotency key:
  `pay-7e73b139-0440-4478-b88f-01f6d2f14e40`

The provider reference is intentionally omitted from this report. It remains
available in the local Payments database for test-mode reconciliation.

## Observed sequence

1. Orders started the checkout pipeline.
2. Inventory successfully reserved the requested seat.
3. Payments called `POST https://api.stripe.com/v1/charges` using a valid
   Stripe test-mode key.
4. Stripe returned a successful authorization.
5. Payments persisted one `AUTHORIZED` payment authorization and the related
   idempotency record with response code `200`.
6. Payments attempted to publish to the Kafka topic `payment-authorized`.
7. Kafka repeatedly returned `UNKNOWN_TOPIC_OR_PARTITION` because the topic
   was absent from the Strimzi desired state.
8. Orders did not receive a terminal response within the configured
   three-second Payments client timeout.
9. Orders marked the order `FAILED` and released the Inventory reservation.
10. Payments remained `AUTHORIZED`, leaving the order and payment states
    inconsistent.

The `JobCancellationException` recorded by Payments was a consequence of the
upstream request timeout and cancellation, not the root cause.

## Root cause

The application publishes money-path events to topic-specific Kafka topics,
including `payment-authorized`, while the Strimzi configuration originally
declared only the generic `payment-events` topic. Kafka topic auto-creation was
not available for this workflow, so the producer could not obtain metadata for
the topic used by the code.

The missing topic was therefore a contract mismatch between application event
names and the Kubernetes/Strimzi desired state.

## Contributing factors

### Payment state was committed before event publication

Payments performs the provider call and commits the authorization and
idempotency records before invoking `KafkaTemplate.send`. Event publication is
not part of the same durable transaction or an outbox workflow. A Kafka
failure can consequently leave an authorized payment without a corresponding
published event or successful response to Orders.

### Orders used a shorter timeout than the downstream payment workflow

The Orders Payments client has a three-second timeout, while Payments can call
an external provider, persist database records, initialize a Kafka producer,
and publish an event. The timeout exposed the missing-topic problem quickly,
but it is also tight for the complete downstream operation.

Increasing the timeout alone would not solve the consistency defect; it would
only delay failure when Kafka is unavailable.

### No automatic post-authorization compensation

Orders releases Inventory after a checkout failure, but automatic payment
refund/reversal is not wired for the window in which payment authorization has
succeeded and a later checkout step fails. The application logs that manual
refund or reconciliation may be required.

### Deployment smoke tests did not validate every application topic

The existing Kind smoke test verified deployments and basic HTTP endpoints,
but did not compare application producer/consumer topic names with the
Strimzi-managed Kafka topics or execute the complete payment event path.

## Duplicate-charge assessment

The request was retried, but the incident did not create duplicate Stripe
charges for the affected order.

Payments used the stable idempotency key
`pay-7e73b139-0440-4478-b88f-01f6d2f14e40`, and the Stripe adapter prefixed it
consistently for provider requests. The Payments database contains one
authorization record and one idempotency record for the order.

A new order uses a new idempotency key and therefore creates a separate Stripe
test-mode payment, as expected.

## Corrective actions completed

The missing application topics were added to
`platform/strimzi/kafka-topics.yaml`:

- `order-confirmed`
- `payment-authorized`
- `payment-declined`
- `payment-refunded`
- `payment-refund-failed`

The existing Kind Kustomize patch sets their replication factor to `1`, which
matches the single-broker Kind topology. All five topics reached the Strimzi
`Ready=True` condition.

Payments and Orders were restarted to clear pending producer state and client
circuit-breaker state. The Kind smoke test passed after the change.

The affected order is not retroactively repaired by topic creation. Its local
test-mode payment remains `AUTHORIZED` while the order remains `FAILED` and
must be explicitly refunded or reconciled.

## Recommended follow-up actions

1. Implement a Payments outbox so the authorization state and event intent are
   committed atomically, with asynchronous and retryable Kafka publication.
2. Add automated reconciliation for `AUTHORIZED` payments whose Orders state
   is `FAILED` or does not become `CONFIRMED` within a defined interval.
3. Implement an explicit refund/reversal step when checkout fails after payment
   authorization.
4. Add a deployment validation that compares all application Kafka topic names
   with the Strimzi desired state.
5. Extend the Kind end-to-end test to cover reserve, authorize, confirm, event
   publication, notification, and compensation paths.
6. Review the three-second Orders-to-Payments timeout after the durable event
   publication design is corrected.
7. Alert on the condition `Orders=FAILED` combined with
   `Payments=AUTHORIZED`.

## Current status

- Stripe credential injection: fixed and verified in the Payments pod.
- Required Kafka topics: created and `Ready`.
- Payments and Orders deployments: successfully rolled out.
- Kind smoke test: passing.
- Affected historical order: still requires test-mode refund or
  reconciliation.
- Full browser checkout after the topic fix: still to be confirmed separately;
  the infrastructure failure described in this report is resolved.
