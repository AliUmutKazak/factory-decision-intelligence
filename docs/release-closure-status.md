# Review sections 5–17: closure and evidence

The supplied review begins at section 5 and ends at section 17. This package covers those sections and their technical subitems while preserving forecast → LP → MRP → CP-SAT → MES/rescheduling → service/cost/carbon → ledger → API/dashboard. Customer/vendor acceptance and a paid pilot remain external work; they cannot be represented by a synthetic demo.

| Section / subitem | Current implementation | Evidence |
|---|---|---|
| 5.1 CI | Pinned dependencies, one solver worker, isolated mutable integration runtimes, physics/lineage gates and Docker job | GitHub Actions PR matrix |
| 5.2 staging | Context-local private DB/files; validate/seal before atomic canonical publication | Release regressions and bundle tests |
| 5.3 rescheduler persistence | Immutable new run, analytics, audit/ledger, validation, sealed bundle and promotion last | Dynamic rescheduler/API tests |
| 5.4 freeze | Hard machine/start/end/setup commitments; MES states and existing FROZEN state preserved | Freeze and dynamic tests |
| 5.5 ACTIVE reads | Sole-ACTIVE queries and snapshot reads; ambiguity/missing/corrupt data fails explicitly | API/governance/readiness/dashboard tests |
| 5.6 scenarios | Actual isolated LP/MRP/CP-SAT reruns; matrix snapshot pins one baseline; policy-only changes also solve | Scenario tests and decision-closure regression |
| 5.7 monetary objective | Actual COST_OPTIMIZED TMC in currency; independent cost reconciliation and rate-sensitive sequence choice | `test_decision_closure.py` |
| 5.8 economics | Canonical durations/lot quantities, base labor/setup and separate OT premiums; material and W1 expedite included | Economic and decision-closure tests |
| 5.9 reference | One verified sealed source, complete payload hashes, source Git/config/environment lineage | Reference tests and verify_active_run.py |
| 5.10 README | Actual API, objective, freeze/tier, adapter and deployment behavior documented | README and closure/run/demo documentation |
| 6 benchmark | CP-SAT, FIFO, EDD, SPT, Greedy and COST_OPTIMIZED on one immutable snapshot with shared physical constraints; actual schedules/costs and scoped optimality | Snapshot/disruption benchmark regression; `artifacts/demo/benchmark.json` |
| 6 measured gains | Actual EDD comparison, signed gains, undefined zero denominators; source/code/input fingerprints retained | Demo comparison and measured business-case export |
| 7 ledger | Durable SQLite, immutable decision IDs, read-only ACTIVE API/one-connection reads and restart survival | Ledger and API regressions |
| 8 B2MML | Unmodified official MESA 0701 schema closure, XSD validation and schedule/MES import/export for a declared profile | Schema hash tests, invalid XML rejection and canonical round trips |
| 8 vendor acceptance | **External dependency:** actual customer test tenant, transport/version agreement and response traces required | Explicit pilot acceptance package; no false vendor claim |
| 9 Docker | Clean bootstrap, shared persistent runtime, health/readiness, ACTIVE verification and restart reuse | Docker CI smoke job |
| 10 what-if/orchestrator | One authoritative production engine; sandbox solves do not publish; persist/validate/audit/version/promote flow retained | What-if/dynamic/API tests |
| 10 Tier-1 | Preserve and certify the existing plan for no-disruption checks; otherwise regular-shift local repair preserving machine order, exact production-model certification; FEASIBLE certificate without global optimum/bound/gap claim | Local-tier success, unchanged-plan and fallback audit tests |
| 10 FLEXIBLE | Same machine and hard lower/upper start displacement around source positions; actual context persisted for replay | Bounds/machine mismatch tests and model-context regression |
| 10 fallback/freeze/audit | Rejected candidate records reason and uses full CP-SAT; frozen commitments remain hard; old ACTIVE survives failure | Dynamic and release tests |
| 11–12 maturity | Advanced engineering prototype / single-host factory POC; no production SaaS claim | README, Docker/deployment docs |
| 13 commercial route | ERP-to-execution decision layer; portfolio → role/consulting → customer POC → paid implementation → reusable product → SaaS if justified | Demo and customer pilot guide |
| 14 release/decision/execution/product | Runtime/ACTIVE governance, monetary objective, shared benchmark, scenarios/service/cost, MES/freeze/tiers/versions/validation/ledger, API/UI/Docker health | Full quality and integration matrix |
| 14 demo/business case | Reproducible CLI, six measured cases, cost components, XML demo and documented walkthrough | `scripts/export_business_case.py`, `artifacts/demo/` |
| 14 ROI preparation | Explicit cycles/realization/implementation/operating assumptions; negative benefits retained, invalid payback undefined; default realization zero | `test_business_case.py`, exported projections |
| 14 customer adapter | Supplied CSV normalization with explicit field and resource/product maps; no fake substitute data | Customer adapter tests |
| 14 real pilot/ROI/sale | **External dependency:** real customer/data/access, shadow operation and signed acceptance/finance evidence required | `docs/demo-and-customer-pilot.md` acceptance table |
| 15 restraint | No predictive maintenance ML, digital twin, agents, K8s, microservices or SAP/SCADA expansion | Scope of this change |
| 16 architecture | Existing planning/execution/analytics architecture retained | Pipeline and integration matrix |
| 17 reliability | Failure-safe ACTIVE, correct run reads, real scenario snapshot, durable new reschedule version, reproducible decisions, clean Docker lifecycle | P0 tests and CI jobs |

## Validation scope

The preceding hardening head `0e078a6dc9db6168ef74dd1cb982603214c1fae0` passed 195 tests and clean-start/restart Docker verification ([run 37542007742](https://github.com/AliUmutKazak/factory-decision-intelligence/actions/runs/37542007742)). This evidence applies to that source, not automatically to later edits. The new decision/adapter/demo implementation has additional focused tests; final full-suite and Docker results are recorded against the actual PR head.

The measured demo stores its source workload and model hashes. A time-limited monetary solve need not outperform another policy; positive business value is measured rather than hardcoded. Energy is analytic, and configured holding/tardiness penalties are not automatically realized cash benefits. Reference and demo source revisions are deliberately retained instead of being mislabeled as an unrelated artifact-only commit.

The monetary objective and independent cost evaluation use the same makespan-scaled Scope 1 forklift assumption as canonical carbon analytics. Reschedule audit and API affected-task counts include actual machine/start/end changes, not every task outside the freeze horizon.

The technical package and reproducible pilot preparation can be completed here. Actual vendor interoperability, customer pilot execution, paid implementation and verified customer ROI remain unexecuted until the required customer data/access and acceptance evidence exist.
