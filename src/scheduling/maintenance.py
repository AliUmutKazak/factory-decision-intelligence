"""
Machine Master Data Maintenance & Calendar Exception Engine (Madde 35).
Planlı bakım (planned maintenance), mola ve takvim istisnalarını
CP-SAT çizelgeleme kısıtlarına dönüştürür.
"""

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass
class MaintenanceWindow:
    """Planlı bakım veya duruş penceresi."""

    machine_id: str
    start_min: int
    end_min: int
    maintenance_type: str = "PREVENTIVE"
    description: str = ""

    @property
    def duration_min(self) -> int:
        return max(0, self.end_min - self.start_min)


def load_machine_maintenance_windows(conn: Any = None) -> list[MaintenanceWindow]:
    """
    Veritabanından (veya tanımlı tablodan) planlı bakım pencerelerini okur.
    Tablo yoksa veya bağlantı verilmezse boş liste döner.
    """
    if conn is None:
        return []

    try:
        query = """
            SELECT machine_id, start_min, end_min, maintenance_type, description
            FROM machine_maintenance
            WHERE is_active = 1
        """
        df = pd.read_sql(query, conn)
        windows = []
        for _, row in df.iterrows():
            windows.append(
                MaintenanceWindow(
                    machine_id=str(row["machine_id"]),
                    start_min=int(row["start_min"]),
                    end_min=int(row["end_min"]),
                    maintenance_type=str(row.get("maintenance_type", "PREVENTIVE")),
                    description=str(row.get("description", "")),
                )
            )
        return windows
    except Exception:
        return []


def inject_maintenance_intervals_into_model(
    model: Any,
    machine_intervals_map: dict[str, list[Any]],
    maintenance_windows: list[MaintenanceWindow],
) -> list[dict[str, Any]]:
    """
    Planlı bakım pencerelerini CP-SAT modeline sabit IntervalVar olarak ekler
    ve ilgili tezgâhın NoOverlap listesine iliştirir.
    """
    injected_records = []
    for idx, mw in enumerate(maintenance_windows):
        m_id = mw.machine_id
        if mw.duration_min <= 0:
            continue

        var_name = f"maint_{m_id}_{idx}"
        fixed_interval = model.NewFixedSizeIntervalVar(mw.start_min, mw.duration_min, var_name)

        if m_id not in machine_intervals_map:
            machine_intervals_map[m_id] = []
        machine_intervals_map[m_id].append(fixed_interval)

        injected_records.append(
            {
                "machine_id": m_id,
                "start_min": mw.start_min,
                "end_min": mw.end_min,
                "duration_min": mw.duration_min,
                "type": mw.maintenance_type,
                "var_name": var_name,
            }
        )

    return injected_records
