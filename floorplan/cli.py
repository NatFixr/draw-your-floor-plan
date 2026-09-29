"""fp command line: check | questions | render."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .checker import Report, check_path
from .model import Plan
from .units import fmt_area_ft2, fmt_area_m2


def _room_names(plan: Plan | None) -> dict[tuple[str, str], str]:
    if not plan:
        return {}
    return {(lv.id, r.id): r.name.get("en") or r.name.get("fr") or r.id for lv in plan.levels for r in lv.rooms}


def _text(plan: Plan | None, rep: Report, path: str, verbose: bool) -> str:
    out = [f"fp check {path}" + (f"  ({plan.project.id})" if plan else "")]
    for f in rep.findings:
        if f.level == "FATAL":
            out.append(f"FATAL  {f.code}  {f.msg}" + (f"  @ {f.where}" if f.where else ""))
        elif f.level == "OPEN":
            out.append(f"OPEN  [{f.q or '--'}]  {f.msg}")
        elif f.level == "FIT":
            out.append(f"FIT  {f.code}  {f.msg}")
        elif verbose:
            out.append(f"INFO  {f.code}  {f.msg}")
    names = _room_names(plan)
    for lid, rooms in rep.areas.items():
        out += ["", f"areas, level {lid}", f"  {'room':<8}{'name':<24}{'m2':>8}{'ft2':>8}"]
        for rid, a in rooms.items():
            out.append(f"  {rid:<8}{names.get((lid, rid), ''):<24}{fmt_area_m2(a):>8}{fmt_area_ft2(a):>8}")
    out += ["", f"manifest: {len(rep.manifest)} printed values", f"{rep.n('FATAL')} FATAL, {rep.n('OPEN')} OPEN, {rep.n('FIT')} FIT"]
    return "\n".join(out)


def _cmd_check(a: argparse.Namespace) -> int:
    plan, rep = check_path(a.plan)
    if a.json:
        print(json.dumps(rep.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(_text(plan, rep, a.plan, a.verbose))
    return 0 if rep.ok else 2


def _cmd_questions(a: argparse.Namespace) -> int:
    plan, rep = check_path(a.plan)
    if plan is None:
        print(_text(plan, rep, a.plan, False), file=sys.stderr)
        return 2
    md = [f"# Open questions: {plan.project.title.get('en') or plan.project.id}", ""]
    for q in sorted(plan.questions, key=lambda q: (q.rank, q.id)):
        md += [f"## {q.id}. {q.title}", ""]
        if q.measure:
            md.append(f"Measure: {q.measure}")
        if q.why:
            md.append(f"Unlocks: {q.why}")
        cited = [f for f in rep.findings if f.level == "OPEN" and f.q == q.id]
        md += ["", "Findings:" if cited else "No open findings cite this question."]
        md += [f"- {f.msg}" for f in cited]
        md.append("")
    text = "\n".join(md)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


def _cmd_render(a: argparse.Namespace) -> int:
    from floorplan.render.sheets import RenderRefused, render_plan

    plan, rep = check_path(a.plan)
    if plan is None or not rep.ok:
        print(_text(plan, rep, a.plan, False), file=sys.stderr)
        return 2
    sheets = ["sketch", "permit", "builder"] if a.level == "all" else [a.level]
    langs = ["fr", "en", "bi"] if a.lang == "all" else [a.lang]
    formats = tuple(f.strip() for f in a.formats.split(",") if f.strip())
    try:
        for sl in sheets:
            for lang in langs:
                for r in render_plan(plan, sl, lang, a.out, formats, a.levels):
                    print(f"{r.level_id} {sl} {lang} 1:{r.scale}: " + ", ".join(str(p) for p in r.paths.values()))
    except RenderRefused as e:
        print(f"render refused: {e}", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the fp console script."""
    ap = argparse.ArgumentParser(prog="fp", description="Floor-plan drafting checker and renderer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="verify a plan; exit 2 on FATAL")
    c.add_argument("plan")
    c.add_argument("--json", action="store_true")
    c.add_argument("-v", "--verbose", action="store_true", help="also print INFO lines")
    c.set_defaults(fn=_cmd_check)
    q = sub.add_parser("questions", help="list open questions with the findings citing them")
    q.add_argument("plan")
    q.add_argument("--out")
    q.set_defaults(fn=_cmd_questions)
    r = sub.add_parser("render", help="render sheets to svg, pdf, png, dxf")
    r.add_argument("plan")
    r.add_argument("--out", default="out")
    r.add_argument("--level", choices=["sketch", "permit", "builder", "all"], default="permit")
    r.add_argument("--lang", choices=["fr", "en", "bi", "all"], default="fr")
    r.add_argument("--formats", default="svg,pdf,png,dxf")
    r.add_argument("--levels", nargs="+", default=None, help="plan level ids to render (default all)")
    r.set_defaults(fn=_cmd_render)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
