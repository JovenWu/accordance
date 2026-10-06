import datetime
from pathlib import Path

from accordance.kb.loader import load_kb

REPO_ROOT = Path(__file__).resolve().parents[3]
KB = load_kb(REPO_ROOT / "kb" / "gri")


def test_edition_status_consistent_with_calendar_today():
    """Time-bomb guard for the static edition gating.

    `applicable_disclosures` gates purely on the hand-curated `status`, but GRI
    editions flip on fixed calendar dates (302/305 retire 2026-12-31; 102/103
    become mandatory 2027-01-01). This test goes RED the moment a threshold
    passes — forcing a human to update kb/gri/*.yaml — instead of the default
    judge silently grading against a retired edition (or skipping a now-mandatory
    one) in production. ISO YYYY-MM-DD strings compare correctly lexicographically.
    """
    today = datetime.date.today().isoformat()
    stale: list[str] = []
    for did, d in KB.items():
        if d.status == "upcoming" and d.effective_date and d.effective_date <= today:
            stale.append(
                f"{did}: status='upcoming' but effective_date {d.effective_date} "
                f"has arrived → set status='current'"
            )
        if d.status == "current" and d.effective_until and d.effective_until < today:
            stale.append(
                f"{did}: status='current' but effective_until {d.effective_until} "
                f"has passed → set status='superseded'"
            )
    assert not stale, (
        f"KB edition gating is stale as of {today}. Update kb/gri/*.yaml:\n  - "
        + "\n  - ".join(stale)
    )

def test_304_superseded_by_101():
    for i in range(1, 5):
        d = KB[f"304-{i}"]
        assert d.status == "superseded"
        assert d.effective_until == "2025-12-31"
        assert d.superseded_by == "GRI 101: Biodiversity 2024"

def test_102_103_upcoming_2027():
    for did in ["102-1", "102-10", "103-1", "103-5"]:
        assert KB[did].status == "upcoming"
        assert KB[did].effective_date == "2027-01-01"

def test_302_current_with_successor():
    assert KB["302-1"].status == "current"
    assert KB["302-1"].effective_until == "2026-12-31"
    assert KB["302-1"].superseded_by == "GRI 103: Energy 2025"

def test_305_partial_supersession():
    assert KB["305-1"].superseded_by == "GRI 102: Climate Change 2025"
    assert KB["305-6"].superseded_by is None
    assert KB["305-7"].superseded_by is None
    assert KB["305-6"].status == "current"

def test_101_current_effective_2026():
    assert KB["101-1"].status == "current"
    assert KB["101-1"].effective_date == "2026-01-01"
