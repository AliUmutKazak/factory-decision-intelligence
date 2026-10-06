# Demo, business case and customer pilot

This is a single-host manufacturing decision-support POC. The demo proves its own engineering behavior, not production SaaS readiness or customer ROI. No new ERP replacement, predictive maintenance, digital twin, SAP/SCADA gateway or distributed platform is introduced.

## Reproduce the technical demo

1. Install `requirements.txt`, run `python main.py`, then `python scripts/verify_active_run.py`.
2. Start `uvicorn src.api.server:app --port 8000` and `streamlit run dashboard/app.py`. Alternatively use `docker compose up --build -d --wait`.
3. Read `/ready` and `/api/v1/schedule/current`; verify their run IDs agree. Restart Compose and verify the same ACTIVE version remains.
4. Record a MES disruption through the documented API. Verify the new run ID, prior frozen positions, reschedule audit, decision ledger, sealed bundle and ACTIVE promotion. A rejected local candidate must report its rejection reason and use full CP-SAT; a failed solve preserves ACTIVE.
5. Open the scenario tab and explicitly compute the comparison. Its baseline ID identifies one immutable snapshot.
6. Use the scheduling tab's explicit benchmark button, or export a reproducible case:

```bash
python scripts/export_business_case.py --output-dir artifacts/demo --seconds 30
```

The report contains six policies, actual accepted schedules, late lots, weighted/unweighted tardiness, setup, makespan, runtime, independent cost components, source run ID, constraint/input fingerprint, code hashes and Git revision. FIFO/EDD/SPT/Greedy choose machine sequences; the same production CP-SAT model places their intervals. Their runtime is therefore not a pure heuristic speed comparison. OPTIMAL for a dispatch rule means optimal within its fixed sequence. FEASIBLE does not prove a global optimum. Missing solutions produce explicit unknown results.

The recorded demo is a modeled case using the project's input data and synthetic engineering/economic assumptions. Improvement percentages use measured equivalent workloads, retain negative results, and remain undefined when the EDD denominator is zero or a solution is unavailable. All six cases share the same physical input fingerprint. Setup/idle/process energy are analytic estimates, not meter readings.

## Economic acceptance and ROI

`COST_OPTIMIZED` minimizes monetary manufacturing cost with the configured labor, setup, overtime premiums, WIP holding, weighted tardiness, energy, carbon, material and W1 expedite rates. Fixed task material/process costs are included; setup, overtime, WIP, lateness and idle-energy costs depend on the chosen schedule. Micro-currency coefficient rounding is reported. A time-limited solve can return a worse cost than another policy and must be assessed against measured baselines. The report records that behavior rather than promising automatic savings.

The default ROI realization fraction is zero. To make an explicitly assumed projection:

```bash
python scripts/export_business_case.py --output-dir artifacts/customer-case \
  --cycles-per-year 50 --realization-fraction 0.25 \
  --implementation-cost 10000 --annual-operating-cost 5000
```

These inputs are assumptions, not observed customer data. Annual gross benefit is `(baseline cost - candidate cost) × cycles × realization fraction`. Net benefit subtracts operating costs; first-year ROI also subtracts implementation cost. Payback is undefined when annual net benefit is nonpositive. Modeled holding/tardiness penalties must be reconciled to cash flow before claiming financial ROI; projected production savings cannot automatically be called realized cash savings.

## Customer data boundary and B2MML

`CustomerFileAdapter` takes explicit canonical-to-source column maps and customer-to-internal product/machine ID maps. It imports supplied CSV orders and MES actuals into validated contracts, rejects unknown IDs, duplicates, missing columns and nonfinite quantities, and creates no synthetic substitute records. It is a read-only file adapter; endpoint transport is customer-specific.

`ISA95Adapter` now supports validated schedule/MES XML export and import for a declared factory profile of B2MML 0701. MESA's unmodified official XSD dependency closure, full license, source commit and per-file hashes are vendored under `src/contracts/xsd/b2mml-0701`. A caller must supply a timezone-aware Monday time epoch. The XML export validates before returning. Schedule metadata is carried in a declared factory-v1 Description profile; operation IDs, definitions, resources and ISO timestamps use standard elements. Scrap quantity is an explicit standard SegmentData parameter. Ambiguous multi-segment messages cannot silently enter the single-operation MESActual contract.

This XML API supersedes the prior unvalidated V0600-like exports. Callers now supply `origin`; schedule callers additionally supply `schedule_id`. The adapter accepts the supported factory profile, not every possible valid B2MML message. XSD validity and our round trips do not establish interoperability with a specific vendor endpoint.

The Business To Manufacturing Markup Language (B2MML) is used courtesy of MESA International.

## External acceptance still required

A real customer pilot and vendor interoperability cannot be executed without an actual customer, authorized endpoint/test tenant, real identifier maps and representative data. These are the remaining external dependencies:

| Input / acceptance | Required evidence |
|---|---|
| Production boundary | Agreed site, planning horizon, routes, machine calendar/maintenance, current WIP and release constraints |
| Data contract | Customer field maps, resource/product IDs, quantity/time/currency units and example accepted/rejected payloads |
| Vendor endpoint | Authorized test transport, version/profile agreement and actual acknowledgement/rejection traces |
| Shadow pilot | Time-stamped baseline vs recommendations, operator acceptance, freeze preservation, failed-run behavior and rollback |
| Cash benefit | Measured execution/setup/overtime/late-delivery changes and approved customer finance conversion assumptions |
| Commercial acceptance | Named sponsor, agreed criteria, pilot sign-off, pricing and scope of paid implementation |

The commercialization route remains portfolio → engineering role/consulting → customer POC → paid implementation → reusable product → SaaS only when justified. The technical demo, reusable boundary adapter, ROI calculator and pilot acceptance package are implemented; no completed customer pilot, sale or verified financial return is claimed.
