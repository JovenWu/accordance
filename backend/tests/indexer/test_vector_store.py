import pytest

from accordance.db import connection, ensure_embedding_dim
from accordance.indexer.chunker import Chunk
from accordance.indexer.vector_store import VectorStore


class FakeEmbedder:
    """Deterministic 8-dim embeddings keyed on whether 'water' is in the text."""

    def embed_documents(self, texts):
        return [
            [1.0, 0, 0, 0, 0, 0, 0, 0] if "water" in t.lower() else [0, 1.0, 0, 0, 0, 0, 0, 0]
            for t in texts
        ]

    def embed_query(self, q):
        return [1.0, 0, 0, 0, 0, 0, 0, 0] if "water" in q.lower() else [0, 1.0, 0, 0, 0, 0, 0, 0]


def _seed_run(conn, run_id):
    conn.execute("INSERT INTO reports (id, name) VALUES (%s, 'r')", (run_id + "_rep",))
    conn.execute(
        "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
        "pdf_sha256, pdf_path, status) VALUES "
        "(%s, %s, 1, 'initial', 'f', 's', 'p', 'indexing')",
        (run_id, run_id + "_rep"),
    )


@pytest.fixture
def store():
    with connection() as conn:
        ensure_embedding_dim(conn, dim=8)
        yield VectorStore(conn, FakeEmbedder(), mode="hybrid"), conn


def test_write_and_dense_retrieve_is_run_scoped(store):
    vs, conn = store
    _seed_run(conn, "runA")
    _seed_run(conn, "runB")
    vs.write("runA", [Chunk(page=1, text="water withdrawal 303-3")])
    vs.write("runB", [Chunk(page=1, text="water withdrawal other run")])
    hits = vs.retrieve_dense("runA", "water", k=5)
    assert len(hits) == 1
    assert all(h["chunk_id"] for h in hits)  # only runA's chunk


def test_bm25_or_semantics(store):
    vs, conn = store
    _seed_run(conn, "runA")
    vs.write(
        "runA",
        [Chunk(page=1, text="greenhouse gas emissions"), Chunk(page=2, text="board governance")],
    )
    hits = vs.retrieve_bm25("runA", "emissions board", k=5)
    assert len(hits) == 2  # OR: both chunks hit at least one token


def test_retrieve_by_tag_boundary(store):
    """retrieve_by_tag("2-1") must NOT match chunks containing [[GRI 2-10]].

    The regex boundary (?![\\d-]) in retrieve_by_tag ensures "2-1" does not
    match "2-10", "2-11", etc.
    """
    vs, conn = store
    _seed_run(conn, "runT")
    vs.write(
        "runT",
        [
            Chunk(page=1, text="See [[GRI 2-1]] for board composition."),
            Chunk(page=10, text="See [[GRI 2-10]] for diversity data."),
        ],
    )
    hits = vs.retrieve_by_tag("runT", "2-1")
    pages = [h["page"] for h in hits]
    assert 1 in pages  # GRI 2-1 matched
    assert 10 not in pages  # GRI 2-10 must NOT match "2-1"


def test_retrieve_page_siblings_excludes_ids(store):
    """retrieve_page_siblings respects exclude_ids and is safe with exclude_ids=[]."""
    vs, conn = store
    _seed_run(conn, "runS")
    ids = vs.write(
        "runS",
        [
            Chunk(page=3, text="page three chunk a"),
            Chunk(page=3, text="page three chunk b"),
            Chunk(page=4, text="page four chunk c"),
        ],
    )
    id_a, id_b, id_c = ids

    # With one id excluded: that id is absent, others on those pages present.
    hits = vs.retrieve_page_siblings("runS", pages=[3, 4], exclude_ids=[id_a])
    hit_ids = [h["chunk_id"] for h in hits]
    assert id_a not in hit_ids
    assert id_b in hit_ids
    assert id_c in hit_ids
    # Results are ordered by id (deterministic).
    assert hit_ids == sorted(hit_ids)

    # With exclude_ids=[] (empty): all chunks on those pages are returned.
    # This guards the "AND id NOT IN ()" SQL anti-pattern that would filter
    # ALL rows when the IN-list is empty.
    hits_all = vs.retrieve_page_siblings("runS", pages=[3, 4], exclude_ids=[])
    hit_ids_all = [h["chunk_id"] for h in hits_all]
    assert id_a in hit_ids_all
    assert id_b in hit_ids_all
    assert id_c in hit_ids_all


def test_write_is_idempotent(store):
    """Writing the same run_id twice replaces rows, not appends."""
    vs, conn = store
    _seed_run(conn, "runI")
    chunks = [
        Chunk(page=1, text="water usage report data"),
        Chunk(page=2, text="energy consumption metrics"),
    ]
    vs.write("runI", chunks)
    vs.write("runI", chunks)  # Second write of the same run_id
    row = conn.execute("SELECT COUNT(*) AS cnt FROM chunks WHERE run_id=%s", ("runI",)).fetchone()
    assert row["cnt"] == len(chunks)  # Exactly one copy, not doubled


def test_retrieve_hybrid_merges_both(store):
    """retrieve_hybrid fuses dense and BM25 results via RRF.

    Chunk A ("water …") matches via dense cosine distance for a "water" query.
    Chunk B ("greenhouse emission …") matches via BM25 because its keyword
    "emission" appears in the query. Both must appear in the fused top-k.
    """
    vs, conn = store
    _seed_run(conn, "runHY")
    vs.write(
        "runHY",
        [
            Chunk(page=1, text="water consumption data"),
            Chunk(page=2, text="greenhouse emission reduction target"),
        ],
    )
    # "water" drives the dense embedding; "emission" is a BM25 hit on chunk B.
    hits = vs.retrieve_hybrid("runHY", "water emission", k=2)
    assert len(hits) == 2  # RRF fused dense (chunk A) + BM25 (chunk B)


def test_bm25_all_stopwords_returns_empty(store):
    """retrieve_bm25 returns [] for stopword-only queries without raising.

    "the", "a", and "is" are all English stopwords in PostgreSQL's default
    text-search configuration. Documents the PG16-safe empty-tsquery behavior:
    no exception is propagated and the caller receives an empty list.
    """
    vs, conn = store
    _seed_run(conn, "runBM")
    vs.write("runBM", [Chunk(page=1, text="water consumption data")])
    result = vs.retrieve_bm25("runBM", "the a is", k=5)
    assert result == []
