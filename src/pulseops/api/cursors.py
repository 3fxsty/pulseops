"""Opaque cursors for the check history (ADR-015: keyset pagination).

A cursor is base64url("v1:<scheduled_at in microseconds>"). Clients must not
interpret it: the version prefix lets the format change without breaking
them. Anything that does not decode cleanly is rejected, never trusted.
"""

import base64
import binascii
from datetime import datetime

from pulseops.timestamps import from_microseconds, to_microseconds

CURSOR_VERSION = "v1"
# "v1:" plus up to 17 digits (microseconds up to the year 5138), base64-encoded.
MAX_CURSOR_LENGTH = 32
MAX_DIGITS = 17


class InvalidCursorError(ValueError):
    """The cursor was not issued by this API (or was tampered with)."""


def encode_cursor(scheduled_at: datetime) -> str:
    raw = f"{CURSOR_VERSION}:{to_microseconds(scheduled_at)}".encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def decode_cursor(cursor: str) -> datetime:
    if not 0 < len(cursor) <= MAX_CURSOR_LENGTH:
        raise InvalidCursorError
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise InvalidCursorError from None
    version, _, digits = raw.partition(":")
    if version != CURSOR_VERSION or not (0 < len(digits) <= MAX_DIGITS):
        raise InvalidCursorError
    if not all("0" <= char <= "9" for char in digits):
        raise InvalidCursorError
    return from_microseconds(int(digits))
