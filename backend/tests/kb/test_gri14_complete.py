from pathlib import Path

from accordance.kb.loader import load_kb

REPO_ROOT = Path(__file__).resolve().parents[3]
KB = load_kb(REPO_ROOT / "kb" / "gri")

GRI14_SECTOR_IDS = {
    "14.0.1",
    "14.6.2", "14.6.3",
    "14.8.4", "14.8.5", "14.8.6", "14.8.7", "14.8.8", "14.8.9",
    "14.9.6", "14.10.4", "14.11.3", "14.11.4",
    "14.12.2", "14.12.3", "14.13.2", "14.13.3",
    "14.15.3", "14.15.4", "14.20.3",
    "14.22.5", "14.22.6", "14.23.8",
    "14.25.2", "14.25.3", "14.25.4",
}

def test_all_gri14_sector_disclosures_present():
    missing = GRI14_SECTOR_IDS - set(KB)
    assert not missing, f"missing GRI 14 sector disclosures: {sorted(missing)}"

def test_all_gri14_files_category_sector():
    for did, d in KB.items():
        if d.standard.startswith("GRI 14"):
            assert d.category == "sector", f"{did} not category=sector"
