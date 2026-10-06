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
    applicable: bool = True
    na_reason: str | None = None
