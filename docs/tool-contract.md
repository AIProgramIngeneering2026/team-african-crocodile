# Tool contract

A **Tool** (`convert_unit`, `get_weather`, `transform_text`). The Dispatcher talks
to every Tool only through this contract (Strategy pattern); the Registry finds a Tool by operation name
(Registry pattern). A new Tool = new class + one `registry.register(...)` line in the composition root. The
Dispatcher does not change.

## 1. Interface (Python, `app/application/tool.py`)

```python
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class FieldError:
    field: str          # JSON path in the request, e.g. "params.precision"
    code: str           # FieldErrorCode from openapi.yaml, e.g. "INVALID_PRECISION"
    message: str
    rejected_value: Any = None


class ParamsInvalid(Exception):
    """Stage 1: raised by Tool.validate. The Dispatcher turns it into 422 VALIDATION_ERROR. No Job is created."""
    def __init__(self, errors: list[FieldError]):
        self.errors = errors          # ALL wrong fields, not only the first one


@dataclass(frozen=True)
class ToolError:
    """Stage 2: a failure that is part of the Job history (Job.status = error)."""
    code: str                         # ErrorCode from openapi.yaml, e.g. "INCOMPATIBLE_DIMENSIONS"
    message: str                      # human-readable, safe to show to the client
    details: Mapping[str, Any] | None = None
    retryable: bool = False           # True: a new Job with the same params may succeed later


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: Mapping[str, Any] | None = None    # result payload when ok (ConversionResult, WeatherResult, TextResult)
    error: ToolError | None = None           # when not ok

    @staticmethod
    def success(data: Mapping[str, Any]) -> "ToolResult":
        return ToolResult(ok=True, data=data)

    @staticmethod
    def failure(error: ToolError) -> "ToolResult":
        return ToolResult(ok=False, error=error)


@dataclass(frozen=True)
class ToolContext:
    correlation_id: str
    deadline_s: float                 # time budget for execute(); WeatherTool: 17 s


class Tool(Protocol):
    name: str                         # operation name = Registry key, e.g. "convert_unit"
    version: str                      # contract version of this Tool, saved in Job.tool_version ("convert_unit/1")

    def validate(self, params: Mapping[str, Any]) -> Mapping[str, Any]:
        """Stage 1. Return normalised params (defaults applied, aliases canonicalised) or raise ParamsInvalid.
        Must be pure: no I/O, no clock, no network."""

    def execute(self, params: Mapping[str, Any], ctx: ToolContext) -> ToolResult:
        """Stage 2. Called only with params returned by validate(). Expected failures are returned as
        ToolResult.failure(...), never raised. Must not write to the Job storage and must not know about HTTP."""
```

```python
class Registry:
    def register(self, tool: Tool) -> None: ...      # raises DuplicateTool at startup if the name is taken
    def get(self, name: str) -> Tool | None: ...      # None → Dispatcher raises UnknownOperation(names())
    def names(self) -> list[str]: ...                 # sorted; used in UNKNOWN_OPERATION details
```
## 2. What a Tool receives and returns

| | Contents |
|---|---|
| **Input of `validate`** | `params` exactly as in the request body (`dict` from JSON). Can be anything — the Tool must not trust types. |
| **Output of `validate`** | Normalised params: defaults applied (`precision = 3`, `units = metric`, `profile = title-basic-v1`), unit aliases canonicalised (`°F` -> `F`), generated `experiment_id` when missing. These normalised params are what is saved in `Job.params`. |
| **Input of `execute`** | Normalised params + `ToolContext` (correlation id for logs, time budget). |
| **Output of `execute`** | `ToolResult.success(data)` — `data` matches `ConversionResult` / `WeatherResult` / `TextResult` in `openapi.yaml`; or `ToolResult.failure(ToolError)`. |
| **Exceptions** | `validate` may raise only `ParamsInvalid`. `execute` should not raise; if it does, the Dispatcher catches it, logs the stack trace and fails the Job with `TOOL_INTERNAL_ERROR` (message without internal details). |

Rules for every Tool:

1. **No side effects outside the Tool's own resources.** Tools never touch `JobRepository`, never change the Job
   state, never call another Tool. Saving history is the Dispatcher's job.
2. **No HTTP knowledge.** Tools return error *codes*; the HTTP layer chooses status codes.
3. **Provider details stay in the adapter.** A Tool that uses an external service talks to a port
   (`WeatherProvider`) and receives our types (`WeatherData`, `WeatherError`), never raw provider JSON.
4. **Determinism.** For local Tools the same normalised params give the same `data` (except timestamps).
5. **Every error code** a Tool can produce is listed in `openapi.yaml` (`ErrorCode` / `FieldErrorCode`) and in §4.

## 3. Who validates parameters — Tool or caller?

**The Tool owns its parameter rules.** The caller (HTTP layer, Dispatcher) checks only the envelope.
This is the split from lecture 103 ("Кому принадлежит проверка?") applied to our service:

| Rule | Owner | Result when broken |
|---|---|---|
| Body is JSON ≤ 64 KiB, has string `operation` and object `params`, has `Idempotency-Key` | HTTP layer | `400` / `413` / `415`, no Job |
| `operation` is registered | Dispatcher + Registry | `422 UNKNOWN_OPERATION`, no Job |
| **Stage 1 : form of params**: required fields, types, unknown fields, static limits (precision 0–6, uncertainty ≥ 0, finite value, \|value\| ≤ 1e12, length value > 0, text ≤ 10 000 chars, profile/units from a fixed list, required ids) | **Tool.validate** | `422 VALIDATION_ERROR` with **all** wrong fields, no Job, no history record |
| **Stage 2 : meaning and execution**: unit known in the unit registry, same dimension, above absolute zero, factor available, city found, provider answers correctly | **Tool.execute** (and the adapter for provider rules) | Job is saved and ends in `error`; the failed attempt stays in history |
| Finished Job cannot run again | **Job** (domain) | `InvalidJobTransition` |
| OpenWeatherMap JSON has the needed fields | **OpenWeatherMapAdapter** | `MALFORMED_RESPONSE` -> Job `error` |

Why two stages: requirements say that malformed input (e.g. missing `engineer_id`, empty text, value ≤ 0 for
length) must not create a history record, while a researcher must see physically wrong requests
(e.g. −300 °C, metre -> kilogram) in the history (requirements.md, scenarios 1, 3, 4, 6; decision on AI finding 3
in Practice 1).

The HTTP layer may repeat simple schema checks from `openapi.yaml` for a nicer message, but the authoritative rule
is in the Tool, so a future CLI entry point gets exactly the same behaviour.

## 4. Tools described through this contract

### 4.1 `convert_unit` — UnitConverterTool (version `convert_unit/1`)

Covers requirements scenarios 1, 3, 6.

| | |
|---|---|
| **Params** | `value` number (required); `from_unit`, `to_unit` strings (required); `precision` int 0–6, default 3; `uncertainty` number ≥ 0, optional; `experiment_id` optional; `engineer_id` (required for length). |
| **Units (registry v1)** | Exactly the units named in `requirements.md`: temperature `C`, `F`, `K`; length `mm`, `cm`, `m`, `km`, `in`, `ft`, `yd`, `mi`; mass `mg`, `g`, `kg`, `t`, `lb`, `oz`. Aliases: `°C`, `degC`, `celsius`; `°F` (U+00B0 or U+02DA), `degF`, `fahrenheit`; `kelvin`; `kilometer(s)`, `mile(s)`, `meter(s)`/`metre(s)`, `kilogram(s)`… - case-insensitive, trimmed. |
| **Algorithm** | Resolve both units → dimension check → temperature: canonical formulas (`F = C × 9/5 + 32`, `K = C + 273.15`); others: exact decimal factor via base unit (`1 mi = 1.609344 km` -> `1 km = 0.621371192237334 mi`). Uncertainty: multiplied by the scale part only (`±0.1 °C -> ±0.18 °F`). Rounding: `decimal` half-up to `precision`. |
| **Returns (`ConversionResult`)** | `value` (rounded), `raw_value`, `unit`, `uncertainty` / `uncertainty_supplied`, `precision`, `rounding_rule`, `display` (`"77.00 ± 0.18 °F"`), `source`, `conversion {id, version, kind, factor, expression}`, `experiment_id`, `engineer_id`. |
| **Stage-1 errors** (`422`) | `FIELD_REQUIRED`, `FIELD_TYPE`, `UNKNOWN_FIELD`, `VALUE_NOT_FINITE`, `VALUE_OUT_OF_RANGE`, `INVALID_PRECISION`, `NEGATIVE_UNCERTAINTY`, `VALUE_MUST_BE_POSITIVE` (length). |
| **Stage-2 errors** (Job `error`) | `UNSUPPORTED_UNIT` (details: unit, supported_units), `INCOMPATIBLE_DIMENSIONS` (details: dimensions + alternatives), `BELOW_ABSOLUTE_ZERO`, `UNSUPPORTED_UNIT_PAIR`, `CONVERSION_FACTOR_UNAVAILABLE`. All `retryable = false`. |
| **External calls** | None. Execution time: milliseconds. |

Example — scenario 3: `{value: 12.345, from_unit: "km", to_unit: "mi", precision: 3, engineer_id: "ENG-007"}` ->
`raw_value 7.670827368169888`, `value 7.671`, `conversion {id: "km->mi", version: "1", kind: "factor", factor: "0.621371192237334"}`.

### 4.2 `get_weather` -> WeatherTool (version `get_weather/1`)

Covers requirements scenarios 2 and 5.

| | |
|---|---|
| **Params** | `city` string (required); `country` ISO 3166-1 alpha-2, optional; `units` `metric` \| `imperial`, default `metric`. |
| **Dependencies (ports)** | `WeatherProvider.resolve_city(city, country) -> list[Location]`, `WeatherProvider.current(locat-on, units) -> WeatherData`; both raise `WeatherError(code, retryable, details)`. `WeatherCache.get/put(key)`, key = resolved location + units, TTL 10 min. |
| **Algorithm** | Resolve city (0 -> `CITY_NOT_FOUND`; > 1 and no `country` -> `AMBIGUOUS_CITY` with candidates; > 1 with `country` -> the provider's first candidate, shown in `city_name`/`lat`/`lon` of the result) -> fresh cache entry? return it with `from_cache = true` -> otherwise call provider -> validate ranges (humidity 0–100 %, pressure > 0, temperature −100…+70 °C equivalent, `observed_at` present) -> put into cache -> return. Only validated successful data is cached; errors never are. No stale fallback in v1. |
| **Cache rules** | TTL 10 min counted from `cached_at` (not from `observed_at`; the result shows both). `put` overwrites the entry for its key, so there is never more than one entry per key. Two parallel cache misses for the same key may both call the provider — accepted cost. |
| **Returns (`WeatherResult`)** | temperature, humidity, pressure (hPa / inHg), wind speed or `null` with `wind_speed_available = false`, `observed_at`, location, `from_cache`, `cached_at`, `attribution`. |
| **Stage-1 errors** (`422`) | `FIELD_REQUIRED`, `FIELD_TYPE`, `UNKNOWN_FIELD`, `INVALID_UNITS`, `INVALID_COUNTRY_CODE`. |
| **Stage-2 errors** (Job `error`) | `CITY_NOT_FOUND`, `AMBIGUOUS_CITY`, `RATE_LIMITED` (retryable, `retry_after_s`), `SERVICE_CONFIGURATION_ERROR` (provider 401; logged as configuration error), `WEATHER_SERVICE_UNAVAILABLE` (retryable; timeout, connection error, 5xx), `MALFORMED_RESPONSE` (missing/renamed field, not JSON, body > 1 MiB), `INVALID_DATA` (value out of plausible range). |

**OpenWeatherMapAdapter** (implements `WeatherProvider`; the only place that knows OpenWeatherMap):

| Provider situation | Adapter behaviour | Our error |
|---|---|---|
| Connect does not succeed in 3 s, connection refused, HTTP 502/503/504 | Retry **once** after 0.5 s (GET is safe to repeat) | after 2nd failure: `WEATHER_SERVICE_UNAVAILABLE`, `details.cause`, `attempts: 2` |
| No response within read timeout 10 s | **No retry** (keeps worst case ≈ 17 s) | `WEATHER_SERVICE_UNAVAILABLE`, `cause: read_timeout` |
| HTTP 500 | Retry once (as above) | `WEATHER_SERVICE_UNAVAILABLE`, `cause: http_5xx` |
| HTTP 404 | - | `CITY_NOT_FOUND` |
| HTTP 401 | - | `SERVICE_CONFIGURATION_ERROR` |
| HTTP 429 | No retry; read `Retry-After` if present | `RATE_LIMITED` |
| Body not JSON, required field missing or renamed, body > 1 MiB | - | `MALFORMED_RESPONSE`, `details.field` |
| Any other status | - | `WEATHER_SERVICE_UNAVAILABLE`, `cause: unexpected_status` |

**Total budget.** City resolution and the weather request together must fit into `ToolContext.deadline_s = 17 s`.
Each call uses `min(its timeout, remaining budget)`; a retry is skipped when the remaining budget is too small. When
the budget is used up: `WEATHER_SERVICE_UNAVAILABLE`, `cause: deadline_exceeded`.

API key and base URL come from environment variables (`OWM_API_KEY`, `OWM_BASE_URL`); the key is never logged.
Every call is logged with correlation id, endpoint (without key), attempt, status / timeout type, elapsed ms.
For tests the adapter is replaced by a fake `WeatherProvider`; the adapter itself is tested against a local fake
HTTP server.

### 4.3 `transform_text` — TextTransformTool (version `transform_text/1`)

Covers requirements scenario 4.

| | |
|---|---|
| **Params** | `text` (required, ≤ 10 000 chars); `profile` from a fixed list, v1: `title-basic-v1` (default); `author_id`, `document_id` (required). |
| **Profile `title-basic-v1`** | Split on whitespace, keep whitespace as is; in each token make the first letter upper case and the rest lower case. No small-word exceptions (so `"the lazy dog"` → `"The Lazy Dog"`). Supported characters: printable Unicode letters, digits, punctuation, spaces; control characters are not supported. |
| **Returns (`TextResult`)** | `text`, `profile`, `profile_version`, `author_id`, `document_id`, `transformed_at`. |
| **Stage-1 errors** (`422`) | `FIELD_REQUIRED`, `FIELD_TYPE`, `UNKNOWN_FIELD`, `TEXT_EMPTY`, `TEXT_TOO_LONG`, `PROFILE_NOT_FOUND`, `UNSUPPORTED_CHARACTERS` (details: positions). |
| **Stage-2 errors** | None expected (pure function); an unexpected exception → `TOOL_INTERNAL_ERROR`. |
| **External calls** | None. |