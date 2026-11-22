"""Unit registry for `convert_unit` (tool-contract.md, section 4.1).

Every unit is defined by an exact linear map to the base unit of its dimension:
    base = value * scale + offset
Base units: length -> metre, mass -> kilogram, temperature -> kelvin.
Exact rational numbers (`Fraction`) are used, so 1 mi = 1609.344 m and 1 K = 1 °C are exact.
Only the units named in requirements.md (scenarios 1, 3, 6) are registered — no scope increase.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable

LENGTH = "length"
MASS = "mass"
TEMPERATURE = "temperature"


@dataclass(frozen=True)
class Unit:
    id: str  # canonical id saved in history, e.g. "F", "km"
    name: str  # used in messages, e.g. "meter"
    symbol: str  # used in `display`, e.g. "°F"
    dimension: str
    scale: Fraction | None  # None = factor unknown -> CONVERSION_FACTOR_UNAVAILABLE
    offset: Fraction = Fraction(0)
    aliases: tuple[str, ...] = ()


def _f(text: str) -> Fraction:
    return Fraction(text)


DEFAULT_UNITS: tuple[Unit, ...] = (
    # temperature (kelvin = value * scale + offset)
    Unit("C", "celsius", "°C", TEMPERATURE, _f("1"), _f("273.15"), ("°c", "degc", "celsius", "℃")),
    Unit(
        "F",
        "fahrenheit",
        "°F",
        TEMPERATURE,
        Fraction(5, 9),
        _f("459.67") * Fraction(5, 9),
        ("°f", "degf", "fahrenheit", "℉"),
    ),
    Unit("K", "kelvin", "K", TEMPERATURE, _f("1"), _f("0"), ("kelvin", "kelvins")),
    # length (metre)
    Unit("mm", "millimeter", "mm", LENGTH, _f("0.001"), aliases=("millimeter", "millimeters", "millimetre", "millimetres")),
    Unit("cm", "centimeter", "cm", LENGTH, _f("0.01"), aliases=("centimeter", "centimeters", "centimetre", "centimetres")),
    Unit("m", "meter", "m", LENGTH, _f("1"), aliases=("meter", "meters", "metre", "metres")),
    Unit("km", "kilometer", "km", LENGTH, _f("1000"), aliases=("kilometer", "kilometers", "kilometre", "kilometres")),
    Unit("in", "inch", "in", LENGTH, _f("0.0254"), aliases=("inch", "inches")),
    Unit("ft", "foot", "ft", LENGTH, _f("0.3048"), aliases=("foot", "feet")),
    Unit("yd", "yard", "yd", LENGTH, _f("0.9144"), aliases=("yard", "yards")),
    Unit("mi", "mile", "mi", LENGTH, _f("1609.344"), aliases=("mile", "miles")),
    # mass (kilogram) — named in scenario 6
    Unit("mg", "milligram", "mg", MASS, _f("0.000001"), aliases=("milligram", "milligrams")),
    Unit("g", "gram", "g", MASS, _f("0.001"), aliases=("gram", "grams")),
    Unit("kg", "kilogram", "kg", MASS, _f("1"), aliases=("kilogram", "kilograms")),
    Unit("t", "tonne", "t", MASS, _f("1000"), aliases=("tonne", "tonnes")),
    Unit("lb", "pound", "lb", MASS, _f("0.45359237"), aliases=("pound", "pounds", "lbs")),
    Unit("oz", "ounce", "oz", MASS, _f("0.45359237") / 16, aliases=("ounce", "ounces")),
)

# Two short suggestions per dimension, used in the INCOMPATIBLE_DIMENSIONS message (requirements, scenario 6).
DIMENSION_HINTS = {LENGTH: "cm/ft", MASS: "g/lb", TEMPERATURE: "C/F"}


def _normalise(text: str) -> str:
    text = text.replace("˚", "°")  # ring above (˚) looks like a degree sign
    return "".join(text.split()).casefold()  # "° F" -> "°f", "KM" -> "km"


class UnitRegistry:
    def __init__(self, units: Iterable[Unit] = DEFAULT_UNITS, version: str = "1") -> None:
        self.version = version
        self._units: dict[str, Unit] = {}
        self._lookup: dict[str, Unit] = {}
        for unit in units:
            if unit.id in self._units:
                raise ValueError(f"duplicate unit id {unit.id}")
            self._units[unit.id] = unit
            for alias in (unit.id, *unit.aliases):
                key = _normalise(alias)
                other = self._lookup.get(key)
                if other is not None and other.id != unit.id:
                    raise ValueError(f"alias '{alias}' is used by {other.id} and {unit.id}")
                self._lookup[key] = unit

    def resolve(self, text: str) -> Unit | None:
        if not isinstance(text, str):
            return None
        return self._lookup.get(_normalise(text))

    def ids(self) -> list[str]:
        return list(self._units)

    def of_dimension(self, dimension: str) -> list[str]:
        return [u.id for u in self._units.values() if u.dimension == dimension]
