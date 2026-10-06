# Run isolation and dynamic rescheduling

The canonical database retains historical versions. Downstream reads select one explicit run ID, or the sole ACTIVE version. New solves require explicitly cloned inputs; an unknown run cannot borrow an unrelated plan. Existing run IDs cannot be restarted, and ACTIVE/ARCHIVED schedules cannot be overwritten.

## Publishing a pipeline run

The pipeline acquires a canonical database writer lock, copies the current database into a private staging directory, and runs every stage with context-local paths. It advances RUNNING → STAGING → VALIDATE → COMPLETED, validates physics and lineage, exports a database containing only that version, and seals the complete bundle with SHA-256 hashes. It promotes the version inside the private database and atomically replaces the canonical database only after sealing succeeds. A failure before that replacement preserves the previous ACTIVE version and compatibility outputs. Cache refresh after publication is best effort; the sealed bundle is the authoritative artifact.

Retention preserves ACTIVE and the published reference source. Cleanup of an external database uses its own artifact tree. Snapshots contain the selected version and shared master data; canonical history is retained independently.

## Dynamic rescheduling

The authoritative engine is `src.scheduling.rescheduler.DynamicRescheduler`; the integration facade delegates all disruptions to it. Completed/in-progress and freeze-horizon tasks retain their machine, start, end and business identity through hard CP-SAT constraints. New work cannot begin before the event time. Disruption downtime is queued after any committed frozen tasks on the affected machine: this policy preserves the frozen commitments and does not model interruption/resumption of a running operation.

A committed reschedule creates a new run, recomputes energy/carbon results, validates it, records its audit entry and decision ledger, seals its private outputs, and promotes ACTIVE last. The original version remains available. A sandbox solve uses an in-memory database and does not publish files. MES events are durable before solving; failure to replan does not erase the observation. MES writes and pipeline publication share the same thread/process lock. Reinitializing MES tracking preserves recorded execution status.

## Scheduling and scenarios

Machine downtime and material release delays are solver constraints. Demand/capacity shocks rerun LP, MRP, CP-SAT and energy/carbon accounting in a private database. Missing baseline data fails explicitly; zero production remains a valid result. Rush orders are separate lots with their requested due dates and penalty weights; quantities round up to complete production batches.

The solver enforces exact processing/setup overlap against the W1 overtime budget. W2+ overtime is prohibited. Transfer lots are capped to fit a regular shift, including throughput shocks. Initial setup ends at the first operation start, keeping solver constraints and exported accounting consistent.

OR-Tools is pinned to 9.14.6206 after native crashes were observed with 9.15.6755 during this workload. Validation covers solver feasibility rather than assuming an optimum from a time-limited solve. CI verifies the ACTIVE bundle hashes, database lineage and physics, followed by the full test suite.
