"""convert_unit — requirements scenarios 1, 3, 6 and the two validation stages."""

from __future__ import annotations

from fractions import Fraction

import pytest

from jobservice import codes
from jobservice.application import ParamsInvalid, ToolContext
from jobservice.domain import JobStatus
from jobservice.tools import UnitConverterTool
from jobservice.tools.unit_converter import round_half_up
from jobservice.tools.units import DEFAULT_UNITS, Unit, UnitRegistry

CTX = ToolContext(correlation_id="t", deadline_s=1)


def tool() -> UnitConverterTool:
    return UnitConverterTool(new_id=lambda: "generated")


def run(params):
    t = tool()
    return t.execute(t.validate(params), CTX)


def field_codes(exc: ParamsInvalid) -> dict[str, str]:
    return {e.field: e.code for e in exc.errors}


# ---- scenario 1: 25 °C -> °F with uncertainty ------------------------------------------------------
def test_scenario_1_celsius_to_fahrenheit_with_uncertainty(real_dispatcher):
    job = real_dispatcher.submit(
        "convert_unit",
        {"value": 25, "from_unit": "°C", "to_unit": "fahrenheit", "precision": 2, "uncertainty": 0.1,
         "experiment_id": "EXP-2026-041"},
        idempotency_key="s1",
    ).job
    assert job.status is JobStatus.DONE
    r = job.result
    assert r["display"] == "77.00 ± 0.18 °F"
    assert (r["value"], r["uncertainty"], r["unit"], r["uncertainty_supplied"]) == (77.0, 0.18, "F", True)
    assert r["experiment_id"] == "EXP-2026-041"
    assert r["conversion"] == {"id": "C->F", "version": "1", "kind": "formula", "factor": None,
                               "expression": "F = C × 9/5 + 32"}
    assert job.params["from_unit"] == "C" and job.params["to_unit"] == "F"  # canonical ids in history


def test_missing_experiment_id_is_generated_for_temperature():
    r = run({"value": 25, "from_unit": "C", "to_unit": "F"}).data
    assert r["experiment_id"] == "EXP-generated"
    assert r["uncertainty"] is None and r["uncertainty_supplied"] is False


@pytest.mark.parametrize("alias", ["F", "f", "°F", "˚F", "° F", "degF", "Fahrenheit", "℉"])
def test_fahrenheit_aliases(alias):
    assert run({"value": 0, "from_unit": "C", "to_unit": alias}).data["value"] == 32.0


@pytest.mark.parametrize(
    ("value", "src", "dst", "expected"),
    [(100, "C", "F", 212.0), (-40, "C", "F", -40.0), (0, "C", "K", 273.15), (77, "F", "C", 25.0),
     (0, "K", "C", -273.15), (-273.15, "C", "K", 0.0)],
)
def test_temperature_formulas(value, src, dst, expected):
    assert run({"value": value, "from_unit": src, "to_unit": dst, "precision": 2}).data["value"] == expected


def test_below_absolute_zero_is_a_job_error_kept_in_history(real_dispatcher, repo):
    job = real_dispatcher.submit("convert_unit", {"value": -300, "from_unit": "C", "to_unit": "F"},
                                 idempotency_key="az").job
    assert job.status is JobStatus.ERROR and job.error.code == codes.BELOW_ABSOLUTE_ZERO
    assert repo.get(job.id) is not None


def test_negative_kelvin_is_below_absolute_zero():
    assert run({"value": -1, "from_unit": "K", "to_unit": "C"}).error.code == codes.BELOW_ABSOLUTE_ZERO


def test_unsupported_unit_is_a_job_error_listing_supported_units(real_dispatcher):
    job = real_dispatcher.submit("convert_unit", {"value": 1, "from_unit": "C", "to_unit": "parsec"},
                                 idempotency_key="u").job
    assert job.status is JobStatus.ERROR and job.error.code == codes.UNSUPPORTED_UNIT
    assert job.error.details["unit"] == "parsec" and "F" in job.error.details["supported_units"]


# ---- scenario 3: km -> mi ----------------------------------------------------------------------------
def test_scenario_3_kilometres_to_miles(real_dispatcher):
    job = real_dispatcher.submit(
        "convert_unit",
        {"value": 12.345, "from_unit": "km", "to_unit": "mi", "precision": 3, "engineer_id": "ENG-007"},
        idempotency_key="s3",
    ).job
    r = job.result
    assert r["value"] == 7.671 and r["display"] == "7.671 mi"
    assert r["raw_value"] == pytest.approx(7.670827368169888, rel=1e-15)
    assert r["conversion"]["factor"] == "0.621371192237334"
    assert r["conversion"]["kind"] == "factor" and r["conversion"]["version"] == "1"
    assert r["engineer_id"] == "ENG-007" and r["rounding_rule"] == "half-up"


def test_default_precision_is_3():
    r = run({"value": 1, "from_unit": "mi", "to_unit": "km", "engineer_id": "E"}).data
    assert r["precision"] == 3 and r["display"] == "1.609 km"


@pytest.mark.parametrize("value", [0, -5])
def test_length_must_be_positive(value):
    with pytest.raises(ParamsInvalid) as info:
        tool().validate({"value": value, "from_unit": "km", "to_unit": "mi", "engineer_id": "E"})
    assert field_codes(info.value) == {"params.value": codes.VALUE_MUST_BE_POSITIVE}


def test_length_needs_engineer_id():
    with pytest.raises(ParamsInvalid) as info:
        tool().validate({"value": 1, "from_unit": "km", "to_unit": "mi"})
    assert field_codes(info.value) == {"params.engineer_id": codes.FIELD_REQUIRED}


# ---- scenario 6: incompatible dimensions -------------------------------------------------------------
def test_scenario_6_metre_to_kilogram(real_dispatcher, repo):
    job = real_dispatcher.submit(
        "convert_unit", {"value": 12.5, "from_unit": "meter", "to_unit": "kilogram", "engineer_id": "ENG-007"},
        idempotency_key="s6",
    ).job
    assert job.status is JobStatus.ERROR and job.result is None
    assert job.error.code == codes.INCOMPATIBLE_DIMENSIONS
    assert job.error.message == (
        "Cannot convert meter to kilogram — length vs mass. Use cm/ft for length or g/lb for mass."
    )
    assert job.error.details["alternatives_for_source"] == ["mm", "cm", "m", "km", "in", "ft", "yd", "mi"]
    assert job.error.details["alternatives_for_target"] == ["mg", "g", "kg", "t", "lb", "oz"]
    stored = repo.get(job.id)  # kept in history with the engineer id
    assert stored.params["engineer_id"] == "ENG-007" and stored.params["value"] == 12.5


# ---- stage 1: wrong parameters, every field named ----------------------------------------------------
def test_all_wrong_fields_are_reported_at_once():
    with pytest.raises(ParamsInvalid) as info:
        tool().validate({"from_unit": "C", "to_unit": "F", "precision": 9, "uncertainty": -0.1, "colour": "red"})
    assert field_codes(info.value) == {
        "params.value": codes.FIELD_REQUIRED,
        "params.precision": codes.INVALID_PRECISION,
        "params.uncertainty": codes.NEGATIVE_UNCERTAINTY,
        "params.colour": codes.UNKNOWN_FIELD,
    }


@pytest.mark.parametrize(
    ("params", "field", "code"),
    [
        ({"value": "25"}, "params.value", codes.FIELD_TYPE),
        ({"value": True}, "params.value", codes.FIELD_TYPE),
        ({"value": float("nan")}, "params.value", codes.VALUE_NOT_FINITE),
        ({"value": float("inf")}, "params.value", codes.VALUE_NOT_FINITE),
        ({"value": 1e13}, "params.value", codes.VALUE_OUT_OF_RANGE),
        ({"precision": -1}, "params.precision", codes.INVALID_PRECISION),
        ({"precision": 2.5}, "params.precision", codes.FIELD_TYPE),
        ({"from_unit": 5}, "params.from_unit", codes.FIELD_TYPE),
        ({"from_unit": "  "}, "params.from_unit", codes.FIELD_REQUIRED),
        ({"to_unit": None}, "params.to_unit", codes.FIELD_REQUIRED),
    ],
)
def test_single_wrong_field(params, field, code):
    base = {"value": 25, "from_unit": "C", "to_unit": "F"}
    with pytest.raises(ParamsInvalid) as info:
        tool().validate({**base, **params})
    assert field_codes(info.value) == {field: code}


def test_invalid_params_through_dispatcher_create_no_job(real_dispatcher, repo):
    with pytest.raises(ParamsInvalid):
        real_dispatcher.submit("convert_unit", {"value": 25, "from_unit": "C", "to_unit": "F", "precision": 9},
                               idempotency_key="bad")
    assert len(repo) == 0


# ---- rounding and factors ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("x", "places", "expected"),
    [("2.5", 0, "3"), ("-2.5", 0, "-3"), ("7.6705", 3, "7.671"), ("-0.0004", 3, "0.000"), ("1", 2, "1.00")],
)
def test_round_half_up_ties_away_from_zero(x, places, expected):
    assert str(round_half_up(Fraction(x), places)) == expected


def test_decimal_input_is_exact_not_binary():
    # 1.005 is 1.00499999... in binary floating point; the user typed 1.005, so half-up gives 1.01
    assert run({"value": 1.005, "from_unit": "m", "to_unit": "m", "precision": 2, "engineer_id": "E"}).data["value"] == 1.01


def test_missing_factor_is_conversion_factor_unavailable():
    units = UnitRegistry([*DEFAULT_UNITS[:-1], Unit("oz", "ounce", "oz", "mass", None)])
    t = UnitConverterTool(units=units)
    result = t.execute(t.validate({"value": 1, "from_unit": "kg", "to_unit": "oz"}), CTX)
    assert result.error.code == codes.CONVERSION_FACTOR_UNAVAILABLE


def test_unit_registry_rejects_conflicting_aliases():
    with pytest.raises(ValueError):
        UnitRegistry([Unit("a", "a", "a", "length", Fraction(1), aliases=("x",)),
                      Unit("b", "b", "b", "length", Fraction(1), aliases=("X",))])
