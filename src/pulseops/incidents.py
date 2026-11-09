"""When an incident opens and when it closes (ADR-060).

A pure function: it looks at a monitor's latest checks and returns what to do.
The caller (pulseops/scheduling.py) runs it in the transaction that stores the
check (ADR-061) and applies the decision.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from pulseops.status import STALE_AFTER_INTERVALS, STALE_MARGIN

# Consecutive failed checks that open an incident, and consecutive successful
# ones that close it. Two and two: one hiccup never alerts, and a site that
# alternates up and down never opens and closes incidents all day.
OPEN_AFTER_FAILURES = 2
CLOSE_AFTER_SUCCESSES = 2
# How many recent checks the caller passes in. More than the thresholds, so a
# streak that grew past them (e.g. a late check filled a hole) still starts at
# its real first check.
LOOKBACK_CHECKS = 10


class RecentCheck(Protocol):
    scheduled_at: datetime
    is_up: bool
    error_kind: str | None
    status_code: int | None


@dataclass(frozen=True, slots=True)
class OpenIncident:
    """Open an incident, described by the first failed check of the streak."""

    started_at: datetime
    error_kind: str
    status_code: int | None


@dataclass(frozen=True, slots=True)
class ResolveIncident:
    """Close the open incident at the first successful check of the streak."""

    resolved_at: datetime


Decision = OpenIncident | ResolveIncident | None


def decide(
    recent_checks: Sequence[RecentCheck],
    *,
    interval_seconds: int,
    incident_open: bool,
    not_before: datetime | None = None,
) -> Decision:
    """What the latest checks mean for the monitor's incidents.

    recent_checks: newest first, the newest being the check just stored.
    not_before: when the monitor's previous incident ended. A streak never
    reaches back past it, so checks from before a pause or a URL change never
    start a new incident.
    """
    streak = _latest_streak(recent_checks, interval_seconds, not_before)
    if not streak:
        return None
    newest, first = streak[0], streak[-1]
    if incident_open:
        if newest.is_up and len(streak) >= CLOSE_AFTER_SUCCESSES:
            return ResolveIncident(resolved_at=first.scheduled_at)
        return None
    if not newest.is_up and len(streak) >= OPEN_AFTER_FAILURES:
        if first.error_kind is None:
            # The checks table forbids it (ck_checks_is_up_matches_error_kind).
            raise ValueError("a failed check has no error_kind")
        return OpenIncident(
            started_at=first.scheduled_at,
            error_kind=first.error_kind,
            status_code=first.status_code,
        )
    return None


def _latest_streak(
    checks: Sequence[RecentCheck], interval_seconds: int, not_before: datetime | None
) -> list[RecentCheck]:
    """The newest run of checks with the same outcome, newest first.

    A gap longer than the staleness limit (ADR-047) breaks the run: two checks
    that far apart are not consecutive, e.g. with the worker stopped between
    them.
    """
    max_gap = STALE_AFTER_INTERVALS * timedelta(seconds=interval_seconds) + STALE_MARGIN
    streak: list[RecentCheck] = []
    for check in checks:
        if not_before is not None and check.scheduled_at < not_before:
            break
        if streak:
            if check.is_up != streak[0].is_up:
                break
            if streak[-1].scheduled_at - check.scheduled_at > max_gap:
                break
        streak.append(check)
    return streak
