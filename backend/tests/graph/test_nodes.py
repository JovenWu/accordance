import logging

from accordance import db
from accordance.graph.nodes import judge_one_node
from accordance.indexer.chunker import Chunk
from accordance.indexer.embedder import FakeEmbedder
from accordance.indexer.vector_store import VectorStore
from accordance.judge.output_schema import (
    DisclosureStatus,
    ElementJudgment,
    ElementStatus,
    JudgeOutput,
)
from accordance.kb.schema import Disclosure, RequiredElement
from accordance.llm.adapter import FakeJudgeLLM


def _seed_run(conn, run_id="r1", report_id="rep-1"):
    conn.execute("INSERT INTO reports (id, name) VALUES (%s, %s)", (report_id, "x.pdf"))
    conn.execute(
        "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, "
        "pdf_sha256, pdf_path, status) VALUES (%s, %s, 1, 'initial', 'x.pdf', 'sha', 'x', 'judging')",
        (run_id, report_id),
    )


_DISCLOSURE = Disclosure(
    id="303-3",
    standard="GRI 303",
    title="Water withdrawal",
    category="topic",
    requirement_text="Total water withdrawal",
    required_elements=[RequiredElement(id="total", desc="total")],
    retrieval_queries=["water"],
    suggested_fix_template="Add a breakdown.",
)


def test_judge_one_node_writes_finding():
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO reports (id, name) VALUES (%s, %s)",
            ("rep-nodes-1", "x.pdf"),
        )
        conn.execute(
            "INSERT INTO runs (id, report_id, version_number, kind, pdf_filename, pdf_sha256, pdf_path, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            ("r1", "rep-nodes-1", 1, "initial", "x.pdf", "sha", "x", "judging"),
        )
        embedder = FakeEmbedder(dim=8)
        store = VectorStore(conn, embedder)
        store.write("r1", [Chunk(page=1, text="water 41 ML")])

        d = Disclosure(
            id="303-3",
            standard="GRI 303",
            title="Water withdrawal",
            category="topic",
            requirement_text="Total water withdrawal",
            required_elements=[RequiredElement(id="total", desc="total")],
            retrieval_queries=["water"],
            suggested_fix_template="Add a breakdown.",
        )

        state = {"run_id": "r1"}
        out = judge_one_node(
            state=state,
            disclosure=d,
            store=store,
            llm=FakeJudgeLLM(),
            conn=conn,
        )
        assert "findings" in out
        assert len(out["findings"]) == 1
        assert out["findings"][0]["disclosure_id"] == "303-3"
        row = conn.execute(
            "SELECT disclosure_id, status, prompt_hash FROM findings WHERE run_id=%s",
            ("r1",),
        ).fetchone()
        assert row["disclosure_id"] == "303-3"
        # prompt_hash must be stamped — eval depends on this for diff attribution
        assert row["prompt_hash"]
        assert len(row["prompt_hash"]) == 16

        # At least one trace row must exist (FakeJudgeLLM returns 'partial', so
        # rejudge is not triggered — exactly one trace).
        traces = conn.execute(
            "SELECT attempt, rejudged, parse_path, prompt_hash, model, "
            "chunk_ids_json, distances_json FROM judge_traces WHERE run_id=%s",
            ("r1",),
        ).fetchall()
        assert len(traces) == 1
        t = traces[0]
        assert t["attempt"] == 1
        assert t["rejudged"] is False or t["rejudged"] == 0
        assert t["parse_path"] in ("structured", "fallback")
        assert t["prompt_hash"] == row["prompt_hash"]
        assert t["model"]
        # chunk_ids_json is a JSON array containing the retrieved chunk id(s)
        assert t["chunk_ids_json"].startswith("[")


def test_vision_fallback_fires_on_partial_verdict(monkeypatch):
    """The text judge (FakeJudgeLLM) returns 'partial' with
    needs_vision_fallback=false. With vision_fallback_on_low_confidence on
    (default), the node must still escalate to vision — this is the fix for
    the 0/38 never-fired bug, where data locked in table-images was never
    re-read because the LLM never self-flagged."""
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    with db.connection() as conn:
        _seed_run(conn)
        store = VectorStore(conn, FakeEmbedder(dim=8))
        store.write("r1", [Chunk(page=1, text="water 41 ML")])

        calls: list[tuple[str, list[int]]] = []

        def fake_vision(disclosure, pdf_path, pages, llm):
            calls.append((disclosure.id, pages))
            return JudgeOutput(
                status=DisclosureStatus.covered,
                elements=[ElementJudgment(id="total", status=ElementStatus.found, page=1)],
                note="vision read the table",
                evidence_excerpt="Surface water 41 ML",
                evidence_page=1,
                needs_vision_fallback=False,
            )

        # The node imports judge_with_vision from this module at call time.
        monkeypatch.setattr("accordance.judge.vision_fallback.judge_with_vision", fake_vision)

        out = judge_one_node(
            state={"run_id": "r1"},
            disclosure=_DISCLOSURE,
            store=store,
            llm=FakeJudgeLLM(),
            conn=conn,
        )
        assert out["findings"], "expected a finding"
        # Vision must have been attempted despite needs_vision_fallback=false.
        assert calls == [("303-3", [1])]
        row = conn.execute(
            "SELECT status, vision_fallback_used FROM findings WHERE run_id='r1'"
        ).fetchone()
        assert row["vision_fallback_used"] is True or row["vision_fallback_used"] == 1
        # Vision verdict ('covered') overrode the text verdict ('partial').
        assert row["status"] == "covered"


def test_vision_fallback_can_be_disabled(monkeypatch):
    """With VISION_FALLBACK_ENABLED=false, the partial text verdict stands
    and vision is never invoked."""
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("VISION_FALLBACK_ENABLED", "false")
    with db.connection() as conn:
        _seed_run(conn)
        store = VectorStore(conn, FakeEmbedder(dim=8))
        store.write("r1", [Chunk(page=1, text="water 41 ML")])

        calls: list = []

        def fake_vision(disclosure, pdf_path, pages, llm):
            calls.append(disclosure.id)
            raise AssertionError("vision should not be called when disabled")

        monkeypatch.setattr("accordance.judge.vision_fallback.judge_with_vision", fake_vision)

        judge_one_node(
            state={"run_id": "r1"},
            disclosure=_DISCLOSURE,
            store=store,
            llm=FakeJudgeLLM(),
            conn=conn,
        )
        assert calls == []
        row = conn.execute(
            "SELECT status, vision_fallback_used FROM findings WHERE run_id='r1'"
        ).fetchone()
        assert row["vision_fallback_used"] is False or row["vision_fallback_used"] == 0
        assert row["status"] == "partial"


from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage


class _FakeNALLM(BaseChatModel):
    """Returns applicable=false so the node should persist score 0."""

    @property
    def _llm_type(self) -> str:
        return "fake-na"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.outputs import ChatGeneration, ChatResult

        canned = (
            '{"status":"missing","elements":[{"id":"total","status":"missing","page":null}],'
            '"note":"out of scope","evidence_excerpt":null,"evidence_page":null,'
            '"needs_vision_fallback":false,"applicable":false,'
            '"na_reason":"No water withdrawal operations in scope."}'
        )
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=canned))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def test_judge_one_node_persists_score(monkeypatch):
    # FakeJudgeLLM returns one element "found" -> f=1.0 -> score 5.
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("VISION_FALLBACK_ENABLED", "false")
    with db.connection() as conn:
        _seed_run(conn)
        store = VectorStore(conn, FakeEmbedder(dim=8))
        store.write("r1", [Chunk(page=1, text="water 41 ML")])

        judge_one_node(
            state={"run_id": "r1"},
            disclosure=_DISCLOSURE,
            store=store,
            llm=FakeJudgeLLM(),
            conn=conn,
        )
        row = conn.execute(
            "SELECT status, score, na_reason FROM findings WHERE run_id='r1'"
        ).fetchone()
        assert row["score"] == 5  # element found -> 5
        assert row["status"] == "partial"  # legacy status UNCHANGED (LLM verdict)
        assert row["na_reason"] is None


def test_judge_one_node_persists_na_score_0(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("VISION_FALLBACK_ENABLED", "false")
    with db.connection() as conn:
        _seed_run(conn)
        store = VectorStore(conn, FakeEmbedder(dim=8))
        store.write("r1", [Chunk(page=1, text="irrelevant")])

        # 303-3 is NOT in NO_OMISSION_DISCLOSURES, so applicable=false -> score 0.
        judge_one_node(
            state={"run_id": "r1"},
            disclosure=_DISCLOSURE,
            store=store,
            llm=_FakeNALLM(),
            conn=conn,
        )
        row = conn.execute("SELECT score, na_reason FROM findings WHERE run_id='r1'").fetchone()
        assert row["score"] == 0
        assert "scope" in row["na_reason"]


def test_na_verdict_does_not_trigger_vision(monkeypatch):
    """An applicable=false (N/A) verdict must NOT escalate to vision, even with
    vision enabled, and must persist score 0 with its na_reason intact."""
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("VISION_FALLBACK_ENABLED", "true")
    with db.connection() as conn:
        _seed_run(conn)
        store = VectorStore(conn, FakeEmbedder(dim=8))
        store.write("r1", [Chunk(page=1, text="irrelevant")])

        calls: list = []

        def fake_vision(disclosure, pdf_path, pages, llm):
            calls.append(disclosure.id)
            raise AssertionError("vision must not be called for an N/A disclosure")

        monkeypatch.setattr("accordance.judge.vision_fallback.judge_with_vision", fake_vision)

        judge_one_node(
            state={"run_id": "r1"},
            disclosure=_DISCLOSURE,
            store=store,
            llm=_FakeNALLM(),
            conn=conn,
        )
        assert calls == []  # vision never invoked
        row = conn.execute(
            "SELECT score, na_reason, vision_fallback_used FROM findings WHERE run_id='r1'"
        ).fetchone()
        assert row["score"] == 0
        assert "scope" in row["na_reason"]
        assert row["vision_fallback_used"] is False or row["vision_fallback_used"] == 0


class _AlwaysRaiseLLM(BaseChatModel):
    """LLM that always raises so we can trigger the error path in judge_one_node."""

    @property
    def _llm_type(self) -> str:
        return "always-raise"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("simulated LLM failure")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("simulated LLM failure")


def test_judge_error_path_emits_warning(monkeypatch, caplog):
    """When the judge LLM raises, judge_one_node must:
    1. Persist an error finding (status='error').
    2. Emit a WARNING-level log via the accordance.graph.nodes logger.
    """
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    monkeypatch.setenv("VISION_FALLBACK_ENABLED", "false")
    with db.connection() as conn:
        _seed_run(conn)
        store = VectorStore(conn, FakeEmbedder(dim=8))
        store.write("r1", [Chunk(page=1, text="irrelevant")])

        # caplog installs its handler on the root logger, but accordance sets
        # propagate=False (to avoid double-emit under uvicorn). Attach caplog's
        # handler directly to accordance so records are captured in tests.
        accordance_logger = logging.getLogger("accordance")
        accordance_logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.WARNING, logger="accordance.graph.nodes"):
                judge_one_node(
                    state={"run_id": "r1"},
                    disclosure=_DISCLOSURE,
                    store=store,
                    llm=_AlwaysRaiseLLM(),
                    conn=conn,
                )
        finally:
            accordance_logger.removeHandler(caplog.handler)

        # Error finding must be persisted
        row = conn.execute("SELECT status, note FROM findings WHERE run_id='r1'").fetchone()
        assert row["status"] == "error"
        assert "Judge failed" in row["note"]

        # Warning must be logged
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_records, "expected at least one warning-level log from judge failure"
        combined = " ".join(r.getMessage() for r in warning_records)
        assert "303-3" in combined or "r1" in combined


def test_vision_uses_text_pass_pages_not_fresh_retrieve(monkeypatch):
    """The vision branch must NOT issue a fresh store.retrieve() call —
    it must reuse the pages already retrieved by the text pass (recorded in
    JudgeTrace.pages). This avoids a redundant embedding round per
    vision-eligible disclosure.

    We verify this by:
    1. Tracking every store.retrieve() call.
    2. Running judge_one_node with vision enabled and a partial text verdict.
    3. Asserting that retrieve() was NOT called during the vision branch
       (no calls after the text-pass judge completes).
    4. Asserting that the pages passed to judge_with_vision originate
       from the text-pass traces (i.e. page 1, the only page in the store).
    """
    monkeypatch.setenv("EMBEDDING_MODEL", "fake:fake")
    with db.connection() as conn:
        _seed_run(conn)
        store = VectorStore(conn, FakeEmbedder(dim=8))
        store.write("r1", [Chunk(page=3, text="water 41 ML")])

        retrieve_calls: list[tuple] = []
        original_retrieve = store.retrieve

        def spy_retrieve(run_id, q, k):
            retrieve_calls.append((run_id, q, k))
            return original_retrieve(run_id, q, k)

        store.retrieve = spy_retrieve  # type: ignore[method-assign]

        vision_call_pages: list[list[int]] = []

        def fake_vision(disclosure, pdf_path, pages, llm):
            vision_call_pages.append(list(pages))
            return JudgeOutput(
                status=DisclosureStatus.covered,
                elements=[ElementJudgment(id="total", status=ElementStatus.found, page=3)],
                note="vision read the table",
                evidence_excerpt="Surface water 41 ML",
                evidence_page=3,
                needs_vision_fallback=False,
            )

        monkeypatch.setattr("accordance.judge.vision_fallback.judge_with_vision", fake_vision)

        # Count how many retrieve calls happened during the text pass.
        retrieve_calls.clear()
        judge_one_node(
            state={"run_id": "r1"},
            disclosure=_DISCLOSURE,
            store=store,
            llm=FakeJudgeLLM(),
            conn=conn,
        )

        # Vision must have fired (partial verdict → low-confidence escalation).
        assert vision_call_pages, "vision was never called"

        # ALL retrieve calls must have happened during the text-pass judge, NOT
        # after it in the vision branch. We count text-pass calls by looking at
        # the number of queries the text judge issued; any EXTRA call would mean
        # re-retrieval.  The text pass for _DISCLOSURE uses 1 retrieval_query
        # ("water") + 1 element desc ("total") = 2 retrieve calls per pass
        # (at most one rejudge adds another 1-2).  We allow up to 6 as a liberal
        # upper bound for the text pass. A vision re-retrieval would add calls
        # proportional to len(retrieval_queries) again — easy to detect.
        # Simpler invariant: page 3 must appear in the pages passed to vision
        # (proving pages came from trace.pages, not from a fresh retrieve that
        # would return whatever the store returns).
        assert 3 in vision_call_pages[0], (
            f"Vision was not given page 3 from the text-pass traces; got {vision_call_pages[0]}. "
            "This means vision pages were NOT sourced from the text-pass traces."
        )

        # No retrieve calls should happen AFTER judge_disclosure_with_rejudge returns
        # (i.e. during the vision branch). We detect this by checking that
        # retrieve was not called with any of the disclosure's retrieval_queries
        # a second time after the text judge completed.
        # Count retrieve calls that used the disclosure's query strings.
        query_call_counts: dict[str, int] = {}
        for _, q, _ in retrieve_calls:
            query_call_counts[q] = query_call_counts.get(q, 0) + 1

        # With rejudge disabled (FakeJudgeLLM returns partial, not missing),
        # "water" should appear at most once (the text pass). A second appearance
        # would indicate re-retrieval in the vision branch.
        water_calls = query_call_counts.get("water", 0)
        assert water_calls <= 1, (
            f"retrieve('water') was called {water_calls} times — "
            "the vision branch appears to be issuing a redundant re-retrieval."
        )


# ── failure attribution ──────────────────────────────────────────────
# Retrieval (query embedding + vector search) and the judge LLM are two
# different network dependencies, but both used to surface as
# "Judge failed: ...". When the embedding account ran out of credits, every
# disclosure reported a judge failure while the judge was never called —
# sending debugging at the wrong subsystem entirely.


class _ExplodingRetrieveStore:
    """Store whose retrieval raises — stands in for a dead embedding endpoint."""

    def __init__(self, conn):
        self.conn = conn

    def retrieve(self, run_id, query, k=5):
        raise RuntimeError("Error code: 429 - You have no credits remaining.")

    def retrieve_by_tag(self, run_id, disclosure_id, limit):
        return []

    def retrieve_page_siblings(self, *a, **kw):
        return []


class _ExplodingLLM(FakeJudgeLLM):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("upstream judge model unavailable")


def _finding(conn, run_id):
    return conn.execute(
        "SELECT status, note FROM findings WHERE run_id=%s", (run_id,)
    ).fetchone()


def test_retrieval_failure_is_not_reported_as_a_judge_failure():
    # Patch the module logger rather than using caplog: once create_app()
    # configures logging, accordance loggers stop propagating to the root
    # handler, so caplog silently sees nothing depending on test order.
    from unittest.mock import patch

    with db.connection() as conn:
        _seed_run(conn, run_id="r-retr", report_id="rep-retr")
        with patch("accordance.graph.nodes.logger") as log:
            judge_one_node(
                {"run_id": "r-retr"},
                _DISCLOSURE,
                _ExplodingRetrieveStore(conn),
                FakeJudgeLLM(),
                conn,
            )
        row = _finding(conn, "r-retr")
        assert row["status"] == "error"
        assert "retrieval" in row["note"].lower()
        assert "judge failed" not in row["note"].lower()
        assert "retrieval" in str(log.warning.call_args).lower()


def test_judge_llm_failure_is_still_reported_as_a_judge_failure():
    with db.connection() as conn:
        _seed_run(conn, run_id="r-judge", report_id="rep-judge")
        store = VectorStore(conn, FakeEmbedder(dim=8))
        store.write("r-judge", [Chunk(page=1, text="water 41 ML")])
        judge_one_node({"run_id": "r-judge"}, _DISCLOSURE, store, _ExplodingLLM(), conn)
        row = _finding(conn, "r-judge")
        assert row["status"] == "error"
        assert "judge failed" in row["note"].lower()
        assert "retrieval" not in row["note"].lower()


def test_vision_fallback_failure_is_logged_not_swallowed(monkeypatch):
    """A silent `except Exception: pass` hid every vision failure.

    Vision is ~17% of spend and its value is already unclear; failing
    invisibly means it could be dead for an entire run with no signal.
    """
    from unittest.mock import patch

    import accordance.judge.vision_fallback as vf

    def boom(*a, **kw):
        raise RuntimeError("page render exploded")

    monkeypatch.setattr(vf, "judge_with_vision", boom)
    with db.connection() as conn:
        _seed_run(conn, run_id="r-vis", report_id="rep-vis")
        store = VectorStore(conn, FakeEmbedder(dim=8))
        store.write("r-vis", [Chunk(page=1, text="water 41 ML")])
        with patch("accordance.graph.nodes.logger") as log:
            judge_one_node({"run_id": "r-vis"}, _DISCLOSURE, store, FakeJudgeLLM(), conn)
        logged = " ".join(str(c) for c in log.warning.call_args_list).lower()
        assert "vision" in logged
        # The text verdict must survive — vision is an optional upgrade.
        assert _finding(conn, "r-vis")["status"] != "error"


def test_judge_one_node_honours_the_structured_method_setting(monkeypatch):
    """JUDGE_STRUCTURED_METHOD must actually reach judge_disclosure.

    The setting was defined and threaded through judge/core.py but never passed
    from judge_one_node, so the documented escape hatch for a proxy that rejects
    json_schema silently did nothing.
    """
    from accordance.config import get_settings
    from accordance.graph import nodes as nodes_mod

    seen: list[str] = []

    def _spy(*args, **kwargs):
        seen.append(kwargs.get("structured_method"))
        return None, []

    monkeypatch.setattr(nodes_mod, "judge_disclosure_with_rejudge", _spy)
    settings = get_settings()
    monkeypatch.setattr(settings, "judge_structured_method", "function_calling")

    with db.connection() as conn:
        _seed_run(conn, run_id="r-sm", report_id="rep-sm")
        store = VectorStore(conn, FakeEmbedder(dim=8))
        store.write("r-sm", [Chunk(page=1, text="water 41 ML")])
        judge_one_node(
            state={"run_id": "r-sm"},
            disclosure=_DISCLOSURE,
            store=store,
            llm=FakeJudgeLLM(),
            conn=conn,
        )

    assert seen == ["function_calling"]
