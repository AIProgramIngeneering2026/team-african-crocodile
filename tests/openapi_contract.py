"""docs/api/openapi.yaml as an executable check (lecture 104: "контракт — единственный источник правды").

`OpenApi.check(...)` is called for EVERY response in the API tests (see tests/api_client.py):
  * the status code is documented for that operation;
  * the body validates against the documented JSON Schema (OpenAPI 3.1 = JSON Schema 2020-12);
  * every documented response header is present.
So a test that only looks at the status still fails when the body drifts away from the contract.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

OPENAPI_PATH = Path(__file__).resolve().parents[1] / "docs" / "api" / "openapi.yaml"
_BASE = "urn:jobservice:openapi"


def _pointer(*parts: str) -> str:
    return "#/" + "/".join(p.replace("~", "~0").replace("/", "~1") for p in parts)


class OpenApi:
    def __init__(self, path: Path = OPENAPI_PATH) -> None:
        self.doc: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        resource = Resource.from_contents(self.doc, default_specification=DRAFT202012)
        self._registry = Registry().with_resource(_BASE, resource)

    # ---- lookup -----------------------------------------------------------------------------------
    def operations(self) -> set[tuple[str, str]]:
        return {
            (method.upper(), path)
            for path, item in self.doc["paths"].items()
            for method in item
            if method in {"get", "post", "put", "patch", "delete", "head", "options"}
        }

    def documented_statuses(self, method: str, template: str) -> set[int]:
        return {int(s) for s in self.doc["paths"][template][method.lower()]["responses"]}

    def _response(self, method: str, template: str, status: int) -> tuple[dict[str, Any], list[str]]:
        location = ["paths", template, method.lower(), "responses", str(status)]
        response = self.doc["paths"][template][method.lower()]["responses"][str(status)]
        if "$ref" in response:  # e.g. #/components/responses/InternalError
            location = response["$ref"].lstrip("#/").split("/")
            response = self.doc
            for part in location:
                response = response[part]
        return response, location

    def validator(self, pointer: str) -> Draft202012Validator:
        return Draft202012Validator({"$ref": _BASE + pointer}, registry=self._registry,
                                    format_checker=FormatChecker())

    def schema_validator(self, name: str) -> Draft202012Validator:
        return self.validator(_pointer("components", "schemas", name))

    # ---- the check --------------------------------------------------------------------------------
    def check(self, method: str, template: str | None, status: int, headers: Mapping[str, str], body: Any) -> None:
        """Raise AssertionError if the response is not what the contract promises."""
        if template is None:  # unknown endpoint / method: only the shared error format applies
            errors = list(self.schema_validator("ErrorResponse").iter_errors(body))
            assert not errors, f"{method} -> {status}: body is not ErrorResponse: {errors[0].message}"
            return
        documented = self.documented_statuses(method, template)
        assert status in documented, f"{method} {template} answered {status}, documented: {sorted(documented)}"
        response, location = self._response(method, template, status)
        media = response.get("content", {}).get("application/json")
        assert media is not None, f"{method} {template} {status}: no JSON body documented"
        pointer = _pointer(*location, "content", "application/json", "schema")
        errors = sorted(self.validator(pointer).iter_errors(body), key=lambda e: list(e.absolute_path))
        assert not errors, (
            f"{method} {template} {status}: body breaks the contract at "
            f"{'/'.join(map(str, errors[0].absolute_path)) or '<root>'}: {errors[0].message}"
        )
        lower = {k.lower(): v for k, v in headers.items()}
        for name, spec in response.get("headers", {}).items():
            if name.lower() == "retry-after":
                continue  # optional hint
            assert name.lower() in lower, f"{method} {template} {status}: documented header {name} is missing"
            enum = spec.get("schema", {}).get("enum")
            if enum:
                assert lower[name.lower()] in enum, f"header {name}={lower[name.lower()]!r} not in {enum}"


@lru_cache(maxsize=1)
def openapi() -> OpenApi:
    return OpenApi()
