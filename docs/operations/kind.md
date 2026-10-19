# Run EuroTransit on Kind

Choose standard Kind for development or Kind HA for multi-node experiments. Both use the direct setup script, local development identities and a real provider sandbox. The optional [GitOps procedure](gitops.md) is separate from direct setup and its smoke checks.

## Prerequisites

Install Docker, Kind, kubectl, Helm, Just, Python 3, curl and `rg`. Check out application beside configuration, or set `EUROTRANSIT_APP_DIR`. Provide a Stripe test/restricted-test key through `STRIPE_SECRET_KEY`; live keys are refused and the key is never written to Git.

Allocate at least 8 GiB Docker memory and 20 GiB free disk for the integral development stack; qualify actual HA headroom with the [experiment preflight](ha-experiment.md). All Kind nodes share the workstation. An existing standard cluster is not converted into HA; preserve needed data before separately authorizing replacement.

## Start and verify

Run from configuration with the sandbox key already in the environment:

| Profile | Render | Start | Verify |
| --- | --- | --- | --- |
| Standard, one node | `just render-kind` | `just kind-up` | `just kind-test` |
| HA, one control plane and three workers | `just render-kind-ha` | `just kind-ha-up` | `just kind-ha-test` |

The setup script creates a missing cluster, builds and loads five backend images, the frontend and the connector image, installs controllers, creates disposable Secrets and waits for the marketplace before applying CDC connectors. Standard Kind runs three per-service Connect workers; HA runs a two-replica shared worker group. Both have three outbox connectors and require healthy tasks, not only Ready Pods. [Deployment](../platform/deployment.md) owns the topology; [CDC](../platform/cdc.md) owns worker/slot behavior.

For prebuilt images use `SKIP_BUILD=1`; the seven selected local image tags must exist. Standard defaults to `local`, HA to `kind-ha`. Keep source revisions, image IDs and digests when collecting evidence.

Standard setup excludes Argo CD, Chaos Mesh and monitoring by default. `just kind-up-observability` enables monitoring; `just kind-ha-up` enables it for HA. These are local profiles, not public deployments.

## HA host preparation

The profile requires cluster name `eurotransit` for its placement rules. Check shared host inotify limits before running worker restarts. The fault preflight requires at least 512 instances and 524288 watches; the tested runtime settings below affect the Linux Docker host:

```bash
sudo sysctl -w fs.inotify.max_user_instances=1024 fs.inotify.max_user_watches=524288
```

Apply host changes only within the authorized local setup. Do not delete an existing cluster to bypass the four-node check. `kind-up.sh` scopes cluster operations to its selected Kind context.

## Access, diagnostics and cleanup

For browser access map `eurotransit.local` and `keycloak.eurotransit.local` to `127.0.0.1`; smoke checks use curl `--resolve` and do not require that hosts-file change. Local database/demo-user values are disposable. AKS ciphertext and credentials are environment-specific.

```bash
just kind-status
just kind-logs
just kind-down
```

`kind-down` deletes the local cluster. Collect required evidence and preserve data before using it. On failure inspect Pod descriptions, events, controller status and connector task status before rerunning.

Smoke covers workload readiness, gateway/frontend availability, authentication and public/internal route separation. See [kind-test.sh](../../scripts/kind-test.sh) for its exact assertions. Argo reconciliation, HA faults and complete tracing/dashboard proof are separate checks. The application [smoke workflow](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/.github/workflows/smoke-tests.yml) owns CI orchestration; this guide owns local execution.
