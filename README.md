# PulseOps

[![CI](https://github.com/3fxsty/pulseops/actions/workflows/ci.yml/badge.svg)](https://github.com/3fxsty/pulseops/actions/workflows/ci.yml)

Uptime monitoring for websites and APIs. Add a URL and PulseOps checks it on its own, every 30 seconds or more, keeps 30 days of history and tells you how the site has been doing: current status, uptime and response times.

Version 0.1.0 is the MVP: an HTTP API with Swagger UI, a worker that runs the checks, PostgreSQL and Valkey, all started with one `docker compose up`. It is a portfolio project focused on backend and DevOps practice:

- every design decision is recorded, with the options that were rejected, in [`docs/decisions.md`](docs/decisions.md);
- every verified fact (test counts, measurements, library behaviour) is recorded, with how to reproduce it, in [`docs/evidence.md`](docs/evidence.md).

> [!WARNING]
> PulseOps is **not yet meant to be exposed to the internet**. The API listens on `127.0.0.1` only, and the secure deployment (reverse proxy, HTTPS, rate limits) arrives in Phase 9. Until then, run it on your own machine or a trusted network. To report a vulnerability, see [`SECURITY.md`](SECURITY.md).

![Swagger UI with the PulseOps endpoints](docs/images/swagger.png)

## Features

- **Monitors:** create, list, edit, pause and delete them, each with its own interval (30 s minimum).
- **Automatic checks:** a site is down if it does not answer, returns 4xx/5xx or takes more than 10 s.
- **History and statistics:** every check is kept for 30 days. `/stats` gives the current status, uptime, and mean and p95 response times over the last 24 hours, 7 days or 30 days.
- **Incidents and alerts:** two failed checks in a row open an incident and two successful ones close it, so a single hiccup or a flapping site never pages anyone. Optional Telegram alerts announce the start and the end, and are retried if Telegram fails.
- **Safe by default:** API key, SSRF protection on every connection, least-privilege database roles, and neither secrets nor monitored URLs in any log.
- **Tested:** automated tests against real PostgreSQL and Valkey, and CI that builds and smoke-tests the whole stack on every pull request. Current test counts, coverage and measurements are in [`docs/evidence.md`](docs/evidence.md).

## Architecture

```mermaid
flowchart LR
    client([Client or Swagger UI])
    site([Monitored site])

    subgraph compose [docker compose]
        api[API<br/>FastAPI]
        pg[(PostgreSQL<br/>monitors, schedule,<br/>check history,<br/>incidents, alerts)]
        valkey[(Valkey<br/>task queue)]
        subgraph worker [Worker: ArdiQ]
            scheduler[Scheduler<br/>every 5 s]
            check[Check task]
            delivery[Alert delivery<br/>every 5 s]
            retention[Retention<br/>every hour]
        end
        migrate[migrate<br/>one-shot]
    end
    telegram([Telegram])

    client -- "HTTP + X-API-Key" --> api
    api -- "monitors, history, stats" --> pg
    scheduler -- "claim due monitors" --> pg
    scheduler -- "enqueue checks (ids only)" --> valkey
    valkey -- "deliver" --> check
    check -- "GET, SSRF-checked" --> site
    check -- "store the outcome,<br/>open or close incidents" --> pg
    delivery -- "pending alerts" --> pg
    delivery -- "Bot API, HTTPS" --> telegram
    retention -- "delete old checks<br/>and incidents" --> pg
    migrate -. "schema, as the owner role" .-> pg
```

- **The API never talks to the queue.** It only reads and writes PostgreSQL, so it never holds the Valkey password.
- **The schedule lives in PostgreSQL, not in the queue.** Every 5 s, the scheduler claims the monitors that are due, moves each one to its next slot and enqueues their checks, all in one transaction. If Valkey is lost, at most one check per monitor is lost.
- **Checks are idempotent.** A check is stored under `(monitor, slot)`, so a task delivered twice is stored once.
- **Alerts go through an outbox.** An incident and its pending alert are written in the same transaction as the check; the delivery cron sends it afterwards and retries it if Telegram fails. An alert is never lost between the two, and only the worker holds the bot token.
- **`migrate` runs first** and exits: it applies the database migrations as the schema owner, and the API and the worker start only after it succeeds.

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
- Swagger UI: <http://localhost:8000/docs>. Click **Authorize** and paste your `API_KEY`. The docs are off unless `DOCS_ENABLED=true`, which `.env.example` sets for development.

## Example

```bash
API_KEY=…  # the one in .env
curl -s -X POST http://127.0.0.1:8000/api/v1/monitors \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"name": "Google", "url": "https://www.google.com", "interval_seconds": 30}'
# a few minutes later
curl -s "http://127.0.0.1:8000/api/v1/monitors/<id>/stats?period=24h" -H "X-API-Key: $API_KEY"
```

A real response, from a monitor checking Google every 30 s for about six minutes:

```json
{
  "status": "up",
  "last_check": {
    "scheduled_at": "2026-10-28T12:07:10.452511Z",
    "is_up": true,
    "status_code": 200,
    "response_time_ms": 236,
    "error_kind": null,
    "error_detail": null
  },
  "period": "24h",
  "from": "2026-10-27T12:07:39.354335Z",
  "to": "2026-10-28T12:07:39.354335Z",
  "uptime_percent": 100.0,
  "avg_response_time_ms": 245.6,
  "p95_response_time_ms": 301.0,
  "checks_total": 11,
  "checks_up": 11,
  "checks_down": 0
}
```

The same endpoint in Swagger UI, a few minutes later:

![A /stats response in Swagger UI](docs/images/stats.png)

## Design highlights

Each point links to the decision record that explains it, including the options that were rejected and why.

- **SSRF protection where it matters.** PulseOps visits URLs that users give it, so a URL must never reach an internal address (cloud metadata, the database, the host). URLs are validated when they are saved ([ADR-023](docs/decisions.md#adr-023--ssrf-protection-on-create-and-edit)) and again at every TCP connection, redirects included. The connection goes to the very IP that was validated, which defeats DNS rebinding ([ADR-031](docs/decisions.md#adr-031--ssrf-at-connect-time-ip-pinning-no-proxies)).
- **Only validated URLs can be stored.** The repository accepts a `ValidatedUrl`, a type that only the validation step can create ([ADR-030](docs/decisions.md#adr-030--validatedurl-only-validated-urls-reach-the-database)).
- **Least privilege in the database.** The app role reads and writes rows only; migrations run as a separate owner role; the superuser is never used by PulseOps ([ADR-014](docs/decisions.md#adr-014--migrations-one-shot-migrate-service-and-three-database-roles)).
- **A schedule that survives restarts.** One global scheduler claims due monitors with `FOR NO KEY UPDATE SKIP LOCKED` and enqueues before it commits, so a failed enqueue loses nothing ([ADR-039](docs/decisions.md#adr-039--scheduling-one-global-scheduler-the-schedule-in-postgresql)). Missed slots are skipped, not piled up ([ADR-040](docs/decisions.md#adr-040--next-slot-missed-periods-and-rescheduling-on-edit)).
- **Idempotent check tasks.** Tasks carry ids only (never the URL), hold no database connection while they check, and insert with `ON CONFLICT DO NOTHING` ([ADR-041](docs/decisions.md#adr-041--the-check-task-idempotent-ids-only-no-connection-held)).
- **URLs and secrets stay out of the logs**, since URLs may carry tokens: not in the worker's lines, not in the HTTP client's, not in SQLAlchemy's errors, not in PostgreSQL's error log ([ADR-044](docs/decisions.md#adr-044--secrets-and-urls-stay-out-of-the-logs)).
- **Honest statistics.** Uptime is counted in checks, and a period without data is `null`, neither 0 % nor 100 % ([ADR-046](docs/decisions.md#adr-046--uptime-is-counted-in-checks-no-data-is-not-a-number)). The history is paged with opaque, strictly decoded cursors ([ADR-050](docs/decisions.md#adr-050--opaque-history-cursors)).
- **Retention without full scans.** Old checks are deleted hourly in short batches by physical row address, on a queue lane of their own ([ADR-051](docs/decisions.md#adr-051--retention-hourly-batch-deletes-on-a-dedicated-lane)).
- **A hardened CI.** Read-only token, actions and Docker images pinned by SHA and digest, and secrets generated for each run (see [Continuous integration](#continuous-integration)).

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
| GET | `/api/v1/monitors/{id}/stats?period=7d` | Current status, uptime and response times over `24h`, `7d` or `30d`, and the open incident if any (`open_incident`) |
| GET | `/api/v1/monitors/{id}/incidents?limit=50&cursor=…` | A monitor's incidents, newest first |
| GET | `/api/v1/incidents?state=open&limit=50&cursor=…` | Incidents across monitors, each with its monitor's `id` and `name`. `state` is `open` or `resolved`; without it, both |

Two probes need no API key: `GET /health` (the API process is up) and `GET /health/scheduler`, for an outside monitor: `200 {"status": "ok"}` if the scheduler completed a tick in the last 60 s, otherwise `503` with `stale` (or `unavailable` if the database does not answer within 3 s). It never shows a timestamp and is sent with `Cache-Control: no-store`.

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

## Incidents and alerts

An **incident** is an outage of a monitor, with a start and an end:

- **It opens after 2 failed checks in a row** and closes after 2 successful ones. Its start is the first failed check and its end the first successful one, so its duration is the real outage. A gap of more than 2 intervals + 60 s between checks (the worker was stopped) breaks a streak.
- **Pausing a monitor or changing its URL** closes its open incident as `paused` or `monitor_changed`, without a "recovered" alert.
- **Incidents are kept for a year** (checks, 30 days), as the long-term history of outages.

**Alerts** go to one Telegram chat, as plain text:

```
🔴 DOWN: Shop API
Since: 2026-11-03 12:00:00 UTC
Cause: http_error (HTTP 503)
Monitor: 01970000-0000-7000-8000-000000000001
```

- **One "DOWN" and one "RECOVERED" per incident.** A "RECOVERED" always goes out, and never before its "DOWN". A late "DOWN" whose incident is already over is skipped: the "RECOVERED" carries the start and the duration.
- **Never the monitor's URL nor the error detail**, which may carry tokens: Telegram is an outside service that keeps the messages.
- **Retries:** a network error, a timeout, a 429 or a 5xx is retried, waiting 10 s, 20 s, 40 s… up to an hour, for at most 20 attempts or 24 h. Any other answer (an invalid token, an unknown chat, a blocked bot) fails at once, with an ERROR in the worker's log that says what to fix.
- **Optional:** without a bot, incidents are still recorded and their alerts are skipped (not sent later).

To set up a bot:

1. In Telegram, talk to [@BotFather](https://t.me/BotFather), send `/newbot` and choose a name. It answers with the bot's **token**. Treat it like a password.
2. Send any message to your new bot (or add it to a group). Then open `https://api.telegram.org/bot<token>/getUpdates` in a private browser window (the URL holds the token, so keep it out of your history): the **chat id** is the `"id"` inside `"chat"` (negative for groups).
3. Put both in `.env` and recreate the worker:

```bash
TELEGRAM_BOT_TOKEN=<token>
TELEGRAM_CHAT_ID=<chat id>
```

```bash
docker compose up -d worker
docker compose exec worker python -m pulseops.alerts test   # sends a test message
```

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

### Continuous integration

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every pull request and on every push to `main`, with three jobs in parallel:

| Job | What it checks |
|---|---|
| Lint | `ruff check` (security rules included) and `ruff format --check` |
| Tests | `alembic upgrade head` and `alembic check` on a fresh database, then `pytest --cov` (fails below 95 %), against PostgreSQL and Valkey started from `docker-compose.yml` |
| Full stack | `docker compose up --build --wait` (image, migrations, API, worker) and the smoke test against it |

- **Secrets:** `scripts/ci_env.py` writes a fresh `.env` from `.env.example` for every run, with random values masked in the logs. No password lives in the repository.
- **Hardening:**
  - the workflow's token is read-only;
  - actions are pinned to a commit SHA, and Docker images to a digest;
  - Dependabot keeps those pins, the Python dependencies and the images up to date;
  - there is no `pull_request_target`.

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
4. **Each stored check may open or close an incident**, in the same transaction (see [Incidents and alerts](#incidents-and-alerts)). Checks of one monitor take turns, and a check that arrives late is kept in the history but never decides.
5. **Every 5 s, the alert delivery** sends the pending alerts, on its own `alerts` lane.
6. **Every successful scheduler tick stamps `scheduler_heartbeat`**, even when nothing is due, so a stalled scheduler can be detected (`GET /health/scheduler`).
7. **Every hour, checks older than 30 days are deleted** in batches of 5,000, for at most 60 s per run (the rest goes in the next run), and then the incidents resolved more than a year ago.
   - It runs on its own `maintenance` lane, so a long cleanup never delays the scheduler.
   - Each batch deletes by physical row address, so it never scans the whole table.

The worker's logs show one line per check with the monitor's public id, up/down, the error kind, the response time and whether it opened or resolved an incident. They never show the URL, which may carry tokens, nor the bot token:

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

`scripts/measure_queries.py` seeds the test database with realistic history (by default, 10 monitors × 31 days of checks every 30 s), times the history, stats and retention queries, prints their plans, and deletes everything it created:

```bash
uv run python scripts/measure_queries.py            # summary
uv run python scripts/measure_queries.py --plans    # with full EXPLAIN ANALYZE plans
uv run python scripts/measure_queries.py --monitors 1000 --interval 3600   # other shapes
```

Measured results are recorded in [`docs/evidence.md`](docs/evidence.md).

## Roadmap

Done after the MVP: incidents, Telegram alerts and `/health/scheduler`. Next, in order:

1. **UI and metrics:** Grafana and/or an HTMX page; Prometheus metrics.
2. **Deployment:** a VPS behind Nginx or Caddy, with HTTPS and automatic deploys, and an outside monitor on `/health/scheduler`.
3. **Extras:** users and login instead of the API key, a public status page.

## License

[MIT](LICENSE) © 2026 3fxsty
