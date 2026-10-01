from pathlib import Path

import pytest

from accordance.kb.loader import load_kb

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_load_kb_finds_303_3():
    kb = load_kb(REPO_ROOT / "kb" / "gri")
    assert "303-3" in kb
    d = kb["303-3"]
    assert d.title == "Water withdrawal"
    assert len(d.required_elements) == 8


def test_load_kb_missing_directory_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_kb(tmp_path / "nonexistent")


def test_load_kb_skips_non_yaml(tmp_path):
    (tmp_path / "303-3.yaml").write_text(
        """
id: "303-3"
standard: "GRI 303"
title: "x"
category: topic
requirement_text: "x"
required_elements: [{id: a, desc: x}]
retrieval_queries: [q]
suggested_fix_template: "x"
""".strip()
    )
    (tmp_path / "README.md").write_text("# notes")
    kb = load_kb(tmp_path)
    assert list(kb.keys()) == ["303-3"]
