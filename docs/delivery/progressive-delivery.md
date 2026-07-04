# Progressive Delivery

EuroTransit must demonstrate at least two progressive delivery strategies.

## Required Demonstrations

- Canary deployment for Orders, because it is on the critical money path.
- Blue/Green deployment for Catalog, because it is stateless and read-heavy.

## Strategies Not Used on the Critical Path

EuroTransit also documents where rolling and all-at-once delivery would fit, because they are valid delivery strategies but weaker choices for the checkout money path.

- **Rolling deployment:** Useful for low-risk stateless service updates, routine patching, or internal components where gradual pod replacement is enough. It is not the primary Orders strategy because it does not provide an explicit traffic percentage, metric-gated promotion, or simple abort decision for the critical checkout path.
- **All-at-once deployment:** Useful only for very low-risk changes, local/dev environments, or emergency rollback to a previously validated version. It is not used for Orders because the blast radius is immediate and there is no progressive exposure window.

Orders therefore uses canary for metric-gated exposure. Catalog uses blue/green because it is stateless, read-heavy, and easy to switch or roll back as a whole.

## Promotion Signals

Promotion should depend on observable behavior:

- checkout success rate;
- request latency;
- HTTP 5xx rate;
- circuit breaker state for critical dependencies;
- relevant application logs and traces.

## Abort Criteria

- Checkout success-rate burn exceeds the threshold defined in the canonical application SLO document.
- p95 checkout latency breaches the SLO during the canary window.
- Orders payment or inventory circuit breakers remain open beyond the configured alert window.
- Distributed traces show the new version adds unexplained latency or error concentration.
