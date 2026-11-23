"""Helper for Stage-1 validation inside Tools: collects EVERY wrong field, then raises once."""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

from jobservice import codes
from jobservice.application.tool import FieldError, ParamsInvalid

_MISSING = object()


def _short(value: Any) -> Any:
    if isinstance(value, str) and len(value) > 100:
        return value[:100]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)  # NaN / Infinity are not valid JSON
    return value


class ParamReader:
    def __init__(self, params: Any, allowed: Iterable[str]) -> None:
        self.errors: list[FieldError] = []
        if not isinstance(params, Mapping):
            self.params: Mapping[str, Any] = {}
            self.fail("params", codes.FIELD_TYPE, "Field 'params' must be an object.", None)
            return
        self.params = params
        allowed_set = set(allowed)
        for key in params:
            if key not in allowed_set:
                self.fail(key, codes.UNKNOWN_FIELD, "Field is not allowed for this operation.", params[key])

    # ---- reporting ------------------------------------------------------------------------------
    def fail(self, name: str, code: str, message: str, value: Any) -> None:
        field = name if name == "params" else f"params.{name}"
        self.errors.append(FieldError(field, code, message, _short(value)))

    def has_error(self, name: str) -> bool:
        return any(e.field == f"params.{name}" for e in self.errors)

    def raise_if_errors(self) -> None:
        if self.errors:
            raise ParamsInvalid(self.errors)

    # ---- typed readers: return the value, or None when missing/invalid (the error is recorded) ----
    def _raw(self, name: str, required: bool) -> Any:
        value = self.params.get(name, _MISSING)
        if value is _MISSING or value is None:
            if required:
                self.fail(name, codes.FIELD_REQUIRED, "Field is required.", None)
            return None
        return value

    def number(self, name: str, *, required: bool) -> int | float | None:
        value = self._raw(name, required)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self.fail(name, codes.FIELD_TYPE, "Field must be a number.", value)
            return None
        if isinstance(value, float) and not math.isfinite(value):
            self.fail(name, codes.VALUE_NOT_FINITE, "Value must be a finite number.", value)
            return None
        return value

    def integer(self, name: str, *, required: bool) -> int | None:
        value = self._raw(name, required)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self.fail(name, codes.FIELD_TYPE, "Field must be an integer.", value)
            return None
        if isinstance(value, float):
            if not (math.isfinite(value) and value.is_integer()):
                self.fail(name, codes.FIELD_TYPE, "Field must be an integer.", value)
                return None
            value = int(value)
        return value

    def string(self, name: str, *, required: bool, max_len: int) -> str | None:
        value = self._raw(name, required)
        if value is None:
            return None
        if not isinstance(value, str):
            self.fail(name, codes.FIELD_TYPE, "Field must be a string.", value)
            return None
        if not value.strip():
            self.fail(name, codes.FIELD_REQUIRED, "Field must not be empty.", value)
            return None
        if len(value) > max_len:
            self.fail(name, codes.VALUE_OUT_OF_RANGE, f"Field must be at most {max_len} characters.", value)
            return None
        return value
