from pathlib import Path

import yaml

from accordance.kb.loader import load_kb
from accordance.kb.presets import load_presets

REPO_ROOT = Path(__file__).resolve().parents[3]
KB = load_kb(REPO_ROOT / "kb" / "gri")
PRESETS = load_presets(REPO_ROOT / "kb" / "presets", KB)


def test_mining_preset_loads():
    p = next(p for p in PRESETS if p.id == "gri-14-mining")
    assert p.standard == "GRI 14: Mining Sector 2024"


def test_mining_preset_ids_resolve_in_kb():
    p = next(p for p in PRESETS if p.id == "gri-14-mining")
    assert p.disclosure_ids, "preset is empty"
    assert all(did in KB for did in p.disclosure_ids)


def test_mining_preset_dedupes_and_excludes_upcoming():
    p = next(p for p in PRESETS if p.id == "gri-14-mining")
    assert len(p.disclosure_ids) == len(set(p.disclosure_ids))
    assert p.disclosure_ids.count("3-3") == 1
    assert all(KB[did].status != "upcoming" for did in p.disclosure_ids)


def test_mining_preset_includes_sector_and_current_biodiversity():
    p = next(p for p in PRESETS if p.id == "gri-14-mining")
    assert "14.6.2" in p.disclosure_ids
    assert "101-1" in p.disclosure_ids
    assert "304-1" not in p.disclosure_ids


def test_presets_exclude_non_current_editions():
    for p in PRESETS:
        for did in p.disclosure_ids:
            assert KB[did].status == "current", f"{p.id} includes non-current {did} ({KB[did].status})"


def test_preset_yaml_references_no_unknown_ids():
    """Regression test: catch dangling disclosure id references in preset YAMLs
    before the loader's skip logic silently shrinks a preset."""
    presets_dir = REPO_ROOT / "kb" / "presets"
    for f in sorted(presets_dir.glob("*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        for topic in data.get("topics", []):
            for did in topic.get("disclosures", []):
                assert did in KB, f"{f.name} topic {topic.get('id')} references unknown id {did}"
