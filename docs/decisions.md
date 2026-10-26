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

---

## ADR-017 — API routes and versioning: `/api/v1/monitors`

- **Date:** 2026-10-27 (Phase 2)
- **Status:** Accepted

**Options.**
1. **Versioned prefix** `/api/v1/...`.
2. **Unversioned** `/monitors`.

**Decision.** Versioned prefix:

| Method | Path | Response |
|---|---|---|
| POST | `/api/v1/monitors` | 201 + `Location` |
| GET | `/api/v1/monitors` | 200, paginated |
| GET | `/api/v1/monitors/{id}` | 200 / 404 |
| PATCH | `/api/v1/monitors/{id}` | 200 / 404 |
| DELETE | `/api/v1/monitors/{id}` | 204 / 404 (checks removed by cascade) |

`/health` stays outside the prefix and unauthenticated.

**Rationale.** Breaking changes (e.g. users in Phase 10) can ship as `/api/v2` without breaking v1 clients.

**Weak point.** Longer URLs, and maintaining two versions in parallel would cost real work.

**Reversibility.** Hard: routes are the public contract.

---

## ADR-018 — Editing: PATCH only

- **Date:** 2026-10-27 (Phase 2)
- **Status:** Accepted

**Options.**
1. **PATCH only.**
2. **PUT + PATCH.**
3. **Dedicated `/pause` and `/resume` endpoints.**

**Decision.** PATCH only.
- Only the fields sent are applied (`exclude_unset`).
- `null` for a required field (`name`, `url`, `interval_seconds`, `is_active`) is a 422.
- Pausing is `PATCH {"is_active": false}`.
- If `url` is present, it goes through exactly the same checks as on creation: normalization, SSRF and duplicates. If it is absent, no URL check or DNS lookup happens, so pausing works even when the site's DNS is down.

**Rationale.** Partial edits cover every MVP use case. PUT would duplicate code, and dedicated endpoints would duplicate what PATCH already does.

**Weak point.** Clients cannot replace a whole resource atomically. Nobody needs that today.

**Reversibility.** Easy to add PUT later. Removing PATCH would be hard.

---

## ADR-019 — Public identifier named `id`

- **Date:** 2026-10-27 (Phase 2)
- **Status:** Accepted

**Options.**
1. **Expose `public_id` as `id`.**
2. **Expose it as `public_id`.**

**Decision.** The API field `id` carries `monitors.public_id` (UUID v7). The internal integer id never leaves the API. In the code, `public_id` and `id` are always named explicitly so they cannot be confused.

**Rationale.** Clients do not need to know an internal key exists, and the contract stays clean.

**Weak point.** `id` means different things in the API and in the database. Explicit naming in the code mitigates it.

**Reversibility.** Hard: it is part of the response contract.

---

## ADR-020 — Errors: RFC 9457 Problem Details + `code`

- **Date:** 2026-10-27 (Phase 2)
- **Status:** Accepted

**Options.**
1. **RFC 9457** Problem Details.
2. **FastAPI's default** `{"detail": ...}`.
3. **A custom envelope.**

**Decision.** `application/problem+json` with `type`, `title`, `status`, `detail` and an extension member `code`: a stable snake_case identifier that programs can match without parsing text.
- `type` is a relative reference under our own namespace (`/problems/<slug>`), never a domain we do not own.
- **422:** an own handler converts FastAPI/Pydantic errors into an `errors` list with only `loc`, `msg` and `type`. **Never `input`**: echoing input could leak, e.g., a password embedded in a URL.
- **500:** always generic (`internal_error`), with no traces, SQL, table or constraint names. Details go to the logs only.
- **Status mapping:**

| Status | `code` | When |
|---|---|---|
| 401 | `unauthorized` | Missing or wrong API key |
| 404 | `monitor_not_found` | |
| 409 | `monitor_url_conflict` | Detected by catching the `uq_monitors_url` violation by name, not with a racy SELECT first |
| 422 | `validation_error`, `url_target_not_allowed`, `url_credentials_not_allowed` | |
| 500 | `internal_error` | Any other integrity error, or anything unexpected |

- Implemented with our own exception handlers, without dependencies.
- "Must never happen" tests (exact response fields, no leaked internals, no echoed secrets, generic 500, 401 without key, key absent from logs) are part of this decision.

**Rationale.** A standard format that any client understands, plus a machine-readable `code`. Errors become an attack surface if they leak internals.

**Weak point.** A relative `type` resolves against our own host, where nothing is served. It works as an identifier, not as documentation.

**Reversibility.** Hard: clients code against the error format.

---

## ADR-021 — Monitor list pagination: limit/offset

- **Date:** 2026-10-27 (Phase 2)
- **Status:** Accepted

**Options.**
1. **limit/offset.**
2. **Cursor (keyset).**
3. **No pagination.**

**Decision.** `?limit=50&offset=0`: `limit` defaults to 50 (max 100), `offset` >= 0.
- Optional `is_active` filter; no other filters or sort options.
- Fixed, tie-free order by the internal `id`, ascending (creation order).
- Response: `{items, total, limit, offset}`.

**Rationale.** Simple and enough for tens or hundreds of monitors. A fixed order keeps the "closed list" security rule trivially true.

**Weak point.** Offset pages can shift if rows are inserted while paging, and get slower on large offsets. The check history (Phase 5) will therefore use cursor pagination on `(monitor_id, scheduled_at)`.

**Reversibility.** Medium: adding cursor parameters later is additive, but removing offset would break clients.

---

## ADR-022 — URL normalization

- **Date:** 2026-10-27 (Phase 2)
- **Status:** Accepted

**Context.** Without normalization, `HTTPS://Example.com` and `https://example.com/` would be stored as different monitors.

**Decision.** In this order:
1. Strip surrounding whitespace.
2. Validate with Pydantic `HttpUrl`, which:
   - lowercases scheme and host;
   - drops default ports;
   - converts international domains to punycode;
   - adds `/` for an empty path;
   - accepts only `http` and `https`;
   - canonicalizes odd IP notations (e.g. `http://2130706433/` becomes `127.0.0.1`).
3. Drop the `#fragment`: browsers never send it to the server.
4. Drop a trailing dot from the host (`example.com.` → `example.com`).
5. Reject `user:password@` with 422 `url_credentials_not_allowed`: those credentials would be stored in plain text and shown by the API.
6. Leave path and query untouched: they are case-sensitive and order may matter.
7. Enforce <= 2048 characters **after** normalization (punycode can lengthen a URL).

**Rejected.** Percent-encoding normalization (RFC 3986 §6.2.2), to be reevaluated if real duplicates appear.

**Weak point.** Duplicates that differ only in percent-encoding or query order are not detected.

**Reversibility.** Medium: stricter rules later may require a data migration to re-normalize stored URLs.

---

## ADR-023 — SSRF protection on create and edit

- **Date:** 2026-10-27 (Phase 2)
- **Status:** Accepted

**Context.** PulseOps fetches URLs supplied by users. Without protection, it could be pointed at internal services (PostgreSQL, Valkey) or at cloud metadata endpoints (`169.254.169.254`).

**Options.**
1. **Literal IPs + DNS resolution at creation.**
2. **Literal IPs and obvious names only**, without DNS.

**Decision.** Option 1, in `pulseops/security/ssrf.py`, reused by the checker in Phase 3.
- **Literal IP hosts** are checked directly. **Hostnames** are resolved asynchronously (`loop.getaddrinfo`) with a short timeout.
- **If resolution fails or times out, the URL is accepted.** The check will record `dns_error`, and Phase 3 validates again on every check.
- **If any resolved address is not allowed,** the request gets 422 `url_target_not_allowed` with a generic message that never reveals the IP or what a name resolves to, so the API cannot be used to map the internal network.
- **Any port** is allowed (real APIs live on 8080, 8443…).
- `ALLOW_PRIVATE_TARGETS=true` disables the block for self-hosted installs on private networks.

**IP rule.**
1. Unwrap IPv4 embedded in IPv6: IPv4-mapped (`::ffff:0:0/96`), 6to4 (`2002::/16`), Teredo (client address) and NAT64 well-known prefix `64:ff9b::/96` (last 32 bits). The embedded IPv4 must **also** be allowed.
2. An address is allowed only if `is_global` is true, it is not multicast, it is not in `::/96` (deprecated IPv4-compatible), and it is not in `64:ff9b:1::/48`. The local-use NAT64 range is blocked whole, because the IPv4 position inside it is not reliable.

**Verified gaps in Python 3.13** (covered by tests):
- `224.0.0.1` and `ff02::1` (multicast), `64:ff9b::7f00:1` (NAT64 wrapping 127.0.0.1) and `::127.0.0.1` (IPv4-compatible) all report `is_global=True`.
- 6to4 and Teredo already report `is_global=False` as whole ranges, so unwrapping them is defence in depth.

**Rationale.**
- **Validating NAT64 instead of blocking it** keeps PulseOps usable on an IPv6-only VPS with DNS64, where every IPv4-only site resolves into `64:ff9b::/96`.
- **Accepting unresolvable names** avoids rejecting domains that do not exist yet. The authoritative check happens at fetch time.

**Weak point.** A creation-time check is time-of-check/time-of-use: DNS can change afterwards (DNS rebinding). That is why Phase 3 re-validates on every check and every redirect. Also, `getaddrinfo` runs in a thread pool and a timeout does not free the thread; acceptable for the API, to be revisited for the checker in Phase 3.

**Reversibility.** Easy: internal module behind one function.

---

## ADR-024 — API authentication: static API key in `ApiSettings`

- **Date:** 2026-10-27 (Phase 2)
- **Status:** Accepted

**Context.** The MVP has no users, but an open API would let anyone create monitors.

**Options.**
1. **Static API key** in a header.
2. **No authentication** until Phase 9/10.

**Settings options.**
1. **A separate `ApiSettings`.**
2. **The shared `Settings`.**

**Decision.**
- **The key:** `X-API-Key` header, value from `API_KEY`. It is required, at least 32 characters (`openssl rand -base64 32`), validated at startup (no valid key, no API) and compared with `secrets.compare_digest` (constant time). It never appears in logs or errors.
- **Where it lives:** a separate `ApiSettings` (with `DOCS_ENABLED`), so the worker never needs or sees the key.
- **Scope:** `/health` stays open. Swagger exposes the key through its "Authorize" button. A missing or wrong key gets 401 `unauthorized`.

**Rationale.** Cheap, and it closes the hole before deployment. A separate settings class keeps least privilege between API and worker.

**Weak point.** A single shared secret with no rotation, per-client identity or brute-force throttling. Throttling will be done in the Phase 9 proxy, and the key is replaced by users in Phase 10.

**Reversibility.** Easy: one dependency on the router.

---

## ADR-025 — Code layers: router → repository

- **Date:** 2026-10-27 (Phase 2)
- **Status:** Accepted

**Options.**
1. **Router → repository.**
2. **Router with SQLAlchemy inline.**
3. **Router → service → repository.**

**Decision.** Option 1.
- `api/monitors.py` only speaks HTTP: it validates, translates and responds, and never touches the database.
- `repositories/monitors.py` owns all database access and knows nothing about HTTP.

**Rationale.** Phase 10's owner filter will be added in exactly one place, as the Security rules require. A service layer is premature until real business logic appears (alerts, Phase 7).

**Weak point.** Small orchestration logic (URL validation before saving) lives in the router for now.

**Reversibility.** Easy: a service layer can be inserted later without changing the API.

---

## ADR-026 — Changing a monitor's URL is allowed

- **Date:** 2026-10-27 (Phase 2)
- **Status:** Accepted

**Options.**
1. **Allow URL changes via PATCH.**
2. **Make `url` immutable**, so a new URL means a new monitor.

**Decision.** Allowed, always with normalization, SSRF and duplicate checks. The existing check history is kept.

**Rationale.** Fixing a typo or following a migration (e.g. `http` → `https`) should not lose history.

**Weak point.** History before the change refers to the old URL, and the API does not record when the URL changed.

**Reversibility.** Easy to forbid later. Allowing it again after forbidding it is also easy.

---

## ADR-027 — `DOCS_ENABLED` setting

- **Date:** 2026-10-27 (Phase 2)
- **Status:** Accepted

**Decision.** Boolean in `ApiSettings`, default `true`. With `false`, `/docs`, `/redoc` and `/openapi.json` are disabled. The production value is decided in Phase 9.

**Rationale.** The API map helps attackers, and FastAPI's Swagger page loads its assets from an external CDN.

**Weak point.** Hiding docs is not a security control by itself.

**Reversibility.** Easy.

---

## ADR-028 — No CORS

- **Date:** 2026-10-27 (Phase 2)
- **Status:** Accepted

**Decision.** The CORS middleware is not added. If it is ever needed, it will allow specific origins only, never `*`.

**Rationale.** There is no browser frontend on another origin. The safe default is that browsers block cross-site calls.

**Weak point.** A future web UI on another domain will need explicit configuration.

**Reversibility.** Easy.

---

## ADR-029 — API exposure and request size

- **Date:** 2026-10-27 (Phase 2)
- **Status:** Accepted

**Decision.**
- **Now:** Compose publishes the API on `127.0.0.1:8000` only, so it is reachable from this machine alone until Phase 9.
- **Phase 9:** the reverse proxy limits request body size. FastAPI has no body limit, and Pydantic limits apply only after the body is already in memory.

**Weak point.** Until Phase 9 there is no body size limit, which is acceptable while the API is local-only and behind an API key.

**Reversibility.** Easy.

---

## ADR-030 — `ValidatedUrl`: only validated URLs reach the database

- **Date:** 2026-10-27 (Phase 2)
- **Status:** Accepted

**Context.** URL validation (normalization + SSRF) runs outside Pydantic, because it needs its own error codes and an async DNS lookup. A future endpoint could forget to call it.

**Decision.** The repository accepts only a `ValidatedUrl` for the `url` field.
- `ValidatedUrl` is an immutable type in `pulseops.security`, created only by the validation function. Its constructor requires a module-private token and raises otherwise.
- The repository also checks `isinstance` at runtime.

**Rationale.** Saving an unvalidated URL becomes impossible by accident, even for endpoints added later.

**Weak point.** Python has no truly private constructors: importing the private token would bypass the guard. It prevents mistakes, not deliberate misuse, and such a bypass stands out in code review.

**Reversibility.** Easy.
