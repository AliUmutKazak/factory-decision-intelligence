"""Dispatch sequence construction and conservative local repair candidates.

Dispatch rules choose machine sequences; the production CP-SAT model subsequently
places and validates every interval with the same physical constraints. A local
repair uses regular shifts, preserves machine order, and remains a candidate
until the exact production model certifies all its positions.
"""

from math import ceil


def dispatch_rank(tasks, rule):
    records = {str(row.task_id): row._asdict() for row in tasks.itertuples(index=False)}
    original = {str(tid): i for i, tid in enumerate(tasks.task_id)}
    predecessors = {tid: set() for tid in records}
    for _, group in tasks.groupby("lot_id"):
        ordered = list(group.sort_values("operation_seq").task_id.astype(str))
        for previous, following in zip(ordered, ordered[1:]):
            predecessors[following].add(previous)
    for _, group in tasks.groupby(["product_id", "operation_seq"]):
        ordered = list(group.sort_values("sub_lot_index", kind="stable").task_id.astype(str))
        for previous, following in zip(ordered, ordered[1:]):
            predecessors[following].add(previous)
    done, ranks, machine_end, estimated_end = set(), {}, {}, {}
    while len(done) < len(records):
        ready = [tid for tid in records if tid not in done and predecessors[tid] <= done]
        if not ready:
            raise ValueError("Cyclic routing/transfer-lot dispatch dependencies.")

        def key(tid):
            row = records[tid]
            duration = row.get("duration", row.get("duration_min"))
            release = row.get("release_time_min", 0)
            if rule == "EDD":
                return row["due_date_min"], original[tid]
            if rule == "SPT":
                return duration, original[tid]
            if rule == "Greedy":
                earliest = max(
                    machine_end.get(row["machine_id"], 0),
                    release,
                    max((estimated_end[p] for p in predecessors[tid]), default=0),
                )
                return earliest + duration, original[tid]
            if rule == "FIFO":
                return release, original[tid]
            raise ValueError(f"Unknown dispatch rule: {rule}")

        chosen = min(ready, key=key)
        row = records[chosen]
        start = max(
            machine_end.get(row["machine_id"], 0),
            row.get("release_time_min", 0),
            max((estimated_end[p] for p in predecessors[chosen]), default=0),
        )
        estimated_end[chosen] = start + row.get("duration", row.get("duration_min"))
        machine_end[row["machine_id"]] = estimated_end[chosen]
        ranks[chosen] = len(done)
        done.add(chosen)
    return ranks


def local_repair_candidate(
    schedule, current_time, frozen, flexible, daily_hours, setup_matrix, initial_states, maintenance
):
    """Preserve original per-machine order and shift only mutable tasks.

    Raises ValueError when this conservative candidate cannot meet commitments;
    the orchestrator can then run full CP-SAT reoptimization.
    """
    records = {str(row.task_id): row._asdict() for row in schedule.itertuples(index=False)}
    predecessors = {tid: set() for tid in records}
    for group_key in ("lot_id", "machine_id"):
        for _, group in schedule.groupby(group_key):
            column = "operation_seq" if group_key == "lot_id" else "start_min"
            ordered = list(group.sort_values(column).task_id.astype(str))
            for previous, following in zip(ordered, ordered[1:]):
                predecessors[following].add(previous)
    positions, last_product, available = {}, dict(initial_states), {}
    while len(positions) < len(records):
        ready = [tid for tid in records if tid not in positions and predecessors[tid] <= positions.keys()]
        if not ready:
            raise ValueError("Local repair machine/routing precedence cycle.")
        tid = min(ready, key=lambda task: (records[task]["start_min"], task))
        row = records[tid]
        machine = str(row["machine_id"])
        setup = setup_matrix.get((machine, last_product.get(machine), row["product_id"]), 0)
        previous_end = max((positions[p][2] for p in predecessors[tid]), default=0)
        if tid in frozen:
            position = frozen[tid]
            if position[1] < previous_end or position[1] - setup < available.get(machine, 0):
                raise ValueError(f"Local repair would move a frozen predecessor: {tid}")
        else:
            duration = int(row["duration_min"])
            regular = int(round(daily_hours[machine] * 60))
            if duration + setup > regular:
                raise ValueError(f"Local repair interval does not fit a regular shift: {tid}")
            earliest = max(
                current_time,
                row.get("release_time_min", 0),
                previous_end,
                available.get(machine, 0) + setup,
                flexible.get(tid, (machine, 0, float("inf")))[1],
            )
            start = ceil(earliest)
            for _ in range(10000):
                block_start = start - setup
                day = int(block_start // 1440)
                shift_start = day * 1440 + 1440 - regular
                if day % 7 == 6:
                    start = (day + 1) * 1440 + 1440 - regular + setup
                    continue
                if block_start < shift_start:
                    start = shift_start + setup
                    continue
                if start + duration > (day + 1) * 1440:
                    start = (day + 1) * 1440 + 1440 - regular + setup
                    continue
                conflict = next(
                    (
                        window
                        for window in maintenance
                        if str(window.machine_id) == machine
                        and block_start < window.end_min
                        and start + duration > window.start_min
                    ),
                    None,
                )
                if conflict:
                    start = int(conflict.end_min) + setup
                    continue
                break
            else:
                raise ValueError("Local repair calendar search exceeded its bound.")
            if tid in flexible and start > flexible[tid][2]:
                raise ValueError(f"Local repair exceeds flexible movement bounds: {tid}")
            position = (machine, start, start + duration)
        positions[tid] = position
        available[machine] = position[2]
        last_product[machine] = row["product_id"]
    return positions
