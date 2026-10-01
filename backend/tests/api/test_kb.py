


def test_kb_returns_grouped_standards(auth_client):
    r = auth_client.get("/api/kb")
    assert r.status_code == 200
    groups = r.json()
    standards = {g["standard"] for g in groups}
    assert any(s.startswith("GRI 2:") for s in standards)
    assert any(s.startswith("GRI 303:") for s in standards)
    total = sum(len(g["disclosures"]) for g in groups)
    assert total == 217
    first = groups[0]["disclosures"][0]
    assert {"id", "title", "category"} <= set(first.keys())


def test_kb_exposes_edition_metadata(auth_client):
    groups = auth_client.get("/api/kb").json()
    by_id = {d["id"]: d for g in groups for d in g["disclosures"]}
    assert by_id["304-1"]["status"] == "superseded"
    assert by_id["304-1"]["superseded_by"] == "GRI 101: Biodiversity 2024"
    assert by_id["102-1"]["status"] == "upcoming"
    assert by_id["305-1"]["status"] == "current"


def test_kb_presets_endpoint(auth_client):
    presets = auth_client.get("/api/kb/presets").json()
    mining = next(p for p in presets if p["id"] == "gri-14-mining")
    assert "14.6.2" in mining["disclosure_ids"]
    assert "101-1" in mining["disclosure_ids"]
