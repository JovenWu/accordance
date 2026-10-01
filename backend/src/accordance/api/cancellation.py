"""Process-wide cooperative cancellation for in-flight runs.

Python threads can't be killed safely, so we use a flag the workers
check between operations. In-flight LLM calls and Docling extraction
will finish naturally, but the worker stops issuing new work once the
flag is set.
"""
import threading


class CancellationRegistry:
    def __init__(self) -> None:
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()

    def cancel(self, run_id: str) -> None:
        with self._lock:
            self._cancelled.add(run_id)

    def is_cancelled(self, run_id: str) -> bool:
        return run_id in self._cancelled

    def clear(self, run_id: str) -> None:
        with self._lock:
            self._cancelled.discard(run_id)


registry = CancellationRegistry()
