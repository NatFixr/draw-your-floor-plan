"""DXF writer (ezdxf, R2018): model items in inches in model space, sheet frame in a paper layout.

Dim items become real DIMENSION entities (dimstyle FP-ARCH); paper items are drawn in mm with y flipped.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import ezdxf
import ezdxf.zoom
from ezdxf import colors
from ezdxf.enums import MTextEntityAlignment, TextEntityAlignment
from ezdxf.lldxf import const

from . import styles as S
from .layout import Arc, Circle, Dim, Item, Line, Poly, RoomBoundary, Sheet, Text, dim_geometry
from .metrics import text_width

APPID = "FLOORPLAN"
DIMSTYLE = "FP-ARCH"
LW_VALID = (0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100, 106, 120, 140, 158, 200, 211)
ANSI31_SPACING_IN = 0.125  # perpendicular line spacing of ANSI31 in the imperial pattern table

# name: (lineweight 1/100 mm, ACI colour, plot)
LAYERS = {
    "A-WALL-E": (50, 8, True), "A-WALL-N": (70, 7, True), "A-WALL-D": (35, 1, True),
    "A-DOOR": (25, 3, True), "A-GLAZ": (25, 5, True),
    "A-FLOR-STRS": (18, 6, True), "A-FLOR-FIXT": (18, 30, True), "A-FURN": (13, 8, True),
    "A-AREA": (13, 9, False), "A-AREA-OPEN": (13, 9, True), "A-AREA-IDEN": (18, 2, True),
    "A-ANNO-DIMS": (13, 4, True), "A-ANNO-TEXT": (18, 7, True), "A-ANNO-SYMB": (25, 7, True),
    "A-ANNO-TTLB": (50, 7, True), "A-ANNO-LEGN": (18, 7, True), "A-ANNO-SCHD": (18, 7, True),
    "A-ANNO-VPRT": (13, 7, False),
}
DASH_LT = {"dashed": "DASHED", "fine": "FP-FINE"}
STYLES = {("regular", "normal"): "FP", ("bold", "normal"): "FP-BOLD",
          ("regular", "italic"): "FP-ITALIC", ("bold", "italic"): "FP-BOLDITALIC"}
_ALIGN_T = {"bl": TextEntityAlignment.LEFT, "bc": TextEntityAlignment.CENTER, "br": TextEntityAlignment.RIGHT,
            "ml": TextEntityAlignment.MIDDLE_LEFT, "mc": TextEntityAlignment.MIDDLE_CENTER,
            "mr": TextEntityAlignment.MIDDLE_RIGHT, "tl": TextEntityAlignment.TOP_LEFT,
            "tc": TextEntityAlignment.TOP_CENTER, "tr": TextEntityAlignment.TOP_RIGHT}
_ALIGN_M = {"bl": MTextEntityAlignment.BOTTOM_LEFT, "bc": MTextEntityAlignment.BOTTOM_CENTER,
            "br": MTextEntityAlignment.BOTTOM_RIGHT, "ml": MTextEntityAlignment.MIDDLE_LEFT,
            "mc": MTextEntityAlignment.MIDDLE_CENTER, "mr": MTextEntityAlignment.MIDDLE_RIGHT,
            "tl": MTextEntityAlignment.TOP_LEFT, "tc": MTextEntityAlignment.TOP_CENTER,
            "tr": MTextEntityAlignment.TOP_RIGHT}


def _lw(pen_mm: float) -> int:
    """Nearest valid DXF lineweight (1/100 mm)."""
    v = pen_mm * 100
    return min(LW_VALID, key=lambda w: abs(w - v))


def _rgb(hexs: str) -> colors.RGB:
    h = hexs.lstrip("#")
    return colors.RGB(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _mtext_escape(s: str) -> str:
    s = s.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
    return re.sub(r"\r?\n", r"\\P", s)


def _plain(s: str) -> str:
    """Plain TEXT: neutralise %% control codes."""
    return s.replace("%%", "% %")


class _Writer:
    def __init__(self, sheet: Sheet):
        self.sh = sheet
        self.k = sheet.k
        self.mm_in = 1.0 / sheet.k
        self.H = sheet.size_mm[1]
        self.doc = ezdxf.new("R2018", setup=False)
        self.msp = self.doc.modelspace()
        self.psp = None
        self.layer_lw: dict[str, int] = {}
        self._setup()

    # ---------------------------------------------------------------- document
    def _setup(self) -> None:
        d, sh = self.doc, self.sh
        d.header["$INSUNITS"] = 1
        d.header["$MEASUREMENT"] = 0
        m = sh.lang == "fr" and sh.units != "imperial"
        d.header["$LUNITS"] = 2 if m else 4
        d.header["$LUPREC"] = 2 if m else 4
        d.header["$PSLTSCALE"] = 0
        d.header["$DIMSTYLE"] = DIMSTYLE
        d.appids.add(APPID)
        d.linetypes.add("DASHED", pattern=[3.6, 2.4, -1.2], description="Dashed 2.4/1.2 mm __ __ __")
        d.linetypes.add("FP-FINE", pattern=[2.0, 1.2, -0.8], description="Fine dash 1.2/0.8 mm _ _ _")
        for (weight, style), name in STYLES.items():
            d.styles.add(name, font=S.FONT_FILES[(weight, style)].rsplit("/", 1)[-1])
        for name in LAYERS:
            self.layer(name)
        self._dimstyle()

    def _dimstyle(self) -> None:
        sh = self.sh
        metric = sh.lang in ("fr", "bi") and sh.units != "imperial"
        attr = {
            "dimscale": sh.scale / 25.4, "dimtxt": S.H["dim"], "dimtxsty": "FP", "dimtad": 1, "dimgap": S.DIM["text_gap"],
            "dimexo": S.DIM["gap"], "dimexe": S.DIM["over"], "dimasz": S.DIM["tick"] / math.sqrt(2), "dimtsz": 0.0,
            "dimtih": 0, "dimatfit": 2, "dimtix": 0, "dimtoh": 0, "dimlwd": _lw(S.PEN["fine"]), "dimlwe": _lw(S.PEN["fine"]),
            "dimdle": 0.0, "dimzin": 0, "dimlunit": 2 if metric else 4, "dimdec": 2 if metric else 4,
            "dimlfac": 0.0254 if metric else 1.0, "dimdsep": ord(",") if sh.lang == "fr" else ord("."),
        }
        ds = self.doc.dimstyles.new(DIMSTYLE, dxfattribs=attr)
        ds.set_arrows(blk=ezdxf.ARROWS.architectural_tick)

    def layer(self, name: str, pen_mm: float = S.PEN["opening"]) -> str:
        """Create the layer when unknown; return its name."""
        if name not in self.layer_lw:
            lw, aci, plot = LAYERS.get(name, (_lw(pen_mm), 7, True))
            lyr = self.doc.layers.add(name, color=aci, lineweight=lw)
            lyr.dxf.plot = int(plot)
            if name == "A-WALL-D":
                lyr.dxf.linetype = "DASHED"
            self.layer_lw[name] = lw
        return name

    # ---------------------------------------------------------------- helpers
    def target(self, it: Item):
        """(layout, point transform, length factor mm->layout units, dash ltscale) for an item."""
        if it.space == "model":
            return self.msp, (lambda p: (p[0], p[1])), self.mm_in, self.mm_in
        return self.psp, (lambda p: (p[0], self.H - p[1])), 1.0, 1.0

    def attribs(self, it: Item, pen: float | None = None, dash: str | None = None, color: str = S.INK) -> dict:
        layer = it.layer or "0"
        if layer == "A-AREA" and not isinstance(it, RoomBoundary):
            layer = "A-AREA-OPEN"
        self.layer(layer, pen if pen else S.PEN["opening"])
        a: dict = {"layer": layer}
        if pen and _lw(pen) != self.layer_lw[layer]:
            a["lineweight"] = _lw(pen)
        if dash:
            a["linetype"] = DASH_LT[dash]
            a["ltscale"] = self.target(it)[3]
        if color != S.INK:
            a["true_color"] = colors.rgb2int(_rgb(color))
        return a

    def tag(self, ent, it: Item, value: str | None = None) -> None:
        v = value if value is not None else it.tag
        if v:
            ent.set_xdata(APPID, [(1000, v)])

    # ---------------------------------------------------------------- items
    def poly(self, p: Poly) -> None:
        lay, tf, _, _ = self.target(p)
        rings = [[tf(q) for q in p.pts]] + [[tf(q) for q in h] for h in p.holes]
        if p.fill and p.closed and len(p.pts) >= 3:
            h = lay.add_hatch(color=7, dxfattribs={"layer": self.attribs(p)["layer"]})
            if p.fill == S.INK:
                h.set_solid_fill(color=7)
            else:
                h.set_solid_fill(rgb=_rgb(p.fill))
            for i, r in enumerate(rings):
                h.paths.add_polyline_path(r, is_closed=True,
                                          flags=const.BOUNDARY_PATH_EXTERNAL if i == 0 else const.BOUNDARY_PATH_DEFAULT)
            self.tag(h, p)
        if p.hatch and p.closed and len(p.pts) >= 3:
            h = lay.add_hatch(color=7, dxfattribs={"layer": self.attribs(p)["layer"]})
            spacing = S.HATCH_SPACING_MM * self.target(p)[2]
            h.set_pattern_fill("ANSI31", scale=spacing / ANSI31_SPACING_IN, color=7)
            h.rgb = _rgb(S.HATCH_COLOR)
            for i, r in enumerate(rings):
                h.paths.add_polyline_path(r, is_closed=True,
                                          flags=const.BOUNDARY_PATH_EXTERNAL if i == 0 else const.BOUNDARY_PATH_DEFAULT)
            self.tag(h, p)
        if p.pen_mm > 0:
            a = self.attribs(p, p.pen_mm, p.dash, p.color)
            for i, r in enumerate(rings):
                if len(r) >= 2:
                    e = lay.add_lwpolyline(r, format="xy", close=(p.closed or i > 0), dxfattribs=dict(a))
                    self.tag(e, p)

    def line(self, ln: Line) -> None:
        lay, tf, _, _ = self.target(ln)
        e = lay.add_line(tf(ln.p1), tf(ln.p2), dxfattribs=self.attribs(ln, ln.pen_mm, ln.dash, ln.color))
        self.tag(e, ln)

    def arc(self, a: Arc) -> None:
        lay, tf, _, _ = self.target(a)
        e = lay.add_arc(tf(a.center), a.r, a.start_deg, a.end_deg, dxfattribs=self.attribs(a, a.pen_mm, a.dash, a.color))
        self.tag(e, a)

    def circle(self, c: Circle) -> None:
        lay, tf, _, _ = self.target(c)
        cx, cy = tf(c.center)
        if c.fill:
            h = lay.add_hatch(color=7, dxfattribs={"layer": self.attribs(c)["layer"]})
            if c.fill == S.INK:
                h.set_solid_fill(color=7)
            else:
                h.set_solid_fill(rgb=_rgb(c.fill))
            h.paths.add_polyline_path([(cx - c.r, cy, 1), (cx + c.r, cy, 1)], is_closed=True,
                                      flags=const.BOUNDARY_PATH_EXTERNAL)
            self.tag(h, c)
        if c.pen_mm > 0:
            e = lay.add_circle((cx, cy), c.r, dxfattribs=self.attribs(c, c.pen_mm, c.dash, c.color))
            self.tag(e, c)

    def text(self, t: Text) -> None:
        lay, tf, f, _ = self.target(t)
        a = self.attribs(t, None, None, t.color)
        a["style"] = STYLES[(t.weight if t.weight in ("regular", "bold") else "regular",
                             t.style if t.style in ("normal", "italic") else "normal")]
        h = t.h_mm * f
        if "\n" in t.s:
            a.update(char_height=h, rotation=t.rot_deg)
            e = lay.add_mtext(_mtext_escape(t.s), dxfattribs=a)
            e.set_location(tf(t.pos), attachment_point=int(_ALIGN_M[t.anchor]))
        else:
            e = lay.add_text(_plain(t.s), height=h, rotation=t.rot_deg, dxfattribs=a)
            e.set_placement(tf(t.pos), align=_ALIGN_T[t.anchor])
        self.tag(e, t)

    def room(self, r: RoomBoundary) -> None:
        a = self.attribs(r, S.PEN["fine"])
        e = self.msp.add_lwpolyline([tuple(q) for q in r.pts], format="xy", close=True, dxfattribs=a)
        e.set_xdata(APPID, [(1000, r.room_id)])

    def dim(self, d: Dim) -> None:
        sh = self.sh
        if d.space != "model":
            g = dim_geometry(d, sh)
            fine, tk = S.PEN["fine"], S.PEN["tick"]
            for a, b in g.ext + ([g.leader] if g.leader else []) + [g.line]:
                self.line(Line(a, b, fine, layer=d.layer, tag=d.tag))
            for a, b in g.ticks:
                self.line(Line(a, b, tk, layer=d.layer, tag=d.tag))
            self.text(g.text)
            return
        pa, pb = sh.xf(*d.p1), sh.xf(*d.p2)
        off = d.offset_mm * self.mm_in
        # point order (west to east, south to north) decides which side CAD puts the text on
        if d.orient == "h":
            p1, p2 = (d.p1, d.p2) if pa <= pb else (d.p2, d.p1)
            base, angle = (p1[0], p1[1] + off), 0
        else:
            top, bot = (d.p1, d.p2) if pa[1] <= pb[1] else (d.p2, d.p1)
            p1, p2 = bot, top
            base, angle = (top[0] + off, top[1]), 90
        # text is pinned where dim_geometry puts it, so CAD's own fit test cannot move it off the PDF
        t = dim_geometry(d, sh).text
        hx, hy = (0.0, S.H["dim"] / 2) if not t.rot_deg else (-S.H["dim"] / 2, 0.0)
        kw = {"location": sh.inv(t.pos[0] + hx, t.pos[1] - hy), "override": {"dimtmove": 1 if d.place == "raise" else 2}}
        layer = self.attribs(d)["layer"]
        dm = self.msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, text=d.text, dimstyle=DIMSTYLE,
                                     dxfattribs={"layer": layer}, **kw)
        dm.render()
        self.tag(dm.dimension, d)

    # ---------------------------------------------------------------- sheet
    def view_rect(self) -> tuple[float, float, float, float]:
        """Paper-mm rectangle (x0, y0, x1, y1, y down) the viewport shows."""
        r = self.sh.meta.get("view_rect_mm")
        if r:
            return tuple(r)
        xs: list[float] = []
        ys: list[float] = []
        for it in self.sh.items:
            if it.space != "model":
                continue
            pts, ext = [], 0.0
            if isinstance(it, (Poly, RoomBoundary)):
                pts = it.pts
            elif isinstance(it, Line):
                pts = [it.p1, it.p2]
            elif isinstance(it, Dim):
                g = dim_geometry(it, self.sh)  # already paper mm
                tw = text_width(it.text, S.H["dim"]) / 2
                for x, y in [q for e in g.ext for q in e] + list(g.line):
                    xs.append(x)
                    ys.append(y)
                xs += [g.text.pos[0] - tw, g.text.pos[0] + tw]
                ys += [g.text.pos[1] - tw, g.text.pos[1] + tw]
            elif isinstance(it, (Arc, Circle)):
                pts, ext = [it.center], it.r * self.k
            elif isinstance(it, Text):
                pts, ext = [it.pos], text_width(it.s, it.h_mm)
            for p in pts:
                x, y = self.sh.xf(*p)
                xs += [x - ext, x + ext]
                ys += [y - ext, y + ext]
        w, h = self.sh.size_mm
        b = S.BORDER_MM
        if not xs:
            return (b, b, w - b, h - b)
        pad = 2.0
        return (max(b, min(xs) - pad), max(b, min(ys) - pad), min(w - b, max(xs) + pad), min(h - b, max(ys) + pad))

    def layout_name(self) -> str:
        sh = self.sh
        raw = "-".join(x for x in (sh.sheet_level.upper(), sh.level_id) if x) or "SHEET"
        return re.sub(r'[<>/\\":;?*|,=`]', "_", raw)[:255]

    def build(self) -> None:
        d, sh = self.doc, self.sh
        w, h = sh.size_mm
        name = self.layout_name()
        self.psp = d.layouts.new(name)
        self.psp.page_setup(size=(w, h), margins=(0, 0, 0, 0), units="mm", scale=(1, 1))
        if "Layout1" in d.layouts:
            d.layouts.delete("Layout1")
        order = list(S.LAYERS) + sorted({i.layer for i in sh.items} - set(S.LAYERS))
        rank = {n: i for i, n in enumerate(order)}
        for it in sorted(sh.items, key=lambda i: rank.get(i.layer, len(order))):
            if isinstance(it, Poly):
                self.poly(it)
            elif isinstance(it, Line):
                self.line(it)
            elif isinstance(it, Arc):
                self.arc(it)
            elif isinstance(it, Circle):
                self.circle(it)
            elif isinstance(it, Text):
                self.text(it)
            elif isinstance(it, Dim):
                self.dim(it)
            elif isinstance(it, RoomBoundary):
                self.room(it)
            else:
                raise TypeError(type(it))
        x0, y0, x1, y1 = self.view_rect()
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        vp = self.psp.add_viewport(center=(cx, h - cy), size=(x1 - x0, y1 - y0), view_center_point=sh.inv(cx, cy),
                                   view_height=(y1 - y0) / self.k, status=1,
                                   dxfattribs={"layer": self.layer("A-ANNO-VPRT")})
        vp.dxf.view_height = (y1 - y0) / self.k
        ezdxf.zoom.extents(self.msp)
        d.header["$TILEMODE"] = 1


def write_dxf(sheet: Sheet, path: Path) -> None:
    """Write the sheet as an R2018 DXF: model in inches, sheet frame and a 1:scale viewport in a paper layout."""
    w = _Writer(sheet)
    w.build()
    w.doc.saveas(Path(path))
