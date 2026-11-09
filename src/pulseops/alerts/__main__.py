"""Send a test alert from the command line (ADR-066).

    python -m pulseops.alerts test

Run it inside the worker's container: it uses the worker's TELEGRAM_BOT_TOKEN
and TELEGRAM_CHAT_ID. Exit codes: 0 sent, 1 not sent, 2 alerts not set up.
"""

import argparse
import asyncio
import sys

from pydantic import ValidationError

from pulseops.alerts.messages import TEST_MESSAGE
from pulseops.alerts.notifier import DeliveryError
from pulseops.alerts.telegram import TelegramNotifier
from pulseops.config import AlertSettings


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m pulseops.alerts")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("test", help="send a test message to the configured chat")
    parser.parse_args()

    try:
        settings = AlertSettings()
    except ValidationError as error:
        # hide_input_in_errors: the message never shows the values.
        print(f"Invalid alert settings:\n{error}", file=sys.stderr)
        return 2
    if not settings.enabled:
        print(
            "Alerts are off: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.",
            file=sys.stderr,
        )
        return 2

    try:
        asyncio.run(_send_test(settings))
    except DeliveryError as error:
        print(f"Not sent: {error}", file=sys.stderr)
        return 1
    print("Sent: check the chat.")
    return 0


async def _send_test(settings: AlertSettings) -> None:
    async with TelegramNotifier(
        token=settings.telegram_bot_token, chat_id=settings.telegram_chat_id
    ) as notifier:
        await notifier.send(TEST_MESSAGE)


if __name__ == "__main__":
    sys.exit(main())
