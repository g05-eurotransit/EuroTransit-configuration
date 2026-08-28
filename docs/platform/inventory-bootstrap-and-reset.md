# Inventory bootstrap and transactional reset

Inventory schema changes are owned by versioned Flyway migrations in the
application image. Demo capacity is deliberately separate: Argo CD first waits
for the Inventory Deployment at sync wave `-2`, then executes the idempotent
`inventory-bootstrap` Sync hook at wave `-1`.

The bootstrap creates seats `1A` through `6D` for the five demo routes, for
every date from the database current date through six calendar months. It uses
`ON CONFLICT DO NOTHING`, so another sync fills only missing capacity and never
overwrites seats that are already held or sold. There is no dependency on a
specific Flyway version: Inventory readiness is the migration gate, and an
incompatible schema makes `psql` fail with `ON_ERROR_STOP`.

## Development-cluster reset

Reset only during an announced maintenance window. Pause Argo CD automation for
the platform root, marketplace and connectors, pause the Orders and Inventory
Debezium connectors, and scale Orders, Inventory and Payments to zero. For each
of `orders_db`, `inventory_db` and `payments_db`, recreate only the `public`
schema and assign it to its existing database owner. Do not delete the
CloudNativePG cluster, databases, roles, secrets, Kafka topics or Keycloak.

After syncing the new marketplace revision, verify that Inventory completed all
Flyway migrations before the bootstrap hook, that every route/date contains 24
distinct seats, and that a second bootstrap run changes neither the row count
nor held/sold state. Resume the Debezium connectors and Argo CD automation only
after all services and connectors report Ready.
