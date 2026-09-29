"""Display list shared by the SVG and DXF writers.

Every item carries an NCS `layer`, a `space` and an optional `tag` (semantic id such as "door:D1").
space "model": coordinates, radii and offsets in model inches (x east, y north, y up).
space "paper": millimetres on the sheet, y grows downward.
Pens, text heights and Dim offsets are always paper mm. Angles are degrees, counter-clockwise on screen.
Text anchor is two letters: vertical b (baseline) | m (middle of cap height) | t (top of caps), then
horizontal l | c | r. Text.rot_deg 90 reads bottom to top.
Dim is semantic: p1, p2 are the measured points, orient "h" or "v", offset_mm moves the dimension line
from the p1 reference toward +y (north) for "h" and +x (east) for "v". dim_geometry expands one into
extension lines, dimension line, ticks and text; the DXF writer emits a real DIMENSION instead.
RoomBoundary is not drawn in SVG; it carries the room polygon (model inches) on A-AREA for DXF.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import styles as S
from .metrics import text_width

Pt = tuple[float, float]


@dataclass
class Item:
    layer: str = field(default="", kw_only=True)
    space: str = field(default="paper", kw_only=True)
    tag: str = field(default="", kw_only=True)


@dataclass
class Poly(Item):
    pts: list[Pt]
    closed: bool = True
    pen_mm: float = S.PEN["opening"]
    fill: str | None = None
    dash: str | None = None
    hatch: str | None = None
    holes: list[list[Pt]] = field(default_factory=list)
    color: str = S.INK


@dataclass
class Line(Item):
    p1: Pt
    p2: Pt
    pen_mm: float = S.PEN["opening"]
    dash: str | None = None
    color: str = S.INK


@dataclass
class Arc(Item):
    center: Pt
    r: float
    start_deg: float
    end_deg: float
    pen_mm: float = S.PEN["swing"]
    dash: str | None = None
    color: str = S.INK


@dataclass
class Circle(Item):
    center: Pt
    r: float
    pen_mm: float = S.PEN["opening"]
    fill: str | None = None
    dash: str | None = None
    color: str = S.INK


@dataclass
class Text(Item):
    pos: Pt
    s: str
    h_mm: float = S.H["note"]
    anchor: str = "bl"
    rot_deg: float = 0.0
    weight: str = "regular"
    style: str = "normal"
    color: str = S.INK
    halo: bool = False


@dataclass
class Dim(Item):
    p1: Pt
    p2: Pt
    orient: str
    offset_mm: float
    text: str
    open_marker: bool = False
    place: str = "mid"  # mid | raise
    raise_mm: float = 0.0
    shift_mm: float = 0.0


@dataclass
class RoomBoundary(Item):
    room_id: str
    pts: list[Pt]


@dataclass
class Sheet:
    size_mm: Pt
    scale: int
    ox: float = 0.0
    oy: float = 0.0
    level_id: str = ""
    sheet_level: str = ""
    lang: str = "fr"
    units: str = "metric"
    title: str = ""
    items: list[Item] = field(default_factory=list)
    scalebar: dict | None = None  # solid 1 m segment: x0_mm, x1_mm, y_mm
    meta: dict = field(default_factory=dict)

    @property
    def k(self) -> float:
        """Paper mm per model inch."""
        return 25.4 / self.scale

    def xf(self, x: float, y: float) -> Pt:
        """Model inches to paper mm."""
        return (self.ox + x * self.k, self.oy - y * self.k)

    def inv(self, xm: float, ym: float) -> Pt:
        """Paper mm to model inches."""
        return ((xm - self.ox) / self.k, (self.oy - ym) / self.k)

    def paper(self, space: str, p: Pt) -> Pt:
        """Point of an item in `space` to paper mm."""
        return self.xf(*p) if space == "model" else p

    def add(self, *items: Item) -> None:
        """Append items to the display list."""
        self.items.extend(items)

    def of_layer(self, layer: str) -> list[Item]:
        """Items on one layer."""
        return [i for i in self.items if i.layer == layer]


@dataclass
class DimGeom:
    ext: list[tuple[Pt, Pt]]
    line: tuple[Pt, Pt]
    ticks: list[tuple[Pt, Pt]]
    text: Text
    leader: tuple[Pt, Pt] | None


def dim_fits(d: Dim, sheet: Sheet) -> bool:
    """True when the dimension text fits between the extension lines."""
    a, b = sheet.paper(d.space, d.p1), sheet.paper(d.space, d.p2)
    span = abs(a[0] - b[0]) if d.orient == "h" else abs(a[1] - b[1])
    return text_width(d.text, S.H["dim"]) + 1.6 <= span


def dim_geometry(d: Dim, sheet: Sheet) -> DimGeom:
    """Expand a Dim into paper-mm primitives per the SPEC dimension style."""
    a, b = sheet.paper(d.space, d.p1), sheet.paper(d.space, d.p2)
    g, ov, tk, tg = S.DIM["gap"], S.DIM["over"], S.DIM["tick"], S.DIM["text_gap"]
    h = S.H["dim"]
    off = d.offset_mm
    if d.orient == "h":
        a, b = sorted((a, b))
        ly = a[1] - off
        sgn = [math.copysign(1, ly - p[1]) for p in (a, b)]
        ext = [((p[0], p[1] + s * g), (p[0], ly + s * ov)) for p, s in zip((a, b), sgn)]
        line = ((a[0], ly), (b[0], ly))
        d45 = tk / 2 / math.sqrt(2)
        ticks = [((p[0] - d45, ly + d45), (p[0] + d45, ly - d45)) for p in (a, b)]
        cx = (a[0] + b[0]) / 2 + d.shift_mm
        base = ly - tg - (d.raise_mm if d.place == "raise" else 0.0)
        text = Text((cx, base), d.text, h, "bc", 0.0, layer="A-ANNO-DIMS")
        leader = ((cx, base + 0.4), (cx, ly)) if d.place == "raise" else None
    else:
        a, b = sorted((a, b), key=lambda p: p[1])
        lx = a[0] + off
        sgn = [math.copysign(1, lx - p[0]) for p in (a, b)]
        ext = [((p[0] + s * g, p[1]), (lx + s * ov, p[1])) for p, s in zip((a, b), sgn)]
        line = ((lx, a[1]), (lx, b[1]))
        d45 = tk / 2 / math.sqrt(2)
        ticks = [((lx - d45, p[1] + d45), (lx + d45, p[1] - d45)) for p in (a, b)]
        cy = (a[1] + b[1]) / 2 + d.shift_mm
        base = lx - tg - (d.raise_mm if d.place == "raise" else 0.0)
        text = Text((base, cy), d.text, h, "bc", 90.0, layer="A-ANNO-DIMS")
        leader = ((base + 0.4, cy), (lx, cy)) if d.place == "raise" else None
    return DimGeom(ext, line, ticks, text, leader)
