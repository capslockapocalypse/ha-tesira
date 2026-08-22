"""Unit tests for the TTP response parsing helpers.

These test pure functions only (no SSH/asyncio involved) against response
strings taken directly from the Biamp Cornerstone Tesira Text Protocol
manual (v4.2), so they double as a record of the expected wire format.
"""
from tesira_under_test.client import (  # noqa: E402  (registered by conftest.py)
    _quote_tag,
    parse_int_value,
    parse_list,
    parse_value,
)


def test_parse_value_bool():
    assert parse_value('"value":false') == "false"


def test_parse_value_int():
    assert parse_value('"value":1001') == "1001"


def test_parse_int_value():
    assert parse_int_value('"value":1001') == 1001


def test_parse_int_value_non_numeric_returns_none():
    assert parse_int_value('"value":"BUTTERWORTH"') is None


def test_parse_int_value_missing_returns_none():
    assert parse_int_value("") is None


def test_parse_list():
    body = (
        '"list":["123" "AudioMeter1" "AudioMeter2" "AudioMeter3" '
        '"DEVICE" "Input1" "Mixer1" "Mute1" "Level1" "Output1"]'
    )
    assert parse_list(body) == [
        "123",
        "AudioMeter1",
        "AudioMeter2",
        "AudioMeter3",
        "DEVICE",
        "Input1",
        "Mixer1",
        "Mute1",
        "Level1",
        "Output1",
    ]


def test_parse_list_empty_when_absent():
    assert parse_list('"value":1001') == []


def test_quote_tag_no_spaces():
    assert _quote_tag("Level1") == "Level1"


def test_quote_tag_with_spaces():
    assert _quote_tag("my level 2") == '"my level 2"'


def test_quote_tag_numeric():
    assert _quote_tag("123") == "123"
