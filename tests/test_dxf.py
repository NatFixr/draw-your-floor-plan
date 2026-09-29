import math
from pathlib import Path

import ezdxf
import pytest
from ezdxf import recover

from floorplan.checker import check
from floorplan.geometry import build_level
from floorplan.model import load_plan
from floorplan.render import styles as S
from floorplan.render.layout import Arc, Circle, Dim, Line, Poly, RoomBoundary, Sheet, Text, dim_geometry
from floorplan.render.dxf import APPID, write_dxf

ROOT = Path(__file__).resolve().parent.parent
CASES = [("example", "permit", "fr"), ("example", "builder", "en"), ] + ([("house", "permit", "fr")] if (ROOT / "tests" / "fixtures" / "house.yaml").exists() else [])
NEEDED = ("A-WALL-E", "A-DOOR", "A-GLAZ", "A-ANNO-DIMS", "A-AREA")


def _plan(project):
    if project == "house":
        return load_plan(ROOT / "tests" / "fixtures" / "house.yaml")
    return load_plan(ROOT / "examples" / "cottage" / "plan.yaml")


def _tags(e):
    return [t.value for t in e.get_xdata(APPID)] if e.has_xdata(APPID) else []


def _paper_layouts(doc):
    return [ly for ly in doc.layouts if ly.name != "Model"]


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    render_plan = pytest.importorskip("floorplan.render.sheets", reason="renderer (sheets.py) not importable yet").render_plan
    out = {}
    for project, sl, lang in CASES:
        plan = _plan(project)
        d = tmp_path_factory.mktemp(f"{project}-{sl}-{lang}")
        out[(project, sl, lang)] = (plan, render_plan(plan, sl, lang, d, formats=("dxf",)))
    return out


@pytest.mark.parametrize("case", CASES)
def test_dxf_of_rendered_plan(rendered, case):
    plan, results = rendered[case]
    assert results
    for res in results:
        path = res.paths["dxf"]
        doc = ezdxf.readfile(path)
        aud = doc.audit()
        assert not aud.has_errors, [e.message for e in aud.errors]
        _, rec_aud = recover.readfile(path)
        assert not rec_aud.has_errors
        assert doc.header["$INSUNITS"] == 1
        assert doc.header["$LUNITS"] == (2 if case[2] == "fr" else 4)
        layers = {ly.dxf.name for ly in doc.layers}
        assert set(NEEDED) <= layers

        msp = doc.modelspace()
        geom = build_level(plan, res.level_id)
        found = {}
        for e in msp.query("LWPOLYLINE"):
            if e.dxf.layer == "A-AREA":
                (rid,) = _tags(e)
                found[rid] = [tuple(p) for p in e.get_points("xy")]
        assert set(found) == set(geom.rooms)
        for rid, poly in geom.rooms.items():
            want = list(poly.exterior.coords)[:-1]
            assert len(found[rid]) == len(want)
            for (x, y), (wx, wy) in zip(found[rid], want):
                assert abs(x - wx) < 1e-6 and abs(y - wy) < 1e-6

        dims = list(msp.query("DIMENSION"))
        assert dims
        assert all(d.dxf.dimstyle == "FP-ARCH" and d.dxf.layer == "A-ANNO-DIMS" for d in dims)

        (lay,) = _paper_layouts(doc)
        assert lay.name == f"{case[1].upper()}-{res.level_id}"
        assert (lay.dxf.paper_width, lay.dxf.paper_height) == pytest.approx(res.sheet_size_mm, abs=0.01)
        vps = [v for v in lay.viewports() if v.dxf.id != 1]
        assert len(vps) == 1
        vp = vps[0]
        assert vp.dxf.height / vp.dxf.view_height == pytest.approx(25.4 / res.scale, rel=0.005)
        assert any(e.dxf.layer == "A-ANNO-TTLB" for e in lay)


def test_dims_match_display_list(tmp_path):
    sheets = pytest.importorskip("floorplan.render.sheets", reason="renderer (sheets.py) not importable yet")
    plan = _plan("house" if (ROOT / "tests" / "fixtures" / "house.yaml").exists() else "example")
    sh, _ = sheets.build_sheet(plan, check(plan), plan.levels[0].id, "builder", "bi")
    path = tmp_path / "d.dxf"
    write_dxf(sh, path)
    doc = ezdxf.readfile(path)
    want = [d for d in sh.items if isinstance(d, Dim) and d.space == "model"]
    got = list(doc.modelspace().query("DIMENSION"))
    assert len(want) == len(got) > 0
    for d, e in zip(want, got):
        assert e.dxf.text == d.text
        g = dim_geometry(d, sh)
        (ax, ay), (bx, by) = (sh.inv(*p) for p in g.line)
        if d.orient == "h":
            assert e.dxf.defpoint.y == pytest.approx(ay, abs=1e-6)
        else:
            assert e.dxf.defpoint.x == pytest.approx(ax, abs=1e-6)
        t = g.text
        hx, hy = (0.0, S.H["dim"] / 2) if not t.rot_deg else (-S.H["dim"] / 2, 0.0)
        cx, cy = sh.inv(t.pos[0] + hx, t.pos[1] - hy)
        assert math.dist((e.dxf.text_midpoint.x, e.dxf.text_midpoint.y), (cx, cy)) * sh.k < 0.05


def _hand_sheet(lang="en"):
    sh = Sheet((431.8, 279.4), 50, ox=100.0, oy=200.0, level_id="rdc", sheet_level="permit", lang=lang, title="t")
    sq = [(0, 0), (100, 0), (100, 80), (0, 80)]
    hole = [(20, 20), (40, 20), (40, 40), (20, 40)]
    sh.add(
        Poly(sq, True, 0.5, "#5a5a5a", holes=[hole], layer="A-WALL-E", space="model", tag="wall:E1"),
        Poly(sq, True, 0.35, None, "dashed", layer="A-WALL-D", space="model"),
        Poly(sq, True, 0.0, None, None, "unmeasured", layer="A-AREA", space="model"),
        Line((0, 0), (10, 10), 0.13, "fine", layer="A-AREA", space="model", tag="open:R1:R2"),
        Arc((5, 5), 30, 0, 90, layer="A-DOOR", space="model", tag="door:D1"),
        Circle((50, 50), 6, layer="A-ANNO-SYMB", space="model"),
        Text((10, 10), "Kitchen\nHSP 2,44", 3.5, "mc", weight="bold", layer="A-AREA-IDEN", space="model"),
        Text((10, 10), "P. 0,86", 2.5, "bl", 90.0, layer="A-ANNO-TEXT", space="model"),
        Line((10, 10), (100, 10), 0.5, layer="X-NEW-LAYER", space="paper"),
        Text((20, 30), "TITLE", 5.0, "bl", layer="A-ANNO-TTLB"),
        Dim((0, 0), (100, 0), "h", 8.0, "8'-4\"*", layer="A-ANNO-DIMS", space="model", tag="dim:x"),
        RoomBoundary("R1", sq, layer="A-AREA", space="model"),
    )
    return sh


def test_hand_built_sheet(tmp_path):
    sh = _hand_sheet()
    path = tmp_path / "h.dxf"
    write_dxf(sh, path)
    doc = ezdxf.readfile(path)
    assert not doc.audit().has_errors
    msp = doc.modelspace()
    kinds = {e.dxftype() for e in msp}
    assert {"HATCH", "LWPOLYLINE", "LINE", "ARC", "CIRCLE", "TEXT", "MTEXT", "DIMENSION"} <= kinds
    solid = [h for h in msp.query("HATCH") if h.dxf.solid_fill]
    assert len(solid[0].paths) == 2 and solid[0].rgb == (0x5A, 0x5A, 0x5A)
    assert any(h.dxf.pattern_name == "ANSI31" for h in msp.query("HATCH"))
    dashed = [e for e in msp.query("LWPOLYLINE") if e.dxf.layer == "A-WALL-D"]
    assert dashed[0].dxf.linetype == "DASHED" and dashed[0].dxf.ltscale == pytest.approx(50 / 25.4)
    assert doc.layers.get("A-WALL-E").dxf.lineweight == 50 and doc.layers.get("A-WALL-N").dxf.lineweight == 70
    assert doc.layers.get("A-AREA").dxf.plot == 0
    assert doc.layers.get("X-NEW-LAYER").dxf.lineweight == 50
    (arc,) = msp.query("ARC")
    assert arc.dxf.radius == 30 and tuple(arc.dxf.center)[:2] == (5, 5) and _tags(arc) == ["door:D1"]
    mt = msp.query("MTEXT").first
    assert mt.dxf.char_height == pytest.approx(3.5 * 50 / 25.4) and mt.dxf.style == "FP-BOLD" and "\\P" in mt.text
    tx = msp.query("TEXT").first
    assert tx.dxf.rotation == 90 and tx.dxf.style == "FP"
    assert doc.styles.get("FP").dxf.font == "NotoSans-Regular.ttf"
    (room,) = [e for e in msp.query("LWPOLYLINE") if e.dxf.layer == "A-AREA"]
    assert _tags(room) == ["R1"]
    ds = doc.dimstyles.get("FP-ARCH")
    assert ds.dxf.dimscale == pytest.approx(50 / 25.4) and ds.dxf.dimtxt == 2.5 and ds.dxf.dimtad == 1
    assert ds.dxf.dimlunit == 4 and ds.dxf.dimlfac == 1.0
    (dm,) = msp.query("DIMENSION")
    assert dm.dxf.text == "8'-4\"*" and dm.dxf.defpoint.y == pytest.approx(8.0 * 50 / 25.4)
    (lay,) = _paper_layouts(doc)
    assert lay.name == "PERMIT-rdc" and "Layout1" not in doc.layouts
    assert any(e.dxf.layer == "X-NEW-LAYER" and e.dxftype() == "LINE" for e in lay)
    title = [e for e in lay if e.dxftype() == "TEXT"][0]
    assert tuple(title.dxf.insert)[:2] == (20, 279.4 - 30)
    vp = [v for v in lay.viewports() if v.dxf.id != 1][0]
    assert vp.dxf.height / vp.dxf.view_height == pytest.approx(25.4 / 50)


def test_fr_dimstyle_is_metric(tmp_path):
    path = tmp_path / "f.dxf"
    write_dxf(_hand_sheet("fr"), path)
    doc = ezdxf.readfile(path)
    ds = doc.dimstyles.get("FP-ARCH")
    assert doc.header["$LUNITS"] == 2
    assert (ds.dxf.dimlfac, ds.dxf.dimdec, ds.dxf.dimdsep, ds.dxf.dimlunit) == (0.0254, 2, ord(","), 2)
