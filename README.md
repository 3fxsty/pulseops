# PulseOps

Uptime monitoring for websites and APIs: periodically checks whether they respond, how long they take, and keeps the history to compute availability.

> Work in progress — see [`docs/decisions.md`](docs/decisions.md) for the design decisions so far.

## Quick start

Requirements: Docker with Docker Compose.

```bash
cp .env.example .env   # then replace every change-me value
docker compose up --build
```

Compose refuses to start without the secrets in `.env`, and the API refuses to start without a valid `API_KEY` (at least 32 characters, e.g. `openssl rand -base64 32`). On start-up, the one-shot `migrate` service applies the database migrations and exits. The API starts only after it succeeds.

The API listens on `127.0.0.1:8000` only.

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

URLs are stored normalized. They are refused when they embed credentials or point to private, internal or reserved addresses (SSRF protection; set `ALLOW_PRIVATE_TARGETS=true` for installs that must check a private network).

Errors use [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) Problem Details (`application/problem+json`) with a stable `code`:

| Status | `code` |
|---|---|
| 401 | `unauthorized` |
| 404 | `monitor_not_found`, `not_found` |
| 409 | `monitor_url_conflict` |
| 422 | `validation_error`, `url_credentials_not_allowed`, `url_target_not_allowed` |
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

Requirements: [uv](https://docs.astral.sh/uv/), and PostgreSQL running (`docker compose up -d postgres`) for the tests.

```bash
uv sync                # install dependencies (Python 3.13 is fetched automatically)
uv run pytest          # run the tests (against the separate pulseops_test database)
uv run pytest --cov    # same, with a coverage report
uv run ruff check .    # lint, including security rules
uv run ruff format .   # format
```

With the stack running (`docker compose up -d`):

```bash
# Check one URL exactly as PulseOps will (prints JSON; exit 0 = up, 1 = down)
docker compose exec api python -m pulseops.checker https://www.google.com

# Smoke test: the manual test list against the live API (needs internet access).
# It only touches the monitors it creates, and deletes them afterwards.
uv run python scripts/smoke_test.py
```

## Checker

A site is **down** if it does not answer, returns 4xx/5xx, or takes more than 10 s (one deadline for DNS, connection, TLS, up to 5 redirects and the final headers). The body is never downloaded. Every TCP connection, including each redirect, is SSRF-checked at connect time and pinned to the validated IP. Failures are classified as `timeout`, `dns_error`, `connection_error`, `ssl_error`, `http_error` or `blocked_target`.
