# EuroTransit Configuration

Kubernetes deployment, GitOps, platform configuration and operational evidence for EuroTransit Marketplace.

Start with the [deployment architecture](docs/platform/deployment.md), including clickable diagrams for Kind, Kind HA and AKS.

## Run with Kind

```bash
just kind-up
just kind-test
```

See [Kind setup](docs/operations/kind.md) for prerequisites, credentials and cleanup. Other environments and GitOps bootstrap are covered in [operations](docs/operations/README.md).

## Documentation

- [Platform](docs/platform/README.md): topology, GitOps, identity, CDC and observability.
- [Operations](docs/operations/README.md): environment setup, recovery and controlled experiments.
- [Verification](docs/verification/README.md): results by environment and scenario; [testing and tooling](docs/verification/testing-tooling.md) explains the process and tools.
- [Readiness](docs/readiness.md): operational acceptance and remaining work.

Service behavior and API/event contracts live in [application](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/README.md).
