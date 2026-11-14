# ADR-0003: Protection against repeated requests — required `Idempotency-Key` on `POST /jobs`

- **Date:** 2026-11-14
- **Status:** Accepted (Practice 2)
- **Deciders:** БалчаНМ, ТегеньСБ

## Context and constraints

- Cards K1 (double click, 100 ms apart) and K2 (response lost after the server finished) — a timeout does not mean
  the Job was not executed (lecture 102, "Таймаут не факт, что операция не выполнилась").
- Requirements: "shall not accept a duplicate submission of the same request" (scenario 1),
  "shall not create duplicate conversion/transformation records" (scenarios 3, 4).
- The project checklist requires at least one idempotent operation: `POST /jobs` with an idempotency key.
- Execution is synchronous (ADR-0002), so a duplicate can arrive while the first request is still `running`.

## Decision

1. `POST /jobs` **requires** the header `Idempotency-Key` (1–128 visible ASCII characters; a UUID is recommended).
   Missing or invalid → `400 IDEMPOTENCY_KEY_REQUIRED`, no Job.
2. The key is stored with the Job together with `request_hash` = SHA-256 of the canonical JSON of
   `{operation, params}` (keys sorted, no whitespace) **as sent by the client, before defaults are applied**.
   A retry must resend the same body; adding an explicit default value (e.g. `precision: 3`) counts as a different
   body. The `jobs` table has a **unique constraint** on the key.
3. Same key, same hash → the existing Job is returned **as it is now** with `200` and `Idempotent-Replayed: true`;
   the Tool is not executed again. If the first request is still executing, the client sees `created`/`running`
   and polls `GET /jobs/{id}`.
4. Same key, different hash → `409 IDEMPOTENCY_KEY_REUSED` with `existing_job_id`.
5. Two requests with the same new key at the same moment: both try to insert; the unique constraint lets only one
   win; the loser reads the winner's Job and answers as in 3.
6. Requests rejected before a Job exists (`400/413/415/422`) do not store the key: the client may fix the body and
   send it again with the same key.
7. Keys live as long as their Job (no expiry in v1). Keys are global because there is no client identity
   (ADR-0004).
8. To run the same operation again on purpose (e.g. after `JOB_INTERRUPTED` or `WEATHER_SERVICE_UNAVAILABLE`), the
   client uses a **new** key → a new Job; the old Job is not changed.

## Alternatives considered

| Alternative | Why not now |
|---|---|
| Optional key (no key → always a new Job) | K1 would still create two Jobs for clients that forget the header; our requirements forbid duplicate records. |
| Server-side de-duplication by request content and time window | Two legitimately identical requests (same conversion twice for two samples) would be merged; the window length is arbitrary. |
| Key with expiry (e.g. 24 h) | Needs a cleanup job and makes the answer depend on time; storage of short strings is cheap at our scale. |
| `PUT /jobs/{client_generated_id}` | Also idempotent, but makes clients generate Job ids and mixes identity with retry protection. |

## Consequences and cost

- **+** K1 and K2 have one simple rule; replays never re-run a Tool or re-call OpenWeatherMap.
- **+** Atomic thanks to the unique constraint, not to application locks.
- **−** Every client must generate and keep a key per intended Job.
- **−** A replay returns old data (e.g. weather observed an hour ago) — by design; `finished_at` and
  `result.observed_at` show the age.
- **−** The table grows with keys; the key column needs an index.

## Revisit when

- Clients get identities (ADR-0004 revisited) → scope keys per client;
- storage growth becomes a problem → add expiry with a documented window;
- asynchronous execution is introduced (ADR-0002 revisited) → `202` replay semantics must be redefined.
