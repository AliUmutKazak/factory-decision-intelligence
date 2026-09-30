from ortools.sat.python import cp_model

from src.scheduling.maintenance import (
    MaintenanceWindow,
    inject_maintenance_intervals_into_model,
)


def test_maintenance_interval_prevents_job_overlap():
    """
    Planlı bakım penceresi (100-200 dk) olan bir tezgâhta,
    150 dk süren bir işin bakım aralığına denk gelemeyeceğini,
    zorunlu olarak ya 0'da başlayıp 100'den önce biteceğini ya da 200'den sonra başlayacağını doğrular.
    """
    model = cp_model.CpModel()
    horizon = 500

    # İş: 150 dakika sürüyor
    job_start = model.NewIntVar(0, horizon, "job_start")
    job_end = model.NewIntVar(0, horizon, "job_end")
    job_interval = model.NewIntervalVar(job_start, 150, job_end, "job_interval")

    machine_intervals = {"M1": [job_interval]}

    # Bakım Penceresi: M1 makinesinde [100, 200] dakikaları arası
    maintenance = [
        MaintenanceWindow(
            machine_id="M1",
            start_min=100,
            end_min=200,
            maintenance_type="PREVENTIVE",
        )
    ]

    inject_maintenance_intervals_into_model(model, machine_intervals, maintenance)

    # Tezgaha NoOverlap uygula
    model.AddNoOverlap(machine_intervals["M1"])

    # İşi mümkün olan en erken zamanda bitirmeye çalış
    model.Minimize(job_end)

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    assert status == cp_model.OPTIMAL
    start_val = solver.Value(job_start)
    end_val = solver.Value(job_end)

    # İş 150 dk sürdüğü için [0, 100) arasına sığamaz (100 < 150).
    # Bu yüzden bakım bitiminden (200) önce bitemez, mecburen 200 veya sonrasında başlamalıdır!
    assert start_val >= 200
    assert end_val == start_val + 150
