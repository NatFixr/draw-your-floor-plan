"""Derive level geometry (rooms, wall mass, openings) from a Plan."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import shapely
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.polygon import LinearRing
from shapely.ops import unary_union

from .model import Ledger, Plan

DIRS = {"E": (1.0, 0.0), "W": (-1.0, 0.0), "N": (0.0, 1.0), "S": (0.0, -1.0)}
_EPS = 1e-6
Geom = Polygon | MultiPolygon


@dataclass
class OpeningGeom:
    id: str
    type: str
    status: str
    position: str
    a: tuple[float, float]
    b: tuple[float, float]
    normal: tuple[float, float]
    depth: float
    width: float
    height: float | None
    hinge: str | None
    swing: str | None
    room: str
    sill: float | None = None


@dataclass
class Gap:
    a: str
    b: str  # room id or "envelope"
    d: float
    kind: str  # open | std | absorbed | thin | zone


@dataclass
class LevelGeom:
    level_id: str
    envelope: Polygon
    rooms: dict[str, Polygon]
    closure: dict[str, float]
    walls: dict[str, Geom]
    openings: list[OpeningGeom]
    unassigned: Geom
    zones: list[Polygon] = field(default_factory=list)
    zone_edges: list[LineString] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)


def trace(origin: tuple[float, float], legs: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Cumulative points for (dx, dy) legs starting at origin (len(legs)+1 points)."""
    pts = [origin]
    for dx, dy in legs:
        x, y = pts[-1]
        pts.append((x + dx, y + dy))
    return pts


def path_polygon(led: Ledger, origin, path) -> tuple[Polygon, float]:
    """Polygon (last point replaced by origin) and closure error in inches."""
    o = led.point(origin)
    legs = [(DIRS[d][0] * led.value(v), DIRS[d][1] * led.value(v)) for d, v in path]
    pts = trace(o, legs)
    return Polygon(pts[:-1]), math.dist(pts[-1], o)


def _polys(g) -> Geom:
    parts = [p for p in shapely.get_parts(g) if isinstance(p, Polygon) and not p.is_empty]
    if not parts:
        return Polygon()
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def _clean(g, min_area: float = 1e-3) -> Geom:
    parts = [p for p in shapely.get_parts(_polys(g)) if p.area >= min_area]
    if not parts:
        return Polygon()
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def _closing(g: Geom, r: float) -> Geom:
    return g.buffer(r, join_style="mitre").buffer(-r, join_style="mitre")


def _edges(poly: Polygon) -> list[tuple[str, float, float, float, int]]:
    """Axis-aligned edges as (axis, coord, lo, hi, outward sign along the perpendicular axis)."""
    c = list(poly.exterior.coords)
    ccw = LinearRing(c).is_ccw
    out = []
    for (x0, y0), (x1, y1) in zip(c, c[1:]):
        if abs(y1 - y0) < 1e-9 and abs(x1 - x0) > 1e-9:
            ux = 1 if x1 > x0 else -1
            out.append(("h", y0, min(x0, x1), max(x0, x1), -ux if ccw else ux))
        elif abs(x1 - x0) < 1e-9 and abs(y1 - y0) > 1e-9:
            uy = 1 if y1 > y0 else -1
            out.append(("v", x0, min(y0, y1), max(y0, y1), uy if ccw else -uy))
    return out


def _kind(d: float, env: bool, p: float, absorb: float) -> str:
    if env:
        return "std" if d <= 0.25 else "absorbed" if d <= absorb else "zone"
    if d <= 0.01:
        return "open"
    if abs(d - p) <= 0.25:
        return "std"
    if p + 0.25 < d <= p + absorb:
        return "absorbed"
    return "thin" if d < p - 0.25 else "zone"


def _gaps(rooms: dict[str, Polygon], env: Polygon, p: float, absorb: float) -> list[Gap]:
    """Facing edge pairs (room-room, room-envelope) with their separation."""
    redges = {rid: _edges(poly) for rid, poly in rooms.items()}
    eedges = _edges(env)
    found: dict[tuple[str, str, float], Gap] = {}

    def blocked(axis, lo, hi, c0, c1, skip) -> bool:
        if abs(c1 - c0) <= 0.01:
            return False
        a, b = sorted((c0, c1))
        box = Polygon([(lo, a), (hi, a), (hi, b), (lo, b)]) if axis == "h" else \
            Polygon([(a, lo), (b, lo), (b, hi), (a, hi)])
        return any(r.intersection(box).area > 1 for k, r in rooms.items() if k not in skip)

    for a, ea in redges.items():
        for ax, ca, lo, hi, sa in ea:
            for b, eb in list(redges.items()) + [("envelope", eedges)]:
                if b == a:
                    continue
                for bx, cb, lo2, hi2, sb in eb:
                    isenv = b == "envelope"
                    if bx != ax or (sb != sa if isenv else sb != -sa):
                        continue
                    s = (cb - ca) * sa
                    olo, ohi = max(lo, lo2), min(hi, hi2)
                    if s < -0.01 or ohi - olo < 1 or blocked(ax, olo, ohi, ca, cb, {a, b}):
                        continue
                    d = max(s, 0.0)
                    x, y = (a, b) if isenv or a < b else (b, a)
                    found.setdefault((x, y, round(d, 2)), Gap(x, y, d, _kind(d, isenv, p, absorb)))
    return list(found.values())


def _depth(mass: Geom, mid, n, probe: float) -> float:
    start = (mid[0] - n[0] * 0.01, mid[1] - n[1] * 0.01)
    end = (mid[0] + n[0] * probe, mid[1] + n[1] * probe)
    hit = LineString([start, end]).intersection(mass)
    lines = [g for g in shapely.get_parts(hit) if isinstance(g, LineString) and g.length > 0]
    if not lines:
        return 0.5
    lines.sort(key=lambda g: min(math.dist(start, c) for c in g.coords))
    return max(lines[0].length, 1.0)


def build_level(plan: Plan, level_id: str) -> LevelGeom:
    """Build rooms, wall mass (openings cut) and opening geometry for one level."""
    lv = plan.level(level_id)
    led = plan.resolver()
    env, env_err = path_polygon(led, lv.envelope.origin, lv.envelope.path)
    rooms: dict[str, Polygon] = {}
    closure = {"envelope": env_err}
    for r in lv.rooms:
        rooms[r.id], closure[r.id] = path_polygon(led, r.origin, r.path)
    ext_t, p = led.value(lv.exterior_wall), led.value(lv.partition)
    room_union = unary_union(list(rooms.values())) if rooms else Polygon()

    absorb = led.value(lv.absorb_max)
    ext = env.buffer(ext_t, join_style="mitre") - env
    fills = []
    if rooms:
        r1 = (p + absorb) / 2 + 0.01
        r2 = absorb / 2 + 0.01
        fills.append(_closing(room_union, r1) & env)
        fills.append(_closing(unary_union([*rooms.values(), ext]), r2) & env)
    part = unary_union(fills) - room_union if fills else Polygon()
    sets: dict[str, list] = {"existing": [ext, part], "new": [], "demolish": []}
    removed = []
    for w in lv.walls:
        line = LineString([led.point(w.a), led.point(w.b)])
        poly = line.buffer(led.value(w.thickness) / 2, cap_style="flat")
        sets[w.status].append(poly)
        if w.status != "existing":
            removed.append(poly)
    existing = unary_union(sets["existing"])
    if removed:
        existing = existing - unary_union(removed)
    walls: dict[str, Geom] = {
        "existing": _clean(existing),
        "new": _clean(unary_union(sets["new"])) if sets["new"] else Polygon(),
        "demolish": _clean(unary_union(sets["demolish"])) if sets["demolish"] else Polygon(),
    }
    mass = unary_union([g for g in walls.values() if not g.is_empty])
    unassigned = _clean(env - room_union - mass)
    zones = [z for z in shapely.get_parts(unassigned) if z.area >= 6 and not z.buffer(-0.25).is_empty]
    envb = env.exterior.buffer(1e-4)
    zone_edges: list[LineString] = []
    for z in zones:
        rest = z.boundary.difference(envb)
        if not rest.is_empty:
            zone_edges += [g for g in shapely.get_parts(shapely.line_merge(rest)) if g.length > 1e-3]
    gaps = _gaps(rooms, env, p, absorb)

    ops: list[OpeningGeom] = []
    probe = ext_t + 2 * p + 2
    for o in lv.openings:
        coords = list(rooms[o.room].exterior.coords)
        v0, v1 = coords[o.edge], coords[o.edge + 1]
        length = math.dist(v0, v1)
        u = ((v1[0] - v0[0]) / length, (v1[1] - v0[1]) / length)
        ccw = LinearRing(coords).is_ccw
        n = (u[1], -u[0]) if ccw else (-u[1], u[0])
        off, width = led.value(o.offset), led.value(o.width)
        a = (v0[0] + u[0] * off, v0[1] + u[1] * off)
        b = (a[0] + u[0] * width, a[1] + u[1] * width)
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        depth = _depth(mass, mid, n, probe)
        ops.append(OpeningGeom(
            id=o.id, type=o.type, status=o.status, position=o.position, a=a, b=b, normal=n,
            depth=depth, width=width, height=led.value(o.height) if o.height else None,
            hinge=o.hinge if o.type == "door" else None,
            swing=o.swing if o.type == "door" else None, room=o.room,
            sill=led.value(o.sill) if o.sill else None))
    for og in ops:
        d = og.depth
        rect = Polygon([
            (og.a[0] - og.normal[0] * _EPS, og.a[1] - og.normal[1] * _EPS),
            (og.b[0] - og.normal[0] * _EPS, og.b[1] - og.normal[1] * _EPS),
            (og.b[0] + og.normal[0] * (d + _EPS), og.b[1] + og.normal[1] * (d + _EPS)),
            (og.a[0] + og.normal[0] * (d + _EPS), og.a[1] + og.normal[1] * (d + _EPS)),
        ])
        walls = {k: (g.difference(rect) if not g.is_empty else g) for k, g in walls.items()}
    walls = {k: _clean(g, 0.0) for k, g in walls.items()}
    return LevelGeom(level_id, env, rooms, closure, walls, ops, unassigned, zones, zone_edges, gaps)


def door_swing(og: OpeningGeom):
    """Hinge point, open-leaf direction s, closed-leaf direction u, and the swing arc angles (deg)."""
    n, d, a, b = og.normal, og.depth, og.a, og.b
    a2, b2 = (a[0] + n[0] * d, a[1] + n[1] * d), (b[0] + n[0] * d, b[1] + n[1] * d)
    inside = og.swing == "in"
    h_face, f_face = (a, b) if og.hinge == "start" else (b, a)
    h_far, f_far = (a2, b2) if og.hinge == "start" else (b2, a2)
    base = h_face if inside else h_far
    free = f_face if inside else f_far
    s = (-n[0], -n[1]) if inside else n
    w = og.width
    u = ((free[0] - base[0]) / w, (free[1] - base[1]) / w)
    aT = math.degrees(math.atan2(s[1], s[0]))
    aF = math.degrees(math.atan2(u[1], u[0]))
    a0, a1 = (aT, aT + 90) if abs(((aF - aT) % 360) - 90) < 1 else (aF, aF + 90)
    return base, s, u, a0, a1


def sector(c, r, a0, a1, n=24) -> Polygon:
    """Circular sector polygon, angles in degrees."""
    pts = [c]
    for i in range(n + 1):
        t = math.radians(a0 + (a1 - a0) * i / n)
        pts.append((c[0] + r * math.cos(t), c[1] + r * math.sin(t)))
    return Polygon(pts)


def swing_polygon(og: OpeningGeom) -> Polygon:
    """Floor area a door sweeps."""
    base, _, _, a0, a1 = door_swing(og)
    return sector(base, og.width, a0, a1)


def item_frame(at, rot: float, w: float, d: float):
    """loc(u, v) for an item centred at `at`: u along its back, v from the back towards its front."""
    th = math.radians(rot)
    bk = (math.sin(th), math.cos(th))
    al = (math.cos(th), -math.sin(th))
    cx, cy = at

    def loc(u_, v_):
        return (cx + al[0] * u_ + bk[0] * (d / 2 - v_), cy + al[1] * u_ + bk[1] * (d / 2 - v_))
    return loc


def item_polygon(at, rot: float, w: float, d: float) -> Polygon:
    """Footprint of a fixture or furniture item."""
    loc = item_frame(at, rot, w, d)
    return Polygon([loc(-w / 2, 0), loc(w / 2, 0), loc(w / 2, d), loc(-w / 2, d)])


FIXTURE_DEFAULT = {"toilet": (15, 28), "sink": (24, 20), "tub": (60, 30), "shower": (36, 36), "range": (30, 26),
                   "fridge": (30, 30), "washer": (27, 27), "dryer": (27, 27), "counter": (24, 24)}


def fixture_polygon(led: Ledger, fx) -> Polygon:
    dw, dd = FIXTURE_DEFAULT[fx.type]
    return item_polygon(fx.at, fx.rot, led.value(fx.w) if fx.w else float(dw), led.value(fx.d) if fx.d else float(dd))


def furniture_polygon(led: Ledger, f) -> Polygon:
    return item_polygon(f.at, f.rot, led.value(f.w), led.value(f.d))
