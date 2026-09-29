"""Collision registry in paper mm: text boxes measured with Pillow, obstacles as shapely geometry."""
from __future__ import annotations

import math

from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.prepared import prep

from .layout import Text
from .metrics import text_metrics

PAD_MM = 0.25
PAD_Y_MM = 0.05  # vertical pad: wrapped lines sit on a 1.5 x h pitch


def text_polygon(t: Text, pos: tuple[float, float] | None = None) -> Polygon:
    """Ink box of a Text (pos overrides t.pos), paper mm, rotation applied."""
    px, py = pos if pos is not None else t.pos
    adv, l, top, r, b = text_metrics(t.s, t.h_mm, t.weight, t.style)
    v, hz = t.anchor[0], t.anchor[1]
    ox = {"l": 0.0, "c": -adv / 2, "r": -adv}[hz]
    cap = t.h_mm
    oy = {"b": 0.0, "m": cap / 2, "t": cap}[v]  # baseline offset below the anchor, y down
    top, b = max(top, -1.07 * t.h_mm), min(b, 0.34 * t.h_mm)  # ascender/descender extremes; accents ignored
    x0, x1 = ox + l - PAD_MM, ox + r + PAD_MM
    y0, y1 = oy + top - PAD_Y_MM, oy + b + PAD_Y_MM
    th = math.radians(t.rot_deg)
    c, s = math.cos(th), math.sin(th)
    pts = []
    for lx, ly_down in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        up = -ly_down
        pts.append((px + lx * c - up * s, py - (lx * s + up * c)))
    return Polygon(pts)


class Placer:
    """Registry of obstacles and placed text; every text drawn goes through add_text."""

    def __init__(self) -> None:
        self.obstacles: list[tuple[str, BaseGeometry]] = []
        self.texts: list[tuple[Text, Polygon]] = []
        self._union: BaseGeometry | None = None
        self._prep = None

    def add_obstacle(self, kind: str, geom: BaseGeometry, buffer: float = 0.0) -> None:
        """Register a solid region text must not overlap; lines get `buffer` mm."""
        if geom.is_empty:
            return
        self.obstacles.append((kind, geom.buffer(buffer) if buffer else geom))
        self._union = None

    def remove_kind(self, kind: str) -> None:
        """Drop every obstacle of one kind."""
        self.obstacles = [o for o in self.obstacles if o[0] != kind]
        self._union = None

    def _obstacle_prep(self):
        if self._union is None:
            self._union = unary_union([g for _, g in self.obstacles]) if self.obstacles else Polygon()
            self._prep = prep(self._union)
        return self._prep

    def is_free(self, geom: BaseGeometry, ignore: tuple[str, ...] = (), text: bool = True) -> bool:
        """True when geom hits no obstacle (except `ignore` kinds) and no placed text."""
        if ignore:
            for kind, g in self.obstacles:
                if kind not in ignore and g.intersects(geom):
                    return False
        elif self._obstacle_prep().intersects(geom):
            return False
        if text:
            for _, b in self.texts:
                if b.intersects(geom) and b.intersection(geom).area > 1e-6:
                    return False
        return True

    def add_text(self, t: Text, check: bool = False, ignore: tuple[str, ...] = ()) -> bool:
        """Register t; with check, refuse (False) when its box is not free."""
        b = text_polygon(t)
        if check and not self.is_free(b, ignore):
            return False
        self.texts.append((t, b))
        return True

    def overlaps(self) -> list[tuple[str, str]]:
        """Pairs of registered text boxes that overlap."""
        out = []
        for i, (ta, a) in enumerate(self.texts):
            for tb, b in self.texts[i + 1:]:
                if a.intersects(b) and a.intersection(b).area > 1e-6:
                    out.append((ta.s, tb.s))
        return out


def rect(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    """Axis-aligned box helper."""
    return box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
