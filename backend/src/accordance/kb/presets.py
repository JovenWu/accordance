from pathlib import Path

import yaml
from pydantic import BaseModel

from accordance.kb.loader import applicable_disclosures
from accordance.kb.schema import Disclosure


class Preset(BaseModel):
    id: str
    name: str
    standard: str
    disclosure_ids: list[str]


def load_presets(presets_dir: Path, kb: dict[str, Disclosure]) -> list[Preset]:
    """Load preset YAMLs; flatten topic disclosure lists into a deduped,
    order-preserved id list, keeping only ids present in `kb` with status 'current'."""
    if not presets_dir.is_dir():
        return []
    applicable = applicable_disclosures(kb)
    out: list[Preset] = []
    for f in sorted(presets_dir.glob("*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        seen: dict[str, None] = {}
        for topic in data.get("topics", []):
            for did in topic.get("disclosures", []):
                if did in applicable and did not in seen:
                    seen[did] = None
        out.append(
            Preset(
                id=data["id"],
                name=data["name"],
                standard=data["standard"],
                disclosure_ids=list(seen.keys()),
            )
        )
    return out
