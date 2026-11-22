"""`convert_unit` — UnitConverterTool, version `convert_unit/1` (tool-contract.md, section 4.1).

Requirements: scenarios 1 (°C -> °F with uncertainty), 3 (km -> mi), 6 (incompatible dimensions).

Stage 1 (`validate`, -> 422, no Job): types, unknown fields, finite value, |value| <= 1e12,
    precision 0–6, uncertainty >= 0; for LENGTH conversions value > 0 and engineer_id required.
Stage 2 (`execute`, -> Job error, kept in history): UNSUPPORTED_UNIT, INCOMPATIBLE_DIMENSIONS,
    BELOW_ABSOLUTE_ZERO, CONVERSION_FACTOR_UNAVAILABLE.

Arithmetic is exact (`Fraction`); rounding is half-up, ties away from zero (25.005 -> 25.01, -25.005 -> -25.01).
"""

from __future__ import annotations

import math
import uuid
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Any, Callable, Mapping

from jobservice import codes
from jobservice.application.tool import ToolContext, ToolError, ToolResult
from jobservice.tools._params import ParamReader
from jobservice.tools.units import DIMENSION_HINTS, LENGTH, TEMPERATURE, Unit, UnitRegistry

MAX_ABS_VALUE = 1e12
DEFAULT_PRECISION = 3
MAX_PRECISION = 6
_ALLOWED = ("value", "from_unit", "to_unit", "precision", "uncertainty", "experiment_id", "engineer_id")

_FORMULAS = {
    ("C", "F"): "F = C × 9/5 + 32",
    ("F", "C"): "C = (F − 32) × 5/9",
    ("C", "K"): "K = C + 273.15",
    ("K", "C"): "C = K − 273.15",
    ("F", "K"): "K = (F + 459.67) × 5/9",
    ("K", "F"): "F = K × 9/5 − 459.67",
}


def round_half_up(x: Fraction, places: int) -> Decimal:
    """Exact half-up rounding (ties away from zero) of a rational number to `places` decimals."""
    n = math.floor(abs(x) * 10**places + Fraction(1, 2))
    with localcontext() as ctx:
        ctx.prec = 60
        d = Decimal(n).scaleb(-places)
        return -d if (x < 0 and n != 0) else d


def _to_fraction(value: int | float) -> Fraction:
    # str() keeps the number as the client wrote it: Fraction("12.345"), not the binary 12.34499999...
    return Fraction(value) if isinstance(value, int) else Fraction(str(value))


def _significant(x: Fraction, digits: int = 15) -> str:
    with localcontext() as ctx:
        ctx.prec = digits
        d = Decimal(x.numerator) / Decimal(x.denominator)
    return format(d.normalize(), "f")


class UnitConverterTool:
    name = "convert_unit"
    version = "convert_unit/1"

    def __init__(self, units: UnitRegistry | None = None, new_id: Callable[[], str] | None = None) -> None:
        self._units = units or UnitRegistry()
        self._new_id = new_id or (lambda: str(uuid.uuid4()))

    # ---- Stage 1 --------------------------------------------------------------------------------------
    def validate(self, params: Mapping[str, Any]) -> Mapping[str, Any]:
        r = ParamReader(params, _ALLOWED)

        value = r.number("value", required=True)
        if value is not None and abs(value) > MAX_ABS_VALUE:
            r.fail("value", codes.VALUE_OUT_OF_RANGE, "Absolute value must not exceed 1e12.", value)
            value = None

        from_raw = r.string("from_unit", required=True, max_len=32)
        to_raw = r.string("to_unit", required=True, max_len=32)

        precision = r.integer("precision", required=False)
        if precision is not None and not 0 <= precision <= MAX_PRECISION:
            r.fail("precision", codes.INVALID_PRECISION, "Precision must be between 0 and 6.", precision)
        if precision is None and not r.has_error("precision"):
            precision = DEFAULT_PRECISION

        uncertainty = r.number("uncertainty", required=False)
        if uncertainty is not None and uncertainty < 0:
            r.fail("uncertainty", codes.NEGATIVE_UNCERTAINTY, "Uncertainty must be non-negative.", uncertainty)

        experiment_id = r.string("experiment_id", required=False, max_len=64)
        engineer_id = r.string("engineer_id", required=False, max_len=64)

        # Dimension-dependent form rules. An unknown unit is NOT a Stage-1 error: it is a Stage-2
        # error (UNSUPPORTED_UNIT) so that the researcher sees it in history.
        src = self._units.resolve(from_raw) if from_raw else None
        dst = self._units.resolve(to_raw) if to_raw else None
        dims = {u.dimension for u in (src, dst) if u is not None}
        if LENGTH in dims:
            if value is not None and value <= 0:
                r.fail("value", codes.VALUE_MUST_BE_POSITIVE, "Length must be positive.", value)
            if engineer_id is None and not r.has_error("engineer_id"):
                r.fail("engineer_id", codes.FIELD_REQUIRED, "engineer_id is required for length conversions.", None)

        r.raise_if_errors()

        if TEMPERATURE in dims and experiment_id is None:
            experiment_id = f"EXP-{self._new_id()}"  # requirements, scenario 1: generate a missing id

        assert value is not None and from_raw is not None and to_raw is not None and precision is not None
        normalized: dict[str, Any] = {
            "value": value,
            "from_unit": src.id if src else from_raw.strip(),
            "to_unit": dst.id if dst else to_raw.strip(),
            "precision": precision,
        }
        if uncertainty is not None:
            normalized["uncertainty"] = uncertainty
        if experiment_id is not None:
            normalized["experiment_id"] = experiment_id
        if engineer_id is not None:
            normalized["engineer_id"] = engineer_id
        return normalized

    # ---- Stage 2 --------------------------------------------------------------------------------------
    def execute(self, params: Mapping[str, Any], ctx: ToolContext) -> ToolResult:
        src = self._units.resolve(params["from_unit"])
        dst = self._units.resolve(params["to_unit"])
        for raw, unit in ((params["from_unit"], src), (params["to_unit"], dst)):
            if unit is None:
                return ToolResult.failure(
                    ToolError(
                        codes.UNSUPPORTED_UNIT,
                        f"Unit '{raw}' is not supported.",
                        {"unit": raw, "supported_units": self._units.ids()},
                    )
                )
        assert src is not None and dst is not None

        if src.dimension != dst.dimension:
            return ToolResult.failure(self._incompatible(src, dst))

        if src.scale is None or dst.scale is None or not self._units.version:
            return ToolResult.failure(
                ToolError(
                    codes.CONVERSION_FACTOR_UNAVAILABLE,
                    f"No conversion factor is available for {src.id} -> {dst.id}.",
                    {"from_unit": src.id, "to_unit": dst.id},
                )
            )

        x = _to_fraction(params["value"])
        base = x * src.scale + src.offset
        if src.dimension == TEMPERATURE and base < 0:
            return ToolResult.failure(
                ToolError(
                    codes.BELOW_ABSOLUTE_ZERO,
                    "Value is below absolute zero.",
                    {"value": params["value"], "unit": src.id, "kelvin": float(base)},
                )
            )

        precision: int = params["precision"]
        raw = (base - dst.offset) / dst.scale
        rounded = round_half_up(raw, precision)

        uncertainty = params.get("uncertainty")
        u_rounded: Decimal | None = None
        if uncertainty is not None:
            # Only the scale part of the map applies to an uncertainty: ±0.1 °C -> ±0.18 °F.
            u_rounded = round_half_up(_to_fraction(uncertainty) * src.scale / dst.scale, precision)

        display = f"{rounded}" + (f" ± {u_rounded}" if u_rounded is not None else "") + f" {dst.symbol}"
        return ToolResult.success(
            {
                "value": float(rounded),
                "raw_value": float(raw),
                "unit": dst.id,
                "uncertainty": float(u_rounded) if u_rounded is not None else None,
                "uncertainty_supplied": uncertainty is not None,
                "precision": precision,
                "rounding_rule": "half-up",
                "display": display,
                "source": {"value": params["value"], "unit": src.id},
                "conversion": self._conversion(src, dst),
                "experiment_id": params.get("experiment_id"),
                "engineer_id": params.get("engineer_id"),
            }
        )

    # ---- helpers ----------------------------------------------------------------------------------------
    def _incompatible(self, src: Unit, dst: Unit) -> ToolError:
        message = (
            f"Cannot convert {src.name} to {dst.name} — {src.dimension} vs {dst.dimension}. "
            f"Use {DIMENSION_HINTS[src.dimension]} for {src.dimension} "
            f"or {DIMENSION_HINTS[dst.dimension]} for {dst.dimension}."
        )
        return ToolError(
            codes.INCOMPATIBLE_DIMENSIONS,
            message,
            {
                "source_dimension": src.dimension,
                "target_dimension": dst.dimension,
                "alternatives_for_source": self._units.of_dimension(src.dimension),
                "alternatives_for_target": self._units.of_dimension(dst.dimension),
            },
        )

    def _conversion(self, src: Unit, dst: Unit) -> dict[str, Any]:
        assert src.scale is not None and dst.scale is not None
        is_formula = src.offset != 0 or dst.offset != 0
        if is_formula:
            factor = None
            expression = _FORMULAS.get((src.id, dst.id), f"{dst.id} = {src.id}")
        else:
            factor = _significant(src.scale / dst.scale)
            expression = f"{dst.id} = {src.id} × {factor}"
        return {
            "id": f"{src.id}->{dst.id}",
            "version": self._units.version,
            "kind": "formula" if is_formula else "factor",
            "factor": factor,
            "expression": expression,
        }
