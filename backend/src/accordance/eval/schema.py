"""Ground-truth schema for the evaluation harness.

A ground-truth file is one YAML per labeled report. The labeler need only
fill in disclosures they're confident about — the runner only compares
labeled disclosures, never penalizing the judge for unlabeled ones.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

# A labeler can write "found"/"partial"/"missing" for elements and
# "covered"/"partial"/"missing" for disclosures. We re-use the same enums
# the judge emits so the comparison is apples-to-apples.

LabeledElementStatus = Literal["found", "partial", "missing"]
LabeledDisclosureStatus = Literal["covered", "partial", "missing"]


class LabeledElement(BaseModel):
    id: str
    expected_status: LabeledElementStatus
    expected_page: int | None = None


class LabeledDisclosure(BaseModel):
    id: str
    expected_status: LabeledDisclosureStatus
    expected_score: int | None = None  # 0 = N/A, 1-5 = grade; None until relabeled
    expected_evidence_page: int | None = None
    notes: str | None = None
    elements: list[LabeledElement] = Field(default_factory=list)


class GroundTruth(BaseModel):
    report_id: str
    pdf_filename: str
    pdf_sha256: str | None = None
    pdf_path: str | None = None
    labeler: str | None = None
    labeled_at: date | None = None
    disclosures: list[LabeledDisclosure] = Field(min_length=1)

    @classmethod
    def from_yaml(cls, path: Path) -> GroundTruth:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls.model_validate(data)

    def disclosure_ids(self) -> set[str]:
        return {d.id for d in self.disclosures}

    def by_id(self) -> dict[str, LabeledDisclosure]:
        return {d.id: d for d in self.disclosures}


__all__ = [
    "GroundTruth",
    "LabeledDisclosure",
    "LabeledDisclosureStatus",
    "LabeledElement",
    "LabeledElementStatus",
]
