"""prompt_hash determinism + sensitivity tests."""

import importlib

from accordance.judge import prompts


def test_prompt_hash_is_stable_across_imports():
    """Same module source → same hash. Reimporting must not produce a new value."""
    h1 = prompts.PROMPT_HASH
    reimported = importlib.reload(prompts)
    assert reimported.PROMPT_HASH == h1


def test_prompt_hash_is_16_hex_chars():
    h = prompts.PROMPT_HASH
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_prompt_hash_changes_when_system_changes(monkeypatch):
    """Tampering with the system prompt at runtime should yield a different hash.

    This is the property eval relies on: 'finding.prompt_hash == X' means it was
    produced by the exact prompt revision whose hash is X.
    """
    monkeypatch.setattr(prompts, "SYSTEM_PROMPT", prompts.SYSTEM_PROMPT + "\n# tweak")
    h2 = prompts._compute_prompt_hash()
    assert h2 != prompts.PROMPT_HASH


def test_prompt_hash_changes_when_template_changes(monkeypatch):
    monkeypatch.setattr(
        prompts, "USER_TEMPLATE", prompts.USER_TEMPLATE + "\nReturn JSON now."
    )
    h2 = prompts._compute_prompt_hash()
    assert h2 != prompts.PROMPT_HASH


def test_system_prompt_contains_few_shot_examples():
    """Smoke check that the examples we added are present in the shipping prompt."""
    sp = prompts.SYSTEM_PROMPT
    assert "EXAMPLE 1" in sp
    assert "EXAMPLE 2" in sp
    assert '"status":"covered"' in sp
    assert '"status":"partial"' in sp


def test_system_prompt_documents_applicable_and_na():
    sp = prompts.SYSTEM_PROMPT
    assert "applicable" in sp
    assert "na_reason" in sp
    assert "2-1" in sp and "3-2" in sp
