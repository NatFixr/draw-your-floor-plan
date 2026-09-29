"""SVG writer: display list to a sheet-sized SVG (user units are paper mm)."""
from __future__ import annotations

import math
from pathlib import Path
from xml.sax.saxutils import escape

from . import styles as S
from .layout import Arc, Circle, Dim, Item, Line, Poly, RoomBoundary, Sheet, Text, dim_geometry

_HATCH_ID = "hatch-unmeasured"


def _n(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _stroke(pen: float, color: str, dash: str | None) -> str:
    a = f'stroke="{color}" stroke-width="{_n(pen)}"'
    if dash:
        a += ' stroke-dasharray="' + " ".join(_n(x) for x in S.DASH[dash]) + '"'
    return a


def _ring(pts, sheet: Sheet, space: str, close: bool) -> str:
    q = [sheet.paper(space, p) for p in pts]
    return "M" + " L".join(f"{_n(x)} {_n(y)}" for x, y in q) + (" Z" if close else "")


def _line(p1, p2, pen, color=S.INK, dash=None, cls="") -> str:
    c = f' class="{cls}"' if cls else ""
    return (f'<line{c} x1="{_n(p1[0])}" y1="{_n(p1[1])}" x2="{_n(p2[0])}" y2="{_n(p2[1])}" '
            f'{_stroke(pen, color, dash)}/>')


def _text(t: Text, sheet: Sheet) -> str:
    x, y = sheet.paper(t.space, t.pos)
    h = t.h_mm
    fs = h / S.CAP
    dy = {"b": 0.0, "m": h / 2, "t": h}[t.anchor[0]]
    anchor = {"l": "start", "c": "middle", "r": "end"}[t.anchor[1]]
    tr = f' transform="translate({_n(x)} {_n(y)}) rotate({_n(-t.rot_deg)})"' if t.rot_deg else f' transform="translate({_n(x)} {_n(y)})"'
    a = f'font-size="{_n(fs)}" text-anchor="{anchor}" fill="{t.color}"'
    if t.weight == "bold":
        a += ' font-weight="700"'
    if t.style == "italic":
        a += ' font-style="italic"'
    if t.halo:
        a += f' stroke="{S.PAPER}" stroke-width="1.1" stroke-linejoin="round" paint-order="stroke"'
    return f'<text{tr} x="0" y="{_n(dy)}" {a}>{escape(t.s)}</text>'


def _arc(a: Arc, sheet: Sheet) -> str:
    k = sheet.k if a.space == "model" else 1.0
    cx, cy = sheet.paper(a.space, a.center)
    r = a.r * k
    p0 = (cx + r * math.cos(math.radians(a.start_deg)), cy - r * math.sin(math.radians(a.start_deg)))
    p1 = (cx + r * math.cos(math.radians(a.end_deg)), cy - r * math.sin(math.radians(a.end_deg)))
    span = (a.end_deg - a.start_deg) % 360
    d = f"M{_n(p0[0])} {_n(p0[1])} A{_n(r)} {_n(r)} 0 {1 if span > 180 else 0} 0 {_n(p1[0])} {_n(p1[1])}"
    cls, ident = "arc", ""
    if a.tag.startswith("door:"):
        cls, ident = "door-arc", f' id="arc-{escape(a.tag[5:])}"'
    return f'<path class="{cls}"{ident} fill="none" d="{d}" {_stroke(a.pen_mm, a.color, a.dash)}/>'


def _poly(p: Poly, sheet: Sheet) -> str:
    d = _ring(p.pts, sheet, p.space, p.closed)
    for h in p.holes:
        d += " " + _ring(h, sheet, p.space, True)
    fill = f"url(#{_HATCH_ID})" if p.hatch else (p.fill or "none")
    stroke = _stroke(p.pen_mm, p.color, p.dash) if p.pen_mm > 0 else 'stroke="none"'
    tag = f' data-tag="{escape(p.tag)}"' if p.tag else ""
    return f'<path{tag} fill="{fill}" fill-rule="evenodd" stroke-linejoin="miter" d="{d}" {stroke}/>'


def _dim(d: Dim, sheet: Sheet) -> str:
    g = dim_geometry(d, sheet)
    fine = S.PEN["fine"]
    out = [f'<g class="dim" data-tag="{escape(d.tag)}">']
    out += [_line(a, b, fine) for a, b in g.ext]
    out.append(_line(*g.line, fine))
    out += [_line(a, b, S.PEN["tick"]) for a, b in g.ticks]
    if g.leader:
        out.append(_line(*g.leader, fine))
    out.append(_text(g.text, sheet))
    out.append("</g>")
    return "".join(out)


def _item(it: Item, sheet: Sheet) -> str:
    if isinstance(it, Poly):
        return _poly(it, sheet)
    if isinstance(it, Line):
        p1, p2 = sheet.paper(it.space, it.p1), sheet.paper(it.space, it.p2)
        return _line(p1, p2, it.pen_mm, it.color, it.dash)
    if isinstance(it, Arc):
        return _arc(it, sheet)
    if isinstance(it, Circle):
        k = sheet.k if it.space == "model" else 1.0
        cx, cy = sheet.paper(it.space, it.center)
        return (f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(it.r * k)}" fill="{it.fill or "none"}" '
                f'{_stroke(it.pen_mm, it.color, it.dash)}/>')
    if isinstance(it, Text):
        return _text(it, sheet)
    if isinstance(it, Dim):
        return _dim(it, sheet)
    if isinstance(it, RoomBoundary):
        return ""
    raise TypeError(type(it))


def svg_string(sheet: Sheet) -> str:
    """Render the sheet to an SVG document string."""
    w, h = sheet.size_mm
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{_n(w)}mm" height="{_n(h)}mm" '
            f'viewBox="0 0 {_n(w)} {_n(h)}" font-family="{S.FONT_FAMILY}">')
    sp = S.HATCH_SPACING_MM
    defs = (f'<defs><pattern id="{_HATCH_ID}" patternUnits="userSpaceOnUse" width="{_n(sp)}" height="{_n(sp)}" '
            f'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="{_n(sp)}" stroke="{S.HATCH_COLOR}" '
            f'stroke-width="{_n(S.PEN["fine"])}"/></pattern></defs>')
    body = [f'<title>{escape(sheet.title)}</title>', defs,
            f'<rect x="0" y="0" width="{_n(w)}" height="{_n(h)}" fill="{S.PAPER}"/>']
    layers = list(S.LAYERS) + sorted({i.layer for i in sheet.items} - set(S.LAYERS))
    for layer in layers:
        its = sheet.of_layer(layer)
        if not its:
            continue
        body.append(f'<g id="{layer}" data-layer="{layer}">')
        body += [s for s in (_item(i, sheet) for i in its) if s]
        body.append("</g>")
    return head + "\n".join(body) + "</svg>\n"


def write_svg(sheet: Sheet, path: str | Path) -> Path:
    """Write the SVG file and return its path."""
    p = Path(path)
    p.write_text(svg_string(sheet), encoding="utf-8")
    return p
