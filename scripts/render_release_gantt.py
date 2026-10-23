"""Render the README chart from the archived synthetic release schedule."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Patch

plt.switch_backend("Agg")


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/screenshots/source/v012"
OUTPUT = ROOT / "docs/screenshots/05-Dogrulanmis-Laboratuvar-Cizelgesi.png"
COLORS = {
    "P01": "#f87171",
    "P02": "#3b82f6",
    "P03": "#4ade80",
    "P04": "#7dd3fc",
    "P05": "#f9a8d4",
}


def main() -> None:
    with (SOURCE / "production_schedule.csv").open(encoding="utf-8-sig", newline="") as stream:
        schedule = list(csv.DictReader(stream))
    solver = json.loads((SOURCE / "schedule_solver_metadata.json").read_text(encoding="utf-8"))
    run = json.loads((SOURCE / "run_metadata.json").read_text(encoding="utf-8"))
    run_id = run["run_id"]
    if not schedule or solver["run_id"] != run_id or any(row["run_id"] != run_id for row in schedule):
        raise ValueError("Screenshot inputs must belong to one nonempty run")
    if run["git_sha"] != "fa61c34e597214b1185461da89fdeba3349334f6":
        raise ValueError("Screenshot source is not the verified v0.1.12-lab commit")
    if len(schedule) != solver["tasks_scheduled"]:
        raise ValueError("Schedule and solver metadata task counts disagree")

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12})
    fig = plt.figure(figsize=(16, 9), facecolor="#0b0f16")
    fig.text(0.05, 0.93, "Kapasite Kısıtlı Üretim Çizelgesi", color="#f4f7fb", fontsize=27, weight="bold")
    fig.text(
        0.05,
        0.88,
        "OR-Tools CP-SAT  •  3 tezgâh  •  sentetik laboratuvar verisi",
        color="#a9b3c2",
        fontsize=13,
    )

    ax = fig.add_axes((0.085, 0.34, 0.75, 0.46), facecolor="#0e1520")
    machines = sorted({row["machine_id"] for row in schedule})
    positions = {machine: len(machines) - index for index, machine in enumerate(machines)}
    for row in schedule:
        start = float(row["start_min"]) / 60
        end = float(row["end_min"]) / 60
        setup = float(row["setup_before_min"]) / 60
        y = positions[row["machine_id"]]
        color = COLORS[row["product_id"]]
        if setup > 0:
            ax.barh(y, setup, left=start - setup, height=0.58, color=color, alpha=0.28)
        ax.barh(y, end - start, left=start, height=0.58, color=color, edgecolor="#0b0f16", linewidth=0.7)

    makespan = float(solver["objective_makespan_min"]) / 60
    ax.set_xlim(0, max(192, makespan + 8))
    ax.set_ylim(0.4, len(machines) + 0.6)
    ax.set_yticks([positions[machine] for machine in machines], labels=machines)
    ax.set_xticks(list(range(0, 193, 24)))
    ax.tick_params(colors="#dce3ec", length=0, pad=10)
    ax.grid(axis="x", color="#546170", alpha=0.25)
    ax.set_axisbelow(True)
    ax.set_xlabel("Plan başlangıcından itibaren geçen süre (saat)", color="#dce3ec", labelpad=14)
    for spine in ax.spines.values():
        spine.set_visible(False)

    legend = ax.legend(
        handles=[Patch(facecolor=color, label=product) for product, color in COLORS.items()],
        title="Ürün",
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        frameon=False,
        labelcolor="#dce3ec",
    )
    legend.get_title().set_color("#dce3ec")

    cards = [
        ("ÇÖZÜCÜ DURUMU", solver["solver_status"], "#eab308"),
        ("ÇİZELGE SÜRESİ", f"{makespan:.1f}".replace(".", ",") + " saat", "#60a5fa"),
        ("TOPLAM HAZIRLIK", f"{solver['objective_setup_min']} dk", "#2dd4bf"),
        ("PLANLANAN MİKTAR", f"{solver['total_scheduled_units']:,}".replace(",", ".") + " adet", "#f472b6"),
    ]
    for index, (label, value, color) in enumerate(cards):
        x = 0.05 + index * 0.238
        fig.add_artist(
            FancyBboxPatch(
                (x, 0.115),
                0.22,
                0.105,
                boxstyle="round,pad=0.008,rounding_size=0.013",
                transform=fig.transFigure,
                facecolor="#151c26",
                edgecolor="#354252",
                linewidth=0.8,
            )
        )
        fig.text(x + 0.014, 0.178, label, color="#aeb8c5", fontsize=11, weight="bold")
        fig.text(x + 0.014, 0.137, value, color=color, fontsize=19, weight="bold")

    fig.text(
        0.05,
        0.07,
        f"{run_id}  •  v0.1.12-lab  •  {solver['solve_time_seconds']:.1f} sn çözüm süresi",
        color="#aeb8c5",
        fontsize=10,
    )
    fig.text(0.95, 0.07, "FEASIBLE optimumluk kanıtı değildir.", color="#eab308", fontsize=10, ha="right")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, dpi=100, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(OUTPUT)


if __name__ == "__main__":
    main()
