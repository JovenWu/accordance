from pathlib import Path

from accordance.kb.loader import load_kb

REPO_ROOT = Path(__file__).resolve().parents[3]
KB = load_kb(REPO_ROOT / "kb" / "gri")

GRI12_SECTOR_IDS = {
    "12.2.4",
    "12.3.4", "12.3.5", "12.3.6",
    "12.9.4",
    "12.10.2",
    "12.11.3", "12.11.4",
    "12.13.3", "12.13.4",
    "12.20.5", "12.20.6",
    "12.21.8",
}

def test_all_gri12_sector_disclosures_present():
    missing = GRI12_SECTOR_IDS - set(KB)
    assert not missing, f"missing GRI 12 sector disclosures: {sorted(missing)}"

def test_all_gri12_files_category_sector():
    for did, d in KB.items():
        if d.standard.startswith("GRI 12"):
            assert d.category == "sector", f"{did} not category=sector"
