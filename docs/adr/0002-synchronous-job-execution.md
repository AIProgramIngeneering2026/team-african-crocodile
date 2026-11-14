# ADR-0002: Jobs are executed synchronously inside `POST /jobs`; no cancellation; interrupted Jobs fail on restart

- **Date:** 2026-11-14
- **Status:** Accepted (Practice 2)
- **Deciders:** БалчаНМ, ТегеньСБ

## Context and constraints

- Local Tools finish in milliseconds. `get_weather` is bounded: connect timeout 3 s, read timeout 10 s, one retry
  for connection errors/5xx, total budget 17 s (tool-contract.md Section 4.2).
- The project needs a Job with history and a lifecycle, and results must be readable after the request
  (`GET /jobs/{id}`).
- Practices 3–4 must deliver a working core and API soon; a queue/worker adds components we do not need yet.
- Cards K6 (cancel) and K9 (restart while `running`) need explicit answers.

## Decision

1. `POST /jobs` saves the Job (`created`), runs it (`running`) and saves the final state (`done`/`error`)
   **before** responding. The response contains the final Job. `GET /jobs/{id}` returns any Job later.
2. **Cancellation is not supported** in v1: there is no `cancelled` state and no cancel endpoint. A client that
   disconnects does not stop the Job; the Job finishes and is stored.
3. **Restart recovery:** on startup, before accepting requests, the Dispatcher moves every Job in `created` or
   `running` to `error` with code `JOB_INTERRUPTED` and sets `finished_at`. (In one process every non-final Job
   found at startup was being executed by the previous, stopped process.) The client finds this with
   `GET /jobs/{id}` or by repeating the request with the same `Idempotency-Key` (ADR-0003), and runs it again with a
   new key.

## Alternatives considered

| Alternative | Why not now |
|---|---|
| Asynchronous: `202 Accepted` + background worker + polling | Needs a queue or a polling worker, claim/lease of Jobs, more states and recovery rules. Pays for long jobs that we do not have. |
| Synchronous with cancellation (`DELETE /jobs/{id}` or `POST /jobs/{id}/cancel`) | A synchronous Job is already finished when a second request could arrive (except during the ≤ 17 s weather call). Cancelling an HTTP call in flight gives an unknown result. Little value, real complexity. |
| Restart recovery by re-running interrupted Jobs automatically | Safe for our pure Tools, but it would hide failures and needs a worker that owns the retry; a client that already got a timeout cannot tell which run produced the result. |

## Consequences and cost

- **+** Simple lifecycle (4 states), simple API, one place for the whole scenario.
- **+** K6 and K9 have explicit answers.
- **−** The HTTP connection is held up to ≈ 17 s for weather; clients must use a timeout ≥ 20 s.
  A shorter client timeout is handled by idempotent retry (card K2).
- **−** A Job interrupted by a restart is not finished automatically; the client must re-submit with a new key.
- **−** Throughput is limited by the number of server workers, because each one waits for the weather call.

## Revisit when

- A Tool may run longer than ~20 s (LLM Tool in semester 2 is the expected trigger) → switch that operation to
  `202 Accepted` + worker; then add the `cancelled` state and cancellation;
- several service instances run at once (recovery "all non-final Jobs at startup" would become wrong; it would
  need a lease/heartbeat per Job).
