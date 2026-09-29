# draw-your-floor-plan

An agent skill and a small Python drawing tool that turn tape measurements, voice notes
and room photos into a checked, true-scale floor plan: PDF that prints to scale, PNG for a
phone, SVG, and a DXF that opens in AutoCAD.

It is built for people with a tape measure and no drafter: planning a renovation, getting
window quotes, checking whether furniture fits, sketching for a permit, or handing a
contractor dimensioned plans with door and window schedules.

Every printed number traces to where it came from. Measurements that do not add up are
flagged with a question, never silently adjusted, and furniture that hits a wall, blocks a
door or sits above a window sill is flagged before anyone carries it up the stairs.

## Install

Put this folder in your agent's skills directory (for Claude Code,
`~/.claude/skills/draw-your-floor-plan/`; for Codex, `~/.agents/skills/draw-your-floor-plan/`), then:

    python3 -m venv .venv && .venv/bin/pip install -e .
    .venv/bin/fp check examples/cottage/plan.yaml     # expect: 0 FATAL, 0 OPEN, 0 FIT

Python 3.11 or later. `SKILL.md` is what the agent reads; `SPEC.md` is the plan file schema.

## Use by hand

    .venv/bin/fp check plan.yaml
    .venv/bin/fp render plan.yaml --level sketch|permit|builder|all --lang en|fr|bi --out out
    .venv/bin/fp questions plan.yaml

Tests: `.venv/bin/pip install -e '.[dev]' && .venv/bin/python -m pytest -q`.

MIT licensed.
