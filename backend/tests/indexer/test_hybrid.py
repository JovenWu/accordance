"""Tests for hybrid retrieval (dense + BM25 + RRF)."""

import pytest

from accordance.db import connection
from accordance.indexer.chunker import Chunk
from accordance.indexer.embedder import FakeEmbedder
from accordance.indexer.vector_store import (
    VectorStore,
    _to_tsquery,
    reciprocal_rank_fusion,
)


def _seed_run(c, run_id: str, *, sha: str = "sha", report_id: str | None = None) -> None:
    rep = report_id or (run_id + "_rep")
    c.execute("INSERT INTO reports (id, name) VALUES (%s, %s)", (rep, "x.pdf"))
    c.execute(
        "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
        "pdf_sha256, pdf_path, status) "
        "VALUES (%s, %s, 1, 'initial', 'x.pdf', %s, 'x', 'queued')",
        (run_id, rep, sha),
    )


def _seed_chunks(store: VectorStore, run_id: str = "r1") -> None:
    store.write(
        run_id,
        [
            Chunk(page=4, text="About Acme Industries: legal name and headquarters."),
            Chunk(page=10, text="Employee count broken down by region and gender."),
            Chunk(page=47, text="Scope 1 emissions for FY2024 totaled 12,450 tCO2e."),
            Chunk(page=48, text="Water withdrawal totaled 41 megaliters across all sites."),
            Chunk(page=99, text="Unrelated marketing fluff with no metric content."),
        ],
    )


@pytest.fixture
def conn():
    with connection() as c:
        yield c


def test_rrf_combines_two_rankings():
    """Item in both rankings outscores items in only one."""
    rankings = [
        [10, 20, 30],
        [20, 10, 40],
    ]
    fused = reciprocal_rank_fusion(rankings, k_constant=60)
    by_id = {cid: score for cid, score in fused}
    assert abs(by_id[10] - by_id[20]) < 1e-9
    assert by_id[10] > by_id[30]
    assert by_id[10] > by_id[40]


def test_rrf_handles_empty_rankings():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


def test_build_fts_query_or_joins_tokens():
    q = _to_tsquery("Scope 1 emissions")
    assert q == "scope | 1 | emissions"


def test_build_fts_query_returns_empty_for_punctuation_only():
    assert _to_tsquery("!!! ???") == ""


def test_build_fts_query_strips_special_chars():
    q = _to_tsquery("GRI 305-1: Scope 1")
    tokens = q.split(" | ")
    assert "gri" in tokens
    assert "305" in tokens
    assert "1" in tokens


def test_bm25_finds_keyword_match(conn):
    _seed_run(conn, "r1")
    store = VectorStore(conn, FakeEmbedder(dim=8))
    _seed_chunks(store)
    hits = store.retrieve_bm25("r1", "Scope 1 emissions", k=2)
    assert hits[0]["page"] == 47
    assert "Scope 1" in hits[0]["text"]


def test_bm25_returns_empty_when_no_match(conn):
    _seed_run(conn, "r1")
    store = VectorStore(conn, FakeEmbedder(dim=8))
    _seed_chunks(store)
    hits = store.retrieve_bm25("r1", "xyzzy plugh quux", k=5)
    assert hits == []


def test_bm25_scopes_to_run_id(conn):
    _seed_run(conn, "r1", sha="sha1")
    _seed_run(conn, "r2", sha="sha2")
    store = VectorStore(conn, FakeEmbedder(dim=8))
    store.write("r1", [Chunk(page=1, text="alpha keyword")])
    store.write("r2", [Chunk(page=1, text="alpha keyword in other run")])
    hits = store.retrieve_bm25("r1", "alpha", k=10)
    assert len(hits) == 1
    assert hits[0]["page"] == 1


def test_hybrid_returns_chunks_for_keyword_query(conn):
    _seed_run(conn, "r1")
    store = VectorStore(conn, FakeEmbedder(dim=8), mode="hybrid")
    _seed_chunks(store)
    hits = store.retrieve("r1", "Scope 1 emissions", k=3)
    pages = [h["page"] for h in hits]
    assert 47 in pages


def test_hybrid_degrades_to_dense_when_no_bm25_hits(conn):
    """When BM25 has zero matches, hybrid falls back to dense results."""
    _seed_run(conn, "r1")
    store = VectorStore(conn, FakeEmbedder(dim=8), mode="hybrid")
    _seed_chunks(store)
    hits = store.retrieve("r1", "xyzzy", k=2)
    assert len(hits) <= 2


def test_mode_dense_skips_bm25(conn, monkeypatch):
    _seed_run(conn, "r1")
    store = VectorStore(conn, FakeEmbedder(dim=8), mode="dense")
    _seed_chunks(store)
    called = {"bm25": 0}
    orig = store.retrieve_bm25

    def spy(*args, **kwargs):
        called["bm25"] += 1
        return orig(*args, **kwargs)

    monkeypatch.setattr(store, "retrieve_bm25", spy)
    store.retrieve("r1", "Scope 1", k=3)
    assert called["bm25"] == 0


def test_mode_bm25_skips_dense(conn, monkeypatch):
    _seed_run(conn, "r1")
    store = VectorStore(conn, FakeEmbedder(dim=8), mode="bm25")
    _seed_chunks(store)
    called = {"dense": 0}
    orig = store.retrieve_dense

    def spy(*args, **kwargs):
        called["dense"] += 1
        return orig(*args, **kwargs)

    monkeypatch.setattr(store, "retrieve_dense", spy)
    store.retrieve("r1", "Scope 1", k=3)
    assert called["dense"] == 0
