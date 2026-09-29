"""Vocabulary fr/en (bi uses fr) and room-name abbreviations."""
from __future__ import annotations

VOCAB: dict[str, dict[str, str]] = {
    "to_confirm": {"fr": "à confirmer", "en": "to confirm"},
    "unmeasured": {"fr": "non mesurée", "en": "not measured"},
    "open_value": {"fr": "valeur à confirmer", "en": "open value"},
    "untracked_open": {"fr": "élément ouvert sans question", "en": "untracked open item"},
    "closes": {"fr": "ferme", "en": "closes"},
    "area": {"fr": "Aire", "en": "Area"},
    "ceiling": {"fr": "HSP", "en": "Ceiling"},
}


_V = {
    "legend": ("LÉGENDE", "LEGEND"),
    "notes": ("NOTES", "NOTES"),
    "notes_cont": ("NOTES (SUITE)", "NOTES (CONT.)"),
    "wall_existing": ("Mur existant", "Existing wall"),
    "wall_new": ("Mur neuf", "New wall"),
    "wall_demolish": ("Mur à démolir", "Wall to demolish"),
    "window": ("Fenêtre", "Window"),
    "door": ("Porte", "Door"),
    "opening": ("Ouverture sans porte", "Opening, no door"),
    "unmeasured_zone": ("Zone non mesurée", "Unmeasured zone"),
    "legend_confirm": ("* À confirmer sur place", "* To confirm on site"),
    "legend_dashed": ("Pointillé : position approximative", "Dashed: approximate position"),
    "drawing_title": ("TITRE DU DESSIN", "DRAWING TITLE"),
    "scale": ("ÉCHELLE", "SCALE"),
    "date": ("DATE", "DATE"),
    "drawn_by": ("DESSINÉ PAR", "DRAWN BY"),
    "sheet": ("FEUILLE", "SHEET"),
    "sheet_of": ("{n} de {m}", "{n} of {m}"),
    "rev": ("RÉV.", "REV."),
    "rev_desc": ("DESCRIPTION", "DESCRIPTION"),
    "issued_permit": ("Émis pour demande de permis", "Issued for permit application"),
    "issued_builder": ("Émis pour construction", "Issued for construction"),
    "prelim_builder": ("Préliminaire, non émis pour construction", "Preliminary, not for construction"),
    "total_area": ("Superficie globale (intérieure)", "Total floor area (interior)"),
    "view_plan": ("VUE EN PLAN", "PLAN VIEW"),
    "hsp": ("HSP", "CLG"),
    "ft2": ("pi²", "ft²"),
    "win_abbr": ("FEN.", "WIN."),
    "door_abbr": ("P.", "D."),
    "stair_up": ("MONTE", "UP"),
    "stair_down": ("DESC.", "DN"),
    "width_abbr": ("l.", "w."),
    "north": ("N", "N"),
    "faces_note": ("Cotes aux faces intérieures (gypse).", "Dimensions to interior faces (drywall)."),
    "wall_types": ("TYPES DE MURS", "WALL TYPES"),
    "wt_ext": ("Mur extérieur", "Exterior wall"),
    "wt_fdn": ("Mur de fondation", "Foundation wall"),
    "wt_part": ("Cloison", "Partition"),
    "assumed_paren": ("(présumée)", "(assumed)"),
    "door_sched": ("TABLEAU DES PORTES", "DOOR SCHEDULE"),
    "win_sched": ("TABLEAU DES FENÊTRES", "WINDOW SCHEDULE"),
    "col_mark": ("REPÈRE", "MARK"),
    "col_room": ("PIÈCE", "ROOM"),
    "col_size": ("LARG. x HAUT.", "W x H"),
    "col_type": ("TYPE", "TYPE"),
    "col_swing": ("SENS", "SWING"),
    "col_state": ("ÉTAT", "STATUS"),
    "col_pos": ("POSITION", "POSITION"),
    "col_sill": ("ALLÈGE", "SILL"),
    "sill_none": ("non mesurée", "not measured"),
    "t_door": ("Porte", "Door"),
    "t_opening": ("Ouverture sans porte", "Opening, no door"),
    "swing_in": ("Int.", "In"),
    "swing_out": ("Ext.", "Out"),
    "hinge_left": ("charn. g.", "hinge L"),
    "hinge_right": ("charn. d.", "hinge R"),
    "st_existing": ("Existant", "Existing"),
    "st_new": ("Neuf", "New"),
    "st_demolish": ("À démolir", "Demolish"),
    "pos_measured": ("mesurée", "measured"),
    "pos_assumed": ("approximative", "approximate"),
    "sched_hand": ("Sens : Int. = ouvre vers la pièce indiquée ; charn. g./d. vue depuis cette pièce.", "Swing: In = opens into the listed room; hinge L/R seen from that room."),
    "fixtures_note": ("Appareils : positions relevées.", "Fixtures: measured positions."),
    "unmeasured_label": ("non mesuré", "not measured"),
    "sketch_of": ("Croquis", "Sketch"),
    "fn_confirm": ("* à confirmer", "* to confirm"),
    "fn_dashed": ("pointillé : position approximative", "dashed: approximate position"),
    "fn_hatch": ("hachures : non mesuré", "hatch: not measured"),
}
for _k, (_fr, _en) in _V.items():
    VOCAB[_k] = {"fr": _fr, "en": _en}

ABBR = {
    "fr": {"Salle de bain": "S.D.B.", "Garde-robe": "G.-R.", "Chambre": "Ch.", "Escalier": "Esc.", "Corridor": "Corr.",
           "Cuisine": "Cuis.", "Salon": "Sal.", "Walk-in": "W.-I.", "Salle de jeux": "S. jeux"},
    "en": {"Bathroom": "Bath", "Closet": "Clo.", "Bedroom": "Bdrm", "Stair": "Stair", "Hall": "Hall",
           "Kitchen": "Kit.", "Living room": "Liv.", "Play area": "Play"},
}


def colon(lang: str = "en") -> str:
    """Colon with the French space before it (fr and bi only)."""
    return " :" if lang in ("fr", "bi") else ":"


def abbreviate(name: str, lang: str = "en") -> str:
    """Shorten a room name with the ABBR table (longest key first); unchanged when nothing matches."""
    table = ABBR["fr" if lang == "bi" else lang]
    for key in sorted(table, key=len, reverse=True):
        if name.lower().startswith(key.lower()):
            return table[key] + name[len(key):]
    return name


def t(key: str, lang: str = "en") -> str:
    """Translate key; bi uses fr; falls back to en, then the key."""
    entry = VOCAB.get(key)
    if entry is None:
        return key
    lang = "fr" if lang == "bi" else lang
    return entry.get(lang) or entry.get("en") or key
