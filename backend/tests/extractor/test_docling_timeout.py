"""Wall-clock timeout helper for the Docling extraction pass."""
import time

import pytest

from accordance.extractor.docling_extractor import _run_with_timeout
from accordance.extractor.models import ExtractionTimeoutError


def test_run_with_timeout_returns_value_when_fast():
    assert _run_with_timeout(lambda: 42, timeout=5) == 42


def test_run_with_timeout_disabled_is_passthrough():
    # timeout <= 0 disables the guard entirely (default behavior).
    assert _run_with_timeout(lambda: 7, timeout=0) == 7


def test_run_with_timeout_raises_on_slow_call():
    with pytest.raises(ExtractionTimeoutError):
        _run_with_timeout(lambda: time.sleep(2), timeout=0.1)


def test_run_with_timeout_propagates_inner_error():
    def boom():
        raise ValueError("inner")

    with pytest.raises(ValueError, match="inner"):
        _run_with_timeout(boom, timeout=5)
