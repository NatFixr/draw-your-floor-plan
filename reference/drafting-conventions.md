# Residential floor plan drafting conventions (AutoCAD)

Fetched 2026-09-28. Numbers marked UNVERIFIED are common practice I could not confirm in a fetched primary source. "Sec." = secondary source.

## Line weights (mm)
- NCS/UDS scale of widths: fine 0.18, thin 0.25, medium 0.35, wide 0.50, extra wide 0.70 (also 1.00, 1.40, 2.00). Source: CSI UDS module 1 slides, https://web.itu.edu.tr/yamanhak/ders/uyg/s-ncs.pdf (2026-09-28).
- NCS existing/new/demo/hidden rule: "existing, thin line, .25mm; new, medium, .35mm, demo, medium dashed; hidden, thin dashed" and "minimum text size ... 3/32-in or 2.4mm". Source (Sec., a course author's summary of NCS): https://pdhonline.com/courses/g210/g210content.pdf, p.10 (2026-09-28). Note this NCS rule is about work status, not cut vs beyond.
- ISO 128 series 0.13, 0.18, 0.25, 0.35, 0.50, 0.70, 1.0 (each step about sqrt2). Source (Sec.): https://www.coohom.com/article/architectural-floor-plan-line-weights via search summary; page not fetched. UNVERIFIED against ISO text.
- Per element (Sec.): cut walls 0.50 to 0.70; openings/secondary 0.35; fixtures 0.25; annotations, dimensions, hatches, leaders 0.13 to 0.25 (0.18 hatch); hidden dashed 0.18 to 0.35; centreline 0.13 to 0.18. Sources: https://www.firstinarchitecture.co.uk/architectural-line-weights-and-line-types/ (fetched, cut 0.35 to 0.50, outline 0.50+, dimension/leader/hatch about 0.13) and the coohom search summary (cut 0.50 to 0.70). The two disagree at the margin; pick one set and keep it. Suggested house set at 1:50 (my synthesis): cut walls 0.50, doors/windows/stairs 0.25, beyond and fixtures 0.18, dimensions/hatch/leaders 0.13.

## Wall poché and status
- Poche = two solid lines with the gap filled by solid or hatch (Sec.: https://www.archisoup.com/architecture-line-types-and-weights).
- NCS status suffix on layers: E existing to remain, D existing to demolish, N new work, F future, M to be moved, T temporary, A abandoned, X not in contract. Source: https://www.nationalcadstandard.org/ncs6/pdfs/ncs6_clg_lnf.pdf (fetched, extracted text).
- Convention (NCS via Sec. summary above): existing walls thinner or grey-filled, new walls heavier with solid black or diagonal hatch, demolition medium dashed with no fill. Exact fills (ANSI31 vs SOLID) UNVERIFIED as standard; it is office practice.
- NRC/PSPC Canadian CADD standard uses the same idea: layer extensions "-N New Work", "-X Demolition" (https://canadabuys.canada.ca/sites/default/files/webform/tender_notice/67286/25-58051_eng-and-const-cadd-standards-v5r2.pdf, section 3.2, fetched).

## Door and window symbols in plan
- Door: straight line for the leaf plus a curved line showing the swing (Sec.: https://architecturecourses.org/design/architectural-drawing-symbols via search summary). Arc typically 90 degrees at door width; leaf drawn open at 90 degrees; arc thin (0.18 to 0.25). Cased opening: no leaf, jambs only. UNVERIFIED: exact arc lineweights.
- Window: "The outer two lines represent the window frame; the middle line represents the glass" (three lines across the wall thickness; search summary of https://blueprintprimer.com/posts/architectural-symbols-and-what-they-mean). Sill line sometimes fourth line.

## Dimensioning
- Dimension line continuous, figure above the line, never below; first line at least 1/2 in from object, further lines at least 3/8 in apart; arrowhead length equals lettering height, 3:1 length to width; slash/tick, open, closed, solid or dot allowed but do not mix. Text 3/32 in for notes and dimensions. Source: https://www.sfponline.org/uploads/14/architecturalsymbolsandconventions.pdf (fetched, extracted).
- Strings (Sec.): first (inner) string to openings and partitions, second to wall faces or partitions, outermost overall building dimension. Source: sfponline.org search snippet, same PDF family; treat as UNVERIFIED for wording.
- Dimensions to: exterior stud face for wood frame, centreline for openings; rough opening for windows/doors in Quebec permit drawings (Quebec municipal models write "OUV. BRUTE").
- NCS: round dimensions uniformly (example 1-7/8 in = 48 mm), "for partial plans provide match-lines and key plans", scale bar required with every plan (PDHonline link above).
- AutoCAD settings (my practice, UNVERIFIED as standard): DIMSCALE 1 with annotative style, DIMTXT 2.5 mm paper, DIMEXO 1.5 mm, DIMEXE 1.5 mm, DIMDLI 7 mm (baseline spacing), DIMBLK architectural tick with DIMTSZ set, DIMTAD 1 (text above), DIMTIH/DIMTOH 0 (aligned).

## Scales and sheets
- 1:50 is what several Quebec municipal model drawings use. NCS course note: standard floor plans at 1/8 in = 1 ft; 1/4 in = 1 ft for denser rooms (PDHonline). 1/4 in = 1 ft is 1:48, so 1:50 and 1/4 in are near-equivalent on paper. 1:100 is about 1/8 in = 1 ft (1:96).
- Sheet sizes (Wikipedia Paper size, https://en.wikipedia.org/wiki/Paper_size, fetched): ISO A4 210x297, A3 297x420, A2 420x594, A1 594x841, A0 841x1189 mm; Letter 8.5x11, Tabloid/ANSI B 11x17, ANSI C 17x22, ANSI D 22x34, ANSI E 34x44; Arch C 18x24, Arch D 24x36, Arch E 36x48 in.
- Border: sfponline says a 1/2 in border line.

## Text heights on paper
- NCS minimum 2.4 mm (3/32 in), no exceptions (PDHonline). Suggested 2.5 (notes, dimensions), 3.5 (room names, tags), 5 (titles): ISO 3098 style series; UNVERIFIED against ISO text. Set text height = paper height x scale factor unless annotative.

## Title block, north arrow, tags, schedules (all UNVERIFIED conventions unless noted)
- Title block: project name and address, drawing title and number, scale, date, drawn by, revision table, sheet n of N, north arrow. NCS defines a title block area and a north-arrow convention: "Circle Line" plan north pointing up, scale bar required (PDHonline p.10; UDS "orientation and north arrow" slide). Municipal by-laws typically ask for date, title, "nord astronomique", scale, author on site plans.
- Room tag: name (by use, as fiche 12 requires), area in m2, ceiling height; sometimes finish. NCS layer for tags: A-AREA-IDEN or A-ANNO-IDEN style (Identification tags, verified as a minor group "IDEN", https://facilities.duke.edu/sites/default/files/AIA%20CAD%20Layer%20Guidelines.pdf).
- Door schedule columns: mark, location/room, width x height (rough opening), type, swing, material, hardware, fire rating, remarks. Window schedule: mark, width x height rough opening, type (casement, slider), glazing, egress Y/N, remarks. NCS rule: two columns is a list, three or more a schedule (PDHonline).

## Layers (DXF export)
- NCS format: discipline-major-minor1-minor2-status, separated by dashes; discipline and major mandatory. Examples verified in the AIA CLG list (Duke copy, fetched): A-WALL, A-WALL-FULL, A-WALL-CNTR, A-WALL-HEAD, A-WALL-JAMB, A-WALL-PATT, A-DOOR, A-DOOR-FULL, A-GLAZ, A-GLAZ-SILL, A-FLOR-STRS, A-FLOR-FIXT, A-FURN, A-AREA, A-CLNG. Annotation minors apply to any major: -DIMS, -IDEN, -NOTE, -TEXT, -SYMB, -TTLB, -NPLT, -SCHD, -TITL, -LEGN, -MATC. So A-ANNO-DIMS, A-ANNO-TEXT, A-ANNO-TTLB are valid. Sources: https://www.nationalcadstandard.org/ncs6/pdfs/ncs6_clg_lnf.pdf and the Duke PDF.
- Status examples: A-WALL-E existing, A-WALL-D demolish, A-WALL-N new.
- Canadian federal alternative (NRC/PSPC v5r2): A-DR-INT interior doors, A-DR-EXT, A-GL-DIM, A-DT-DIM, A-EM-WAL-OLN, with -N/-X extensions. Use NCS for cross-tool DXF portability unless a Canadian client mandates PSPC.

## Canadian wall thicknesses
- Interior 2x4 partition: 3-1/2 in stud plus 1/2 in gypsum both sides = 4-1/2 in. Source (Sec., search snippets only, pages not fetched): https://hingemodern.com/interior-wall-thickness/ and homeinspectioninsider.com/interior-wall-thickness/ (2026-09-28).
- Exterior 2x6 frame: 5-1/2 in stud plus 1/2 in gypsum inside plus sheathing and cladding; 6.5 to 8 in overall is my range, UNVERIFIED by a fetched source. Older Quebec houses vary; measure on site.
- Poured concrete foundation: NBC Table 9.15.4.2.-A minimum 150 mm (5 7/8 in) for low backfill, 200 mm (7 7/8 in) most common at 1.0 to 1.5 m backfill with lateral support, 250 or 300 mm for taller. The page claims Quebec 2020 code is identical. Source (Sec.): https://www.codeswise.com/q/what-is-the-minimum-thickness-of-a-poured-concrete-basement-wall-in-residential-construction. So 8 in (200 mm) is the code minimum in the common case, 10 in usual for higher backfill. Measure the real wall.
- CSA B78.x: CAN3-B78.1 general technical drawings excludes building drawings; CAN3-B78.3-M77 "building drawings" exists (NRC archive, https://nrc-publications.canada.ca/eng/view/object/?id=29ae44e1-b45f-4417-9bdb-498befdbca91); CSA B78.5 CAD (buildings). Contents not fetched, UNVERIFIED; treat NCS and ISO as the working references.
