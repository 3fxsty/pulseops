from ardiq import Ardiq

from pulseops.config import BrokerSettings

# Checks wait on the network, not the CPU, so many run at once.
CONCURRENCY = 32
CHECKS_LANE = "checks"
SCHEDULER_LANE = "scheduler"

# ArdiQ keeps its default msgpack codec. Never pass a pickle-based
# serializer: a forged task payload could execute code in the worker.
app = Ardiq(
    redis_url=BrokerSettings().broker_url.get_secret_value(),
    queue_name="pulseops",
    # Lowest priority first: the scheduler's tick is picked up before checks.
    priorities=[CHECKS_LANE, SCHEDULER_LANE],
    default_priority=CHECKS_LANE,
    concurrency=CONCURRENCY,
    # Checks never take the last slot, so slow checks (up to 10 s each)
    # cannot keep the scheduler waiting.
    limits={CHECKS_LANE: CONCURRENCY - 1},
)
