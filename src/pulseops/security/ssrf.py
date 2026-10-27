"""SSRF protection: refuse URLs that point inside private networks (ADR-023).

Reused by the checker (Phase 3), which must validate again on every check and
every redirect, because DNS answers can change after a monitor is created.
"""

import asyncio
import socket
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network

from pulseops.security.errors import UrlTargetNotAllowedError

DNS_TIMEOUT_SECONDS = 2.5

# ipaddress.is_global reports these as public, so they need explicit rules.
IPV4_COMPATIBLE = ip_network("::/96")  # deprecated, e.g. ::127.0.0.1
NAT64_WELL_KNOWN = ip_network("64:ff9b::/96")  # IPv4 in the last 32 bits
NAT64_LOCAL_USE = ip_network("64:ff9b:1::/48")  # IPv4 position not reliable

type IPAddress = IPv4Address | IPv6Address


def embedded_ipv4(address: IPv6Address) -> list[IPv4Address]:
    """IPv4 addresses hidden inside an IPv6 one, which must be checked too."""
    found = []
    if address.ipv4_mapped is not None:
        found.append(address.ipv4_mapped)
    if address.sixtofour is not None:
        found.append(address.sixtofour)
    if address.teredo is not None:
        found.append(address.teredo[1])  # the client address
    if address in NAT64_WELL_KNOWN:
        found.append(IPv4Address(int(address) & 0xFFFFFFFF))
    return found


def is_allowed_address(address: IPAddress) -> bool:
    """Public unicast only. Verified with tests rather than trusting is_global."""
    if not address.is_global or address.is_multicast:
        return False
    if isinstance(address, IPv6Address):
        if address in IPV4_COMPATIBLE or address in NAT64_LOCAL_USE:
            return False
        return all(is_allowed_address(inner) for inner in embedded_ipv4(address))
    return True


async def resolve_host(host: str) -> list[IPAddress] | None:
    """Resolve a hostname without blocking the event loop.

    Returns None when the name does not resolve or the lookup times out.
    getaddrinfo runs in a worker thread, which the timeout does not free.
    """
    loop = asyncio.get_running_loop()
    try:
        async with asyncio.timeout(DNS_TIMEOUT_SECONDS):
            infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (TimeoutError, OSError):
        return None
    return [ip_address(info[4][0]) for info in infos]


async def check_target(host: str, *, allow_private: bool) -> None:
    """Raise UrlTargetNotAllowedError if the host points anywhere not public.

    A name that does not resolve is accepted: the check will record a
    dns_error, and the checker validates again before every request.
    """
    if allow_private:
        return
    try:
        addresses = [ip_address(host)]
    except ValueError:
        addresses = await resolve_host(host)
        if addresses is None:
            return
    if not all(is_allowed_address(address) for address in addresses):
        raise UrlTargetNotAllowedError
