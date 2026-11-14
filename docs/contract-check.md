# Contract check with the poker deck (K1–K10)

Contract under test: [api/openapi.yaml](api/openapi.yaml), [tool-contract.md](tool-contract.md),
[architecture.md section 3 (Job states)](architecture.md#3-job-state-diagram), ADRs in [adr/](adr/).
Deck: `tasks/p2_poker/README.md` in Zadania. Date: 2026-11-14.

Each card was translated into a concrete request to our service. Every answer points to the place where the
contract says it.

| Карта | Ответ контракта |
|---|---|
| **К1 Двойной клик** - `POST /jobs` `{operation: convert_unit, params: {value: 25, from_unit: C, to_unit: F, precision: 2}}` sent twice 100 ms apart with the same `Idempotency-Key` | One Job. The first request -> `201`; the second -> `200` with the **same** Job `id`, header `Idempotent-Replayed: true`, the Tool is not executed again; if the first is still executing, the second sees `status: running`. Two simultaneous inserts are resolved by the unique constraint on the key. Without the header  -> `400 IDEMPOTENCY_KEY_REQUIRED`, no Job. - `openapi.yaml`: `POST /jobs` responses `200`, `400`; [ADR-0003](adr/0003-idempotency-key.md) Decision 1, 3, 5 |
| **К2 Ответ потерялся** - `get_weather` for London executed, client got a connection timeout | Client repeats `POST /jobs` with the **same** key and body -> `200` with the stored Job (`done` with the weather, or `error`); OpenWeatherMap is not called again. If the client has the `Location`/`id`, it can also `GET /jobs/{id}`. Repeat with a different body -> `409 IDEMPOTENCY_KEY_REUSED`. - `openapi.yaml`: `POST /jobs` `200`/`409`, `GET /jobs/{job_id}`; [ADR-0003](adr/0003-idempotency-key.md) Decision 3, 4 |
| **К3 Неизвестная операция** - `{operation: "convert_currency", params: {...}}` | `422`, `error.code = UNKNOWN_OPERATION`, `details.operation`, `details.available_operations = [convert_unit, get_weather, transform_text]`. No Job is created, nothing in history. - `openapi.yaml`: `POST /jobs` -> `422` example `unknownOperation`; [tool-contract.md Section 3](tool-contract.md#3-who-validates-parameters--tool-or-caller) |
| **К4 Кривые параметры** — `convert_unit` without `value`, `precision: 9`, `value: "25"` (string) | `422 VALIDATION_ERROR`; `details.fields[]` lists **every** wrong field with JSON path, code and rejected value (`params.value FIELD_REQUIRED`, `params.precision INVALID_PRECISION`, `FIELD_TYPE`…). No Job. Values that are well-formed but wrong for the domain (unit `parsec`, −300 °C, metre -> kilogram) create a Job that ends in `error` (`UNSUPPORTED_UNIT`, `BELOW_ABSOLUTE_ZERO`, `INCOMPATIBLE_DIMENSIONS`) and stays in history. - `openapi.yaml`: `FieldError`, `ConvertUnitParams` description, `422` example `validation`; [tool-contract.md section 3, section 4](tool-contract.md#3-who-validates-parameters--tool-or-caller) |
| **К5 Воскрешение** — client wants to run again a Job that is `done` (or `error` after `WEATHER_SERVICE_UNAVAILABLE`) | Not allowed: `done`/`error` are final, there is no restart operation. Same key -> the same old Job is returned unchanged (`200`). New key → a **new** Job with a new `id`; the old Job and its result/error stay unchanged in history. - [architecture.md section 3 "Forbidden transitions"](architecture.md#forbidden-transitions-and-what-the-system-answers); [ADR-0003](adr/0003-idempotency-key.md) Decision 8 |
| **К6 Отмена** - client changes its mind while `get_weather` is `running` | Not supported in v1 - consciously not closed: no `cancelled` state, no cancel endpoint; closing the connection does not stop the Job, it finishes and is stored. Reason: synchronous execution ≤ 17 s, cancelling an HTTP call gives an unknown result. - [ADR-0002](adr/0002-synchronous-job-execution.md) Decision 2; [architecture.md section 3](architecture.md#forbidden-transitions-and-what-the-system-answers) |
| **К7 Огромный вход** - 1000× larger: 10 MB text for `transform_text`, `value: 1e300`, OpenWeatherMap returns a 50 MB body | Body > 64 KiB -> `413 PAYLOAD_TOO_LARGE` from the HTTP layer before JSON parsing, no Job. Text > 10 000 chars (body still < 64 KiB) -> `422 VALIDATION_ERROR` / `TEXT_TOO_LONG`. `|value|` > 1e12 -> `422` / `VALUE_OUT_OF_RANGE`. Provider body > 1 MiB -> adapter stops reading -> Job `error` `MALFORMED_RESPONSE`. -> `openapi.yaml` `info.description` "Limits", `413` response; [tool-contract.md section 4.2](tool-contract.md#42-get_weather--weathertool-version-get_weather1) adapter table |
| **К8 Чужой или несуществующий id** — `GET /jobs/00000000-0000-4000-8000-000000000000`, `GET /jobs/abc`, id of another client's Job | Non-existent and malformed id -> the same `404 JOB_NOT_FOUND` (reveals nothing). Another client's Job: **consciously not closed** - v1 has no authentication or ownership; protection is unguessable UUIDv4 ids, no list endpoint, no personal data in parameters. - `openapi.yaml`: `GET /jobs/{job_id}` `404`; [ADR-0004](adr/0004-no-authentication-in-v1.md) |
| **К9 Перезапуск сервера** - process restarted while a `get_weather` Job was `running` | On startup, before accepting requests, every `created`/`running` Job -> `error` with `JOB_INTERRUPTED` and `finished_at` (allowed transition). The client sees it via `GET /jobs/{id}` or by repeating with the same key, and runs it again with a new key. - [ADR-0002](adr/0002-synchronous-job-execution.md) Decision 3; [architecture.md section 3 "Allowed transitions"](architecture.md#allowed-transitions) |
| **К10 Внешний сервис** - OpenWeatherMap is silent for 30 s / answers garbage / renamed `main.temp` | Silent: read timeout 10 s, no retry -> Job `error` `WEATHER_SERVICE_UNAVAILABLE` (`cause: read_timeout`), client gets `201` with `status: error` after ≈ 10 s (worst case ≤ 17 s). Connection error / 5xx: one retry, then the same code. Garbage or renamed field -> `MALFORMED_RESPONSE` with `details.field`; implausible values -> `INVALID_DATA`. Nothing is cached; provider details stay in logs and in `OpenWeatherMapAdapter` only. 429 -> `RATE_LIMITED`, 401 -> `SERVICE_CONFIGURATION_ERROR`. - [tool-contract.md section 4.2](tool-contract.md#42-get_weather--weathertool-version-get_weather1) adapter table and total budget; [ADR-0001](adr/0001-modular-monolith-local-tools.md) |

**Summary:** 8 of 10 cards are fully answered by the contract. K6 (cancel) and the "another client's Job" part of
K8 are consciously not closed, with reasons in ADR-0002 and ADR-0004. No card was "not applicable".

---

## Что предложил ИИ

**Prompt:**

```text
You are the attacking team in "contract poker". Below is the contract of our service: openapi.yaml,
tool-contract.md, the Job state diagram from architecture.md, and ADR-0001…0004. Below that is the deck
(cards K1–K10) and our table of answers for each card.

Your task: find 3 MORE concrete situations that our contract does NOT answer — not repeats of K1–K10 and not
things the table already covers. For each situation give:
1) the concrete request and data,
2) the question "what does the API return, what state is the Job in?",
3) why the contract has no answer (quote the place that is silent or contradictory),
4) how you would close the gap with the smallest change.

[openapi.yaml]
[tool-contract.md]
[architecture.md §3]
[ADR-0001…0004]
[deck K1–K10]
[our K1–K10 table]
```

**Findings and decisions:**

| # | Situation the model found | Gap | Decision |
|---|---|---|---|
| 1 | `get_weather {city: "Springfield", country: "US"}` — the provider returns several Springfields even with a country code. | The contract said `AMBIGUOUS_CITY` only for "> 1 candidate and no `country`". With a country and still several candidates the behaviour was undefined; the client cannot narrow further because there is no `state` parameter. | **Accepted.** With `country` given, the Tool takes the provider's first candidate; `city_name`, `lat`, `lon` in the result show which one. No new parameter (scope unchanged). Changed: [tool-contract.md §4.2](tool-contract.md#42-get_weather--weathertool-version-get_weather1) "Algorithm". |
| 2 | Two `get_weather` Jobs for London+metric arrive at the same moment with an empty cache; also: the provider's `observed_at` is already 50 minutes old when cached. | Requirement 2 says "shall not create duplicate cache entries", but the contract did not say what happens with parallel misses, and whether TTL is counted from `observed_at` or from caching time. | **Accepted.** `put` overwrites by key (never two entries per key); parallel misses may both call the provider (accepted cost); TTL counted from `cached_at`, the result shows both `cached_at` and `observed_at`. Changed: [tool-contract.md §4.2](tool-contract.md#42-get_weather--weathertool-version-get_weather1) "Cache rules". |
| 3 | First request `{value: 12.345, from_unit: km, to_unit: mi, engineer_id: E1}`; retry with the same key adds `precision: 3` (the default). | Is it "the same body"? If the hash is over the raw body, the retry gets `409` although the meaning is the same. | **Rejected (only documented).** A retry must resend exactly the same body — that is what HTTP client retries do. Hashing normalised params would require validating before the idempotency lookup and would couple the key to Tool defaults, which may change between Tool versions. Clarified in [ADR-0003](adr/0003-idempotency-key.md) Decision 2. |