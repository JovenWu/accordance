from enum import StrEnum

from pydantic import BaseModel, Field


class ElementStatus(StrEnum):
    found = "found"
    partial = "partial"
    missing = "missing"


class DisclosureStatus(StrEnum):
    covered = "covered"
    partial = "partial"
    missing = "missing"
    error = "error"


class ElementJudgment(BaseModel):
    id: str
    status: ElementStatus
    page: int | None = None


class JudgeOutput(BaseModel):
    status: DisclosureStatus
    elements: list[ElementJudgment] = Field(default_factory=list)
    note: str
    evidence_excerpt: str | None = None
    evidence_page: int | None = None
    needs_vision_fallback: bool = False
    # Whether the disclosure applies to this report at all. False => candidate
    # for a 0 (Not Applicable) grade, subject to the rollup's guardrails.
    applicable: bool = True
    # Required when applicable is False: the stated/inferred reason it is out
    # of scope (org type/size, or a non-material sector topic).
    na_reason: str | None = None
