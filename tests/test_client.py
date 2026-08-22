"""Unit tests for the TTP client's pure helper functions (no SSH/asyncio)."""
from tesira_under_test.client import (  # noqa: E402  (registered by conftest.py)
    _escape_value,
    _quote_tag,
    parse_float_value,
)


def test_escape_value_plain():
    assert _escape_value("Morning Announcement") == "Morning Announcement"


def test_escape_value_embedded_quote():
    assert _escape_value('Room "A"') == 'Room \\"A\\"'


def test_escape_value_embedded_backslash():
    assert _escape_value(r"C:\Presets") == r"C:\\Presets"


def test_escape_value_quote_and_backslash():
    assert _escape_value('back\\slash "quote"') == 'back\\\\slash \\"quote\\"'


def test_quote_tag_no_spaces():
    assert _quote_tag("Level1") == "Level1"


def test_quote_tag_with_spaces():
    assert _quote_tag("Program Volume") == '"Program Volume"'


def test_parse_float_value_positive():
    assert parse_float_value('"value":0.000000') == 0.0


def test_parse_float_value_negative():
    assert parse_float_value('"value":-10.500000') == -10.5


def test_parse_float_value_missing():
    assert parse_float_value('"list":["a" "b"]') is None
