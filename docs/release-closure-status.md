# Release closure scope

This package follows the project review shared on 5 October 2026. The supplied review text starts at section 5 and contains sections 5–17, including all ten P0 subitems. Sections 1–4 have not been supplied and are not certified here. The LP → MRP → CP-SAT architecture is preserved, with no large new product feature.

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

## Supplied review: sections 5–17

| Review section | Current closure / remaining scope | Evidence |
|---|---|---|
| 5: ten P0 defects | All ten implemented; see the detailed table above | Release, freeze, scenario, economics, reference and API tests; CI quality and Docker jobs |
| 6: benchmark business value | Actual late lots, unweighted and weighted tardiness are separately calculated from canonical operations; heuristic operations count each lot once; aggregate metadata leaves unknown counts blank | `test_benchmark_contracts.py`, `test_scheduling_benchmark.py`, dashboard smoke test |
| 6: percentage improvement vs EDD | **Open:** an equivalent-constraint baseline is required before a business-value percentage can be claimed. Current heuristics remain illustrations with explicit limitations | Benchmark and dashboard captions; no claimed percentage or fabricated numerical business case |
| 7: durable Decision Ledger | SQLite persistence, immutable IDs, restart-safe reads and ACTIVE-scoped API query implemented. Queries do not create tables and remain on the same DB connection during atomic publication | Durable ledger, duplicate-ID, read-only query and concurrent publication regressions |
| 8: ISA-95 claims | Canonical contracts and B2MML-oriented exports are described accurately; no claim of validated B2MML compliance or bidirectional support | Adapter docstrings, README, existing contract tests |
| 8: schema/vendor interoperability | **Deferred:** B2MML XSD validation and real vendor interoperability are a separate integration stage, as stated in the review | Explicit README limitation |
| 9: Docker lifecycle | Pipeline bootstrap, sealing/verification, ACTIVE reuse, health/readiness and restart persistence implemented; corrupted DB readiness returns 503 | Docker smoke job and API readiness regressions |
| 10: authoritative rescheduler | Actual production and facade calls use one engine, hard freeze constraints, validation, ledger, immutable version and promotion; what-if is isolated | Dynamic rescheduler, what-if and freeze integration tests |
| 10: Tier-1 and FLEXIBLE movement | **Deferred:** production uses full CP-SAT; no separate Tier-1 local repair or restricted FLEXIBLE movement tier. Frozen commitments are hard constraints; other tasks are reoptimized | Run-isolation documentation and README freeze boundary rule |
| 11–12: maturity assessment | Advanced engineering prototype / single-host factory POC; production SaaS readiness is not claimed | README and deployment limitations |
| 13: commercialization route | Strategy retained: decision layer between ERP and execution. Consulting, customer-specific POC and paid implementation are future work | No ERP replacement or completed customer pilot claim |
| 14: release/decision/execution/product closure | Runtime, scenario reruns, service/cost schemas, execution persistence, API/UI and operational health implemented. Monetary optimization uses immediate option A from P0-7: OPERATIONAL_BALANCED; a money-based CP-SAT objective remains deferred | Objective-policy tests, scenario/economic regressions and release gates |
| 14: demo/business case/ROI/pilot | **Future:** business-case claims require equivalent baselines and customer-specific inputs; pilot/ROI is not marked complete | No invented customer results |
| 15: feature restraint | No predictive-maintenance ML, digital twin, agents, Kubernetes, microservices expansion or real SAP/SCADA gateway added | Changes remain release/runtime/decision reliability work |
| 16: architecture | Existing forecast → LP → MRP → scheduling → MES/rescheduling → analytics/audit → API/dashboard preserved | Pipeline and integration tests |
| 17: engineering reliability questions | Failure preserves ACTIVE; APIs select ACTIVE; scenarios snapshot their baseline; rescheduling persists new versions; audit survives restart; Docker clean-start/restart is exercised | P0 tests and CI evidence |

The supplied review does not turn its explicitly deferred roadmap into finished functionality. In particular, benchmark metric correctness is closed, but an equivalent-feasibility business-value proof remains open.

## Verification record

The previous hardening head `aa4e95c5e0e83853841f7a61796f1df7c3c01048` passed the complete GitHub Actions matrix: 184 tests and the clean-start/restart Docker job ([run 37537786461](https://github.com/AliUmutKazak/factory-decision-intelligence/actions/runs/37537786461)). That result applies to that head, not automatically to subsequent edits. The follow-up review closes additional benchmark, economic-configuration, read-only audit and readiness defects; its current checks are reported in the PR rather than represented by a static pass-count badge.

The deployment remains a single-host demo/POC. Disruption downtime is queued after frozen commitments; operation interruption/resumption is not implemented. The production path uses CP-SAT rather than a separate Tier-1 heuristic repair. Heuristic benchmark rules use a simplified constraint model and do not establish an equivalent-feasibility performance claim.

Work proceeds along the agreed route: Release Hardening → Runtime Isolation → Active Run Governance → Rescheduling Closure → Economic/Scenario Closure → Product Hardening → Demo/Commercialization. This PR closes the ten supplied P0 defects and runtime validation package; it does not claim that unseen sections 1–4, the equivalent-constraint benchmark proof, deferred integration/optimization tiers or commercialization work are complete.
