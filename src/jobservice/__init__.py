"""Job Execution Service (Practice 4: HTTP API and storage over the domain core of Practice 3).

Layers (docs/architecture.md):
    domain          Job and its transition rules; imports nothing from the project except `codes`.
    application     Dispatcher, Registry and the ports (Tool, JobRepository).
    tools           Concrete Tools behind the Tool contract.
    infrastructure  Implementations of the ports: SQLite + migrations (service), in-memory (unit tests).
    api             HTTP layer (WSGI) — maps HTTP to Dispatcher calls and errors to status codes.
    bootstrap       Composition root: the only place that knows every concrete class.

Only `infrastructure` talks to the database and only `api` / `server` know HTTP
(checked by tests/test_core_boundaries.py). No third-party package is needed at run time.
"""

__version__ = "0.4.0"
