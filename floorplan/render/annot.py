"""Annotation: room tags, room dimensions, BUILDER dimension strings, callouts, marks, wall-type tags."""
from __future__ import annotations

import math

import shapely

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import LinearRing
from shapely.ops import nearest_points, polylabel, unary_union
from shapely.prepared import prep

from . import styles as S
from ..geometry import OpeningGeom
from ..i18n import abbreviate, colon
from ..units import fmt_area_ft2, fmt_area_m2, fmt_ftin, fmt_m
from .ctx import Ctx
from .drawplan import to_paper, try_text
from .layout import Circle, Dim, Line, Poly, Text, dim_fits, dim_geometry
from .metrics import text_metrics, text_width
from .placer import rect, text_polygon

LINE_GAP = 1.0
TAG_PAD = 0.6


# ------------------------------------------------------------------ helpers
def _lang(ctx: Ctx) -> str:
    return "fr" if ctx.lang == "bi" else ctx.lang


def size_text(ctx: Ctx, w_id: str, h_id: str | None) -> str:
    """Opening size 'W x H' in the sheet language (values from the ledger, * when open)."""
    def one(lid: str) -> str:
        v, o = ctx.led.value(lid), ctx.is_open(lid)
        if ctx.ftin:
            return fmt_ftin(v) + ("*" if o else "")
        s = fmt_m(v, "fr") + ("*" if o else "")
        return s + (f" [{fmt_ftin(v)}]" if ctx.lang == "bi" else "")
    return one(w_id) + (f" x {one(h_id)}" if h_id else "")


def _line_m(ctx: Ctx, p1, p2, pen, dash=None, layer="A-ANNO-SYMB", tag=""):
    ctx.sheet.add(Line(ctx.sheet.inv(*p1), ctx.sheet.inv(*p2), pen, dash, layer=layer, space="model", tag=tag))


def _poly_m(ctx: Ctx, pts, closed, pen, fill=None, layer="A-ANNO-SYMB", tag=""):
    ctx.sheet.add(Poly([ctx.sheet.inv(*p) for p in pts], closed, pen, fill, layer=layer, space="model", tag=tag))


def _circle_m(ctx: Ctx, c, r_mm, pen, fill=None, layer="A-ANNO-SYMB", tag=""):
    ctx.sheet.add(Circle(ctx.sheet.inv(*c), r_mm * ctx.mm_in, pen, fill, layer=layer, space="model", tag=tag))


# ------------------------------------------------------------------ room tags
def _dims_lines(ctx: Ctx, room) -> list[str]:
    ids = room.dims or []
    if not ids:
        return []
    vals = [(ctx.led.value(i), ctx.is_open(i)) for i in ids]
    lang = ctx.lang
    if ctx.ftin or (ctx.sl == "sketch" and lang != "fr"):
        f = [fmt_ftin(v) + ("*" if o else "") for v, o in vals]
        return [f"{f[0]} x {f[1]}" if len(f) == 2 else f"{ctx.tr('width_abbr')} {f[0]}"]
    f = [fmt_m(v, "fr") + ("*" if o else "") for v, o in vals]
    main = f"{f[0]} x {f[1]} m" if len(f) == 2 else f"{ctx.tr('width_abbr')} {f[0]} m"
    if lang == "bi":
        ft = [fmt_ftin(v) for v, _ in vals]
        return [main, "[" + " x ".join(ft) + "]"]
    return [main]


def _area_line(ctx: Ctx, room) -> str:
    a = ctx.geom.rooms[room.id].area
    # area rests only on the room's own legs
    star = "*" if any(ctx.is_open(leg[1]) for leg in room.path) else ""
    m2 = fmt_area_m2(a, "fr" if ctx.lang in ("fr", "bi") else "en")
    if ctx.ftin:
        s = f"{fmt_area_ft2(a)} {ctx.tr('ft2')}{star}"
        return s + (f" [{m2} m²]" if ctx.sl == "builder" else "")
    s = f"{m2} m²{star}"
    return s + (f" [{fmt_area_ft2(a)} ft²]" if ctx.lang == "bi" else "")


def _hsp_line(ctx: Ctx, room) -> str | None:
    cid = room.ceiling or ctx.lv.ceiling
    if not cid:
        return None
    e = ctx.led.entry(cid)
    lang = _lang(ctx)
    tx = e.text_imp if ctx.ftin and e.text_imp else e.text
    if tx and (tx.get(lang) or tx.get("en")):
        txt = tx.get(lang) or tx.get("en")
    else:
        v = ctx.led.value(cid)
        txt = (fmt_ftin(v) if ctx.ftin else fmt_m(v, "fr") + " m") + ("*" if ctx.is_open(cid) else "")
    return f"{ctx.tr('hsp')} {txt}"


def is_rect(ctx: Ctx, room) -> bool:
    """True when the room polygon is an axis-aligned rectangle."""
    p = ctx.geom.rooms[room.id]
    return abs(p.envelope.area - p.area) < 0.5 and len(p.exterior.coords) == 5


def total_area_text(ctx: Ctx) -> str:
    """'Superficie globale (intérieure) : 65,8 m²' from the envelope interior polygon."""
    a = ctx.geom.envelope.area
    lv = ctx.lv
    ids = [i for v in [*lv.envelope.origin, *(v for _, v in lv.envelope.path)] for i in ctx.led.ids_in(v)]
    star = "*" if any(ctx.is_open(i) for i in ids) else ""
    m2 = fmt_area_m2(a, "fr" if ctx.lang in ("fr", "bi") else "en")
    if ctx.ftin:
        val = f"{fmt_area_ft2(a)} {ctx.tr('ft2')}{star}"
    else:
        val = f"{m2} m²{star}" + (f" [{fmt_area_ft2(a)} ft²]" if ctx.lang == "bi" else "")
    return f"{ctx.tr('total_area')}{colon(ctx.lang)} {val}"


def tag_variants(ctx: Ctx, room) -> list[list[tuple[str, float, str, str, str]]]:
    """Candidate tag texts, richest first: lists of (text, h_mm, weight, style, colour)."""
    lang = _lang(ctx)
    name = room.name.get(lang) or room.name.get("en") or room.id
    sl = ctx.sl
    sl_ = ctx.sl
    dims = _dims_lines(ctx, room) if (is_rect(ctx, room) and len(room.dims or []) == 2) or (
        sl_ == "sketch" and room.kind == "stair") else []
    kind = room.kind

    def make(nm: str, hn: float, hs: float, full: bool = True):
        if sl == "sketch":
            ls = [(room.id, S.H["sketch_code"] * hs / 2.5 if hs < 2.5 else S.H["sketch_code"], "regular", "normal", S.GREY),
                  (nm, hn, "bold", "normal", S.INK)]
            ls += [(d, hs, "regular", "normal", S.INK) for d in dims]
            return ls
        ls = []
        if sl == "builder":
            ls.append((room.id, S.H["sketch_code"], "regular", "normal", S.GREY))
        ls.append((nm.upper(), hn, "bold", "normal", S.INK))
        if kind == "closet" and sl != "sketch" or kind == "stair" and sl != "sketch":
            return ls
        ls += [(d, hs, "regular", "normal", S.INK) for d in dims]
        if kind == "stair" or not full:
            return ls
        ls.append((_area_line(ctx, room), hs, "regular", "normal", S.INK))
        if sl in ("permit", "builder"):
            h = _hsp_line(ctx, room)
            if h:
                ls.append((h, hs, "regular", "normal", S.INK))
        return ls

    hn = S.H["sketch_name"] if sl == "sketch" else S.H["room"]
    hs = S.H["sketch_dim"] if sl == "sketch" else S.H["note"]
    ab = abbreviate(name, lang)
    out = [make(name, hn, hs), make(name, 2.5 if sl != "sketch" else 3.0, 2.2), make(ab, 2.5 if sl != "sketch" else 3.0, 2.2)]
    out.append(make(ab, 2.5, 2.2, full=False))
    out.append([(ab.upper() if sl != "sketch" else ab, 2.2, "bold", "normal", S.INK)])
    return out


def _stack(lines, cx, cy, rot90: bool):
    """Positions for lines stacked by their ink extents, centred on (cx, cy); returns (pos, w, h)."""
    ink = []
    for l in lines:
        _, _, top, _, bot = text_metrics(l[0], l[1], l[2], l[3])
        ink.append((-top, max(bot, 0.0)))
    ht = sum(a_ + d_ for a_, d_ in ink) + LINE_GAP * (len(lines) - 1)
    wd = max(text_width(l[0], l[1], l[2], l[3]) for l in lines)
    pos = []
    cur = (cx if rot90 else cy) - ht / 2
    for (asc, desc) in ink:
        base = cur + asc
        pos.append((base, cy) if rot90 else (cx, base))
        cur = base + desc + LINE_GAP
    return (pos, ht, wd) if rot90 else (pos, wd, ht)


def _emit_tag(ctx: Ctx, room, lines, pos, rot90, halo: bool = False):
    for (s, h, w, st, col), p in zip(lines, pos):
        ctx.put_model(Text(p, s, h, "bc", 90.0 if rot90 else 0.0, w, st, col, halo, layer="A-AREA-IDEN", tag=f"tag:{room.id}"))


def place_room_tag(ctx: Ctx, room) -> None:
    """Inside the room (polylabel, then grid; rotate, shrink, abbreviate, code only), else outside with a short leader."""
    poly = to_paper(ctx, ctx.geom.rooms[room.id])
    avail = poly.buffer(-1.5)
    variants = tag_variants(ctx, room)
    if room.kind == "stair":
        lang = _lang(ctx)
        name = room.name.get(lang) or room.name.get("en") or room.id
        dims = _dims_lines(ctx, room) if ctx.sl == "sketch" else []
        sk = ctx.sl == "sketch"
        nm, hn, hd = (name, 3.0, 2.5) if sk else (abbreviate(name, lang).upper(), 2.5, 2.2)
        two = [(nm, hn, "bold", "normal", S.INK)] + [(d, hd, "regular", "normal", S.INK) for d in dims]
        one = [(" ".join([nm] + dims), hd, "bold", "normal", S.INK)]
        x0, y0, x1, y1 = poly.bounds
        rot = (y1 - y0) >= (x1 - x0)  # text runs along the flight
        if _tag_inside(ctx, room, poly, poly.buffer(-0.3), [(two, rot), (one, rot)], halo=True):
            return
        _tag_outside(ctx, room, poly, one) or _tag_outside(ctx, room, poly, variants[4])
        return
    if ctx.sl == "sketch":  # rotate before shrinking
        order = [(v, r) for v in variants[:4] for r in (False, True)] + [(variants[4], False), (variants[4], True)]
    else:  # shrink and abbreviate first, rotate last
        order = [(v, False) for v in variants[:5]] + [(v, True) for v in variants[:5]]
    code = [(room.id, S.H["sketch_code"], "regular", "normal", S.GREY)]
    if ctx.sl in ("sketch", "builder"):
        order += [(code, False), (code, True)]
    if not avail.is_empty and _tag_inside(ctx, room, poly, avail, order):
        return
    if _tag_outside(ctx, room, poly, variants[2]) or _tag_outside(ctx, room, poly, variants[4]):
        return
    if not avail.is_empty and _tag_inside(ctx, room, poly, avail, [(code, False), (code, True)]):
        return
    _tag_outside(ctx, room, poly, variants[4], reach=90.0)


def _tag_inside(ctx: Ctx, room, poly, avail, order, halo: bool = False) -> bool:
    pl = ctx.placer
    pa = prep(avail)
    c0 = polylabel(poly, 0.2)
    cand = []
    if room.tag_at:
        cand.append(ctx.sheet.xf(*room.tag_at))
    cand.append((c0.x, c0.y))
    x0, y0, x1, y1 = avail.bounds
    pts = []
    y = y0
    while y <= y1:
        x = x0
        while x <= x1:
            pts.append((x, y))
            x += 1.0
        y += 1.0
    pts = [p for p in pts if pa.contains(Point(p))]
    pts.sort(key=lambda p: (p[0] - c0.x) ** 2 + (p[1] - c0.y) ** 2)
    cand += pts
    for lines, rot90 in order:
        _, w, h = _stack(lines, 0, 0, rot90)
        for cx, cy in cand:
            b = rect(cx - w / 2 - TAG_PAD, cy - h / 2 - TAG_PAD, cx + w / 2 + TAG_PAD, cy + h / 2 + TAG_PAD)
            if pa.contains(b) and pl.is_free(b):
                pos, _, _ = _stack(lines, cx, cy, rot90)
                _emit_tag(ctx, room, lines, pos, rot90, halo)
                return True
    return False


def leader_ok(ctx: Ctx, seg: LineString) -> bool:
    """True when a leader crosses no registered text box and no other leader or dimension line."""
    if any(b.intersects(seg) for _, b in ctx.placer.texts):
        return False
    return not any(k in ("leader", "dim") and g.intersects(seg) for k, g in ctx.placer.obstacles)


def _tag_outside(ctx: Ctx, room, poly, lines, reach: float = 45.0) -> bool:
    """Cheapest free spot outside every room: short leader, little poche, no text or other room crossed."""
    pl = ctx.placer
    others = [to_paper(ctx, r) for rid, r in ctx.geom.rooms.items() if rid != room.id]
    others_u = unary_union(others) if others else Polygon()
    rooms_p = unary_union([poly] + others).buffer(0.8)
    wall_u = unary_union([g for k, g in pl.obstacles if k == "wall"] or [Polygon()])
    room_in = poly.buffer(-0.8)
    if room_in.is_empty:
        room_in = poly
    _, w, h = _stack(lines, 0, 0, False)
    zx0, zy0, zx1, zy1 = ctx.zone
    x0, y0, x1, y1 = poly.bounds
    best = None
    step = 2.0 if reach <= 45 else 3.0
    cy = y0 - reach
    while cy <= y1 + reach:
        cx = x0 - reach
        while cx <= x1 + reach:
            b = rect(cx - w / 2 - TAG_PAD, cy - h / 2 - TAG_PAD, cx + w / 2 + TAG_PAD, cy + h / 2 + TAG_PAD)
            bx0, by0, bx1, by1 = b.bounds
            if bx0 > zx0 and by0 > zy0 and bx1 < zx1 and by1 < zy1 and not b.intersects(rooms_p) and pl.is_free(b.buffer(0.6)):
                q_in, q_box = nearest_points(room_in, b)
                seg = LineString([(q_box.x, q_box.y), (q_in.x, q_in.y)])
                cost = seg.length + 3.0 * seg.intersection(wall_u).length + 8.0 * seg.intersection(others_u).length
                if (best is None or cost < best[0]) and leader_ok(ctx, seg):
                    best = (cost, cx, cy, seg, q_in)
            cx += step
        cy += step
    if not best:
        return False
    _, cx, cy, seg, q_in = best
    pos, _, _ = _stack(lines, cx, cy, False)
    _emit_tag(ctx, room, lines, pos, False)
    _line_m(ctx, seg.coords[0], seg.coords[1], S.PEN["leader"], layer="A-AREA-IDEN", tag=f"leader:{room.id}")
    _circle_m(ctx, (q_in.x, q_in.y), 0.5, 0.13, S.INK, layer="A-AREA-IDEN", tag=f"leader:{room.id}")
    pl.add_obstacle("leader", seg, 0.3)
    return True


def place_labels(ctx: Ctx) -> None:
    """Fixed-position labels through the registry: nearest free spot to `at` inside the same room or zone."""
    lang = _lang(ctx)
    pl = ctx.placer
    regions = [(to_paper(ctx, p), p) for p in [*ctx.geom.rooms.values(), *ctx.geom.zones]]
    env_p = to_paper(ctx, ctx.geom.envelope)
    for lab in ctx.lv.labels:
        if lab.style == "open" and ctx.sl == "permit" or not lab.text:
            continue
        txt = lab.text.get(lang) or lab.text.get("en") or ""
        if not txt:
            continue
        h = S.H["note"]
        color = S.GREY if lab.style == "unmeasured" else S.INK
        st = "normal" if lab.style == "note" else "italic"
        lines = [(ln, h, "regular", st, color) for ln in txt.split("\n")]
        c0 = ctx.sheet.xf(*lab.at)
        home = next((rp for rp, p in regions if p.contains(Point(lab.at))), None)
        _, w, ht = _stack(lines, 0, 0, False)
        cand = [(c0[0], c0[1])]
        for r in [1.5 * k for k in range(1, 60)]:
            for ang in range(0, 360, 15):
                cand.append((c0[0] + r * math.cos(math.radians(ang)), c0[1] + r * math.sin(math.radians(ang))))
        chosen = None
        for region in (home, env_p):
            if region is None:
                continue
            pa = prep(region.buffer(-0.4))
            for cx, cy in cand:
                b = rect(cx - w / 2 - 0.4, cy - ht / 2 - 0.4, cx + w / 2 + 0.4, cy + ht / 2 + 0.4)
                if pa.contains(b) and pl.is_free(b):
                    chosen = (cx, cy)
                    break
            if chosen:
                break
        cx, cy = chosen or c0
        pos, _, _ = _stack(lines, cx, cy, False)
        for (s, hh, w_, st_, col), p in zip(lines, pos):
            ctx.put_model(Text(p, s, hh, "bc", 0.0, w_, st_, col, True, layer="A-ANNO-TEXT", tag="label"))


# ------------------------------------------------------------------ room dimensions (PERMIT, BUILDER)
def _leg_dim(ctx: Ctx, room, i: int, lid: str, off_mm: float = S.DIM["room_in"]) -> Dim | None:
    poly = ctx.geom.rooms[room.id]
    co = list(poly.exterior.coords)
    p0, p1 = co[i], co[i + 1]
    d = room.path[i][0]
    ring = LinearRing(co)
    u = (p1[0] - p0[0], p1[1] - p0[1])
    ln = math.hypot(*u)
    if ln < 1e-6:
        return None
    u = (u[0] / ln, u[1] / ln)
    n_out = (u[1], -u[0]) if ring.is_ccw else (-u[1], u[0])
    inward = (-n_out[0], -n_out[1])
    if abs(ln - ctx.led.value(lid)) > 0.01:  # value is not the drawn length: stays on the tag only
        return None
    horiz = d in ("E", "W")
    off = off_mm * (math.copysign(1, inward[1]) if horiz else math.copysign(1, inward[0]))
    txt = ctx.val(ctx.led.value(lid), ctx.is_open(lid))
    return Dim(p0, p1, "h" if horiz else "v", off, txt, ctx.is_open(lid), layer="A-ANNO-DIMS", space="model",
               tag=f"dim:{room.id}:{lid}")


def _dim_hits(ctx: Ctx, d: Dim) -> tuple[int, Text, list]:
    """Collisions of the dimension line, extension lines and text (extension lines may lie on the wall face, so
    swing sectors are eroded 0.3 mm for them)."""
    g = dim_geometry(d, ctx.sheet)
    line = LineString(list(g.line)).buffer(0.3)
    exts = [LineString(list(e)).buffer(0.25) for e in g.ext]
    swings = [(k, o) for k, o in ctx.placer.obstacles if k.startswith("swing:")]
    skip = ("wall", "dim", "arrow") + tuple(k for k, _ in swings)
    hits = 0 if ctx.placer.is_free(line, ("wall", "dim", "arrow")) else 1
    for e in exts:
        hits += 0 if ctx.placer.is_free(e, skip) and not any(o.buffer(-0.3).intersects(e) for _, o in swings) else 1
    tb = text_polygon(g.text)
    hits += 0 if ctx.placer.is_free(tb.buffer(0.5)) else 1
    return hits, g.text, [line] + exts


def commit_dim(ctx: Ctx, d: Dim) -> None:
    """Add the Dim to the sheet and register its text and lines with the placer."""
    g = dim_geometry(d, ctx.sheet)
    ctx.sheet.add(d)
    ctx.placer.add_text(g.text)
    for e in [g.line] + list(g.ext) + ([g.leader] if g.leader else []):
        ctx.placer.add_obstacle("dim", LineString(list(e)), 0.3)


def _leg_side(ctx: Ctx, room, i: int):
    """(envelope side, lo, hi) when leg i lies on an envelope face, else (None, lo, hi)."""
    co = list(ctx.geom.rooms[room.id].exterior.coords)
    p, q = co[i], co[i + 1]
    x0, y0, x1, y1 = ctx.geom.envelope.bounds
    if abs(p[1] - q[1]) < 1e-6:
        side = "S" if abs(p[1] - y0) < 1.0 else "N" if abs(p[1] - y1) < 1.0 else None
        lo, hi = sorted((p[0], q[0]))
    else:
        side = "W" if abs(p[0] - x0) < 1.0 else "E" if abs(p[0] - x1) < 1.0 else None
        lo, hi = sorted((p[1], q[1]))
    return side, lo, hi


def _given_outside(ctx: Ctx, room, i: int) -> bool:
    """True when leg i lies on an envelope face whose exterior string already gives that value."""
    side, lo, hi = _leg_side(ctx, room, i)
    return side is not None and any(s == side and abs(a - lo) < 0.3 and abs(b - hi) < 0.3 for s, a, b in ctx.ext_dims)


def room_dims(ctx: Ctx, room) -> None:
    """One dimension per ledger id in room.dims, inside the room and clear of swings, fixtures and text.

    Tries the 5 mm offset on every leg carrying the id, then deeper offsets; BUILDER skips a value
    already given by an exterior string.
    """
    room_p = to_paper(ctx, ctx.geom.rooms[room.id])
    if ctx.sl == "sketch" and is_rect(ctx, room):
        return  # sketch: rectangles carry W x D on the tag
    for lid in room.dims or []:
        legs = [i for i, (_, v) in enumerate(room.path) if v == lid and _leg_dim(ctx, room, i, lid) is not None]
        if not legs:
            continue
        if ctx.sl == "builder" and any(_given_outside(ctx, room, i) for i in legs):
            continue
        if ctx.sl == "permit":  # legs on the envelope go outside, one shared offset per side
            env = next((i for i in legs if _leg_side(ctx, room, i)[0]), None)
            if env is not None:
                d = _leg_dim(ctx, room, env, lid)
                side = _leg_side(ctx, room, env)[0]
                ext_mm = ctx.led.value(ctx.lv.exterior_wall) * ctx.k
                d.offset_mm = (-1.0 if side in ("S", "W") else 1.0) * (ext_mm + S.DIM["permit_out"])
                _fit_dim(ctx, d, 0.0)
                commit_dim(ctx, d)
                ctx.ext_dims.append((side, *_leg_side(ctx, room, env)[1:]))
                continue
        best = None
        for step in range(0, 25):
            off = S.DIM["room_in"] + 2.5 * step
            for i in legs:
                d = _leg_dim(ctx, room, i, lid, off)
                if d is None:
                    continue
                if not dim_fits(d, ctx.sheet):
                    d.place, d.raise_mm = "raise", S.DIM["raise"]
                g = dim_geometry(d, ctx.sheet)
                if not room_p.buffer(0.4).contains(LineString(list(g.line))):
                    continue
                hits = _dim_hits(ctx, d)[0] + (0 if room_p.buffer(0.4).contains(text_polygon(g.text)) else 1)
                if best is None or hits < best[0]:
                    best = (hits, d)
                if hits == 0:
                    break
            if best and best[0] == 0:
                break
        if best and best[0] > 0:  # nothing fully clean: keep the text free, inside this room; extension lines may graze
            found = None
            for step in range(0, 25):
                off = S.DIM["room_in"] + 2.5 * step
                for i in legs:
                    d = _leg_dim(ctx, room, i, lid, off)
                    if d is None or not room_p.buffer(0.4).contains(LineString(list(dim_geometry(d, ctx.sheet).line))):
                        continue
                    opts = [("mid", 0.0, 0.0)] if dim_fits(d, ctx.sheet) else []
                    opts += [("raise", r_, s_) for r_ in (S.DIM["raise"], S.DIM["raise"] + 3.0)
                             for s_ in [0.0] + [q * k for k in range(1, 12) for q in (3.0, -3.0)]]
                    for pl_, r_, s_ in opts:
                        d.place, d.raise_mm, d.shift_mm = pl_, r_, s_
                        tp = text_polygon(dim_geometry(d, ctx.sheet).text)
                        if room_p.buffer(0.4).contains(tp) and ctx.placer.is_free(tp.buffer(0.5)):
                            found = d
                            break
                    if found:
                        break
                if found:
                    break
            if found:
                best = (0.5, found)
        if best and best[0] > 0 and ctx.sl == "sketch":  # cannot clear a swing inside: go outside (not on the S side: scale bar)
            for i in legs:
                side = _leg_side(ctx, room, i)[0]
                if side in ("E", "W", "N"):
                    d = _leg_dim(ctx, room, i, lid)
                    ext_mm = ctx.led.value(ctx.lv.exterior_wall) * ctx.k
                    d.offset_mm = (-1.0 if side == "W" else 1.0) * (ext_mm + 7.0)
                    _fit_dim(ctx, d, 0.0)
                    best = (0, d)
                    break
        if best:
            commit_dim(ctx, best[1])


# ------------------------------------------------------------------ BUILDER dimension strings
def _spans_side(ctx: Ctx, side: str):
    """Points and coverage spans (lo, hi, ledger id or None) along one envelope side."""
    g = ctx.geom
    x0, y0, x1, y1 = g.envelope.bounds
    horiz = side in ("S", "N")
    ref = {"S": y0, "N": y1, "W": x0, "E": x1}[side]
    lo_e, hi_e = (x0, x1) if horiz else (y0, y1)
    ax = 0 if horiz else 1
    cx = 1 - ax
    pts = {lo_e, hi_e}
    spans: list[tuple[float, float, str | None]] = []
    edges = []
    for r in ctx.lv.rooms:
        co = list(g.rooms[r.id].exterior.coords)
        for i in range(len(co) - 1):
            p, q = co[i], co[i + 1]
            if abs(p[cx] - ref) < 1.0 and abs(q[cx] - ref) < 1.0 and abs(p[ax] - q[ax]) > 1.0:
                lo, hi = sorted((p[ax], q[ax]))
                pts.update((lo, hi))
                edges.append((lo, hi))
                v = r.path[i][1]
                spans.append((lo, hi, v if isinstance(v, str) and v in ctx.led else None))
    edges.sort()
    for (a_lo, a_hi), (b_lo, b_hi) in zip(edges, edges[1:]):
        if b_lo > a_hi + 0.01:
            spans.append((a_hi, b_lo, ctx.lv.partition if abs((b_lo - a_hi) - ctx.led.value(ctx.lv.partition)) < 0.01 else None))
    for o, og in zip(ctx.lv.openings, g.openings):
        if og.position != "measured":
            continue
        if abs(og.normal[ax]) < 0.5 and (og.normal[cx] > 0) == (side in ("N", "E")):
            if abs(og.a[cx] - ref) < 1.0:
                lo, hi = sorted((og.a[ax], og.b[ax]))
                pts.update((lo, hi))
                spans.append((lo, hi, o.width))
    return horiz, ref, sorted(pts), spans


def _merge(pts, tol=0.3):
    out = []
    for p in pts:
        if not out or p - out[-1] > tol:
            out.append(p)
    return out


def builder_dims(ctx: Ctx) -> None:
    """Two-tier dimension strings outside each side of the envelope."""
    ext_mm = ctx.led.value(ctx.lv.exterior_wall) * ctx.k
    for side in ("S", "N", "W", "E"):
        horiz, ref, pts, spans = _spans_side(ctx, side)
        pts = _merge(pts)
        sign = -1.0 if side in ("S", "W") else 1.0
        for tier, off in ((1, ext_mm + S.DIM["tier1"]), (2, ext_mm + S.DIM["tier2"])):
            seq = pts if tier == 1 else [pts[0], pts[-1]]
            if tier == 2 and len(pts) == 2:
                continue
            for a, b in zip(seq, seq[1:]):
                if tier == 1:
                    lid = next((lid for lo, hi, lid in spans if abs(lo - a) < 0.01 and abs(hi - b) < 0.01 and lid), None)
                    op = ctx.computed_open(b - a, lid)
                else:
                    want = ("E", "W") if horiz else ("N", "S")
                    lid = next((v for d, v in ctx.lv.envelope.path if d in want and isinstance(v, str) and v in ctx.led
                                and abs(ctx.led.value(v) - (b - a)) < 0.01), None)
                    op = ctx.computed_open(b - a, lid)
                p1 = (a, ref) if horiz else (ref, a)
                p2 = (b, ref) if horiz else (ref, b)
                d = Dim(p1, p2, "h" if horiz else "v", sign * off, ctx.val(b - a, op), op, layer="A-ANNO-DIMS",
                        space="model", tag=f"dim:{side}{tier}")
                _fit_dim(ctx, d, b - a)
                commit_dim(ctx, d)
                ctx.ext_dims.append((side, a, b))


def _fit_dim(ctx: Ctx, d: Dim, length_in: float) -> None:
    """Text mid-span if it fits and is free, else raised/shifted with a leader; drops the [alt units] as a last resort."""
    for attempt in (0, 1):
        if attempt == 1:
            if " [" not in d.text:
                break
            star = "*" if d.text.endswith("*") else ""
            d.text = d.text.split(" [")[0] + star
        d.place, d.raise_mm, d.shift_mm = "mid", 0.0, 0.0
        if dim_fits(d, ctx.sheet) and _dim_hits(ctx, d)[0] == 0:
            return
        for raise_mm in (S.DIM["raise"], S.DIM["raise"] + 3.0, S.DIM["raise"] + 6.0):
            for shift in [0.0] + [s_ * k for k in range(1, 15) for s_ in (3.0, -3.0)]:
                d.place, d.raise_mm, d.shift_mm = "raise", raise_mm, shift
                if ctx.placer.is_free(text_polygon(dim_geometry(d, ctx.sheet).text).buffer(0.5)):
                    return
    d.place, d.raise_mm, d.shift_mm = "raise", S.DIM["raise"], 0.0


# ------------------------------------------------------------------ callouts and marks
def _exterior(ctx: Ctx, og: OpeningGeom) -> bool:
    mid = ((og.a[0] + og.b[0]) / 2, (og.a[1] + og.b[1]) / 2)
    ext_t = ctx.led.value(ctx.lv.exterior_wall)
    probe = Point(mid[0] + og.normal[0] * (og.depth + 2), mid[1] + og.normal[1] * (og.depth + 2))
    return not ctx.geom.envelope.buffer(ext_t + 0.3, join_style="mitre").contains(probe)


def window_callouts(ctx: Ctx) -> None:
    """FEN. w x h H outside the wall, parallel to it, centred on the window."""
    for o, og in zip(ctx.lv.openings, ctx.geom.openings):
        if og.type != "window" or ctx.assumed_size(o.width, o.height):
            continue
        s = f"{ctx.tr('win_abbr')} {size_text(ctx, o.width, o.height)}" + (" H" if o.height else "")
        mid = ((og.a[0] + og.b[0]) / 2, (og.a[1] + og.b[1]) / 2)
        n = og.normal
        ext = _exterior(ctx, og)
        base = ctx.sheet.xf(mid[0] + n[0] * og.depth, mid[1] + n[1] * og.depth) if ext else ctx.sheet.xf(*mid)
        sgn = 1.0 if ext else -1.0
        nx, ny = n[0] * sgn, -n[1] * sgn  # paper-space outward-of-anchor normal
        h = S.H["dim"]
        along = (-ny, nx)
        placed = False
        for gap in (1.6, 6.0, 10.0):
            for sh in (0, 3, -3, 6, -6, 10, -10, 14, -14):
                cx, cy = base[0] + nx * gap + along[0] * sh, base[1] + ny * gap + along[1] * sh
                if abs(nx) < 0.5:  # horizontal wall
                    tx = Text((cx, cy), s, h, "bc" if ny < 0 else "tc", 0.0, layer="A-ANNO-TEXT", tag=f"callout:{og.id}")
                else:
                    px = cx + (h if nx > 0 else 0.0)
                    tx = Text((px, cy), s, h, "bc", 90.0, layer="A-ANNO-TEXT", tag=f"callout:{og.id}")
                if try_text(ctx, tx):
                    placed = True
                    break
            if placed:
                break


def door_callouts(ctx: Ctx) -> None:
    """P. w on the swing side: beside the open leaf when free, else by the arc, else inside the sector."""
    h = S.H["dim"]
    for o, og in zip(ctx.lv.openings, ctx.geom.openings):
        if og.type != "door" or og.id not in ctx.meta_swing or ctx.assumed_size(o.width):
            continue
        s = f"{ctx.tr('door_abbr')} {size_text(ctx, o.width, None)}"
        tw = text_width(s, h)
        own = f"swing:{og.id}"
        base, tip, closed = ctx.meta_leaf[og.id]
        w = math.dist(base, tip)
        leaf = ((tip[0] - base[0]) / w, (tip[1] - base[1]) / w)
        u = ((closed[0] - base[0]) / w, (closed[1] - base[1]) / w)  # towards the closed position, into the sector

        def beside(f, sgn, gap):
            ext = abs(u[0]) * tw / 2 + abs(u[1]) * h / 2
            p = (base[0] + leaf[0] * f * w, base[1] + leaf[1] * f * w)
            return (p[0] + sgn * u[0] * (gap + ext), p[1] + sgn * u[1] * (gap + ext))

        tries = [(beside(f, -1, g), ()) for f in (0.6, 0.45, 0.75, 0.3, 0.85) for g in (1.4, 2.4)]
        co = list(ctx.meta_swing[og.id].exterior.coords)
        cxy, mid_arc = co[0], co[len(co) // 2]
        ang0 = math.atan2(mid_arc[1] - cxy[1], mid_arc[0] - cxy[0])
        r = math.hypot(mid_arc[0] - cxy[0], mid_arc[1] - cxy[1])
        ring = sorted((dist + abs(da) * 0.06, dist, da) for dist in (r + 2.2, r + 4.5, r + 7.0, r + 10.0) for da in range(-90, 91, 15))
        tries += [((cxy[0] + dist * math.cos(ang0 + math.radians(da)), cxy[1] + dist * math.sin(ang0 + math.radians(da))), ()) for _, dist, da in ring]
        tries += [(beside(f, 1, 1.2), (own,)) for f in (0.6, 0.45, 0.75)]
        tries += [((cxy[0] + r * f * math.cos(ang0), cxy[1] + r * f * math.sin(ang0)), (own,)) for f in (0.62, 0.5, 0.75)]
        for pos, ign in tries:
            if try_text(ctx, Text(pos, s, h, "mc", 0.0, layer="A-ANNO-TEXT", tag=f"callout:{og.id}"), ign):
                break


def _hexagon(c, r):
    return [(c[0] + r * math.cos(math.radians(60 * i + 30)), c[1] + r * math.sin(math.radians(60 * i + 30))) for i in range(6)]


def _mark_spaces(ctx: Ctx, og):
    """Paper polygons of the host room and of the spaces across the wall (other rooms, unassigned, outside)."""
    host = to_paper(ctx, ctx.geom.rooms[og.room])
    others = [to_paper(ctx, r) for rid, r in ctx.geom.rooms.items() if rid != og.room]
    if not ctx.geom.unassigned.is_empty:
        others.append(to_paper(ctx, ctx.geom.unassigned))
    other_u = unary_union(others) if others else Polygon()
    ext_t = ctx.led.value(ctx.lv.exterior_wall)
    outside = _exterior(ctx, og)
    env_outer = to_paper(ctx, ctx.geom.envelope.buffer(ext_t, join_style="mitre")) if outside else None
    return host, other_u, env_outer


def _mark_ok(ctx: Ctx, og, box, spaces, ign) -> bool:
    host, other_u, env_outer = spaces
    in_space = host.contains(box) or other_u.contains(box) or (env_outer is not None and not box.intersects(env_outer))
    return in_space and ctx.placer.is_free(box, ign)


def _mark_at(ctx: Ctx, og, c, r, spaces, ign=()) -> bool:
    b = rect(c[0] - r - 0.4, c[1] - r - 0.4, c[0] + r + 0.4, c[1] + r + 0.4)
    if not _mark_ok(ctx, og, b, spaces, ign):
        return False
    if og.type == "window":
        _poly_m(ctx, _hexagon(c, r + 0.3), True, S.PEN["opening"], S.PAPER, tag=f"mark:{og.id}")
    else:
        _circle_m(ctx, c, r, S.PEN["opening"], S.PAPER, tag=f"mark:{og.id}")
    ctx.put_model(Text(c, og.id, S.H["mark"], "mc", 0.0, layer="A-ANNO-SYMB", tag=f"mark:{og.id}"))
    ctx.placer.add_obstacle("mark", b)
    return True


def opening_marks(ctx: Ctx) -> None:
    """Circle marks on doors, hexagon marks on windows: within 8 mm of the opening midpoint, in a connected space."""
    for og in ctx.geom.openings:
        r = max(2.6, text_width(og.id, S.H["mark"]) / 2 + 0.9)
        mid = ((og.a[0] + og.b[0]) / 2, (og.a[1] + og.b[1]) / 2)
        n = og.normal
        mid_p = ctx.sheet.xf(*mid)
        pn_in = (-n[0], n[1])  # paper vector into the host room
        spaces = _mark_spaces(ctx, og)
        # signed steps along the normal from the wall's host face: +ve into the room, -ve across the wall
        cands = []
        for dist in (r + 0.6, r + 1.6, r + 3.0, r + 4.5, -(r + 0.6 + og.depth * ctx.k), -(r + 1.8 + og.depth * ctx.k), -(r + 3.5 + og.depth * ctx.k)):
            for sh in (0, 2, -2, 4, -4, 6, -6):
                c = (mid_p[0] + pn_in[0] * dist + (-pn_in[1]) * sh, mid_p[1] + pn_in[1] * dist + pn_in[0] * sh)
                if math.dist(c, mid_p) <= 8.0 + r:
                    cands.append(c)
        # nearest first; doors prefer the side away from the swing, windows the room side
        away = og.type != "window" and (og.swing == "in" or og.type == "opening")

        def pref(c):
            side = (c[0] - mid_p[0]) * pn_in[0] + (c[1] - mid_p[1]) * pn_in[1]
            return math.dist(c, mid_p) + (0.0 if (side < 0) == away else 2.5)

        cands.sort(key=pref)
        done = any(_mark_at(ctx, og, c, r, spaces) for c in cands)
        if not done and og.id in ctx.meta_swing:
            base, tip, closed = ctx.meta_leaf[og.id]
            for f in (0.55, 0.7, 0.4):
                c = (base[0] + (tip[0] + closed[0] - 2 * base[0]) / 2 * f, base[1] + (tip[1] + closed[1] - 2 * base[1]) / 2 * f)
                if math.dist(c, mid_p) <= 8.0 + r + 6 and _mark_at(ctx, og, c, r, spaces, (f"swing:{og.id}",)):
                    break


def _spot_near(ctx: Ctx, cp, w, hh) -> tuple[float, float, Polygon] | None:
    """Nearest free tag-box centre around paper point cp whose leader crosses no text or line."""
    for dist in (3.5, 5.0, 7.0, 9.5, 12.5, 16.0, 20.0):
        for ang in range(0, 360, 20):
            bx, by = cp[0] + dist * math.cos(math.radians(ang)), cp[1] + dist * math.sin(math.radians(ang))
            b = rect(bx - w / 2, by - hh / 2, bx + w / 2, by + hh / 2)
            if not ctx.placer.is_free(b.buffer(0.5)):
                continue
            e = b.exterior.interpolate(b.exterior.project(Point(*cp)))
            if leader_ok(ctx, LineString([(e.x, e.y), cp])):
                return bx, by, b
    return None


def wall_tags(ctx: Ctx) -> None:
    """Every wall type in the legend gets a tag: E1/F1 on the exterior wall, P1 on one or two long partitions."""
    g = ctx.geom
    w, hh = 8.0, 4.4
    ext_t = ctx.led.value(ctx.lv.exterior_wall)
    for code, _, _ in ctx.wall_types():
        if code == "P1":
            outer = g.envelope.buffer(ext_t + 0.5, join_style="mitre")
            part = g.walls["existing"].difference(outer.difference(g.envelope)).difference(g.envelope.boundary.buffer(1.0))
            p_t = ctx.led.value(ctx.lv.partition)
            cands = []
            rooms_u = unary_union(list(g.rooms.values())).buffer(0.05)
            outside_u = g.envelope.buffer(ext_t + 10).difference(g.envelope.buffer(ext_t - 0.05))
            for rid, poly in g.rooms.items():
                co = list(poly.exterior.coords)
                ccw = LinearRing(co).is_ccw
                for k in range(len(co) - 1):
                    p0, p1 = co[k], co[k + 1]
                    L = math.dist(p0, p1)
                    if L < 40:
                        continue
                    u = ((p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L)
                    n = (u[1], -u[0]) if ccw else (-u[1], u[0])
                    for f in (0.5, 0.3, 0.7):
                        face = (p0[0] + (p1[0] - p0[0]) * f, p0[1] + (p1[1] - p0[1]) * f)
                        ray = LineString([face, (face[0] + n[0] * 14, face[1] + n[1] * 14)]).intersection(part.buffer(0.01))
                        segs = [s_ for s_ in shapely.get_parts(ray) if isinstance(s_, LineString) and s_.length > 0.5]
                        if not segs:
                            continue
                        seg = min(segs, key=lambda s_: min(math.dist(face, c_) for c_ in s_.coords))
                        far = max(seg.coords, key=lambda c_: math.dist(face, c_))
                        beyond = Point(far[0] + n[0] * 0.4, far[1] + n[1] * 0.4)
                        other = [r2 for r2, q in g.rooms.items() if r2 != rid and q.buffer(0.05).contains(beyond)]
                        if not other:
                            continue  # zone, empty or exterior: not a partition between two rooms
                        pair = {rid, other[0]}
                        if not any({gp.a, gp.b} == pair and gp.kind == "std" for gp in g.gaps):
                            continue  # absorbed or thin wall: no standard partition tag
                        m = ((face[0] + far[0]) / 2, (face[1] + far[1]) / 2)
                        cands.append((L, m))
                        break
            cands.sort(key=lambda c: -c[0])
            done, used = 0, []
            for L, m in cands:
                if done >= 2:
                    break
                cp = ctx.sheet.xf(*m)
                if any(math.dist(cp, u_) < 40 for u_ in used):
                    continue
                spot = _spot_near(ctx, cp, w, hh)
                if spot:
                    _emit_wall_tag(ctx, code, (spot[0], spot[1]), cp, spot[2])
                    used.append(cp)
                    done += 1
        else:
            x0, y0, x1, y1 = g.envelope.bounds
            hw = ext_t * ctx.k / 2
            placed = False
            for side in ("S", "N", "W", "E"):
                for f in (0.5, 0.35, 0.65, 0.2, 0.8, 0.12, 0.88):
                    if side in ("S", "N"):
                        pin = (x0 + (x1 - x0) * f, y0 - ext_t / 2 if side == "S" else y1 + ext_t / 2)
                    else:
                        pin = (x0 - ext_t / 2 if side == "W" else x1 + ext_t / 2, y0 + (y1 - y0) * f)
                    cp = ctx.sheet.xf(*pin)
                    ux, uy = {"S": (0, 1), "N": (0, -1), "W": (-1, 0), "E": (1, 0)}[side]
                    for gap in (1.8, 3.2):
                        bx, by = cp[0] + ux * (hw + gap + w / 2), cp[1] + uy * (hw + gap + hh / 2)
                        b = rect(bx - w / 2, by - hh / 2, bx + w / 2, by + hh / 2)
                        if ctx.placer.is_free(b.buffer(0.5)):
                            _emit_wall_tag(ctx, code, (bx, by), cp, b)
                            placed = True
                            break
                    if placed:
                        break
                if placed:
                    break
            if not placed:
                spot = _spot_near(ctx, ctx.sheet.xf(x0 - ext_t / 2, (y0 + y1) / 2), w, hh)
                if spot:
                    _emit_wall_tag(ctx, code, (spot[0], spot[1]), ctx.sheet.xf(x0 - ext_t / 2, (y0 + y1) / 2), spot[2])


def _emit_wall_tag(ctx: Ctx, code, c, target, b) -> None:
    s = ctx.sheet
    edge = b.exterior.interpolate(b.exterior.project(Point(*target)))
    _line_m(ctx, (edge.x, edge.y), target, S.PEN["leader"], tag=f"wtag:{code}")
    _circle_m(ctx, target, 0.5, 0.13, S.INK, tag=f"wtag:{code}")
    _poly_m(ctx, [(b.bounds[0], b.bounds[1]), (b.bounds[2], b.bounds[1]), (b.bounds[2], b.bounds[3]), (b.bounds[0], b.bounds[3])],
            True, S.PEN["opening"], S.PAPER, tag=f"wtag:{code}")
    ctx.put_model(Text(c, code, S.H["mark"], "mc", 0.0, layer="A-ANNO-SYMB", tag=f"wtag:{code}"))
    ctx.placer.add_obstacle("wtag", b.buffer(0.4))
    ctx.placer.add_obstacle("leader", LineString([(edge.x, edge.y), target]), 0.3)
