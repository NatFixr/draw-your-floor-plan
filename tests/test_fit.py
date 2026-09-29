"""Furniture fit checks and window sills."""
from pathlib import Path

import yaml

from floorplan.checker import check_path
from floorplan.render.sheets import build_sheet
from floorplan.checker import check
from floorplan.model import load_plan

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "cottage" / "plan.yaml"


def _run(tmp_path, edit):
    d = yaml.safe_load(EXAMPLE.read_text())
    edit(d)
    p = tmp_path / "plan.yaml"
    p.write_text(yaml.safe_dump(d, allow_unicode=True))
    plan, rep = check_path(p)
    assert plan is not None and rep.ok, [f.msg for f in rep.findings if f.level == "FATAL"]
    return {f.code for f in rep.findings if f.level == "FIT"}


def _furn(d):
    return d["levels"][0]["furniture"]


def test_example_fits(tmp_path):
    assert _run(tmp_path, lambda d: None) == set()


def test_through_wall(tmp_path):
    def e(d):
        _furn(d)[2]["at"] = [20, 200]  # bed pushed into the west wall
    assert "furniture_through_wall" in _run(tmp_path, e)


def test_blocks_door(tmp_path):
    def e(d):
        _furn(d)[1]["at"] = [60, 20]  # coffee table in the entry door swing
    assert "furniture_blocks_door" in _run(tmp_path, e)


def test_overlap(tmp_path):
    def e(d):
        _furn(d)[1]["at"] = [150, 80]  # table on the sofa
    assert "furniture_overlap" in _run(tmp_path, e)


def test_on_fixture(tmp_path):
    def e(d):
        _furn(d).append({"id": "F9", "type": "chair", "room": "R3", "at": [215, 226], "w": "ctab_d", "d": "ctab_d"})
    assert "furniture_on_fixture" in _run(tmp_path, e)


def test_window_sill(tmp_path):
    def high(d):
        f = _furn(d)[0]
        f.update(at=[282, 60], rot=90)  # sofa against the east wall, in front of W2 (sill 30)
        d["ledger"]["sofa_h"]["v"] = 34
    assert "furniture_above_sill" in _run(tmp_path, high)

    def low(d):
        _furn(d)[0].update(at=[282, 60], rot=90)
        d["ledger"]["sofa_h"]["v"] = 28
    assert "furniture_above_sill" not in _run(tmp_path, low)

    def unknown(d):
        _furn(d)[0].update(at=[282, 60], rot=90)
        for o in d["levels"][0]["openings"]:
            o.pop("sill", None)
    assert "furniture_at_window_sill_unknown" in _run(tmp_path, unknown)


def test_sill_on_door_is_fatal(tmp_path):
    d = yaml.safe_load(EXAMPLE.read_text())
    d["levels"][0]["openings"][0]["sill"] = "w1_s"
    p = tmp_path / "plan.yaml"
    p.write_text(yaml.safe_dump(d, allow_unicode=True))
    _, rep = check_path(p)
    assert any(f.code == "sill_not_window" for f in rep.findings)


def test_sill_in_schedule_and_furniture_drawn():
    plan = load_plan(EXAMPLE)
    sh, _ = build_sheet(plan, check(plan), "main", "builder", "en")
    tags = {getattr(i, "tag", "") for i in sh.items}
    assert {"furniture:F1", "furniture:F2", "furniture:F3"} <= tags
    texts = [getattr(i, "text", "") for i in sh.items]
    assert "not measured" not in texts
    psh, _ = build_sheet(plan, check(plan), "main", "permit", "en")
    assert not any(str(getattr(i, "tag", "")).startswith("furniture:") for i in psh.items)
