from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from accordance.eval.schema import GroundTruth


def _write(tmp_path: Path, data: dict) -> Path:
    f = tmp_path / "gt.yaml"
    f.write_text(yaml.safe_dump(data), encoding="utf-8")
    return f


def _minimal(**extra):
    return {
        "report_id": "demo",
        "pdf_filename": "demo.pdf",
        "disclosures": [
            {"id": "2-1", "expected_status": "covered"},
        ],
        **extra,
    }


def test_minimal_yaml_loads(tmp_path):
    f = _write(tmp_path, _minimal())
    gt = GroundTruth.from_yaml(f)
    assert gt.report_id == "demo"
    assert gt.disclosures[0].id == "2-1"
    assert gt.disclosures[0].expected_status == "covered"
    assert gt.disclosures[0].elements == []


def test_element_level_labels(tmp_path):
    data = _minimal(
        disclosures=[
            {
                "id": "2-1",
                "expected_status": "partial",
                "expected_evidence_page": 4,
                "elements": [
                    {"id": "legal_name", "expected_status": "found", "expected_page": 4},
                    {"id": "countries_of_operation", "expected_status": "missing"},
                ],
            }
        ]
    )
    f = _write(tmp_path, data)
    gt = GroundTruth.from_yaml(f)
    d = gt.disclosures[0]
    assert d.expected_evidence_page == 4
    assert len(d.elements) == 2
    assert d.elements[0].expected_page == 4
    assert d.elements[1].expected_page is None


def test_rejects_invalid_status(tmp_path):
    data = _minimal(disclosures=[{"id": "2-1", "expected_status": "DEFINITELY_NOT_A_STATUS"}])
    f = _write(tmp_path, data)
    with pytest.raises(ValidationError):
        GroundTruth.from_yaml(f)


def test_rejects_invalid_element_status(tmp_path):
    data = _minimal(
        disclosures=[
            {
                "id": "2-1",
                "expected_status": "covered",
                "elements": [{"id": "x", "expected_status": "covered"}],
            }
        ]
    )
    f = _write(tmp_path, data)
    with pytest.raises(ValidationError):
        GroundTruth.from_yaml(f)


def test_requires_at_least_one_disclosure(tmp_path):
    data = _minimal()
    data["disclosures"] = []
    f = _write(tmp_path, data)
    with pytest.raises(ValidationError):
        GroundTruth.from_yaml(f)


def test_by_id_helper():
    gt = GroundTruth.model_validate(
        _minimal(
            disclosures=[
                {"id": "2-1", "expected_status": "covered"},
                {"id": "3-1", "expected_status": "missing"},
            ]
        )
    )
    by_id = gt.by_id()
    assert set(by_id.keys()) == {"2-1", "3-1"}
    assert by_id["3-1"].expected_status == "missing"
