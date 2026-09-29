"""Length parsing and formatting. Model units are inches."""
from __future__ import annotations

import re
from fractions import Fraction

M_PER_IN = 0.0254

_METRIC = re.compile(r"^([+-]?\d+(?:[.,]\d+)?)\s*(mm|cm|m)$", re.I)
_IMPERIAL = re.compile(
    r"""^(?:(?P<ft>\d+(?:\.\d+)?)\s*'\s*-?\s*)?
        (?:(?P<in>\d+(?:\.\d+)?)(?:\s*-?\s*(?P<n>\d+)/(?P<d>\d+))?
          |(?P<n2>\d+)/(?P<d2>\d+))?
        \s*"?$""",
    re.X,
)
_METRIC_TO_IN = {"mm": 1 / 25.4, "cm": 1 / 2.54, "m": 1 / M_PER_IN}


def parse_length(v: int | float | str) -> float:
    """Return inches for a number (inches) or a unit string; ValueError otherwise."""
    if isinstance(v, bool):
        raise ValueError(f"not a length: {v!r}")
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        raise ValueError(f"not a length: {v!r}")
    s = v.strip()
    m = _METRIC.match(s)
    if m:
        return float(m.group(1).replace(",", ".")) * _METRIC_TO_IN[m.group(2).lower()]
    m = _IMPERIAL.match(s)
    if not s or not m or not any(m.group(k) for k in ("ft", "in", "n2")):
        raise ValueError(f"not a length: {v!r}")
    total = float(m.group("ft") or 0) * 12 + float(m.group("in") or 0)
    n, d = m.group("n") or m.group("n2"), m.group("d") or m.group("d2")
    if n:
        if int(d) == 0:
            raise ValueError(f"zero denominator: {v!r}")
        total += int(n) / int(d)
    return total


def fmt_ftin(inches: float, prec: float = 0.25) -> str:
    """Architectural feet-inches, e.g. 5'-6 1/2"."""
    denom = round(1 / prec)
    steps = round(abs(inches) * denom)
    feet, rem = divmod(steps, 12 * denom)
    whole, fs = divmod(rem, denom)
    frac = Fraction(fs, denom)
    fr = f" {frac.numerator}/{frac.denominator}" if frac else ""
    return f"{'-' if inches < 0 and steps else ''}{feet}'-{whole}{fr}\""


def _num(x: float, lang: str, nd: int) -> str:
    s = f"{x:.{nd}f}"
    return s.replace(".", ",") if lang == "fr" else s


def fmt_m(inches: float, lang: str = "en", nd: int = 2) -> str:
    """Metres without unit suffix; decimal comma for fr."""
    return _num(inches * M_PER_IN, lang, nd)


def fmt_area_m2(sq_in: float, lang: str = "en", nd: int = 1) -> str:
    """Square metres without unit suffix."""
    return _num(sq_in * M_PER_IN**2, lang, nd)


def fmt_area_ft2(sq_in: float, nd: int = 0) -> str:
    """Square feet without unit suffix."""
    return f"{sq_in / 144:.{nd}f}"
