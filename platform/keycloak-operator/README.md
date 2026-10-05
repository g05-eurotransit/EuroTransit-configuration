# Keycloak Operator AKS overlay

The base vendors the five unmodified resources selected by the existing Argo
Application from [keycloak-k8s-resources, tag 26.7.0](https://github.com/keycloak/keycloak-k8s-resources/tree/26.7.0/kubernetes).
`base/upstream/26.7.0/SHA256SUMS` records the downloaded bytes so review and
rendering do not depend on network access. Verify with `sha256sum -c SHA256SUMS`
from that directory. Refresh all five files together when upgrading upstream.

The AKS overlay changes only the Deployment memory request to 224Mi and retains
the 450Mi limit. CPU remains upstream's 300m/700m. The image, CRDs, Role,
RoleBinding, ServiceAccount, Service and operator configuration remain upstream.
The Kind Application continues to use the original upstream source directly.
