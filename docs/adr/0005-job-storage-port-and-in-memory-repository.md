# ADR-0005: Jobs are stored behind a `JobRepository` port; Practice 3 uses an in-memory implementation

- **Date:** 2026-11-22
- **Status:** Accepted (Practice 3)
- **Deciders:** БалчаНМ, ТегеньСБ

## Context and constraints

- Practice 3 delivers the domain core (Job, Registry, Dispatcher, two Tools). HTTP and the database arrive in
  Practice 4; PostgreSQL by Practice 7 (architecture.md, component diagram).
- The core must be testable without a web framework or a database. `tests/test_core_boundaries.py` fails if a core
  file imports one.
- The Dispatcher needs storage for three things from earlier decisions:
  - a **unique idempotency key**, so a repeated request never runs a Tool twice (ADR-0003, decision 5);
  - **lookup of unfinished Jobs** for restart recovery (ADR-0002, decision 3);
  - reading a stored Job later (`GET /jobs/{id}`).
- The architecture already names `SqlJobRepository implements JobRepository`; the interface exists on paper but
  not yet in code.

## Decision

1. The application layer defines the storage interface `JobRepository` in
   `src/jobservice/application/ports.py`. Its methods describe what the Dispatcher needs, not generic CRUD:
   `add`, `save`, `get`, `find_by_key`, `find_unfinished`.
2. `add` must behave like a database **UNIQUE constraint** on the idempotency key: it raises
   `DuplicateIdempotencyKey` and stores nothing. Every implementation must keep this rule.
3. For Practice 3 the only implementation is `InMemoryJobRepository`
   (`src/jobservice/infrastructure/memory_job_repository.py`). It copies Jobs on write and on read, so changing a
   Job object after `save` does not change what is stored, and it uses one lock so each method is atomic.
4. The Dispatcher and the Tools depend only on the interface. The implementation is chosen in one place,
   `src/jobservice/bootstrap.py`.
5. The in-memory repository is **not** used in production. Practice 4 adds `SqlJobRepository` behind the same
   interface, and the Dispatcher tests must pass with both.

## Alternatives considered

| Alternative | Why not now |
|---|---|
| Write `SqlJobRepository` (SQLite + migrations) in Practice 3 | Brings a database, schema and migrations into a practice about the domain core. Hides logic errors behind storage errors. Practice 4 is planned for it. |
| Plain `dict` inside the Dispatcher, no interface | Fast to write, but the Dispatcher would own storage details and Practice 4 would have to change it. Breaks the rule that the Dispatcher sees only `submit()` / `get()` and a repository interface (architecture.md, Dispatcher row). |
| Mock repository inside each test | Every test would invent its own storage rules; the unique-key rule could differ between tests. One shared in-memory implementation keeps the rule in one place. |

## Consequences and cost

- **+** The core runs and is tested with no framework and no database; the whole test suite runs in well under a
  second.
- **+** The unique-key rule is written down once as part of the interface (decision 2) and is the second line of
  defence for card K1/З1: if the Dispatcher's own check were skipped, a repeated key is still refused by storage.
- **+** Switching to SQL in Practice 4 changes `bootstrap.py` and adds one class; the Dispatcher does not change.
- **−** Jobs are lost when the process stops. This is acceptable only until Practice 4. Because of this, restart
  recovery (ADR-0002, decision 3) is exercised in tests by simulating a restart, not by a real database.
- **−** The in-memory version can hide problems that appear only with a real database (transactions, concurrent
  writers, column limits). Mitigation: in Practice 4 run the Dispatcher tests, plus tests of the unique-key rule, against `SqlJobRepository` too.
- **−** One lock serialises all repository calls. Fine for tests and one process; not a design for load.

## Revisit when

- `SqlJobRepository` is added (Practice 4): make the storage tests run against every implementation,
  and update this ADR's status to "Superseded for production use".
- Several service instances run at once: a unique constraint in a shared database becomes the only safe place for
  the idempotency rule (see also "Revisit when" in ADR-0002).
