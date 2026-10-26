# Architecture Decision Records

Every approved design or tooling decision is recorded here.
Format: context, options considered, decision, rationale.

---

## ADR-001 — Core stack

- **Date:** 2026-10 (pre-Phase 0)
- **Status:** Accepted

**Context.** PulseOps is a backend/DevOps portfolio project: an uptime monitor that periodically checks websites and APIs, measures response time and keeps a history to compute availability.

**Decision.**

| Concern | Choice |
|---|---|
| Language | Python 3.12+ |
| Project & dependency management | uv |
| API | FastAPI (automatic Swagger UI) |
| HTTP client for checks | httpx (async) — replaced by httpx2, see ADR-008 |
| Database | PostgreSQL |
| ORM & migrations | SQLAlchemy 2 (async) + Alembic |
| Tests | pytest |
| Lint & format | Ruff |
| CI | GitHub Actions |
| Containers | Docker + Docker Compose |
| MVP interface | Swagger UI |

**Rationale.** A fully async stack (FastAPI + httpx + async SQLAlchemy) fits a workload dominated by waiting on network I/O. uv and Ruff are fast, single-binary tools that replace several older ones (pip/venv/pyenv, flake8/isort/black). Docker Compose lets the whole system start with one command, both locally and in CI.

---

## ADR-002 — Task queue: ArdiQ

- **Date:** 2026-10 (pre-Phase 0)
- **Status:** Accepted

**Context.** Checks must run in the background, on a schedule, outside the API process.

**Options.** Celery, Taskiq, ARQ, ArdiQ.

**Decision.** ArdiQ 1.2.0 (Rust core, async, built on Redis Streams + Lua).

**Rationale.**
- Native async, matching the rest of the stack.
- Low memory footprint.
- Cron, retries and a dead letter queue included out of the box.
- Direct support from the author (issues and PRs are welcome).

**Consequences.**
- ArdiQ is isolated in `pulseops.queue` so it can be replaced without touching the rest of the code.
- Delivery is at-least-once: every task must be idempotent.
- Crons use `coalesce=True` so overdue checks are not piled up.

---

## ADR-003 — MVP business rules

- **Date:** 2026-10 (pre-Phase 0)
- **Status:** Accepted

**Decision.**
- A monitored site is **down** if it does not respond, returns a 4xx/5xx status, or takes **more than 10 s**.
- Check interval is configurable per monitor, **minimum 30 s**.
- Check history is retained for **30 days**; older rows are deleted automatically.

**Out of MVP scope:** alerts, incidents, visual interface, users/login, deployment.

---

## ADR-004 — Python version: 3.13

- **Date:** 2026-10-26 (Phase 0)
- **Status:** Accepted

**Context.** The stack requires Python 3.12+. The development machine ships Python 3.14.

**Options.**
1. **3.12** — most battle-tested, but nothing in the stack forces it.
2. **3.13** — newest version ArdiQ officially supports.
3. **3.14** — newest overall; ArdiQ's abi3 wheel installs, but 3.14 is not officially supported.

**Decision.** Python 3.13, pinned in `.python-version` and used by the Docker image (`python:3.13-slim`). uv manages the interpreter, independently of the system Python.

**Rationale.** Newest version supported by every dependency. Running an unsupported version would make it unclear whether a failure is ours or the runtime's.

---

## ADR-005 — Source layout: `src/pulseops/`

- **Date:** 2026-10-26 (Phase 0)
- **Status:** Accepted

**Options.**
1. **`src/` layout** — package under `src/pulseops/`.
2. **Flat layout** — package at the repository root.

**Decision.** `src/` layout (what `uv init --package` generates).

**Rationale.** Code cannot be imported by accident from the working directory, so tests run against the installed package, exactly as in the Docker image. Packaging mistakes surface locally instead of inside the container.

---

## ADR-006 — Local Docker: Docker Engine inside WSL

- **Date:** 2026-10-26 (Phase 0)
- **Status:** Accepted

**Context.** Development happens on Windows + WSL (Ubuntu). Docker was not installed.

**Options.**
1. **Docker Engine in WSL** — native Linux install.
2. **Docker Desktop** — Windows app with WSL integration and a GUI.

**Decision.** Docker Engine installed natively in WSL.

**Rationale.** Free, lighter, and identical to what will run on the Linux production VPS, so the workflow carries over to deployment (Phase 9).

---

## ADR-007 — Broker: Valkey or Redis

- **Date:** 2026-10-26 (Phase 0)
- **Status:** Accepted

**Context.** ArdiQ only uses features present in Redis 7.2, which Valkey is based on, but Valkey is not officially tested.

**Options.**
1. **Valkey** — open-source (BSD) fork of Redis 7.2, maintained under the Linux Foundation.
2. **Redis** — the officially tested broker for ArdiQ.

**Plan agreed beforehand.** Run Valkey in Docker Compose and execute `ardiq doctor`. If it passes, use Valkey; otherwise switch to Redis (one-line change) and report it to the ArdiQ author.

**Result.** `ardiq doctor` against `valkey/valkey:9` (Valkey 9.1.2, reports Redis-compatible version 7.2.4) passed every check: connection, version, key writes and Lua scripts. The only warning was "no live workers", which is expected before Phase 4.

**Decision.** Valkey.

**Rationale.** Fully compatible with what ArdiQ needs, and truly open-source. Switching to Redis later only means changing the image in `docker-compose.yml`.

---

## ADR-008 — HTTP client: httpx2 instead of httpx

- **Date:** 2026-10-26 (Phase 0)
- **Status:** Accepted (supersedes the httpx entry in ADR-001)

**Context.** Starlette (FastAPI's foundation) deprecated using `httpx` in its test client and recommends `httpx2`. `httpx` itself is not deprecated, but it is no longer actively maintained. Since httpx is also the client that performs every uptime check, staying on an unmaintained library is a risk.

**Options.**
1. **Keep httpx** — works today, but unmaintained and flagged by Starlette.
2. **Switch to httpx2** — actively maintained successor (by the Pydantic organization), same programming model.

**Decision.** httpx2 (2.16.0) for both the checker and the API test client.

**Rationale.** Actively maintained and the client Starlette now expects. The switch is cheap because no check code exists yet.

**Consequences.** httpx2 verifies TLS certificates against the operating system's trust store (through `truststore`), so the Docker image must ship the system CA certificates. `python:3.13-slim` already includes `ca-certificates`; an HTTPS request from inside the container was verified to work.
