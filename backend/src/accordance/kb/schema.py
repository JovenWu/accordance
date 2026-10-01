from typing import Literal

from pydantic import BaseModel, Field


class RequiredElement(BaseModel):
    id: str
    desc: str


class Disclosure(BaseModel):
    id: str
    standard: str
    title: str
    category: Literal["universal", "topic", "management", "sector"]
    requirement_text: str
    required_elements: list[RequiredElement] = Field(min_length=1)
    retrieval_queries: list[str] = Field(min_length=1)
    good_evidence_hints: list[str] = Field(default_factory=list)
    suggested_fix_template: str
    # Edition currency metadata (optional; default = current/effective).
    status: Literal["current", "superseded", "upcoming"] = "current"
    effective_date: str | None = None       # ISO date it becomes mandatory
    effective_until: str | None = None       # last valid publication date
    superseded_by: str | None = None         # successor standard label
