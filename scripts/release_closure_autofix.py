"""One-shot release-closure fixer.

This script is intentionally temporary. It applies deterministic semantic fixes
that Ruff cannot infer, then the workflow runs Ruff's own fixer/formatter.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def replace_once(path: str, old: str, new: str, *, required: bool = False) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8-sig")
    if old not in text:
        if required:
            raise RuntimeError(f"Expected pattern not found in {path}: {old!r}")
        return
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def ensure_after(path: str, anchor: str, insertion: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8-sig")
    if insertion.strip() in text:
        return
    if anchor not in text:
        raise RuntimeError(f"Anchor not found in {path}: {anchor!r}")
    target.write_text(text.replace(anchor, anchor + insertion, 1), encoding="utf-8")


def main() -> None:
    # Syntax regression introduced during the run-scoped energy refactor.
    replace_once(
        "src/energy/energy_analytics.py",
        '         kpi_df["run_id"] = run_id',
        '        kpi_df["run_id"] = run_id',
        required=True,
    )

    # Planned maintenance was wired into the scheduler but its import was lost
    # during a later cleanup commit.
    ensure_after(
        "src/scheduling/schedule_cpsat.py",
        "from src.scheduling.calendar_service import MachineCalendarService\n",
        "from src.scheduling.maintenance import load_machine_maintenance_windows\n",
    )

    # lineage.py still intentionally resolves legacy dynamic aliases through the
    # config module in several compatibility paths. Keep that module import until
    # those call sites are fully migrated.
    ensure_after(
        "src/utils/lineage.py",
        "from pathlib import Path\n\n",
        "from src import config\n",
    )


if __name__ == "__main__":
    main()
