"""Guardrails baked into the judge system prompt.

These are presence checks — not LLM behavior tests — so an accidental edit
that removes a guardrail fails CI. See diagnosis RC1 (cites GRI index) and
RC3 (gibberish table-cell excerpts).
"""

from accordance.judge.prompts import SYSTEM_PROMPT


def test_prompt_forbids_citing_the_content_index():
    p = SYSTEM_PROMPT.lower()
    assert "content index" in p
    # Described as a navigation table the judge must never cite.
    assert "navigation" in p
    assert "never" in p


def test_example5_credits_the_figure_without_quoting_the_garbled_cell():
    # EXAMPLE 5 (garbled water table) must still credit the figure (element
    # found) but NOT store the number-soup cell as evidence_excerpt.
    assert "total_withdrawal_ml" in SYSTEM_PROMPT
    output_line = next(
        ln
        for ln in SYSTEM_PROMPT.splitlines()
        if '"total_withdrawal_ml"' in ln and '"status":"covered"' in ln
    )
    assert '"evidence_excerpt":null' in output_line
    assert "Total15,660.0015,660.00" not in output_line
