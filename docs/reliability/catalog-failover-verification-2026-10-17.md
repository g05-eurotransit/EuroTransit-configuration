# Catalog failover verification — 2026-10-17

Outcome: the timeout was reproduced and attributed to an unavailable backend
still present in the gateway's routing set. No functional Catalog defect was
observed on the tested `GET /api/catalog/routes` path. Catalog failover is
demonstrated with measured transient errors. The specification does not require
zero errors during every failure: these timeouts must be assessed against the
applicable availability/latency SLO and error budget, rather than treated as an
automatic failure of the failover requirement. This check neither certifies all
Catalog functionality nor establishes SLO compliance. The original stricter
zero-error diagnostic result remains recorded unchanged.

## Historical timeout

The access log for worker-stop run `30677fd63d` records a request starting at
14:35:15 UTC, HTTP 504 after 1083 ms, with backend `10.244.3.21:8080`.
That was the Catalog replica on the worker stopped at 14:34:45.174. The runner
observed Node NotReady only at 14:35:32.776. Thus the gateway attempted that
replica approximately 30 seconds after its worker had stopped, while Kubernetes
had not yet withdrawn it. The historical response is a gateway timeout, not an
HTTP error returned by a running Catalog process on that stopped worker.

## Controlled Catalog-only check

Run `catalog-check-20261017T202233Z`, context `kind-eurotransit`, kept nodes,
PostgreSQL, Kafka and the other services running. No checkout or payment was
submitted; no application image, ingress configuration or probe was changed.

Two independent request loops ran every 250 ms after each response: one through
public Traefik and one directly to the healthy Catalog Pod through a private
localhost port-forward. All successful responses were validated as nonempty
JSON arrays and had identical body hashes.

After a six-second baseline, SIGSTOP suspended only the Catalog process in Pod
`catalog-649f7fd5d-n6x8b` on worker3, IP `10.244.2.12`. An independent watchdog
issued SIGCONT after 12 seconds, verifying the immutable container ID and process
ID before resuming it. The main process recorded recovery at 13.12 seconds and
observed another nine seconds. Phase labels refer to request start time; the
fault-labelled phase includes the short interval between watchdog resumption
and the main process recording recovery. Endpoint readiness was sampled separately.

| Path | Baseline | Fault-labelled phase | Recovery |
| --- | --- | --- | --- |
| Public ingress | 24/24 HTTP 200 | 25 HTTP 200, **5 HTTP 504** | 35/35 HTTP 200 |
| Healthy Pod directly | 24/24 HTTP 200 | **52/52 HTTP 200** | 35/35 HTTP 200 |

All five gateway access records name the suspended backend `10.244.2.12:8080`.
They took approximately 1000–1065 ms, consistent with the configured one-second
response-header timeout. The healthy control's maximum latency during the fault
was 6.15 ms; no successful response had an invalid or divergent body.

The first sampled Ready=false/endpoint withdrawal was 7.509 seconds after
SIGSTOP. All 21 subsequent ingress requests in the fault-labelled phase returned
200. No further timeout appeared during recovery. The Pod UID and container ID
were unchanged, restart count remained zero, and both Catalog Pods/endpoints
were Ready after cleanup. The private port-forward was terminated.

## Interpretation

The current availability gap is between a backend becoming unresponsive and its
removal from routing. The readiness probe did detect the suspended process and
traffic then used the healthy replica. The surviving Catalog instance continued
to return correct data throughout the experiment.

The configured two-attempt transport retry did not rescue these response stalls.
Traefik's retry is not a general retry of HTTP error responses; the observed 504s
must remain visible. Merely increasing its attempt count is not a demonstrated
fix. Faster application readiness may shorten the process-stall window, but it
does not by itself shorten node-failure detection when the kubelet is stopped.

The follow-up therefore belongs to routing/failure detection and handling of
in-flight read failures. The evidence does not currently justify changing Catalog
business logic. Detection latency and acceptable client errors still need to be
assessed against team-owned availability objectives.

[Sanitized observations](evidence/2026-10-17/catalog-failover-verification.json)
contain timings, request counts, backend attribution and raw-artifact hashes.
Raw request/access logs, endpoint samples and the exact diagnostic script remain
in ignored `load-results/catalog-check-20261017T202233Z/`.

Reference: [Traefik 3.4 transport retry semantics](https://doc.traefik.io/traefik/v3.4/middlewares/http/retry/).
