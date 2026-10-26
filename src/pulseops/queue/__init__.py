"""Task queue layer.

Everything ArdiQ-specific lives in this package so the queue can be swapped
without touching the rest of the codebase.
"""

from pulseops.queue.app import app

__all__ = ["app"]
