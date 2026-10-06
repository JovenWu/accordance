from accordance.extractor.models import ExtractedPage, ExtractedReport
from accordance.indexer.chunker import _split_by_headings, chunk_report


def _report(*page_markdowns: str) -> ExtractedReport:
    return ExtractedReport(
        source_sha256="x",
        pages=[
            ExtractedPage(page_number=i + 1, markdown=md, tables=[])
            for i, md in enumerate(page_markdowns)
        ],
    )


def test_chunk_short_page_returns_one_chunk():
    report = _report("Hello world")
    chunks = chunk_report(report, target_tokens=500, overlap_tokens=50)
    assert len(chunks) == 1
    assert chunks[0].page == 1
    assert chunks[0].text == "Hello world"


def test_chunk_long_page_splits():
    long_text = " ".join(["word"] * 2000)
    report = _report(long_text)
    chunks = chunk_report(report, target_tokens=500, overlap_tokens=50)
    assert len(chunks) > 1
    assert all(c.page == 1 for c in chunks)


def test_chunks_do_not_cross_page_boundaries():
    report = _report("Page one content", "Page two content")
    chunks = chunk_report(report, target_tokens=500, overlap_tokens=50)
    pages = {c.page for c in chunks}
    assert pages == {1, 2}
    for c in chunks:
        if c.page == 1:
            assert "two" not in c.text


def test_split_by_headings_no_headings():
    sections = _split_by_headings("Just some prose, no headings here.")
    assert len(sections) == 1
    assert sections[0].heading == ""
    assert "prose" in sections[0].text


def test_split_by_headings_multiple_sections():
    md = (
        "# Title\n"
        "Intro paragraph.\n"
        "## Section A\n"
        "Body of A.\n"
        "## Section B\n"
        "Body of B.\n"
    )
    sections = _split_by_headings(md)
    headings = [s.heading for s in sections]
    assert headings == ["# Title", "## Section A", "## Section B"]
    assert "Body of A." in sections[1].text
    assert "Body of B." in sections[2].text
    for s in sections:
        assert s.text.startswith(s.heading)


def test_split_by_headings_prefix_content():
    """Content before the first heading is preserved as its own section."""
    md = "Some preamble.\n\n## First\nBody."
    sections = _split_by_headings(md)
    assert len(sections) == 2
    assert sections[0].heading == ""
    assert "preamble" in sections[0].text
    assert sections[1].heading == "## First"


def test_small_sections_become_one_chunk_each():
    md = (
        "## Org details\nWe are Acme Pte Ltd.\n"
        "## Headquarters\nSingapore.\n"
        "## Operations\nFive countries.\n"
    )
    report = _report(md)
    chunks = chunk_report(report, target_tokens=500, overlap_tokens=50)
    assert len(chunks) == 3
    assert all(c.page == 1 for c in chunks)
    texts = [c.text for c in chunks]
    assert any("Acme" in t for t in texts)
    assert any("Singapore" in t for t in texts)
    assert any("Five countries" in t for t in texts)
    assert any("## Org details" in t for t in texts)


def test_oversized_section_splits_with_heading_repeated():
    """A section bigger than target_tokens splits within itself; the heading
    is prepended to every piece so each sub-chunk carries section context."""
    heading = "## Greenhouse gas emissions"
    body = " ".join(["emission"] * 1500)
    md = f"{heading}\n{body}"
    report = _report(md)
    chunks = chunk_report(report, target_tokens=200, overlap_tokens=20)
    assert len(chunks) > 1
    assert all(heading in c.text for c in chunks)


def test_no_heading_oversized_falls_back_to_window_split():
    """Page with no headings but oversized text uses token-window split,
    without any heading repetition (since there is none)."""
    text = " ".join(["token"] * 2000)
    report = _report(text)
    chunks = chunk_report(report, target_tokens=500, overlap_tokens=50)
    assert len(chunks) > 1
    assert all(not c.text.startswith("#") for c in chunks)


def test_empty_page_is_skipped():
    report = _report("", "Page two content")
    chunks = chunk_report(report, target_tokens=500, overlap_tokens=50)
    pages = {c.page for c in chunks}
    assert pages == {2}


def test_mixed_short_and_long_sections():
    md = (
        "## Short\nShort body.\n"
        "## Long\n" + " ".join(["word"] * 1500)
    )
    report = _report(md)
    chunks = chunk_report(report, target_tokens=200, overlap_tokens=20)
    assert len(chunks) >= 2
    short_chunks = [c for c in chunks if "Short body" in c.text]
    long_chunks = [c for c in chunks if "## Long" in c.text]
    assert len(short_chunks) == 1
    assert len(long_chunks) >= 2


def test_large_table_kept_atomic():
    rows = "\n".join(f"| {i} | {i * 2} | {i * 3} |" for i in range(200))
    md = f"## Emissions by year\n| A | B | C |\n|---|---|---|\n{rows}"
    report = _report(md)
    chunks = chunk_report(report, target_tokens=100, overlap_tokens=10)
    holding = [c for c in chunks if "| 0 | 0 | 0 |" in c.text]
    assert len(holding) == 1
    assert "| 199 | 398 | 597 |" in holding[0].text


def test_prose_section_still_window_splits():
    body = " ".join(["word"] * 1500)
    report = _report(f"## Narrative\n{body}")
    chunks = chunk_report(report, target_tokens=200, overlap_tokens=20)
    assert len(chunks) > 1


def test_oversized_table_falls_back_to_splitting():
    rows = "\n".join(
        f"| {i} | value-{i} | data-{i} | extra-{i} | more-{i} | last-{i} |"
        for i in range(2000)
    )
    md = f"## Huge table\n| A | B | C | D | E | F |\n|---|---|---|---|---|---|\n{rows}"
    report = _report(md)
    chunks = chunk_report(report, target_tokens=200, overlap_tokens=20)
    assert len(chunks) > 1


def _index_rows(*ids: str) -> str:
    """A GRI-content-index-style block: one 'GRI <id> ... <page>' row per id."""
    return "\n".join(f"GRI {i} Disclosure title for {i} .... {40 + n}" for n, i in enumerate(ids))


def test_content_index_page_is_excluded():
    """A page that is a GRI content index (many disclosure ids, ~every line an
    id row) is navigation, not evidence — it must produce NO chunks."""
    md = "# GRI Content Index\n" + _index_rows(
        "2-1", "2-2", "2-3", "3-1", "201-1", "302-1", "303-1", "305-1", "305-2", "401-1"
    )
    chunks = chunk_report(_report(md), target_tokens=500, overlap_tokens=50)
    assert chunks == []


def test_content_index_under_subheadings_is_excluded():
    """An index fragmented under per-standard sub-headings is still caught at
    the page level (each subsection alone has too few ids)."""
    md = (
        "# GRI Content Index\n"
        "## GRI 2: General Disclosures\n" + _index_rows("2-1", "2-2", "2-3") + "\n"
        "## GRI 300: Environmental\n" + _index_rows("302-1", "303-1", "305-1") + "\n"
        "## GRI 400: Social\n" + _index_rows("401-1", "403-1", "405-1") + "\n"
    )
    chunks = chunk_report(_report(md), target_tokens=500, overlap_tokens=50)
    assert chunks == []


def test_narrative_mentioning_one_disclosure_is_kept():
    """Prose that references a single disclosure id is real content — keep it."""
    md = (
        "## Emissions\n"
        "We report our direct emissions under GRI 305-1 for the 2024 period, "
        "covering all combustion sources across the group."
    )
    chunks = chunk_report(_report(md), target_tokens=500, overlap_tokens=50)
    assert len(chunks) == 1
    assert "direct emissions" in chunks[0].text


def test_numeric_data_table_is_not_excluded():
    """A data table of figures (no GRI id rows) must NOT be mistaken for an
    index — it is the substantive evidence the judge needs."""
    md = (
        "## Water withdrawal by source (ML)\n"
        "| Source | 2023 | 2024 |\n|---|---|---|\n"
        "| Surface water | 12450 | 12999 |\n"
        "| Groundwater | 3210 | 3400 |\n"
        "| Total | 15660 | 16399 |\n"
    )
    chunks = chunk_report(_report(md), target_tokens=500, overlap_tokens=50)
    assert len(chunks) == 1
    assert "Surface water" in chunks[0].text


def test_inline_answered_general_disclosures_page_is_kept():
    """A GRI 2-series page that answers each disclosure inline (id-dense, but
    NOT a navigation table — no index heading) is substantive content and must
    be kept, or those disclosures would silently come back missing."""
    md = (
        "## General Disclosures\n"
        "2-1 Organizational details: Acme Corp, a private limited company in Singapore.\n"
        "2-2 Entities included in reporting: all subsidiaries in the annual report.\n"
        "2-3 Reporting period: calendar year 2024, published March 2025.\n"
        "2-4 Restatements: none in the current reporting period.\n"
        "2-5 External assurance: limited assurance by an external provider.\n"
        "2-6 Activities and value chain: mining and processing of nickel.\n"
        "2-7 Employees: 3,200 total employees across all operating sites.\n"
        "2-8 Workers who are not employees: 450 contractors engaged this year.\n"
    )
    chunks = chunk_report(_report(md), target_tokens=500, overlap_tokens=50)
    assert chunks
    assert any("Organizational details" in c.text for c in chunks)


def test_disclosure_keyed_data_summary_table_is_kept():
    """A consolidated ESG data table that carries a GRI reference column on
    each figure row is the evidence the judge needs — not a navigation index."""
    md = (
        "## ESG Performance Data Summary\n"
        "| Indicator | GRI | 2023 | 2024 |\n|---|---|---|---|\n"
        "| Scope 1 emissions (tCO2e) | 305-1 | 12000 | 12450 |\n"
        "| Scope 2 emissions (tCO2e) | 305-2 | 8000 | 8200 |\n"
        "| Energy consumption (GJ) | 302-1 | 50000 | 51000 |\n"
        "| Water withdrawal (ML) | 303-3 | 15000 | 15660 |\n"
        "| Total employees | 2-7 | 3000 | 3200 |\n"
        "| New hires | 401-1 | 400 | 450 |\n"
        "| Women in workforce (%) | 405-1 | 30 | 33 |\n"
        "| Governance body size | 2-9 | 10 | 11 |\n"
    )
    chunks = chunk_report(_report(md), target_tokens=2000, overlap_tokens=50)
    assert chunks
    assert any("305-1" in c.text for c in chunks)


def test_material_topics_mapping_table_is_kept():
    """A material-topics → GRI Standard mapping table carries GRI 3-2/3-3
    evidence and must not be mistaken for the navigation index."""
    md = (
        "## Material Topics\n"
        "| Material topic | GRI Standard |\n|---|---|\n"
        "| Climate change | 305-1 |\n"
        "| Energy | 302-1 |\n"
        "| Water | 303-3 |\n"
        "| Biodiversity | 304-1 |\n"
        "| Emissions | 305-2 |\n"
        "| Waste | 306-1 |\n"
        "| Employment | 401-1 |\n"
        "| Health and safety | 403-9 |\n"
        "| Diversity | 405-1 |\n"
        "| Anti-corruption | 205-1 |\n"
    )
    chunks = chunk_report(_report(md), target_tokens=2000, overlap_tokens=50)
    assert chunks
    assert any("Climate change" in c.text for c in chunks)
