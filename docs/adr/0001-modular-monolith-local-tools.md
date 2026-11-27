# ADR-0001: One process (modular monolith) with local Tools and an adapter for OpenWeatherMap

- **Date:** 2026-11-14
- **Status:** Accepted (Practice 2); HTTP framework amended by [ADR-0006](0006-sqlite-storage-migrations-and-stdlib-http.md) (standard-library WSGI instead of FastAPI)
- **Deciders:** БалчаНМ, ТегеньСБ

## Context and constraints

- Team of 2 people, one semester, course checkpoints every week.
- Three Tools: `convert_unit` and `transform_text` are pure local computations (milliseconds);
  `get_weather` calls one external HTTP service (OpenWeatherMap).
- Required by the project: Tools behind one contract, new Tool without changing the Dispatcher, storage with
  migrations, one-command start (`docker compose up`), an LLM Tool in the second semester.
- No requirement for independent releases or independent scaling of any Tool.

## Decision

Build **one application process** (Python, FastAPI) with internal module boundaries:
`api` → `application` (Dispatcher, Registry, ports) → `domain` (Job); `tools`; `infrastructure`
(SQL repository, OpenWeatherMap adapter). All Tools run **inside** the process and are registered in the Registry
at startup. OpenWeatherMap is reached only through `OpenWeatherMapAdapter`, which implements the `WeatherProvider`
port. The database runs as a separate container (SQLite during prototyping, PostgreSQL from Practice 7).

## Alternatives considered

| Alternative | Why not now |
|---|---|
| A separate service per Tool (microservices) | Network calls, versioning, deployment and tracing for 3 small Tools and 2 people. No requirement asks for independent release or scaling. |
| Separate worker process + queue for Tools | Needed only for long jobs; all our Tools finish in ≤ 17 s (see ADR-0002). |
| WeatherTool calls OpenWeatherMap directly (no adapter) | Provider field names and status codes would leak into the Tool, the history and the tests; a renamed provider field would touch several modules (lecture 103, "Чужой язык внутри системы"). |

## Consequences and cost

- **+** Simple to run, debug and test; one deployment; Tool calls are plain method calls.
- **+** Provider changes are local to the adapter; the WeatherTool is tested with a fake provider.
- **−** Common release: a change to any Tool redeploys the whole service.
- **−** Common resources: a slow weather request occupies a worker of the same process.
- **−** Boundaries are kept only by discipline (imports are checked in review); nothing physically prevents a
  module from importing another one's internals.

## Revisit when

- A Tool needs minutes of execution, a GPU, or its own scaling (likely the LLM Tool in semester 2);
- a Tool must be released independently or is owned by another team;
- the weather calls start to slow down local Tools noticeably.

Revisiting may move **one** Tool out of the process while the rest stays as it is.
