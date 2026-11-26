-- 0001: the jobs table (Practice 4).
-- One row = one Job. The rules from architecture.md §3 that the database can check are written as CHECKs,
-- so a bug in the code cannot store a Job that breaks them.
CREATE TABLE jobs (
    id                  TEXT PRIMARY KEY,                       -- UUIDv4 (ADR-0004)
    operation           TEXT NOT NULL,
    params_json         TEXT NOT NULL,                          -- normalised params, never change
    idempotency_key     TEXT NOT NULL,
    request_hash        TEXT NOT NULL,                          -- SHA-256 of the body as sent (ADR-0003)
    tool_version        TEXT NOT NULL,
    correlation_id      TEXT NOT NULL,
    status              TEXT NOT NULL CHECK (status IN ('created', 'running', 'done', 'error')),
    result_json         TEXT,
    error_code          TEXT,
    error_message       TEXT,
    error_details_json  TEXT,
    created_at          TEXT NOT NULL,                          -- ISO 8601, UTC
    started_at          TEXT,
    finished_at         TEXT,
    -- ADR-0003, decision 5: the second line of defence against a double click / a race of two requests.
    CONSTRAINT uq_jobs_idempotency_key UNIQUE (idempotency_key),
    -- Job invariants 1–3 (domain/job.py).
    CONSTRAINT ck_jobs_result_only_when_done  CHECK ((status = 'done')  = (result_json IS NOT NULL)),
    CONSTRAINT ck_jobs_error_only_when_error  CHECK ((status = 'error') = (error_code IS NOT NULL AND error_message IS NOT NULL)),
    CONSTRAINT ck_jobs_finished_when_final    CHECK ((status IN ('done', 'error')) = (finished_at IS NOT NULL)),
    CONSTRAINT ck_jobs_started_when_running   CHECK (status <> 'running' OR started_at IS NOT NULL)
);

-- Startup recovery (ADR-0002, decision 3) looks for unfinished Jobs; a partial index stays tiny.
-- Lookups by id use the primary key, lookups by idempotency key use the UNIQUE index above.
CREATE INDEX ix_jobs_unfinished ON jobs (status) WHERE status IN ('created', 'running');
