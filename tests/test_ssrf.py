import asyncio
import socket
from ipaddress import ip_address

import pytest

from pulseops.security import ssrf
from pulseops.security.errors import (
    UrlCredentialsNotAllowedError,
    UrlTargetNotAllowedError,
)
from pulseops.security.ssrf import check_target, is_allowed_address, resolve_host
from pulseops.security.validation import ValidatedUrl, validate_monitor_url

ALLOWED = [
    "8.8.8.8",
    "2001:4860:4860::8888",
    "::ffff:8.8.8.8",  # IPv4-mapped public address
    "64:ff9b::808:808",  # NAT64 wrapping 8.8.8.8 (IPv6-only VPS with DNS64)
]

BLOCKED = [
    "127.0.0.1",
    "10.0.0.5",
    "192.168.1.1",
    "169.254.169.254",  # cloud metadata
    "100.64.0.1",  # CGNAT
    "0.0.0.0",  # noqa: S104 (an address under test, not a bind)
    "255.255.255.255",
    "224.0.0.1",  # multicast: is_global is True
    "::1",
    "fe80::1",
    "fc00::1",
    "ff02::1",  # IPv6 multicast: is_global is True
    "::ffff:127.0.0.1",  # IPv4-mapped
    "2002:7f00:1::",  # 6to4 wrapping 127.0.0.1
    "2002:808:808::",  # 6to4 is blocked whole, even wrapping a public IPv4
    "64:ff9b::7f00:1",  # NAT64 wrapping 127.0.0.1: is_global is True
    "64:ff9b:1::1",  # NAT64 local-use range, blocked whole
    "64:ff9b:1::808:808",
    "2001:0:4136:e378:8000:63bf:3fff:fdd2",  # Teredo
    "::127.0.0.1",  # IPv4-compatible: is_global is True
]


@pytest.mark.parametrize("address", ALLOWED)
def test_public_addresses_are_allowed(address):
    assert is_allowed_address(ip_address(address))


@pytest.mark.parametrize("address", BLOCKED)
def test_internal_addresses_are_blocked(address):
    assert not is_allowed_address(ip_address(address))


@pytest.mark.parametrize("address", ["224.0.0.1", "64:ff9b::7f00:1", "::127.0.0.1"])
def test_is_global_alone_is_not_enough(address):
    # Documents why the extra rules exist: Python calls these "global".
    assert ip_address(address).is_global


# --- check_target ---


@pytest.mark.anyio
async def test_literal_internal_ip_is_rejected():
    with pytest.raises(UrlTargetNotAllowedError):
        await check_target("169.254.169.254", allow_private=False)


@pytest.mark.anyio
async def test_name_is_rejected_if_any_address_is_internal(fake_dns):
    fake_dns["mixed.example"] = ["8.8.8.8", "10.0.0.1"]

    with pytest.raises(UrlTargetNotAllowedError):
        await check_target("mixed.example", allow_private=False)


@pytest.mark.anyio
async def test_name_with_only_public_addresses_is_accepted(fake_dns):
    fake_dns["public.example"] = ["8.8.8.8", "2001:4860:4860::8888"]

    await check_target("public.example", allow_private=False)


@pytest.mark.anyio
async def test_unresolvable_name_is_accepted(fake_dns):
    fake_dns["not-yet-live.example"] = None

    await check_target("not-yet-live.example", allow_private=False)


@pytest.mark.anyio
async def test_allow_private_targets_disables_the_block():
    await check_target("127.0.0.1", allow_private=True)


@pytest.mark.anyio
async def test_error_never_reveals_the_address(fake_dns):
    fake_dns["internal.example"] = ["10.1.2.3"]

    with pytest.raises(UrlTargetNotAllowedError) as error:
        await check_target("internal.example", allow_private=False)

    assert "10.1.2.3" not in str(error.value)


# --- resolve_host ---


@pytest.mark.anyio
async def test_resolve_returns_none_when_lookup_fails(monkeypatch):
    async def failing(*args, **kwargs):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", failing)

    assert await resolve_host("nowhere.example") is None


@pytest.mark.anyio
async def test_resolve_returns_none_on_timeout(monkeypatch):
    async def hanging(*args, **kwargs):
        await asyncio.sleep(10)

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", hanging)
    monkeypatch.setattr(ssrf, "DNS_TIMEOUT_SECONDS", 0.01)

    assert await resolve_host("slow.example") is None


# --- validate_monitor_url: disguised internal URLs ---


@pytest.mark.anyio
@pytest.mark.parametrize(
    "url",
    [
        "http://0x7f.1/",
        "http://2130706433/",
        "http://[::ffff:127.0.0.1]/",
        "http://localhost./",
        "http://169.254.169.254/latest/meta-data/",
    ],
)
async def test_disguised_internal_urls_are_rejected(fake_dns, url):
    fake_dns["localhost"] = ["127.0.0.1"]

    with pytest.raises(UrlTargetNotAllowedError):
        await validate_monitor_url(url, allow_private_targets=False)


@pytest.mark.anyio
async def test_userinfo_trick_is_rejected_as_credentials(fake_dns):
    with pytest.raises(UrlCredentialsNotAllowedError):
        await validate_monitor_url(
            "http://example.com@127.0.0.1/", allow_private_targets=False
        )


# --- ValidatedUrl ---


@pytest.mark.anyio
async def test_validation_returns_normalized_validated_url(fake_dns):
    url = await validate_monitor_url(
        "HTTPS://Example.com#top", allow_private_targets=False
    )

    assert isinstance(url, ValidatedUrl)
    assert url.value == "https://example.com/"


def test_validated_url_cannot_be_built_directly():
    with pytest.raises(TypeError):
        ValidatedUrl("http://127.0.0.1/", _token=object())


@pytest.mark.anyio
async def test_validated_url_is_immutable(fake_dns):
    url = await validate_monitor_url("https://example.com", allow_private_targets=False)

    with pytest.raises(AttributeError):
        url._value = "http://127.0.0.1/"
