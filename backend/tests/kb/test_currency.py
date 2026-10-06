from pathlib import Path

from accordance.kb.loader import applicable_disclosures, load_kb
from accordance.kb.schema import Disclosure, RequiredElement

REPO_ROOT = Path(__file__).resolve().parents[3]
KB = load_kb(REPO_ROOT / "kb" / "gri")


def _d(did: str, *, status: str = "current", **extra) -> Disclosure:
    return Disclosure(
        id=did,
        standard="GRI X",
        title=did,
        category="topic",
        requirement_text="r",
        required_elements=[RequiredElement(id="x", desc="x")],
        retrieval_queries=["q"],
        suggested_fix_template="fix",
        status=status,
        **extra,
    )


def test_applicable_excludes_superseded_and_upcoming_keeps_current_real_kb():
    app = applicable_disclosures(KB)
    assert "304-1" not in app
    assert "304-4" not in app
    assert "102-1" not in app
    assert "103-1" not in app
    assert "101-1" in app
    assert "302-1" in app
    assert "305-6" in app
    assert "2-1" in app


def test_applicable_returns_exactly_the_current_subset():
    app = applicable_disclosures(KB)
    assert all(d.status == "current" for d in app.values())
    n_current = sum(1 for d in KB.values() if d.status == "current")
    assert len(app) == n_current
    assert len(app) < len(KB)


def test_applicable_preserves_kb_insertion_order():
    kb = {"a": _d("a"), "old": _d("old", status="superseded"), "b": _d("b")}
    assert list(applicable_disclosures(kb).keys()) == ["a", "b"]
