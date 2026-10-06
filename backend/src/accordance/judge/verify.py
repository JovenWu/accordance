"""Zero-cost hallucination guard for judge output.

Substring-checks the LLM's `evidence_excerpt` against the chunks the
retriever actually returned. When the excerpt doesn't appear in *any* of
those chunks, it almost certainly didn't come from the report — the LLM
fabricated it. We don't trust string-match alone to detect semantic
mismatch ("quote exists but doesn't support the claim"), but it catches
the most egregious cases (made-up numbers, invented quote, etc.) at zero
LLM cost.

Verified excerpts are passed through unchanged. Unverified ones get
cleared (the excerpt and its cited page are nulled) so users don't see
fake quotes in the dashboard. The original is preserved in the
JudgeTrace for forensic debugging.
"""

from __future__ import annotations

import re

_WS = re.compile(r"\s+")
_PUNCT_EDGES = re.compile(r"^[^\w]+|[^\w]+$")


def _normalize(s: str) -> str:
    """Lowercase, collapse whitespace, strip leading/trailing punctuation.

    Designed to survive normal LLM rephrasing artifacts:
    - smart quotes vs straight quotes (handled by edge-strip + lowercase)
    - double spaces from PDF extraction
    - trailing period the LLM may or may not have included
    """
    s = _WS.sub(" ", s).strip().lower()
    return _PUNCT_EDGES.sub("", s)


def verify_excerpt(excerpt: str | None, chunks: list[dict]) -> bool:
    """Return True if the excerpt plausibly came from one of the chunks.

    Strategy:
      1. Empty / None excerpt → trivially True (nothing to verify).
      2. Normalize both sides, then substring-check excerpt ⊆ chunk.text.
      3. Fall back to a token-overlap check: if >= 70% of the excerpt's
         content words appear in any single chunk, accept. This handles
         the case where the LLM lightly paraphrased while still quoting
         (e.g., dropped a stray adjective).

    Designed to err on the side of *accepting* — false-positives mean a
    hallucinated quote slips through, but false-negatives mean we drop a
    real one, which is the worse outcome since the verdict itself still
    stands either way.
    """
    if not excerpt or not excerpt.strip():
        return True
    excerpt_norm = _normalize(excerpt)
    if not excerpt_norm:
        return True

    for chunk in chunks:
        chunk_norm = _normalize(chunk["text"])
        if excerpt_norm in chunk_norm:
            return True

    excerpt_tokens_all = re.findall(r"\w+", excerpt_norm)
    excerpt_word_tokens = {t for t in excerpt_tokens_all if len(t) > 2 and not _has_digit(t)}
    excerpt_numeric_tokens = {t for t in excerpt_tokens_all if _has_digit(t)}
    if not excerpt_word_tokens and not excerpt_numeric_tokens:
        return False
    for chunk in chunks:
        chunk_tokens = set(re.findall(r"\w+", _normalize(chunk["text"])))
        if not chunk_tokens:
            continue
        if excerpt_numeric_tokens and not excerpt_numeric_tokens.issubset(chunk_tokens):
            continue
        if not excerpt_word_tokens:
            return True
        overlap = excerpt_word_tokens & chunk_tokens
        if len(overlap) / len(excerpt_word_tokens) >= 0.7:
            return True

    return False


def _has_digit(token: str) -> bool:
    return any(c.isdigit() for c in token)
