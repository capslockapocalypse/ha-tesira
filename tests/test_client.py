"""Unit tests for the TTP client's pure helper functions (no SSH/asyncio)."""
from tesira_under_test.client import _escape_value  # noqa: E402  (registered by conftest.py)


def test_escape_value_plain():
    assert _escape_value("Morning Announcement") == "Morning Announcement"


def test_escape_value_embedded_quote():
    assert _escape_value('Room "A"') == 'Room \\"A\\"'


def test_escape_value_embedded_backslash():
    assert _escape_value(r"C:\Presets") == r"C:\\Presets"


def test_escape_value_quote_and_backslash():
    assert _escape_value('back\\slash "quote"') == 'back\\\\slash \\"quote\\"'
