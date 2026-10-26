# PulseOps

Uptime monitoring for websites and APIs: periodically checks whether they respond, how long they take, and keeps the history to compute availability.

> Work in progress — see [`docs/decisions.md`](docs/decisions.md) for the design decisions so far.

## Quick start

Requirements: Docker with Docker Compose.

```bash
cp .env.example .env   # then replace every change-me value
docker compose up --build
```

Compose refuses to start without the secrets in `.env`. On start-up, the one-shot `migrate` service applies the database migrations and exits. The API starts only after it succeeds.

- API health check: <http://localhost:8000/health>
- Swagger UI: <http://localhost:8000/docs>

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
uv run ruff check .    # lint, including security rules
uv run ruff format .   # format
```
