from pathlib import Path

import yaml

from accordance.kb.schema import Disclosure


def load_kb(kb_dir: Path) -> dict[str, Disclosure]:
    """Load all disclosure YAMLs in kb_dir into a {id: Disclosure} dict.

    Raises FileNotFoundError if kb_dir doesn't exist. Non-yaml files are skipped.
    """
    if not kb_dir.is_dir():
        raise FileNotFoundError(f"KB directory not found: {kb_dir}")

    out: dict[str, Disclosure] = {}
    for yaml_file in sorted(kb_dir.glob("*.yaml")):
        data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        disclosure = Disclosure(**data)
        if disclosure.id in out:
            raise ValueError(f"Duplicate disclosure id: {disclosure.id}")
        out[disclosure.id] = disclosure
    return out


def applicable_disclosures(kb: dict[str, Disclosure]) -> dict[str, Disclosure]:
    """The in-force subset of ``kb``: disclosures whose edition is currently
    effective (``status == "current"``), preserving insertion order.

    Excludes ``superseded`` editions (withdrawn — e.g. GRI 304 Biodiversity
    2016) and ``upcoming`` editions not yet mandatory (e.g. GRI 102/103
    Climate/Energy 2025). Without this gate the default judge path grades a
    report against BOTH the retired and the replacement edition of the same
    standard, double-counting it. ``status`` is the curated source of truth
    (the ``effective_*`` dates are descriptive); this mirrors the same filter
    ``kb.presets.load_presets`` applies to preset selections.
    """
    return {did: d for did, d in kb.items() if d.status == "current"}
