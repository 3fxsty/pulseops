"""Cursors: exact round trip, and nothing forged gets through."""

import base64
import uuid
from datetime import UTC, datetime

import pytest

from pulseops.api.cursors import (
    InvalidCursorError,
    decode_cursor,
    decode_incident_cursor,
    encode_cursor,
    encode_incident_cursor,
)

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


# --- incident cursors (ADR-069) ---

INCIDENT_ID = uuid.UUID("0197a3c2-5e1f-7b40-9d2a-6c8e1f0b4a11")
HEX = INCIDENT_ID.hex


def test_incident_cursor_round_trip():
    cursor = encode_incident_cursor(MOMENT, INCIDENT_ID)

    assert decode_incident_cursor(cursor) == (MOMENT, INCIDENT_ID)
    assert HEX not in cursor and "2026" not in cursor


def test_incident_cursor_fits_its_length_limit():
    # The largest timestamp a cursor allows (17 digits).
    latest = datetime(5000, 1, 1, tzinfo=UTC)

    assert len(encode_incident_cursor(latest, INCIDENT_ID)) <= 72


def test_the_two_kinds_of_cursor_never_mix():
    with pytest.raises(InvalidCursorError):
        decode_incident_cursor(encode_cursor(MOMENT))
    with pytest.raises(InvalidCursorError):
        decode_cursor(encode_incident_cursor(MOMENT, INCIDENT_ID))


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "a" * 73,  # longer than any real cursor
        b64(f"i2:1793140694931815:{HEX}"),  # unknown version
        b64("i1:1793140694931815"),  # no id
        b64(f"i1::{HEX}"),  # no time
        b64(f"i1:1793140694931815:{HEX}:x"),  # one part too many
        b64(f"i1:1793140694931815:{HEX.upper()}"),  # never written in upper case
        b64(f"i1:1793140694931815:{HEX[:-1]}"),  # 31 hex digits
        b64(f"i1:1793140694931815:{HEX[:-1]}g"),  # not hex
        b64(f"i1:1793140694931815:{INCIDENT_ID}"),  # dashed form
        b64(f"i1:-5:{HEX}"),
        b64(f"i1:999999999999999999:{HEX}"),  # 18 digits
        b64(f"i1:1' OR '1'='1:{HEX}"),
    ],
)
def test_forged_incident_cursors_are_rejected(cursor):
    with pytest.raises(InvalidCursorError):
        decode_incident_cursor(cursor)
