"""All local solver entry points share one bounded runtime slot."""

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.utils.solver_slot import SolverBusyError, solver_slot


def test_solver_slot_blocks_other_threads_and_releases(tmp_path):
    db_path = tmp_path / "factory.db"

    def contend():
        with solver_slot(db_path):
            return "unexpected"

    with solver_slot(db_path), ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(SolverBusyError):
            pool.submit(contend).result()
    assert contend() == "unexpected"


def test_solver_slot_blocks_other_processes(tmp_path):
    db_path = tmp_path / "factory.db"
    child = (
        "import sys; from src.utils.solver_slot import SolverBusyError, solver_slot; "
        "\ntry:\n with solver_slot(sys.argv[1]): pass\n"
        "except SolverBusyError: sys.exit(23)\n"
    )
    with solver_slot(db_path):
        result = subprocess.run([sys.executable, "-c", child, str(db_path)], check=False, capture_output=True)
    assert result.returncode == 23, result.stderr.decode(errors="replace")
    result = subprocess.run([sys.executable, "-c", child, str(db_path)], check=False, capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
