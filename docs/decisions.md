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

---

## ADR-031 — SSRF at connect time: IP pinning, no proxies

- **Date:** 2026-10-27 (Phase 3)
- **Status:** Accepted

**Context.** Validating a URL's DNS and then letting the HTTP client resolve it again leaves a gap (time-of-check/time-of-use). Between the two lookups a hostname can switch from a public IP to an internal one (DNS rebinding). Redirects can also point anywhere.

**Options.**
1. **Pin the IP in a custom network backend:** resolve, validate, connect to the validated address.
2. **Validate first, then let httpx2 resolve again** — simple, but leaves the rebinding gap.
3. **Dedicated egress proxy** (e.g. Smokescreen) — strongest, but an extra service.

**Decision.** Option 1 (`pulseops/checker/network.py`).
- `PinnedNetworkBackend.connect_tcp` resolves the host, validates **all** addresses with `is_allowed_address` (one disallowed address blocks the host, same rule as the API), and connects to one of those same addresses. It tries them in order and falls back on failure.
- TLS keeps using the hostname for SNI and certificate validation. Verified in httpcore2: `server_hostname` comes from the request origin, not the connected IP.
- Every connection goes through the backend, so redirects are covered with no extra code.
- The client is created with **`trust_env=False`**. Through an `HTTP(S)_PROXY` from the environment, the SSRF check would apply to the proxy's address instead of the target's. A test proves the variables are ignored.

**Weak point.** `PinnedTransport` replaces httpx2's internal `_pool` attribute; a release could change it. The checker tests, including a simulated rebinding, fail loudly if that happens. It was verified that disabling the validation makes the four SSRF tests fail.

**Reversibility.** Easy: isolated module. Option 3 is reevaluated in Phase 9.

---

## ADR-032 — Redirects: follow up to 5

- **Date:** 2026-10-27 (Phase 3)
- **Status:** Accepted

**Options.**
1. **Follow up to 5.**
2. **Do not follow; any 3xx counts as up.**

**Decision.** Follow up to 5 (`follow_redirects=True`, `max_redirects=5`). The final page is what gets measured, as a visitor would see it.

| Case | Result |
|---|---|
| More than 5 redirects, or a loop | Down, `http_error` |
| Redirect to a scheme other than http/https | Down, `http_error` |
| Redirect to a disallowed address | Down, `blocked_target` (enforced at connect time, ADR-031) |

**Rationale.** Option 2 would report `http://site` → 301 as up even if the HTTPS site were down.

**Weak point.** Intermediate redirect bodies are read by httpx2 (usually empty), within the global deadline.

**Reversibility.** Easy.

---

## ADR-033 — Timing: one 10-second deadline for the whole check

- **Date:** 2026-10-27 (Phase 3)
- **Status:** Accepted

**Options.**
1. **One total deadline.**
2. **Per-phase timeouts** (connect, read…).

**Decision.**
- **One deadline (`asyncio.timeout(10)`)** covers DNS, connection, TLS, every redirect and the final response headers. It matches the business rule "takes more than 10 s → down" exactly.
- **`response_time_ms`** runs from the start of the check until the final response's headers arrive, redirects included.
- **On timeout:** `timeout`, with no status code and no response time.
- **The body is never downloaded:** the response is opened as a stream and closed after the headers.

**Rationale.** Per-phase timeouts can add up to more than 10 s and break the business rule.

**Weak point.** A timeout does not say which phase was slow.

**Reversibility.** Easy.

---

## ADR-034 — User-Agent: honest, versioned

- **Date:** 2026-10-27 (Phase 3)
- **Status:** Accepted

**Options.**
1. **An own User-Agent.**
2. **Imitate a browser.**
3. **httpx2's default.**

**Decision.** `PulseOps/<package version> (uptime monitor)`. The version is read automatically from the package metadata. A contact URL will be added once there is a domain (Phase 9).

**Rationale.** It identifies the bot honestly, as serious monitors do. Imitating a browser deceives the site, and the default does not identify PulseOps.

**Weak point.** Sites that block bots answer 403 and show as down. Configurable expected status codes per monitor are on the post-MVP roadmap.

**Reversibility.** Easy.

---

## ADR-035 — Fresh connections for every check

- **Date:** 2026-10-27 (Phase 3)
- **Status:** Accepted

**Options.**
1. **Shared client, no keep-alive.**
2. **Reuse connections.**

**Decision.** One shared client per `Checker` (TLS setup reused) with `max_keepalive_connections=0`. Every check pays DNS + TCP + TLS like a first-time visitor.

**Rationale.** Response times stay comparable between checks, and every check goes through the SSRF validation again (an open connection would skip it).

**Weak point.** Costs more network and CPU per check.

**Reversibility.** Easy.

---

## ADR-036 — DNS resolution: getaddrinfo in a dedicated, bounded thread pool

- **Date:** 2026-10-27 (Phase 3)
- **Status:** Accepted

**Context.** `getaddrinfo` blocks, so it runs in a thread. A timeout frees the caller but not the thread.

**Options.**
1. **`getaddrinfo` in a dedicated pool.**
2. **`aiodns`** (c-ares): truly async, but adds a C library and behaves differently from the system resolver in edge cases (`/etc/hosts`, search domains).

**Decision.** `getaddrinfo` in a dedicated `ThreadPoolExecutor` (16 threads, `pulseops-dns`), shared by the API and the checker. Timeout: 2.5 s; a failed lookup returns "no answer" (`dns_error`).

**Rationale.** No new dependency, and the same behaviour as the rest of the system (including Docker's internal DNS). A stuck DNS server can only exhaust its own pool, never the rest of the process.

**Weak point.** If DNS goes down completely, the pool saturates and checks report down, which in that situation is the truth.

**Reversibility.** Easy: one function. Revisit `aiodns` if saturation shows up in Phase 4.

---

## ADR-037 — Checker interface, error mapping and command line

- **Date:** 2026-10-27 (Phase 3)
- **Status:** Accepted

**Decision.**
- **Package:** `pulseops/checker/`, with no database access (Phase 4 stores results).
- **`Checker`:** a reusable class (one HTTP client for many checks). `check_url()` is a one-off helper.
- **`CheckOutcome`:** an immutable dataclass mirroring a `checks` row. It enforces the same rules as the database constraints (`is_up` ⇔ no `error_kind`, known kinds, detail ≤ 500 characters).
- **Error mapping**, each case verified against real local servers:

| Situation | `error_kind` |
|---|---|
| Deadline exceeded | `timeout` |
| Name does not resolve | `dns_error` |
| Connection refused or reset | `connection_error` |
| Invalid, expired, wrong-name or untrusted certificate | `ssl_error` (detected through the `ssl.SSLError` cause of httpx2's `ConnectError`) |
| 4xx/5xx, too many redirects, unsupported redirect scheme | `http_error` |
| Disallowed address, also after a redirect | `blocked_target`, with a generic detail that never contains an IP |

- **Command line:** `python -m pulseops.checker <url>` normalizes the URL like the API, applies `ALLOW_PRIVATE_TARGETS` and prints the outcome as JSON (exit 0 up, 1 down, 2 invalid URL).

**Rejected.** A temporary API endpoint to trigger checks: it would let the API fetch arbitrary URLs on demand, which is another SSRF surface.

**Reversibility.** Medium: Phase 4 will depend on this interface.

---

## ADR-038 — Evidence tooling: coverage and smoke test

- **Date:** 2026-10-27 (Phase 3)
- **Status:** Accepted

**Decision.**
- **Coverage:** `pytest-cov`, run with `uv run pytest --cov`, branch coverage on. It is configured with `concurrency = ["greenlet", "thread"]`: SQLAlchemy async runs code in greenlets, and without it lines after a database call were wrongly reported as never executed. The figure is recorded in `docs/evidence.md`.
- **Smoke test:** `scripts/smoke_test.py` runs the manual test list against the live stack from outside, as a user would.
  - It only touches the monitors it creates (unique URLs per run) and deletes them, so it is safe on a stack with real data.
  - It is extended in every phase.

**Weak point.**
- A high coverage figure does not prove the tests check the right things. The SSRF tests were checked by disabling the protection and watching them fail.
- The smoke test needs internet access, because it creates monitors for real sites.

**Reversibility.** Easy.

---

## ADR-039 — Scheduling: one global scheduler, the schedule in PostgreSQL

- **Date:** 2026-10-27 (Phase 4)
- **Status:** Accepted

**Context.** Each monitor must be checked every `interval_seconds`. This is the key design choice of the MVP: who decides which monitors are due, and where that schedule lives.

**Options.**
1. **A global scheduler** (an ArdiQ cron every few seconds) that reads a `next_check_at` column in PostgreSQL.
2. **One self-rescheduling task per monitor**: each check enqueues the next one with `schedule_ms`.
3. **One `@app.cron` per monitor.**

**Decision.** Option 1.
- **New column:** `monitors.next_check_at` (`timestamptz NOT NULL DEFAULT now()`, migration `0002`), with a partial index on `next_check_at WHERE is_active`.
- **The scheduler:** `@app.cron(every=5, coalesce=True)`. Each tick runs one statement that claims the due monitors (`next_check_at <= now()`, oldest first, at most 500) and moves them to their next slot:
  - `UPDATE … FROM (SELECT … FOR NO KEY UPDATE SKIP LOCKED) RETURNING` claims each monitor once, even with two schedulers running: the second skips the rows the first has locked.
  - `NO KEY UPDATE` rather than `UPDATE`, because ids never change. With plain `FOR UPDATE`, storing a check for a claimed monitor (a foreign key share lock) waited for the scheduler's commit. Verified by `test_a_claimed_monitor_still_accepts_checks`, which times out with the stronger lock.
  - Times come from the database clock.
  - Scheduling keeps `updated_at` as it is: it is not an edit.
- **Enqueue before commit.** The tick enqueues the claimed checks (one `enqueue_many` round trip) and only then commits:
  - if enqueueing fails, the claim rolls back and the next tick claims the same slots again, so no check is lost;
  - if the commit fails after enqueueing, the same checks are enqueued again, and the fixed task ids and `ON CONFLICT DO NOTHING` absorb them (ADR-041).
- **Why:**
  - **The schedule lives in the source of truth.** Losing Valkey, or a single task, costs at most one check per monitor. Nothing stops silently.
  - **Changes need no queue access.** Creating, editing, pausing or deleting a monitor takes effect on its own, without the API touching the queue (ADR-043).

**Rejected.**
- **Option 2:** exact timing and no polling, but one lost task (Valkey restart, dead letter, bug) silently stops that monitor for good. It would need a "repair" cron, which is option 1 plus complexity. Edits and deletes would also make the API cancel tasks in Valkey, and a re-delivered check would enqueue two "next" checks.
- **Option 3:** ArdiQ registers crons at import time (a decorator filling a dict); they cannot be created or removed at runtime. Checked in the ArdiQ 1.2.0 source.

**Weak point.**
- One query every 5 s even when nothing is due (cheap with the partial index).
- A check can start up to one tick (≤ 5 s) late.
- `next_check_at` is updated on every check, leaving dead row versions for autovacuum. Irrelevant at this scale.

**Reversibility.** Medium: a column, an index and one module (`repositories/scheduling.py`).

---

## ADR-040 — Next slot, missed periods and rescheduling on edit

- **Date:** 2026-10-27 (Phase 4)
- **Status:** Accepted

**Decision.**
- **Next slot:** `previous slot + k × interval`, with the smallest `k` that lands in the future. After an outage, a monitor gets one check for the slot that was due and none for the missed ones, and it stays on its own time grid. Monitors therefore stay spread out instead of all firing in the same second.
- **Gaps:** periods when the worker was down have no checks. Phase 5 counts them as **"no data"**, neither up nor down.
- **Brought forward to `now()`:**
  - **on create** (the column default), so the first check comes within a few seconds;
  - **when the URL or the interval changes, or the monitor is reactivated.** Otherwise going from a 1-day interval to 30 s would still wait for the old slot. Only real changes count: sending the same value, renaming or pausing keep the schedule.

**Rejected.**
- **Catching up** (one check per missed period): a stampede of late checks that say nothing about the past.
- **Resetting to `now() + interval`:** simple, but every overdue monitor lands on the same instant.

**Reversibility.** Easy: one SQL expression and one helper in `repositories/monitors.py`.

---

## ADR-041 — The check task: idempotent, ids only, no connection held

- **Date:** 2026-10-27 (Phase 4)
- **Status:** Accepted

**Decision.**
- **Payload:** `check_monitor(monitor_id, scheduled_at_us)`. Only two integers travel through the queue, never the URL, so it never shows up in Valkey, in ArdiQ's logs or in its dead letter queue. `scheduled_at` travels in **microseconds**:
  - msgpack cannot carry datetimes;
  - milliseconds would lose part of the database value, so the check would not land exactly on the claimed slot.
- **Idempotency, two safeguards:**
  - **A fixed task id `check:<monitor_id>:<µs>`:** the same slot enqueued twice while it waits is one task.
  - **`INSERT … ON CONFLICT DO NOTHING` on `(monitor_id, scheduled_at)`.** Needed because ArdiQ's id deduplication only lasts while the task exists: the same id enqueued after the task finished runs again (verified against Valkey, `test_same_task_id_after_it_finished_runs_again`). The first outcome wins.
- **No database connection during the check:** a short session reads the monitor and closes, then the check runs (up to 10 s), then a new session stores the result. Verified by `test_no_database_connection_is_held_during_the_check`: no pooled connection is checked out while the fake checker runs.
- **Deleted or paused monitor:** nothing is checked. A monitor deleted while its check runs is not an error: the foreign key violation is recognised by constraint name and nothing is stored.
- **Task options:**
  - `max_retries=3`, for infrastructure failures only (database down). A site that is down is an outcome, not an error. Retrying is safe because the insert is idempotent.
  - `timeout=30` s, a safety net above the checker's 10 s deadline.
  - `expire_ms` = the monitor's interval: a check not started before the next slot is dropped (verified against Valkey, `test_expired_tasks_are_dropped_without_running`).
- **Layering:** the logic lives in `pulseops/scheduling.py` and knows nothing about ArdiQ. `pulseops/queue/tasks.py` only wraps it, so the queue can be swapped and the logic is tested without Valkey.

**Reversibility.** Easy for the options; the payload format must stay compatible while tasks are in flight.

---

## ADR-042 — Worker capacity and the database pool

- **Date:** 2026-10-27 (Phase 4)
- **Status:** Accepted; lanes amended by ADR-051 (a third `maintenance` lane, and `checks` limited to 30)

**Decision.**
- **`concurrency=32`:** checks wait on the network, not the CPU.
  - **Rough numbers, not measured:** about 100 checks/s at 300 ms each, about 3 checks/s if every check hits the 10 s deadline.
  - **To scale:** `ardiq run -w N` or more worker containers, without code changes.
- **Two lanes, `checks` and `scheduler`, with `limits={"checks": 31}`:** checks never take the last slot, so slow checks cannot keep the scheduler waiting. `default_priority` is set explicitly to `checks`, because with two lanes ArdiQ's default would be the higher one.
- **Database pool:** SQLAlchemy's default, 5 + 10 overflow = 15 connections per process. Each task holds one only for milliseconds (ADR-041), so 15 serve 32 concurrent tasks. When the pool is exhausted, a task waits (up to 30 s) instead of failing. API (15) + worker (15) stay well below PostgreSQL's default of 100.
- **Startup and shutdown:** `@app.lifespan` creates one `Checker` (shared TLS setup) and the session factory per worker, and disposes of the engine on shutdown. `stop_grace_period: 15s` in Compose lets checks in flight finish.

**Weak point.** Starting values, not measurements. To be tuned with `app.metrics()` once there is real load.

**Reversibility.** Easy: constants in `pulseops/queue/app.py`.

---

## ADR-043 — Broker settings apart; Valkey for tests on localhost

- **Date:** 2026-10-27 (Phase 4)
- **Status:** Accepted

**Decision.**
- **`BrokerSettings`** holds `broker_url` and is used only by the worker. The API service no longer receives `BROKER_URL`. With ADR-039 the API never uses the queue, so it never gets the Valkey password; a compromised API cannot inject tasks. It mirrors `ApiSettings`, which the worker never sees.
- **Valkey is published on `127.0.0.1:6380`** (password required) so tests can use a real broker, as they do with PostgreSQL.
  - **Why host port 6380:** 6379 is often taken by another local Redis (it was, on the development machine).
  - **Inside Docker** the worker still uses `valkey:6379`.
- **Test isolation:** tests use Valkey logical database `1` (`TEST_BROKER_URL`, development uses `0`), and each test creates its own throwaway queue and purges it.
- **Why a real broker:** `ardiq.testing.inline` ignores delays and expiry, which are exactly what the scheduler relies on. Inline tests are still used for the task wrappers.

**Weak point.** If the API ever needs to enqueue (for example, a "check now" button), it will need the password again.

**Reversibility.** Easy.

---

## ADR-044 — Secrets and URLs stay out of the worker's logs

- **Date:** 2026-10-27 (Phase 4)
- **Status:** Accepted

**Context.** Monitor URLs may carry tokens in their query. `ardiq run` logs at INFO (DEBUG with `-v`), and ArdiQ logs and keeps the error of every failed task.

**Decision.**
- **Our log line:** one line per check, with `public_id`, up/down, `error_kind`, response time and whether it was stored. Never the URL, and never `error_detail`, which may echo it. Verified with a URL carrying a token (`test_logs_never_show_the_url_or_the_error_detail`).
- **httpx2 and httpcore2 log at WARNING only.** httpx2 logs `HTTP Request: GET <full URL>` at INFO for every request and redirect, and httpcore2 traces more at DEBUG. The checker raises both loggers to WARNING, whatever the process's logging setup. `test_urls_never_reach_the_logs` failed before the change.
- **`hide_parameters=True` on the database engine.** By default, SQLAlchemy puts query parameters in its error messages. A failed insert would then put `error_detail` (and the URL in it) in ArdiQ's logs and dead letters.
- **The scheduler's errors are logged, not raised.** A failing tick (database or Valkey down) logs `scheduling failed, retrying next tick: <error>` and returns 0. The claim has rolled back, so the next tick, 5 s later, retries the same slots.
  - **Why:** raising would add a dead letter every 5 s for as long as the outage lasts.
  - **The password stays out:** ArdiQ's errors do not include the Valkey password (`test_scheduler_error_log_never_shows_the_broker_password`, against the real Valkey with a wrong password).

**Weak point.** While ticks fail, `ardiq status` reports the cron's last run as succeeded. The scheduler heartbeat (ADR-045) is the reliable signal.

**Reversibility.** Easy.

---

## ADR-045 — Scheduler heartbeat and restart policy

- **Date:** 2026-10-28 (Phase 4)
- **Status:** Accepted

**Context.** If the worker dies, or keeps running but stops scheduling, nothing is checked and nothing says so ("who watches the watchman").

**Decision.**
- **Heartbeat table `scheduler_heartbeat`** (migration `0003`):
  - **Shape:** one row (`id = 1`, enforced by a CHECK) with `last_success_at`, stamped with the database clock.
  - **Written in the tick's own transaction,** after the claim and the enqueue, **empty ticks included**. It therefore only moves when a tick really commits: a quiet PulseOps keeps it fresh, and a tick that fails to enqueue leaves the old time in place. Tests: `test_an_empty_tick_still_moves_the_heartbeat`, `test_a_failed_enqueue_does_not_move_the_heartbeat`.
  - **Who reads it:** the API (Phase 7, `/health`) will read it without access to Valkey.
- **`restart: unless-stopped`** on `api`, `worker`, `postgres` and `valkey`:
  - a crashed service comes back on its own, and `docker compose stop` still stops it for good;
  - `migrate` is `restart: "no"`, because it must run once and exit.
  - **Verified:** after a `kill -9` of the worker's process, Docker restarted it (restart count 1).

**Rejected.**
- **A key in Valkey:** lighter, but the API has no access to Valkey (ADR-043).
- **In memory or in the logs only:** the API could not see it.

**Weak point.**
- A restart policy only covers a process that exits. A hung but alive worker is caught by the heartbeat, which needs Phase 7's alerting to be acted on.
- The policy only helps after a reboot if the Docker daemon starts on its own.

**Reversibility.** Easy.

---

## ADR-046 — Uptime is counted in checks; no data is not a number

- **Date:** 2026-10-28 (Phase 5)
- **Status:** Accepted

**Context.** Uptime is the share of time a monitor was up. Checks are samples, and there are gaps when the worker is down (ADR-040).

**Options.**
1. **By number of checks:** checks up / checks in the period.
2. **By time:** each check weighs the interval it covers.
3. **By incidents:** total time minus the duration of each outage (Phase 7).

**Decision.** Option 1.
- **`uptime_percent`** = checks up / checks in the period × 100, rounded to 3 decimals.
- **It is `null` when the period has no checks:** "no data" is neither 0 % nor 100 %.
- **Gaps fall out on their own:** a period without checks simply contributes nothing (the Phase 5 rule decided in ADR-040).

**Why.** While the interval does not change, every check covers the same time, so options 1 and 2 give exactly the same number. Option 2 needs the interval stored in every check, a schema change, for a difference that only appears when the interval changes inside the period.

**Weak point.** If the interval changes inside the period, every check weighs the same although it covers a different time (a day at 5 min and a day at 30 s: the second weighs 10 times more).

**Reversibility.** Easy. Moving to option 2 means adding `interval_seconds` to `checks`. Thanks to the 30-day retention, the whole history has it 30 days later, without backfilling.

---

## ADR-047 — A monitor's current status

- **Date:** 2026-10-28 (Phase 5)
- **Status:** Accepted

**Decision.** `status`, derived from the latest check by a pure function (`pulseops/status.py`):

| Status | When |
|---|---|
| `paused` | The monitor is inactive (wins over everything) |
| `unknown` | No check yet, or the latest is older than 2 × interval + 60 s |
| `up` / `down` | The latest check, when it is recent |

**Why the staleness rule.** If the worker stops, the last check stays "up" forever. Reporting it as current would be a lie; past that threshold it is "no data". The 60 s margin covers the scheduler's 5 s tick and the check itself. The boundary is tested (180 s still fresh for a 60 s interval, 181 s stale).

**Rejected.** Always returning the last outcome, however old: simpler, but wrong exactly when it matters (the worker is down).

**Reversibility.** Easy: one function.

---

## ADR-048 — History and stats endpoints

- **Date:** 2026-10-28 (Phase 5)
- **Status:** Accepted

**Decision.** Two routes under the monitor, with the API key, 404 `monitor_not_found` for an unknown monitor:

| Route | Response |
|---|---|
| `GET /api/v1/monitors/{id}/checks?limit=50&cursor=…` | `items` (`scheduled_at`, `is_up`, `status_code`, `response_time_ms`, `error_kind`, `error_detail`), newest first, and `next_cursor` (`null` on the last page). `limit` 1–100 |
| `GET /api/v1/monitors/{id}/stats?period=7d` | `status` and `last_check` (ADR-047); `period`, `from`, `to`; `uptime_percent` (ADR-046); `avg_response_time_ms` and `p95_response_time_ms` (ADR-049); `checks_total`, `checks_up`, `checks_down` |

- **Periods:** a closed list, `24h`, `7d` (default) and `30d`, as windows ending at the database's `now()`. Anything else is a 422. Nothing older than 30 days exists anyway (retention).
- **`error_detail` is returned:** it is the user's own data, behind the API key. It still never reaches the logs (ADR-044).
- **The internal monitor id is never exposed:** items do not carry `monitor_id`.

**Rejected.**
- **Status inside `GET /monitors`:** one more query per monitor; to be revisited with a UI (Phase 8).
- **A separate `/status` route:** another route for data already in `/stats`.
- **Free `from`/`to` dates:** more validation for no current need. They can be added later without breaking anything.

**Reversibility.** Hard: routes and response shapes are a public contract.

---

## ADR-049 — Latency statistics, computed on demand

- **Date:** 2026-10-28 (Phase 5)
- **Status:** Accepted

**Decision.**
- **Mean and 95th percentile, over the checks that were up only.**
  - **Why only those:** timeouts have no time, and a 500 answered in 5 ms would flatter a broken site.
  - **Why the p95:** it shows the spikes a mean hides, and PostgreSQL computes it in the same query (`percentile_cont(0.95) WITHIN GROUP … FILTER`).
- **On demand:** one aggregate query over the primary key `(monitor_id, scheduled_at)`, no precomputed tables.
- **Measured** (`scripts/measure_queries.py`, ADR-052; 10 monitors, 892,810 checks): `/stats` over 30 days (86,400 checks of one monitor) takes **~19-20 ms** (median of 20 runs), well under the 100 ms target. A history page takes ~1.7 ms.

**Rejected.** Hourly rollups (a table or materialized view): very fast, but one more thing to keep in sync. To be revisited if the measurement degrades or there are many monitors.

**Weak point.** The MVP only asked for the mean; the p95 is one more field to maintain.

**Reversibility.** Easy for the computation; the field names are part of the contract (ADR-048).

---

## ADR-050 — Opaque history cursors

- **Date:** 2026-10-28 (Phase 5)
- **Status:** Accepted

**Context.** ADR-015 decided keyset pagination over `(monitor_id, scheduled_at)`. With OFFSET, a check arriving while a client pages shifts every page by one.

**Decision.**
- **Format:** `base64url("v1:<scheduled_at in microseconds>")`, without padding. The query is `scheduled_at < cursor ORDER BY scheduled_at DESC LIMIT n+1`; the extra row tells whether there is a next page.
- **Opaque:** clients only pass back the `next_cursor` they received. The version prefix lets the format change without breaking them.
- **Strict decoding:** length, strict base64, `v1` prefix, ASCII digits only, at most 17 of them. Anything else is 422 `invalid_cursor`, and the cursor is never echoed. A well-formed cursor with another time is harmless: the monitor always comes from the URL, so it can only return an empty or a different page of that same monitor.
- **Microseconds:** the cursor keeps the exact database value (`pulseops/timestamps.py`, shared with the queue payload).

**Rejected.** A readable `before=<timestamp>` parameter: easy to debug, but it would become part of the contract.

**Reversibility.** Hard for the parameter names; easy for the format (the version prefix).

---

## ADR-051 — Retention: hourly batch deletes on a dedicated lane

- **Date:** 2026-10-28 (Phase 5)
- **Status:** Accepted

**Decision.**
- **A cron every hour, `delete_expired_checks`,** deletes checks older than 30 days (`pulseops/retention.py`).
- **Batches of 5,000**, each in its own short transaction, so locks stay short and what was deleted stays deleted.
- **A 60 s budget per run:** no new batch starts after 60 s, and what is left goes in the next run. ArdiQ's `timeout` (90 s) is only a safety net that never cuts a batch in normal conditions.
- **Its own lane, `maintenance`, limited to 1** (requested by the project owner). The lanes become `["checks", "maintenance", "scheduler"]`, and **`checks` drops from 31 to 30**, so checks (30) + cleanup (1) always leave at least one slot for the scheduler.
  - **Verified against Valkey:** with `checks` at 31, the scheduler did not run while checks and cleanup were busy; with 30 it runs at once (`test_scheduler_keeps_its_slot_while_checks_and_cleanup_are_busy`).
- **Delete by physical address (`ctid`), with the date checked again:** `DELETE … WHERE ctid = ANY(ARRAY(SELECT ctid … WHERE scheduled_at < cutoff LIMIT 5000)) AND scheduled_at < cutoff`.
  - **Why `ctid`:** the first version joined on `(monitor_id, scheduled_at) IN (subquery)`. Depending on the statistics sample, PostgreSQL picked a hash join over a **full table scan**, 99 ms per batch, growing with the table. With `ctid` there is no join: a TID scan visits exactly those addresses. No sequential scan in 5 measured runs.
  - **Why recheck the date** (requested by the project owner): selection and deletion are one statement, so an address cannot be reused in between. If one ever pointed at a recent check, nothing would be deleted. `test_an_address_reused_by_a_recent_check_is_never_deleted` simulates it.
- **Index choice is left to PostgreSQL:**
  - with a backlog, the selection uses the **BRIN index** on `scheduled_at`;
  - for the hourly steady state, PostgreSQL 18 prefers the **primary key with a skip scan** (one index search per monitor): 0.7 ms with 10 monitors, 4.8 ms with 1,000.
  - Either way the table is never scanned whole.

**Rejected.**
- **Partitioning `checks` by day** and dropping partitions: best at scale, much more complexity. Noted for when `checks` grows a lot.
- **`pg_cron`:** not in the image, and it would put PulseOps logic inside the database.
- **One huge DELETE:** long locks and bloat.

**Weak point.** Switching from the skip scan to the BRIN index with many thousands of monitors is expected but not verified.

**Reversibility.** Easy.

---

## ADR-052 — Evidence tooling for Phase 5

- **Date:** 2026-10-28 (Phase 5)
- **Status:** Accepted

**Decision.**
- **`scripts/measure_queries.py`:** seeds the test database with realistic checks (10 monitors × 31 days every 30 s by default, inserted in time order), runs `EXPLAIN ANALYZE` and 20 real runs of the history, stats and retention queries, and deletes everything it created. Options: `--plans`, `--monitors`, `--days`, `--interval`.
  - **It measures the API's own SQL:** the repository builds its statements in separate functions (`history_statement`, `stats_statement`, `expired_batch_statement`).
  - **`EXPLAIN` without string-built SQL:** done with SQLAlchemy's compiler extension, which keeps bound parameters. The DELETE's plan is rolled back.
  - **`ANALYZE` needs the table owner,** so the script runs it as `pulseops_owner`; in production, autovacuum does it.
- **The smoke test checks the worker too:** a new monitor must get its first automatic check within 20 s, then `/checks` and `/stats` are checked through the API. 29 checks in total.

**Reversibility.** Easy.
