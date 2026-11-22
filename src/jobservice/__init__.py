"""Job Execution Service — domain core (Practice 3).

Layers (docs/architecture.md):
    domain          Job and its transition rules; imports nothing from the project except `codes`.
    application     Dispatcher, Registry and the ports (Tool, JobRepository).
    tools           Concrete Tools behind the Tool contract.
    infrastructure  Implementations of the ports (in-memory repository for now).
    bootstrap       Composition root: the only place that knows every concrete class.

No web framework and no database driver is imported anywhere in this package.
"""
