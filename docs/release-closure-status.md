# Release closure scope

This package follows the recovered P0 checklist from the project review. It preserves the LP → MRP → CP-SAT architecture and adds no large product feature. The original 17-section message is not available verbatim in this workspace, so this document does not certify every unseen subitem as complete.

| P0 item | Implemented closure | Verification |
|---|---|---|
| CI failures | Pinned solver/dependencies, single-worker search, isolated mutating tests and physics gates | Full GitHub Actions quality matrix |
| Staging isolation | Context-local runtime paths, private DB/files, sealed bundle before atomic publication | Staging failure and release regressions |
| Rescheduler persistence | One authoritative engine, immutable new version, analytics, audit/ledger and ACTIVE promotion last | Dynamic rescheduler and API integration tests |
| Freeze horizon | Hard start/end/machine constraints; committed MES states override planned timing; persisted FROZEN state | Frozen horizon tests, including zero-window and mixed ID types |
| ACTIVE API/dashboard isolation | Explicit run-scoped queries; ambiguous ACTIVE registry fails; no completed-run fallback | API readiness, governance and dashboard render tests |
| Scenario simulation | Real isolated LP/MRP/CP-SAT reruns; one baseline snapshot across the entire matrix | Scenario matrix and concurrent promotion regression |
| COST_OPTIMIZED claim | Renamed OPERATIONAL_BALANCED; obsolete names rejected; monetary TMC remains separate analytics | Objective policy tests |
| Economic schema | Canonical duration/setup columns, lot identity, physical quantities, SSOT rates and OT premiums | Exact-value economic/service regressions |
| Reference consistency | Reference regenerated from a verified sealed run; source SHA/config/environment and payload hashes retained | Reference tests and ACTIVE bundle verification |
| README/code mismatch | Correct API paths/payloads, actual CBC solver, live CI badge, documented deployment and maturity | Code/document review and Docker smoke job |

Docker additionally verifies clean startup, shared persistent artifacts, API/dashboard readiness, and reuse of the same ACTIVE version after restart. The dashboard renders without implicitly solving scenarios or writing runtime data; reschedule audit entries can be read through the API and dashboard.

The deployment remains a single-host demo/POC. Disruption downtime is queued after frozen commitments; operation interruption/resumption is not implemented. The production path uses CP-SAT rather than a separate Tier-1 heuristic repair. Heuristic benchmark rules use a simplified constraint model and do not establish an equivalent-feasibility performance claim.

Work proceeds along the agreed route: Release Hardening → Runtime Isolation → Active Run Governance → Rescheduling Closure → Economic/Scenario Closure → Product Hardening → Demo/Commercialization. This PR closes the recovered P0 defects and runtime validation package; it does not claim production SaaS readiness or completion of unspecified commercialization work.
