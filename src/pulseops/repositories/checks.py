from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Delete, Select, any_, column, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pulseops.checker import CheckOutcome
from pulseops.db.models import Check

MONITOR_FOREIGN_KEY = "fk_checks_monitor_id_monitors"
# A row's physical address in the table (PostgreSQL system column).
CTID = column("ctid")


@dataclass(frozen=True, slots=True)
class CheckStats:
    since: datetime
    until: datetime
    total: int
    up: int
    # Latency of the checks that were up only: timeouts have no time, and a
    # 500 answered in 5 ms would flatter a broken site. None without data.
    avg_response_time_ms: float | None
    p95_response_time_ms: float | None


async def record_check(
    session: AsyncSession,
    *,
    monitor_id: int,
    scheduled_at: datetime,
    outcome: CheckOutcome,
) -> bool:
    """Store one check. Returns False if nothing was stored.

    Idempotent: the queue delivers at least once, so the same check
    (monitor_id, scheduled_at) may arrive twice; the second is a no-op
    (ON CONFLICT DO NOTHING on the primary key). A monitor deleted while its
    check was running is not an error either: there is nothing to record.
    """
    statement = (
        insert(Check)
        .values(
            monitor_id=monitor_id,
            scheduled_at=scheduled_at,
            is_up=outcome.is_up,
            status_code=outcome.status_code,
            response_time_ms=outcome.response_time_ms,
            error_kind=outcome.error_kind,
            error_detail=outcome.error_detail,
        )
        .on_conflict_do_nothing()
        .returning(Check.monitor_id)
    )
    try:
        stored = await session.scalar(statement)
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        constraint = getattr(error.orig.__cause__, "constraint_name", None)
        if constraint == MONITOR_FOREIGN_KEY:
            return False
        raise
    return stored is not None


# The statements are built apart from running them, so that
# scripts/measure_queries.py can EXPLAIN exactly the SQL the API runs.


def history_statement(
    *, monitor_id: int, limit: int, before: datetime | None = None
) -> Select:
    query = select(Check).where(Check.monitor_id == monitor_id)
    if before is not None:
        query = query.where(Check.scheduled_at < before)
    return query.order_by(Check.scheduled_at.desc()).limit(limit)


def stats_statement(*, monitor_id: int, period: timedelta) -> Select:
    since = func.now() - period
    is_up = Check.is_up.is_(True)
    return select(
        since,
        func.now(),
        func.count(),
        func.count().filter(is_up),
        func.avg(Check.response_time_ms).filter(is_up),
        func.percentile_cont(0.95).within_group(Check.response_time_ms).filter(is_up),
    ).where(Check.monitor_id == monitor_id, Check.scheduled_at >= since)


def expired_batch_statement(*, retention: timedelta, batch_size: int) -> Delete:
    """Delete by physical row address (ctid), never by joining on the key.

    The inner SELECT finds one batch of expired rows (through the BRIN index
    on scheduled_at, or the primary key when PostgreSQL finds it cheaper) and
    ARRAY() turns their addresses into a list, computed once. The DELETE then
    visits exactly those addresses (a TID scan). Joining on (monitor_id,
    scheduled_at) instead let the planner pick a hash join over a full table
    scan for some statistics samples: every batch would read the whole table.
    """
    cutoff = func.now() - retention
    expired = (
        select(CTID)
        .select_from(Check.__table__)
        .where(Check.scheduled_at < cutoff)
        .limit(batch_size)
        .scalar_subquery()
    )
    return delete_at_addresses_statement(func.array(expired), older_than=cutoff)


def delete_at_addresses_statement(addresses, *, older_than) -> Delete:
    """Delete the rows at these addresses, but only if they are still expired.

    Selection and deletion run in one statement, so an address cannot be
    reused in between; the date is checked again anyway (defence in depth):
    an address that pointed at a recent check would delete nothing.
    """
    return delete(Check).where(CTID == any_(addresses), Check.scheduled_at < older_than)


async def list_checks(
    session: AsyncSession,
    *,
    monitor_id: int,
    limit: int,
    before: datetime | None = None,
) -> Sequence[Check]:
    """Newest first, strictly older than `before` (keyset pagination).

    Unlike OFFSET, a page never shifts when new checks arrive meanwhile, and
    it reads only `limit` rows from the primary key index.
    """
    query = history_statement(monitor_id=monitor_id, limit=limit, before=before)
    return (await session.scalars(query)).all()


async def latest_check(session: AsyncSession, monitor_id: int) -> Check | None:
    checks = await list_checks(session, monitor_id=monitor_id, limit=1)
    return checks[0] if checks else None


async def check_stats(
    session: AsyncSession, *, monitor_id: int, period: timedelta
) -> CheckStats:
    """Counts and latency over the last `period`, in one query.

    The window ends at the database's now(), the same clock that stamps
    scheduled_at.
    """
    query = stats_statement(monitor_id=monitor_id, period=period)
    since_at, until, total, up, avg, p95 = (await session.execute(query)).one()
    return CheckStats(
        since=since_at,
        until=until,
        total=total,
        up=up,
        avg_response_time_ms=None if avg is None else float(avg),
        p95_response_time_ms=None if p95 is None else float(p95),
    )


async def delete_expired_checks(
    session: AsyncSession, *, retention: timedelta, batch_size: int
) -> int:
    """Delete one batch of checks older than `retention`, commit, return how many.

    Small batches keep each transaction (and its locks) short; the caller
    loops until a batch comes back smaller than `batch_size`.
    """
    statement = expired_batch_statement(retention=retention, batch_size=batch_size)
    result = await session.execute(statement)
    await session.commit()
    return result.rowcount
