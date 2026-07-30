# EuroTransit Local Kind Setup

Kind is the Kubernetes acceptance environment. Docker Compose remains useful
for the fastest application-only loop.

## Prerequisites

Install Docker, Kind, kubectl, Helm, Just, curl and `rg`. Keep
`EuroTransit-configuration` and `EuroTransit-application` in the same parent
directory, or set `EUROTRANSIT_APP_DIR` explicitly.

For the integral profile, allocate Docker Desktop at least 8 GiB RAM and 20
GiB free disk. The stack includes Kafka, PostgreSQL, Debezium, Keycloak and
five JVM services; a smaller Docker VM can make the Kind control plane
unresponsive while all workloads start.

## Start And Test

```bash
just render-kind
STRIPE_SECRET_KEY=sk_test_... just kind-up
just kind-test
```

`kind-up` creates a single-node cluster when absent, builds the application
images and the custom Debezium Kafka Connect image from the application
repository, loads them into Kind, installs the controllers, creates
development-only secrets, and deploys the runtime and application chart. It is
safe to run again.

`STRIPE_SECRET_KEY` is required and must be a Stripe test-mode secret key.
The bootstrap writes it directly to the `payments-provider-credentials`
Kubernetes Secret; it is not stored in this repository. Live-mode keys are
rejected in Kind.

Kind intentionally uses one node to limit workstation disk and memory usage;
the three-node topology is validated only on the assigned AKS cluster.

The build uses the application repository's unified `Dockerfile` for all five
Spring Boot services. Gradle compilation runs inside the builder stage, while
Docker reuses the cached bootstrap and production dependency layers.
`connect/Dockerfile` separately builds the Strimzi-compatible Kafka Connect
runtime with the pinned Debezium PostgreSQL plugin.

To reuse images already built on the workstation:

```bash
STRIPE_SECRET_KEY=sk_test_... SKIP_BUILD=1 just kind-up
```

The default profile includes Traefik, cert-manager, CloudNativePG, Strimzi,
Keycloak, Debezium and the five backend services. It excludes Prometheus,
Grafana, Argo CD and Chaos Mesh to keep startup and memory use reasonable.
Keycloak runs through the official Keycloak Operator `26.7.0` and uses the
same CloudNativePG cluster with its own database and credentials.

The bootstrap applies `KafkaConnect` and `KafkaConnector` resources only after
the application Helm release is ready. This ensures that Orders and Inventory
have completed their Flyway migrations before Debezium inspects
`public.outbox_events`. `kind-up` and `kind-test` both require the two workers
and the two connectors to report `Ready=True`.
The connector overlays set an explicit JVM heap below the container memory
limit so local Docker/Kind host-memory detection cannot over-allocate the
worker.

To include Prometheus and Grafana:

```bash
just kind-up-observability
```

## Diagnostics And Cleanup

```bash
just kind-status
just kind-logs
just kind-down
```

The smoke test uses curl `--resolve`, so editing `/etc/hosts` is not required.
For manual browser access, map `eurotransit.local` and
`keycloak.eurotransit.local` to `127.0.0.1`.

Local database and identity secrets use fixed development values. The payment
provider credential is supplied through `STRIPE_SECRET_KEY`. These values are
created directly in Kind and are never written to the repository. AKS uses
SealedSecrets and must not reuse them.
