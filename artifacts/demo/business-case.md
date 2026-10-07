# Measured factory demo business case

Baseline: `RUN-20261006-00a0d3`.
Physical input fingerprint: `3b661b07be4b97c3b5d9385789efb111cccf50217b41dcd6c27f0788169070cd`.

All accepted schedules share the production calendar, maintenance, routes, setup, material availability, overtime and committed movement constraints.
Dispatch baselines select machine order and use CP-SAT to place intervals; runtime includes a solver and is not a pure heuristic speed comparison.

| Method | Status | Makespan h | Weighted tardiness h | Cost | Currency |
|---|---|---:|---:|---:|---|
| CP-SAT | FEASIBLE | 187.73 | 48.56666666666667 | 1871298.55 | EUR |
| FIFO | OPTIMAL | 211.82 | 127.15 | 1878950.7 | EUR |
| EDD | OPTIMAL | 235.82 | 102.81666666666666 | 1875119.44 | EUR |
| SPT | OPTIMAL | 238.67 | 207.0 | 1880511.65 | EUR |
| Greedy | OPTIMAL | 238.67 | 207.0 | 1880511.65 | EUR |
| COST_OPTIMIZED | FEASIBLE | 203.83 | 86.91666666666667 | 1871395.68 | EUR |

Weighted tardiness improvement versus EDD: 52.76381909547738% (undefined if EDD is zero or unavailable).

ROI projections and their explicit assumptions are in benchmark.json. Default realization is zero until customer financial evidence exists.
These are modeled manufacturing costs and analytic energy estimates. No actual customer pilot, verified cash saving, meter telemetry or vendor endpoint acceptance is claimed.
B2MML schedules are validated against the unmodified MESA 0701 XSDs. The supplied time epoch is recorded separately.
