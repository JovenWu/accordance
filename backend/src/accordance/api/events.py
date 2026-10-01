import asyncio


class EventBus:
    """In-process pub/sub for run progress events feeding the SSE /stream route.

    Thread-safety: subscribers live on the event loop, but publish() is called
    from run-worker threads. asyncio.Queue is NOT thread-safe, so each delivery
    is marshalled back onto the subscriber's loop via call_soon_threadsafe.
    """

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue]] = {}
        # Loop captured per queue at subscribe time (subscribe runs on the loop).
        self._loops: dict[asyncio.Queue, asyncio.AbstractEventLoop | None] = {}

    def subscribe(self, run_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.setdefault(run_id, []).append(q)
        try:
            self._loops[q] = asyncio.get_running_loop()
        except RuntimeError:
            self._loops[q] = None  # no running loop (sync context) — best-effort
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        subs = self._queues.get(run_id)
        if subs and q in subs:
            subs.remove(q)
            if not subs:
                # Drop the empty key so _queues doesn't grow one entry per run
                # for the lifetime of the process.
                del self._queues[run_id]
        self._loops.pop(q, None)

    def publish(self, run_id: str, event: dict) -> None:
        # .get with a default tuple: never insert a key just by publishing.
        for q in list(self._queues.get(run_id, ())):
            loop = self._loops.get(q)
            if loop is not None and not loop.is_closed():
                loop.call_soon_threadsafe(self._safe_put, q, event)
            else:
                self._safe_put(q, event)

    @staticmethod
    def _safe_put(q: asyncio.Queue, event: dict) -> None:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


bus = EventBus()
