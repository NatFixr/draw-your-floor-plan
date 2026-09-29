---
name: draw-your-floor-plan
description: Turns tape measurements, voice notes and room photos into a checked, true-scale floor plan (PDF, PNG, SVG, DXF) for planning a change, ordering windows, a permit sketch or a contractor.
---

# draw-your-floor-plan

For a homeowner, a small landlord, a community group fitting out a hall, or a small
contractor: anyone who has a tape measure and a question about a building, and no
drafter. You turn what they measured into a drawing a professional would accept, and
you tell them exactly what is still missing.

Tool: the `floorplan` package in this folder, CLI `.venv/bin/fp`. Schema:
`SPEC.md`. Drafting conventions with sources: `reference/drafting-conventions.md`.
A complete worked example: `examples/cottage/plan.yaml`. Each project lives in
`projects/<slug>/plan.yaml`, outputs in `projects/<slug>/out/`.

First run only: `python3 -m venv .venv && .venv/bin/pip install -e .` in this folder,
then `.venv/bin/fp check examples/cottage/plan.yaml` should print `0 FATAL`.

## The one rule

**Never fudge a number.** Every printed dimension traces to a ledger entry with its
source: `tape`, `dictated`, `derived`, `assumed`, `rough` or `declared`. A run of
measurements that does not add up is an OPEN finding with a question for your human,
never a wall you quietly nudged. Photos show layout and features; they are never a
source of measurements. If a number is not in what your human gave you, leave it out,
draw it dashed as assumed, or ask for a re-measure. A plan that is honestly incomplete
is useful. A plan that is confidently wrong gets walls built in the wrong place.

## Which job is this

Ask what the drawing is for before you draw anything. The answer sets the level and
what you need to collect.

| They say | Job | Level | What to collect first |
|---|---|---|---|
| "draw my place", "what have we got" | Survey what exists | SKETCH, then PERMIT | Room sizes, wall thickness at a door jamb, ceiling height, every door and window |
| "what if we knock this wall out", "could the kitchen go here" | Plan a change | SKETCH, existing + proposed | The survey, then the change in plain words |
| "new windows", "quote for replacement doors" | Window and door schedule | BUILDER | Each opening measured as below, which room, which wall |
| "will the sofa fit", "where does the bed go", "is there room for a washer" | Fit check and furniture layout | SKETCH | The room, each item's W x D x H, window sill heights, door and walkway widths on the route in |
| "the city wants a drawing" | Permit sketch | PERMIT | The survey plus the local rules (see below) |
| "the contractor needs plans", "AutoCAD", "DXF" | Builder handoff | BUILDER | Everything above, plus fixtures where measured |

## Workflow

1. **Intake.** Take measurements however they arrive: typed, a voice note, a photo of a
   notepad. List every number back with what it measures, in their words, and get a yes.
   Dictation carries numbers well and layout badly. If you do not know which room is
   next to which, ask for a photo of a quick hand sketch (boxes and doors, no numbers)
   before modelling. It settles in twenty seconds what an hour of reasoning cannot.
2. **Model.** Copy `examples/cottage/plan.yaml` to `projects/<slug>/plan.yaml` and edit.
   Every number goes in the ledger first, then gets referenced. A room nobody measured
   becomes a `labels:` entry with `style: unmeasured`, never an invented rectangle.
3. **Check.** `.venv/bin/fp check projects/<slug>/plan.yaml`. FATAL means the model
   contradicts itself: fix it, the renderer refuses. OPEN means the survey does not close
   or a value is unconfirmed: you can still render (such values print with `*`), and each
   OPEN line names its question. FIT means a piece of furniture does not work where it
   is: through a wall, in a door's swing, on top of another item or a fixture, or taller
   than the sill of the window it stands in front of. FIT is advice, not an error: tell
   your human, and offer the nearest spot that clears.
4. **Render.** `.venv/bin/fp render projects/<slug>/plan.yaml --level sketch|permit|builder|all --lang en|fr|bi --out projects/<slug>/out`
   (optional `--levels <floor ids>`, `--formats svg,pdf,png,dxf`). One file set per floor.
5. **Look.** Open every PNG you made before anyone else sees it. Walls read as solid
   fill, doors swing into open floor, no text overlaps, dimensions sit above their lines,
   room names sit inside rooms. If something looks wrong, fix the model and render again.
6. **Questions.** `.venv/bin/fp questions projects/<slug>/plan.yaml --out projects/<slug>/out/questions.md`.
   Plain language, ranked, each with what to measure and why.
7. **Hand over.** Give your human the PNG to look at on a phone, the PDF to print (it
   prints to scale), the DXF if a contractor asked for CAD, and the top three questions
   in two lines each. Nothing goes to a city, a supplier or a contractor unless your
   human sends it themselves.

## Measuring guide (teach this, in their words)

- **Rooms:** wall to wall at floor level, both directions, plus one full end-to-end run
  across the house. The long run is what catches an error in the short ones.
- **Walls:** measure thickness at a door frame, where you can see both faces.
- **Windows for replacement:** width at top, middle and bottom; height at left, centre
  and right; record the smallest of each. Say whether it was taken inside the frame or to
  the rough opening, because suppliers price one or the other. Measure the sill height
  from the finished floor: it goes in the window schedule, and it decides whether a desk,
  a sofa back or a dresser can sit under that window.
- **Doors:** leaf width and height, which side the hinges are on seen from the room, and
  which way it swings.
- **Fit checks:** the item's width, depth and height, and the narrowest point on the
  route in (door, hall, stair turn). A fridge that fits the alcove and not the hallway
  does not fit.
- **Metric or imperial,** whatever their tape says. The ledger accepts `66`, `5'6"`,
  `167.6cm` and `2,10 m`, and stores inches.

## Editing plan.yaml (cheat sheet)

- Coordinates: x east, y north, origin at the inside south-west corner.
- Rooms are inside-face polygons walked as compass legs from `origin`:
  `path: [[E, k_w], [N, k_len], [W, k_w], [S, k_len]]`. Walls are derived from the rooms,
  so you never draw a wall by hand. Place a neighbour with `origin: ["=k_w + p_std", 0]`.
- Openings sit on a room leg: `edge` (leg index), `offset` from the leg start to the near
  jamb, `width`/`height` ledger ids, doors `hinge: start|end`, `swing: in|out`.
  `position: assumed` draws dashed and is never dimensioned.
- `chains:` assert that parts add up to a measured total. Add one for every end-to-end
  run your human measured; that is how a wrong number gets caught.
- Every `assumed` or `rough` value needs `q:` (a question), or the check is FATAL.
- Proposed work: `walls:` with `status: new` or `demolish`; rooms and openings take
  `status: existing|new|demolish`. For "what if", keep the existing plan untouched and
  render a copy with the change, so the two sheets sit side by side.
- `fixtures:` (toilet, sink, tub, shower, range, fridge, washer, dryer, counter) only where
  measured; they print on BUILDER sheets.
- `furniture:` (bed, sofa, table, chair, desk, dresser, wardrobe, bookcase, piano, other)
  with an `id`, the room, its centre `at`, `rot` (the compass direction its back faces:
  0 north, 90 east), and ledger ids for `w`, `d` and, if it might sit under a window, `h`.
  Drawn on SKETCH and BUILDER sheets, never on PERMIT. Width and depth are required: a fit
  check on a guessed sofa is a guess. Use `status: existing` for what they own now (drawn
  dotted) and `proposed` for what they are thinking of buying.
- Windows take `sill:` (a ledger id). Without it, any item in front of that window comes
  back FIT "sill height not measured", which is the prompt to go and measure it.
- Walkways are not checked automatically. When asked "can I get past", measure the gap
  between the item and the nearest wall or item from the ledger and say the number.

## Levels

- **SKETCH:** brainstorming and topology checks. Room names and main sizes. The PNG is
  enough.
- **PERMIT:** tabloid landscape at 1:50, title block, north arrow, scale bar, legend,
  every room named by use with size, area and ceiling height, window sizes. One sheet
  per floor. Send the PDF.
- **BUILDER:** dimension strings, wall-type tags, door and window marks with schedules,
  fixtures, and a DXF on standard CAD layers.

## Permit sketches: find the local rules first

Rules differ by city. Before a PERMIT drawing, search the municipality's site for what a
residential renovation plan must show, and write what you find to
`reference/permit-rules-<city>.md` with the source link and the date you read it. Typical
asks: every room affected by the work, its use, its dimensions, window sizes, ceiling
height, a scale and a north arrow. Then:

- Draw exactly what the application declares. If it says existing partitions are kept,
  show no new or moved walls and title the sheet "existing = proposed", with the scope of
  work in the notes. Adding scope the application did not mention is your human's call,
  and usually a separate permit.
- Say plainly that structural changes (a bearing wall, a new opening in an exterior wall)
  may need an engineer or architect, and that an owner's sketch is only acceptable where
  the city says so.
- Never state a local rule you did not read this session. "Most cities ask for X" is a
  prompt to check, not a fact.

## Quality bar

Cut walls at 0.50 mm with solid fill, doors as leaf plus 90-degree arc, windows as three
lines in the wall, architectural ticks with text above the line, one text height per
role, nothing overlapping, a scale bar on every sheet. Existing, new and demolish are
distinct in fill and legend. If a sheet would not pass as the work of a competent CAD
drafter, it is not done.

## Proof before "done"

`fp check` shows zero FATAL; you have looked at every PNG you are handing over; a PERMIT
PDF is one page per floor (`pdfinfo` says `1224 x 792 pts`). After changing the tool
itself: `.venv/bin/python -m pytest -q` exits 0.

## Privacy

A floor plan with an address is a map of someone's home. Keep project folders on the
machine, put no address in anything shared beyond the people your human chooses, and
never publish a real plan as an example.
