# ADR-0006: SQLite storage with numbered SQL migrations, one transaction per transition, HTTP on the standard library

- **Date:** 2026-11-26
- **Status:** Accepted (Practice 4). Amends ADR-0001 (HTTP layer: stdlib WSGI instead of FastAPI) and supersedes
  ADR-0005 for production use (the in-memory repository stays for unit tests).
- **Deciders:** БалчаНМ, ТегеньСБ

## Context and constraints

- Practice 4: network API over the core, contract file that matches the code, storage with **migrations**
  (not tables created by code at startup), Jobs and results survive a restart, unified errors, idempotency keys
  in the database, and **a change of state and its result/history in one transaction**.
- Our contract already exists and is hand-written: `docs/api/openapi.yaml` (contract-first since Practice 2).
  Its error body is our own `ErrorResponse`; validation errors list **every** wrong field in `details.fields[]`
  produced by `Tool.validate` (tool-contract.md §3).
- The core has no third-party dependency and `tests/test_core_boundaries.py` keeps it that way.
- One process (ADR-0001), synchronous execution (ADR-0002), PostgreSQL planned by Practice 7.

## Decision

1. **Storage: SQLite** through `SqliteJobRepository` (`src/jobservice/infrastructure/sqlite_job_repository.py`)
   behind the existing `JobRepository` port. The Dispatcher did not change.
2. **Migrations: numbered SQL files** `infrastructure/migrations/NNNN_name.sql` + table `schema_migrations`
   (version, name, SHA-256, applied_at), applied by `python -m jobservice migrate`. Each migration runs in one
   transaction with its version row. An edited applied migration, a gap in numbers or a database newer than the
   code stop the migration. The service **never** creates tables: at startup it checks that the schema is current
   and refuses to start otherwise.
3. **Schema rules in the database too:** `UNIQUE(idempotency_key)` (ADR-0003, decision 5); `CHECK`s for the Job
   invariants (result only when `done`, error only when `error`, `finished_at` only when final, `started_at` when
   `running`, closed list of statuses); partial index on unfinished Jobs for startup recovery.
4. **History:** table `job_history` (migration 0002, with a backfill for Jobs written under schema 1).
   `add` = `INSERT jobs` + `INSERT job_history`; `save` = `UPDATE jobs` + `INSERT job_history` when the status
   changed — each in **one** `BEGIN IMMEDIATE … COMMIT`. Either both rows change or none.
   `save` also refuses to overwrite a Job that is already final with another state (`JobStateConflict`, a lost
   update) — the in-memory repository follows the same rule.
5. **No transaction is open while a Tool runs.** The Dispatcher commits `running` before `Tool.execute` and the
   final state after it; the HTTP answer is sent only after the final `COMMIT` (lecture 104, "ответ — только после
   фиксации").
6. **HTTP: a WSGI application on the standard library** (`src/jobservice/api/app.py`, threaded `wsgiref` server in
   `server.py`). The code is **checked against** `openapi.yaml`: routes = operations, every response in the tests
   is validated against the documented status, schema and headers (`tests/openapi_contract.py`), every example in
   the contract is validated against its schema, and a seeded fuzz test sends random bodies.
7. Storage failures that a retry can fix become `503 STORAGE_UNAVAILABLE` with `Retry-After`; anything unexpected
   becomes `500 INTERNAL_ERROR`. Driver messages, SQL and paths go to the JSON log under the correlation id only.

## Alternatives considered

| Alternative | Why not now |
|---|---|
| FastAPI + Pydantic (ADR-0001, lecture 104 example) | FastAPI **generates** its own OpenAPI from code — a second contract next to our hand-written one, so we would have to pick a single source of truth again. Its default validation answer (`422 {"detail": [...]}`) breaks our `ErrorResponse`; Pydantic would duplicate `Tool.validate` (two validators that can disagree). Would add 3 runtime packages for 3 endpoints. Revisit below. |
| Alembic + SQLAlchemy | Autogeneration from ORM models is the main benefit; we have no ORM and two tables. Numbered SQL files are explicitly allowed by the task and keep the SQL readable in review. |
| `CREATE TABLE IF NOT EXISTS` at startup | Forbidden by the task; gives no version, no history of schema changes, no protection against an edited schema. |
| Result and status in one row, no history table | One `UPDATE` is atomic by itself, but then there is nothing to diagnose a Job with ("Без истории диагностика превращается в археологию", lecture 104). |
| Keep a connection/transaction for the whole request | Would hold the SQLite write lock while a Tool runs (up to 17 s for weather) and block every other writer. |

## Consequences and cost

- **+** No third-party runtime dependency; `make run` works on a bare Python 3.10+.
- **+** The contract stays the single source of truth; drift is caught by tests, not by clients.
- **+** Atomic state + history, double defence for idempotency (application check + UNIQUE), invariants enforced by
  the database as well.
- **−** About 250 lines of HTTP code we maintain ourselves (routing, body limits, JSON parsing); no Swagger UI page
  (the contract can be opened in any Swagger viewer).
- **−** `wsgiref` is a development-grade server (thread per request, no TLS). Fine on localhost / trusted network
  (ADR-0004); a production deployment would put it behind a real WSGI server (any WSGI server can run `build_app`).
- **−** SQLite allows one writer at a time; writes are short, so this is acceptable for one process.
- **−** If the final write fails, the Job stays `running` until the next start (then `JOB_INTERRUPTED`); the client
  got `500`/`503` and can see the state with `GET /jobs/{id}`.

## Revisit when

- PostgreSQL (Practice 7): same migrations idea, SQL dialect differences (`BEGIN IMMEDIATE`, partial index syntax),
  `ON CONFLICT` for the key; run the repository contract tests against it.
- The number of endpoints grows or async I/O is needed (weather in Practice 6, LLM Tool): consider FastAPI **with**
  a test that compares the generated OpenAPI with `docs/api/openapi.yaml`.
- Several processes: startup recovery needs leases (ADR-0002, "Revisit when").
