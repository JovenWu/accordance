import pytest

from accordance.judge.core import _extract_json


@pytest.mark.parametrize(
    "raw,expected_start",
    [
        ('{"status":"covered"}', '{"status":"covered"}'),
        (
            '```json\n{"status":"covered","note":"x"}\n```',
            '{"status":"covered","note":"x"}',
        ),
        (
            '```\n{"status":"covered"}\n```',
            '{"status":"covered"}',
        ),
        (
            'Here is the JSON:\n```json\n{"status":"partial"}\n```',
            '{"status":"partial"}',
        ),
        (
            'Sure, here you go: {"status":"missing","note":"n"} Hope that helps!',
            '{"status":"missing","note":"n"}',
        ),
    ],
)
def test_extract_json_strips_wrapping(raw, expected_start):
    assert _extract_json(raw).strip() == expected_start
