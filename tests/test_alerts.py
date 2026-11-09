"""Telegram alerts: settings, client, messages and command (ADR-064 to ADR-066)."""

import asyncio
import json
import logging
import subprocess
import sys
import time
import traceback
import uuid
from dataclasses import fields
from datetime import UTC, datetime, timedelta, timezone

import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from pulseops.alerts import DeliveryError, TelegramNotifier
from pulseops.alerts import __main__ as cli
from pulseops.alerts.messages import TEST_MESSAGE, IncidentSummary, alert_text
from pulseops.alerts.telegram import TELEGRAM_API_URL
from pulseops.config import AlertSettings

pytestmark = pytest.mark.anyio

# Made up, and unlike a real token (those start with "AA" after the colon),
# so secret scanners never mistake it for one.
FAKE_TOKEN = "123456:fake-token-for-tests-only-not-real"
CHAT_ID = "-1001234567890"
ALERT_VARIABLES = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")


@pytest.fixture
def no_alert_environment(monkeypatch):
    """Only what each test sets counts, not the developer's .env or shell."""
    for name in ALERT_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def alert_settings(**values) -> AlertSettings:
    return AlertSettings(_env_file=None, **values)


# --- settings ---


def test_alerts_are_off_without_settings(no_alert_environment):
    assert alert_settings().enabled is False


def test_empty_values_mean_not_set(no_alert_environment, monkeypatch):
    # .env.example ships TELEGRAM_BOT_TOKEN= and TELEGRAM_CHAT_ID= empty.
    for name in ALERT_VARIABLES:
        monkeypatch.setenv(name, "")

    assert alert_settings().enabled is False


def test_both_settings_turn_alerts_on(no_alert_environment):
    settings = alert_settings(telegram_bot_token=FAKE_TOKEN, telegram_chat_id=CHAT_ID)

    assert settings.enabled is True
    assert FAKE_TOKEN not in repr(settings)


@pytest.mark.parametrize(
    "values",
    [{"telegram_bot_token": FAKE_TOKEN}, {"telegram_chat_id": CHAT_ID}],
    ids=["token-only", "chat-only"],
)
def test_one_setting_without_the_other_stops_start_up(no_alert_environment, values):
    with pytest.raises(ValidationError, match="both") as error:
        alert_settings(**values)

    assert FAKE_TOKEN not in str(error.value)


@pytest.mark.parametrize(
    "token",
    ["123456", "fake-token-for-tests-only-not-real", "123456:too-short"],
)
def test_a_malformed_token_is_refused_without_echoing_it(no_alert_environment, token):
    with pytest.raises(ValidationError) as error:
        alert_settings(telegram_bot_token=token, telegram_chat_id=CHAT_ID)

    assert token not in str(error.value)


@pytest.mark.parametrize("chat_id", ["42", "-1001234567890", "@pulseops_alerts"])
def test_chat_ids_and_channel_names_are_accepted(no_alert_environment, chat_id):
    settings = alert_settings(telegram_bot_token=FAKE_TOKEN, telegram_chat_id=chat_id)

    assert settings.telegram_chat_id == chat_id


@pytest.mark.parametrize("chat_id", ["abc", "@abc", "12 34", "-"])
def test_malformed_chat_ids_are_refused(no_alert_environment, chat_id):
    with pytest.raises(ValidationError, match="number or an @channel"):
        alert_settings(telegram_bot_token=FAKE_TOKEN, telegram_chat_id=chat_id)


# --- the Bot API client ---


class FakeTelegram:
    """Stands in for api.telegram.org: records requests, answers as told."""

    def __init__(self, respond=None):
        self.requests: list[httpx2.Request] = []
        self.respond = respond or (
            lambda request: httpx2.Response(200, json={"ok": True})
        )

    async def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        answer = self.respond(request)
        return await answer if asyncio.iscoroutine(answer) else answer

    def notifier(self, **options) -> TelegramNotifier:
        return TelegramNotifier(
            token=SecretStr(FAKE_TOKEN),
            chat_id=CHAT_ID,
            transport=httpx2.MockTransport(self.handle),
            **options,
        )


def answer(status: int, body=None, **kwargs):
    return lambda request: httpx2.Response(status, json=body, **kwargs)


async def failure(telegram: FakeTelegram) -> DeliveryError:
    async with telegram.notifier() as notifier:
        with pytest.raises(DeliveryError) as error:
            await notifier.send("Hello")
    return error.value


def leaks_token(error: BaseException) -> bool:
    shown = [str(error), repr(error), *traceback.format_exception(error)]
    return any(FAKE_TOKEN in text for text in shown)


async def test_sends_plain_text_to_the_fixed_bot_api_address():
    telegram = FakeTelegram()

    async with telegram.notifier() as notifier:
        await notifier.send("Example is down")

    [request] = telegram.requests
    assert request.method == "POST"
    assert str(request.url) == f"https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage"
    assert TELEGRAM_API_URL == "https://api.telegram.org"
    assert json.loads(request.content) == {
        "chat_id": CHAT_ID,
        "text": "Example is down",
        "link_preview_options": {"is_disabled": True},
    }


async def test_a_rate_limit_says_how_long_to_wait():
    body = {"ok": False, "error_code": 429, "parameters": {"retry_after": 30}}

    error = await failure(FakeTelegram(answer(429, body)))

    assert (error.reason, error.status_code, error.retry_after) == (
        "rate_limited",
        429,
        30,
    )


async def test_a_rate_limit_without_a_json_answer_uses_the_header():
    respond = lambda request: httpx2.Response(  # noqa: E731
        429, text="slow down", headers={"Retry-After": "7"}
    )

    assert (await failure(FakeTelegram(respond))).retry_after == 7


async def test_a_zero_wait_is_ignored():
    # retry_after 0 would mean "retry at once": fall back to the header.
    respond = lambda request: httpx2.Response(  # noqa: E731
        429,
        json={"ok": False, "parameters": {"retry_after": 0}},
        headers={"Retry-After": "5"},
    )

    assert (await failure(FakeTelegram(respond))).retry_after == 5


async def test_a_rate_limit_without_any_wait_leaves_it_to_the_retry_policy():
    assert (await failure(FakeTelegram(answer(429, {"ok": False})))).retry_after is None


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_a_server_error_is_temporary(status):
    error = await failure(FakeTelegram(answer(status, {"ok": False})))

    assert (error.reason, error.status_code) == ("http_error", status)
    assert error.permanent is False


@pytest.mark.parametrize(
    ("status", "problem"),
    [
        (400, "Telegram rejected the message (for example, the chat does not exist)"),
        (401, "the bot token is not valid"),
        (403, "the bot cannot write to the chat (blocked, or removed from it)"),
        (404, "the bot token is not valid (malformed)"),
        (409, "Telegram refused the alert"),
    ],
)
async def test_any_other_error_is_permanent_and_says_why(status, problem):
    error = await failure(FakeTelegram(answer(status, {"ok": False})))

    assert (error.reason, error.status_code, error.permanent) == (
        "http_error",
        status,
        True,
    )
    assert str(error) == f"http_error (HTTP {status}): {problem}"
    assert not leaks_token(error)


async def test_a_200_that_is_not_ok_is_permanent():
    error = await failure(FakeTelegram(answer(200, {"ok": False})))

    assert (error.status_code, error.permanent) == (200, True)


async def test_network_failures_and_rate_limits_are_temporary():
    def refuse(request):
        raise httpx2.ConnectError("refused", request=request)

    refused = await failure(FakeTelegram(refuse))
    limited = await failure(FakeTelegram(answer(429, {"ok": False})))

    assert (refused.permanent, limited.permanent) == (False, False)


async def test_redirects_are_never_followed():
    # The token is in the path: a redirect must never carry it anywhere else.
    telegram = FakeTelegram(
        answer(302, headers={"Location": "https://elsewhere.example/steal"})
    )

    error = await failure(telegram)

    assert (error.reason, error.status_code, error.permanent) == (
        "http_error",
        302,
        True,
    )
    assert len(telegram.requests) == 1


async def test_a_connection_error_never_carries_the_token():
    def refuse(request):
        raise httpx2.ConnectError(f"cannot reach {request.url}", request=request)

    error = await failure(FakeTelegram(refuse))

    assert error.reason == "connection_error"
    assert not leaks_token(error)


async def test_a_send_that_hangs_is_cut_at_the_deadline():
    async def hang(request):
        await asyncio.sleep(30)

    telegram = FakeTelegram(hang)
    started = time.perf_counter()

    async with telegram.notifier(deadline=0.2) as notifier:
        with pytest.raises(DeliveryError) as error:
            await notifier.send("Hello")

    assert (error.value.reason, error.value.permanent) == ("timeout", False)
    assert time.perf_counter() - started < 1
    assert not leaks_token(error.value)


def test_importing_alerts_alone_silences_httpx2():
    # httpx2 logs every request URL at INFO, and this one holds the token. In
    # the test process the checker has already silenced it for everyone, so
    # check a fresh interpreter, as `python -m pulseops.alerts test` runs.
    code = (
        "import logging, pulseops.alerts; "
        "print(*(logging.getLogger(n).level for n in ('httpx2', 'httpcore2')))"
    )
    # A fixed command: this interpreter and a literal script.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert result.stdout.split() == [str(logging.WARNING)] * 2


async def test_the_token_never_reaches_the_logs(caplog):
    caplog.set_level(logging.DEBUG)

    async with FakeTelegram().notifier() as notifier:
        await notifier.send("Hello")
    await failure(FakeTelegram(answer(500, {"ok": False})))

    assert FAKE_TOKEN not in caplog.text


async def test_proxy_variables_are_ignored(monkeypatch):
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")

    # The real client, without a fake transport (with one, httpx2 never looks
    # at proxy variables, so it would prove nothing). _mounts holds the proxy
    # routes httpx2 built from the environment.
    async with TelegramNotifier(
        token=SecretStr(FAKE_TOKEN), chat_id=CHAT_ID
    ) as notifier:
        assert notifier._client.trust_env is False
        assert notifier._client._mounts == {}
    # A default client would send the token through that proxy.
    async with httpx2.AsyncClient() as default:
        assert default._mounts


# --- what an alert says ---

MONITOR_ID = uuid.UUID("01970000-0000-7000-8000-000000000001")
STARTED = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def summary(**overrides) -> IncidentSummary:
    fields_ = {
        "monitor_name": "Shop API",
        "monitor_id": MONITOR_ID,
        "started_at": STARTED,
        "error_kind": "http_error",
        "status_code": 503,
    }
    return IncidentSummary(**(fields_ | overrides))


def test_the_opened_alert():
    assert alert_text("opened", summary()) == (
        "🔴 DOWN: Shop API\n"
        "Since: 2026-11-03 12:00:00 UTC\n"
        "Cause: http_error (HTTP 503)\n"
        f"Monitor: {MONITOR_ID}"
    )


def test_the_resolved_alert_stands_on_its_own():
    # It may arrive without the "opened" one (ADR-063): start and cause included.
    resolved = summary(resolved_at=STARTED + timedelta(minutes=5, seconds=30))

    assert alert_text("resolved", resolved) == (
        "✅ RECOVERED: Shop API\n"
        "Down for 5 min 30 s, since 2026-11-03 12:00:00 UTC\n"
        "Cause: http_error (HTTP 503)\n"
        f"Monitor: {MONITOR_ID}"
    )


def test_a_cause_without_an_http_status():
    text = alert_text("opened", summary(error_kind="timeout", status_code=None))

    assert "Cause: timeout\n" in text


def test_times_are_shown_in_utc():
    # The same moment, as 13:00 in a UTC+1 zone.
    plus_one = STARTED.astimezone(timezone(timedelta(hours=1)))

    assert "Since: 2026-11-03 12:00:00 UTC" in alert_text(
        "opened", summary(started_at=plus_one)
    )


@pytest.mark.parametrize(
    ("seconds", "shown"),
    [
        (0, "0 s"),
        (45, "45 s"),
        (90, "1 min 30 s"),
        (3600, "1 h"),
        (3725, "1 h 2 min"),  # two units at most
        (90000, "1 d 1 h"),
        (3 * 86400 + 59, "3 d"),
    ],
)
def test_durations_are_short(seconds, shown):
    resolved = summary(resolved_at=STARTED + timedelta(seconds=seconds))

    assert f"Down for {shown}, since" in alert_text("resolved", resolved)


def test_a_line_break_in_the_name_cannot_fake_a_line():
    text = alert_text("opened", summary(monitor_name="Shop\n✅ RECOVERED: Shop"))

    assert text.splitlines()[0] == "🔴 DOWN: Shop ✅ RECOVERED: Shop"
    assert len(text.splitlines()) == 4


def test_an_alert_has_no_room_for_the_url_or_the_error_detail():
    # ADR-065: never sent to Telegram, so not even carried here.
    assert {f.name for f in fields(IncidentSummary)}.isdisjoint({"url", "error_detail"})


def test_unknown_alert_kinds_are_refused():
    with pytest.raises(ValueError, match="reminder"):
        alert_text("reminder", summary())
    with pytest.raises(ValueError):
        alert_text("resolved", summary())  # never resolved


# --- python -m pulseops.alerts test ---


@pytest.fixture
def run_cli(monkeypatch, no_alert_environment):
    """Run the command with the given settings and a fake Telegram."""

    def run(telegram: FakeTelegram | None = None, **settings) -> int:
        monkeypatch.setattr("sys.argv", ["pulseops.alerts", "test"])
        monkeypatch.setattr(cli, "AlertSettings", lambda: alert_settings(**settings))
        if telegram is not None:
            monkeypatch.setattr(
                cli, "TelegramNotifier", lambda **kwargs: telegram.notifier()
            )
        return cli.main()

    return run


CONFIGURED = {"telegram_bot_token": FAKE_TOKEN, "telegram_chat_id": CHAT_ID}


def test_cli_sends_the_test_message(run_cli, capsys):
    telegram = FakeTelegram()

    assert run_cli(telegram, **CONFIGURED) == 0

    [request] = telegram.requests
    assert json.loads(request.content)["text"] == TEST_MESSAGE
    assert "Sent" in capsys.readouterr().out


def test_cli_reports_a_failed_send_without_the_token(run_cli, capsys):
    assert run_cli(FakeTelegram(answer(401, {"ok": False})), **CONFIGURED) == 1

    output = capsys.readouterr()
    assert "Not sent: http_error (HTTP 401)" in output.err
    assert FAKE_TOKEN not in output.out + output.err


def test_cli_says_when_alerts_are_off(run_cli, capsys):
    assert run_cli() == 2

    assert "Alerts are off" in capsys.readouterr().err


def test_cli_refuses_invalid_settings_without_echoing_them(run_cli, capsys):
    assert run_cli(telegram_bot_token=FAKE_TOKEN) == 2

    output = capsys.readouterr()
    assert "Invalid alert settings" in output.err
    assert FAKE_TOKEN not in output.out + output.err
