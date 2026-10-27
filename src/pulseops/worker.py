"""Worker entry point: `ardiq run pulseops.worker:app`.

Importing the tasks registers them (and the scheduler's cron) on the app.
"""

from pulseops.queue import tasks
from pulseops.queue.app import app

__all__ = ["app", "tasks"]
