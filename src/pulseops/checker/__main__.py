"""Check one URL from the command line (ADR-037).

    python -m pulseops.checker https://example.com

Prints the outcome as JSON. The URL is normalized first, exactly as the API
would store it; the SSRF policy follows ALLOW_PRIVATE_TARGETS.
"""

import argparse
import asyncio
import dataclasses
import json
import sys

from pulseops.checker import check_url
from pulseops.config import get_settings
from pulseops.security.errors import UrlValidationError
from pulseops.security.urls import normalize_url


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m pulseops.checker")
    parser.add_argument("url", help="http or https URL to check")
    args = parser.parse_args()

    try:
        url = normalize_url(args.url).url
    except UrlValidationError as error:
        print(f"Invalid URL: {error.__class__.__name__}", file=sys.stderr)
        return 2

    outcome = asyncio.run(
        check_url(url, allow_private_targets=get_settings().allow_private_targets)
    )
    print(json.dumps({"url": url, **dataclasses.asdict(outcome)}, indent=2))
    return 0 if outcome.is_up else 1


if __name__ == "__main__":
    sys.exit(main())
