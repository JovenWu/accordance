"""Regression tests for resolve_pdf_path.

Root cause (debugged 2026-06-11): pdf_path is persisted as a platform-specific
string (str(Path) at upload time), so a DB created on Windows ('data\\pdfs\\x.pdf')
breaks when read in the Linux container — fitz.open() raises FileNotFoundError and
the vision fallback silently produces 0 pages. PDFs always live in pdf_dir under a
unique '<uuid>.pdf' name, so resolution must normalize separators and fall back to
pdf_dir/<basename>.
"""
from accordance.config import Settings, resolve_pdf_path


def test_resolves_windows_relative_path_to_pdf_dir(tmp_path):
    settings = Settings(data_dir=tmp_path)
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir(parents=True)
    real = pdf_dir / "abc.pdf"
    real.write_bytes(b"%PDF-1.4 fake")

    # A row written by the app while running on Windows: backslashes, relative.
    resolved = resolve_pdf_path("data\\pdfs\\abc.pdf", settings)

    assert resolved == real
    assert resolved.is_file()


def test_prefers_stored_path_when_it_exists(tmp_path):
    settings = Settings(data_dir=tmp_path)
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir(parents=True)
    real = pdf_dir / "xyz.pdf"
    real.write_bytes(b"%PDF")

    resolved = resolve_pdf_path(str(real), settings)

    assert resolved.is_file()
    assert resolved.name == "xyz.pdf"


def test_missing_file_returns_pdf_dir_candidate(tmp_path):
    settings = Settings(data_dir=tmp_path)

    # No file on disk — caller decides how to handle (404 / fallback), but we
    # must not crash and must point at the canonical location.
    resolved = resolve_pdf_path("data\\pdfs\\nope.pdf", settings)

    assert resolved == tmp_path / "pdfs" / "nope.pdf"
