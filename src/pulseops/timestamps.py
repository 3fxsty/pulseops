"""Exact conversion between timestamps and integer microseconds.

PostgreSQL stores microseconds: a timestamp that travels as an integer (queue
payloads, API cursors) must come back exactly the same, or it no longer
matches the row it came from.
"""

from datetime import UTC, datetime, timedelta

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
MICROSECOND = timedelta(microseconds=1)


def to_microseconds(moment: datetime) -> int:
    return (moment - EPOCH) // MICROSECOND


def from_microseconds(value: int) -> datetime:
    return EPOCH + value * MICROSECOND
