"""Run-admission semaphore (bounded concurrent runs) + graceful shutdown drain."""
import threading
import time

import accordance.api.runs as runs_mod
from accordance.api.cancellation import registry as cancel_registry
from accordance.config import Settings


def _reset_admission():
    runs_mod._run_admission = None
    with runs_mod._active_runs_lock:
        runs_mod._active_runs.clear()


def test_admission_semaphore_bounds_to_config():
    _reset_admission()
    sem = runs_mod._admission_semaphore(Settings(max_concurrent_runs=2))
    assert sem.acquire(blocking=False) is True
    assert sem.acquire(blocking=False) is True
    assert sem.acquire(blocking=False) is False
    sem.release()
    sem.release()


def test_spawn_admitted_runs_work_and_unregisters():
    _reset_admission()
    s = Settings(max_concurrent_runs=2)
    done = threading.Event()
    t = runs_mod._spawn_admitted(s, done.set, run_id="r-done")
    t.join(timeout=2)
    assert done.is_set()
    with runs_mod._active_runs_lock:
        assert t not in runs_mod._active_runs


def test_drain_cancels_active_runs_and_joins():
    _reset_admission()
    s = Settings(max_concurrent_runs=2)
    rid = "r-drain"
    cancel_registry.clear(rid)

    def work():
        while not cancel_registry.is_cancelled(rid):
            time.sleep(0.01)

    t = runs_mod._spawn_admitted(s, work, run_id=rid)
    try:
        n = runs_mod.drain_active_runs(timeout=3)
        assert n == 1
        assert cancel_registry.is_cancelled(rid)
        assert not t.is_alive()
    finally:
        cancel_registry.clear(rid)
