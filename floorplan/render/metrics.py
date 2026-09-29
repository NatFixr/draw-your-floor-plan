"""Text measurement with Pillow on the Noto Sans files Chrome draws with."""
from __future__ import annotations

from functools import lru_cache

from PIL import ImageFont

from .styles import CAP, FONT_FILES

_PX = 1000


@lru_cache(maxsize=None)
def _font(weight: str, style: str) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_FILES[(weight, style)], _PX)


@lru_cache(maxsize=65536)
def text_metrics(s: str, h_mm: float, weight: str = "regular", style: str = "normal"):
    """(advance, left, top, right, bottom) in mm about the left baseline origin; y grows down."""
    if not s:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    f = _font(weight, style)
    k = (h_mm / CAP) / _PX
    l, t, r, b = f.getbbox(s, anchor="ls")
    return f.getlength(s) * k, l * k, t * k, r * k, b * k


def text_width(s: str, h_mm: float, weight: str = "regular", style: str = "normal") -> float:
    """Advance width in mm."""
    return text_metrics(s, h_mm, weight, style)[0]


def wrap(s: str, width_mm: float, h_mm: float, weight: str = "regular", style: str = "normal") -> list[str]:
    """Greedy word wrap of s into lines no wider than width_mm."""
    out: list[str] = []
    for para in s.split("\n"):
        cur = ""
        for w in para.split():
            trial = f"{cur} {w}".strip()
            if cur and text_width(trial, h_mm, weight, style) > width_mm:
                out.append(cur)
                cur = w
            else:
                cur = trial
        out.append(cur)
    return out
