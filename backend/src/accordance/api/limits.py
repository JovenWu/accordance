"""Lightweight, in-process request limits.

Two guards, both sized for the single-instance deployment (no shared store):

- ``MaxBodySizeMiddleware`` rejects oversized request bodies at the ASGI layer
  from the Content-Length header, BEFORE Starlette's multipart parser spools the
  body to disk — so an oversized upload is refused at the door rather than after
  being buffered (the in-handler streaming cap remains as the fallback for
  chunked uploads that omit Content-Length).

- ``FailureLimiter`` is a thread-safe sliding-window counter used to throttle
  failed logins per client IP and per username (online brute-force / credential
  stuffing defense). State is in-memory; on a multi-instance deployment promote
  this to a shared store.
"""

from __future__ import annotations

import threading
import time

from starlette.responses import PlainTextResponse


class MaxBodySizeMiddleware:
    """Refuse requests whose declared Content-Length exceeds ``max_bytes``."""

    def __init__(self, app, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and self.max_bytes > 0:
            for name, value in scope.get("headers", ()):
                if name == b"content-length":
                    try:
                        declared = int(value)
                    except ValueError:
                        break
                    if declared > self.max_bytes:
                        resp = PlainTextResponse(
                            "Request body too large.", status_code=413
                        )
                        await resp(scope, receive, send)
                        return
                    break
        await self.app(scope, receive, send)


class FailureLimiter:
    """Thread-safe sliding-window failure counter keyed by arbitrary strings.

    The login handler runs in Starlette's threadpool (sync ``def``), so multiple
    requests can touch this concurrently — every access is taken under a lock.
    """

    def __init__(self) -> None:
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _now(now: float | None) -> float:
        return now if now is not None else time.monotonic()

    def is_blocked(
        self, key: str, *, limit: int, window: float, now: float | None = None
    ) -> bool:
        """True if ``key`` has >= ``limit`` failures within the last ``window``
        seconds. Prunes expired entries as a side effect."""
        if limit <= 0:
            return False
        t = self._now(now)
        with self._lock:
            recent = [ts for ts in self._fails.get(key, ()) if t - ts < window]
            if recent:
                self._fails[key] = recent
            else:
                self._fails.pop(key, None)
            return len(recent) >= limit

    def record_failure(self, key: str, *, window: float, now: float | None = None) -> None:
        t = self._now(now)
        with self._lock:
            recent = [ts for ts in self._fails.get(key, ()) if t - ts < window]
            recent.append(t)
            self._fails[key] = recent

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._fails.clear()


login_limiter = FailureLimiter()


def client_ip(request) -> str:
    """Best-effort client IP for rate-limit keying. With uvicorn --proxy-headers
    this reflects the proxy-forwarded client address; otherwise the peer."""
    client = getattr(request, "client", None)
    if client is not None and client.host:
        return client.host
    return "unknown"
