# Five-minute demo storyboard : recording pending

This is a recording plan, not a completed demo or a fabricated video link.
Record only after the delivery/tracing/observability gates in `docs/delivery/readiness.md` close.

| Time | Show | Required evidence |
| --- | --- | --- |
| 0:00 to 0:40 | Running system, five services, single ingress, GitOps revision and immutable images | Actual cluster and Argo state; explain any temporary controller pause |
| 0:40 to 1:20 | Checkout RED/end-to-end view and one trace | Real confirmed order, terminal SLI, gateway/service/Kafka spans |
| 1:20 to 2:20 | Orders canary exposure, gate decision, promote and abort recovery | Candidate hash, Traefik weight, AnalysisRun samples and stable route |
| 2:20 to 3:10 | Catalog blue/green preview, switch and rollback | Distinct revisions, preview check, active route and retained old revision |
| 3:10 to 4:20 | One bounded fault, symptom alert and recovery | Actual fault interval, firing alert, user-visible impact and cleanup |
| 4:20 to 5:00 | Invariants and recovery trade-offs | Independent provider audit, one-seat crash proof, factual failed-availability finding |

Historical alert evidence from the recorded run is available in the observability
report; label it as replayed evidence with its source run/revision. A historical screenshot
must not be presented as an alert firing live during the recording.

Before release, commit the real recording URL and revisions here, keep provider
identifiers/credentials out of the recording and complete team review of the
hypotheses/postmortem. The recording URL is still pending.
