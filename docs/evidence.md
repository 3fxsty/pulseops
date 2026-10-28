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
| 3 — Checker | PR #4, 2026-10-27 | 170 passed, 95 % coverage | clean (with `S` rules) | 38 | Checker inside the container against real sites; smoke test 22/22 |
| 4 — Automatic checks | PR #5, 2026-10-27 | 213 passed, 97 % coverage | clean (with `S` rules) | 45 | Worker in Compose: a new monitor gets its first check in 2 s, then one per interval; worker restarted after `kill -9`; heartbeat fresh |
| 5 — Status and statistics | PR #6, 2026-10-28 | 266 passed, 97 % coverage | clean (with `S` rules) | 52 | Smoke test 29/29 (first automatic check in 5 s); query measurement on ~893,000 checks |

Reproduce the current numbers:

```bash
uv run pytest -q                 # test count and result
uv run pytest -q --cov           # same, with coverage
uv run python scripts/smoke_test.py   # live stack, from outside
uv run python scripts/measure_queries.py   # query timings and plans (test database)
uv run ruff check .              # lint, including security rules
uv run alembic check             # models match migrations
grep -c "^## ADR-" docs/decisions.md
```

## Current test suite (2026-10-28, Phase 5)

**266 passed in ~19 s**, against real PostgreSQL 18 (separate `pulseops_test` database), real Valkey 9 (logical database 1, throwaway queues) and real local HTTP/HTTPS servers. **Coverage: 97 %** (statements and branches, `uv run pytest --cov`). About 10 s of the run is a single test (`test_scheduler_error_log_never_shows_the_broker_password`): ArdiQ retries a failed connection before giving up, and has no option to shorten that.

| File | Tests | What it proves |
|---|---|---|
| `test_ssrf.py` | 45 | The full SSRF address table, DNS behaviour (own thread pool, failures, timeouts), disguised internal URLs, `ValidatedUrl` guard |
| `test_api_monitors.py` | 31 | Every endpoint, pagination, PATCH rules, 404/409/422 paths, cascade delete, repository guard |
| `test_checker.py` | 27 | Up/down against real local servers: 200, 404/500/503, timeout, body never downloaded, User-Agent, refused connection, DNS failure, address fallback, redirects (limit, loop, other scheme), SSRF at connect time (literal IP, redirect to internal IP, DNS rebinding, mixed answers), proxy variables ignored, URLs never logged, TLS (valid, wrong name, expired, untrusted CA), CLI |
| `test_url_normalization.py` | 25 | Every normalization rule, credential rejection, length limits |
| `test_models.py` | 22 | Every database constraint, UUID v7, cascade, `ON CONFLICT DO NOTHING` idempotency |
| `test_api_checks.py` | 20 | History (exact fields, every check once in order, no shift when a check arrives mid-pagination, forged cursor, a cursor never reaches another monitor, `limit` bounds) and stats (healthy, down with rounding, no data, paused, stale → `unknown`, period window, unknown period), 404/401 on both, API error kinds match the database |
| `test_api_security.py` | 15 | "Must never happen" guarantees (see below) |
| `test_cursors.py` | 14 | Exact microsecond round trip, opaque URL-safe cursor, 12 forged cursors rejected |
| `test_scheduling.py` | 12 | Scheduler tick (enqueue then commit, failed enqueue loses nothing, heartbeat moves on empty ticks and not on failed ones), check run (stores the outcome, no connection held during the check, deleted/paused skipped, URL and `error_detail` never logged), `hide_parameters` |
| `test_checks_repository.py` | 12 | Storing a check (idempotent, monitor deleted meanwhile), keyset history, latest check, stats (latency of up checks only, p95, period, no data), batch delete (recent kept, one batch at a time, an address pointing at a recent check deletes nothing) |
| `test_scheduling_repository.py` | 9 | Claiming due monitors: due/not due, inactive, missed slots keep the rhythm, batch size, `updated_at` untouched, two schedulers never claim the same monitor, a claimed monitor still accepts checks, a rolled-back claim is retried with the same slot |
| `test_monitor_rescheduling.py` | 8 | Create, new URL, new interval and reactivation bring the next check forward; rename, pause and same values do not |
| `test_queue_tasks.py` | 6 | ArdiQ wrappers in memory (`inline`): microsecond round trip, check task, scheduler tick, broken broker, retention task, error log without the broker password (real Valkey) |
| `test_status.py` | 5 | Current status: up/down, paused, no checks, the staleness boundary (180 s fresh, 181 s stale for a 60 s interval) |
| `test_queue_broker.py` | 5 | ArdiQ against real Valkey: id dedup while waiting, no dedup after finishing, `expire_ms` drops stale tasks, 16-digit integers intact, the scheduler keeps its slot while checks (30) and cleanup (1) are busy |
| `test_permissions.py` | 4 | The app role can read and write rows, but cannot CREATE, ALTER or DROP |
| `test_retention.py` | 3 | Every expired batch deleted and recent checks kept, the 60 s budget stops between batches and the next run finishes, nothing to delete |
| `test_migrations.py` | 2 | Downgrade/upgrade round trip; models match migrations |
| `test_health.py` | 1 | Liveness endpoint |

Not covered, on purpose: the real database session factory (tests substitute their own) and small helpers.

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
| The checker never connects to a disallowed address, not even after a redirect or a DNS answer that changes (rebinding) | `test_checker.py::test_dns_rebinding_is_blocked`, `test_redirect_to_internal_ip_is_blocked`, `test_one_internal_address_blocks_the_whole_host` |
| Those SSRF tests really detect the gap | Checked on 2026-10-27: with the validation disabled, all four fail |
| The checker ignores `HTTP(S)_PROXY` | `test_proxy_environment_variables_are_ignored` (a default client fails on the same variables) |
| The response body is never downloaded | `test_body_is_never_downloaded` |
| Bad certificates are never accepted | `test_bad_certificate_is_ssl_error`, `test_untrusted_certificate_authority_is_ssl_error` |
| The worker never logs a monitor URL or `error_detail` (URLs may carry tokens) | `test_scheduling.py::test_logs_never_show_the_url_or_the_error_detail`, `test_checker.py::test_urls_never_reach_the_logs` |
| Database errors never carry query parameters | `test_database_errors_never_show_query_parameters` |
| Scheduler errors never log the Valkey password | `test_queue_tasks.py::test_scheduler_error_log_never_shows_the_broker_password` |
| The API never gets the Valkey password | `test_api_security.py::test_api_settings_never_carry_the_broker_password`; `BROKER_URL` absent from the API container (checked 2026-10-27) |
| A failed enqueue loses no check | `test_scheduling.py::test_failed_enqueue_loses_no_check` |
| Two schedulers never claim the same monitor | `test_scheduling_repository.py::test_two_schedulers_never_claim_the_same_monitor` |
| No database connection is held during a check | `test_no_database_connection_is_held_during_the_check` |
| The same check stored twice is one row | `test_checks_repository.py::test_the_same_check_twice_stores_one_row` |
| The heartbeat only moves when a tick commits | `test_an_empty_tick_still_moves_the_heartbeat`, `test_a_failed_enqueue_does_not_move_the_heartbeat` |
| Those Phase 4 tests really detect the gap | Checked on 2026-10-27/28 by breaking the code on purpose: holding the session during the check, logging the URL, a stronger lock, an error carrying the password and stamping the heartbeat before enqueueing all made the matching test fail |
| Paging the history never skips or repeats a check, even when one arrives meanwhile | `test_api_checks.py::test_new_checks_do_not_shift_the_next_page`, `test_history_pages_cover_every_check_once_in_order` |
| A forged cursor is a 422 that does not echo it, and never reaches another monitor | `test_forged_cursor_is_422_without_echoing_it`, `test_a_cursor_never_reaches_another_monitor`, `test_cursors.py::test_forged_cursors_are_rejected` |
| No data is reported as `null` uptime, never 0 % or 100 % | `test_stats_without_data_say_so` |
| A stale last check is not reported as current | `test_stale_last_check_is_unknown`, `test_status.py::test_a_stale_check_is_unknown` |
| Retention never deletes a recent check, not even through a reused row address | `test_delete_expired_checks_keeps_recent_ones`, `test_an_address_reused_by_a_recent_check_is_never_deleted` (it fails without the date recheck) |
| A cleanup run stops at its time budget | `test_retention.py::test_stops_at_the_time_limit_and_finishes_next_run` |
| The scheduler keeps a slot while checks and cleanup are busy | `test_queue_broker.py::test_scheduler_keeps_its_slot_while_checks_and_cleanup_are_busy` (real Valkey). Checked on 2026-10-28: with `checks` limited to 31, the scheduler did not run within 3 s |
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
| 2026-10-27 | `python -m pulseops.checker` inside the API container | `https://www.google.com` up (200), so the image's system CA certificates work with httpx2/truststore; `https://httpbin.org/status/404` → `http_error` 404; `https://expired.badssl.com` → `ssl_error`; `http://169.254.169.254/` and `http://postgres:5432/` → `blocked_target` |
| 2026-10-27 | Full checker verification inside the API container, 21 real cases | **20/20 meaningful cases as expected**. Up with plausible latency: Google 200 (163 ms); `http://github.com` → https 200 (232 ms); httpbin `/redirect/3` 200 (1378 ms, 4 fresh TLS connections). `http_error`: `/redirect/6`, 404, 500. `ssl_error`: expired, wrong host, self-signed, untrusted root (badssl.com). `dns_error`: `.invalid`. `blocked_target`: `169.254.169.254`, `postgres`, `127.0.0.1:8000`, `[::ffff:127.0.0.1]`, and public names resolving to internal IPs (`169.254.169.254.nip.io`, `10.0.0.5.nip.io`, `localtest.me`). `ALLOW_PRIVATE_TARGETS=true` → `http://api:8000/health` up (20 ms). `HTTP(S)_PROXY` set to a dead proxy → Google still up (proxy ignored). No `blocked_target` detail contains an IP |
| 2026-10-27 | `https://httpbin.org/redirect-to?url=http://169.254.169.254/` | Not usable: httpbin (and httpbingo) now answer 403 to redirects outside an allow-list, so the checker correctly reports `http_error` 403. Redirects to internal IPs are covered by `test_redirect_to_internal_ip_is_blocked` and `test_dns_rebinding_is_blocked` against real local servers |
| 2026-10-27 | `scripts/smoke_test.py` against the live stack | **22/22**; none of its monitors left behind |
| 2026-10-27 | `https://example.com` from the development network | Down: the connection to its Cloudflare addresses is reset (also with plain `curl`); other sites, Cloudflare-hosted ones included, are up. A network-path issue, not a checker bug |
| 2026-10-27 | Migration `0002` on a database with monitors | The existing monitor got one check for its overdue slot (`scheduled_at` = the migration time), not a backlog (ADR-040) |
| 2026-10-27 | Worker end to end in Compose: monitor created through the API (`https://www.google.com/?e2e=1`, 30 s) | First check 2 s after creation, `scheduled_at` equal to `created_at`; second exactly 30 s later. Both up (200). The worker's log lines show the `public_id`, never the URL. Checked with `psql` as `pulseops_app` |
| 2026-10-28 | Scheduler heartbeat in the live stack | `scheduler_heartbeat.last_success_at` 4 s old, read as `pulseops_app` |
| 2026-10-28 | `kill -9` of the worker's process (restart policy) | Docker restarted it (restart count 0 → 1) and the worker came back up |
| 2026-10-27 23:33 UTC | `https://example.com` again (checker in the container and `curl` on the host) | Still down: connection reset by its Cloudflare addresses (`2606:4700:…`); Google up (200). It was outside football match hours, so "blocked only during matches" is not confirmed. Cause stays on the network path |
| 2026-10-27 | ArdiQ: a second `app.run()` in burst mode on the same app | Returns at once and leaves the task queued (`queue_size` 1); a new `Ardiq` instance processes it. Same result on Redis 7.4.12 and Valkey 9.1.2. Reported upstream by the project owner (see "Upstream issues") |
| 2026-10-28 | `scripts/smoke_test.py` against the live stack (Phase 5) | **29/29**. A new monitor got its first automatic check in 5 s; `/stats` up with 100 % uptime; forged cursor 422; unknown period 422; paused status; none of its monitors left behind |
| 2026-10-28 | `ardiq status` in the live worker | Lanes `scheduler`, `maintenance`, `checks`; crons `schedule_due_checks` (every 5 s) and `delete_expired_checks` (next run on the hour) |
| 2026-10-28 | Query measurement, see "Query performance" | `/stats` 30 days ~19-20 ms; history page ~1.7 ms; batch delete never scans the whole table |
| 2026-10-28 | Phase 5 tested by the project owner from Swagger | Stats; history followed with `next_cursor` to the end; forged cursor 422; a failing monitor shown as `down`; paused; `unknown` with the worker stopped |
| 2026-10-28 11:23 UTC | `https://example.com` from a second, unrelated network (another router) | Still down the same way: connection reset after ~40 ms, with `curl` on the host and with the checker in the container. With two different networks failing alike, the router is ruled out; the cause is upstream (provider) or on the development machine itself. Google up; smoke test 29/29 on the same network |
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
| httpcore2 does the TLS handshake with the origin hostname (`server_hostname`), not the connected IP | Pinning the IP keeps HTTPS working (SNI and certificate checks use the name) |
| httpx2 reports TLS failures as `ConnectError`; the `ssl.SSLError` is in the cause chain | The checker walks the chain to tell `ssl_error` from `connection_error` |
| httpx2's default client obeys `HTTP(S)_PROXY` | The checker sets `trust_env=False` |
| Coverage under SQLAlchemy async misses lines after database calls unless `concurrency = ["greenlet", "thread"]` | Set in `pyproject.toml`; `api/monitors.py` went from a false 80 % to 100 % |
| `asyncio.Server.wait_closed()` waits for open connections | Test servers call `close_clients()` (Python 3.13); suite time 35 s → 0.6 s |
| trustme 1.2.1 issues expired certificates (`not_after`) | Expired-certificate test runs offline |
| httpx2 logs `HTTP Request: GET <full URL>` at INFO for every request and redirect; httpcore2 traces at DEBUG | The checker raises both loggers to WARNING (ADR-044) |
| SQLAlchemy puts query parameters in error messages unless the engine has `hide_parameters=True` | Set on the app engine (ADR-044) |
| PostgreSQL does not keep a CTE's order in `UPDATE … RETURNING` | Claimed monitors are sorted in Python (a test was flaky before) |
| A claim with `FOR UPDATE` blocks inserting a check for that monitor (foreign key share lock); `FOR NO KEY UPDATE` does not | The claim uses `FOR NO KEY UPDATE SKIP LOCKED` (ADR-039) |
| `ALTER TABLE … ADD COLUMN … NOT NULL DEFAULT now()` does not rewrite the table in PostgreSQL 18 (same file node, `atthasmissing = true`) | Migration `0002` is cheap on a large `monitors` table |
| ArdiQ 1.2.0 deduplicates a custom `task_id` only while the task exists; after it finishes, the same id runs again | `ON CONFLICT DO NOTHING` is still needed (ADR-041) |
| ArdiQ 1.2.0 `expire_ms` drops a task not started in time (status `not_found`) | Stale checks are dropped (ADR-041) |
| ArdiQ's `BrokerError`/`ArdiqError` messages do not include the Redis password (`timed out`, `Password authentication failed`) | Safe to log the scheduler's error |
| ArdiQ has no connection timeout option: an unreachable broker fails after ~16 s, a wrong password after ~9.5 s | The password-log test takes ~10 s |
| `ardiq.testing.inline` ignores delays and `expire_ms` | Expiry and dedup are tested against real Valkey |
| `ardiq run` configures root logging at INFO | Third-party INFO logs (httpx2) reach the worker's output unless silenced |
| `DELETE … WHERE (monitor_id, scheduled_at) IN (SELECT … LIMIT n)`: depending on the statistics sample, PostgreSQL 18 picked either a nested loop over the primary key (~9 ms per 5,000 rows) or a hash semi join over a full table scan (~99 ms on 892,810 rows) | Batch deletes go by `ctid` (TID scan, no join) |
| `x = ANY ((SELECT …))` is still a subquery comparison in PostgreSQL (`tid = tid[]` error), even with double parentheses; `x = ANY (ARRAY(SELECT …))` is an array comparison | The delete uses `func.array(subquery)`, which renders `array((SELECT …))` |
| PostgreSQL 18 uses a B-tree skip scan on `(monitor_id, scheduled_at)` for `scheduled_at < X` (one index search per monitor: 11 with 10 monitors, 1,001 with 1,000) | For the hourly cleanup it beats the BRIN index at these sizes; with a backlog, the BRIN index is used |
| Only a table's owner can `ANALYZE` it | The measurement script runs `ANALYZE` as `pulseops_owner` |
| SQLAlchemy 2.1 compiles `percentile_cont(…).within_group(…).filter(…)` to `percentile_cont(…) WITHIN GROUP (ORDER BY …) FILTER (WHERE …)` | Mean and p95 in one query |
| ArdiQ lane limits hold: with limits 30 + 1 out of 32 slots, a third lane always gets a slot; with 31 + 1 it gets none | `checks` limited to 30 (ADR-051) |
| 17 decimal digits of microseconds reach the year 5138 | The cursor allows at most 17 digits |

## Query performance (2026-10-28)

`uv run python scripts/measure_queries.py` on the test database (PostgreSQL 18.6 in Docker, development machine). Default shape: 10 monitors × 31 days of checks every 30 s, **892,810 checks** inserted in time order, 28,810 past retention. Times are the median of 20 real runs unless marked as EXPLAIN.

| Query | Time | Plan |
|---|---|---|
| `/stats`, 30 days (86,400 checks of one monitor) | **~19-20 ms** | Bitmap index scan on `pk_checks` |
| `/stats`, 7 days | ~5.6 ms | Bitmap index scan on `pk_checks` |
| `/checks`, first page and a page 15 days back | **~1.7 ms** | Backward index scan on `pk_checks` (0.03 ms in EXPLAIN) |
| Retention batch (5,000) with a backlog | 2.4-39 ms (EXPLAIN) | BRIN index (`ix_checks_scheduled_at_brin`) + TID scan with the date recheck |
| Retention batch, hourly steady state | 0.7-1.3 ms (EXPLAIN) | Primary key skip scan (11 index searches) + TID scan with the date recheck |
| Full retention run, 28,810 expired checks | **0.09-0.27 s** (6 batches) | — |

Other shapes, same script:

| Shape | Result |
|---|---|
| 1,000 monitors × 31 days every hour (745,000 checks) | Hourly batch: primary key skip scan with 1,001 index searches, 4.8 ms. Backlog batch: BRIN index. `/stats` 30 days: 2.1 ms |
| 10 monitors × 40 days every 30 s (1,152,010 checks, 288,010 expired: a 10-day backlog) | Full retention run: **3.07 s**, 58 batches (~53 ms each), BRIN index |

No measured run of the batch delete in its final form (by `ctid`) contains a sequential scan.

## Verified versions (2026-10-28)

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
| Redis (only to reproduce an ArdiQ issue) | 7.4.12 |
| Docker / Compose | 29.9.2 / v5.6.1 |

## Size (2026-10-28, after Phase 5)

| Metric | Value | Command |
|---|---|---|
| Commits on `main` | 59 | `git rev-list --count main` |
| Non-blank lines in `src/` | 1774 (1394 after Phase 4) | `find src -name '*.py' \| xargs cat \| grep -cv '^\s*$'` |
| Non-blank lines in `tests/` | 2082 (1610 after Phase 4) | same, on `tests` |
| ADRs | 52 | `grep -c "^## ADR-" docs/decisions.md` |
| Merged PRs | 6 | `gh pr list --state merged` |

## Upstream issues

Problems found in libraries, reported by the project owner. Each row is added once the issue is open.

| Library | Issue | Status |
|---|---|---|
| ArdiQ | [#9](https://github.com/17tayyy/ardiq/issues/9) — Docs: custom `task_id` deduplication only lasts while the task exists | Open (2026-10-28) |
| ArdiQ | [#10](https://github.com/17tayyy/ardiq/issues/10) — Security: examples publish Redis on all interfaces (0.0.0.0) without a password | Open (2026-10-28) |
| ArdiQ | [#11](https://github.com/17tayyy/ardiq/issues/11) — A second `app.run()` in burst mode on the same instance exits without processing the queue | Open (2026-10-28) |
