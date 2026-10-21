"""The applier contract: one class per kind of customizing (Open/Closed: a new kind is a new class in the registry).

An applier reads what the site has (`diff`, never writes) and writes what the YAML declares (`write`, idempotent). The engine
runs `plan` (diffs only) or `apply` (diff, then write what differs) over every applier in a fixed order.
"""

import datetime
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class Change:
    kind: str
    name: str
    action: str  # "create" or "update"
    fields: tuple[str, ...] = field(default=())

    def __str__(self):
        detail = f" ({', '.join(self.fields)})" if self.fields else ""
        return f"{self.action:<6} {self.kind}: {self.name}{detail}"


class ResourceApplier(ABC):
    """Brings one kind of Frappe metadata to the state the YAML declares."""

    kind: str = ""

    @abstractmethod
    def items(self, bundle) -> list:
        """The specs of this kind in the bundle."""

    @abstractmethod
    def name_of(self, spec) -> str:
        """A readable name of one spec, for the plan."""

    @abstractmethod
    def diff(self, spec) -> tuple[str, ...] | None:
        """None when the site matches the spec, () when the record is missing, else the names of the differing fields."""

    @abstractmethod
    def write(self, spec) -> None:
        """Create or update the record so that diff(spec) is None."""

    def change(self, spec):
        differing = self.diff(spec)
        if differing is None:
            return None
        return Change(self.kind, self.name_of(spec), "create" if differing == () else "update", differing)

    def plan(self, bundle) -> list[Change]:
        return [c for c in (self.change(s) for s in self.items(bundle)) if c]

    def apply(self, bundle) -> list[Change]:
        changes = []
        for spec in self.items(bundle):
            change = self.change(spec)
            if change:
                self.write(spec)
                changes.append(change)
        return changes


def same(current, wanted) -> bool:
    """Compare a value read from the database with a declared one: None and "" are equal, numbers by value, times as HH:MM:SS,
    JSON text by content."""
    current, wanted = normal(current), normal(wanted)
    if isinstance(current, (int, float)) and isinstance(wanted, (int, float)):
        return abs(float(current) - float(wanted)) < 1e-9
    return current == wanted


def normal(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime.timedelta):
        seconds = int(value.total_seconds())
        return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, str) and value[:1] in "[{":
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def differing(current: dict, wanted: dict) -> tuple[str, ...] | None:
    keys = tuple(k for k, v in wanted.items() if not same(current.get(k), v))
    return keys or None
