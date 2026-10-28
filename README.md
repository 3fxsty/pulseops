# PulseOps

Uptime monitoring for websites and APIs: periodically checks whether they respond, how long they take, and keeps the history to compute availability.

> Work in progress — see [`docs/decisions.md`](docs/decisions.md) for the design decisions so far.

## Quick start

Requirements: Docker with Docker Compose.

```bash
cp .env.example .env   # then replace every change-me value
docker compose up --build
```

Compose refuses to start without the secrets in `.env`, and the API refuses to start without a valid `API_KEY` (at least 32 characters, e.g. `openssl rand -base64 32`). On start-up, the one-shot `migrate` service applies the database migrations and exits. The API and the worker start only after it succeeds.

| Service | Role | Exposed on |
|---|---|---|
| `api` | FastAPI: manage monitors | `127.0.0.1:8000` |
| `worker` | ArdiQ: schedules and runs the checks, deletes old history | — |
| `postgres` | Monitors and check history | `127.0.0.1:5432` (for tests) |
| `valkey` | ArdiQ's queue | `127.0.0.1:6380` (for tests) |
| `migrate` | Applies migrations once, then exits | — |

Every long-running service restarts on its own after a crash (`restart: unless-stopped`).

- API health check: <http://localhost:8000/health>
- Swagger UI: <http://localhost:8000/docs>. Click **Authorize** and paste your `API_KEY`.

## API

Every `/api/v1` endpoint requires the `X-API-Key` header.

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/monitors` | Create a monitor (201 + `Location`) |
| GET | `/api/v1/monitors?limit=50&offset=0&is_active=true` | List monitors, paginated |
| GET | `/api/v1/monitors/{id}` | Get a monitor |
| PATCH | `/api/v1/monitors/{id}` | Change only the fields sent (e.g. `{"is_active": false}` to pause) |
| DELETE | `/api/v1/monitors/{id}` | Delete a monitor and its check history |
| GET | `/api/v1/monitors/{id}/checks?limit=50&cursor=…` | Check history, newest first. Pass `next_cursor` as `cursor` for the next page |
| GET | `/api/v1/monitors/{id}/stats?period=7d` | Current status, uptime and response times over `24h`, `7d` or `30d` |

### Status and statistics

`/stats` answers "how has this site been doing?":

- **`status`:** `up` or `down` from the latest check; `paused` if the monitor is inactive; `unknown` if there is no check yet or the latest is older than 2 intervals + 60 s (the worker may be stopped).
- **`uptime_percent`:** checks up / checks in the period × 100 (3 decimals). It is `null` when the period has no checks: no data is neither 0 % nor 100 %.
- **`avg_response_time_ms` and `p95_response_time_ms`:** over the checks that were up.
- **Counts:** `checks_total`, `checks_up` and `checks_down`.

The history is paginated with an opaque cursor, so pages never shift when new checks arrive. A cursor that was not issued by the API gets a 422 `invalid_cursor`.

URLs are stored normalized. They are refused when they embed credentials or point to private, internal or reserved addresses (SSRF protection; set `ALLOW_PRIVATE_TARGETS=true` for installs that must check a private network).

Errors use [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) Problem Details (`application/problem+json`) with a stable `code`:

| Status | `code` |
|---|---|
| 401 | `unauthorized` |
| 404 | `monitor_not_found`, `not_found` |
| 409 | `monitor_url_conflict` |
| 422 | `validation_error`, `url_credentials_not_allowed`, `url_target_not_allowed`, `invalid_cursor` |
| 500 | `internal_error` |

## Database

PostgreSQL uses three roles (least privilege, see ADR-014):

| Role | Used by | Can do |
|---|---|---|
| `postgres` | Administration only | Everything (superuser) |
| `pulseops_owner` | `migrate` service, migration tests | Create and alter tables |
| `pulseops_app` | API and worker | Read and write rows only |

The roles and the `pulseops` / `pulseops_test` databases are created the first time the PostgreSQL volume is initialized. After changing role passwords in `.env`, recreate the volume with `docker compose down -v`. This deletes all data.

Inspect the schema:

```bash
docker compose exec postgres psql -U pulseops_owner -d pulseops -c '\d monitors'
docker compose exec postgres psql -U pulseops_owner -d pulseops -c '\d checks'
```

Migrations, run from the host while PostgreSQL is up:

```bash
uv run alembic upgrade head                                 # apply pending migrations
uv run alembic downgrade -1                                 # undo the last one
uv run alembic revision --autogenerate -m "describe change" # new migration; always review it by hand
uv run alembic check                                        # fail if models and migrations differ
```

## Development

Requirements: [uv](https://docs.astral.sh/uv/), and PostgreSQL and Valkey running (`docker compose up -d postgres valkey`) for the tests.

```bash
uv sync                # install dependencies (Python 3.13 is fetched automatically)
uv run pytest          # run the tests (pulseops_test database, Valkey logical database 1)
uv run pytest --cov    # same, with a coverage report
uv run ruff check .    # lint, including security rules
uv run ruff format .   # format
```

With the stack running (`docker compose up -d`):

```bash
# Check one URL exactly as PulseOps will (prints JSON; exit 0 = up, 1 = down)
docker compose exec api python -m pulseops.checker https://www.google.com

# Smoke test: the manual test list against the live API, worker included
# (needs internet access). It only touches the monitors it creates, and
# deletes them afterwards.
uv run python scripts/smoke_test.py
```

## Checker

A site is **down** if it does not answer, returns 4xx/5xx, or takes more than 10 s (one deadline for DNS, connection, TLS, up to 5 redirects and the final headers). The body is never downloaded. Every TCP connection, including each redirect, is SSRF-checked at connect time and pinned to the validated IP. Failures are classified as `timeout`, `dns_error`, `connection_error`, `ssl_error`, `http_error` or `blocked_target`.

## Automatic checks

The `worker` service runs the scheduler and the checks (ArdiQ on Valkey):

1. **Every 5 s, the scheduler** claims the active monitors whose `next_check_at` has come, moves each one to its next slot and enqueues one check per monitor.
   - The schedule lives in PostgreSQL, so losing the queue costs at most one check.
   - Missed slots (worker down) are skipped, not caught up.
2. **The worker runs each check** with the checker and stores the outcome in `checks`.
   - The `scheduled_at` of each check is the time it was due.
   - A re-delivered check is stored only once.
3. **A new monitor is checked within a few seconds.** Changing its URL or interval, or reactivating it, brings its next check forward to now. Pausing or deleting it stops its checks.
4. **Every successful scheduler tick stamps `scheduler_heartbeat`**, even when nothing is due, so a stalled scheduler can be detected.
5. **Every hour, checks older than 30 days are deleted** in batches of 5,000, for at most 60 s per run (the rest goes in the next run).
   - It runs on its own `maintenance` lane, so a long cleanup never delays the scheduler.
   - Each batch deletes by physical row address, so it never scans the whole table.

The worker's logs show one line per check with the monitor's public id, up/down, the error kind and the response time. They never show the URL, which may carry tokens:

```bash
docker compose logs -f worker
```

The checks are served by the API (`/checks` and `/stats`, see above). For a direct look, use `psql` as the app role:

```bash
# When the scheduler last completed a tick
docker compose exec postgres sh -c 'psql "postgresql://pulseops_app:$PULSEOPS_APP_PASSWORD@127.0.0.1/pulseops" -c "
  SELECT last_success_at, now() - last_success_at AS age FROM scheduler_heartbeat"'

# The queue: crons, lanes, workers
docker compose exec worker ardiq status pulseops.worker:app
```

## Performance

`scripts/measure_queries.py` seeds the test database with realistic history (10 monitors × 31 days every 30 s, ~893,000 checks), times the history, stats and retention queries, prints their plans, and deletes everything it created:

```bash
uv run python scripts/measure_queries.py            # summary
uv run python scripts/measure_queries.py --plans    # with full EXPLAIN ANALYZE plans
uv run python scripts/measure_queries.py --monitors 1000 --interval 3600   # other shapes
```

Measured results are recorded in [`docs/evidence.md`](docs/evidence.md).
