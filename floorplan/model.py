"""Pydantic plan schema and the Ledger that resolves every printed number."""
from __future__ import annotations

import ast
import math
import re
from pathlib import Path
from typing import Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .units import parse_length

Value = Union[int, float, str]
Coord = tuple[Value, Value]
Text = dict[str, str]
Dir = Literal["E", "W", "N", "S"]
Src = Literal["tape", "dictated", "derived", "assumed", "rough", "declared"]

TOL: dict[str, float] = {
    "tape": 0.5, "dictated": 1.0, "derived": 4.0,
    "rough": 12.0, "declared": 0.0, "assumed": math.inf,
}
_IDENT = re.compile(r"^[A-Za-z_]\w*$")


class PlanError(ValueError):
    """Raised by load_plan for unreadable or schema-invalid plan files."""


class LedgerError(ValueError):
    """Ledger resolution failure; code is unknown_ref, cycle or bad_value."""

    def __init__(self, code: str, msg: str):
        super().__init__(msg)
        self.code = code


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _dstr(v):
    return None if v is None else str(v)


class LedgerEntry(_M):
    v: Value
    src: Src
    date: Optional[str] = None
    note: Optional[str] = None
    q: Optional[str] = None
    text: Optional[Text] = None
    text_imp: Optional[Text] = None  # printed instead of text on imperial sheets
    prov: Optional[Text] = None
    date_str = field_validator("date", mode="before")(_dstr)


class Project(_M):
    id: str
    title: Text
    address: str = ""
    author: str = ""
    date: str = ""
    sheet_prefix: str = "A"
    reference: Optional[str] = None
    survey_date: Optional[str] = None
    surveyor: Text = Field(default_factory=lambda: {"fr": "le propriétaire", "en": "the owner"})
    subtitle: Optional[Text] = None
    units: Literal["metric", "imperial"] = "metric"  # imperial: fr sheets print ft-in and pi²
    minimal: bool = False  # submission sheet: no * marks, no generated notes, no callout on an assumed size
    notes: dict[str, list[str]] = Field(default_factory=dict)
    date_str = field_validator("date", "survey_date", mode="before")(_dstr)


class Stair(_M):
    up: Dir
    go: Literal["up", "down"] = "down"


class Room(_M):
    id: str
    name: Text
    kind: Literal["room", "hall", "closet", "bath", "stair"] = "room"
    status: Literal["existing", "new", "demolish"] = "existing"
    origin: Coord
    path: list[tuple[Dir, Value]]
    dims: Optional[list[str]] = Field(default=None, min_length=1)
    ceiling: Optional[str] = None
    tag_at: Optional[tuple[float, float]] = None
    stair: Optional[Stair] = None

    @field_validator("path", mode="before")
    @classmethod
    def _upper(cls, p):
        return [[str(d).upper(), v] for d, v in p] if isinstance(p, list) else p


class Envelope(_M):
    origin: Coord
    path: list[tuple[Dir, Value]]


class Wall(_M):
    id: str
    status: Literal["existing", "new", "demolish"] = "new"
    a: Coord
    b: Coord
    thickness: str


class Opening(_M):
    id: str
    type: Literal["door", "opening", "window"]
    room: str
    edge: int
    offset: Value
    width: str
    height: Optional[str] = None
    hinge: Literal["start", "end"] = "start"
    swing: Literal["in", "out"] = "in"
    status: Literal["existing", "new", "demolish"] = "existing"
    position: Literal["measured", "assumed"] = "measured"
    sill: Optional[str] = None  # windows: ledger id, finished floor to top of sill


class Label(_M):
    at: tuple[float, float]
    text: Optional[Text] = None
    style: Literal["unmeasured", "open", "note"] = "note"
    q: Optional[str] = None


class Unlocated(_M):
    what: Text
    w: str
    h: Optional[str] = None


class Fixture(_M):
    type: Literal["toilet", "sink", "tub", "shower", "range", "fridge", "washer", "dryer", "counter"]
    room: str
    at: tuple[float, float]
    rot: float = 0
    w: Optional[str] = None
    d: Optional[str] = None


class Furniture(_M):
    id: str
    type: Literal["bed", "sofa", "table", "chair", "desk", "dresser", "wardrobe", "bookcase", "piano", "other"]
    room: str
    at: tuple[float, float]  # centre, inches, level coordinates
    rot: float = 0  # compass bearing of the item's back, as for fixtures
    w: str  # ledger id, along the back
    d: str  # ledger id, back to front
    h: Optional[str] = None  # ledger id, height (used against window sills)
    label: Optional[Text] = None
    status: Literal["existing", "proposed"] = "proposed"


class Level(_M):
    id: str
    name: Text
    ceiling: Optional[str] = None
    exterior_wall: str
    partition: str
    absorb_max: Value = 3
    gap_q: Optional[str] = None
    gap_q_pairs: dict[str, str] = Field(default_factory=dict)
    unlocated: list[Unlocated] = Field(default_factory=list)
    envelope: Envelope
    rooms: list[Room] = Field(default_factory=list)
    walls: list[Wall] = Field(default_factory=list)
    openings: list[Opening] = Field(default_factory=list)
    labels: list[Label] = Field(default_factory=list)
    fixtures: list[Fixture] = Field(default_factory=list)
    furniture: list[Furniture] = Field(default_factory=list)


class Chain(_M):
    id: str
    level: str
    parts: list[Value]
    total: Value
    q: Optional[str] = None
    note: Optional[str] = None


class Question(_M):
    id: str
    rank: int = 99
    title: str
    measure: str = ""
    why: str = ""


class Plan(_M):
    project: Project
    ledger: dict[str, LedgerEntry] = Field(default_factory=dict)
    levels: list[Level]
    chains: list[Chain] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)

    def level(self, level_id: str) -> Level:
        """Return the level with this id; KeyError if absent."""
        for lv in self.levels:
            if lv.id == level_id:
                return lv
        raise KeyError(level_id)

    def resolver(self) -> "Ledger":
        """Fresh Ledger over this plan's entries."""
        return Ledger(self.ledger)


class Ledger:
    """Resolves numbers, unit strings, ledger ids and "=expr" to inches."""

    def __init__(self, entries: dict[str, LedgerEntry]):
        self.entries = entries
        self._cache: dict[str, float] = {}

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in self.entries

    def entry(self, ledger_id: str) -> LedgerEntry:
        """Entry for an id; LedgerError(unknown_ref) if missing."""
        try:
            return self.entries[ledger_id]
        except KeyError:
            raise LedgerError("unknown_ref", f"unknown ledger id '{ledger_id}'") from None

    def value(self, x: Value) -> float:
        """Resolve x to inches."""
        return self._eval(x, ())

    def point(self, c: Coord) -> tuple[float, float]:
        """Resolve an (x, y) coordinate pair."""
        return (self.value(c[0]), self.value(c[1]))

    def is_open(self, ledger_id: str) -> bool:
        """OPEN-marked: has q or src assumed/rough."""
        e = self.entry(ledger_id)
        return bool(e.q) or e.src in ("assumed", "rough")

    def tol(self, x: Value, assumed: float = math.inf) -> float:
        """Tolerance in inches; `assumed` is what an assumed-src id contributes."""
        if isinstance(x, str):
            if x in self.entries:
                src = self.entries[x].src
                return assumed if src == "assumed" else TOL[src]
            if x.strip().startswith("="):
                ts = [self.tol(n, assumed) for n in self.ids_in(x)]
                return math.inf if math.inf in ts else math.sqrt(sum(t * t for t in ts))
        return 0.0

    def ids_in(self, x: Value) -> list[str]:
        """Ledger ids referenced by x (x itself if an id, names inside an expression)."""
        if isinstance(x, str):
            if x in self.entries:
                return [x]
            if x.strip().startswith("="):
                return [n.id for n in ast.walk(self._parse(x)) if isinstance(n, ast.Name)]
        return []

    @staticmethod
    def _parse(expr: str) -> ast.Expression:
        try:
            return ast.parse(expr.strip()[1:].strip(), mode="eval")
        except SyntaxError:
            raise LedgerError("bad_value", f"bad expression {expr!r}") from None

    def _eval(self, x: Value, stack: tuple[str, ...]) -> float:
        if isinstance(x, bool):
            raise LedgerError("bad_value", f"not a length: {x!r}")
        if isinstance(x, (int, float)):
            return float(x)
        if not isinstance(x, str):
            raise LedgerError("bad_value", f"not a length: {x!r}")
        s = x.strip()
        if s in self.entries:
            return self._entry_value(s, stack)
        if s.startswith("="):
            return self._expr(self._parse(s).body, stack, s)
        try:
            return parse_length(s)
        except ValueError:
            if _IDENT.match(s):
                raise LedgerError("unknown_ref", f"unknown ledger id '{s}'") from None
            raise LedgerError("bad_value", f"not a length: {x!r}") from None

    def _entry_value(self, key: str, stack: tuple[str, ...]) -> float:
        if key in self._cache:
            return self._cache[key]
        if key in stack:
            chain = " -> ".join((*stack[stack.index(key):], key))
            raise LedgerError("cycle", f"ledger cycle: {chain}")
        v = self._eval(self.entries[key].v, (*stack, key))
        self._cache[key] = v
        return v

    def _expr(self, n: ast.AST, stack: tuple[str, ...], src: str) -> float:
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return float(n.value)
        if isinstance(n, ast.Name):
            if n.id not in self.entries:
                raise LedgerError("unknown_ref", f"unknown ledger id '{n.id}' in {src!r}")
            return self._entry_value(n.id, stack)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -self._expr(n.operand, stack, src)
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = self._expr(n.left, stack, src), self._expr(n.right, stack, src)
            if isinstance(n.op, ast.Add):
                return a + b
            if isinstance(n.op, ast.Sub):
                return a - b
            if isinstance(n.op, ast.Mult):
                return a * b
            if b == 0:
                raise LedgerError("bad_value", f"division by zero in {src!r}")
            return a / b
        raise LedgerError("bad_value", f"unsupported syntax in {src!r}")


def load_plan(path: str | Path) -> Plan:
    """Read plan.yaml into a Plan; raises PlanError with a readable message."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise PlanError(f"cannot read {path}: {e}") from e
    if not isinstance(data, dict):
        raise PlanError(f"{path}: top level must be a mapping")
    try:
        return Plan.model_validate(data)
    except ValidationError as e:
        lines = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
        raise PlanError(f"{path}: schema error\n  " + "\n  ".join(lines)) from e
