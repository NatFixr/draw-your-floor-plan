"""Geometry and ledger checker: FATAL / OPEN / FIT / INFO findings, areas, manifest."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from .geometry import build_level, fixture_polygon, furniture_polygon, swing_polygon
from .i18n import t
from .model import Ledger, LedgerError, Plan, PlanError, load_plan
from .units import fmt_ftin

AREA_TOL = 1.0  # sq in
OPENING_TOL = 0.01  # in
CLOSE_FLOOR = 1e-4  # in
CLOSE_TOL = 0.01  # in


@dataclass
class Finding:
    level: str  # FATAL | OPEN | FIT | INFO
    code: str
    msg: str
    q: str | None = None
    where: str = ""


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    areas: dict[str, dict[str, float]] = field(default_factory=dict)
    manifest: list[tuple[str, str, str, float, bool]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when there is no FATAL finding."""
        return not self.n("FATAL")

    def n(self, level: str) -> int:
        """Count of findings at a level."""
        return sum(f.level == level for f in self.findings)

    @property
    def open_count(self) -> int:
        """Number of OPEN findings."""
        return self.n("OPEN")

    def to_dict(self) -> dict:
        """JSON-ready form."""
        return {
            "ok": self.ok, "fatal": self.n("FATAL"), "open": self.n("OPEN"), "fit": self.n("FIT"),
            "findings": [asdict(f) for f in self.findings],
            "areas": self.areas,
            "manifest": [list(m) for m in self.manifest],
        }


class _Ctx:
    def __init__(self, plan: Plan):
        self.plan = plan
        self.led = plan.resolver()
        self.rep = Report()
        self.qids = {q.id for q in plan.questions}
        self.seen_open: set[str] = set()

    def add(self, level: str, code: str, msg: str, q: str | None = None, where: str = "") -> None:
        f = Finding(level, code, msg, q, where)
        if f not in self.rep.findings:
            self.rep.findings.append(f)

    def val(self, x, where: str) -> float | None:
        try:
            return self.led.value(x)
        except LedgerError as e:
            self.add("FATAL", e.code, str(e), where=where)
            return None

    def ident(self, x, where: str) -> str | None:
        """Require a ledger id (printed values must be ledger entries)."""
        if x in self.led:
            return x
        self.add("FATAL", "unknown_ref", f"unknown ledger id '{x}'", where=where)
        return None

    def check_q(self, q: str | None, where: str) -> None:
        if q and q not in self.qids:
            self.add("FATAL", "unknown_question", f"unknown question id '{q}'", q, where)

    def print_value(self, level_id: str, what: str, lid: str) -> None:
        """Record a printed ledger entry in the manifest and OPEN bookkeeping."""
        e = self.led.entries[lid]
        try:
            v = self.led.value(lid)
        except LedgerError:
            return
        marked = self.led.is_open(lid)
        self.rep.manifest.append((level_id, what, lid, v, marked))
        if (e.src == "declared" or (e.src == "derived" and e.q)) and not e.prov:
            self.add("FATAL", "prov_missing", f"printed entry '{lid}' (src {e.src}) has no prov", where=f"ledger.{lid}")
        if not marked or lid in self.seen_open:
            return
        self.seen_open.add(lid)
        if e.q:
            self.add("OPEN", "open_value", f"{lid} = {fmt_ftin(v)} ({e.src}) {e.note or ''}".rstrip(),
                     e.q, f"ledger.{lid}")


def _sqrt_sum(ts: list[float]) -> float:
    return math.inf if math.inf in ts else math.sqrt(sum(x * x for x in ts))


def _closure(c: _Ctx, level_id: str, label: str, err: float, legs) -> None:
    where = f"{level_id}.{label}"
    if err <= CLOSE_TOL:
        c.add("INFO", "closure_ok", f"{label} closes (residual {err:.2f} in)", where=where)
        return
    q = next((c.led.entries[i].q for _, v in legs for i in c.led.ids_in(v) if c.led.entries[i].q), None)
    msg = f"{label} legs don't close by {err:.2f} in (out of square)"
    if q:
        c.add("OPEN", "room_out_of_square", msg, q, where)
    else:
        c.add("FATAL", "room_open_no_q", f"{msg}; no leg carries a q", where=where)


def _dup(c: _Ctx, ids: list[str], kind: str, where: str) -> None:
    for i in sorted({i for i in ids if ids.count(i) > 1}):
        c.add("FATAL", "duplicate_id", f"duplicate {kind} id '{i}'", where=where)


def _check_gaps(c: _Ctx, lv, g) -> None:
    led, lid = c.led, lv.id
    p, ext_t = led.value(lv.partition), led.value(lv.exterior_wall)
    for gap in g.gaps:
        if gap.kind not in ("absorbed", "thin"):
            continue
        key = f"{gap.a}|{gap.b}"
        q = lv.gap_q_pairs.get(key) or lv.gap_q
        if gap.b == "envelope":
            msg = f"{key} exterior wall {ext_t + gap.d:.2f} in derived vs {lv.exterior_wall} {ext_t:.2f} in"
        else:
            msg = f"{key} wall {gap.d:.2f} in derived vs {lv.partition} {p:.2f} in"
        if q:
            c.add("OPEN", "wall_absorbed", msg, q, f"{lid}.{key}")
        else:
            c.add("FATAL", "gap_no_q", f"{msg}; no gap_q for this pair", where=f"{lid}.{key}")
    for z in g.zones:
        pt = z.representative_point()
        q = next((lb.q for lb in lv.labels if lb.q and z.contains(Point(lb.at))), None)
        msg = f"unmeasured zone near ({pt.x:.0f}, {pt.y:.0f}) in, {z.area / 144:.1f} ft2"
        if q:
            c.add("OPEN", "zone_unmeasured", msg, q, f"{lid}.zone")
        else:
            c.add("FATAL", "zone_no_q", f"{msg}; no labelled point with a q inside", where=f"{lid}.zone")


def _check_level(c: _Ctx, lv) -> None:
    lid, led = lv.id, c.led
    n0 = c.rep.n("FATAL")
    for what, ref in (("exterior wall", lv.exterior_wall), ("partition", lv.partition)):
        if c.ident(ref, f"{lid}.{what}"):
            c.print_value(lid, what, ref)
    if lv.ceiling:
        c.ident(lv.ceiling, f"{lid}.ceiling")
    rooms = {r.id: r for r in lv.rooms}
    _dup(c, [r.id for r in lv.rooms], "room", lid)
    _dup(c, [o.id for o in lv.openings], "opening", lid)
    paths = [("envelope", lv.envelope.origin, lv.envelope.path)] + [(r.id, r.origin, r.path) for r in lv.rooms]
    for label, origin, path in paths:
        if len(path) < 3:
            c.add("FATAL", "bad_path", f"{label} path needs at least 3 legs", where=f"{lid}.{label}")
        for x in origin:
            c.val(x, f"{lid}.{label}.origin")
        for _, v in path:
            c.val(v, f"{lid}.{label}.path")
    for r in lv.rooms:
        for i in r.dims or []:
            if c.ident(i, f"{lid}.{r.id}.dims"):
                c.print_value(lid, f"{r.id} dim", i)
        ceil = r.ceiling or lv.ceiling
        if r.ceiling:
            c.ident(r.ceiling, f"{lid}.{r.id}.ceiling")
        if ceil and ceil in led:
            c.print_value(lid, f"{r.id} ceiling", ceil)
    for w in lv.walls:
        for p in (w.a, w.b):
            for x in p:
                c.val(x, f"{lid}.{w.id}")
        if c.ident(w.thickness, f"{lid}.{w.id}.thickness"):
            c.print_value(lid, f"{w.id} thickness", w.thickness)
    for o in lv.openings:
        where = f"{lid}.{o.id}"
        if o.room not in rooms:
            c.add("FATAL", "unknown_room", f"opening {o.id}: unknown room '{o.room}'", where=where)
            continue
        if not 0 <= o.edge < len(rooms[o.room].path):
            c.add("FATAL", "bad_edge", f"opening {o.id}: edge {o.edge} not in room {o.room}", where=where)
        c.val(o.offset, where)
        if c.ident(o.width, f"{where}.width"):
            c.print_value(lid, f"{o.id} width", o.width)
        if o.height and c.ident(o.height, f"{where}.height"):
            c.print_value(lid, f"{o.id} height", o.height)
        if o.position == "measured":
            for i in led.ids_in(o.offset):
                c.print_value(lid, f"{o.id} offset", i)
        if o.sill:
            if o.type != "window":
                c.add("FATAL", "sill_not_window", f"opening {o.id} is a {o.type}; only windows take a sill", where=where)
            elif c.ident(o.sill, f"{where}.sill"):
                c.print_value(lid, f"{o.id} sill", o.sill)
    for f in lv.fixtures:
        if f.room not in rooms:
            c.add("FATAL", "unknown_room", f"fixture {f.type}: unknown room '{f.room}'", where=lid)
        for what, ref in (("w", f.w), ("d", f.d)):
            if ref and c.ident(ref, f"{lid}.fixture.{what}"):
                c.print_value(lid, f"fixture {f.type} {what}", ref)
    _dup(c, [f.id for f in lv.furniture], "furniture", lid)
    for f in lv.furniture:
        if f.room not in rooms:
            c.add("FATAL", "unknown_room", f"furniture {f.id}: unknown room '{f.room}'", where=lid)
        for what, ref in (("w", f.w), ("d", f.d), ("h", f.h)):
            if ref:
                c.ident(ref, f"{lid}.{f.id}.{what}")
    for u in lv.unlocated:
        for what, ref in (("w", u.w), ("h", u.h)):
            if ref and c.ident(ref, f"{lid}.unlocated"):
                c.print_value(lid, f"unlocated {u.what.get('en') or u.what.get('fr')} {what}", ref)
    c.val(lv.absorb_max, f"{lid}.absorb_max")
    for q in (lv.gap_q, *lv.gap_q_pairs.values(), *(lb.q for lb in lv.labels)):
        c.check_q(q, lid)
    if c.rep.n("FATAL") > n0:
        return  # geometry needs a clean level

    g = build_level(c.plan, lid)
    for label, err in g.closure.items():
        legs = lv.envelope.path if label == "envelope" else rooms[label].path
        _closure(c, lid, label, err, legs)
    _check_gaps(c, lv, g)
    ids = list(g.rooms)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            ov = g.rooms[a].intersection(g.rooms[b]).area
            if ov > AREA_TOL:
                c.add("FATAL", "room_overlap", f"rooms {a} and {b} overlap by {ov:.1f} sq in", where=f"{lid}.{a}")
    for rid, poly in g.rooms.items():
        if not poly.is_valid:
            c.add("FATAL", "room_invalid", f"room {rid} polygon is self-intersecting", where=f"{lid}.{rid}")
            continue
        out = poly.difference(g.envelope).area
        if out > AREA_TOL:
            c.add("FATAL", "room_outside", f"room {rid} extends {out:.1f} sq in outside the envelope",
                  where=f"{lid}.{rid}")
    for o, og in zip(lv.openings, g.openings):
        coords = list(g.rooms[o.room].exterior.coords)
        leg = math.dist(coords[o.edge], coords[o.edge + 1])
        off = led.value(o.offset)
        where = f"{lid}.{o.id}"
        if og.width > leg + OPENING_TOL:
            c.add("FATAL", "opening_too_wide",
                  f"opening {o.id} width {og.width:.1f} in exceeds its wall ({leg:.1f} in)", where=where)
        elif off < -OPENING_TOL or off + og.width > leg + OPENING_TOL:
            c.add("FATAL", "opening_off_leg",
                  f"opening {o.id} spans {off:.1f}..{off + og.width:.1f} in on a {leg:.1f} in wall", where=where)
    c.rep.areas[lid] = {rid: poly.area for rid, poly in g.rooms.items()}
    _check_fit(c, lv, g)


FIT_TOL = 1.0  # sq in of overlap before it counts
WINDOW_NEAR = 6.0  # in: an item this close to a window sits in front of it


def _check_fit(c: _Ctx, lv, g) -> None:
    """FIT findings: furniture through a wall, in a door swing, on top of another item, or above a window sill."""
    if not lv.furniture:
        return
    led, lid = c.led, lv.id
    names = {r.id: r.name.get("en") or r.name.get("fr") or r.id for r in lv.rooms}
    floor = unary_union(list(g.rooms.values()))
    items = [(f, furniture_polygon(led, f)) for f in lv.furniture]
    fixed = [(f"{fx.type} in {names.get(fx.room, fx.room)}", fixture_polygon(led, fx)) for fx in lv.fixtures]
    for i, (f, fp) in enumerate(items):
        where = f"{lid}.{f.id}"
        out = fp.difference(floor)
        if out.area > FIT_TOL:
            reach = max(floor.distance(Point(p)) for p in fp.exterior.coords)
            c.add("FIT", "furniture_through_wall",
                  f"{f.id} ({f.type}) in {names.get(f.room, f.room)} runs {fmt_ftin(reach)} into a wall or unmeasured area", where=where)
        for og in g.openings:
            if og.type == "door":
                ov = fp.intersection(swing_polygon(og)).area
                if ov > FIT_TOL:
                    c.add("FIT", "furniture_blocks_door", f"{f.id} ({f.type}) is in the swing of door {og.id}", where=where)
            elif og.type == "window" and fp.distance(LineString([og.a, og.b])) <= WINDOW_NEAR:
                h = led.value(f.h) if f.h else None
                if og.sill is None:
                    c.add("FIT", "furniture_at_window_sill_unknown",
                          f"{f.id} ({f.type}) sits in front of window {og.id}, whose sill height is not measured", where=where)
                elif h is None:
                    c.add("FIT", "furniture_at_window_height_unknown",
                          f"{f.id} ({f.type}) sits in front of window {og.id} (sill {fmt_ftin(og.sill)}); its height is not given", where=where)
                elif h > og.sill:
                    c.add("FIT", "furniture_above_sill",
                          f"{f.id} ({f.type}) is {fmt_ftin(h)} tall, {fmt_ftin(h - og.sill)} above the sill of window {og.id}", where=where)
        for f2, fp2 in items[i + 1:]:
            if fp.intersection(fp2).area > FIT_TOL:
                c.add("FIT", "furniture_overlap", f"{f.id} ({f.type}) overlaps {f2.id} ({f2.type})", where=where)
        for what, xp in fixed:
            if fp.intersection(xp).area > FIT_TOL:
                c.add("FIT", "furniture_on_fixture", f"{f.id} ({f.type}) overlaps the {what}", where=where)


def _check_chains(c: _Ctx) -> None:
    levels = {lv.id for lv in c.plan.levels}
    for ch in c.plan.chains:
        where = f"chain {ch.id}"
        c.check_q(ch.q, where)
        if ch.level not in levels:
            c.add("FATAL", "unknown_level", f"chain {ch.id}: unknown level '{ch.level}'", where=where)
            continue
        vals = [c.val(x, where) for x in (*ch.parts, ch.total)]
        if any(v is None for v in vals):
            continue
        resid = sum(vals[:-1]) - vals[-1]
        tol = _sqrt_sum([c.led.tol(x, 0.0) for x in (*ch.parts, ch.total)])
        if abs(resid) > max(tol, CLOSE_FLOOR):
            # an open chain nobody will be asked about is untracked: refuse it
            c.add("OPEN" if ch.q else "FATAL", "chain_open" if ch.q else "chain_open_no_q",
                  f"chain {ch.id} off by {resid:+.2f} in (tolerance {tol:.2f})" + (f": {ch.note}" if ch.note else ""),
                  ch.q, where)
        else:
            c.add("INFO", "chain_ok", f"chain {ch.id} closes within tolerance (residual {resid:+.2f} in)", where=where)


def check(plan: Plan) -> Report:
    """Run every checker rule over a loaded plan."""
    c = _Ctx(plan)
    _dup(c, [q.id for q in plan.questions], "question", "questions")
    _dup(c, [lv.id for lv in plan.levels], "level", "levels")
    for lid, e in plan.ledger.items():
        c.val(lid, f"ledger.{lid}")
        c.check_q(e.q, f"ledger.{lid}")
        if e.src in ("assumed", "rough") and not e.q:
            c.add("FATAL", "assumed_no_q", f"ledger entry '{lid}' (src {e.src}) has no q", where=f"ledger.{lid}")
    for lv in plan.levels:
        _check_level(c, lv)
    _check_chains(c)
    return c.rep


def check_path(path: str | Path) -> tuple[Plan | None, Report]:
    """Load and check a plan file; a schema error becomes a FATAL finding."""
    try:
        plan = load_plan(path)
    except PlanError as e:
        rep = Report()
        rep.findings.append(Finding("FATAL", "schema", str(e), where=str(path)))
        return None, rep
    return plan, check(plan)
