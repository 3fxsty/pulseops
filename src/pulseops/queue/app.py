from ardiq import Ardiq

from pulseops.config import get_settings

# ArdiQ keeps its default msgpack codec. Never pass a pickle-based
# serializer: a forged task payload could execute code in the worker.
app = Ardiq(
    redis_url=get_settings().broker_url.get_secret_value(),
    queue_name="pulseops",
)
