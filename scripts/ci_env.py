"""Write a throwaway .env for CI from .env.example, with random secrets.

    python3 scripts/ci_env.py [--output PATH]

Every value that starts with "change-me" gets a fresh random value (hex: URL
safe, and long enough for API_KEY). No password lives in the repository, and
CI starts from .env.example exactly as a newcomer would, which also proves
the example is complete. On GitHub Actions each value is masked in the logs.
It never overwrites an existing file, so it cannot replace a real .env.
Standard library only: it runs before any dependency is installed.
"""

import argparse
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = "change-me"


def fill(example: str) -> tuple[str, list[str]]:
    """The example with every placeholder replaced, and the new values."""
    lines, generated = [], []
    for line in example.splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.lstrip().startswith("#") and value.startswith(PLACEHOLDER):
            value = secrets.token_hex(24)  # 48 characters
            generated.append(value)
            line = f"{key}={value}"
        lines.append(line)
    return "\n".join(lines) + "\n", generated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=ROOT / ".env")
    args = parser.parse_args()

    content, generated = fill((ROOT / ".env.example").read_text())
    if not generated:
        print(f"no {PLACEHOLDER} values found in .env.example", file=sys.stderr)
        return 1
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for value in generated:
            print(f"::add-mask::{value}")  # hidden in every later log line
    try:
        # O_EXCL: fail instead of overwriting; 0o600: readable by its owner only.
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(f"{args.output} already exists; not overwriting it", file=sys.stderr)
        return 1
    with os.fdopen(fd, "w") as file:
        file.write(content)
    print(f"Wrote {args.output.name} with {len(generated)} random secrets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
