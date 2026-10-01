"""An encrypted/password-protected PDF must fail with a clear typed error,
not a raw 'document closed or encrypted' deep in extraction."""
import fitz
import pytest

from accordance.extractor.models import EncryptedPDFError
from accordance.extractor.pymupdf_extractor import extract_pdf


def _make_encrypted_pdf(path):
    doc = fitz.open()
    doc.new_page()
    doc.save(
        str(path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner",
        user_pw="user",  # user password => needs_pass when reopened without it
    )
    doc.close()


def test_extract_encrypted_pdf_raises_clear_error(tmp_path):
    path = tmp_path / "locked.pdf"
    _make_encrypted_pdf(path)
    with pytest.raises(EncryptedPDFError):
        extract_pdf(path)
