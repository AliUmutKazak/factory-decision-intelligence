"""One-shot release-closure fixer.

This script is intentionally temporary. It applies deterministic semantic fixes
that Ruff cannot infer, then the workflow runs Ruff's own fixer/formatter.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str, *, required: bool = False) -> None:
    text = read(path)
    if old not in text:
        if required:
            raise RuntimeError(f"Expected pattern not found in {path}: {old!r}")
        return
    write(path, text.replace(old, new, 1))


def ensure_before(path: str, anchor: str, insertion: str) -> None:
    text = read(path)
    if insertion.strip() in text:
        return
    if anchor not in text:
        raise RuntimeError(f"Anchor not found in {path}: {anchor!r}")
    write(path, text.replace(anchor, insertion + anchor, 1))


def ensure_after(path: str, anchor: str, insertion: str) -> None:
    text = read(path)
    if insertion.strip() in text:
        return
    if anchor not in text:
        raise RuntimeError(f"Anchor not found in {path}: {anchor!r}")
    write(path, text.replace(anchor, anchor + insertion, 1))


def main() -> None:
    # Syntax regression introduced during the run-scoped energy refactor.
    replace_once(
        "src/energy/energy_analytics.py",
        '         kpi_df["run_id"] = run_id',
        '        kpi_df["run_id"] = run_id',
        required=True,
    )

    # Scheduling runtime dependencies were lost during import cleanup.
    ensure_before(
        "src/scheduling/schedule_cpsat.py",
        "from src.utils.db import",
        "from src.scheduling.calendar_service import MachineCalendarService\n"
        "from src.scheduling.maintenance import load_machine_maintenance_windows\n",
    )

    # lineage.py still resolves a few backwards-compatible dynamic aliases
    # through the config module. Ruff will retain this import because those
    # references are live.
    ensure_after(
        "src/utils/lineage.py",
        "from pathlib import Path\n\n",
        "from src import config\n",
    )


if __name__ == "__main__":
    main()
