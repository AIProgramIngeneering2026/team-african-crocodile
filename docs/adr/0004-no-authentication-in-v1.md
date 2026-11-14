# ADR-0004: No authentication and no Job ownership in v1; Job ids are random UUIDv4

- **Date:** 2026-11-14
- **Status:** Accepted (Practice 2)
- **Deciders:** БалчаНМ, ТегеньСБ

## Context and constraints

- Card K8: a client asks for a Job that does not exist or that another client created.
- README: the service is a course project used by researchers, engineers, authors and course reviewers through
  one API. Authentication and user management are not in the project scope and are not graded.
- The project rules exclude real personal data. Our parameters contain only measurements, city names, short texts
  and opaque ids (`experiment_id`, `engineer_id`, `author_id`, `document_id`).

## Decision

1. v1 has **no authentication and no ownership** of Jobs. Every client that knows a Job id can read that Job.
2. Job ids are **random UUIDv4** (122 random bits), never sequential, so ids cannot be guessed or enumerated.
3. There is **no endpoint that lists Jobs**, so history is reachable only by id.
4. `GET /jobs/{id}` returns `404 JOB_NOT_FOUND` for both a non-existent id and a malformed id — the answer does not
   reveal anything about other Jobs.
5. Documented in `openapi.yaml`: do not put personal data into parameters; the ids in parameters are opaque labels.
6. The service is intended to run on localhost / a trusted network (docker compose).

## Alternatives considered

| Alternative | Why not now |
|---|---|
| API keys per client + `owner_id` on Job; foreign Job → `404` | Needs key issuing, storage and configuration; out of scope for the course checkpoints. |
| OAuth2 / OpenID Connect | Much larger scope; external identity provider. |
| Sequential integer ids | Trivial to enumerate everyone's history. |

## Consequences and cost

- **+** Simple API and tests; K8 has an explicit answer.
- **−** Anyone with a Job id (e.g. copied into a chat) can read its parameters and result.
- **−** Idempotency keys are global (ADR-0003): two clients choosing the same key would collide
  (`409` or a replay of the other's Job). Using UUID keys makes this practically impossible.
- **−** No per-client rate limits; a single client can use up the OpenWeatherMap quota (mitigated by the 10-minute
  cache).

## Revisit when

- The service is exposed outside a trusted network;
- a requirement needs "my history" (list of my Jobs);
- any parameter may contain personal data.
