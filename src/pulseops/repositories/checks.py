from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pulseops.checker import CheckOutcome
from pulseops.db.models import Check

MONITOR_FOREIGN_KEY = "fk_checks_monitor_id_monitors"


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
