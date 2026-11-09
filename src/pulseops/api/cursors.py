"""Opaque cursors for keyset pagination (ADR-050, ADR-069).

- Check history: base64url("v1:<scheduled_at in microseconds>").
- Incidents: base64url("i1:<started_at in microseconds>:<incident id, hex>").

Clients must not interpret them: the prefix lets a format change without
breaking them, and keeps one list's cursors out of the other. Anything that
does not decode cleanly is rejected, never trusted.
"""

import base64
import binascii
from datetime import datetime
from uuid import UUID

from pulseops.timestamps import from_microseconds, to_microseconds

CURSOR_VERSION = "v1"
# "v1:" plus up to 17 digits (microseconds up to the year 5138), base64-encoded.
MAX_CURSOR_LENGTH = 32
MAX_DIGITS = 17
INCIDENT_CURSOR_VERSION = "i1"
# "i1:", up to 17 digits, ":" and 32 hex digits: 53 characters, 72 encoded.
MAX_INCIDENT_CURSOR_LENGTH = 72
HEX_DIGITS = frozenset("0123456789abcdef")


class InvalidCursorError(ValueError):
    """The cursor was not issued by this API (or was tampered with)."""


def encode_cursor(scheduled_at: datetime) -> str:
    return _encode(f"{CURSOR_VERSION}:{to_microseconds(scheduled_at)}")


def decode_cursor(cursor: str) -> datetime:
    version, _, digits = _decode(cursor, MAX_CURSOR_LENGTH).partition(":")
    if version != CURSOR_VERSION:
        raise InvalidCursorError
    return _moment(digits)


def encode_incident_cursor(started_at: datetime, incident_id: UUID) -> str:
    micros = to_microseconds(started_at)
    return _encode(f"{INCIDENT_CURSOR_VERSION}:{micros}:{incident_id.hex}")


def decode_incident_cursor(cursor: str) -> tuple[datetime, UUID]:
    parts = _decode(cursor, MAX_INCIDENT_CURSOR_LENGTH).split(":")
    if len(parts) != 3 or parts[0] != INCIDENT_CURSOR_VERSION:
        raise InvalidCursorError
    _, digits, hex_id = parts
    # Exactly what encode_incident_cursor writes: 32 lowercase hex digits.
    if len(hex_id) != 32 or not set(hex_id) <= HEX_DIGITS:
        raise InvalidCursorError
    return _moment(digits), UUID(hex=hex_id)


def _encode(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode()).rstrip(b"=").decode()


def _decode(cursor: str, max_length: int) -> str:
    if not 0 < len(cursor) <= max_length:
        raise InvalidCursorError
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return base64.b64decode(padded, altchars=b"-_", validate=True).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise InvalidCursorError from None


def _moment(digits: str) -> datetime:
    if not 0 < len(digits) <= MAX_DIGITS:
        raise InvalidCursorError
    if not all("0" <= char <= "9" for char in digits):
        raise InvalidCursorError
    return from_microseconds(int(digits))
