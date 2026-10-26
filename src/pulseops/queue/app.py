import os

from ardiq import Ardiq

BROKER_URL = os.environ.get("BROKER_URL", "redis://localhost:6379/0")

app = Ardiq(redis_url=BROKER_URL, queue_name="pulseops")
