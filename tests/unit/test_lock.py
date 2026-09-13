from __future__ import annotations

from gitftp.lock import holder_message, parse


def test_parse_real_newline() -> None:
    assert parse(b"abc123\nalice@host on Mon, 01 Jan 2024 00:00:00 +0000\n") == (
        "abc123",
        "alice@host on Mon, 01 Jan 2024 00:00:00 +0000",
    )


def test_parse_upstream_literal_backslash_n() -> None:
    assert parse(b"abc123\\nalice@host on date") == ("abc123", "alice@host on date")


def test_parse_empty() -> None:
    assert parse(b"") == ("", "")


def test_holder_message_shape() -> None:
    msg = holder_message()
    assert "@" in msg and " on " in msg
