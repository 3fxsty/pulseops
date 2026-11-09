"""What every alert channel offers (ADR-064)."""

from typing import Protocol


class DeliveryError(Exception):
    """An alert did not reach its channel.

    Safe to log as it is: it never carries a token, a URL or the channel's
    answer, only why it failed.
    """

    def __init__(
        self,
        reason: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
        problem: str | None = None,
    ) -> None:
        self.reason = reason
        self.status_code = status_code
        # Seconds the channel asked us to wait before trying again (a 429).
        self.retry_after = retry_after
        # Set only when retrying cannot help (ADR-063): what a person must fix.
        self.problem = problem
        details = []
        if status_code is not None:
            details.append(f"HTTP {status_code}")
        if retry_after is not None:
            details.append(f"retry after {retry_after:g} s")
        message = f"{reason} ({', '.join(details)})" if details else reason
        super().__init__(f"{message}: {problem}" if problem else message)

    @property
    def permanent(self) -> bool:
        """The same answer would come back on every retry."""
        return self.problem is not None


class Notifier(Protocol):
    async def send(self, text: str) -> None:
        """Deliver one plain-text message, or raise DeliveryError."""
        ...
