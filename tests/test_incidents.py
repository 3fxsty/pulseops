"""The rule that opens and closes incidents (ADR-060), without a database."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from pulseops.incidents import (
    LOOKBACK_CHECKS,
    OpenIncident,
    ResolveIncident,
    decide,
)

T0 = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
INTERVAL = 60


@dataclass(frozen=True)
class FakeCheck:
    scheduled_at: datetime
    is_up: bool
    error_kind: str | None = None
    status_code: int | None = None


def at(slot: int, every: int = INTERVAL) -> datetime:
    return T0 + timedelta(seconds=every * slot)


def make_check(slot: int, outcome: str, every: int = INTERVAL) -> FakeCheck:
    if outcome == "U":
        return FakeCheck(at(slot, every), True, None, 200)
    return FakeCheck(at(slot, every), False, "http_error", 503)


def history(pattern: str, every: int = INTERVAL) -> list[FakeCheck]:
    """Checks from a pattern such as "UUFF" (U up, F failed), oldest first and
    one per interval. Returned newest first, as decide() expects."""
    return [make_check(slot, c, every) for slot, c in enumerate(pattern)][::-1]


def replay(pattern: str) -> list[tuple[str, datetime]]:
    """Feed the checks one at a time, as the worker does, and list the events."""
    events: list[tuple[str, datetime]] = []
    seen: list[FakeCheck] = []
    incident_open, not_before = False, None
    for slot, outcome in enumerate(pattern):
        seen.insert(0, make_check(slot, outcome))
        decision = decide(
            seen[:LOOKBACK_CHECKS],
            interval_seconds=INTERVAL,
            incident_open=incident_open,
            not_before=not_before,
        )
        if isinstance(decision, OpenIncident):
            events.append(("opened", decision.started_at))
            incident_open = True
        elif isinstance(decision, ResolveIncident):
            events.append(("resolved", decision.resolved_at))
            incident_open, not_before = False, decision.resolved_at
    return events


# --- opening ---


def test_no_checks_decide_nothing():
    assert decide([], interval_seconds=INTERVAL, incident_open=False) is None


def test_one_failure_does_not_open_an_incident():
    assert decide(history("UF"), interval_seconds=INTERVAL, incident_open=False) is None


def test_two_failures_open_it_at_the_first_one():
    decision = decide(history("UFF"), interval_seconds=INTERVAL, incident_open=False)

    assert decision == OpenIncident(
        started_at=at(1), error_kind="http_error", status_code=503
    )


def test_a_longer_streak_starts_at_its_real_first_failure():
    # E.g. a late check filled a hole: the streak is already three long.
    decision = decide(history("UFFF"), interval_seconds=INTERVAL, incident_open=False)

    assert decision.started_at == at(1)


def test_the_cause_comes_from_the_first_failure():
    checks = [
        FakeCheck(at(1), False, "http_error", 503),
        FakeCheck(at(0), False, "timeout", None),
    ]

    decision = decide(checks, interval_seconds=INTERVAL, incident_open=False)

    assert (decision.error_kind, decision.status_code) == ("timeout", None)


def test_successes_without_an_incident_decide_nothing():
    assert (
        decide(history("FUU"), interval_seconds=INTERVAL, incident_open=False) is None
    )


def test_failures_while_open_decide_nothing():
    assert decide(history("FFF"), interval_seconds=INTERVAL, incident_open=True) is None


# --- closing ---


def test_one_success_does_not_close_it():
    assert decide(history("FFU"), interval_seconds=INTERVAL, incident_open=True) is None


def test_two_successes_close_it_at_the_first_one():
    decision = decide(history("FFUU"), interval_seconds=INTERVAL, incident_open=True)

    assert decision == ResolveIncident(resolved_at=at(2))


def test_a_failure_between_successes_keeps_it_open():
    assert (
        decide(history("FFUFU"), interval_seconds=INTERVAL, incident_open=True) is None
    )


# --- gaps (ADR-047's staleness limit: 2 x interval + 60 s) ---


@pytest.mark.parametrize(
    ("interval", "gap_seconds", "consecutive"),
    [
        (60, 180, True),  # exactly the limit
        (60, 181, False),  # one second more
        (30, 120, True),
        (30, 121, False),
    ],
)
def test_a_gap_breaks_a_failure_streak(interval, gap_seconds, consecutive):
    checks = [
        FakeCheck(T0 + timedelta(seconds=gap_seconds), False, "timeout"),
        FakeCheck(T0, False, "timeout"),
    ]

    decision = decide(checks, interval_seconds=interval, incident_open=False)

    assert (decision is not None) == consecutive


def test_a_gap_breaks_a_success_streak():
    checks = [
        FakeCheck(T0 + timedelta(seconds=181), True),
        FakeCheck(T0, True),
    ]

    assert decide(checks, interval_seconds=INTERVAL, incident_open=True) is None


# --- not_before: the previous incident's end ---


@pytest.mark.parametrize(
    ("not_before", "opens"),
    [
        (at(1), False),  # the older failure came before the previous incident ended
        (at(0), True),  # a check exactly at that time already counts
    ],
)
def test_a_streak_never_reaches_back_past_the_previous_incident(not_before, opens):
    decision = decide(
        history("FF"),
        interval_seconds=INTERVAL,
        incident_open=False,
        not_before=not_before,
    )

    assert (decision is not None) == opens


# --- whole sequences, check by check ---


def test_a_site_that_alternates_never_opens_an_incident():
    assert replay("FUFUFUFUFU") == []


def test_an_outage_opens_once_and_resolves_once():
    assert replay("UUFFFUUU") == [("opened", at(2)), ("resolved", at(5))]


def test_flapping_during_an_incident_keeps_it_open():
    assert replay("UFFUFUFUU") == [("opened", at(1)), ("resolved", at(7))]


def test_a_second_outage_opens_a_second_incident():
    assert replay("FFUUFF") == [
        ("opened", at(0)),
        ("resolved", at(2)),
        ("opened", at(4)),
    ]


def test_a_failed_check_without_error_kind_is_refused():
    # The checks table makes this impossible; never open an incident without cause.
    checks = [FakeCheck(at(1), False), FakeCheck(at(0), False)]

    with pytest.raises(ValueError, match="no error_kind"):
        decide(checks, interval_seconds=INTERVAL, incident_open=False)
