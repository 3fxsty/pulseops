# PulseOps

Uptime monitoring for websites and APIs: periodically checks whether they respond, how long they take, and keeps the history to compute availability.

> Work in progress — see [`docs/decisions.md`](docs/decisions.md) for the design decisions so far.

## Quick start

Requirements: Docker with Docker Compose.

```bash
docker compose up --build
```

- API health check: <http://localhost:8000/health>
- Swagger UI: <http://localhost:8000/docs>

## Development

Requirements: [uv](https://docs.astral.sh/uv/).

```bash
uv sync                # install dependencies (Python 3.13 is fetched automatically)
uv run pytest          # run the tests
uv run ruff check .    # lint
uv run ruff format .   # format
```
