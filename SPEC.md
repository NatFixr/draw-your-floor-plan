# floorplan: implementation spec (binding for builders)

Package `floorplan`, venv `.venv` inside the skill folder, console script `fp = floorplan.cli:main`.
Deps: ezdxf, pyyaml, pydantic>=2, shapely>=2, pillow, pytest. External: google-chrome, pdfinfo, pdftoppm.
Model units: INCHES, x east, y north. Paper units: mm. Code comments sparse, factual, max two lines.

## Modules
```
floorplan/units.py     parse_length, fmt_ftin, fmt_m, fmt_area
floorplan/model.py     pydantic schema + Ledger (expression eval)
floorplan/geometry.py  build_level(plan, level_id) -> LevelGeom
floorplan/checker.py   check(plan) -> Report (findings, areas, manifest)
floorplan/i18n.py      vocabulary fr/en, t(key, lang)
floorplan/render/      layout.py (display list), svg.py, pdf.py (chrome+pdftoppm), dxf.py, sheets.py (sketch/permit/builder), styles.py (ONE table of pens, text heights, fills)
floorplan/cli.py       fp check | fp render | fp questions
tests/                 fixtures/*.yaml + test_*.py
projects/example/plan.yaml
```

## units.py
- `parse_length(v) -> float inches`. Accepts int/float (inches), and strings: `66`, `66.5`, `5'6"`, `5' 6"`, `5'-6 1/2"`, `5'`, `6"`, `66 1/2`, `167.6cm`, `167,6 cm`, `1676mm`, `2.1m`, `2,10 m`. Raise ValueError otherwise.
- `fmt_ftin(inches, prec=0.25) -> "5'-6 1/2\""` (architectural: feet-dash-inches, fraction reduced, `0'-8"` for < 1 ft, `12'-0"`).
- `fmt_m(inches, lang, nd=2) -> "1,68"` for fr, `"1.68"` for en/bi (no unit suffix; callers add " m").
- `fmt_area_m2(sq_in, lang, nd=1)`, `fmt_area_ft2(sq_in)`.

## plan.yaml schema (model.py)
```yaml
project:
  id: example                      # slug, used in output file names
  title: {fr: "...", en: "..."}
  address: "..."
  author: "Your Name"
  date: "2026-09-28"
  sheet_prefix: A                  # sheet numbers A-101, A-102 in level order
  subtitle: {fr: "...", en: "..."} # optional line under the sheet title (e.g. "Existant = proposé")
  notes: {fr: [..], en: [..]}      # general notes printed on PERMIT and BUILDER
ledger:                            # EVERY printed number resolves to an entry here
  k_w:   {v: 100, src: tape, date: "2026-07-19", note: "kitchen width"}
  k_len: {v: 256, src: dictated, q: Q3}
  jog:   {v: "=t1_s - t1_n", src: derived}
  p_std: {v: 4.5, src: assumed, note: "2x4 + gypse 2 faces"}
  hsp_s: {v: "2.10m", src: declared, text: {fr: "2,10 m min. (déclaré)", en: "2.10 m min. (declared)"}}
levels:
  - id: rdc
    name: {fr: "Rez-de-chaussée", en: "Main floor"}
    ceiling: hsp_r                 # ledger id; printed as HSP on every room tag unless room overrides
    exterior_wall: ext_t           # ledger id: exterior wall thickness
    partition: p_std               # ledger id: default partition thickness
    envelope: {origin: [0, 0], path: [[E, env_w], [N, k_len], [W, env_w], [S, k_len]]}
    rooms:
      - id: T5                     # stable code, printed small on tags
        name: {fr: Cuisine, en: Kitchen}
        kind: room                 # room | hall | closet | bath | stair
        status: existing           # existing | new | demolish
        origin: [0, 0]             # each coord: number | ledger id | "=expr"
        path: [[E, k_w], [N, k_len], [W, k_w], [S, k_len]]   # compass legs; value = number | ledger id | "=expr"
        dims: [k_w, k_len]         # 1 or 2 ledger ids printed on the tag as W x D (1 = width only)
        ceiling: null              # optional override ledger id
        tag_at: null               # optional [x, y] model inches to force tag position
        stair: null                # kind stair only: {up: N|S|E|W, go: up|down} travel direction going up; go = which way it leads from THIS level
    walls:                         # optional explicit walls (new/demolish work); centreline a->b, flat caps
      - {id: W1, status: new, a: [x, y], b: [x, y], thickness: p_std}
    openings:
      - id: D1
        type: door                 # door | opening (cased, no leaf) | window
        room: T1                   # host room id
        edge: 0                    # index into host room path legs
        offset: 2                  # from the START of that leg, along travel direction, to the near jamb
        width: d1_w                # ledger id (required)
        height: d1_h               # ledger id (optional; windows print W x H)
        hinge: start               # doors: jamb nearer leg start (start) or end (end)
        swing: in                  # doors: into host room (in) or out of it (out)
        status: existing
        position: measured         # measured | assumed. assumed => drawn, never dimensioned, flagged in legend
    labels:                        # free text for unmeasured zones, notes on plan
      - {at: [x, y], text: {fr: "Buanderie\n(non mesurée)", en: "Laundry\n(not measured)"}, style: unmeasured}   # style: unmeasured | open | note
    fixtures:                      # BUILDER only; only where measured
      - {type: toilet|sink|tub|shower|range|fridge|washer|dryer|counter, room: T6, at: [x, y], rot: 0, w: ledger, d: ledger}
    furniture:                     # SKETCH and BUILDER; w and d required (fit checks need real sizes)
      - {id: F1, type: bed|sofa|table|chair|desk|dresser|wardrobe|bookcase|piano|other, room: R2, at: [x, y], rot: 0, w: ledger, d: ledger, h: ledger?, label: {fr, en}?, status: existing|proposed}
    # windows take `sill: ledger` (finished floor to top of sill); it prints in the BUILDER window schedule.
    # FIT findings (fp check): furniture_through_wall, furniture_blocks_door, furniture_overlap,
    # furniture_on_fixture, furniture_above_sill, furniture_at_window_sill_unknown, furniture_at_window_height_unknown.
    # FIT never blocks rendering and never marks a value à confirmer: it is a layout problem, not a survey problem.
chains:                            # assertions the checker verifies
  - {id: C1, level: rdc, parts: [b2_d, p_std, hall_w, p_std, bath_d], total: k_len, q: Q3, note: "west column"}
questions:
  - {id: Q1, rank: 1, title: "...", measure: "what to measure, where", why: "what it unlocks"}
```
- Ledger `src` in {tape, dictated, derived, assumed, rough, declared}. Tolerance (inches): tape 0.5, dictated 1, derived 4, rough 12, declared 0, assumed = inf (assumed values never cause closure findings, but are always "à confirmer" when printed).
- `v` accepts anything parse_length accepts, or `"=expr"`: + - * / parentheses, numbers, ledger ids. Cycles => FATAL.
- An entry is OPEN-marked ("à confirmer") iff it has `q` or src in {assumed, rough}. Such entries must have `q`; an OPEN-marked printed entry without `q` is FATAL ("untracked open item").
- Room path legs: `[E|W|N|S, value]`. Polygon = cumulative points; closure error = distance(last point, origin). Rendered polygon replaces the last point with origin.

## geometry.py
```python
@dataclass
class OpeningGeom:
    id: str; type: str; status: str; position: str
    a: tuple[float,float]; b: tuple[float,float]   # jamb points on the host room face (a = nearer leg start)
    normal: tuple[float,float]                      # unit vector pointing OUT of the host room
    depth: float                                     # wall thickness cut (inches), >= 1
    width: float; height: float | None
    hinge: str | None; swing: str | None; room: str
@dataclass
class LevelGeom:
    level_id: str
    envelope: Polygon                  # interior face of exterior walls
    rooms: dict[str, Polygon]          # interior faces
    closure: dict[str, float]          # room id -> closure error inches
    walls: dict[str, Polygon | MultiPolygon]   # keys 'existing','new','demolish'; openings already cut
    openings: list[OpeningGeom]
    unassigned: Polygon | MultiPolygon # envelope - rooms - walls (unmeasured zones), for info
```
- Exterior mass = envelope.buffer(ext_t, join_style="mitre") - envelope.
- Partition mass = (unary_union([r.buffer(p, join_style="mitre") for r in rooms]) & envelope) - unary_union(rooms). Rooms that touch (gap 0) get no wall between them: that is an open boundary. Gaps wider than 2p remain white (unassigned).
- Explicit walls: centreline buffered with cap_style="flat"; status new goes to walls['new'], demolish to walls['demolish'], and they are removed from 'existing'.
- Opening cut: rectangle spanning [a,b] from the room face outward along `normal`; depth = length of the first contiguous piece of wall mass crossed by the normal ray from the opening midpoint (probe length ext_t + 2p + 2). Cut the rectangle out of all wall sets.

## checker.py
`check(plan) -> Report` with `findings: list[Finding(level: FATAL|OPEN|INFO, code, msg, q, where)]`, `areas: {level: {room: sq_in}}`, `manifest: list[(level_id, what, ledger_id, value_in, open_marked)]` (every number the renderer will print), `ok` = no FATAL.
FATAL: schema error, unknown ledger id, expression cycle, rooms overlapping (> 1 sq in), room outside envelope (> 1 sq in), opening wider than its leg or off the leg, unknown question id, printed OPEN-marked ledger entry without q, room non-closure beyond tolerance with no q on any leg.
OPEN (each carries q): chain |sum(parts) - total| > sqrt(sum tol^2 of parts and total) (assumed parts contribute 0 tolerance but the chain is still OPEN if any part is assumed? NO: assumed parts do not open a chain by themselves); room closure beyond tolerance (q from the first leg entry that has one); every printed ledger entry that is OPEN-marked (one finding per entry, deduplicated).
INFO: chain/room closes within tolerance (show the residual).
CLI output (plain text): header, then lines `FATAL  <code>  <msg>` / `OPEN  [Q3]  <msg>`, then an areas table (m2 and ft2 per room per level), then manifest count and `N FATAL, M OPEN`. Exit 2 if any FATAL, else 0. `--json` for machine output.
`fp questions plan.yaml [--out questions.md]`: markdown, questions sorted by rank; under each, the OPEN findings that cite it. English only.

## Rendering: sheets and conventions
Display list in paper mm. Items tagged with an NCS layer name. Model -> paper: x_mm = x0 + x_in*25.4/scale, y_mm = y0 - y_in*25.4/scale (paper y grows downward). Default scale 50.
Sheets: one output set per level: `<out>/<project.id>-<level.id>-<sheetlevel>-<lang>.{svg,pdf,png,dxf}`.
- PERMIT and BUILDER: Tabloid landscape 431.8 x 279.4 mm, 1:50, 10 mm border (0.50 pen), title block strip on the right (about 80 mm wide): project title, address, drawing title (level name + subtitle), scale "1:50", date, author ("Dessiné par"), sheet "A-101" and "1 de 2", north arrow, graphic scale bar 0-1-2-3-4-5 m (alternating black/white 1 m segments, 0.5 m subdivisions on the first metre), legend (wall statuses present in the model plus: window, door, "cote à confirmer" marker, unmeasured zone), notes (project notes, numbered). Plan centred in the remaining drawing area. Nothing may overlap anything.
- SKETCH: page size = plan extents + 25 mm margin each side, 1:50, no border/title block/legend; a small title line (project + level), north arrow and scale bar. Room name (4 mm) + W x D in ft-in and m. PNG rendered at 200 dpi.
- Text heights (paper mm): dims 2.5, notes 2.5, room names 3.5 (bold, uppercase in fr permit), tags small text 2.2, sheet titles 5, title block labels 1.8. Font: "Noto Sans" (fallback Liberation Sans, sans-serif); measure text widths with Pillow using the Noto Sans TTF found via fc-match, for collision tests.
- Pens (mm): cut walls outline 0.50; existing wall fill solid dark grey #5a5a5a (tunable in styles.py); new wall fill solid black; demolish = dashed 0.35 outline, no fill; doors/windows 0.25; door swing arc 0.18; fixtures 0.18; dims/leaders/hatch 0.13; border 0.50; open boundary between touching rooms: 0.13 dashed.
- Door: leaf drawn open at 90 deg (rectangle 1.5 in thick x width, 0.25 pen) hinged at the hinge jamb on the swing side, arc (0.18) from the leaf tip to the closed position; `opening` = no leaf, jambs only. Window: in the cut, two frame lines at the two wall faces plus one glass line at mid-depth (0.25), jamb lines closing the ends. Assumed-position openings drawn with the same symbol but 0.25 dashed.
- Dimensions: architectural ticks (45 deg slash, 2 mm long, 0.35 pen), extension lines with 1.5 mm gap from object and 1.5 mm overshoot, text 2.5 mm centred ABOVE the dim line and aligned with it (vertical dims read from the right side), dim line continuous. If text does not fit between extension lines, place it outside next to the tick. OPEN-marked values get a trailing marker `*` and the legend explains `* à confirmer` / `* to confirm`.
- Value format per lang: fr = metres with decimal comma ("3,20"); en = ft-in primary with metres in brackets on BUILDER ("10'-6\" [3.20]"), ft-in only on SKETCH; bi = fr metres + ft-in in brackets.
- Room tag (PERMIT): NAME (usage) / "3,20 x 2,87 m" from `dims` / "Aire 9,2 m²" / "HSP 2,41 m" (ceiling ledger text if the entry has `text`). Placed at shapely polylabel, must fit inside the room minus 2 mm; else try a grid of positions inside; else outside with a leader.
- PERMIT content: walls, openings, room tags, one interior dimension per room axis for rooms that have `dims` (horizontal and vertical, inside the room, not colliding with the tag), window callout "FEN. 0,86 x 1,17 H" beside each window (outside the building where possible), door width callout for doors ("P. 0,86"), labels, open-boundary dashed lines. No fixtures.
- BUILDER content: PERMIT content plus: dimension strings on each side of the envelope (tier 1: opening jambs + partitions, tier 2: interior faces overall), wall type tags (existing exterior "E1", partition "P1") with a wall-type legend, door marks (circle, D1..) and window marks (hexagon, W1..), door schedule and window schedule tables (mark, room, W x H, type, swing/hand, status, position measured/assumed), fixtures drawn where present, general notes. Schedules may sit in the drawing area if the plan leaves room; nothing may overlap.
- Legend and notes content comes from i18n + project notes. French strings use proper accents.

## PDF / PNG
SVG root: `width="431.8mm" height="279.4mm" viewBox="0 0 431.8 279.4"`. PDF via headless Chrome: HTML wrapper `<style>@page{size:17in 11in;margin:0} html,body{margin:0;overflow:hidden}</style>` + inline SVG; `google-chrome --headless=new --disable-gpu --no-pdf-header-footer --print-to-pdf=<pdf> file://<html>`; for SKETCH the @page size equals the SVG size in mm. Assert `pdfinfo` Pages: 1 after writing. PNG = `pdftoppm -png -r 150 -singlefile` of the PDF (SKETCH: -r 200). The scale bar's paper geometry (x0_mm, x1_mm for the 0..1 m segment, y_mm) is returned by the renderer so tests can measure it.

## DXF (ezdxf, R2018)
Model space in INCHES, coordinates identical to the model ($INSUNITS=1). Layers with lineweights: A-WALL-E (existing poché: HATCH SOLID + LWPOLYLINE boundaries), A-WALL-N, A-WALL-D (dashed), A-DOOR, A-GLAZ, A-FLOR-STRS, A-FLOR-FIXT, A-AREA (room boundary closed LWPOLYLINEs with XDATA or the room id in a MTEXT), A-AREA-IDEN (room tags MTEXT), A-ANNO-DIMS (real DIMENSION entities, dimstyle "FP-ARCH": DIMBLK ARCHTICK, DIMTAD 1, text height scaled to paper 2.5 mm at 1:50, text override for OPEN marker; fr uses DIMLFAC 0.0254 with 2 decimals and comma DIMDSEP), A-ANNO-TEXT, A-ANNO-SYMB. Title block and border: a paperspace layout named after the sheet with a viewport at 1:50 is desirable; if skipped, say so in the report. `doc.audit()` must report no errors.

## Tests (proof: `.venv/bin/python -m pytest -q` exits 0)
units parsing/formatting; checker on fixtures (pass, fatal overlap, fatal unknown ref, open chain with q, fatal non-closing room without q); example plan: 0 FATAL 0 OPEN; render example PERMIT fr: pdfinfo page size 1224 x 792 pts and Pages 1, PNG rasterized at 300 dpi -> measured 1 m scale bar segment = 20 mm on paper = 236.2 px within 1%; DXF audit clean and A-AREA polylines equal model room polygons within 1e-6; SVG structural (root size, one door-arc per door, room names present, no two text bboxes overlapping per the layout's own bbox registry).

## Submission mode 2026-09-29
- Project `units: metric|imperial` (imperial: fr sheets print ft-in, `pi²`, feet scale bar). Ledger `text_imp` replaces `text` on imperial sheets.
- Project `minimal: true`: no `*` marks anywhere, PERMIT prints only the project notes (no generated provenance/unlocated notes), and an opening whose size rests on an `assumed` entry gets no callout. The model, `fp check` and `fp questions` are unchanged.

## Fix round 2026-09-28 (binding; supersedes anything above that conflicts)

### Model additions (model.py)
- Ledger entry: `prov: {fr, en} | None`, a provenance phrase with optional `{date}` placeholder, e.g. `{fr: "HSP du sous-sol déclarée le {date}", en: "basement ceiling height declared {date}"}`.
- Project: `survey_date: str | None` (default date for entries without `date`), `surveyor: {fr, en}` default `{fr: "le propriétaire", en: "the owner"}`.
- Level: `absorb_max: Value = 3` (inches); `gap_q: str | None` (question for absorbed-wall findings on this level); `gap_q_pairs: dict[str, str] = {}` keyed `"A|B"` (room ids sorted) or `"A|envelope"`, overriding gap_q.
- Level: `unlocated: list[{what: {fr, en}, w: ledger id, h: ledger id | None}]` surveyed items with no known position.
- Label: `q: str | None`; `text` becomes optional (None = no printed text, still marks a zone).
- Room `dims`: 1..n ledger ids. 1 = width only; 2 on a rectangle = "W x D" on the tag; on a NON-rectangular room every id is drawn as a leg dimension and the tag shows no W x D.

### Geometry (geometry.py) — R1 "never invent a wall"
- Partitions = (closing of union(rooms) with radius r = (p + absorb_max)/2 + 0.01, mitre joins) ∩ envelope − rooms. Room-to-envelope fill = (closing of union(rooms ∪ exterior ring) with radius absorb_max/2 + 0.01) ∩ envelope − rooms. Walls = exterior ring ∪ both fills, then explicit walls, then opening cuts. So: room faces ≤ p + absorb_max apart get a wall at their actual gap; a room ≤ absorb_max from the envelope is absorbed into the exterior wall; anything wider stays empty.
- `LevelGeom.zones: list[Polygon]` = pieces of (envelope − rooms − walls) with area ≥ 6 sq in and piece.buffer(-0.25) non-empty. `LevelGeom.zone_edges: list[LineString]` = zone boundaries minus the envelope face (these render as thin dashed lines). Keep `unassigned` for compatibility.
- `LevelGeom.gaps: list[Gap(a, b, d, kind)]`: every facing pair (room-room with projection overlap ≥ 1 in, or room-"envelope") and its min distance d. kind: `open` (d ≤ 0.01), `std` (|d − p| ≤ 0.25, or room-envelope d ≤ 0.25), `absorbed` (p + 0.25 < d ≤ p + absorb_max; room-envelope 0.25 < d ≤ absorb_max), `thin` (0.01 < d < p − 0.25), `zone` (wider).
- Openings on a face with no wall mass: depth = 0.5 in (drawn in the dashed boundary), no error.

### Checker (checker.py)
- R1: each `absorbed` or `thin` gap → OPEN `wall_absorbed` "T3|T4 wall 6.50 in derived vs p_std 4.50 in", q from gap_q_pairs or gap_q; none → FATAL `gap_no_q`. Each zone → OPEN `zone_unmeasured` "unmeasured zone near (x, y), N ft2", q = q of the label(s) whose `at` lies inside the zone (first one); no labelled point with q inside → FATAL `zone_no_q`.
- R2: any room closure error > 0.01 in → OPEN `room_out_of_square` "T2 legs don't close by 0.50 in (out of square)" with q from its legs; none → FATAL (existing code). Tolerance no longer suppresses it.
- R3: every ledger entry with src assumed or rough must have `q`, printed or not → else FATAL `assumed_no_q`.
- Report exposes `open_count` for the renderer.

### Renderer
- R1: zones hatched, bounded by `zone_edges` as 0.18 dashed thin lines, never poché; wall-type tags only on wall pieces whose both long sides touch rooms or the exterior.
- R2: a Dim is emitted only when its ledger value equals the drawn leg length within 0.01 in; otherwise skip it (value stays on the tag). Test invariant: on every sheet, each Dim's text (minus `*`) equals the formatted drawn distance.
- R4: BUILDER revision row text: open_count > 0 → fr "Préliminaire, non émis pour construction", en "Preliminary, not for construction"; else "Émis pour construction" / "Issued for construction".
- R5: PERMIT skips labels with style `open`. Rooms (room, bath, hall): name, W x D (rectangles with 2 dims) or leg dims (non-rectangular), area, HSP. Closets and stairs: name only. BUILDER tags also carry HSP. Each PERMIT sheet prints "Superficie globale (intérieure) : 65,8 m²" (en "Total floor area (interior): ...") = envelope interior area, `*` if the envelope rests on an OPEN entry; wording from fiche 12 p.2 "superficie globale en mètres carrés".
- R6: `opening` (no leaf) symbol = clean gap with solid 0.25 jamb lines across the wall; dashed is reserved for approximate position (then the jamb lines are dashed). Legend: "Ouverture sans porte" swatch distinct from "Pointillé : position approximative".
- R8: level `unlocated` renders as one note: fr "Éléments relevés, position à confirmer : fenêtre dissimulée derrière le gypse (salon) 0,86 x 1,14 ; ...", en "Surveyed, position to confirm: ...", values formatted per lang with `*` rules.
- R9: the provenance note is generated, not authored: fr "Dimensions intérieures relevées par {surveyor} ({dominant date of printed tape/dictated entries}), sauf mention ; " + "; ".join(prov of printed entries that have `prov`, {date} filled from the entry's date or survey_date) + "."; en analog. Printed entries with src declared, or src derived with q, must have `prov` → else FATAL `prov_missing` (checker).
