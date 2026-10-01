"""Cross-encoder reranking of a candidate chunk pool.

The judge retrieves with several queries and unions the results; this reranks
that union against the disclosure requirement and returns the best top-n by
INDEX, so the judge sees chunks in relevance order instead of page order.

FlashRank is local (ONNX, no PyTorch/GPU). `ms-marco-MultiBERT-L-12` is the
multilingual model — sustainability reports are often bilingual.
"""
from __future__ import annotations

from typing import Protocol


class Reranker(Protocol):
    def rerank(self, query: str, passages: list[str], top_n: int) -> list[int]:
        """Return indices into `passages`, best-first, length <= top_n.

        All returned indices must be in range [0, len(passages)) and distinct.
        """
        ...


class NoOpReranker:
    """Identity reranker (keeps input order). For tests / explicit pass-through."""

    def rerank(self, query: str, passages: list[str], top_n: int) -> list[int]:
        return list(range(len(passages)))[:top_n]


# onnxruntime defaults its intra-op thread pool to ONE THREAD PER CPU CORE, so
# FlashRank's session pins every core on a many-core box (and overwhelms a
# low-core production server) during the per-disclosure reranking. FlashRank
# exposes no thread setting, so we cap onnxruntime globally — see
# _install_onnx_thread_cap.
_THREAD_CAP_INSTALLED = False


def _capped_session_options(threads: int):
    """An onnxruntime SessionOptions limited to `threads` intra/inter-op threads."""
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = threads
    return so


def _install_onnx_thread_cap(threads: int) -> None:
    """Cap onnxruntime CPU threads for sessions created without explicit options.

    FlashRank builds ``ort.InferenceSession(path)`` with no SessionOptions, so
    onnxruntime spins up one intra-op thread per core. We wrap InferenceSession
    once (process-global, idempotent) to inject a thread-capped SessionOptions
    when the caller didn't supply one — keeping reranking off every core so a
    constrained production server stays responsive. Callers that pass their own
    ``sess_options`` are left untouched.
    """
    global _THREAD_CAP_INSTALLED
    if _THREAD_CAP_INSTALLED or threads <= 0:
        return
    try:
        import onnxruntime as ort
    except ImportError:
        return

    orig = ort.InferenceSession

    def _capped(*args, **kwargs):
        # InferenceSession(path, sess_options=..., ...) — inject only when the
        # caller gave neither a positional nor keyword sess_options.
        if "sess_options" not in kwargs and len(args) < 2:
            kwargs["sess_options"] = _capped_session_options(threads)
        return orig(*args, **kwargs)

    ort.InferenceSession = _capped
    _THREAD_CAP_INSTALLED = True


class FlashRankReranker:
    """FlashRank-backed cross-encoder reranker."""

    def __init__(self, model_name: str, threads: int = 2) -> None:
        # Cap onnxruntime threads BEFORE FlashRank builds its session.
        _install_onnx_thread_cap(threads)
        from flashrank import Ranker

        self._ranker = Ranker(model_name=model_name)

    def rerank(self, query: str, passages: list[str], top_n: int) -> list[int]:
        if not passages:
            return []
        from flashrank import RerankRequest

        req = RerankRequest(
            query=query,
            passages=[{"id": i, "text": t} for i, t in enumerate(passages)],
        )
        results = self._ranker.rerank(req)  # sorted by score desc; each has "id"
        return [int(r["id"]) for r in results][:top_n]


def build_reranker(enabled: bool, model: str, threads: int = 2) -> Reranker | None:
    """Return a reranker, or None when disabled (judge falls back to page-order).

    `threads` caps the onnxruntime CPU thread pool so reranking doesn't pin
    every core (matters on dev laptops and low-core production servers).
    """
    if not enabled:
        return None
    return FlashRankReranker(model, threads)
