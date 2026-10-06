"""Prepare a verified ACTIVE run before starting the container services."""

import argparse
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import run_end_to_end_pipeline
from scripts.verify_active_run import main as verify_active
from src.config import get_runtime_paths
from src.utils.db import get_active_run_id, get_db_connection
from src.utils.runtime_lock import run_mutation_lock


def bootstrap(refresh: bool = False):
    db_path = Path(get_runtime_paths()["db_path"])
    with run_mutation_lock(db_path):
        active = None
        if db_path.exists():
            with closing(get_db_connection(db_path)) as conn:
                try:
                    active = get_active_run_id(conn)
                except RuntimeError:
                    pass
        if refresh or not active:
            run_end_to_end_pipeline()
        verify_active()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Publish a fresh pipeline version.")
    bootstrap(parser.parse_args().refresh)
