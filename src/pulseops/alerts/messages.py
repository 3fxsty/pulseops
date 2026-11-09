"""What an alert says (ADR-065).

Never the monitor's URL nor the error_detail: a URL may carry tokens, and
Telegram is an outside service that keeps the messages. IncidentSummary has no
field for either, so they cannot slip in.
"""

import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

TEST_MESSAGE = "✅ PulseOps test message: alerts reach this chat."

_UNITS = (("d", 86400), ("h", 3600), ("min", 60), ("s", 1))


@dataclass(frozen=True, slots=True)
class IncidentSummary:
    monitor_name: str
    monitor_id: UUID  # the public id, as in the API
    started_at: datetime
    error_kind: str
    status_code: int | None
    resolved_at: datetime | None = None


def alert_text(kind: str, incident: IncidentSummary) -> str:
    if kind == "opened":
        return "\n".join(
            [
                f"🔴 DOWN: {_one_line(incident.monitor_name)}",
                f"Since: {_utc(incident.started_at)}",
                f"Cause: {_cause(incident)}",
                f"Monitor: {incident.monitor_id}",
            ]
        )
    if kind == "resolved" and incident.resolved_at is not None:
        down_for = _duration(incident.resolved_at - incident.started_at)
        return "\n".join(
            [
                f"✅ RECOVERED: {_one_line(incident.monitor_name)}",
                f"Down for {down_for}, since {_utc(incident.started_at)}",
                f"Cause: {_cause(incident)}",
                f"Monitor: {incident.monitor_id}",
            ]
        )
    raise ValueError(f"no alert text for {kind!r}")


def _one_line(name: str) -> str:
    """A monitor's name on one line: a line break in it could fake a line of
    the alert, such as a "RECOVERED" that never happened."""
    return "".join(
        " " if unicodedata.category(char) in {"Cc", "Zl", "Zp"} else char
        for char in name
    )


def _utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _cause(incident: IncidentSummary) -> str:
    if incident.status_code is None:
        return incident.error_kind
    return f"{incident.error_kind} (HTTP {incident.status_code})"


def _duration(span: timedelta) -> str:
    """Two units at most, starting at the largest: "1 h 5 min", "45 s"."""
    remaining = max(int(span.total_seconds()), 0)
    parts = []
    for unit, seconds in _UNITS:
        amount, remaining = divmod(remaining, seconds)
        if amount or parts:
            parts.append((amount, unit))
        if len(parts) == 2:
            break
    shown = [f"{amount} {unit}" for amount, unit in parts if amount]
    return " ".join(shown) or "0 s"
