"""Nonblocking solver admission shared by local API, dashboard and dispatcher."""

from __future__ import annotations

import errno
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from threading import Lock
from typing import Any

_registry_lock = Lock()
_locks: dict[str, Lock] = {}


class SolverBusyError(RuntimeError):
    """A solver is already using this local runtime."""


@contextmanager
def solver_slot(db_path: str | Path) -> Iterator[None]:
    target = Path(db_path).resolve()
    with _registry_lock:
        thread_lock = _locks.setdefault(str(target), Lock())
    if not thread_lock.acquire(blocking=False):
        raise SolverBusyError("solver is busy")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with (target.parent / f".{target.name}.solver.lock").open("a+b") as handle:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0, 2)
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    if exc.winerror in {33, 36} or exc.errno in {errno.EACCES, errno.EAGAIN}:
                        raise SolverBusyError("solver is busy") from exc
                    raise
            else:
                import fcntl

                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    if exc.errno in {errno.EACCES, errno.EAGAIN}:
                        raise SolverBusyError("solver is busy") from exc
                    raise
            try:
                yield
            finally:
                if sys.platform == "win32":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        thread_lock.release()


def admitted_solver_call(method: Callable[..., Any]) -> Callable[..., Any]:
    """Guard a solver entry point using its instance's canonical DB path."""

    @wraps(method)
    def guarded(self: Any, *args: Any, **kwargs: Any) -> Any:
        with solver_slot(self.disk_db_path):
            return method(self, *args, **kwargs)

    return guarded
