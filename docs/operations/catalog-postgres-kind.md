# Catalog PostgreSQL on Kind

Enable Catalog's dedicated PostgreSQL database on the existing Kind cluster while retaining the HTTP contract. This procedure does not deploy to AKS. The [application storage reference](https://github.com/g05-eurotransit/EuroTransit-application/blob/main/docs/design/catalog-storage.md) owns the model and failure behavior.

## Preconditions

Use an explicit `kind-*` context for every command. Preserve the cluster and PVCs. Verify DNS, kube-proxy, PostgreSQL instances, Kafka, Keycloak, application pods and live CDC connector tasks. A previously successful controller condition alone does not prove current health.

For `too many open files` in kube-proxy, inspect host file-descriptor and inotify limits. The [HA host procedure](kind.md#ha-host-preparation) gives the tested inotify values. Record previous values and restore failed networking pods after adjusting the host; do not replace the cluster.

Create a private evidence directory outside Git, set `TRIAL_DIR` to its path and choose a unique image tag. Checks perform real Stripe sandbox purchases using the existing test-mode provider Secret. Credentials stay in memory; output retains charge hashes.

## Provision and baseline

From configuration:

```bash
python3 scripts/kind-catalog-check.py --output "$TRIAL_DIR/baseline.json"
python3 scripts/provision-kind-catalog.py --context kind-eurotransit
```

Provisioning preserves an existing Catalog credential, appends its CNPG managed role, waits for that role and creates `catalog_db` if absent. It refuses conflicting owners or role definitions and removes PUBLIC connection permission on that database. Other service databases are not migrated. For fresh Kind setup, `CATALOG_STORAGE=postgres` enables this provisioning in `scripts/kind-up.sh`; its default remains in-memory.

## Preview and promotion

Build application using the standard Dockerfile with `SERVICE=catalog`. Record source revisions, source-change hashes and image digest.

```bash
kind load docker-image --name eurotransit eurotransit/catalog:YOUR_UNIQUE_TAG
python3 scripts/kind-catalog-storage.py --context kind-eurotransit \
  --storage postgres --image eurotransit/catalog:YOUR_UNIQUE_TAG \
  --snapshot "$TRIAL_DIR/catalog-before.json"
kubectl --context kind-eurotransit -n eurotransit port-forward \
  service/catalog-preview 18081:8080 --address 127.0.0.1
```

While the port-forward is running, use another terminal to compare preview and wait for its gate:

```bash
python3 scripts/kind-catalog-preview.py --port 18081 --storage postgres \
  --output "$TRIAL_DIR/preview.json"
```

The storage script renders database variables and the authenticated database init container from the chart and patches only Catalog's Deployment template, preserving replica/controller ownership and unrelated configuration. Experimental clusters can have Rollouts changed outside their original Helm release. The script does not update Helm's stored values: a later Helm upgrade must include the intended image and `catalog.storage=postgres`.

Compare all five routes, six offers and six offer details through preview. Preserve ordering, values, policies and departure zones; Standard Milano–Paris must read `Non-refundable.`. Send bounded GET traffic until `catalog-preview-smoke` succeeds, then promote through Argo Rollouts. Do not bypass failed analysis with full promotion.

## Full-flow and failure checks

For the declarative provisioning path and startup gate, run `python3 scripts/kind-catalog-provisioning-check.py --output "$TRIAL_DIR/provisioning.json"`. It creates isolated temporary databases and pods to prove startup waiting, controller creation, bounded failure and owner rejection. Temporary databases use reclaim policy `delete` and are cleaned up. The real `catalog_db` is adopted with `retain`, preserving its contents. Only the Database manifest is applied to Kind; the AKS overlay is never applied there.

With progressive delivery, Catalog anti-affinity is scoped by `rollouts-pod-template-hash` so different revisions can share workers while replicas of one revision remain separated. Topology spreading uses `nodeTaintsPolicy: Honor` to exclude the tainted control plane from eligible domains; otherwise its zero Catalog pods can block the fourth blue/green pod. These settings were tested on Kubernetes v1.34. Existing pods with the older app-wide required anti-affinity retain their scheduling constraint. For the first transition or a rollback to that older template on three workers, temporarily set Catalog's Rollout to one replica, promote only after analysis succeeds, wait for the active Service selector to change, then restore two replicas. Record this temporary reduction in redundancy. Revisions with both corrected scheduling settings can coexist without that reduction.

```bash
python3 scripts/kind-catalog-check.py --require-postgres --refund --output "$TRIAL_DIR/postgres.json"
python3 scripts/kind-catalog-fault.py \
  --historical-orders "$TRIAL_DIR/baseline.json" --output "$TRIAL_DIR/fault.json"
python3 scripts/kind-catalog-persistence.py --output "$TRIAL_DIR/persistence.json"
```

The checkout check buys Standard for one seat and Business for two, verifies reservations, notifications and Stripe sandbox charges, and rejects an altered client price. With `--refund`, it checks Standard refusal and a Business refund with returned seats and independently verified provider refund.

The fault check temporarily sets `ALLOW_CONNECTIONS=false` on `catalog_db` and terminates only its sessions. It requires `503 OFFER_UNRESOLVABLE` for a new checkout with unchanged order, reservation and payment counts and no new provider charge. It reads historical orders and refunds the pre-migration Business purchase while Catalog's database remains unavailable. A `finally` block restores access and the script verifies recovery. If forcibly killed, restore access explicitly on the current PostgreSQL primary:

```sql
ALTER DATABASE catalog_db ALLOW_CONNECTIONS true;
```

For persistence, temporarily change only `of-003.display_note`, restart one Catalog pod and read that pod directly to confirm the value survives. Restore the original note in a `finally` block before further tests. During the database outage, readiness must fail while liveness remains healthy.

## Rollback and completion

```bash
python3 scripts/kind-catalog-storage.py --context kind-eurotransit \
  --snapshot "$TRIAL_DIR/catalog-before.json" --restore
```

Validate and promote the restored revision through blue/green. Recheck the catalog and repeat a sandbox checkout. Retain the database and its data. After successful rollback proof, redeploy the tested PostgreSQL image, pass preview analysis and promote again. Leave Kind on PostgreSQL only if all checks pass.

For the rollback preview, use `kind-catalog-preview.py --storage in-memory` with its port-forward. The comparison tolerates only the known removed exchange note on `of-003`; PostgreSQL preview must always show the corrected text.

Argo can immediately restore a still-retained stable revision with the identical pod hash. In that case, `kind-catalog-preview.py --verified-analysis NAME` accepts an explicitly named successful earlier analysis only when its resolved preview hash matches the currently healthy stable revision and the workload generation has been observed. Record this as reuse of a verified revision, not as a new analysis run. Still repeat the final checkout check and restore two healthy replicas.

Store sanitized results under the [Kind verification index](../verification/README.md). Azure storage, networking, credentials and production performance require separate qualification.
