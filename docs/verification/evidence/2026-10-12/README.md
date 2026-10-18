# Sanitized proof exports

`audit-summary.json` is generated from the seven final correctness/provider
artifacts named in the detailed reports. It exports only aggregate states,
verification results, audit completeness and source SHA-256 hashes. It contains
no credentials, order IDs or provider references. Passing final audits do not
replace failed original load-test verdicts or prove automatic recovery.

`reconciliation-alert.csv` contains actual historical Prometheus samples for
ReconciliationRecordOpen during the fault session, with UTC times, state and
value. It supports the observed pending/firing timeline; it is not a screenshot
of the dashboard or proof of Alertmanager delivery to a human.

Restricted raw evidence remains outside Git in the workspace paths documented
in each report. These exports support review without publishing provider data.
