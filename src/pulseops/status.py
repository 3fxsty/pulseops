"""A monitor's current status, derived from its latest check."""

from datetime import datetime, timedelta
from typing import Literal

Status = Literal["up", "down", "paused", "unknown"]

# A check older than this many intervals (plus a margin for the scheduler's
# 5 s tick and the check itself) is stale: "no data", not "still up".
STALE_AFTER_INTERVALS = 2
STALE_MARGIN = timedelta(seconds=60)


def current_status(
    *,
    is_active: bool,
    interval_seconds: int,
    last_check_at: datetime | None,
    last_check_up: bool | None,
    now: datetime,
) -> Status:
    if not is_active:
        return "paused"
    if last_check_at is None:
        return "unknown"
    stale_after = STALE_AFTER_INTERVALS * timedelta(seconds=interval_seconds)
    if now - last_check_at > stale_after + STALE_MARGIN:
        return "unknown"
    return "up" if last_check_up else "down"
