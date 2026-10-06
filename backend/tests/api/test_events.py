"""Unit tests for the SSE EventBus: no key leak + thread-safe delivery."""
import asyncio
import threading

from accordance.api.events import EventBus


def test_publish_to_unknown_run_does_not_create_key():
    bus = EventBus()
    bus.publish("ghost-run", {"type": "noise"})
    assert "ghost-run" not in bus._queues


def test_unsubscribe_removes_empty_run_key():
    async def go():
        bus = EventBus()
        q = bus.subscribe("r1")
        assert "r1" in bus._queues
        bus.unsubscribe("r1", q)
        assert "r1" not in bus._queues

    asyncio.run(go())


def test_publish_from_worker_thread_delivers_to_subscriber():
    async def go():
        bus = EventBus()
        q = bus.subscribe("r1")

        def worker():
            bus.publish("r1", {"type": "hello"})

        threading.Thread(target=worker).start()
        msg = await asyncio.wait_for(q.get(), timeout=3)
        assert msg == {"type": "hello"}

    asyncio.run(go())
