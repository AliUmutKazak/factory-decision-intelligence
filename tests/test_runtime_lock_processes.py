"""The canonical SQLite write guard must work across separate processes."""

from multiprocessing import get_context

from src.utils.runtime_lock import run_mutation_lock


def _hold_lock(path, acquired, release):
    with run_mutation_lock(path):
        acquired.set()
        if not release.wait(10):
            raise TimeoutError("test did not release writer")


def _wait_for_lock(path, acquired):
    with run_mutation_lock(path):
        acquired.set()


def test_separate_processes_cannot_mutate_one_runtime_at_the_same_time(tmp_path):
    ctx = get_context("spawn")
    path = tmp_path / "factory.db"
    first_acquired = ctx.Event()
    release = ctx.Event()
    second_acquired = ctx.Event()
    first = ctx.Process(target=_hold_lock, args=(path, first_acquired, release))
    second = ctx.Process(target=_wait_for_lock, args=(path, second_acquired))
    first.start()
    try:
        assert first_acquired.wait(10), "first writer could not acquire the lock"
        second.start()
        assert not second_acquired.wait(0.5), "second writer entered during first writer"
    finally:
        release.set()
        first.join(10)
        if first.is_alive():
            first.terminate()
            first.join()
        if second.pid is not None:
            second.join(10)
            if second.is_alive():
                second.terminate()
                second.join()
    assert first.exitcode == 0
    assert second.exitcode == 0
    assert second_acquired.is_set()
