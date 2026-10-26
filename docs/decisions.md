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

---

## ADR-009 — PostgreSQL driver: asyncpg

- **Date:** 2026-10-26 (Phase 1)
- **Status:** Accepted

**Context.** SQLAlchemy needs a driver to talk to PostgreSQL. The whole stack is async.

**Options.**
1. **asyncpg** — async-only driver that speaks PostgreSQL's binary protocol.
2. **psycopg 3** — successor of psycopg2, supports both sync and async.

**Decision.** asyncpg (`postgresql+asyncpg://…`), used by the app and by Alembic (async migration template).

**Rationale.** The binary protocol is the most efficient option for the most write-heavy table (`checks`), and an async-only driver matches a 100 % async stack. Popularity was not a criterion.

---

## ADR-010 — Identifiers: internal integer + public UUID v7

- **Date:** 2026-10-26 (Phase 1)
- **Status:** Accepted

**Context.** Monitor identifiers end up in API URLs. Changing them later (e.g. when users arrive in Phase 10) would break every client.

**Options.**
1. **Integer only** — simple and compact, but enumerable and leaks how many monitors exist.
2. **UUID only** — opaque, but 16 bytes repeated in every row of `checks`.
3. **Integer internal key + UUID public id.**

**Decision.** Option 3.
- `monitors.id`: integer identity, used only internally and for foreign keys.
- `monitors.public_id`: UUID, NOT NULL, UNIQUE, `server_default=uuidv7()` (native in PostgreSQL 18).
- The API exposes only `public_id` (Phase 2).

**Rationale.** `monitor_id` is repeated in millions of check rows: 4 bytes instead of 16. The public id is stable and opaque from day one, and UUID v7 is time-ordered, so it indexes well.

---

## ADR-011 — `monitors` table

- **Date:** 2026-10-26 (Phase 1)
- **Status:** Accepted

**Decision.**

| Column | Type | Constraints |
|---|---|---|
| `id` | integer identity | PK |
| `public_id` | uuid | NOT NULL, UNIQUE, default `uuidv7()` |
| `name` | varchar(100) | NOT NULL |
| `url` | varchar(2048) | NOT NULL, UNIQUE (named constraint) |
| `interval_seconds` | integer | NOT NULL, CHECK 30–86400 |
| `is_active` | boolean | NOT NULL, default true |
| `created_at` | timestamptz | NOT NULL, default `now()` |
| `updated_at` | timestamptz | NOT NULL, default `now()`, `onupdate=func.now()` |

**Rationale.**
- **Database CHECKs as defence in depth:** invalid data is rejected even if API validation fails.
- **Named UNIQUE on `url`:** it will become unique per `(owner_id, url)` in Phase 10, and a predictable name makes that change trivial.
- **URL normalization** happens in the API (Phase 2).
- **`updated_at`** is set by SQLAlchemy on every UPDATE using the database clock (`func.now()`). All SQL goes through SQLAlchemy (see Security rules), so a trigger would only add hidden logic that `alembic check` cannot see.

**Deliberately left out.**
- `method`, `timeout_seconds`: the down rule is global and checks are always GET.
- `next_check_at`, `last_checked_at`: depend on the Phase 4 scheduling decision; they can be added with a later migration.

---

## ADR-012 — `checks` table: composite primary key

- **Date:** 2026-10-26 (Phase 1)
- **Status:** Accepted

**Context.** ArdiQ delivers tasks at least once, so a check may run twice. This is the largest and most write-heavy table.

**Options.**
1. **Surrogate `id` bigint** + `checked_at` — duplicates must be prevented in code.
2. **Composite PK `(monitor_id, scheduled_at)`**, no surrogate id.

**Decision.** Option 2.

| Column | Type | Constraints |
|---|---|---|
| `monitor_id` | integer | FK → `monitors.id` ON DELETE CASCADE; part of PK |
| `scheduled_at` | timestamptz | NOT NULL; part of PK — when the check was *due*, not when it actually ran |
| `is_up` | boolean | NOT NULL |
| `status_code` | smallint | NULL, CHECK 100–599 |
| `response_time_ms` | integer | NULL, CHECK >= 0 |
| `error_kind` | varchar(32) | NULL, CHECK IN (`timeout`, `dns_error`, `connection_error`, `ssl_error`, `http_error`, `blocked_target`) |
| `error_detail` | varchar(500) | NULL |

- Coherence CHECK: `is_up = (error_kind IS NULL)`.
- Indexes: the PK covers per-monitor history queries. A **BRIN** index on `scheduled_at` serves the 30-day retention cleanup, which deletes across all monitors.
- ORM relationship uses `passive_deletes=True`.

**Rationale.**
- **Idempotent by design:** a re-executed check hits the PK and is skipped with `ON CONFLICT DO NOTHING` (Phase 4).
- **Smaller rows** without a surrogate id, and the table is ready for time partitioning or TimescaleDB.
- **`error_kind` values:** no `too_slow`, because the request timeout equals the 10 s down threshold, so a slow site is a `timeout`. `blocked_target` covers SSRF protection.
- **Text + CHECK instead of a PostgreSQL ENUM:** ENUMs are awkward to change in migrations.
- **Cascade done by PostgreSQL**, not the ORM: the ORM would load every check of the monitor into memory.
- **BRIN** is tiny and suits rows that arrive in time order. A `(monitor_id, checked_at)` B-tree would have duplicated the PK.

---

## ADR-013 — Configuration: pydantic-settings

- **Date:** 2026-10-26 (Phase 1)
- **Status:** Accepted

**Options.**
1. **pydantic-settings** — one validated `Settings` class.
2. **`os.environ`** — no dependency, but config is scattered and unvalidated.

**Decision.** pydantic-settings, in `pulseops/config.py`.
- Variables: `DATABASE_URL` (app role), `MIGRATION_DATABASE_URL` (owner role), `BROKER_URL` and `ALLOW_PRIVATE_TARGETS` (bool, default `false`, used from Phase 2 for SSRF protection).
- Secrets and URLs that carry credentials are `SecretStr`.

**Rationale.** Missing or malformed configuration fails at startup with a clear message. `SecretStr` keeps passwords out of logs, tracebacks and reprs.

---

## ADR-014 — Migrations: one-shot `migrate` service and three database roles

- **Date:** 2026-10-26 (Phase 1)
- **Status:** Accepted

**Context.** Migrations must run before the API/worker start, exactly once. The app should not be able to change the schema.

**Options (when to migrate).**
1. **One-shot `migrate` service** in Compose.
2. **On API startup** — replicas and the worker could race.
3. **Manually** — easy to forget.

**Options (roles).**
1. **Two roles** — the image superuser owns the schema; an app role handles rows.
2. **Three roles** — superuser kept for administration only.

**Decision.** A one-shot `migrate` service (`alembic upgrade head`) with three roles:
- **`postgres`:** superuser, administration only; never used by PulseOps.
- **`pulseops_owner`:** not a superuser; owns the `pulseops` and `pulseops_test` databases and their schema. Used only by `migrate` and migration tests.
- **`pulseops_app`:** used by the API and the worker.
  - Allowed: SELECT/INSERT/UPDATE/DELETE on tables and USAGE/SELECT on sequences, granted through `ALTER DEFAULT PRIVILEGES FOR ROLE pulseops_owner`.
  - Not allowed: CREATE, ALTER or DROP.

The roles and databases are created by an init script in `docker-entrypoint-initdb.d`, with passwords taken from `.env`. Startup order: `postgres` (healthy) → `migrate` (completed successfully) → `api`.

**Rationale.** Least privilege. A SQL injection through the API could not alter or drop tables. A leaked migration password would be limited to PulseOps' databases instead of the whole server.

---

## ADR-015 — Tests run against real PostgreSQL in a separate database

- **Date:** 2026-10-26 (Phase 1)
- **Status:** Accepted

**Options.**
1. **Real PostgreSQL**, in a separate database.
2. **In-memory SQLite** — faster, but behaves differently (constraints, types, timestamps) and could hide bugs.

**Decision.** Real PostgreSQL in its own database, `pulseops_test`, created by the same init script with the same roles. Tests never touch development data.

---

## ADR-016 — Security baseline

- **Date:** 2026-10-26 (Phase 1)
- **Status:** Accepted

**Decision.**
- **Linting:** Ruff runs the `S` rules (flake8-bandit). `assert` and test passwords are allowed only under `tests/`.
- **Dependencies:** Dependabot watches the `uv`, `docker` and `docker-compose` ecosystems.
- **Valkey:** requires a password (`--requirepass`); `BROKER_URL` is a `SecretStr`.
- **Compose secrets:** declared as required (`${VAR:?}`), so the stack refuses to start without a `.env` instead of falling back to weak defaults.
- **Published ports:** Valkey is not published outside the Docker network. PostgreSQL is published on `127.0.0.1` only, so tests can run from the host.
- **ArdiQ:** keeps its default msgpack codec, never pickle.
- **Secret scanning:** push protection is to be enabled on GitHub. It is unavailable for free on private repositories, so it is tracked as pending.

**Rationale.** Cheap measures now, which avoid expensive incidents once there are real data and users. The full set of permanent rules lives in `CLAUDE.md` under "Security".
