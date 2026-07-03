# Progressive Delivery

EuroTransit must demonstrate at least two progressive delivery strategies.

## Required Demonstrations

- Canary deployment for Orders, because it is on the critical money path.
- Blue/Green deployment for Catalog, because it is stateless and read-heavy.

## Promotion Signals

Promotion should depend on observable behavior:

- checkout success rate;
- request latency;
- HTTP 5xx rate;
- circuit breaker state for critical dependencies;
- relevant application logs and traces.
