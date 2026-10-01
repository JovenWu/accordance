import pytest

from accordance.indexer.reranker import NoOpReranker, build_reranker


def test_noop_is_identity_capped():
    r = NoOpReranker()
    assert r.rerank("q", ["a", "b", "c"], top_n=2) == [0, 1]
    assert r.rerank("q", ["a", "b", "c"], top_n=10) == [0, 1, 2]
    assert r.rerank("q", [], top_n=5) == []


def test_build_reranker_disabled_returns_none():
    assert build_reranker(False, "ms-marco-MultiBERT-L-12") is None


def test_capped_session_options_sets_thread_counts():
    pytest.importorskip("onnxruntime")
    from accordance.indexer.reranker import _capped_session_options

    so = _capped_session_options(3)
    assert so.intra_op_num_threads == 3
    assert so.inter_op_num_threads == 3


def test_install_onnx_thread_cap_injects_capped_options(monkeypatch):
    ort = pytest.importorskip("onnxruntime")
    import accordance.indexer.reranker as r

    captured = {}

    def fake_session(*args, **kwargs):
        captured["sess_options"] = kwargs.get("sess_options")
        return object()

    monkeypatch.setattr(ort, "InferenceSession", fake_session)
    monkeypatch.setattr(r, "_THREAD_CAP_INSTALLED", False)
    r._install_onnx_thread_cap(2)
    # FlashRank constructs the session positionally with no SessionOptions.
    ort.InferenceSession("dummy.onnx")
    so = captured["sess_options"]
    assert so is not None
    assert so.intra_op_num_threads == 2
    assert so.inter_op_num_threads == 2


def test_install_onnx_thread_cap_respects_caller_options(monkeypatch):
    ort = pytest.importorskip("onnxruntime")
    import accordance.indexer.reranker as r

    captured = {}

    def fake_session(*args, **kwargs):
        captured["sess_options"] = kwargs.get("sess_options")
        return object()

    monkeypatch.setattr(ort, "InferenceSession", fake_session)
    monkeypatch.setattr(r, "_THREAD_CAP_INSTALLED", False)
    r._install_onnx_thread_cap(2)
    explicit = ort.SessionOptions()
    explicit.intra_op_num_threads = 7
    ort.InferenceSession("dummy.onnx", sess_options=explicit)
    # A caller that supplies its own options must not be overridden.
    assert captured["sess_options"].intra_op_num_threads == 7


def test_flashrank_ranks_relevant_passage_first():
    pytest.importorskip("flashrank")
    from accordance.indexer.reranker import FlashRankReranker

    r = FlashRankReranker("ms-marco-MultiBERT-L-12")
    passages = [
        "The cat sat quietly on the warm mat all afternoon.",
        "Total water withdrawal in FY2024 was 41 megaliters across all sites.",
    ]
    order = r.rerank("total water withdrawal in megaliters", passages, top_n=2)
    assert order[0] == 1  # the water passage outranks the cat passage
