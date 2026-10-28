"""Measure the history, stats and retention queries on realistic data.

    uv run python scripts/measure_queries.py [--plans] [--monitors N]
        [--days N] [--interval SECONDS]

Runs against the TEST database (TEST_DATABASE_URL, never development data).
By default: 10 monitors x 31 days of checks every 30 s (~893,000 rows),
inserted in time order as the worker would. Whatever is older than 30 days
is past retention (the first day, by default).

For each query it prints the plan's access path, EXPLAIN ANALYZE's execution
time and the median of 20 real runs. The queries are the repository's own
statements, not copies. Everything it creates is deleted at the end.
"""

import argparse
import asyncio
import statistics
import time
import uuid
from datetime import timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import (
    ClauseElement,
    Executable,
    case,
    delete,
    func,
    insert,
    select,
    text,
    true,
)
from sqlalchemy import Integer as SqlInteger
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from pulseops.db.models import Check, Monitor
from pulseops.repositories.checks import (
    check_stats,
    expired_batch_statement,
    history_statement,
    list_checks,
    stats_statement,
)
from pulseops.retention import BATCH_SIZE, RETENTION, purge_expired_checks

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MONITORS = 10
DEFAULT_DAYS = 31
DEFAULT_INTERVAL_SECONDS = 30
RUNS = 20


class MeasureSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    test_database_url: SecretStr  # pulseops_app on pulseops_test
    test_migration_database_url: SecretStr  # pulseops_owner on pulseops_test


class Explain(Executable, ClauseElement):
    """EXPLAIN (ANALYZE, BUFFERS) around a statement, keeping its bound params."""

    inherit_cache = False

    def __init__(self, statement) -> None:
        self.statement = statement


@compiles(Explain, "postgresql")
def _compile_explain(element, compiler, **kw):
    return "EXPLAIN (ANALYZE, BUFFERS) " + compiler.process(element.statement, **kw)


async def explain(engine, statement) -> list[str]:
    """The plan of a real run. Rolled back, so a DELETE deletes nothing."""
    async with engine.connect() as connection:
        rows = await connection.execute(Explain(statement))
        plan = [row[0] for row in rows]
        await connection.rollback()
    return plan


def execution_ms(plan: list[str]) -> float:
    line = next(line for line in plan if line.startswith("Execution Time"))
    return float(line.split(":")[1].split()[0])


def access_path(plan: list[str]) -> str:
    """Scans on `checks`, e.g. "Index Scan … pk_checks" or "Seq Scan"."""
    scans = []
    for line in plan:
        stripped = line.strip().removeprefix("->").strip()
        if "Scan" in stripped and ("checks" in stripped or "pk_checks" in stripped):
            scans.append(stripped.split("  (")[0])
    return "; ".join(dict.fromkeys(scans)) or "?"


async def median_ms(run, runs: int = RUNS) -> float:
    timings = []
    for _ in range(runs):
        started = time.perf_counter()
        await run()
        timings.append((time.perf_counter() - started) * 1000)
    return statistics.median(timings)


async def seed(
    sessions, owner_engine, *, monitors: int, days: int, interval: timedelta
) -> list[int]:
    async with sessions() as session:
        created = [
            Monitor(
                name=f"measure-{n}",
                url=f"https://measure-{uuid.uuid4()}.invalid/",
                interval_seconds=int(interval.total_seconds()),
                is_active=False,
            )
            for n in range(monitors)
        ]
        session.add_all(created)
        await session.commit()
        ids = [monitor.id for monitor in created]

        # Every monitor at every 30 s slot, oldest first (the worker's order,
        # which is what makes a BRIN index on scheduled_at useful).
        slots = (
            select(
                func.generate_series(
                    func.now() - timedelta(days=days), func.now(), interval
                ).label("at")
            )
        ).subquery("slots")
        measured = (
            select(Monitor.id.label("monitor_id"))
            .where(Monitor.id.in_(ids))
            .subquery("measured")
        )
        seconds = int(interval.total_seconds())
        step = func.floor(func.extract("epoch", slots.c.at) / seconds)
        down = (step % 997) == 0  # about 0.1 % of checks down
        rows = (
            select(
                measured.c.monitor_id,
                slots.c.at,
                ~down,
                case((down, None), else_=200),
                case((down, None), else_=(80 + step % 300).cast(SqlInteger)),
                case((down, "timeout"), else_=None),
            )
            # Every monitor with every slot.
            .select_from(measured.join(slots, true()))
            .order_by(slots.c.at, measured.c.monitor_id)
        )
        await session.execute(
            insert(Check).from_select(
                [
                    "monitor_id",
                    "scheduled_at",
                    "is_up",
                    "status_code",
                    "response_time_ms",
                    "error_kind",
                ],
                rows,
            )
        )
        await session.commit()

    # Planner statistics, as autovacuum would gather them (the app role may
    # not ANALYZE: only the table owner can).
    async with owner_engine.connect() as connection:
        await connection.execute(text("ANALYZE checks"))
        await connection.commit()
    return ids


async def main(show_plans: bool, monitors: int, days: int, interval: timedelta) -> None:
    settings = MeasureSettings()
    config = Config(ROOT / "alembic.ini")
    config.attributes["database_url"] = (
        settings.test_migration_database_url.get_secret_value()
    )
    await asyncio.to_thread(command.upgrade, config, "head")

    engine = create_async_engine(settings.test_database_url.get_secret_value())
    owner_engine = create_async_engine(
        settings.test_migration_database_url.get_secret_value()
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    ids: list[int] = []
    try:
        started = time.perf_counter()
        ids = await seed(
            sessions, owner_engine, monitors=monitors, days=days, interval=interval
        )
        async with sessions() as session:
            total = await session.scalar(select(func.count()).select_from(Check))
            expired = await session.scalar(
                select(func.count())
                .select_from(Check)
                .where(Check.scheduled_at < func.now() - RETENTION)
            )
        print(
            f"Seeded {total:,} checks ({monitors} monitors x {days} days every "
            f"{interval.seconds} s; {expired:,} past retention) in "
            f"{time.perf_counter() - started:.1f} s\n"
        )

        monitor_id = ids[0]
        async with sessions() as session:
            middle = (await session.scalar(select(func.now()))) - timedelta(days=15)

        async def run_stats(period):
            async with sessions() as session:
                await check_stats(session, monitor_id=monitor_id, period=period)

        async def run_history(before):
            async with sessions() as session:
                await list_checks(
                    session, monitor_id=monitor_id, limit=51, before=before
                )

        cases = [
            (
                "stats, 30d",
                stats_statement(monitor_id=monitor_id, period=timedelta(days=30)),
                lambda: run_stats(timedelta(days=30)),
            ),
            (
                "stats, 7d",
                stats_statement(monitor_id=monitor_id, period=timedelta(days=7)),
                lambda: run_stats(timedelta(days=7)),
            ),
            (
                "history, first page (50)",
                history_statement(monitor_id=monitor_id, limit=51),
                lambda: run_history(None),
            ),
            (
                "history, page 15 days back",
                history_statement(monitor_id=monitor_id, limit=51, before=middle),
                lambda: run_history(middle),
            ),
            (
                f"retention batch ({BATCH_SIZE:,}), backlog",
                expired_batch_statement(retention=RETENTION, batch_size=BATCH_SIZE),
                None,
            ),
            (
                "retention batch, hourly steady state",
                expired_batch_statement(
                    retention=timedelta(days=days) - timedelta(hours=1),
                    batch_size=BATCH_SIZE,
                ),
                None,
            ),
        ]

        print(f"{'query':40} {'EXPLAIN ms':>10} {'median ms':>10}  access path")
        for name, statement, run in cases:
            plan = await explain(engine, statement)
            real = f"{await median_ms(run):10.2f}" if run else f"{'—':>10}"
            print(f"{name:40} {execution_ms(plan):10.2f} {real}  {access_path(plan)}")
            if show_plans:
                print("\n".join("    " + line for line in plan) + "\n")

        started = time.perf_counter()
        purged = await purge_expired_checks(sessions)
        elapsed = time.perf_counter() - started
        batches = max(1, -(-purged // BATCH_SIZE))
        print(
            f"\nFull retention run: deleted {purged:,} expired checks in "
            f"{elapsed:.2f} s ({batches} batches, {elapsed / batches * 1000:.1f} ms "
            "per batch)"
        )
    finally:
        if ids:
            async with sessions() as session:
                await session.execute(delete(Monitor).where(Monitor.id.in_(ids)))
                await session.commit()
        await engine.dispose()
        await owner_engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plans", action="store_true", help="print full plans")
    parser.add_argument("--monitors", type=int, default=DEFAULT_MONITORS)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument(
        "--interval", type=int, default=DEFAULT_INTERVAL_SECONDS, help="seconds"
    )
    args = parser.parse_args()
    asyncio.run(
        main(args.plans, args.monitors, args.days, timedelta(seconds=args.interval))
    )
