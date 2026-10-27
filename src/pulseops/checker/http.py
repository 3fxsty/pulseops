"""Visit a URL and decide whether it is up (ADR-003, ADR-031 to ADR-037)."""

import asyncio
import ssl
import time
from importlib.metadata import version
from typing import Self

import httpx2

from pulseops.checker.network import (
    AddressPolicy,
    NameResolutionError,
    PinnedTransport,
    Resolver,
    TargetBlockedError,
    address_policy,
)
from pulseops.checker.outcome import CheckOutcome, down, up
from pulseops.security.ssrf import resolve_host

# Business rule: a site that takes more than 10 s is down. One deadline
# covers DNS, connecting, TLS, every redirect and the final headers.
CHECK_DEADLINE_SECONDS = 10.0
MAX_REDIRECTS = 5
USER_AGENT = f"PulseOps/{version('pulseops')} (uptime monitor)"


def _is_ssl_failure(error: BaseException) -> bool:
    """httpx2 reports TLS failures as ConnectError; the cause tells them apart."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        if isinstance(current, ssl.SSLError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def _describe(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}" if str(error) else type(error).__name__


class Checker:
    """Reusable checker: one HTTP client (shared TLS setup) for many checks.

    Each check still opens fresh connections (no keep-alive), so every one is
    SSRF-validated and timed like a first visit.
    """

    def __init__(
        self,
        *,
        allow_private_targets: bool,
        deadline: float = CHECK_DEADLINE_SECONDS,
        resolver: Resolver = resolve_host,
        policy: AddressPolicy | None = None,
        verify: ssl.SSLContext | bool = True,
    ) -> None:
        self._deadline = deadline
        policy = policy or address_policy(allow_private_targets=allow_private_targets)
        self._client = httpx2.AsyncClient(
            transport=PinnedTransport(resolver=resolver, policy=policy, verify=verify),
            # Ignore HTTP(S)_PROXY: through a proxy, SSRF checks would apply to
            # the proxy's address instead of the target's (ADR-031).
            trust_env=False,
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            timeout=httpx2.Timeout(deadline),
            headers={"User-Agent": USER_AGENT},
        )

    async def check(self, url: str) -> CheckOutcome:
        started = time.perf_counter()
        try:
            async with asyncio.timeout(self._deadline):
                # stream() returns once the final response's headers arrive;
                # leaving the block closes it without downloading the body.
                async with self._client.stream("GET", url) as response:
                    status = response.status_code
                    elapsed_ms = round((time.perf_counter() - started) * 1000)
        except (TimeoutError, httpx2.TimeoutException):
            return down("timeout", f"No response within {self._deadline:g} s")
        except TargetBlockedError:
            # Never reveal which address was refused.
            return down("blocked_target", "The URL points to a blocked destination")
        except NameResolutionError:
            return down("dns_error", "The host name did not resolve")
        except httpx2.TooManyRedirects:
            return down("http_error", f"More than {MAX_REDIRECTS} redirects")
        except httpx2.UnsupportedProtocol:
            return down("http_error", "Redirect to a scheme other than http or https")
        except httpx2.TransportError as error:
            kind = "ssl_error" if _is_ssl_failure(error) else "connection_error"
            return down(kind, _describe(error))

        if status >= 400:
            return down(
                "http_error",
                f"HTTP {status}",
                status_code=status,
                response_time_ms=elapsed_ms,
            )
        return up(status, elapsed_ms)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()


async def check_url(url: str, *, allow_private_targets: bool) -> CheckOutcome:
    """One-off check. Long-running callers should reuse a Checker instead."""
    async with Checker(allow_private_targets=allow_private_targets) as checker:
        return await checker.check(url)
