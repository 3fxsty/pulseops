"""Smoke test: the manual test list, run against the live stack from outside.

    docker compose up -d
    uv run python scripts/smoke_test.py [--base-url http://127.0.0.1:8000]

pytest checks the app from the inside against the test database; this script
checks the real running stack the way a user would. It only touches the
monitors it creates (unique URLs per run) and deletes them at the end, so it
is safe to run against a stack with real data. The API key comes from .env.
Exit code 0 means every check passed.
"""

import argparse
import re
import sys
import uuid

import httpx2

from pulseops.config import ApiSettings

PROBLEM_KEYS = {"type", "title", "status", "detail", "code"}
INTERNALS = re.compile(r"uq_|ck_|pk_|fk_|SELECT|INSERT|UPDATE |Traceback|asyncpg")


class Smoke:
    def __init__(self, client: httpx2.Client, base: str) -> None:
        self.client = client
        self.base = base
        self.results: list[tuple[bool, str, str]] = []

    def check(self, name, response, status, code=None, extra=None):
        """Record one check; also enforce the rules every response must follow."""
        body = response.json() if response.content else None
        problems = []
        if response.status_code != status:
            problems.append(f"status {response.status_code}, expected {status}")
        if code is not None and (body or {}).get("code") != code:
            problems.append(f"code {(body or {}).get('code')!r}, expected {code!r}")
        if response.status_code >= 400 and not PROBLEM_KEYS <= set(body or {}):
            problems.append("not a Problem Details body")
        if INTERNALS.search(response.text):
            problems.append("leaks database internals")
        if re.search(r'"id":\s*\d', response.text):
            problems.append("exposes an integer id")
        if extra is not None and not extra(response, body):
            problems.append("extra check failed")
        self.results.append((not problems, name, "; ".join(problems)))
        return body

    def create(self, headers=None, **overrides):
        body = {
            "name": "Smoke",
            "url": "https://www.google.com",
            "interval_seconds": 60,
        }
        return self.client.post(self.base, json=body | overrides, headers=headers)


def run(base_url: str, api_key: str) -> list[tuple[bool, str, str]]:
    base = f"{base_url.rstrip('/')}/api/v1/monitors"
    run_id = uuid.uuid4().hex[:8]
    created: list[str] = []

    with httpx2.Client(headers={"X-API-Key": api_key}, timeout=30) as client:
        smoke = Smoke(client, base)
        try:
            # 1. Authentication
            smoke.check("no API key", httpx2.get(base), 401, "unauthorized")
            smoke.check(
                "wrong API key",
                httpx2.get(base, headers={"X-API-Key": "hola"}),
                401,
                "unauthorized",
            )

            # 2. Create and normalize
            google_url = f"https://www.google.com/smoke-{run_id}"
            response = smoke.create(
                name="Google", url=f"HTTPS://WWW.Google.COM./smoke-{run_id}#x"
            )
            google = smoke.check(
                "create normalizes the URL",
                response,
                201,
                extra=lambda r, b: (
                    b["url"] == google_url
                    and len(b["id"]) == 36
                    and r.headers.get("location") == f"/api/v1/monitors/{b['id']}"
                ),
            )
            created.append(google["id"])

            # 3. Create errors
            cases = [
                (
                    "disguised duplicate",
                    {"url": f" HTTPS://www.Google.COM./smoke-{run_id}#hola "},
                    409,
                    "monitor_url_conflict",
                ),
                (
                    "interval too low",
                    {
                        "url": f"https://www.google.com/x-{run_id}",
                        "interval_seconds": 10,
                    },
                    422,
                    "validation_error",
                ),
                (
                    "credentials in URL",
                    {"url": "https://usuario:secreto@example.com"},
                    422,
                    "url_credentials_not_allowed",
                ),
                (
                    "cloud metadata",
                    {"url": "http://169.254.169.254/"},
                    422,
                    "url_target_not_allowed",
                ),
                (
                    "the host itself",
                    {"url": "http://127.0.0.1:8000/"},
                    422,
                    "url_target_not_allowed",
                ),
                (
                    "the database service",
                    {"url": "http://postgres:5432/"},
                    422,
                    "url_target_not_allowed",
                ),
                (
                    "disguised IPv4",
                    {"url": "http://0x7f.1/"},
                    422,
                    "url_target_not_allowed",
                ),
                (
                    "disguised IPv6",
                    {"url": "http://[::ffff:127.0.0.1]/"},
                    422,
                    "url_target_not_allowed",
                ),
                (
                    "forbidden field",
                    {"url": f"https://www.google.com/y-{run_id}", "id": "abc"},
                    422,
                    "validation_error",
                ),
            ]
            for name, body, status, code in cases:
                smoke.check(
                    name,
                    smoke.create(**body),
                    status,
                    code,
                    extra=lambda r, b: (
                        "secreto" not in r.text and "169.254" not in r.text
                    ),
                )

            # 4. List and paginate
            second = smoke.create(
                name="Second", url=f"https://www.google.com/second-{run_id}"
            ).json()
            created.append(second["id"])
            first_page = smoke.check(
                "limit=1",
                client.get(base, params={"limit": 1}),
                200,
                extra=lambda r, b: len(b["items"]) == 1 and b["total"] >= 2,
            )
            smoke.check(
                "limit=1 offset=1",
                client.get(base, params={"limit": 1, "offset": 1}),
                200,
                extra=lambda r, b: (
                    len(b["items"]) == 1
                    and b["items"][0]["id"] != first_page["items"][0]["id"]
                ),
            )

            # 5. PATCH
            url = f"{base}/{google['id']}"
            smoke.check(
                "pause",
                client.patch(url, json={"is_active": False}),
                200,
                extra=lambda r, b: b["is_active"] is False,
            )
            smoke.check(
                "filter paused",
                client.get(base, params={"is_active": "false", "limit": 100}),
                200,
                extra=lambda r, b: (
                    google["id"] in {m["id"] for m in b["items"]}
                    and second["id"] not in {m["id"] for m in b["items"]}
                ),
            )
            smoke.check(
                "PATCH cannot bypass SSRF",
                client.patch(url, json={"url": "http://10.0.0.5/"}),
                422,
                "url_target_not_allowed",
            )
            smoke.check(
                "change the URL",
                client.patch(
                    url, json={"url": f"HTTPS://Www.Wikipedia.org/smoke-{run_id}"}
                ),
                200,
                extra=lambda r, b: (
                    b["url"] == f"https://www.wikipedia.org/smoke-{run_id}"
                ),
            )
            smoke.check(
                "null name",
                client.patch(url, json={"name": None}),
                422,
                "validation_error",
            )

            # 6. Not found and delete
            wrong = google["id"][:-1] + ("0" if google["id"][-1] != "0" else "1")
            smoke.check(
                "unknown id", client.get(f"{base}/{wrong}"), 404, "monitor_not_found"
            )
            smoke.check("delete", client.delete(url), 204)
            created.remove(google["id"])
            smoke.check("get after delete", client.get(url), 404, "monitor_not_found")
        finally:
            for monitor_id in created:
                client.delete(f"{base}/{monitor_id}")
    return smoke.results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    results = run(args.base_url, ApiSettings().api_key.get_secret_value())
    width = max(len(name) for _, name, _ in results)
    for ok, name, problems in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {problems}")
    passed = sum(ok for ok, _, _ in results)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
