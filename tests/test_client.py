"""Unit tests for the TTP client's pure helper functions (no SSH/asyncio)."""
from tesira_under_test.client import (  # noqa: E402  (registered by conftest.py)
    TesiraClient,
    TesiraConnectionInfo,
    _escape_value,
    _quote_tag,
    _Subscription,
    parse_float_value,
)

_INFO = TesiraConnectionInfo(host="10.0.0.1", port=22, username="default", password="default")


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


def test_dispatch_push_calls_matching_subscriber():
    client = TesiraClient(_INFO)
    received: list[float] = []
    client._subscriptions["tok1"] = _Subscription(
        tag="Level1", channel=1, throttle_ms=250, callback=received.append
    )

    client._dispatch_push('! "publishToken":"tok1" "value":-12.500000')

    assert received == [-12.5]


def test_dispatch_push_ignores_unknown_token():
    client = TesiraClient(_INFO)
    received: list[float] = []
    client._subscriptions["tok1"] = _Subscription(
        tag="Level1", channel=1, throttle_ms=250, callback=received.append
    )

    client._dispatch_push('! "publishToken":"someone-elses-token" "value":-1.000000')

    assert received == []


def test_dispatch_push_ignores_malformed_line():
    client = TesiraClient(_INFO)
    # Should not raise even though this doesn't match the expected push format.
    client._dispatch_push("! something unexpected")


def test_dispatch_push_only_updates_matching_token_among_several():
    client = TesiraClient(_INFO)
    a_values: list[float] = []
    b_values: list[float] = []
    client._subscriptions["tok_a"] = _Subscription(
        tag="Level1", channel=1, throttle_ms=250, callback=a_values.append
    )
    client._subscriptions["tok_b"] = _Subscription(
        tag="Level2", channel=1, throttle_ms=250, callback=b_values.append
    )

    client._dispatch_push('! "publishToken":"tok_b" "value":3.250000')

    assert a_values == []
    assert b_values == [3.25]
