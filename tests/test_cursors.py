"""History cursors: exact round trip, and nothing forged gets through."""

import base64
from datetime import UTC, datetime

import pytest

from pulseops.api.cursors import InvalidCursorError, decode_cursor, encode_cursor

MOMENT = datetime(2026, 10, 28, 9, 30, 15, 123456, tzinfo=UTC)


def b64(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode()).rstrip(b"=").decode()


def test_round_trip_keeps_the_exact_microsecond():
    assert decode_cursor(encode_cursor(MOMENT)) == MOMENT


def test_cursor_is_opaque_and_url_safe():
    cursor = encode_cursor(MOMENT)

    assert "2026" not in cursor
    assert set(cursor) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "not base64!",
        "a" * 33,  # longer than any real cursor
        b64("v2:1793140694931815"),  # unknown version
        b64("1793140694931815"),  # no version
        b64("v1:"),  # no value
        b64("v1:-5"),
        b64("v1:12.5"),
        b64("v1:１２３"),  # non-ASCII digits
        b64("v1:999999999999999999"),  # 18 digits: more than any real cursor
        b64("v1:1' OR '1'='1"),
        base64.urlsafe_b64encode(b"\xff\xfe").decode(),  # not text
    ],
)
def test_forged_cursors_are_rejected(cursor):
    with pytest.raises(InvalidCursorError):
        decode_cursor(cursor)
