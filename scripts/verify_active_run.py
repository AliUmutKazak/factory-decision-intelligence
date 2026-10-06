"""Verify the ACTIVE database version and its sealed artifact bundle."""

import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_runtime_paths
from src.utils.db import get_active_run_id, get_db_connection
from src.utils.lineage import validate_pipeline_run
from src.utils.run_bundle import verify_run_bundle


def main():
    paths = get_runtime_paths()
    with closing(get_db_connection(paths["db_path"])) as conn:
        run_id = get_active_run_id(conn)
        assert conn.execute("SELECT COUNT(*) FROM pipeline_runs WHERE status = 'ACTIVE'").fetchone()[0] == 1
    bundle = Path(paths["base_dir"]) / "artifacts" / "runs" / run_id
    verify_run_bundle(bundle, run_id)
    validate_pipeline_run(run_id, db_path=str(bundle / "factory.db"), reports_dir=str(bundle / "reports"))
    print(f"ACTIVE run {run_id}: database, physics, lineage and bundle hashes verified.")


if __name__ == "__main__":
    main()
