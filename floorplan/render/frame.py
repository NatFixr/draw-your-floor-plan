"""Paper-space blocks: title strip, legend, notes, view title, scale bar, north arrow, schedules."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import styles as S
from .ctx import Ctx
from .layout import Arc, Circle, Item, Line, Poly, Text
from ..i18n import colon
from .metrics import text_metrics, text_width, wrap
from ..units import fmt_ftin


@dataclass
class Block:
    w: float
    h: float
    items: list[Item] = field(default_factory=list)


def T(x, y, s, h=S.H["note"], anchor="bl", weight="regular", style="normal", color=S.INK, layer="A-ANNO-TEXT", rot=0.0, tag=""):
    """Paper-space Text shorthand."""
    return Text((x, y), s, h, anchor, rot, weight, style, color, layer=layer, tag=tag)


def L(x1, y1, x2, y2, pen=S.PEN["table"], dash=None, layer="A-ANNO-TTLB"):
    """Paper-space Line shorthand."""
    return Line((x1, y1), (x2, y2), pen, dash, layer=layer)


def R(x, y, w, h, pen=S.PEN["table"], fill=None, layer="A-ANNO-TTLB", hatch=None, dash=None):
    """Paper-space rectangle Poly."""
    return Poly([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True, pen, fill, dash, hatch, layer=layer)


def translate(items: list[Item], dx: float, dy: float) -> list[Item]:
    """Copies of paper-space items shifted by (dx, dy)."""
    out: list[Item] = []
    for it in items:
        c = _copy(it)
        if isinstance(c, Line):
            c.p1, c.p2 = (c.p1[0] + dx, c.p1[1] + dy), (c.p2[0] + dx, c.p2[1] + dy)
        elif isinstance(c, Poly):
            c.pts = [(x + dx, y + dy) for x, y in c.pts]
            c.holes = [[(x + dx, y + dy) for x, y in h] for h in c.holes]
        elif isinstance(c, (Arc, Circle)):
            c.center = (c.center[0] + dx, c.center[1] + dy)
        elif isinstance(c, Text):
            c.pos = (c.pos[0] + dx, c.pos[1] + dy)
        out.append(c)
    return out


def _copy(it):
    import copy
    return copy.copy(it)


def place(ctx: Ctx, blk: Block, x: float, y: float) -> None:
    """Add a block at (x, y); its texts go through the registry."""
    for it in translate(blk.items, x, y):
        ctx.sheet.add(it)
        if isinstance(it, Text):
            ctx.placer.add_text(it)


# ---------------------------------------------------------------- symbols
def north_arrow(ctx: Ctx) -> Block:
    """Circle with half-filled arrow and N; block 14 wide, top-left origin."""
    r = 6.0
    cx, cy = 7.0, 3.6 + 1.6 + r
    it: list[Item] = [Circle((cx, cy), r, S.PEN["opening"], layer="A-ANNO-SYMB")]
    it.append(Poly([(cx, cy - r + 0.8), (cx + 2.6, cy + r - 1.2), (cx, cy + r - 3.4)], True, 0.13, S.INK, layer="A-ANNO-SYMB"))
    it.append(Poly([(cx, cy - r + 0.8), (cx - 2.6, cy + r - 1.2), (cx, cy + r - 3.4)], True, S.PEN["opening"], layer="A-ANNO-SYMB"))
    it.append(T(cx, 3.6, ctx.tr("north"), 3.5, "bc", "bold", layer="A-ANNO-SYMB"))
    return Block(14.0, cy + r, it)


def scale_bar(ctx: Ctx, metres: int) -> tuple[Block, dict]:
    """Alternating black/white bar 0-1-2.. m; returns the block and the solid 1 m segment (block-local mm).
    Imperial projects get a feet bar in 2 ft steps (same count of segments, so layout fitting is unchanged)."""
    if ctx.plan.project.units == "imperial" and ctx.lang in ("fr", "en"):
        return _scale_bar_ft(ctx, metres * 3)
    m = 1000.0 / ctx.sheet.scale  # paper mm per metre
    bh, top = 2.0, 4.6
    it: list[Item] = []
    segs = [(0.0, 0.5, True), (0.5, 1.0, False)] + [(float(i), float(i + 1), i % 2 == 1) for i in range(1, metres)]
    for a, b, black in segs:
        x0, x1 = a * m, b * m
        if black:
            it.append(R(x0, top, x1 - x0, bh, 0.0, S.INK, "A-ANNO-SYMB"))
        else:
            it.append(L(x0, top, x1, top, 0.25, layer="A-ANNO-SYMB"))
            it.append(L(x0, top + bh, x1, top + bh, 0.25, layer="A-ANNO-SYMB"))
    it.append(L(0, top, 0, top + bh, 0.25, layer="A-ANNO-SYMB"))
    it.append(L(metres * m, top, metres * m, top + bh, 0.25, layer="A-ANNO-SYMB"))
    for i in range(metres + 1):
        it.append(T(i * m, top - 1.0, f"{i} m" if i == metres else str(i), 2.2, "bc", layer="A-ANNO-SYMB"))
    w = metres * m + text_width(f"{metres} m", 2.2) / 2 + 1
    return Block(w, top + bh, it), {"x0": 1.0 * m, "x1": 2.0 * m, "y": top + bh / 2}


def _scale_bar_ft(ctx: Ctx, feet: int) -> tuple[Block, dict]:
    """Feet scale bar 0-2-4.. ft with 1 ft subdivisions on the first 2 ft."""
    f = 304.8 / ctx.sheet.scale  # paper mm per foot
    bh, top = 2.0, 4.6
    it: list[Item] = []
    step = 2
    feet -= feet % step
    segs = [(0.0, 1.0, True), (1.0, 2.0, False)] + [(float(i), float(i + step), (i // step) % 2 == 1) for i in range(step, feet, step)]
    for a, b, black in segs:
        x0, x1 = a * f, b * f
        if black:
            it.append(R(x0, top, x1 - x0, bh, 0.0, S.INK, "A-ANNO-SYMB"))
        else:
            it.append(L(x0, top, x1, top, 0.25, layer="A-ANNO-SYMB"))
            it.append(L(x0, top + bh, x1, top + bh, 0.25, layer="A-ANNO-SYMB"))
    it.append(L(0, top, 0, top + bh, 0.25, layer="A-ANNO-SYMB"))
    it.append(L(feet * f, top, feet * f, top + bh, 0.25, layer="A-ANNO-SYMB"))
    unit = "pi" if ctx.lang == "fr" else "ft"
    for i in range(0, feet + 1, step):
        it.append(T(i * f, top - 1.0, f"{i} {unit}" if i == feet else str(i), 2.2, "bc", layer="A-ANNO-SYMB"))
    w = feet * f + text_width(f"{feet} {unit}", 2.2) / 2 + 1
    return Block(w, top + bh, it), {"x0": 0.0, "x1": f, "y": top + bh / 2}


def view_title(ctx: Ctx, level_name: str, number: str, sheet_no: str) -> Block:
    """Bubble with view number, bold title over a 0.50 underline, scale and subtitle."""
    title = f"{ctx.tr('view_plan')}{colon(ctx.lang)} {level_name.upper()}"
    tw = text_width(title, S.H["title"], "bold")
    it: list[Item] = []
    r = 5.0
    it.append(Circle((r, r), r, S.PEN["opening"], layer="A-ANNO-SYMB"))
    it.append(L(0, r, 2 * r, r, S.PEN["opening"], layer="A-ANNO-SYMB"))
    it.append(T(r, r - 0.9, number, 3.0, "bc", "bold", layer="A-ANNO-SYMB"))
    it.append(T(r, r + 1.1 + 1.8, sheet_no, 1.8, "bc", layer="A-ANNO-SYMB"))
    x = 2 * r + 4.0
    it.append(T(x, 5.6, title, S.H["title"], "bl", "bold", layer="A-ANNO-TTLB"))
    it.append(L(x, 7.6, x + tw, 7.6, S.PEN["cut"], layer="A-ANNO-TTLB"))
    it.append(T(x, 12.6, f"{ctx.tr('scale')} 1:{ctx.sheet.scale}", 3.0, "bl", layer="A-ANNO-TTLB"))
    h = 12.6
    sub = ctx.plan.project.subtitle
    if sub and ctx.sl != "sketch":
        st = sub.get("fr" if ctx.lang == "bi" else ctx.lang) or sub.get("en") or ""
        it.append(T(x, 17.4, st, S.H["note"], "bl", style="italic", layer="A-ANNO-TTLB"))
        h = 17.4
        tw = max(tw, text_width(st, S.H["note"], style="italic"))
    if ctx.sl == "permit":
        from .annot import total_area_text
        ta = total_area_text(ctx)
        h += 5.0
        it.append(T(x, h, ta, S.H["note"], "bl", layer="A-ANNO-TTLB"))
        tw = max(tw, text_width(ta, S.H["note"]))
    return Block(x + tw, h + 1.0, it)


# ---------------------------------------------------------------- legend
def _swatch_window(x, y):
    return [R(x, y + 0.5, 10, 3.6, 0.25, layer="A-ANNO-LEGN"), L(x, y + 2.3, x + 10, y + 2.3, 0.25, layer="A-ANNO-LEGN")]


def _swatch_door(x, y):
    return [L(x, y + 4.5, x + 1, y + 4.5, 0.5, layer="A-ANNO-LEGN"), L(x + 1, y + 4.5, x + 1, y + 0.5, 0.25, layer="A-ANNO-LEGN"),
            Arc((x + 1, y + 4.5), 4.0, 0, 90, 0.18, layer="A-ANNO-LEGN"), L(x + 5, y + 4.5, x + 10, y + 4.5, 0.5, layer="A-ANNO-LEGN")]


def _swatch_opening(x, y):
    st = S.FILL["existing"]
    return [R(x, y + 0.5, 3.0, 3.6, 0.5, st, "A-ANNO-LEGN"), R(x + 7.0, y + 0.5, 3.0, 3.6, 0.5, st, "A-ANNO-LEGN"),
            L(x + 3.0, y + 0.5, x + 3.0, y + 4.1, 0.25, layer="A-ANNO-LEGN"), L(x + 7.0, y + 0.5, x + 7.0, y + 4.1, 0.25, layer="A-ANNO-LEGN")]


def legend(ctx: Ctx, width: float) -> Block:
    """Legend rows for what is present on this level."""
    lv, g = ctx.lv, ctx.geom
    it: list[Item] = [T(0, 2.5, ctx.tr("legend"), S.H["note"], "bl", "bold", layer="A-ANNO-LEGN")]
    y = 5.0
    row = 5.8
    rows: list[tuple[list[Item] | None, str]] = []
    rows.append(([R(0, 0.5, 10, 3.6, 0.5, S.FILL["existing"], "A-ANNO-LEGN")], ctx.tr("wall_existing")))
    if not g.walls["new"].is_empty:
        rows.append(([R(0, 0.5, 10, 3.6, 0.5, S.FILL["new"], "A-ANNO-LEGN")], ctx.tr("wall_new")))
    if not g.walls["demolish"].is_empty:
        rows.append(([R(0, 0.5, 10, 3.6, 0.35, None, "A-ANNO-LEGN", dash="dashed")], ctx.tr("wall_demolish")))
    types = {o.type for o in lv.openings}
    if "window" in types:
        rows.append((_swatch_window(0, 0), ctx.tr("window")))
    if "door" in types:
        rows.append((_swatch_door(0, 0), ctx.tr("door")))
    if "opening" in types:
        rows.append((_swatch_opening(0, 0), ctx.tr("opening")))
    if ctx.has_unmeasured:
        rows.append(([R(0, 0.5, 10, 3.6, 0.25, None, "A-ANNO-LEGN", hatch="unmeasured")], ctx.tr("unmeasured_zone")))
    if ctx.stars:
        rows.append((None, ctx.tr("legend_confirm")))
    if any(o.position == "assumed" for o in lv.openings):
        rows.append(([L(0, 2.3, 10, 2.3, 0.25, "dashed", "A-ANNO-LEGN")], ctx.tr("legend_dashed")))
    for sw, label in rows:
        if sw:
            for s_ in translate(sw, 0, y):
                it.append(s_)
            it.append(T(13, y + 3.7, label, S.H["note"], layer="A-ANNO-LEGN"))
        else:
            it.append(T(0, y + 3.7, label, S.H["note"], layer="A-ANNO-LEGN"))
        y += row
    return Block(width, y, it)


def _note_item(ctx: Ctx, i: int, n: str, width: float) -> tuple[list[Item], float]:
    """Items and height of one numbered note wrapped to width (local origin top-left of the note)."""
    h = S.H["note"]
    pitch = S.PITCH * h
    ind = 5.5
    it: list[Item] = []
    base = h
    lines = wrap(n, width - ind, h)
    for j, ln in enumerate(lines):
        if j == 0:
            it.append(T(0, base, f"{i}.", h))
        it.append(T(ind, base, ln, h))
        base += pitch
    return it, len(lines) * pitch


def notes_block(ctx: Ctx, width: float, notes: list[str], start: int = 1) -> Block:
    """Numbered notes wrapped to width on one fixed baseline pitch, fixed gap between notes."""
    h = S.H["note"]
    it: list[Item] = [T(0, 2.5, ctx.tr("notes" if start == 1 else "notes_cont"), h, "bl", "bold")]
    y = 5.5
    for i, n in enumerate(notes, start):
        items, ht = _note_item(ctx, i, n, width)
        it += translate(items, 0, y)
        y += ht + S.NOTE_GAP_MM
    return Block(width, y - S.NOTE_GAP_MM, it)


def notes_columns(ctx: Ctx, max_w: float, notes: list[str], gap: float = 8.0, start: int = 1) -> Block:
    """Notes in balanced columns for the drawing area: the column count with the lowest block wins."""
    h = S.H["note"]
    best = None
    for k in range(1, 5):
        cw = (max_w - gap * (k - 1)) / k
        if cw < 70 or cw > 120:
            continue
        parts = [_note_item(ctx, i, n, cw) for i, n in enumerate(notes, start)]
        total = sum(p[1] + S.NOTE_GAP_MM for p in parts)
        cols: list[list[tuple[int, list, float]]] = [[]]
        used = 0.0
        for i, (items, ht) in enumerate(parts, 1):
            if cols[-1] and used + ht > total / k + 4 and len(cols) < k:
                cols.append([])
                used = 0.0
            cols[-1].append((i, items, ht))
            used += ht + S.NOTE_GAP_MM
        height = max(sum(c[2] + S.NOTE_GAP_MM for c in col) for col in cols) - S.NOTE_GAP_MM
        if best is None or height < best[0] - 0.01:
            best = (height, cw, cols)
    if best is None:
        return notes_block(ctx, max_w, notes, start)
    height, cw, cols = best
    it: list[Item] = [T(0, 2.5, ctx.tr("notes" if start == 1 else "notes_cont"), h, "bl", "bold")]
    for c, col in enumerate(cols):
        y = 5.5
        for _, items, ht in col:
            it += translate(items, c * (cw + gap), y)
            y += ht + S.NOTE_GAP_MM
    return Block(len(cols) * cw + (len(cols) - 1) * gap, 5.5 + height, it)


def wall_types_block(ctx: Ctx, width: float) -> Block:
    """BUILDER wall-type legend: code box, name, thickness ft-in and mm, (presumée) when assumed."""
    h = S.H["note"]
    pitch = S.PITCH * h
    it: list[Item] = [T(0, 2.5, ctx.tr("wall_types"), h, "bl", "bold", layer="A-ANNO-LEGN")]
    y = 5.0
    for code, name, thick_id in ctx.wall_types():
        v = ctx.led.value(thick_id)
        e = ctx.led.entry(thick_id)
        s = f"{name}, {fmt_ftin(v)} ({v * 25.4:.0f} mm)" + (f" {ctx.tr('assumed_paren')}" if e.src == "assumed" else "")
        it += tag_box(code, 0, y + 0.2)
        lines = wrap(s, width - 12, h)
        for j, ln in enumerate(lines):
            it.append(T(11, y + 3.0 + j * pitch, ln, h, layer="A-ANNO-LEGN"))
        y += max(5.8, 3.0 + pitch * (len(lines) - 1) + 3.0)
    return Block(width, y, it)


def tag_box(code: str, x: float, y: float) -> list[Item]:
    """Small rectangle with a wall-type code (top-left x, y), 8 x 4.4 mm."""
    return [R(x, y, 8.0, 4.4, 0.25, S.PAPER, "A-ANNO-SYMB"), T(x + 4.0, y + 2.2, code, S.H["mark"], "mc", layer="A-ANNO-SYMB")]


# ---------------------------------------------------------------- title strip
def title_strip(ctx: Ctx, width: float, height: float, sheet_no: str, sheet_i: int, sheet_n: int, notes: list[str] | None) -> Block | None:
    """Right-hand strip (local origin top-left); None when the content does not fit `height`."""
    pad = 4.0
    inner = width - 2 * pad
    p = ctx.plan.project
    lang = "fr" if ctx.lang == "bi" else ctx.lang
    it: list[Item] = [L(0, 0, 0, height, S.PEN["cut"])]
    y = pad
    for ln in wrap(p.title.get(lang) or p.title.get("en") or p.id, inner, 4.0, "bold"):
        it.append(T(pad, y + 4.0, ln, 4.0, "bl", "bold", layer="A-ANNO-TTLB"))
        y += S.PITCH * 4.0
    y += 0.6
    for extra in filter(None, [p.address, p.reference]):
        for ln in wrap(extra, inner, S.H["note"]):
            it.append(T(pad, y + 2.5, ln, S.H["note"], layer="A-ANNO-TTLB"))
            y += S.PITCH * S.H["note"]
    y += 2.0
    it.append(L(0, y, width, y))
    y += 4.0
    lg = legend(ctx, inner)
    it += translate(lg.items, pad, y)
    y += lg.h + 2.0
    if ctx.sl == "builder":
        wt = wall_types_block(ctx, inner)
        it += translate(wt.items, pad, y)
        y += wt.h + 2.0
    if notes:
        nb = notes_block(ctx, inner, notes)
        it += translate(nb.items, pad, y)
        y += nb.h
    # title-block cells, stacked from the bottom
    lab = S.H["label"]
    rev_h, cell_h = 13.0, 12.0
    name = ctx.lv.name.get(lang) or ctx.lv.name.get("en") or ctx.lv.id
    sub = p.subtitle.get(lang) if p.subtitle else ""
    sub_lines = wrap(sub or "", inner, S.H["note"], style="italic") if sub else []
    pn = S.PITCH * S.H["note"]
    a_h = 4.0 + 5.2 + pn * len(sub_lines) + 2.5
    total = rev_h + 2 * cell_h + a_h
    top = height - total
    if y + 4.0 > top:
        return None
    yy = top
    it.append(L(0, yy, width, yy, S.PEN["cut"]))
    it.append(T(pad, yy + 1.2 + lab, ctx.tr("drawing_title"), lab, color=S.GREY, layer="A-ANNO-TTLB"))
    it.append(T(pad, yy + 5.8 + 3.5, name.upper(), 3.5, "bl", "bold", layer="A-ANNO-TTLB"))
    for i, ln in enumerate(sub_lines):
        it.append(T(pad, yy + 5.8 + 3.5 + 4.6 + pn * i, ln, S.H["note"], style="italic", layer="A-ANNO-TTLB"))
    yy += a_h
    half = width / 2
    for (l1, v1, l2, v2) in (
        (ctx.tr("scale"), f"1:{ctx.sheet.scale}", ctx.tr("date"), p.date),
        (ctx.tr("drawn_by"), p.author, ctx.tr("sheet"), f"{sheet_no}   {ctx.tr('sheet_of').format(n=sheet_i, m=sheet_n)}"),
    ):
        split = 0.6 * width if l1 == ctx.tr("drawn_by") else half
        it.append(L(0, yy, width, yy))
        it.append(L(split, yy, split, yy + cell_h))
        for x0, x1, lb, vv in ((pad, split - 2.0, l1, v1), (split + pad, width - 2.0, l2, v2)):
            it.append(T(x0, yy + 1.2 + lab, lb, lab, color=S.GREY, layer="A-ANNO-TTLB"))
            cw = x1 - x0
            hv = next((c for c in (3.0, 2.5, 2.2) if text_width(vv, c) <= cw), 2.2)
            for j, ln in enumerate(wrap(vv, cw, hv)[:2]):
                it.append(T(x0, yy + 5.2 + hv + j * S.PITCH * hv, ln, hv, "bl", layer="A-ANNO-TTLB"))
        yy += cell_h
    it.append(L(0, yy, width, yy))
    c1, c2 = 10.0, 10.0 + 22.0
    it.append(L(0, yy + 4.6, width, yy + 4.6))
    for x_ in (c1, c2):
        it.append(L(x_, yy, x_, height - pad + 3.0))
    heads = [(pad, ctx.tr("rev")), (c1 + 1.5, ctx.tr("date")), (c2 + 1.5, ctx.tr("rev_desc"))]
    for x_, s_ in heads:
        it.append(T(x_, yy + 1.0 + lab, s_, lab, color=S.GREY, layer="A-ANNO-TTLB"))
    prelim = ctx.sl == "builder" and getattr(ctx.rep, "open_count", ctx.rep.n("OPEN")) > 0
    issued = ctx.tr("prelim_builder" if prelim else "issued_builder" if ctx.sl == "builder" else "issued_permit")
    it.append(T(pad, yy + 4.6 + 3.6, "0", S.H["note"], layer="A-ANNO-TTLB"))
    it.append(T(c1 + 1.5, yy + 4.6 + 3.6, p.date, S.H["note"], layer="A-ANNO-TTLB"))
    hi = S.H["note"] if text_width(issued, S.H["note"]) < width - c2 - 3 else 2.2
    for j, ln in enumerate(wrap(issued, width - c2 - 3, hi)[:2]):
        it.append(T(c2 + 1.5, yy + 4.6 + 3.6 + j * S.PITCH * hi, ln, hi, layer="A-ANNO-TTLB"))
    return Block(width, height, it)


# ---------------------------------------------------------------- schedules
def table(ctx: Ctx, title: str, cols: list[str], rows: list[list[str]], layer: str = "A-ANNO-SCHD") -> Block:
    """Simple ruled table: title, header row, data rows; column widths from measured text."""
    h = S.H["sched"]
    pad = 1.1
    widths = []
    for i, c in enumerate(cols):
        w = max([text_width(c, S.H["label"] + 0.4, "bold")] + [text_width(r[i], h) for r in rows]) + 2 * pad
        widths.append(w)
    rh = 4.0
    W = sum(widths)
    it: list[Item] = [T(0, 3.0, title, S.H["note"], "bl", "bold", layer=layer)]
    y0 = 5.0
    it.append(R(0, y0, W, rh, S.PEN["table"], "#e6e6e6", layer))
    x = 0.0
    for c, w in zip(cols, widths):
        it.append(T(x + pad, y0 + rh - 1.2, c, S.H["label"] + 0.4, "bl", "bold", layer=layer))
        x += w
    y = y0 + rh
    for r in rows:
        x = 0.0
        for c, w in zip(r, widths):
            it.append(T(x + pad, y + rh - 1.2, c, h, "bl", layer=layer))
            x += w
        y += rh
    it.append(R(0, y0, W, y - y0, S.PEN["table"], None, layer))
    x = 0.0
    for w in widths[:-1]:
        x += w
        it.append(L(x, y0, x, y, 0.13, layer=layer))
    for j in range(1, len(rows) + 1):
        it.append(L(0, y0 + rh * (j), W, y0 + rh * j, 0.13, layer=layer))
    return Block(W, y, it)
