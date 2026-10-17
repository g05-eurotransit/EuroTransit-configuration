# Add an opt-in two-instance PostgreSQL profile and bounded failover proof plan

AKS currently overrides the shared three-instance CNPG base to one instance.
Add an unselected `aks-ha` overlay with two asynchronous instances on separate
hosts and a review/runbook covering capacity, durability decisions and proof.
Default AKS/Kind owners and the live cluster remain unchanged.
The normal AKS render check also renders the optional HA overlay. The historical
failover report stays owned by its separate report change (#55), linked by permalink.

The budget checker can render the opt-in profile independently. Its baseline
comparison now also accepts the exact monitoring filter already present on main,
with guards against altered defaults or an arbitrary appended filter.

Validation: AKS/Kind/HA renders, baseline field preservation and memory audit,
13 budget/preservation tests, live read-only per-node capacity/topology/schema,
and strict CNPG server dry-run. Ordinary/HA steady requests are 5280/5472Mi.
Dry-run required simulated force-conflicts for an existing instances field owner;
no real apply occurred. Memory pressure headroom, host-loss recovery, RPO/RTO and
async money-path durability remain explicit activation gates. No push or merge.

See [proposal and evidence](postgres-ha-proposal.md).
