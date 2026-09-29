import copy
import math
from pathlib import Path

import pytest
import yaml
from shapely.geometry import Polygon
from shapely.ops import unary_union

from floorplan.checker import check, check_path
from floorplan.cli import main
from floorplan.geometry import build_level
from floorplan.model import Ledger, LedgerError, LedgerEntry, Plan, PlanError, load_plan

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
EXAMPLE = ROOT / "examples" / "cottage" / "plan.yaml"


def codes(rep, level):
    return [f.code for f in rep.findings if f.level == level]


def mutated(name, fn):
    data = yaml.safe_load((FIX / name).read_text(encoding="utf-8"))
    fn(data)
    return Plan.model_validate(data)


def test_fixture_ok():
    rep = check(load_plan(FIX / "ok.yaml"))
    assert rep.ok and not codes(rep, "FATAL") and not codes(rep, "OPEN")


@pytest.mark.parametrize("name,code", [
    ("fatal_overlap.yaml", "room_overlap"),
    ("fatal_unknown_ref.yaml", "unknown_ref"),
    ("fatal_open_no_q.yaml", "room_open_no_q"),
])
def test_fatal_fixtures(name, code):
    _, rep = check_path(FIX / name)
    assert not rep.ok
    assert code in codes(rep, "FATAL")
    assert main(["check", str(FIX / name)]) == 2


def test_open_chain_fixture(capsys):
    _, rep = check_path(FIX / "open_chain.yaml")
    opens = [f for f in rep.findings if f.level == "OPEN"]
    assert rep.ok and [(f.code, f.q) for f in opens] == [("chain_open", "Q1")]
    assert main(["check", str(FIX / "open_chain.yaml")]) == 0
    assert "OPEN  [Q1]" in capsys.readouterr().out


def test_schema_error_is_fatal(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("project: {id: x}\nlevels: []\n")
    with pytest.raises(PlanError):
        load_plan(p)
    plan, rep = check_path(p)
    assert plan is None and codes(rep, "FATAL") == ["schema"]
    assert main(["check", str(p)]) == 2


def test_cycle_and_bad_value():
    def cyc(d):
        d["ledger"]["x"] = {"v": "=y + 1", "src": "derived"}
        d["ledger"]["y"] = {"v": "=x + 1", "src": "derived"}
        d["ledger"]["z"] = {"v": "banana!", "src": "tape"}
    rep = check(mutated("ok.yaml", cyc))
    assert "cycle" in codes(rep, "FATAL") and "bad_value" in codes(rep, "FATAL")


def test_assumed_printed_without_q_and_unknown_question():
    def m(d):
        d["ledger"]["a_w"]["src"] = "assumed"
        d["ledger"]["d_w"]["q"] = "Q9"
    rep = check(mutated("ok.yaml", m))
    assert {"assumed_no_q", "unknown_question"} <= set(codes(rep, "FATAL"))


def test_open_marked_entry_with_q_is_open():
    def m(d):
        d["ledger"]["a_w"]["q"] = "Q1"
        d["questions"] = [{"id": "Q1", "rank": 1, "title": "t"}]
    rep = check(mutated("ok.yaml", m))
    assert rep.ok
    assert [(f.code, f.q) for f in rep.findings if f.level == "OPEN"] == [("open_value", "Q1")]


def test_opening_geometry_faults():
    wide = check(mutated("ok.yaml", lambda d: d["ledger"]["d_w"].update(v=150)))
    assert "opening_too_wide" in codes(wide, "FATAL")
    off = check(mutated("ok.yaml", lambda d: d["levels"][0]["openings"][0].update(offset=90)))
    assert "opening_off_leg" in codes(off, "FATAL")


def test_room_outside_and_unknown_room():
    def m(d):
        d["levels"][0]["rooms"][1]["origin"] = [150, 0]
    rep = check(mutated("ok.yaml", m))
    assert "room_outside" in codes(rep, "FATAL")
    rep = check(mutated("ok.yaml", lambda d: d["levels"][0]["openings"][0].update(room="ZZ")))
    assert "unknown_room" in codes(rep, "FATAL")


def test_example_clean(capsys):
    assert main(["check", str(EXAMPLE)]) == 0
    assert capsys.readouterr().out.strip().endswith("0 FATAL, 0 OPEN, 0 FIT")


def test_example_areas():
    rep = check(load_plan(EXAMPLE))
    a = rep.areas["main"]
    assert a["R1"] == pytest.approx(300 * 110)
    assert a["R2"] == pytest.approx(180 * 125.5)
    assert a["R3"] == pytest.approx(115.5 * 125.5)
    assert len(rep.manifest) > 0


def test_example_swings_are_free():
    plan = load_plan(EXAMPLE)
    g = build_level(plan, "main")
    walls = unary_union(list(g.walls.values()))
    doors = [o for o in g.openings if o.type == "door"]
    assert len(doors) == 4
    for o in doors:
        hinge, other = (o.a, o.b) if o.hinge == "start" else (o.b, o.a)
        c = ((other[0] - hinge[0]) / o.width, (other[1] - hinge[1]) / o.width)
        s = -1 if o.swing == "in" else 1
        open_dir = (s * o.normal[0], s * o.normal[1])
        pts = [hinge] + [
            (hinge[0] + o.width * (math.cos(t) * c[0] + math.sin(t) * open_dir[0]),
             hinge[1] + o.width * (math.cos(t) * c[1] + math.sin(t) * open_dir[1]))
            for t in [i * math.pi / 40 for i in range(21)]]
        sector = Polygon(pts)
        assert sector.intersection(walls).area < 0.5, o.id
        assert sector.difference(g.envelope).area < 0.5, o.id


def test_example_geometry_is_closed():
    g = build_level(load_plan(EXAMPLE), "main")
    assert all(e < 1e-9 for e in g.closure.values())
    assert g.unassigned.area < 1e-3
    assert [o.depth for o in g.openings if o.id in ("D1", "W1")] == pytest.approx([6.5, 6.5])
    assert [o.depth for o in g.openings if o.id in ("D2", "D3", "O1")] == pytest.approx([4.5] * 3)


def test_partition_area_and_opening_cut():
    plan = load_plan(FIX / "ok.yaml")
    g = build_level(plan, "main")
    inside = g.walls["existing"].intersection(g.envelope).area
    # rooms are 100 tall and 4.5 apart: partition 4.5 x 100, minus the 30 in door cut
    assert inside == pytest.approx(4.5 * 100 - 30 * 4.5, abs=1.0)
    d = g.openings[0]
    assert d.depth == pytest.approx(4.5) and d.width == 30
    bare = copy.deepcopy(plan)
    bare.levels[0].openings = []
    gb = build_level(bare, "main")
    assert gb.walls["existing"].area - g.walls["existing"].area == pytest.approx(30 * 4.5, abs=1.0)


def test_explicit_walls_split_sets():
    def m(d):
        d["ledger"]["t"] = {"v": 4.5, "src": "tape"}
        d["levels"][0]["walls"] = [
            {"id": "W1", "status": "new", "a": [50, 10], "b": [50, 60], "thickness": "t"},
            {"id": "W2", "status": "demolish", "a": [102.25, 0], "b": [102.25, 100], "thickness": "t"},
        ]
    g = build_level(mutated("ok.yaml", m), "main")
    assert g.walls["new"].area == pytest.approx(50 * 4.5)
    assert g.walls["demolish"].area == pytest.approx(450 - 30 * 4.5, abs=1.0)  # door cut applies
    assert g.walls["existing"].intersection(g.envelope).area < 10


def test_ledger_resolution():
    L = Ledger({
        "a": LedgerEntry(v=10, src="tape"),
        "b": LedgerEntry(v="=a * 2 - (1 + 1) / 2", src="derived"),
        "c": LedgerEntry(v="1m", src="declared"),
    })
    assert L.value("b") == 19.0
    assert L.value("=-a + b") == 9.0
    assert L.value("c") == pytest.approx(39.37, abs=0.01)
    assert L.value("5'6\"") == 66.0
    assert L.tol("b") == 4.0 and L.tol("c") == 0.0
    for bad in ("=a ** 2", "=__import__('os')", "=a +", "=nope + 1", "nope"):
        with pytest.raises(LedgerError):
            L.value(bad)


def add_q(d, *ids):
    d["questions"] = [{"id": i, "rank": n, "title": i} for n, i in enumerate(ids, 1)]


def gap_finds(rep, code):
    return [(f.level, f.q) for f in rep.findings if f.code == code]


def test_r1_absorbed_gap():
    plan = load_plan(FIX / "gap_absorbed.yaml")
    rep = check(plan)
    assert rep.ok and gap_finds(rep, "wall_absorbed") == [("OPEN", "Q1")]
    g = build_level(plan, "main")
    assert [(x.kind, round(x.d, 2)) for x in g.gaps if x.a == "A" and x.b == "B"] == [("absorbed", 6.5)]
    # wall sits at the actual 6.5 in gap, minus the 30 in door cut
    assert g.walls["existing"].intersection(g.envelope).area == pytest.approx(6.5 * 100 - 30 * 6.5, abs=1.0)
    assert not g.zones
    bare = mutated("gap_absorbed.yaml", lambda d: d["levels"][0].update(gap_q=None))
    assert "gap_no_q" in codes(check(bare), "FATAL")
    pair = mutated("gap_absorbed.yaml", lambda d: d["levels"][0].update(
        gap_q=None, gap_q_pairs={"A|B": "Q1"}))
    assert gap_finds(check(pair), "wall_absorbed") == [("OPEN", "Q1")]


def test_r1_zone_never_invents_a_wall():
    plan = load_plan(FIX / "gap_zone.yaml")
    rep = check(plan)
    assert rep.ok and gap_finds(rep, "zone_unmeasured") == [("OPEN", "Q1")]
    assert not gap_finds(rep, "wall_absorbed")
    g = build_level(plan, "main")
    assert len(g.zones) == 1 and g.zones[0].area == pytest.approx(20 * 100)
    gap_box = Polygon([(100, 0), (120, 0), (120, 100), (100, 100)])
    assert sum(w.intersection(gap_box).area for w in g.walls.values()) == 0
    assert g.zone_edges and next(x.kind for x in g.gaps if x.b == "B") == "zone"
    assert g.openings[0].depth == 0.5

    def unlabel(d):
        d["levels"][0]["labels"] = []
    assert "zone_no_q" in codes(check(mutated("gap_zone.yaml", unlabel)), "FATAL")

    def noq(d):
        del d["levels"][0]["labels"][0]["q"]
    assert "zone_no_q" in codes(check(mutated("gap_zone.yaml", noq)), "FATAL")


def test_r2_out_of_square_is_open_with_leg_q():
    def m(d):
        d["ledger"]["sq_w"] = {"v": 99.5, "src": "tape", "q": "Q1"}
        d["levels"][0]["rooms"][0]["path"][2] = ["W", "sq_w"]
        add_q(d, "Q1")
    rep = check(mutated("ok.yaml", m))
    hit = [f for f in rep.findings if f.code == "room_out_of_square"]
    assert rep.ok and [(f.level, f.q) for f in hit] == [("OPEN", "Q1")]
    assert "0.50 in" in hit[0].msg


def test_r3_assumed_or_rough_needs_q_even_unprinted():
    for src in ("assumed", "rough"):
        rep = check(mutated("ok.yaml", lambda d: d["ledger"].update(spare={"v": 10, "src": src})))
        assert codes(rep, "FATAL") == ["assumed_no_q"]

    def with_q(d):
        d["ledger"]["spare"] = {"v": 10, "src": "assumed", "q": "Q1"}
        add_q(d, "Q1")
    assert check(mutated("ok.yaml", with_q)).ok


def test_r9_prov_missing():
    def declared(d):
        d["ledger"]["a_w"]["src"] = "declared"
    assert codes(check(mutated("ok.yaml", declared)), "FATAL") == ["prov_missing"]

    def with_prov(d):
        declared(d)
        d["ledger"]["a_w"]["prov"] = {"fr": "déclaré le {date}", "en": "declared {date}"}
    assert check(mutated("ok.yaml", with_prov)).ok

    def unprinted(d):
        d["ledger"]["spare"] = {"v": 1, "src": "declared"}
    assert check(mutated("ok.yaml", unprinted)).ok

    def derived_q(d):
        d["ledger"]["a_w"].update(src="derived", q="Q1")
        add_q(d, "Q1")
    assert "prov_missing" in codes(check(mutated("ok.yaml", derived_q)), "FATAL")


def test_unlocated_items_are_printed_values():
    def m(d):
        d["levels"][0]["unlocated"] = [
            {"what": {"fr": "fenêtre cachée", "en": "hidden window"}, "w": "d_w", "h": "a_w"}]
    rep = check(mutated("ok.yaml", m))
    assert rep.ok
    assert [x[2] for x in rep.manifest if x[1].startswith("unlocated")] == ["d_w", "a_w"]


def test_model_additions_and_open_count():
    def m(d):
        d["levels"][0]["rooms"][0]["dims"] = ["a_w"]
        d["levels"][0]["labels"] = [{"at": [10, 10], "style": "open"}]
    plan = mutated("ok.yaml", m)
    assert plan.project.surveyor["en"] == "the owner" and plan.levels[0].absorb_max == 3
    assert plan.levels[0].labels[0].text is None
    assert check(load_plan(FIX / "open_chain.yaml")).open_count == 1
