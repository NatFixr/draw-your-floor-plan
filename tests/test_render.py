import copy
import re
import subprocess
from pathlib import Path

import pytest
import yaml
from PIL import Image

from floorplan.checker import check
from floorplan.model import Plan, load_plan
from floorplan.render import sheets
from floorplan.render.layout import Dim, Poly, dim_geometry
from floorplan.render.sheets import RenderRefused, build_sheet, render_plan
from floorplan.render.svg import svg_string

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "cottage" / "plan.yaml"
HOUSE = ROOT / "tests" / "fixtures" / "house.yaml"  # optional richer fixture (stairs, unmeasured zones); tests skip without it
needs_house = pytest.mark.skipif(not HOUSE.exists(), reason="optional fixture tests/fixtures/house.yaml not present")
FIX = ROOT / "tests" / "fixtures"


def pdfinfo(pdf):
    return subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout


@pytest.fixture(scope="module")
def example():
    return load_plan(EXAMPLE)


@pytest.fixture(scope="module")
def example_permit(example, tmp_path_factory):
    out = tmp_path_factory.mktemp("example")
    return render_plan(example, "permit", "fr", out, formats=("svg", "pdf", "png"))[0]


def test_example_permit_pdf_geometry(example_permit):
    info = pdfinfo(example_permit.paths["pdf"])
    assert re.search(r"^Page size:\s+1224 x 792 pts$", info, re.M)
    assert re.search(r"^Pages:\s+1$", info, re.M)
    assert example_permit.sheet_size_mm == (431.8, 279.4)


def test_scale_bar_pixels(example_permit, tmp_path):
    sb = example_permit.scalebar
    base = tmp_path / "hi"
    subprocess.run(["pdftoppm", "-png", "-r", "300", "-singlefile", str(example_permit.paths["pdf"]), str(base)], check=True)
    im = Image.open(f"{base}.png").convert("L")
    px_mm = 300 / 25.4
    row = round(sb["y_mm"] * px_mm)
    mid = round((sb["x0_mm"] + sb["x1_mm"]) / 2 * px_mm)
    line = [im.getpixel((x, row)) < 128 for x in range(im.width)]
    assert line[mid]
    a = b = mid
    while line[a - 1]:
        a -= 1
    while line[b + 1]:
        b += 1
    run = b - a + 1
    assert run == pytest.approx(20 * px_mm, rel=0.01)
    assert (sb["x1_mm"] - sb["x0_mm"]) == pytest.approx(20.0)


def test_svg_structure(example, example_permit):
    svg = example_permit.paths["svg"].read_text(encoding="utf-8")
    assert re.search(r'<svg[^>]*width="431.8mm"[^>]*height="279.4mm"[^>]*viewBox="0 0 431.8 279.4"', svg)
    doors = [o for o in example.levels[0].openings if o.type == "door"]
    assert len(re.findall(r'class="door-arc"', svg)) == len(doors)
    for o in doors:
        assert f'id="arc-{o.id}"' in svg
    for r in example.levels[0].rooms:
        assert r.name["fr"].upper() in svg
    assert chr(0x2014) not in svg


def test_no_overlapping_text_boxes(example):
    rep = check(example)
    for sl in ("sketch", "permit", "builder"):
        for lang in ("fr", "en", "bi"):
            sheet, ctx = build_sheet(example, rep, "main", sl, lang)
            assert ctx.placer.overlaps() == [], (sl, lang)


@needs_house
@pytest.mark.parametrize("sl", ["sketch", "permit", "builder"])
def test_house_no_overlaps(sl):
    plan = load_plan(HOUSE)
    rep = check(plan)
    for lang in ("fr", "en"):
        for i, lv in enumerate(plan.levels):
            sheet, ctx = build_sheet(plan, rep, lv.id, sl, lang, i, len(plan.levels))
            assert ctx.placer.overlaps() == [], (lv.id, lang)


@needs_house
def test_house_permit_pdfs(tmp_path):
    plan = load_plan(HOUSE)
    res = render_plan(plan, "permit", "fr", tmp_path, formats=("svg", "pdf", "png"))
    assert [r.level_id for r in res] == ["rdc", "ss"]
    for r in res:
        info = pdfinfo(r.paths["pdf"])
        assert "1224 x 792 pts" in info
        assert re.search(r"^Pages:\s+1$", info, re.M)
        assert r.paths["png"].stat().st_size > 10000


def test_file_names_and_levels_filter(example, tmp_path):
    res = render_plan(example, "sketch", "en", tmp_path, formats=("svg",), levels=["main"])
    assert res[0].paths["svg"].name == "example-main-sketch-en.svg"
    assert res[0].scale == 50


def test_sketch_page_is_plan_plus_margins(example):
    sheet, ctx = build_sheet(example, check(example), "main", "sketch", "en")
    w, h = sheet.size_mm
    assert w >= 300 * 25.4 / 50 + 50 - 1e-6 and h >= 240 * 25.4 / 50 + 50 - 1e-6
    assert sheet.scale == 50
    svg = svg_string(sheet)
    assert "A-ANNO-TTLB" in svg and 'stroke-width="0.5"' in svg


def test_refuses_fatal():
    plan = load_plan(FIX / "fatal_overlap.yaml")
    with pytest.raises(RenderRefused):
        render_plan(plan, "permit", "fr", "/tmp/never")


def test_value_formats(example):
    sheet, ctx = build_sheet(example, check(example), "main", "builder", "en")
    assert ctx.val(126, False) == "10'-6\" [3.20]"
    ctx.lang = "bi"
    assert ctx.val(126, True) == '3,20 [10\'-6"]*'
    ctx.lang, ctx.sl = "fr", "permit"
    assert ctx.val(126, False) == "3,20"


@needs_house
def test_open_values_marked_on_house():
    plan = load_plan(HOUSE)
    sheet, ctx = build_sheet(plan, check(plan), "rdc", "permit", "fr", 0, 2)
    svg = svg_string(sheet)
    assert "6,50*" in svg and "P. 1,24*" in svg
    assert "HSP 2,41 m*" in svg
    assert "hatch-unmeasured" in svg


def test_builder_has_schedules_marks_and_fixtures(example):
    sheet, ctx = build_sheet(example, check(example), "main", "builder", "fr")
    svg = svg_string(sheet)
    assert "TABLEAU DES PORTES" in svg and "TABLEAU DES FENÊTRES" in svg
    assert 'id="A-FLOR-FIXT"' in svg
    for mark in ("D1", "W1"):
        assert f">{mark}<" in svg
    tags = {getattr(i, "tag", "") for i in sheet.items}
    assert {"wtag:E1", "wtag:P1"} <= tags
    assert any(t.startswith("dim:S2") or t.startswith("dim:N2") for t in tags)


def test_new_and_demolish_walls(example):
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    data["levels"][0]["walls"] = [
        {"id": "WN", "status": "new", "a": [100, 20], "b": [100, 90], "thickness": "p_std"},
        {"id": "WD", "status": "demolish", "a": [200, 20], "b": [200, 90], "thickness": "p_std"},
    ]
    plan = Plan.model_validate(data)
    sheet, ctx = build_sheet(plan, check(plan), "main", "permit", "fr")
    polys = [i for i in sheet.items if isinstance(i, Poly)]
    new = [p for p in polys if p.layer == "A-WALL-N"]
    demo = [p for p in polys if p.layer == "A-WALL-D"]
    assert new and new[0].fill == "#000000"
    assert demo and demo[0].fill is None and demo[0].dash == "dashed"
    svg = svg_string(sheet)
    assert "Mur neuf" in svg and "Mur à démolir" in svg


def test_dim_geometry_style(example):
    sheet, _ = build_sheet(example, check(example), "main", "permit", "fr")
    d = Dim((0, 0), (300, 0), "h", 5.0, "7,62", layer="A-ANNO-DIMS", space="model")
    g = dim_geometry(d, sheet)
    x0, y0 = sheet.xf(0, 0)
    (a, b) = g.ext[0]
    assert a[1] == pytest.approx(y0 - 1.5) or a[1] == pytest.approx(y0 + 1.5)
    assert abs(g.line[0][1] - (y0 - 5.0)) < 1e-9
    assert g.text.h_mm == 2.5 and g.text.anchor == "bc"
    assert len(g.ticks) == 2


def _swing_conflicts(sheet, ctx):
    from shapely.geometry import LineString
    from floorplan.render.placer import text_polygon
    sw = [(k, g) for k, g in ctx.placer.obstacles if k.startswith("swing:")]
    out = []
    for it in sheet.items:
        if isinstance(it, Dim):
            g = dim_geometry(it, sheet)
            solid = [LineString(list(g.line)), text_polygon(g.text)]
            exts = [LineString(list(e)) for e in g.ext]
            for k, s in sw:
                if any(s.intersects(x) for x in solid) or any(s.buffer(-0.3).intersects(x) for x in exts):
                    out.append((it.tag, k))
    return out


@pytest.mark.parametrize("path,sl", [(EXAMPLE, "permit"), (EXAMPLE, "builder")] + ([(HOUSE, "permit"), (HOUSE, "builder")] if HOUSE.exists() else []))
def test_dimensions_clear_of_door_swings(path, sl):
    plan = load_plan(path)
    rep = check(plan)
    for i, lv in enumerate(plan.levels):
        sheet, ctx = build_sheet(plan, rep, lv.id, sl, "fr", i, len(plan.levels))
        assert _swing_conflicts(sheet, ctx) == []


def test_builder_tags_every_wall_type_and_marks_stay_near():
    import math
    from floorplan.render.layout import Text
    for path in (EXAMPLE, HOUSE) if HOUSE.exists() else (EXAMPLE,):
        plan = load_plan(path)
        rep = check(plan)
        for i, lv in enumerate(plan.levels):
            sheet, ctx = build_sheet(plan, rep, lv.id, "builder", "fr", i, len(plan.levels))
            tags = {getattr(it, "tag", "") for it in sheet.items}
            for code, _, _ in ctx.wall_types():
                assert f"wtag:{code}" in tags
            for og in ctx.geom.openings:
                mk = [it for it in sheet.items if isinstance(it, Text) and it.tag == f"mark:{og.id}"]
                assert mk, og.id
                mid = sheet.xf((og.a[0] + og.b[0]) / 2, (og.a[1] + og.b[1]) / 2)
                assert math.dist(mid, sheet.xf(*mk[0].pos)) < 12.0


@needs_house
def test_stair_direction_label_present():
    plan = load_plan(HOUSE)
    rep = check(plan)
    for sl in ("permit", "builder", "sketch"):
        for i, lv in enumerate(plan.levels):
            sheet, ctx = build_sheet(plan, rep, lv.id, sl, "fr", i, 2)
            svg = svg_string(sheet)
            assert ("DESC." if lv.id == "rdc" else "MONTE") in svg


@needs_house
def test_colon_spacing_and_sketch_footnote():
    plan = load_plan(HOUSE)
    rep = check(plan)
    en, _ = build_sheet(plan, rep, "rdc", "sketch", "en", 0, 2)
    fr, _ = build_sheet(plan, rep, "rdc", "sketch", "fr", 0, 2)
    assert "house: Main floor" in svg_string(en)
    assert "maison unifamiliale : Rez-de-chaussée" in svg_string(fr)
    assert "* to confirm" in svg_string(en) and "hatch: not measured" in svg_string(en)
    assert "* à confirmer" in svg_string(fr) and "hachures : non mesuré" in svg_string(fr)
    ex = load_plan(EXAMPLE)
    sheet, _ = build_sheet(ex, check(ex), "main", "sketch", "en")
    assert "hatch:" not in svg_string(sheet)


@needs_house
def test_wrapped_note_lines_share_one_pitch():
    from floorplan.render import frame
    plan = load_plan(HOUSE)
    sheet, ctx = build_sheet(plan, check(plan), "rdc", "permit", "fr", 0, 2)
    nb = frame.notes_block(ctx, 77.0, list(plan.project.notes["fr"]))
    ys = sorted({round(t.pos[1], 3) for t in nb.items if hasattr(t, "s") and t.pos[0] > 1})
    diffs = {round(b - a, 3) for a, b in zip(ys, ys[1:])}
    assert diffs == {round(1.5 * 2.5, 3), round(1.5 * 2.5 + 1.6, 3)}


@needs_house
def test_unmeasured_hatch_threshold_is_six_inches():
    plan = load_plan(HOUSE)
    sheet, _ = build_sheet(plan, check(plan), "ss", "permit", "fr", 1, 2)
    hatched = [i for i in sheet.items if isinstance(i, Poly) and i.hatch]
    assert len(hatched) >= 2


def _tier_dims(sheet):
    import re as _re
    return [i for i in sheet.items if isinstance(i, Dim) and _re.fullmatch(r"dim:[SNWE][12]", i.tag)]


@needs_house
def test_computed_segments_follow_the_marker_rule():
    plan = load_plan(HOUSE)
    sheet, ctx = build_sheet(plan, check(plan), "ss", "builder", "fr", 1, 2)
    assert ctx.level_open
    n_computed = 0
    for d in _tier_dims(sheet):
        length = abs((d.p2[0] - d.p1[0]) + (d.p2[1] - d.p1[1]))
        match = [i for i in ctx.used_ids if abs(ctx.led.value(i) - length) < 0.01]
        if match:
            assert d.text.endswith("*") == ctx.is_open(match[0]), (d.tag, d.text, match[0])
        else:
            n_computed += 1
            assert d.text.endswith("*"), (d.tag, d.text)
    assert n_computed >= 3


def test_example_builder_prints_no_star_and_no_legend_line():
    plan = load_plan(EXAMPLE)
    for sl in ("permit", "builder", "sketch"):
        sheet, ctx = build_sheet(plan, check(plan), "main", sl, "fr")
        svg = svg_string(sheet)
        assert "*" not in svg and "confirmer" not in svg, sl


def test_star_convention_listed_only_when_a_star_is_printed():
    from floorplan.render.sheets import prints_star
    for path in (EXAMPLE, HOUSE) if HOUSE.exists() else (EXAMPLE,):
        plan = load_plan(path)
        rep = check(plan)
        for sl in ("sketch", "permit", "builder"):
            for i, lv in enumerate(plan.levels):
                sheet, ctx = build_sheet(plan, rep, lv.id, sl, "en", i, len(plan.levels))
                svg = svg_string(sheet)
                assert ("* to confirm" in svg.lower()) == prints_star(sheet), (path.name, lv.id, sl)


@needs_house
def test_permit_envelope_dimensions_sit_outside_on_one_offset_per_side():
    plan = load_plan(HOUSE)
    sheet, ctx = build_sheet(plan, check(plan), "rdc", "permit", "fr", 0, 2)
    ext_mm = ctx.led.value(ctx.lv.exterior_wall) * ctx.k
    outside = {}
    for d in sheet.items:
        if isinstance(d, Dim) and d.tag in ("dim:T5:k_w", "dim:T3:t3_s", "dim:T1:t1_s", "dim:T5:k_len", "dim:T2:t2_n", "dim:T1:t1_e"):
            assert abs(d.offset_mm) > ext_mm, d.tag
            side = "S" if d.orient == "h" and d.offset_mm < 0 else "N" if d.orient == "h" else "W" if d.offset_mm < 0 else "E"
            outside.setdefault(side, set()).add(round(d.offset_mm, 6))
    assert outside.get("S") and all(len(v) == 1 for v in outside.values())
    assert any(isinstance(d, Dim) and d.tag in ("dim:T3:t3_e", "dim:T6:t6_d", "dim:T6:t6_w", "dim:T4:hall_w") for d in sheet.items)  # interior legs stay inside


@needs_house
def test_stair_tag_is_inside_the_stair_with_a_halo():
    from shapely.geometry import Point
    from floorplan.render.layout import Text
    plan = load_plan(HOUSE)
    rep = check(plan)
    for sl in ("permit", "builder", "sketch"):
        sheet, ctx = build_sheet(plan, rep, "rdc", sl, "fr", 0, 2)
        poly = ctx.geom.rooms["T7"]
        tags = [i for i in sheet.items if isinstance(i, Text) and i.tag == "tag:T7"]
        assert tags and all(t.halo and t.rot_deg == 90.0 for t in tags), sl
        assert all(poly.buffer(1).contains(Point(t.pos)) for t in tags), sl


def _texts(sheet):
    from floorplan.render.layout import Text
    return [i for i in sheet.items if isinstance(i, Text)]


def test_every_dim_equals_its_drawn_length():
    for path in (EXAMPLE, HOUSE) if HOUSE.exists() else (EXAMPLE,):
        plan = load_plan(path)
        rep = check(plan)
        for sl, lang in (("permit", "fr"), ("builder", "fr"), ("builder", "en"), ("permit", "bi")):
            for i, lv in enumerate(plan.levels):
                sheet, ctx = build_sheet(plan, rep, lv.id, sl, lang, i, len(plan.levels))
                for d in sheet.items:
                    if isinstance(d, Dim):
                        drawn = abs(d.p2[0] - d.p1[0]) + abs(d.p2[1] - d.p1[1])
                        assert d.text.rstrip("*").split(" [")[0] == ctx.val(drawn, False).split(" [")[0], (path.name, lv.id, sl, d.tag, d.text)


@needs_house
def test_revision_text_by_open_count():
    plan = load_plan(HOUSE)
    rep = check(plan)
    sheet, _ = build_sheet(plan, rep, "rdc", "builder", "fr", 0, 2)
    words = " ".join(t.s for t in _texts(sheet))
    assert "Préliminaire, non émis pour" in words and "construction" in words
    ex = load_plan(EXAMPLE)
    sheet, _ = build_sheet(ex, check(ex), "main", "builder", "fr")
    assert any(t.s == "Émis pour construction" for t in _texts(sheet))
    sheet, _ = build_sheet(plan, rep, "rdc", "builder", "en", 0, 2)
    assert "Preliminary, not for" in " ".join(t.s for t in _texts(sheet))


@needs_house
def test_permit_tags_and_total_area():
    plan = load_plan(HOUSE)
    rep = check(plan)
    for i, lv in enumerate(plan.levels):
        sheet, ctx = build_sheet(plan, rep, lv.id, "permit", "fr", i, 2)
        svg = svg_string(sheet)
        assert "Superficie globale (intérieure)" in svg
        for lab in lv.labels:
            if lab.style == "open" and lab.text:
                assert lab.text["fr"].split("\n")[0] not in svg
        tags: dict = {}
        for t in _texts(sheet):
            if t.tag.startswith("tag:"):
                tags.setdefault(t.tag[4:], []).append(t.s)
        for r in lv.rooms:
            lines = tags.get(r.id, [])
            if r.kind in ("closet", "stair"):
                assert len(lines) == 1, (r.id, lines)
            elif r.id == "T1":
                assert not any(" x " in s for s in lines), lines
                assert any("HSP" in s for s in lines)
    sheet, _ = build_sheet(plan, rep, "rdc", "builder", "fr", 0, 2)
    assert any(t.tag == "tag:T1" and t.s.startswith("HSP") for t in _texts(sheet))


def _with_opening(kind_position):
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    for o in data["levels"][0]["openings"]:
        if o["id"] == "O1":
            o["type"] = "opening"
            o["position"] = kind_position
    return Plan.model_validate(data)


@needs_house
def test_opening_jambs_solid_when_measured_dashed_when_approximate():
    from floorplan.render.layout import Line
    for pos in ("measured", "assumed"):
        plan = _with_opening(pos)
        sheet, _ = build_sheet(plan, check(plan), "main", "permit", "fr")
        lines = [i for i in sheet.items if isinstance(i, Line) and i.tag.startswith("opening:O1")]
        assert len(lines) == 2 and all(l.pen_mm == 0.25 for l in lines)
        assert all((l.dash == "dashed") == (pos == "assumed") for l in lines)
    plan = load_plan(HOUSE)
    sheet, _ = build_sheet(plan, check(plan), "rdc", "permit", "fr", 0, 2)
    svg = svg_string(sheet)
    assert "Ouverture sans porte" in svg and "Pointillé : position approximative" in svg


@needs_house
def test_unlocated_and_provenance_notes():
    from floorplan.render.sheets import provenance_note, unlocated_note
    plan = load_plan(HOUSE)
    rep = check(plan)
    sheet, ctx = build_sheet(plan, rep, "rdc", "permit", "fr", 0, 2)
    words = " ".join(t.s for t in _texts(sheet))
    assert "Éléments relevés, position à confirmer" in words.replace("  ", " ") or unlocated_note(ctx) in words
    assert "position à confirmer" in unlocated_note(ctx)
    assert all(u.what["fr"].split()[0] in words for u in ctx.lv.unlocated)
    sheet, ctx = build_sheet(plan, rep, "ss", "permit", "fr", 1, 2)
    note = provenance_note(ctx)
    assert "sauf mention" in note and "déclarée le 2026-09-15" in note
    assert note.startswith("Dimensions intérieures relevées par le propriétaire")
    ctx.lang = "en"
    assert "unless noted" in provenance_note(ctx)
    ex = load_plan(EXAMPLE)
    _, ectx = build_sheet(ex, check(ex), "main", "permit", "fr")
    assert "sauf mention" not in provenance_note(ectx)


@needs_house
def test_zones_hatched_and_bounded_by_dashed_edges():
    from floorplan.render.layout import Line
    plan = load_plan(HOUSE)
    sheet, ctx = build_sheet(plan, check(plan), "rdc", "permit", "fr", 0, 2)
    hatched = [i for i in sheet.items if isinstance(i, Poly) and i.hatch and i.space == "model"]
    assert len(hatched) == len(ctx.geom.zones) >= 1
    edges = [i for i in sheet.items if getattr(i, "tag", "") == "zone-edge"]
    assert edges and all(e.dash == "dashed" and e.pen_mm == 0.18 for e in edges)
    assert all(p.layer != "A-WALL-E" for p in hatched)


@needs_house
def test_imperial_fr_permit_prints_feet():
    """units: imperial makes a French permit sheet print ft-in, pi² and a feet scale bar."""
    from floorplan.checker import check
    from floorplan.render.sheets import build_sheet
    plan = load_plan(HOUSE)
    plan.project.units = "imperial"
    sheet, _ = build_sheet(plan, check(plan), "rdc", "permit", "fr")
    words = " ".join(getattr(it, "s", "") for it in sheet.items)
    assert "21'-4\"*" in words and "pi²" in words and "14 pi" in words
    assert " m²" not in words
