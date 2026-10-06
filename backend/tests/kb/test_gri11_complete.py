from pathlib import Path

from accordance.kb.loader import load_kb

REPO_ROOT = Path(__file__).resolve().parents[3]
KB = load_kb(REPO_ROOT / "kb" / "gri")

GRI11_SECTOR_IDS = {
    "11.2.4",
    "11.7.4", "11.7.5", "11.7.6",
    "11.8.3", "11.8.4",
    "11.15.4", "11.16.2",
    "11.17.3", "11.17.4",
    "11.20.5", "11.20.6",
    "11.21.8",
}


def test_all_gri11_sector_disclosures_present():
    missing = GRI11_SECTOR_IDS - set(KB)
    assert not missing, f"missing GRI 11 sector disclosures: {sorted(missing)}"


def test_all_gri11_files_category_sector():
    for did, d in KB.items():
        if d.standard.startswith("GRI 11"):
            assert d.category == "sector", f"{did} not category=sector"
