"""Telegram's Bot API, called directly with httpx2 (ADR-064).

The bot only sends: it never receives messages, so nothing listens for
Telegram. The token travels in the URL path (/bot<token>/sendMessage), so the
URL, the exceptions httpx2 raises and Telegram's answers are never logged.
"""

import asyncio
import logging
from typing import Self

import httpx2
from pydantic import SecretStr

from pulseops.alerts.notifier import DeliveryError

# Fixed on purpose (ADR-064): no setting or environment variable can send the
# bot token to another server. Tests pass a fake transport instead.
TELEGRAM_API_URL = "https://api.telegram.org"
# One total deadline per send, well inside the 60 s lease of a claimed alert
# (ADR-063). httpx2's own timeouts apply per phase and could add up to more.
SEND_DEADLINE_SECONDS = 10.0

# What a permanent answer means, for the worker's ERROR line (ADR-063). 401 and
# 404 checked against the real Bot API with made-up tokens.
PERMANENT_PROBLEMS = {
    400: "Telegram rejected the message (for example, the chat does not exist)",
    401: "the bot token is not valid",
    403: "the bot cannot write to the chat (blocked, or removed from it)",
    404: "the bot token is not valid (malformed)",
}
UNEXPECTED_ANSWER = "Telegram refused the alert"

# httpx2 logs every request URL at INFO, and here the URL holds the token.
for _name in ("httpx2", "httpcore2"):
    logging.getLogger(_name).setLevel(logging.WARNING)


class TelegramNotifier:
    """Sends plain-text messages to one chat. One HTTP client per worker."""

    def __init__(
        self,
        *,
        token: SecretStr,
        chat_id: str,
        deadline: float = SEND_DEADLINE_SECONDS,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = token
        self._chat_id = chat_id
        self._deadline = deadline
        self._client = httpx2.AsyncClient(
            transport=transport,
            # Proxy variables are ignored: the token goes to Telegram only.
            trust_env=False,
            follow_redirects=False,
            timeout=httpx2.Timeout(deadline),
        )

    async def send(self, text: str) -> None:
        url = f"{TELEGRAM_API_URL}/bot{self._token.get_secret_value()}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            # Plain text (no parse_mode): a monitor's name cannot change the
            # message's format or add links.
            "text": text,
            "link_preview_options": {"is_disabled": True},
        }
        try:
            async with asyncio.timeout(self._deadline):
                response = await self._client.post(url, json=payload)
        # `from None`: the original exception may quote the URL, token included.
        except (TimeoutError, httpx2.TimeoutException):
            raise DeliveryError("timeout") from None
        except httpx2.HTTPError:
            raise DeliveryError("connection_error") from None

        status = response.status_code
        if status == 429:
            raise DeliveryError(
                "rate_limited", status_code=429, retry_after=_retry_after(response)
            )
        if status >= 500:
            # Telegram's side: worth trying again.
            raise DeliveryError("http_error", status_code=status)
        if status != 200 or not _answered_ok(response):
            # Any other answer would come back the same on every retry.
            raise DeliveryError(
                "http_error",
                status_code=status,
                problem=PERMANENT_PROBLEMS.get(status, UNEXPECTED_ANSWER),
            )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


def _answer(response: httpx2.Response) -> dict:
    try:
        answer = response.json()
    except ValueError:
        return {}
    return answer if isinstance(answer, dict) else {}


def _answered_ok(response: httpx2.Response) -> bool:
    return _answer(response).get("ok") is True


def _retry_after(response: httpx2.Response) -> float | None:
    """How long Telegram asks us to wait: its JSON answer, else the header."""
    parameters = _answer(response).get("parameters")
    candidates = [
        parameters.get("retry_after") if isinstance(parameters, dict) else None,
        response.headers.get("Retry-After"),
    ]
    for value in candidates:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            continue
        if seconds > 0:
            return seconds
    return None
