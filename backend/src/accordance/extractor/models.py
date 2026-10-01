from pydantic import BaseModel


class EncryptedPDFError(ValueError):
    """Raised when a PDF is password-protected/encrypted and can't be read.

    A typed error so the upload path surfaces a clear, actionable message
    instead of a raw "document closed or encrypted" deep in the extractor.
    """


class ExtractionTimeoutError(TimeoutError):
    """Raised when a single extraction pass exceeds its wall-clock budget.

    Bounds how long a run waits on a pathological PDF (the Docling C++ pipeline
    can grind for many minutes on infographic-heavy pages). The container's
    mem_limit remains the backstop for the memory side.
    """


class ExtractedPage(BaseModel):
    page_number: int
    markdown: str
    tables: list[str] = []


class ExtractedReport(BaseModel):
    source_sha256: str
    pages: list[ExtractedPage]
