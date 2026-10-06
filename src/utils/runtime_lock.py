"""Serialize writers sharing a canonical SQLite database across threads/processes."""

from contextlib import contextmanager
from pathlib import Path
from threading import Lock, RLock, local

_registry_lock = Lock()
_locks = {}
_owned = local()


@contextmanager
def run_mutation_lock(db_path):
    target = Path(db_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with _registry_lock:
        thread_lock = _locks.setdefault(str(target), RLock())
    with thread_lock:
        held = getattr(_owned, "paths", set())
        if str(target) in held:
            yield
            return
        with (target.parent / f".{target.name}.run.lock").open("a+b") as handle:
            _owned.paths = held | {str(target)}
            try:
                with _process_lock(handle):
                    yield
            finally:
                _owned.paths = held


@contextmanager
def _process_lock(handle):
    import sys

    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    try:
        yield
    finally:
        if sys.platform == "win32":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
