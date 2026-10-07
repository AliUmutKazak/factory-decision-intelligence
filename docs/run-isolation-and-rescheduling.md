# Run isolation and dynamic rescheduling

The canonical database retains historical versions. Downstream reads select one explicit run ID, or the sole ACTIVE version. New solves require explicitly cloned inputs; an unknown run cannot borrow an unrelated plan. Existing run IDs cannot be restarted, and ACTIVE/ARCHIVED schedules cannot be overwritten.

## Publishing a pipeline run

The pipeline acquires a canonical database writer lock, copies the current database into a private staging directory, and runs every stage with context-local paths. It advances RUNNING → STAGING → VALIDATE → COMPLETED, validates physics and lineage, exports a database containing only that version, and seals the complete bundle with SHA-256 hashes. It promotes the version inside the private database and atomically replaces the canonical database only after sealing succeeds. A failure before that replacement preserves the previous ACTIVE version and compatibility outputs. Cache refresh after publication is best effort; the sealed bundle is the authoritative artifact.

Retention preserves ACTIVE and the published reference source. Cleanup of an external database uses its own artifact tree. Snapshots contain the selected version and shared master data; canonical history is retained independently.

## Dynamic rescheduling

The authoritative engine is `src.scheduling.rescheduler.DynamicRescheduler`; the integration facade delegates all disruptions to it. Completed/in-progress and freeze-horizon tasks retain their machine, start, end and business identity through hard CP-SAT constraints. New work cannot begin before the event time. Disruption downtime is queued after any committed frozen tasks on the affected machine: this policy preserves the frozen commitments and does not model interruption/resumption of a running operation.

A committed reschedule creates a new run, recomputes energy/carbon results, validates it, records its audit entry and decision ledger, seals its private outputs, and promotes ACTIVE last. The original version remains available. Makespan deltas are signed: reoptimization can improve a feasible, non-optimal baseline even after adding downtime. A sandbox solve uses an in-memory database and does not publish files. MES events are durable before solving; failure to replan does not erase the observation. MES writes and pipeline publication share the same thread/process lock. Reinitializing MES tracking preserves recorded execution status.

## Scheduling and scenarios

Machine downtime and material release delays are solver constraints. Demand/capacity shocks rerun LP, MRP, CP-SAT and energy/carbon accounting in a private database. Missing baseline data fails explicitly; zero production remains a valid result. Rush orders are separate lots with their requested due dates and penalty weights; quantities round up to complete production batches.

The solver enforces exact processing/setup overlap against the W1 overtime budget. W2+ overtime is prohibited. Transfer lots are capped to fit a regular shift, including throughput shocks. Initial setup ends at the first operation start, keeping solver constraints and exported accounting consistent.

OR-Tools is pinned to 9.14.6206 and single-worker search. Native crashes were observed with the parallel portfolio in both 9.15 and 9.14 during this workload. Validation covers solver feasibility rather than assuming an optimum from a time-limited solve. CI verifies the ACTIVE bundle hashes, database lineage and physics, followed by the full test suite.

## Economic reporting and objective names

`OPERATIONAL_BALANCED` balances makespan, setup and weighted tardiness in minutes. `COST_OPTIMIZED` minimizes actual monetary TMC using EconomicConfig rates; it includes fixed material/process costs and variable setup, overtime premiums, holding, tardiness, energy and carbon. Monetary objective/bound units and micro-currency rounding are explicit. Policy-only scenario changes trigger a real solve, with scenario energy/carbon rates passed to the monetary objective. Shared independent TMC reporting includes materials and W1 expedites.

A scenario matrix pins one SQLite snapshot for all shocks and reports its baseline run ID. Dashboard scenario computation runs on request and keeps results under that version. Dashboard solver status comes from the ACTIVE database rows rather than a mutable JSON cache.

Analytics retain lot identity, due dates and priorities. Historical demand is not a dispatch-order mapping and cannot multiply lot costs or service KPIs. Quantity is counted once across routing operations. Processing and setup base costs already include worked minutes; overtime adds their respective premiums. Without explicit OT accounting, actual interval/calendar overlap is used, never elapsed makespan. Missing processing duration and ambiguous order metadata fail explicitly.

Zero lower bounds remain valid proof data. A feasible service-first stage cannot become a proven lexicographic optimum just because the efficiency stage is optimal. Solver failures preserve the previous published version.

## Container startup

Compose runs a one-shot bootstrap before API/dashboard startup. A fresh runtime executes the pipeline and verifies the ACTIVE bundle. An existing runtime is verified and reused; invalid bundles block startup. Data, reports and sealed run bundles are shared persistent mounts. `/health` indicates liveness; `/ready` requires one ACTIVE version with solver metadata and returns its ID. CI builds a clean image, checks service readiness and bundle lineage, then restarts the stack and checks that the same ACTIVE version survives. This is a single-host demonstration/POC deployment, not a production multi-tenant service.

The explicit production benchmark pins one immutable snapshot. Dispatch rules select machine sequences and the shared CP-SAT physical model places them under routing, calendar, maintenance, materials, setup, overtime and commitment constraints. Scope-specific optimality and measured runtime are reported; a dispatch OPTIMAL is restricted to its selected sequence. Unknown cases and zero denominators do not invent improvements.

The orchestrator first tries regular-shift local repair, preserving machine order. Every candidate position is certified by the exact production model; rejected candidates fall back to full CP-SAT with an audit reason. The local certificate is FEASIBLE without a global bound. FLEXIBLE tasks retain their machine and hard start-displacement bounds. The final version stores real freeze/FLEXIBLE/maintenance context rather than the all-fixed candidate used for validation.
