from accordance.indexer.embedder import FakeEmbedder, build_embedder


def test_fake_embedder_returns_consistent_vectors():
    e = FakeEmbedder(dim=8)
    v1 = e.embed_query("hello")
    v2 = e.embed_query("hello")
    assert v1 == v2
    assert len(v1) == 8


def test_fake_embedder_batch():
    e = FakeEmbedder(dim=8)
    vs = e.embed_documents(["a", "b", "c"])
    assert len(vs) == 3
    assert all(len(v) == 8 for v in vs)


def test_build_embedder_returns_fake_in_test_mode():
    e = build_embedder("fake:fake", api_key="")
    assert isinstance(e, FakeEmbedder)
