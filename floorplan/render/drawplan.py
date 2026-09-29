"""Model geometry to display-list items: walls, openings, stairs, fixtures, hatches, labels."""
from __future__ import annotations

import math

import shapely
from shapely import affinity
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from . import styles as S
from .ctx import Ctx
from .layout import Arc, Line, Poly, RoomBoundary, Text
from .metrics import text_width
from .placer import text_polygon
from ..geometry import DIRS, FIXTURE_DEFAULT, OpeningGeom, door_swing, item_frame


def to_paper(ctx: Ctx, g: BaseGeometry) -> BaseGeometry:
    """Model-inch shapely geometry to paper mm."""
    k, sh = ctx.k, ctx.sheet
    return affinity.affine_transform(g, [k, 0, 0, -k, sh.ox, sh.oy])


def _parts(g) -> list[Polygon]:
    return [p for p in shapely.get_parts(g) if isinstance(p, Polygon) and not p.is_empty]


def draw_room_boundaries(ctx: Ctx) -> None:
    """RoomBoundary items (DXF only) and dashed open boundaries between touching rooms."""
    for rid, poly in ctx.geom.rooms.items():
        ctx.sheet.add(RoomBoundary(rid, list(poly.exterior.coords)[:-1], layer="A-AREA", space="model"))
    ids = list(ctx.geom.rooms)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            inter = ctx.geom.rooms[a].boundary.intersection(ctx.geom.rooms[b].boundary)
            for ln in shapely.get_parts(inter):
                if isinstance(ln, LineString) and ln.length > 1.0:
                    ctx.sheet.add(Line(ln.coords[0], ln.coords[-1], S.PEN["fine"], "dashed",
                                       layer="A-AREA", space="model", tag=f"open:{a}:{b}"))


def draw_walls(ctx: Ctx) -> None:
    """Poche polygons per status, outline on every ring."""
    for status, g in ctx.geom.walls.items():
        layer = S.LAYER_OF_WALL[status]
        for p in _parts(g):
            pts = list(p.exterior.coords)[:-1]
            holes = [list(r.coords)[:-1] for r in p.interiors]
            if status == "demolish":
                ctx.sheet.add(Poly(pts, True, S.PEN["demo"], None, "dashed", holes=holes, layer=layer, space="model"))
            else:
                ctx.sheet.add(Poly(pts, True, S.PEN["cut"], S.FILL[status], holes=holes, layer=layer, space="model"))
        if not g.is_empty:
            ctx.placer.add_obstacle("wall", to_paper(ctx, g).buffer(0.2))


def unmeasured_pieces(ctx: Ctx) -> list[Polygon]:
    """Zones from the geometry: hatched, bounded by thin dashed zone edges, never poche."""
    return list(ctx.geom.zones)


def draw_unmeasured(ctx: Ctx) -> None:
    """Hatch each zone and draw its boundary (minus the envelope face) as a 0.18 dashed line."""
    for p in unmeasured_pieces(ctx):
        ctx.sheet.add(Poly(list(p.exterior.coords)[:-1], True, 0.0, None, None, "unmeasured",
                           [list(r.coords)[:-1] for r in p.interiors], layer="A-AREA", space="model", tag="unmeasured"))
    for e in ctx.geom.zone_edges:
        c = list(e.coords)
        ctx.sheet.add(Line(c[0], c[-1], S.PEN["swing"], "dashed", layer="A-AREA", space="model", tag="zone-edge") if len(c) == 2 else
                      Poly(c, False, S.PEN["swing"], None, "dashed", layer="A-AREA", space="model", tag="zone-edge"))


def _v(a, b, s=1.0):
    return (a[0] + b[0] * s, a[1] + b[1] * s)


def _sector(c, r, a0, a1, n=24):
    pts = [c]
    for i in range(n + 1):
        a = math.radians(a0 + (a1 - a0) * i / n)
        pts.append((c[0] + r * math.cos(a), c[1] + r * math.sin(a)))
    return Polygon(pts)


def draw_opening(ctx: Ctx, og: OpeningGeom) -> None:
    """Door leaf and swing, window frame and glass lines, or cased-opening lines, plus jambs."""
    sh, pen = ctx.sheet, S.PEN["opening"]
    n, d = og.normal, og.depth
    a, b = og.a, og.b
    a2, b2 = _v(a, n, d), _v(b, n, d)
    dash = "dashed" if og.position == "assumed" else None
    tag = f"{og.type}:{og.id}"
    layer = "A-GLAZ" if og.type == "window" else "A-DOOR"
    add = sh.add
    if not (og.type == "opening" and dash):
        add(Line(a, a2, pen, layer=layer, space="model", tag=tag))
        add(Line(b, b2, pen, layer=layer, space="model", tag=tag))
    if og.type == "window":
        mid, mid2 = _v(a, n, d / 2), _v(b, n, d / 2)
        add(Line(a, b, pen, dash, layer=layer, space="model", tag=tag))
        add(Line(a2, b2, pen, dash, layer=layer, space="model", tag=tag))
        add(Line(mid, mid2, pen, dash, layer=layer, space="model", tag=tag))
        ctx.placer.add_obstacle("window", to_paper(ctx, LineString([a, b2]).buffer(1.0)))
        return
    if og.type == "opening":
        if dash:  # approximate position: the jamb lines go dashed too
            for p, q in ((a, a2), (b, b2)):
                add(Line(p, q, pen, "dashed", layer=layer, space="model", tag=f"{tag}:jamb-approx"))
        ctx.placer.add_obstacle("opening", to_paper(ctx, Polygon([a, b, b2, a2]).buffer(0.5)))
        return
    base, s, u, a0, a1 = door_swing(og)
    w = og.width
    t = S.DOOR_LEAF_IN
    tip = _v(base, s, w)
    leaf = [base, tip, _v(tip, u, t), _v(base, u, t)]
    add(Poly(leaf, True, pen, None, dash, layer="A-DOOR", space="model", tag=tag))
    add(Arc(base, w, a0, a1, S.PEN["swing"] if not dash else pen, dash, layer="A-DOOR", space="model", tag=f"door:{og.id}"))
    sector = _sector(base, w, a0, a1)
    ctx.placer.add_obstacle(f"swing:{og.id}", to_paper(ctx, sector))
    ctx.meta_swing[og.id] = to_paper(ctx, sector)
    ctx.meta_leaf[og.id] = (sh.xf(*base), sh.xf(*tip), sh.xf(*_v(base, u, w)))


def draw_stair(ctx: Ctx, room) -> None:
    """Treads every 10 in, break line and direction arrow with its DN/UP label."""
    poly = ctx.geom.rooms[room.id]
    x0, y0, x1, y1 = poly.bounds
    up = DIRS[room.stair.up]
    vertical = up[0] == 0
    L = (y1 - y0) if vertical else (x1 - x0)
    Wd = (x1 - x0) if vertical else (y1 - y0)
    u0 = (y0 if up[1] > 0 else y1) if vertical else (x0 if up[0] > 0 else x1)  # bottom end
    sgn = (up[1] if vertical else up[0])

    def pt(along, across):
        if vertical:
            return (x0 + across, u0 + sgn * along)
        return (u0 + sgn * along, y0 + across)

    down = room.stair.go == "down"
    cut = L / 2 if down else None  # distance from the bottom end
    gap = 0.9 * ctx.mm_in
    sh = ctx.sheet
    pen = S.PEN["stair"]
    n = int(L // 10)
    for i in range(1, n + 1):
        pos = i * 10
        if pos >= L - 0.5:
            continue
        beyond = down and pos < cut
        if down and abs(pos - cut) < 2 * gap:
            continue
        sh.add(Line(pt(pos, 0), pt(pos, Wd), pen, "fine" if beyond else None, layer="A-FLOR-STRS", space="model", tag=f"tread:{room.id}"))
    if down:
        band = Polygon([pt(cut - 1.6 * ctx.mm_in * 1.4, 0), pt(cut - 1.6 * ctx.mm_in * 1.4, Wd), pt(cut + 1.6 * ctx.mm_in * 1.4, Wd), pt(cut + 1.6 * ctx.mm_in * 1.4, 0)])
        ctx.placer.add_obstacle("break", to_paper(ctx, band))
        zz = 1.7 * ctx.mm_in
        for off in (-gap, gap):
            m = cut + off
            xs = [0.0, Wd * 0.5 - 1.3 * ctx.mm_in, Wd * 0.5 - 0.45 * ctx.mm_in, Wd * 0.5 + 0.45 * ctx.mm_in, Wd * 0.5 + 1.3 * ctx.mm_in, Wd]
            ys = [m, m, m + zz, m - zz, m, m]
            sh.add(Poly([pt(a, b) for a, b in zip(ys, xs)], False, pen * 1.4, layer="A-FLOR-STRS", space="model", tag=f"break:{room.id}"))
    # arrow along the run centre
    inset = 3.0 * ctx.mm_in
    if down:
        a_from, a_to = L - inset, cut + gap + 2.5 * ctx.mm_in
    else:
        a_from, a_to = inset, L - inset
    if abs(a_to - a_from) > 8 * ctx.mm_in:
        c = Wd / 2
        p_from, p_to = pt(a_from, c), pt(a_to, c)
        dirv = (p_to[0] - p_from[0], p_to[1] - p_from[1])
        ln = math.hypot(*dirv)
        dirv = (dirv[0] / ln, dirv[1] / ln)
        hl, hw = 2.4 * ctx.mm_in, 0.7 * ctx.mm_in
        base = (p_to[0] - dirv[0] * hl, p_to[1] - dirv[1] * hl)
        perp = (-dirv[1], dirv[0])
        sh.add(Line(p_from, base, S.PEN["opening"], layer="A-FLOR-STRS", space="model", tag=f"arrow:{room.id}"))
        sh.add(Poly([p_to, _v(base, perp, hw), _v(base, perp, -hw)], True, 0.0, S.INK, layer="A-FLOR-STRS", space="model",
                    tag=f"arrow:{room.id}"))
        ctx.placer.add_obstacle("arrow", to_paper(ctx, LineString([p_from, p_to])), 0.4)
        ctx.meta_stairs[room.id] = (p_from, p_to, vertical)


def stair_label(ctx: Ctx, room) -> None:
    """DESC./MONTE (2.5 mm) beside the arrow tail, inside the stair; else just outside it."""
    if room.id not in ctx.meta_stairs:
        return
    p_from, p_to, vertical = ctx.meta_stairs[room.id]
    s = ctx.tr("stair_down" if room.stair.go == "down" else "stair_up")
    h = S.H["dim"]
    tw = text_width(s, h)
    a, b = ctx.sheet.xf(*p_from), ctx.sheet.xf(*p_to)
    ln = math.hypot(b[0] - a[0], b[1] - a[1])
    d = ((b[0] - a[0]) / ln, (b[1] - a[1]) / ln)
    perp = (-d[1], d[0])
    x0, y0, x1, y1 = to_paper(ctx, ctx.geom.rooms[room.id]).bounds
    half = ((x1 - x0) if vertical else (y1 - y0)) / 2
    rot = 90.0 if vertical else 0.0
    for off in (1.4 + h / 2, half + 1.4 + h / 2):  # inside beside the shaft, then just outside the stair
        for t in [tw / 2 + 1.0 + k * 2.0 for k in range(0, 12)]:
            if t > ln - tw / 2 and off < half:
                break
            for side in (1, -1):
                c = (a[0] + d[0] * t + perp[0] * off * side, a[1] + d[1] * t + perp[1] * off * side)
                if try_text(ctx, Text(c, s, h, "mc", rot, halo=True, layer="A-ANNO-SYMB", tag=f"stairlabel:{room.id}"), clear=0.2):
                    return


def try_text(ctx: Ctx, tx: Text, ignore=(), clear: float = 0.5) -> bool:
    """Place tx (paper mm) as a model-space text when its box is free; False otherwise."""
    b = text_polygon(tx)
    if ctx.placer.is_free(b.buffer(clear) if clear else b, ignore):
        ctx.put_model(tx)
        return True
    return False




def _ellipse(c, a, b, n=28):
    return [(c[0] + a * math.cos(2 * math.pi * i / n), c[1] + b * math.sin(2 * math.pi * i / n)) for i in range(n)]


def draw_fixtures(ctx: Ctx) -> None:
    """Fixture symbols in plan convention at 0.18; rot = compass bearing of the fixture's back."""
    pen = S.PEN["fixture"]
    for fx in ctx.lv.fixtures:
        dw, dd = FIXTURE_DEFAULT[fx.type]
        w = ctx.led.value(fx.w) if fx.w else float(dw)
        d = ctx.led.value(fx.d) if fx.d else float(dd)
        th = math.radians(fx.rot)
        b = (math.sin(th), math.cos(th))  # towards the back
        a = (math.cos(th), -math.sin(th))  # along the back wall
        cx, cy = fx.at

        def loc(u, v):
            return (cx + a[0] * u + b[0] * (d / 2 - v), cy + a[1] * u + b[1] * (d / 2 - v))

        def poly(pts, closed=True, p=pen):
            ctx.sheet.add(Poly(pts, closed, p, None, layer="A-FLOR-FIXT", space="model", tag=f"fixture:{fx.type}"))

        rect_ = [loc(-w / 2, 0), loc(w / 2, 0), loc(w / 2, d), loc(-w / 2, d)]
        t = fx.type
        if t == "toilet":
            tank = 0.3 * d
            poly([loc(-w / 2, 0), loc(w / 2, 0), loc(w / 2, tank), loc(-w / 2, tank)])
            pts = []
            for i in range(29):
                ang = math.pi * i / 28
                pts.append(loc(-(w * 0.46) * math.cos(ang), tank + (d - tank) * 0.5 + (d - tank) * 0.5 * math.sin(ang) * 1.0))
            poly([loc(-w * 0.46, tank + (d - tank) * 0.5)] + pts[1:-1] + [loc(w * 0.46, tank + (d - tank) * 0.5)], False)
            poly([loc(-w * 0.46, tank + (d - tank) * 0.5), loc(-w * 0.46, tank)], False)
            poly([loc(w * 0.46, tank + (d - tank) * 0.5), loc(w * 0.46, tank)], False)
        elif t == "sink":
            poly(rect_)
            poly([loc(u_, v_) for u_, v_ in _ellipse((0, d * 0.55), w * 0.3, d * 0.28)])
            poly([loc(u_, v_) for u_, v_ in _ellipse((0, 2.2), 0.9, 0.9, 10)])
        elif t == "tub":
            poly(rect_)
            r = min(w, d) * 0.12
            inner = Polygon(rect_).buffer(-2.2).buffer(-r).buffer(r)
            ctx.sheet.add(Poly(list(inner.exterior.coords)[:-1], True, pen, None, layer="A-FLOR-FIXT", space="model", tag="fixture:tub"))
            poly([loc(u_, v_) for u_, v_ in _ellipse((-w / 2 + 6 if w >= d else 0, d / 2 if w >= d else 6), 1.1, 1.1, 10)])
        elif t == "shower":
            poly(rect_)
            poly([loc(-w / 2, 0), loc(w / 2, d)], False, 0.13)
            poly([loc(-w / 2, d), loc(w / 2, 0)], False, 0.13)
            poly([loc(u_, v_) for u_, v_ in _ellipse((0, d / 2), 1.3, 1.3, 10)])
        elif t == "range":
            poly(rect_)
            rb = min(w, d) * 0.13
            for du, dv in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                poly([loc(w * 0.22 * du + u_, d * 0.5 + d * 0.2 * dv + v_) for u_, v_ in _ellipse((0, 0), rb, rb, 14)])
        elif t in ("washer", "dryer"):
            poly(rect_)
            poly([loc(u_, v_) for u_, v_ in _ellipse((0, d * 0.55), min(w, d) * 0.32, min(w, d) * 0.32, 20)])
        else:
            poly(rect_)
            if t == "fridge":
                px = (ctx.sheet.xf(*loc(0, d / 2)))
                ctx.put_model(Text(px, "RÉF." if ctx.lang != "en" else "REF.", 2.0, "mc", 90.0 if abs(math.sin(th)) > 0.5 else 0.0,
                                   layer="A-FLOR-FIXT", tag="fixture:fridge"))
        ctx.placer.add_obstacle("fixture", to_paper(ctx, Polygon(rect_)))


def draw_labels(ctx: Ctx) -> None:
    """Free-text labels for unmeasured zones and notes; multi-line, centred on `at`."""
    lang = "fr" if ctx.lang == "bi" else ctx.lang
    for lab in ctx.lv.labels:
        if lab.style == "open" and ctx.sl == "permit":
            continue
        txt = (lab.text.get(lang) or lab.text.get("en") or "") if lab.text else ""
        lines = txt.split("\n")
        h = S.H["note"]
        pitch = h * S.PITCH
        cx, cy = ctx.sheet.xf(*lab.at)
        color = S.GREY if lab.style == "unmeasured" else S.INK
        style = "normal" if lab.style == "note" else "italic"
        for i, ln in enumerate(lines):
            y = cy + (i - (len(lines) - 1) / 2) * pitch
            ctx.put_model(Text((cx, y), ln, h, "mc", 0.0, "regular", style, color, True, layer="A-ANNO-TEXT", tag="label"))


FURN_NAME = {
    "bed": ("LIT", "BED"), "sofa": ("SOFA", "SOFA"), "table": ("TABLE", "TABLE"), "chair": ("CH.", "CHAIR"),
    "desk": ("BUREAU", "DESK"), "dresser": ("COMMODE", "DRESSER"), "wardrobe": ("ARMOIRE", "WARDROBE"),
    "bookcase": ("BIBLIO.", "BOOKCASE"), "piano": ("PIANO", "PIANO"), "other": ("", ""),
}


def draw_furniture(ctx: Ctx) -> None:
    """Furniture outlines at the fine pen on A-FURN: bed pillows, sofa back and arms, chair back; others a box and a name."""
    pen = S.PEN["furniture"]
    lang = "fr" if ctx.lang == "bi" else ctx.lang
    for f in ctx.lv.furniture:
        w, d = ctx.led.value(f.w), ctx.led.value(f.d)
        loc = item_frame(f.at, f.rot, w, d)
        dash = "fine" if f.status == "existing" else None

        def poly(pts, closed=True):
            ctx.sheet.add(Poly(pts, closed, pen, None, dash, layer="A-FURN", space="model", tag=f"furniture:{f.id}"))

        rect_ = [loc(-w / 2, 0), loc(w / 2, 0), loc(w / 2, d), loc(-w / 2, d)]
        poly(rect_)
        if f.type == "bed":
            n = 2 if w >= 48 else 1
            pw, gap = (w - 4 - (n - 1) * 2) / n, 2
            for i in range(n):
                u0 = -w / 2 + 2 + i * (pw + gap)
                poly([loc(u0, 2), loc(u0 + pw, 2), loc(u0 + pw, 10), loc(u0, 10)])
            poly([loc(-w / 2, d * 0.4), loc(w / 2, d * 0.4)], False)
        elif f.type == "sofa":
            bk, arm = min(8.0, d * 0.3), min(6.0, w * 0.15)
            poly([loc(-w / 2, bk), loc(w / 2, bk)], False)
            poly([loc(-w / 2 + arm, bk), loc(-w / 2 + arm, d)], False)
            poly([loc(w / 2 - arm, bk), loc(w / 2 - arm, d)], False)
        elif f.type == "chair":
            poly([loc(-w / 2, min(3.0, d * 0.2)), loc(w / 2, min(3.0, d * 0.2))], False)
        name = (f.label.get(lang) or f.label.get("en") or "") if f.label else FURN_NAME[f.type][0 if lang == "fr" else 1]
        fp = to_paper(ctx, Polygon(rect_))
        if name and f.type not in ("chair",):
            c = ctx.sheet.xf(*loc(0, d * 0.65 if f.type in ("bed", "sofa") else d / 2))
            tx = Text(c, name, S.H["label"], "mc", 0.0, layer="A-FURN", tag=f"furniture:{f.id}")
            if text_polygon(tx).within(fp):
                ctx.put_model(tx)
        ctx.placer.add_obstacle("furniture", fp)
