from accordance.api.versioning import _copy_chunks_to_new_run
from accordance.db import connection
from accordance.indexer.chunker import Chunk
from accordance.indexer.embedder import FakeEmbedder
from accordance.indexer.vector_store import VectorStore


def _seed(conn, run_id, report_id):
    conn.execute("INSERT INTO reports (id, name) VALUES (%s, %s)", (report_id, "x.pdf"))
    conn.execute(
        "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
        "pdf_sha256, pdf_path, status) "
        "VALUES (%s, %s, 1, 'initial', 'x.pdf', 'sha', 'x', 'completed')",
        (run_id, report_id),
    )


def test_copied_vectors_are_retrievable_under_target_run():
    """Fork/retry copies chunks+vectors to a new run. With the run_id partition
    key on chunks.embedding, the copy MUST stamp the TARGET run_id, or the new
    run's dense retrieval is starved — copied vectors land in a different run's
    partition and never match ``run_id = target``."""
    with connection() as conn:
        _seed(conn, "src", "rep-1")
        _seed(conn, "tgt", "rep-2")

        store = VectorStore(conn, FakeEmbedder(dim=8))
        store.write("src", [
            Chunk(page=1, text="water withdrawal 41 megaliters"),
            Chunk(page=2, text="emissions scope one two three"),
        ])

        _copy_chunks_to_new_run(conn, source_run_id="src", target_run_id="tgt")

        hits = store.retrieve_dense("tgt", "water withdrawal", k=5)
        assert hits, "copied vectors are invisible to the target run's dense retrieval"
        assert all(
            "water" in h["text"] or "emissions" in h["text"] for h in hits
        )
