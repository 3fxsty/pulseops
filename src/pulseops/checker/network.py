"""TCP connections pinned to a validated IP: SSRF protection at connect time.

Every connection the checker opens (the first request and every redirect)
goes through `PinnedNetworkBackend.connect_tcp`, which resolves the host,
validates *all* the addresses and then connects to one of those same
addresses. Checking and connecting use one DNS answer, so a name cannot
switch to an internal IP in between (DNS rebinding). TLS still uses the
hostname for SNI and certificate validation (ADR-031).
"""

from collections.abc import Awaitable, Callable, Iterable
from ipaddress import ip_address

import httpcore2
import httpx2

from pulseops.security.ssrf import IPAddress, is_allowed_address, resolve_host

type Resolver = Callable[[str], Awaitable[list[IPAddress] | None]]
type AddressPolicy = Callable[[IPAddress], bool]


class NameResolutionError(Exception):
    """The host name did not resolve (or the lookup timed out)."""


class TargetBlockedError(Exception):
    """The host resolves to an address that must not be contacted."""


def address_policy(*, allow_private_targets: bool) -> AddressPolicy:
    if allow_private_targets:
        return lambda address: True
    return is_allowed_address


class PinnedNetworkBackend(httpcore2.AsyncNetworkBackend):
    def __init__(self, *, resolver: Resolver, policy: AddressPolicy) -> None:
        self._resolver = resolver
        self._policy = policy
        self._inner = httpcore2.AnyIOBackend()

    async def _addresses(self, host: str) -> list[IPAddress]:
        try:
            return [ip_address(host)]
        except ValueError:
            pass
        addresses = await self._resolver(host)
        if not addresses:
            raise NameResolutionError(host)
        return addresses

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        addresses = await self._addresses(host)
        # Same rule as the API: one disallowed address blocks the whole host.
        if not all(self._policy(address) for address in addresses):
            raise TargetBlockedError
        # Unique addresses in resolver order (e.g. IPv6 first, IPv4 fallback).
        *fallbacks, last = dict.fromkeys(addresses)
        for address in fallbacks:
            try:
                return await self._inner.connect_tcp(
                    str(address), port, timeout, local_address, socket_options
                )
            except (httpcore2.ConnectError, httpcore2.ConnectTimeout):
                continue
        return await self._inner.connect_tcp(
            str(last), port, timeout, local_address, socket_options
        )

    async def connect_unix_socket(self, *args, **kwargs):
        raise NotImplementedError("The checker only opens TCP connections")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class PinnedTransport(httpx2.AsyncHTTPTransport):
    """httpx2's transport, with every connection made by PinnedNetworkBackend.

    Built without proxies and without keep-alive: each check opens fresh
    connections, so it is validated and timed like a first-time visitor
    (ADR-035). Replacing `_pool` relies on an httpx2 internal; the checker
    tests fail loudly if a release changes it.
    """

    def __init__(
        self,
        *,
        resolver: Resolver = resolve_host,
        policy: AddressPolicy,
        verify: object = True,
    ) -> None:
        super().__init__(verify=verify, trust_env=False)
        self._pool = httpcore2.AsyncConnectionPool(
            ssl_context=httpx2.create_ssl_context(verify=verify, trust_env=False),
            max_connections=100,
            max_keepalive_connections=0,
            http1=True,
            http2=False,
            network_backend=PinnedNetworkBackend(resolver=resolver, policy=policy),
        )
