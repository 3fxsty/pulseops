# Evidence log

Verified facts about PulseOps, recorded as the project grows. Every entry comes from a command, an automated test or a manual check that was actually run, never from memory or estimates. Each one says when and how it was verified, so it can be reproduced.

Updated at the close of every phase (and whenever a verified fact changes). It contains no personal data or details of any local network: placeholders such as `<local IP>` are used instead.

---

## Snapshot per phase

| Phase | Merged | Automated tests | Ruff | ADRs | Manual verification |
|---|---|---|---|---|---|
| 0 — Foundations | PR #1, 2026-10-26 | 1 passed | clean | 8 | `/health` 200, Swagger 200, `ardiq doctor` OK on Valkey |
| 1 — Data model | PR #2, 2026-10-26 | 29 passed | clean (with `S` rules) | 16 | Clean-volume start, `\d checks`, downgrade/upgrade, `alembic check` |
| 2 — Monitors API | PR #3, 2026-10-27 | 143 passed | clean (with `S` rules) | 30 | Manual test list: 22/22 against the live stack |

Reproduce the current numbers:

```bash
uv run pytest -q                 # test count and result
uv run ruff check .              # lint, including security rules
uv run alembic check             # models match migrations
grep -c "^## ADR-" docs/decisions.md
```

## Current test suite (2026-10-27, after Phase 2)

**143 passed in ~2.5 s**, against real PostgreSQL 18 (separate `pulseops_test` database).

| File | Tests | What it proves |
|---|---|---|
| `test_ssrf.py` | 44 | The full SSRF address table, DNS behaviour, disguised internal URLs, `ValidatedUrl` guard |
| `test_api_monitors.py` | 31 | Every endpoint, pagination, PATCH rules, 404/409/422 paths, cascade delete, repository guard |
| `test_url_normalization.py` | 25 | Every normalization rule, credential rejection, length limits |
| `test_models.py` | 22 | Every database constraint, UUID v7, cascade, `ON CONFLICT DO NOTHING` idempotency |
| `test_api_security.py` | 14 | "Must never happen" guarantees (see below) |
| `test_permissions.py` | 4 | The app role can read and write rows, but cannot CREATE, ALTER or DROP |
| `test_migrations.py` | 2 | Downgrade/upgrade round trip; models match migrations |
| `test_health.py` | 1 | Liveness endpoint |

## Guarantees backed by automated tests

| Guarantee | Test |
|---|---|
| The API never exposes the internal integer id | `test_api_security.py::test_monitor_responses_have_exactly_the_public_fields` |
| Errors never contain SQL, table or constraint names, or tracebacks | `test_errors_never_leak_database_internals`, `test_unexpected_error_is_a_generic_500` |
| Validation errors never echo user input | `test_validation_errors_never_echo_input` |
| A password embedded in a URL is never echoed | `test_password_in_url_is_never_echoed` |
| The API key never reaches the logs | `test_api_key_never_reaches_the_logs` |
| A too-short API key stops startup without being printed | `test_short_api_key_refuses_to_start_without_leaking_it` |
| Missing or wrong API key → 401 | `test_missing_or_wrong_api_key_is_401` |
| No CORS headers are sent | `test_no_cors_headers` |
| PATCH cannot bypass SSRF | `test_api_monitors.py::test_patch_url_goes_through_ssrf_check` |
| Pausing never performs a DNS lookup | `test_pausing_does_not_touch_dns` |
| An unvalidated URL cannot be stored | `test_repository_refuses_unvalidated_urls`, `test_validated_url_cannot_be_built_directly` |
| The app database role cannot change the schema | `test_permissions.py::test_app_role_cannot_change_schema` |
| A re-delivered check is a no-op | `test_models.py::test_check_redelivery_is_a_no_op_with_on_conflict` |
| Tests never touch development data | Separate `pulseops_test` database. Checked manually on 2026-10-26: dev `monitors` count stayed 0 after a full test run |

## Manual verifications

| Date | Check | Result |
|---|---|---|
| 2026-10-26 | `docker compose up --build` (Phase 0) | API, PostgreSQL, Valkey healthy; `/health` → `{"status":"ok"}`; `/docs` → 200 |
| 2026-10-26 | `ardiq doctor` against Valkey 9.1.2 | All checks OK (connection, version 7.2.4-compatible, writes, Lua). Only warning: no live workers (expected before Phase 4) |
| 2026-10-26 | HTTPS request with httpx2 from inside the API container | 200; system CA certificates present (`ca-certificates` ships with `python:3.13-slim`) |
| 2026-10-26 | Clean-volume start (Phase 1) | `migrate` applied `0001` and exited 0; API healthy |
| 2026-10-26 | `\d checks` as `pulseops_owner` | PK `(monitor_id, scheduled_at)`, 4 CHECKs, FK `ON DELETE CASCADE`, BRIN index |
| 2026-10-26 | Valkey without password | `NOAUTH Authentication required`; `ardiq doctor` OK with password (and masks it as `***`) |
| 2026-10-27 | Manual test list for Phase 2, 22 cases, live stack | **22/22 as expected**: auth, normalization, 409 on disguised duplicate, 422 on metadata/localhost/`postgres`/`0x7f.1`/`[::ffff:127.0.0.1]`/credentials/forbidden field, pagination, PATCH including SSRF backdoor, 404/204 |
| 2026-10-27 | `http://postgres:5432/` (Docker service name) | Blocked by SSRF: it resolves to a private IP inside the Docker network |
| 2026-10-27 | Reachability of `127.0.0.1:8000` | Reachable from the host's browser (`/docs` → 200); **not** reachable on the machine's network address (`<local IP>:8000` → no answer) |
| 2026-10-26/27 | Phases 0, 1 and 2 tested by the project owner | Swagger `/health` 200 (Phase 0); `psql` checks (Phase 1); manual list (Phase 2) |

## Library behaviour verified (instead of assumed)

| Finding | Consequence |
|---|---|
| `ipaddress.is_global` is `True` for `224.0.0.1`, `ff02::1` (multicast), `64:ff9b::7f00:1` (NAT64 wrapping 127.0.0.1) and `::127.0.0.1` (IPv4-compatible) | Extra SSRF rules (ADR-023), covered by `test_is_global_alone_is_not_enough` |
| In Python 3.13, 6to4 (`2002::/16`) and Teredo report `is_global=False` as whole ranges | Unwrapping them is defence in depth |
| Pydantic `SecretStr` + `min_length` prints the secret in the validation error | `hide_input_in_errors=True` on every settings class |
| Pydantic `HttpUrl` rejects URLs over 2083 characters on its own | API input limit set to 2083 for a clear error; stored URL limit stays 2048 |
| Pydantic `HttpUrl` canonicalizes `http://2130706433/` and `http://0x7f.1/` to `127.0.0.1` | Obfuscated IPs reach the SSRF check in canonical form |
| SQLAlchemy 2.1 no longer installs `greenlet` | Dependency is `sqlalchemy[asyncio]` |
| Starlette's test client warns against `httpx`, and `httpx` is unmaintained | Switched to `httpx2` (ADR-008) |
| ArdiQ's default codec is msgpack, not pickle | Rule: never override it with pickle |
| Valkey 9.1.2 reports `redis_version:7.2.4` | Compatible with ArdiQ (ADR-007) |
| During first init, PostgreSQL listens only on the Unix socket | Healthcheck uses TCP so `migrate` waits for the roles |
| FastAPI 0.162 keeps included routers nested (`_IncludedRouter`) | `app.routes` does not list router endpoints; `url_path_for` still works |

## Verified versions (2026-10-27)

| Component | Version |
|---|---|
| Python | 3.13.17 |
| FastAPI | 0.162.0 |
| SQLAlchemy | 2.1.6 |
| Alembic | 1.20.1 |
| Pydantic / pydantic-settings | 2.14.1 / 2.16.1 |
| httpx2 | 2.16.0 |
| asyncpg | 0.32.0 |
| ArdiQ | 1.2.0 |
| PostgreSQL | 18.6 |
| Valkey | 9.1.2 |
| Docker / Compose | 29.9.2 / v5.6.1 |

## Size (2026-10-27, after Phase 2)

| Metric | Value | Command |
|---|---|---|
| Commits on `main` | 32 | `git rev-list --count main` |
| Non-blank lines in `src/` | 780 | `find src -name '*.py' \| xargs cat \| grep -cv '^\s*$'` |
| Non-blank lines in `tests/` | 734 | same, on `tests` |
| ADRs | 30 | `grep -c "^## ADR-" docs/decisions.md` |
| Merged PRs | 3 | `gh pr list --state merged` |
