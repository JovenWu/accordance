from pathlib import Path

from accordance.kb.loader import load_kb

REPO_ROOT = Path(__file__).resolve().parents[3]


EXPECTED_IDS = (
    [f"2-{i}" for i in range(1, 31)]
    + ["3-1", "3-2", "3-3"]
    + [f"101-{i}" for i in range(1, 9)]
    + [f"102-{i}" for i in range(1, 11)]
    + [f"103-{i}" for i in range(1, 6)]
    + [f"201-{i}" for i in range(1, 5)]
    + ["202-1", "202-2"]
    + ["203-1", "203-2"]
    + ["204-1"]
    + ["205-1", "205-2", "205-3"]
    + ["206-1"]
    + [f"207-{i}" for i in range(1, 5)]
    + ["301-1", "301-2", "301-3"]
    + ["303-1", "303-2", "303-3", "303-4", "303-5"]
    + [f"306-{i}" for i in range(1, 6)]
    + ["308-1", "308-2"]
    + [f"401-{i}" for i in range(1, 4)]
    + ["402-1"]
    + [f"403-{i}" for i in range(1, 11)]
    + [f"404-{i}" for i in range(1, 4)]
    + ["405-1", "405-2"]
    + ["406-1"]
    + ["407-1"]
    + ["408-1"]
    + ["409-1"]
    + ["410-1"]
    + ["411-1"]
    + [f"412-{i}" for i in range(1, 4)]
    + ["413-1", "413-2"]
    + ["414-1", "414-2"]
    + ["415-1"]
    + ["416-1", "416-2"]
    + [f"417-{i}" for i in range(1, 4)]
    + ["418-1"]
)


def test_full_kb_present_and_valid():
    kb = load_kb(REPO_ROOT / "kb" / "gri")
    missing = [i for i in EXPECTED_IDS if i not in kb]
    assert not missing, f"Missing disclosure YAMLs: {missing}"
    for d in kb.values():
        assert len(d.retrieval_queries) >= 2, f"{d.id}: needs >=2 retrieval queries"
        assert len(d.required_elements) >= 1, f"{d.id}: needs >=1 required element"
