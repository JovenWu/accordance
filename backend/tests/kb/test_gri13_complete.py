from pathlib import Path

from accordance.kb.loader import load_kb

REPO_ROOT = Path(__file__).resolve().parents[3]
KB = load_kb(REPO_ROOT / "kb" / "gri")

GRI13_SECTOR_IDS = {
    "13.3.6", "13.3.7",
    "13.4.2", "13.4.3", "13.4.4", "13.4.5",
    "13.6.2",
    "13.9.2",
    "13.10.4", "13.10.5",
    "13.11.2", "13.11.3",
    "13.13.2", "13.13.3",
    "13.14.3", "13.14.4",
    "13.15.5",
    "13.21.2", "13.21.3",
    "13.23.2", "13.23.3", "13.23.4",
}


def test_all_gri13_sector_disclosures_present():
    missing = GRI13_SECTOR_IDS - set(KB)
    assert not missing, f"missing GRI 13 sector disclosures: {sorted(missing)}"


def test_all_gri13_files_category_sector():
    for did, d in KB.items():
        if d.standard.startswith("GRI 13"):
            assert d.category == "sector", f"{did} not category=sector"
