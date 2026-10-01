from operator import add
from typing import Annotated, TypedDict

from accordance.extractor.models import ExtractedReport
from accordance.judge.output_schema import JudgeOutput


class FindingEntry(TypedDict):
    disclosure_id: str
    judgment: JudgeOutput
    suggested_fix: str


class GraphState(TypedDict, total=False):
    run_id: str
    pdf_path: str
    extraction: ExtractedReport
    indexed: bool
    findings: Annotated[list[FindingEntry], add]
    completed: bool
