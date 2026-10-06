import gc
import hashlib
import logging
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import fitz
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    AcceleratorOptions,
    PdfPipelineOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption

from accordance.config import Settings, get_settings
from accordance.extractor.models import (
    EncryptedPDFError,
    ExtractedPage,
    ExtractedReport,
    ExtractionTimeoutError,
)

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


def _run_with_timeout(fn: Callable[[], _T], timeout: float) -> _T:
    """Run ``fn`` on a daemon thread, raising ExtractionTimeoutError if it
    exceeds ``timeout`` seconds. ``timeout <= 0`` runs ``fn`` inline (disabled).

    The conversion is blocking native code that can't be interrupted, so on
    timeout the worker thread is abandoned (daemon → won't block process exit);
    the run fails fast with a clear error instead of hanging, and the container
    mem_limit bounds the memory the abandoned pass can still consume.
    """
    if not timeout or timeout <= 0:
        return fn()

    box: dict[str, object] = {}
    done = threading.Event()

    def runner() -> None:
        try:
            box["value"] = fn()
        except BaseException as e:
            box["error"] = e
        finally:
            done.set()

    threading.Thread(target=runner, daemon=True).start()
    if not done.wait(timeout):
        raise ExtractionTimeoutError(
            f"Docling extraction exceeded its {timeout:.0f}s budget. The PDF may "
            f"be unusually large or image-heavy; try EXTRACTOR_BACKEND=pymupdf."
        )
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]  # type: ignore[return-value]


def _build_converter(settings: Settings) -> DocumentConverter:
    """Build a Docling converter with memory-conservative defaults.

    Why we lean on the cheap side:
    - `do_ocr=False`: RapidOCR allocates large tensors per page; for
      sustainability reports the text is already embedded so OCR is
      redundant work. Re-enable via DOCLING_DO_OCR=true for scans.
    - `do_table_structure=False`: TableFormer adds another model pass.
      Table text is still extracted; only cell layout is lost.
    - `num_threads=1` + `*_batch_size=1`: defaults are 4 — peak memory
      scales linearly with each. Single-threading eliminates the spike
      pattern that produced `std::bad_alloc` on infographic-heavy pages.
    """
    opts = PdfPipelineOptions(
        do_ocr=settings.docling_do_ocr,
        do_table_structure=settings.docling_do_table_structure,
        images_scale=settings.docling_images_scale,
        layout_batch_size=settings.docling_layout_batch_size,
        ocr_batch_size=settings.docling_ocr_batch_size,
        table_batch_size=settings.docling_table_batch_size,
        accelerator_options=AcceleratorOptions(
            num_threads=settings.docling_num_threads,
            device="auto",
        ),
    )
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _markdown_to_pages(full_md: str, page_count: int, page_offset: int) -> list[ExtractedPage]:
    """Split a Docling-emitted full-document markdown into per-page entries.

    Docling sometimes inserts form-feed (\\f) between pages — if present we
    split on it. Otherwise we put the whole blob on the first page of this
    batch and leave the rest empty (the same fallback as before batching).
    `page_offset` rebases page numbers to global coordinates so batch-2's
    first page is global page (batch_size + 1), not page 1.
    """
    if page_count <= 0:
        return []
    if "\f" in full_md:
        parts = full_md.split("\f")
    else:
        parts = [full_md] + [""] * (page_count - 1)
    out: list[ExtractedPage] = []
    for i in range(page_count):
        md = parts[i].strip() if i < len(parts) else ""
        out.append(ExtractedPage(page_number=page_offset + i + 1, markdown=md, tables=[]))
    return out


def _convert_one(
    pdf_path: Path,
    page_offset: int,
    page_count: int,
    settings: Settings,
) -> list[ExtractedPage]:
    """Run a single Docling pass on a (possibly sub-set) PDF.

    Always destroys the converter at the end and runs gc.collect so the
    next batch starts with a clean C++ heap.
    """
    converter = _build_converter(settings)
    try:
        result = _run_with_timeout(
            lambda c=converter: c.convert(str(pdf_path)),
            settings.docling_timeout_seconds,
        )
        doc = result.document
        try:
            full_md = doc.export_to_markdown()
        except Exception:
            logger.exception("export_to_markdown failed for %s", pdf_path)
            full_md = ""
        return _markdown_to_pages(full_md, page_count, page_offset)
    finally:
        try:
            del result, doc, converter  # type: ignore[possibly-unbound]
        except Exception:
            pass
        gc.collect()


def extract_pdf(pdf_path: Path) -> ExtractedReport:
    """Extract a PDF into per-page Markdown using Docling.

    For long PDFs (>= batch_size pages) we split the source into N-page
    chunks via PyMuPDF, run Docling on each chunk in a fresh converter,
    and rebase page numbers to global coordinates. This bounds peak memory
    per batch and prevents the C++ heap fragmentation that surfaces as
    `std::bad_alloc` deep into long documents (typically pages 200+).

    For short PDFs (< batch_size pages) we still run a single pass — no
    overhead from splitting.
    """
    settings = get_settings()
    batch_size = settings.docling_batch_size

    with fitz.open(str(pdf_path)) as src:
        if src.needs_pass:
            raise EncryptedPDFError(
                "This PDF is password-protected/encrypted and can't be read. "
                "Remove the password and re-upload."
            )
        total_pages = src.page_count

    if total_pages == 0:
        return ExtractedReport(source_sha256=_sha256_of_file(pdf_path), pages=[])

    if batch_size <= 0 or total_pages <= batch_size:
        pages = _convert_one(pdf_path, page_offset=0, page_count=total_pages, settings=settings)
        return ExtractedReport(source_sha256=_sha256_of_file(pdf_path), pages=pages)

    logger.info(
        "extract_pdf: %d pages > batch_size %d; splitting into %d batches",
        total_pages, batch_size,
        (total_pages + batch_size - 1) // batch_size,
    )
    all_pages: list[ExtractedPage] = []
    src = fitz.open(str(pdf_path))
    try:
        for batch_start in range(0, total_pages, batch_size):
            batch_end = min(batch_start + batch_size, total_pages)
            batch_count = batch_end - batch_start
            logger.info(
                "extract_pdf: batch pages %d-%d (%d pages)",
                batch_start + 1, batch_end, batch_count,
            )

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                sub = fitz.open()
                try:
                    sub.insert_pdf(src, from_page=batch_start, to_page=batch_end - 1)
                    sub.save(str(tmp_path))
                finally:
                    sub.close()

                batch_pages = _convert_one(
                    tmp_path,
                    page_offset=batch_start,
                    page_count=batch_count,
                    settings=settings,
                )
                all_pages.extend(batch_pages)
            finally:
                tmp_path.unlink(missing_ok=True)
    finally:
        src.close()

    return ExtractedReport(source_sha256=_sha256_of_file(pdf_path), pages=all_pages)
