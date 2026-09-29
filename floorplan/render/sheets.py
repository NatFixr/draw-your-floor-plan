"""Sheet assembly: scale choice, layout, drawing, files. Entry point render_plan."""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

from shapely.ops import unary_union

from . import annot, drawplan, frame
from . import styles as S
from ..checker import Report, check
from ..geometry import build_level
from ..i18n import colon
from ..model import Plan
from .ctx import Ctx
from .layout import Sheet
from .metrics import text_width
from .pdf import write_pdf, write_png
from .placer import Placer
from .svg import svg_string


class RenderRefused(RuntimeError):
    """The checker reported FATAL findings; nothing is drawn."""


@dataclass
class RenderResult:
    level_id: str
    paths: dict[str, Path]
    scalebar: dict | None
    sheet_size_mm: tuple[float, float]
    scale: int = 50
    overlaps: list = field(default_factory=list)


def _outer_bounds(geom, lv, led):
    ext_t = led.value(lv.exterior_wall)
    parts = [geom.envelope.buffer(ext_t, join_style="mitre")] + [g for g in geom.walls.values() if not g.is_empty]
    return unary_union(parts).bounds


def _hand(og) -> str:
    n = og.normal
    left = (-n[1], n[0])
    w = math.hypot(og.b[0] - og.a[0], og.b[1] - og.a[1])
    u = ((og.b[0] - og.a[0]) / w, (og.b[1] - og.a[1]) / w)
    sgn = -1.0 if og.hinge == "start" else 1.0
    return "hinge_left" if sgn * (u[0] * left[0] + u[1] * left[1]) > 0 else "hinge_right"


def schedules(ctx: Ctx) -> list[frame.Block]:
    """Door and window schedules (BUILDER)."""
    lang = "fr" if ctx.lang == "bi" else ctx.lang
    names = {r.id: (r.name.get(lang) or r.name.get("en") or r.id) for r in ctx.lv.rooms}
    nm = "n. m." if lang == "fr" else "n/m"

    def size(o):
        w = annot.size_text(ctx, o.width, None)
        h = annot.size_text(ctx, o.height, None) if o.height else nm
        return f"{w} x {h}"

    drows, wrows = [], []
    for o, og in zip(ctx.lv.openings, ctx.geom.openings):
        common = [o.id, names.get(o.room, o.room), size(o)]
        st, pos = ctx.tr("st_" + o.status), ctx.tr("pos_" + o.position)
        if og.type == "window":
            sill = annot.size_text(ctx, o.sill, None) if o.sill else ctx.tr("sill_none")
            wrows.append(common + [st, pos, sill])
        elif og.type == "door":
            sw = f"{ctx.tr('swing_' + og.swing)}, {ctx.tr(_hand(og))}"
            drows.append(common + [ctx.tr("t_door"), sw, st, pos])
        else:
            drows.append(common + [ctx.tr("t_opening"), "", st, pos])
    out = []
    if drows:
        out.append(frame.table(ctx, ctx.tr("door_sched"), [ctx.tr(k) for k in ("col_mark", "col_room", "col_size", "col_type", "col_swing", "col_state", "col_pos")], drows))
    if wrows:
        out.append(frame.table(ctx, ctx.tr("win_sched"), [ctx.tr(k) for k in ("col_mark", "col_room", "col_size", "col_state", "col_pos", "col_sill")], wrows))
    return out


def provenance_note(ctx: Ctx) -> str:
    """Generated note: who surveyed, dominant date, then the prov phrase of every printed entry that has one."""
    lang = "fr" if ctx.lang == "bi" else ctx.lang
    p = ctx.plan.project
    ids = list(dict.fromkeys(m[2] for m in ctx.rep.manifest if m[0] == ctx.lv.id))
    dates = [ctx.led.entry(i).date or p.survey_date for i in ids if ctx.led.entry(i).src in ("tape", "dictated")]
    dates = [d for d in dates if d]
    dom = max(set(dates), key=dates.count) if dates else ""
    who = p.surveyor.get(lang) or p.surveyor.get("en") or ""
    provs = []
    for i in ids:
        e = ctx.led.entry(i)
        ph = e.prov and (e.prov.get(lang) or e.prov.get("en"))
        if ph:
            provs.append(ph.format(date=e.date or p.survey_date or ""))
    provs = list(dict.fromkeys(provs))
    when = f" ({dom})" if dom else ""
    if lang == "fr":
        head = f"Dimensions intérieures relevées par {who}{when}"
        return head + (", sauf mention : " + " ; ".join(provs) if provs else "") + "."
    head = f"Interior dimensions surveyed by {who}{when}"
    return head + (", unless noted: " + "; ".join(provs) if provs else "") + "."


def unlocated_note(ctx: Ctx) -> str | None:
    """Surveyed items with no known position, with their sizes."""
    if not ctx.lv.unlocated:
        return None
    lang = "fr" if ctx.lang == "bi" else ctx.lang
    items = []
    for u in ctx.lv.unlocated:
        items.append(f"{u.what.get(lang) or u.what.get('en')} {annot.size_text(ctx, u.w, u.h)}")
    head = "Éléments relevés, position à confirmer : " if lang == "fr" else "Surveyed, position to confirm: "
    return head + " ; ".join(items) + "."


def _notes(ctx: Ctx) -> list[str]:
    lang = "fr" if ctx.lang == "bi" else ctx.lang
    notes = list(ctx.plan.project.notes.get(lang) or ctx.plan.project.notes.get("en") or [])
    if ctx.plan.project.minimal and ctx.sl == "permit":
        return notes
    un = unlocated_note(ctx)
    if un:
        notes.append(un)
    notes.append(provenance_note(ctx))
    if ctx.sl == "builder":
        notes.append(ctx.tr("faces_note"))
        notes.append(ctx.tr("sched_hand"))
        if ctx.lv.fixtures:
            notes.append(ctx.tr("fixtures_note"))
    return notes


def _new_ctx(plan, rep, lv, geom, sc, lang, sl, stars: bool = True) -> Ctx:
    W, H = S.SHEET_MM
    ctx = Ctx(plan, rep, lv, geom, Sheet((W, H), sc, level_id=lv.id, sheet_level=sl, lang=lang, units=plan.project.units), Placer(), lang, sl)
    ctx.stars = stars
    return ctx


def prints_star(sheet: Sheet) -> bool:
    """True when a * is printed on the sheet outside the legend and the footnote."""
    from .layout import Dim, Text
    for it in sheet.items:
        if it.layer == "A-ANNO-LEGN" or it.tag == "footnote":
            continue
        if isinstance(it, (Text,)) and "*" in it.s or isinstance(it, Dim) and "*" in it.text:
            return True
    return False


def _fit_layout(ctx: Ctx, bounds, idx, n) -> dict | None:
    """Try the strip, view band, schedules and plan block in the drawing area; None if they do not fit."""
    W, H = ctx.sheet.size_mm
    sl = ctx.sl
    strip = None
    notes = _notes(ctx)
    sno = f"{ctx.plan.project.sheet_prefix}-{(2 if sl == 'builder' else 1)}{idx + 1:02d}"
    strip, k = None, 0
    for k in range(len(notes), -1, -1):  # as many leading notes as the strip holds
        strip = frame.title_strip(ctx, S.STRIP_MM, H - 2 * S.BORDER_MM, sno, idx + 1, n, notes[:k] or None)
        if strip:
            break
    if strip is None:
        return None
    overflow = notes[k:]
    zx0, zx1 = S.BORDER_MM + 4, W - S.BORDER_MM - strip.w - 4
    zy0, zy1 = S.BORDER_MM + 3, H - S.BORDER_MM - 3
    m = 19.0 if sl == "builder" else 20.0
    pw = (bounds[2] - bounds[0]) * ctx.k + 2 * m
    ph = (bounds[3] - bounds[1]) * ctx.k + 2 * m
    lang = "fr" if ctx.lang == "bi" else ctx.lang
    lvname = ctx.lv.name.get(lang) or ctx.lv.name.get("en") or ctx.lv.id
    sheet_no = f"{ctx.plan.project.sheet_prefix}-{(2 if sl == 'builder' else 1)}{idx + 1:02d}"
    vt = frame.view_title(ctx, lvname, "1", sheet_no)
    na = frame.north_arrow(ctx)
    zw = zx1 - zx0
    bar = None
    for metres in (5, 4, 3):
        b, sb = frame.scale_bar(ctx, metres)
        if vt.w + 10 + na.w + 8 + b.w <= zw:
            bar = (b, sb)
            break
    if bar is None:
        bar = (b, sb)
    band_h = max(vt.h, na.h, bar[0].h)
    scheds = schedules(ctx) if sl == "builder" else []
    sched_h = sched_w = 0.0
    sched_pos: list[tuple[float, float]] = []
    if scheds:
        gap = 5.0
        tw = sum(b.w for b in scheds) + gap * (len(scheds) - 1)
        if tw <= zw:
            sched_h, sched_w = max(b.h for b in scheds), tw
        else:
            sched_h, sched_w = sum(b.h for b in scheds) + gap * (len(scheds) - 1), max(b.w for b in scheds)
    nblock, side, plan_cx, row_h = None, False, zx0 + zw / 2, ph
    tail = 4 + band_h + ((4 + sched_h) if scheds else 0)
    avail_h = zy1 - zy0
    if pw > zw or sched_w > zw:
        return None
    stack = ph + tail
    if overflow:
        nw = min(112.0, zw - pw - 6)
        below = frame.notes_columns(ctx, zw, overflow, start=k + 1)
        if nw >= 55:  # the free column to the right of the plan first
            nb = frame.notes_block(ctx, nw, overflow, k + 1)
            if max(ph, nb.h + m / 2) + tail <= avail_h:
                nblock, side = nb, True
                row_h = max(ph, nb.h + m / 2)
                plan_cx = zx0 + (zw - (pw + 6 + nb.w)) / 2 + pw / 2
                stack = row_h + tail
        if nblock is None:
            nblock = below
            stack = ph + tail + 4 + below.h
    if stack > avail_h:
        return None
    top = zy0 + (zy1 - zy0 - stack) / 2
    cx = zx0 + zw / 2
    return dict(strip=strip, zx0=zx0, zx1=zx1, top=top, cx=cx, pw=pw, ph=ph, m=m, vt=vt, na=na, bar=bar, band_h=band_h,
                scheds=scheds, nblock=nblock, side=side, plan_cx=plan_cx, row_h=row_h, sched_w=sched_w, sched_h=sched_h, zw=zw, sheet_no=sheet_no, strip_x=W - S.BORDER_MM - strip.w)


def build_sheet(plan: Plan, rep: Report, level_id: str, sl: str, lang: str, idx: int = 0, n: int = 1, _stars: bool | None = None, _final: bool = False):
    """Build the display list for one level; returns (Sheet, Ctx)."""
    lv = plan.level(level_id)
    geom = build_level(plan, level_id)
    led = plan.resolver()
    bounds = _outer_bounds(geom, lv, led)
    if _stars is None:
        _stars = not plan.project.minimal and any(m[0] == level_id and m[4] for m in rep.manifest)
    if sl == "sketch":
        ctx = _new_ctx(plan, rep, lv, geom, 50, lang, sl, _stars)
        lay = None
        pw, ph = (bounds[2] - bounds[0]) * ctx.k, (bounds[3] - bounds[1]) * ctx.k
        mg = S.SKETCH_MARGIN_MM
        title_w = text_width(_sketch_title(ctx), 4.0, "bold")
        bar, sb = frame.scale_bar(ctx, 5)
        na = frame.north_arrow(ctx)
        fn_w = text_width(_sketch_footnote(ctx), S.H["note"])
        W = max(pw + 2 * mg, title_w + 2 * mg + na.w + 6, bar.w + 2 * mg, fn_w + 2 * mg)
        Hh = ph + 2 * mg
        ctx.sheet.size_mm = (round(W, 2), round(Hh, 2))
        ctx.sheet.ox = (W - pw) / 2 - bounds[0] * ctx.k
        ctx.sheet.oy = mg + bounds[3] * ctx.k
    else:
        lay = None
        for sc in S.SCALES:
            ctx = _new_ctx(plan, rep, lv, geom, sc, lang, sl, _stars)
            lay = _fit_layout(ctx, bounds, idx, n)
            if lay:
                break
        if lay is None:
            ctx = _new_ctx(plan, rep, lv, geom, S.SCALES[-1], lang, sl, _stars)
            lay = _fit_layout(ctx, bounds, idx, n)
            if lay is None:
                raise RenderRefused("content does not fit the sheet even at 1:100")
        px, py = lay["plan_cx"] - lay["pw"] / 2, lay["top"]
        ctx.sheet.ox = px + lay["m"] - bounds[0] * ctx.k
        ctx.sheet.oy = py + lay["m"] + bounds[3] * ctx.k
    ctx.mm_in = 1.0 / ctx.sheet.k
    sh = ctx.sheet
    ctx.zone = (4.0, 4.0, sh.size_mm[0] - 4.0, sh.size_mm[1] - 4.0) if sl == "sketch" else \
        (lay["zx0"], S.BORDER_MM + 3, lay["zx1"], sh.size_mm[1] - S.BORDER_MM - 3)
    sh.title = f"{plan.project.id} {level_id} {sl} {lang}"
    sh.meta.update(project=plan.project.id, sheet_level=sl, lang=lang, level_id=level_id)

    # sheet furniture
    if sl == "sketch":
        W, Hh = sh.size_mm
        mg = S.SKETCH_MARGIN_MM
        title = _sketch_title(ctx)
        ctx.put(frame.T(mg, 13.0, title, 4.0, "bl", "bold", layer="A-ANNO-TTLB"))
        frame.place(ctx, na, W - mg - na.w, 6.0)
        bx, by = mg, Hh - mg + 6.0
        frame.place(ctx, bar, bx, by)
        sh.scalebar = {"x0_mm": bx + sb["x0"], "x1_mm": bx + sb["x1"], "y_mm": by + sb["y"]}
        fn = _sketch_footnote(ctx)
        if fn:
            ctx.put(frame.T(bx, by + bar.h + 5.0, fn, S.H["note"], "bl", layer="A-ANNO-TEXT", tag="footnote"))
    else:
        W, Hh = sh.size_mm
        b = S.BORDER_MM
        sh.add(frame.R(b, b, W - 2 * b, Hh - 2 * b, S.PEN["border"]))
        frame.place(ctx, lay["strip"], lay["strip_x"], b)
        y_band = lay["top"] + lay["row_h"] + 4
        vt, na, (bar, sb) = lay["vt"], lay["na"], lay["bar"]
        total = vt.w + 10 + na.w + 8 + bar.w
        bx0 = lay["cx"] - total / 2
        bx0 = max(bx0, lay["zx0"])
        frame.place(ctx, vt, bx0, y_band)
        frame.place(ctx, na, bx0 + vt.w + 10, y_band)
        bxx = bx0 + vt.w + 10 + na.w + 8
        frame.place(ctx, bar, bxx, y_band + lay["band_h"] - bar.h)
        by = y_band + lay["band_h"] - bar.h
        sh.scalebar = {"x0_mm": bxx + sb["x0"], "x1_mm": bxx + sb["x1"], "y_mm": by + sb["y"]}
        if lay["scheds"]:
            y = y_band + lay["band_h"] + 4
            xs = lay["cx"] - lay["sched_w"] / 2
            if lay["sched_w"] and sum(bk.w for bk in lay["scheds"]) + 5 * (len(lay["scheds"]) - 1) <= lay["zw"] + 0.01:
                for bk in lay["scheds"]:
                    frame.place(ctx, bk, xs, y)
                    xs += bk.w + 5
            else:
                for bk in lay["scheds"]:
                    frame.place(ctx, bk, lay["cx"] - bk.w / 2, y)
                    y += bk.h + 8
        if lay["nblock"] and lay["side"]:
            frame.place(ctx, lay["nblock"], lay["plan_cx"] + lay["pw"] / 2 + 6, lay["top"] + lay["m"] / 2)
        elif lay["nblock"]:
            y = y_band + lay["band_h"] + 4 + ((lay["sched_h"] + 4) if lay["scheds"] else 0)
            frame.place(ctx, lay["nblock"], lay["cx"] - lay["nblock"].w / 2, y)
    # model content
    drawplan.draw_walls(ctx)
    drawplan.draw_unmeasured(ctx)
    drawplan.draw_room_boundaries(ctx)
    for og in geom.openings:
        drawplan.draw_opening(ctx, og)
    for r in lv.rooms:
        if r.kind == "stair" and r.stair:
            drawplan.draw_stair(ctx, r)
    if sl == "builder":
        drawplan.draw_fixtures(ctx)
    if sl in ("sketch", "builder"):
        drawplan.draw_furniture(ctx)
    for r in lv.rooms:
        if r.kind == "stair" and r.stair:
            drawplan.stair_label(ctx, r)

    # dimensions, then tags, then callouts and marks
    if sl == "builder":
        annot.builder_dims(ctx)
    if sl == "builder":
        for r in lv.rooms:
            if r.kind == "stair":
                ctx.placer.add_obstacle("stairfill", drawplan.to_paper(ctx, geom.rooms[r.id]))
        annot.opening_marks(ctx)
        ctx.placer.remove_kind("stairfill")
    for r in lv.rooms:
        annot.room_dims(ctx, r)
    for r in sorted(lv.rooms, key=lambda r: -geom.rooms[r.id].area):
        annot.place_room_tag(ctx, r)
    annot.place_labels(ctx)
    if sl == "permit":
        annot.window_callouts(ctx)
        annot.door_callouts(ctx)
    if sl == "builder":
        annot.wall_tags(ctx)

    actual = prints_star(sh)
    if actual != _stars and not _final:
        return build_sheet(plan, rep, level_id, sl, lang, idx, n, actual, True)
    if sl != "sketch":
        print(f"{plan.project.id} {level_id} {sl} {lang}: scale 1:{sh.scale}")
    return sh, ctx


def _sketch_title(ctx: Ctx) -> str:
    lang = "fr" if ctx.lang == "bi" else ctx.lang
    p = ctx.plan.project
    return f"{p.title.get(lang) or p.title.get('en') or p.id}{colon(ctx.lang)} {ctx.lv.name.get(lang) or ctx.lv.name.get('en') or ctx.lv.id}"


def _sketch_footnote(ctx: Ctx) -> str:
    parts = []
    if ctx.stars:
        parts.append(ctx.tr("fn_confirm"))
    if any(o.position == "assumed" for o in ctx.lv.openings):
        parts.append(ctx.tr("fn_dashed"))
    if ctx.has_unmeasured:
        parts.append(ctx.tr("fn_hatch"))
    return "\u00a0\u00a0\u00a0".join(parts)


def render_plan(plan: Plan, sheet_level: str, lang: str, out_dir, formats=("svg", "pdf", "png", "dxf"), levels=None) -> list[RenderResult]:
    """Render one sheet per level; refuses when the checker finds FATAL problems."""
    rep = check(plan)
    if not rep.ok:
        raise RenderRefused("; ".join(f.msg for f in rep.findings if f.level == "FATAL"))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    n = len(plan.levels)
    for idx, lv in enumerate(plan.levels):
        if levels and lv.id not in levels:
            continue
        sheet, ctx = build_sheet(plan, rep, lv.id, sheet_level, lang, idx, n)
        stem = out / f"{plan.project.id}-{lv.id}-{sheet_level}-{lang}"
        paths: dict[str, Path] = {}
        svg = svg_string(sheet)
        if "svg" in formats or "pdf" in formats or "png" in formats:
            p = stem.with_suffix(".svg")
            p.write_text(svg, encoding="utf-8")
            paths["svg"] = p
        if "pdf" in formats or "png" in formats:
            paths["pdf"] = write_pdf(sheet, svg, stem.with_suffix(".pdf"))
        if "png" in formats:
            paths["png"] = write_png(paths["pdf"], stem.with_suffix(".png"), 200 if sheet_level == "sketch" else 150)
        if "dxf" in formats:
            try:
                from .dxf import write_dxf
            except ImportError:
                print("dxf skipped: floorplan/render/dxf.py not available", file=sys.stderr)
            else:
                paths["dxf"] = stem.with_suffix(".dxf")
                write_dxf(sheet, paths["dxf"])
        results.append(RenderResult(lv.id, paths, sheet.scalebar, sheet.size_mm, sheet.scale, ctx.placer.overlaps()))
    return results
