"""The one table of pens, fills, text heights, colours, layers and dash patterns."""
from __future__ import annotations

FONT_FAMILY = "Noto Sans, Liberation Sans, sans-serif"
FONT_DIR = "/usr/share/fonts/google-noto"
FONT_FILES = {
    ("regular", "normal"): f"{FONT_DIR}/NotoSans-Regular.ttf",
    ("bold", "normal"): f"{FONT_DIR}/NotoSans-Bold.ttf",
    ("regular", "italic"): f"{FONT_DIR}/NotoSans-Italic.ttf",
    ("bold", "italic"): f"{FONT_DIR}/NotoSans-BoldItalic.ttf",
}
CAP = 0.714  # Noto Sans cap height / em: text "height" is cap height, as in CAD

INK = "#000000"
GREY = "#6e6e6e"
HATCH_COLOR = "#b0b0b0"
PAPER = "#ffffff"
FILL = {"existing": "#5a5a5a", "new": "#000000", "demolish": None}
LAYER_OF_WALL = {"existing": "A-WALL-E", "new": "A-WALL-N", "demolish": "A-WALL-D"}

# paint order, first drawn first
LAYERS = [
    "A-AREA", "A-AREA-IDEN", "A-WALL-E", "A-WALL-N", "A-WALL-D", "A-FLOR-STRS", "A-FLOR-FIXT", "A-FURN",
    "A-DOOR", "A-GLAZ", "A-ANNO-SYMB", "A-ANNO-DIMS", "A-ANNO-TEXT", "A-ANNO-SCHD", "A-ANNO-LEGN", "A-ANNO-TTLB",
]

PEN = {
    "cut": 0.50, "border": 0.50, "opening": 0.25, "swing": 0.18, "fixture": 0.18, "furniture": 0.13, "fine": 0.13,
    "tick": 0.35, "demo": 0.35, "stair": 0.13, "table": 0.25, "leader": 0.13,
}
DASH = {"dashed": (2.4, 1.2), "fine": (1.2, 0.8)}

H = {"dim": 2.5, "note": 2.5, "room": 3.5, "tag": 2.2, "title": 5.0, "label": 1.8, "sketch_name": 4.0,
     "sketch_code": 2.0, "sketch_dim": 2.5, "sched": 2.2, "mark": 2.2}

DIM = {"gap": 1.5, "over": 1.5, "tick": 2.0, "text_gap": 0.8, "raise": 2.4, "room_in": 5.0, "permit_out": 12.0, "tier1": 8.5, "tier2": 15.5}

SHEET_MM = (431.8, 279.4)
BORDER_MM = 10.0
STRIP_MM = 85.0
SCALES = (50, 75, 100)
SKETCH_MARGIN_MM = 25.0
PITCH = 1.5  # baseline pitch of wrapped lines, times text height
NOTE_GAP_MM = 1.6
HATCH_SPACING_MM = 2.5
DOOR_LEAF_IN = 1.5
MIN_UNMEASURED_IN = 6.0
