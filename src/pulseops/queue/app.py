from ardiq import Ardiq

from pulseops.config import BrokerSettings

# Checks wait on the network, not the CPU, so many run at once.
CONCURRENCY = 32
CHECKS_LANE = "checks"
MAINTENANCE_LANE = "maintenance"
ALERTS_LANE = "alerts"
SCHEDULER_LANE = "scheduler"
# Slots per lane. Checks (29) + maintenance (1) + alerts (1) always leave at
# least one slot for the scheduler, so neither slow checks, a long cleanup nor
# a slow alert delays its tick (ADR-051, ADR-070).
LANE_LIMITS = {CHECKS_LANE: CONCURRENCY - 3, MAINTENANCE_LANE: 1, ALERTS_LANE: 1}


def build_app(redis_url: str, queue_name: str) -> Ardiq:
    """The queue as the worker runs it; tests build one on a throwaway queue."""
    # ArdiQ keeps its default msgpack codec. Never pass a pickle-based
    # serializer: a forged task payload could execute code in the worker.
    return Ardiq(
        redis_url=redis_url,
        queue_name=queue_name,
        # Lowest priority first: the scheduler's tick is picked up first.
        priorities=[CHECKS_LANE, MAINTENANCE_LANE, ALERTS_LANE, SCHEDULER_LANE],
        default_priority=CHECKS_LANE,
        concurrency=CONCURRENCY,
        limits=LANE_LIMITS,
    )


app = build_app(BrokerSettings().broker_url.get_secret_value(), "pulseops")
