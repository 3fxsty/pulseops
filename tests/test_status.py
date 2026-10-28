from datetime import UTC, datetime, timedelta

import pytest

from pulseops.status import current_status

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def status(*, active=True, interval=60, ago=None, up=True):
    return current_status(
        is_active=active,
        interval_seconds=interval,
        last_check_at=None if ago is None else NOW - ago,
        last_check_up=None if ago is None else up,
        now=NOW,
    )


def test_recent_check_decides_up_or_down():
    assert status(ago=timedelta(seconds=30), up=True) == "up"
    assert status(ago=timedelta(seconds=30), up=False) == "down"


def test_paused_wins_over_everything():
    assert status(active=False, ago=timedelta(seconds=5)) == "paused"
    assert status(active=False) == "paused"


def test_no_checks_yet_is_unknown():
    assert status() == "unknown"


@pytest.mark.parametrize(
    ("ago_seconds", "expected"),
    [
        (180, "up"),  # exactly 2 x 60 s + 60 s: still fresh
        (181, "unknown"),  # one second later: stale
    ],
)
def test_a_stale_check_is_unknown(ago_seconds, expected):
    assert status(interval=60, ago=timedelta(seconds=ago_seconds)) == expected
