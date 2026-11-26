-- 0002: history of Job transitions (lecture 104, "А зачем нам история?").
-- A row is written in the SAME transaction as the change of jobs.status (ADR-0006): both or neither.
CREATE TABLE job_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,          -- order of events
    job_id          TEXT NOT NULL REFERENCES jobs (id),
    from_status     TEXT CHECK (from_status IS NULL OR from_status IN ('created', 'running', 'done', 'error')),
    to_status       TEXT NOT NULL CHECK (to_status IN ('created', 'running', 'done', 'error')),
    error_code      TEXT,
    at              TEXT NOT NULL                               -- ISO 8601, UTC
);

CREATE INDEX ix_job_history_job_id ON job_history (job_id, id);

-- Jobs written before this migration get one record with their current state, so every Job has a history.
INSERT INTO job_history (job_id, from_status, to_status, error_code, at)
SELECT id, NULL, status, error_code, COALESCE(finished_at, started_at, created_at)
FROM jobs
ORDER BY created_at;
