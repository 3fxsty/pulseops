from ardiq import Ardiq

from pulseops.config import BrokerSettings

# ArdiQ keeps its default msgpack codec. Never pass a pickle-based
# serializer: a forged task payload could execute code in the worker.
app = Ardiq(
    redis_url=BrokerSettings().broker_url.get_secret_value(),
    queue_name="pulseops",
)
