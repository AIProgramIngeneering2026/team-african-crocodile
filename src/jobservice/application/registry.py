"""Registry: operation name -> Tool (Registry pattern, lecture 103).

Filled once in the composition root (`jobservice.bootstrap`). Registration rules are checked at startup:
a non-empty unique name and the two contract methods. The Dispatcher only calls `get` and `names`.
"""

from __future__ import annotations

from jobservice.application.errors import DuplicateTool
from jobservice.application.tool import Tool


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        name = getattr(tool, "name", None)
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Tool {tool!r} must have a non-empty string 'name'")
        version = getattr(tool, "version", None)
        if not isinstance(version, str) or not version:
            raise ValueError(f"Tool '{name}' must have a non-empty string 'version'")
        for method in ("validate", "execute"):
            if not callable(getattr(tool, method, None)):
                raise ValueError(f"Tool '{name}' must implement {method}()")
        if name in self._tools:
            raise DuplicateTool(f"Operation '{name}' is already registered")
        self._tools[name] = tool

    def get(self, name: str) -> Tool | None:
        if not isinstance(name, str):
            return None
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
