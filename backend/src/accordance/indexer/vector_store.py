import re
from collections import defaultdict
from typing import Literal, TypedDict

from pgvector import Vector

from accordance.indexer.chunker import Chunk
from accordance.indexer.embedder import Embedder

RetrievalMode = Literal["hybrid", "dense", "bm25"]


def _to_tsquery(q: str) -> str:
    """OR-join sanitized alnum tokens into a tsquery string: 'a | b | c'.
    Returns '' when no usable tokens (caller treats as no BM25 hits)."""
    tokens = re.findall(r"\w+", q.lower())
    return " | ".join(tokens)


def reciprocal_rank_fusion(
    rankings: list[list[int]], k_constant: int = 60
) -> list[tuple[int, float]]:
    """Standard RRF: score(d) = sum over ranking r of 1 / (k + rank_r(d)).

    `k_constant=60` is the canonical default from Cormack et al. 2009 —
    high enough that the top items from each ranking don't dominate the
    fused list, low enough that meaningful rank differences still matter.

    Returns chunk-id/score pairs sorted by descending score.
    """
    scores: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] += 1.0 / (k_constant + rank)
    return sorted(scores.items(), key=lambda x: -x[1])


class RetrievedChunk(TypedDict):
    chunk_id: int
    page: int
    text: str
    distance: float


class VectorStore:
    """Per-run chunk store with dense (pgvector) + lexical (PG full-text) retrieval.

    `mode` chooses the retrieval strategy used by ``retrieve``:

    - ``hybrid`` (default): over-fetch from both indexes, fuse via RRF,
      return top-k. Best general-purpose accuracy.
    - ``dense``: cosine kNN only. Useful for A/B against the pre-hybrid baseline.
    - ``bm25``: lexical only. Mostly useful for diagnosing why a chunk
      didn't show up — rarely the right default.

    No _db_lock: each worker thread gets its own pooled connection, and
    Postgres MVCC removes any read/write interleaving hazard.
    """

    def __init__(
        self,
        conn,
        embedder: Embedder,
        mode: RetrievalMode = "hybrid",
    ) -> None:
        self.conn = conn
        self.embedder = embedder
        self.mode = mode

    def _delete_run(self, run_id: str) -> None:
        self.conn.execute("DELETE FROM chunks WHERE run_id=%s", (run_id,))

    def write(self, run_id: str, chunks: list[Chunk]) -> list[int]:
        """Insert chunks (text + embedding). Returns chunk ids.

        Idempotent: any existing rows for run_id are removed before inserting,
        so re-indexing the same run produces exactly one copy of each chunk.
        text_tsv is a generated column (PG computes it automatically).
        embedding is a pgvector column; a plain Python list[float] is NOT
        auto-adapted — the code wraps it with ``Vector([float(x) for x in v])``
        explicitly because ``register_vector`` registers the type adapter for
        ``pgvector.Vector`` objects only, not bare Python lists.
        """
        self._delete_run(run_id)
        texts = [c.text for c in chunks]
        vectors = self.embedder.embed_documents(texts)
        ids: list[int] = []
        # One transaction = one commit for the whole batch (autocommit otherwise
        # fsyncs per row). text_tsv is generated; embedding is a pgvector column.
        with self.conn.transaction():
            for c, v in zip(chunks, vectors, strict=True):
                row = self.conn.execute(
                    "INSERT INTO chunks (run_id, page, text, embedding) "
                    "VALUES (%s, %s, %s, %s) RETURNING id",
                    (run_id, c.page, c.text, Vector([float(x) for x in v])),
                ).fetchone()
                ids.append(row["id"])
        return ids

    def retrieve(self, run_id: str, query: str, k: int = 5) -> list[RetrievedChunk]:
        """Top-k chunks for `query`. Strategy controlled by ``self.mode``."""
        if self.mode == "dense":
            return self.retrieve_dense(run_id, query, k)
        if self.mode == "bm25":
            return self.retrieve_bm25(run_id, query, k)
        return self.retrieve_hybrid(run_id, query, k)

    def retrieve_dense(self, run_id: str, query: str, k: int = 5) -> list[RetrievedChunk]:
        """Top-k chunks by cosine distance, scoped to run_id.

        run_id is a plain WHERE filter: the HNSW scan sees the full index and
        Postgres then filters by run_id in the executor. With pgvector ≥0.8 and
        `hnsw.iterative_scan = strict_order` (set on every connection in db.py),
        the index re-scans until it has found k rows that pass the WHERE filter,
        so filtered recall matches unfiltered recall even for small per-run
        partitions. Passes the query vector twice because psycopg does not
        deduplicate named params in positional style.
        """
        qvec = Vector([float(x) for x in self.embedder.embed_query(query)])
        rows = self.conn.execute(
            "SELECT id, page, text, embedding <=> %s AS distance "
            "FROM chunks WHERE run_id=%s AND embedding IS NOT NULL "
            "ORDER BY embedding <=> %s LIMIT %s",
            (qvec, run_id, qvec, k),
        ).fetchall()
        return [
            {
                "chunk_id": r["id"],
                "page": r["page"],
                "text": r["text"],
                "distance": float(r["distance"]),
            }
            for r in rows
        ]

    def retrieve_bm25(self, run_id: str, query: str, k: int = 5) -> list[RetrievedChunk]:
        """Top-k chunks by BM25 (ts_rank_cd), scoped to run_id.

        Tokens are OR-joined via _to_tsquery so a chunk hitting ANY keyword
        surfaces. ts_rank_cd higher = better match; we flip sign so smaller
        distance = better, matching the dense convention.
        """
        tsq = _to_tsquery(query)
        if not tsq:
            return []
        rows = self.conn.execute(
            "SELECT id, page, text, "
            "ts_rank_cd(text_tsv, to_tsquery('english', %s)) AS rank "
            "FROM chunks WHERE run_id=%s AND text_tsv @@ to_tsquery('english', %s) "
            "ORDER BY rank DESC LIMIT %s",
            (tsq, run_id, tsq, k),
        ).fetchall()
        # Flip sign so smaller distance = better, matching the dense convention.
        return [
            {
                "chunk_id": r["id"],
                "page": r["page"],
                "text": r["text"],
                "distance": -float(r["rank"]),
            }
            for r in rows
        ]

    def retrieve_by_tag(
        self, run_id: str, disclosure_id: str, limit: int = 5
    ) -> list[RetrievedChunk]:
        """Chunks that cite this disclosure's own GRI tag (e.g. '[[GRI 303-4]]').

        GRI reports self-label their data tables with the disclosure id, which
        survives extraction. Matching those tags force-surfaces the report's own
        data table for a disclosure — often an appendix table the semantic/rerank
        pass misses. Anchored to 'GRI' + a trailing non-digit/dash boundary so
        '2-1' does not match '2-10'..'2-19' and '303-4' does not match '303-40'.

        `%%GRI%%` — doubled % escapes the literal % for a LIKE pattern in a
        psycopg-parameterized query (psycopg treats % specially).
        """
        pattern = re.compile(rf"GRI\s*{re.escape(disclosure_id)}(?![\d-])")
        rows = self.conn.execute(
            "SELECT id, page, text FROM chunks WHERE run_id=%s AND text LIKE '%%GRI%%' "
            "ORDER BY page",
            (run_id,),
        ).fetchall()
        out: list[RetrievedChunk] = []
        for r in rows:
            if pattern.search(r["text"]):
                if len(out) >= limit:
                    break
                out.append(
                    {
                        "chunk_id": r["id"],
                        "page": r["page"],
                        "text": r["text"],
                        "distance": 0.0,
                    }
                )
        return out

    def retrieve_page_siblings(
        self,
        run_id: str,
        pages: list[int],
        exclude_ids: list[int],
        limit: int = 50,
    ) -> list[RetrievedChunk]:
        """Return chunks on `pages` for `run_id` that are NOT in `exclude_ids`.

        Pure Postgres read — no embedding, no LLM. Used by the page-coherent
        sibling-swap step in judge/core.py to pull in table/picture chunks
        that share a page with a top-ranked narrative chunk but scored below k.

        Returns chunks as RetrievedChunk with distance=0.0 (no ranking signal
        available; callers treat them as supplement, not primary evidence).
        Results are ordered by id (deterministic) and capped at `limit` rows
        so the caller never fetches O(100s) of rows unnecessarily.

        Only emit the NOT IN clause when exclude_ids is non-empty.
        Emitting "AND id NOT IN (NULL)" is a SQL anti-pattern: in SQL,
        "x NOT IN (NULL)" evaluates to UNKNOWN (not TRUE), filtering out ALL
        rows — a silent, hard-to-debug regression.
        """
        if not pages:
            return []
        page_ph = ",".join("%s" for _ in pages)
        excl = f" AND id NOT IN ({','.join('%s' for _ in exclude_ids)})" if exclude_ids else ""
        sql = (
            f"SELECT id, page, text FROM chunks WHERE run_id=%s "
            f"AND page IN ({page_ph}){excl} ORDER BY id LIMIT %s"
        )
        params = [run_id, *pages, *exclude_ids, limit] if exclude_ids else [run_id, *pages, limit]
        rows = self.conn.execute(sql, params).fetchall()
        return [
            {"chunk_id": r["id"], "page": r["page"], "text": r["text"], "distance": 0.0}
            for r in rows
        ]

    def retrieve_hybrid(self, run_id: str, query: str, k: int = 5) -> list[RetrievedChunk]:
        """Over-fetch from dense + BM25, fuse with RRF, return top-k.

        Over-fetches by 4x on each side. Empirically more candidates
        before RRF gives the fusion something useful to do; capped to keep
        memory/latency reasonable on huge reports.
        """
        over = max(k * 4, 20)
        dense = self.retrieve_dense(run_id, query, over)
        bm25 = self.retrieve_bm25(run_id, query, over)
        if not dense and not bm25:
            return []
        if not bm25:
            return dense[:k]
        if not dense:
            return bm25[:k]

        rankings = [
            [r["chunk_id"] for r in dense],
            [r["chunk_id"] for r in bm25],
        ]
        fused = reciprocal_rank_fusion(rankings)

        # Keep the richer record from whichever side hit it first.
        by_id: dict[int, RetrievedChunk] = {}
        for r in dense:
            by_id.setdefault(r["chunk_id"], r)
        for r in bm25:
            by_id.setdefault(r["chunk_id"], r)

        out: list[RetrievedChunk] = []
        for cid, _score in fused[:k]:
            if cid in by_id:
                out.append(by_id[cid])
        return out
