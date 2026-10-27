"""The checker against real local HTTP(S) servers (no mocked transport).

Loopback servers would be blocked by the real SSRF policy, so most tests use
allow_private_targets=True or a test policy; the policy itself is covered by
the blocked_target tests and by test_ssrf.py.
"""

import asyncio
import dataclasses
import json
import logging
import socket
import ssl
import time
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from ipaddress import ip_address
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
import trustme

from pulseops.checker import Checker, CheckOutcome
from pulseops.checker import __main__ as cli
from pulseops.checker.http import MAX_REDIRECTS

pytestmark = pytest.mark.anyio

LOOPBACK = ip_address("127.0.0.1")


class LocalServer:
    """Minimal HTTP/1.1 server with a few routes, recording every request."""

    def __init__(self, ssl_context: ssl.SSLContext | None = None) -> None:
        self.ssl_context = ssl_context
        self.requests: list[dict[str, str]] = []
        self.port = 0
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle, "127.0.0.1", 0, ssl=self.ssl_context
        )
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        self._server.close()
        # Cut deliberately hanging connections (/slow, /headers-only) instead
        # of waiting for them to finish.
        self._server.close_clients()
        await self._server.wait_closed()

    def url(self, path: str, host: str = "127.0.0.1") -> str:
        scheme = "https" if self.ssl_context else "http"
        return f"{scheme}://{host}:{self.port}{path}"

    async def _handle(self, reader, writer) -> None:
        try:
            request_line = (await reader.readline()).decode()
            headers = {}
            while (line := (await reader.readline()).decode().strip()) != "":
                name, _, value = line.partition(":")
                headers[name.strip().lower()] = value.strip()
            target = request_line.split(" ")[1]
            self.requests.append({"target": target, **headers})
            await self._route(urlsplit(target), writer)
        except (ConnectionError, ssl.SSLError, IndexError):
            pass
        finally:
            writer.close()

    async def _route(self, target, writer) -> None:
        path, query = target.path, parse_qs(target.query)
        if path == "/ok":
            await self._respond(writer, 200)
        elif path.startswith("/status/"):
            await self._respond(writer, int(path.rsplit("/", 1)[1]))
        elif path == "/slow":
            await asyncio.sleep(5)
            await self._respond(writer, 200)
        elif path.startswith("/redirect/"):
            remaining = int(path.rsplit("/", 1)[1])
            if remaining == 0:
                await self._respond(writer, 200)
            else:
                await self._redirect(writer, f"/redirect/{remaining - 1}")
        elif path == "/loop":
            await self._redirect(writer, "/loop")
        elif path == "/to":
            await self._redirect(writer, query["url"][0])
        elif path == "/headers-only":
            # Promises a huge body and never finishes sending it: a checker
            # that tried to download the body would hang until the deadline.
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 10000000\r\n\r\npart")
            await writer.drain()
            await asyncio.sleep(30)

    async def _respond(self, writer, status: int) -> None:
        writer.write(
            f"HTTP/1.1 {status} X\r\nContent-Length: 2\r\n"
            "Connection: close\r\n\r\nok".encode()
        )
        await writer.drain()

    async def _redirect(self, writer, location: str) -> None:
        writer.write(
            f"HTTP/1.1 302 Found\r\nLocation: {location}\r\nContent-Length: 0\r\n"
            "Connection: close\r\n\r\n".encode()
        )
        await writer.drain()


@pytest.fixture
async def server():
    server = LocalServer()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
async def checker():
    async with Checker(allow_private_targets=True, deadline=2) as checker:
        yield checker


def fake_resolver(records: dict[str, list[list[str]] | None]):
    """DNS that answers from `records`; a list of answers is used in turn."""
    calls: dict[str, int] = {}

    async def resolve(host: str):
        answers = records.get(host)
        if answers is None:
            return None
        n = calls.get(host, 0)
        calls[host] = n + 1
        return [ip_address(ip) for ip in answers[min(n, len(answers) - 1)]]

    return resolve


def only_loopback(address) -> bool:
    """Test policy: loopback stands in for 'public', everything else blocked."""
    return address == LOOPBACK


def closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# --- up and down ---


async def test_reachable_site_is_up_with_status_and_latency(server, checker):
    outcome = await checker.check(server.url("/ok"))

    assert outcome == CheckOutcome(
        is_up=True, status_code=200, response_time_ms=outcome.response_time_ms
    )
    assert 0 <= outcome.response_time_ms < 2000


@pytest.mark.parametrize("status", [404, 500, 503])
async def test_error_status_is_down_with_http_error(server, checker, status):
    outcome = await checker.check(server.url(f"/status/{status}"))

    assert not outcome.is_up
    assert outcome.error_kind == "http_error"
    assert outcome.status_code == status
    assert outcome.response_time_ms is not None


async def test_slow_site_is_down_with_timeout(server):
    async with Checker(allow_private_targets=True, deadline=0.2) as checker:
        started = time.perf_counter()
        outcome = await checker.check(server.url("/slow"))

    assert outcome.error_kind == "timeout"
    assert outcome.status_code is None and outcome.response_time_ms is None
    assert time.perf_counter() - started < 1


async def test_body_is_never_downloaded(server, checker):
    started = time.perf_counter()
    outcome = await checker.check(server.url("/headers-only"))

    assert outcome.is_up
    assert time.perf_counter() - started < 1  # the deadline is 2 s


async def test_sends_the_pulseops_user_agent(server, checker):
    await checker.check(server.url("/ok"))

    assert server.requests[0]["user-agent"] == (
        f"PulseOps/{version('pulseops')} (uptime monitor)"
    )


async def test_urls_never_reach_the_logs(server, checker, caplog):
    # httpx2 logs every request URL at INFO, and httpcore2 traces at DEBUG.
    # The worker runs with INFO (DEBUG with -v), and URLs may carry tokens.
    caplog.set_level(logging.DEBUG)

    outcome = await checker.check(server.url("/redirect/1?token=s3cr3t-t0ken"))

    assert outcome.is_up
    assert "s3cr3t-t0ken" not in caplog.text
    assert "/redirect/" not in caplog.text


async def test_refused_connection_is_connection_error(checker):
    outcome = await checker.check(f"http://127.0.0.1:{closed_port()}/")

    assert outcome.error_kind == "connection_error"


async def test_unresolvable_name_is_dns_error():
    resolver = fake_resolver({})
    async with Checker(allow_private_targets=True, resolver=resolver) as checker:
        outcome = await checker.check("https://not-yet-live.example/")

    assert outcome.error_kind == "dns_error"


async def test_falls_back_to_the_next_address(server):
    # The server only listens on IPv4; ::1 fails and 127.0.0.1 works.
    resolver = fake_resolver({"dual.test": [["::1", "127.0.0.1"]]})
    async with Checker(allow_private_targets=True, resolver=resolver) as checker:
        outcome = await checker.check(server.url("/ok", host="dual.test"))

    assert outcome.is_up


# --- redirects ---


async def test_follows_redirects_up_to_the_limit(server, checker):
    outcome = await checker.check(server.url(f"/redirect/{MAX_REDIRECTS}"))

    assert outcome.is_up and outcome.status_code == 200
    assert len(server.requests) == MAX_REDIRECTS + 1


async def test_too_many_redirects_is_http_error(server, checker):
    outcome = await checker.check(server.url(f"/redirect/{MAX_REDIRECTS + 1}"))

    assert outcome.error_kind == "http_error"
    assert "redirects" in outcome.error_detail


async def test_redirect_loop_is_http_error(server, checker):
    outcome = await checker.check(server.url("/loop"))

    assert outcome.error_kind == "http_error"


async def test_redirect_to_another_scheme_is_http_error(server, checker):
    outcome = await checker.check(server.url("/to?url=ftp://example.com/file"))

    assert outcome.error_kind == "http_error"


# --- SSRF at connect time ---


async def test_literal_internal_ip_is_blocked_without_connecting():
    async with Checker(allow_private_targets=False) as checker:
        outcome = await checker.check("http://169.254.169.254/latest/meta-data/")

    assert outcome.error_kind == "blocked_target"
    assert "169.254" not in outcome.error_detail


async def test_redirect_to_internal_ip_is_blocked(server):
    async with Checker(allow_private_targets=False, policy=only_loopback) as checker:
        outcome = await checker.check(server.url("/to?url=http://10.0.0.5/"))

    assert outcome.error_kind == "blocked_target"
    assert len(server.requests) == 1  # nothing was sent to 10.0.0.5


async def test_dns_rebinding_is_blocked(server):
    # First lookup: an allowed address. Second (the redirect): an internal one.
    resolver = fake_resolver({"rebind.test": [["127.0.0.1"], ["10.0.0.5"]]})
    target = server.url("/ok", host="rebind.test")
    async with Checker(
        allow_private_targets=False, policy=only_loopback, resolver=resolver
    ) as checker:
        outcome = await checker.check(
            server.url(f"/to?url={target}", host="rebind.test")
        )

    assert outcome.error_kind == "blocked_target"
    assert len(server.requests) == 1


async def test_one_internal_address_blocks_the_whole_host(server):
    resolver = fake_resolver({"mixed.test": [["127.0.0.1", "10.0.0.5"]]})
    async with Checker(
        allow_private_targets=False, policy=only_loopback, resolver=resolver
    ) as checker:
        outcome = await checker.check(server.url("/ok", host="mixed.test"))

    assert outcome.error_kind == "blocked_target"
    assert server.requests == []


async def test_proxy_environment_variables_are_ignored(server, monkeypatch):
    dead_proxy = f"http://127.0.0.1:{closed_port()}"
    for name in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy"]:
        monkeypatch.setenv(name, dead_proxy)

    # A default client obeys the variables and fails on the dead proxy...
    async with httpx2.AsyncClient() as client:
        with pytest.raises(httpx2.ConnectError):
            await client.get(server.url("/ok"))
    # ...the checker ignores them and goes straight to the target.
    async with Checker(allow_private_targets=True) as checker:
        outcome = await checker.check(server.url("/ok"))

    assert outcome.is_up


# --- TLS ---


@pytest.fixture(scope="module")
def ca():
    return trustme.CA()


@pytest.fixture
def trusting_context(ca):
    context = ssl.create_default_context()
    ca.configure_trust(context)
    return context


async def tls_server(ca, *identities, **cert_options) -> LocalServer:
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ca.issue_cert(*identities, **cert_options).configure_cert(context)
    server = LocalServer(ssl_context=context)
    await server.start()
    return server


LOCALHOST = fake_resolver({"localhost": [["127.0.0.1"]]})


async def test_valid_certificate_is_up(ca, trusting_context):
    server = await tls_server(ca, "localhost")
    try:
        async with Checker(
            allow_private_targets=True, resolver=LOCALHOST, verify=trusting_context
        ) as checker:
            outcome = await checker.check(server.url("/ok", host="localhost"))
    finally:
        await server.stop()

    assert outcome.is_up


@pytest.mark.parametrize(
    "cert_options",
    [
        {"identities": ["other.example"]},
        {
            "identities": ["localhost"],
            "not_after": datetime.now(UTC) - timedelta(days=1),
        },
    ],
    ids=["wrong-name", "expired"],
)
async def test_bad_certificate_is_ssl_error(ca, trusting_context, cert_options):
    identities = cert_options.pop("identities")
    server = await tls_server(ca, *identities, **cert_options)
    try:
        async with Checker(
            allow_private_targets=True, resolver=LOCALHOST, verify=trusting_context
        ) as checker:
            outcome = await checker.check(server.url("/ok", host="localhost"))
    finally:
        await server.stop()

    assert outcome.error_kind == "ssl_error"


async def test_untrusted_certificate_authority_is_ssl_error(ca):
    server = await tls_server(ca, "localhost")
    try:
        # System trust store only: the test CA is unknown to it.
        async with Checker(allow_private_targets=True, resolver=LOCALHOST) as checker:
            outcome = await checker.check(server.url("/ok", host="localhost"))
    finally:
        await server.stop()

    assert outcome.error_kind == "ssl_error"


# --- outcome and command line ---


def test_outcome_enforces_the_database_rules():
    with pytest.raises(ValueError):
        CheckOutcome(is_up=True, error_kind="timeout")
    with pytest.raises(ValueError):
        CheckOutcome(is_up=False)
    with pytest.raises(ValueError):
        CheckOutcome(is_up=False, error_kind="too_slow")

    long = CheckOutcome(is_up=False, error_kind="timeout", error_detail="x" * 600)
    assert len(long.error_detail) == 500


def test_cli_prints_the_outcome_as_json(monkeypatch, capsys):
    async def fake_check(url, *, allow_private_targets):
        return CheckOutcome(is_up=True, status_code=200, response_time_ms=12)

    monkeypatch.setattr(cli, "check_url", fake_check)
    monkeypatch.setattr("sys.argv", ["pulseops.checker", "HTTPS://Example.com"])

    assert cli.main() == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == {
        "url": "https://example.com/",
        **dataclasses.asdict(CheckOutcome(True, 200, 12)),
    }


def test_cli_rejects_invalid_urls(monkeypatch):
    monkeypatch.setattr("sys.argv", ["pulseops.checker", "ftp://example.com"])

    assert cli.main() == 2
