"""Shared build context: plan, level geometry, sheet, placer, value formatting."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..checker import Report
from ..geometry import LevelGeom
from ..i18n import t
from ..model import Ledger, Level, Plan
from ..units import fmt_ftin, fmt_m
from .layout import Sheet, Text
from .placer import Placer


@dataclass
class Ctx:
    plan: Plan
    rep: Report
    lv: Level
    geom: LevelGeom
    sheet: Sheet
    placer: Placer
    lang: str
    sl: str  # sketch | permit | builder
    led: Ledger = field(init=False)
    mm_in: float = field(init=False)  # model inches per paper mm
    meta_swing: dict = field(default_factory=dict)
    meta_stairs: dict = field(default_factory=dict)
    meta_leaf: dict = field(default_factory=dict)
    zone: tuple = (12.0, 12.0, 420.0, 268.0)  # paper mm rectangle free for outside tags
    ext_dims: list = field(default_factory=list)  # (side, lo, hi) of exterior dimension segments
    stars: bool = True  # legend and footnote list the * convention

    def __post_init__(self) -> None:
        self.led = self.plan.resolver()
        self.mm_in = 1.0 / self.sheet.k

    @property
    def k(self) -> float:
        """Paper mm per model inch."""
        return self.sheet.k

    @property
    def used_ids(self) -> list[str]:
        """Ledger ids the level's geometry rests on (envelope, rooms, openings, walls, wall thicknesses)."""
        lv, led = self.lv, self.led
        vals: list = [lv.exterior_wall, lv.partition, *lv.envelope.origin, *(v for _, v in lv.envelope.path)]
        for r in lv.rooms:
            vals += [*r.origin, *(v for _, v in r.path)]
        for o in lv.openings:
            vals += [o.offset, o.width] + ([o.height] if o.height else [])
        for w in lv.walls:
            vals += [*w.a, *w.b, w.thickness]
        out: list[str] = []
        for v in vals:
            for i in led.ids_in(v):
                if i not in out:
                    out.append(i)
        return out

    @property
    def level_open(self) -> bool:
        """True when the level's geometry rests on at least one OPEN-marked ledger entry."""
        return any(self._open_id(i, ()) for i in self.used_ids)

    def computed_open(self, length_in: float, lid: str | None = None) -> bool:
        """Marker for a printed computed length: its ledger entry's state when it equals one (lid first, then any
        entry the level uses within 0.01 in), else whether the level rests on an OPEN entry."""
        if lid and lid in self.led:
            return self.is_open(lid)
        for i in self.used_ids:
            if abs(self.led.value(i) - length_in) < 0.01:
                return self.is_open(i)
        return self.level_open

    @property
    def has_unmeasured(self) -> bool:
        """True when the level draws an unmeasured hatch zone or carries an unmeasured label."""
        from .drawplan import unmeasured_pieces
        return bool(unmeasured_pieces(self)) or any(l.style == "unmeasured" for l in self.lv.labels)

    def wall_types(self) -> list[tuple[str, str, str]]:
        """(code, name, thickness ledger id): E1 or F1 for the exterior wall, P1 for partitions."""
        lv = self.lv
        e = self.led.entry(lv.exterior_wall)
        hay = f"{lv.exterior_wall} {e.note or ''}".lower()
        fdn = any(k in hay for k in ("fdn", "foundation", "fondation"))
        out = [("F1" if fdn else "E1", self.tr("wt_fdn" if fdn else "wt_ext"), lv.exterior_wall)]
        if len(lv.rooms) > 1:
            out.append(("P1", self.tr("wt_part"), lv.partition))
        return out

    def tr(self, key: str) -> str:
        """Translate for the sheet language."""
        return t(key, self.lang)

    def is_open(self, x) -> bool:
        """OPEN-marked ledger id, or a derived id resting on one."""
        if not isinstance(x, str) or self.plan.project.minimal:
            return False
        return any(self._open_id(i, ()) for i in self.led.ids_in(x))

    def assumed_size(self, *ids) -> bool:
        """True on a minimal sheet when any of these ledger ids rests on an assumed entry (its callout is skipped)."""
        if not self.plan.project.minimal:
            return False
        return any(self.led.entry(i).src == "assumed" for x in ids if x for i in self.led.ids_in(x))

    def _open_id(self, lid: str, seen: tuple) -> bool:
        if lid in seen:
            return False
        if self.led.is_open(lid):
            return True
        e = self.led.entry(lid)
        return e.src == "derived" and any(self._open_id(i, (*seen, lid)) for i in self.led.ids_in(e.v))

    @property
    def ftin(self) -> bool:
        """True when lengths print in feet-inches (en, or fr on an imperial project)."""
        return self.lang == "en" or (self.lang == "fr" and self.plan.project.units == "imperial")

    def val(self, inches: float, open_: bool = False) -> str:
        """Dimension value per language and sheet level, with trailing * when open."""
        if self.lang == "fr" and self.ftin:
            s = fmt_ftin(inches)
        elif self.lang == "fr":
            s = fmt_m(inches, "fr")
        elif self.lang == "en":
            s = fmt_ftin(inches)
            if self.sl == "builder":
                s += f" [{fmt_m(inches, 'en')}]"
        else:
            s = f"{fmt_m(inches, 'fr')} [{fmt_ftin(inches)}]"
        return s + ("*" if open_ else "")

    def val_id(self, lid: str) -> str:
        """Value of a ledger id formatted for print."""
        return self.val(self.led.value(lid), self.is_open(lid))

    def m_only(self, inches: float, open_: bool = False) -> str:
        """Metres in the sheet language's decimal style (no unit)."""
        return fmt_m(inches, "fr" if self.lang in ("fr", "bi") else "en") + ("*" if open_ else "")

    def put(self, tx: Text, register: bool = True) -> Text:
        """Register a paper-space text and add it to the sheet (converted to model space when model=True tag)."""
        if register:
            self.placer.add_text(tx)
        self.sheet.add(tx)
        return tx

    def put_model(self, tx: Text) -> Text:
        """Register a paper-mm text, then add a model-space copy (pos in inches) to the sheet."""
        self.placer.add_text(tx)
        m = Text(self.sheet.inv(*tx.pos), tx.s, tx.h_mm, tx.anchor, tx.rot_deg, tx.weight, tx.style, tx.color, tx.halo,
                 layer=tx.layer, space="model", tag=tx.tag)
        self.sheet.add(m)
        return m
