from pathlib import Path

from fastapi import APIRouter

from accordance.kb.loader import load_kb
from accordance.kb.ordering import natural_key
from accordance.kb.presets import load_presets

router = APIRouter(prefix="/api/kb", tags=["kb"])

KB_DIR = Path(__file__).resolve().parents[4] / "kb" / "gri"
PRESETS_DIR = Path(__file__).resolve().parents[4] / "kb" / "presets"


@router.get("")
def get_kb():
    """Return disclosures grouped by standard for the selection UI."""
    kb = load_kb(KB_DIR)
    disclosures = sorted(kb.values(), key=lambda d: natural_key(d.id))

    groups: list[dict] = []
    index_by_standard: dict[str, int] = {}
    for d in disclosures:
        if d.standard not in index_by_standard:
            index_by_standard[d.standard] = len(groups)
            groups.append({"standard": d.standard, "disclosures": []})
        groups[index_by_standard[d.standard]]["disclosures"].append(
            {
                "id": d.id,
                "title": d.title,
                "category": d.category,
                "status": d.status,
                "effective_date": d.effective_date,
                "effective_until": d.effective_until,
                "superseded_by": d.superseded_by,
            }
        )
    return groups


@router.get("/presets")
def get_presets():
    kb = load_kb(KB_DIR)
    return [p.model_dump() for p in load_presets(PRESETS_DIR, kb)]
