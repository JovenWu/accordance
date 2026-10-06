"""Snap an LLM's evidence_excerpt to verbatim text from the actual PDF page.

The judge paraphrases/reconstructs quotes (and quotes markdown, not the
glyph text the viewer renders). Snapping replaces the quote with the exact
contiguous span of PDF page text it best matches, so the stored excerpt is
always real report text and the frontend highlight lands exactly on it.
"""

from accordance.judge.snap import best_verbatim_span, snap_excerpt

PAGE = (
    "Corporate Governance\n"
    "The ownership structure of PT Vale Indonesia Tbk reflects a strategic "
    "partnership between global and national shareholders. As of December 31, "
    "2024, the major shareholders were Vale Canada Limited and MIND ID.\n"
)


class TestBestVerbatimSpan:
    def test_returns_the_exact_span_for_a_verbatim_excerpt(self):
        excerpt = (
            "the ownership structure of PT Vale Indonesia Tbk reflects a "
            "strategic partnership"
        )
        span = best_verbatim_span(excerpt, PAGE)
        assert span is not None
        assert span in PAGE
        assert "reflects a strategic partnership" in span

    def test_snaps_a_paraphrase_to_the_real_verbatim_sentence(self):
        excerpt = (
            "As of 31 December 2024, the major shareholders were Vale Canada "
            "Limited and MIND ID across all business units."
        )
        span = best_verbatim_span(excerpt, PAGE)
        assert span is not None
        assert span in PAGE
        assert "Vale Canada Limited and MIND ID" in span

    def test_rejects_coincidental_overlap(self):
        excerpt = (
            "Water consumption intensity decreased by twelve percent compared "
            "to the prior reporting year."
        )
        assert best_verbatim_span(excerpt, PAGE) is None

    def test_expands_a_narrative_fragment_to_the_full_sentence(self):
        page = (
            "Background notes. The board approved the new climate transition "
            "policy in March 2024 after extensive review. Other matters followed."
        )
        span = best_verbatim_span("approved the new climate transition policy", page)
        assert span == (
            "The board approved the new climate transition policy in March "
            "2024 after extensive review."
        )

    def test_numeric_cell_is_not_sentence_expanded(self):
        page = "Total15,660.0015,660.00 and other figures 42,000.00 appear here."
        span = best_verbatim_span("Total15,660.0015,660.00", page)
        assert span == "Total15,660.0015,660.00"

    def test_flattened_multi_metric_row_is_not_expanded_across_cells(self):
        page = (
            "The following data is reported. Surface water 12450 Groundwater "
            "3210 Total water withdrawal 15660 Energy 98000 tonnes here"
        )
        span = best_verbatim_span("Total water withdrawal 15660 Energy", page)
        assert span == "Total water withdrawal 15660 Energy"

    def test_does_not_begin_a_span_mid_number_at_a_decimal(self):
        page = "Revenue grew 3.5 percent and margins improved across all regions this year."
        span = best_verbatim_span("margins improved across all regions", page)
        assert span is not None
        assert not span[0].isdigit()
        assert "margins improved across all regions" in span

    def test_normalizes_quotes_and_ligatures(self):
        page = 'Our office is the “Marina” ﬁnancial centre downtown.'
        excerpt = 'our office is the "Marina" financial centre'
        span = best_verbatim_span(excerpt, page)
        assert span is not None
        assert span in page
        assert "Marina" in span


class TestSnapExcerpt:
    def test_uses_the_cited_page_first(self):
        texts = {5: PAGE, 9: "Unrelated content about energy efficiency."}
        text, page = snap_excerpt(
            "the ownership structure of PT Vale Indonesia Tbk reflects a strategic partnership",
            cited_page=5,
            candidate_pages=[5, 9],
            get_page_text=lambda p: texts.get(p, ""),
        )
        assert page == 5
        assert "ownership structure" in text

    def test_corrects_a_wrong_cited_page_via_fallback(self):
        texts = {5: "Totally different content about emissions.", 9: PAGE}
        text, page = snap_excerpt(
            "As of December 31, 2024, the major shareholders were Vale Canada Limited and MIND ID.",
            cited_page=5,
            candidate_pages=[5, 9],
            get_page_text=lambda p: texts.get(p, ""),
        )
        assert page == 9
        assert "Vale Canada Limited and MIND ID" in text

    def test_drops_when_not_found_anywhere(self):
        texts = {5: "alpha beta gamma", 9: "delta epsilon"}
        assert snap_excerpt(
            "a governance statement that appears on no retrieved page at all",
            cited_page=5,
            candidate_pages=[5, 9],
            get_page_text=lambda p: texts.get(p, ""),
        ) == (None, None)

    def test_empty_or_missing_excerpt_returns_nulls(self):
        assert snap_excerpt(None, 5, [5], lambda p: "x") == (None, None)
        assert snap_excerpt("   ", 5, [5], lambda p: "x") == (None, None)
