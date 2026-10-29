"""Dataclasses for every record the pipeline reads or writes as JSONL."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Iterable, Iterator, TypeVar

ROLES = ("system", "user", "assistant", "tool")
ITEM_TYPES = ("one_off", "preference", "request", "hard_rule", "changed_value")
LABELS = (
    "correct",
    "lost",
    "promoted",
    "hardened",
    "softened",
    "widened",
    "request_promoted",
    "stale",
)
# A rule in the summary that matches no planted item; carries item_id=None.
INVENTED = "invented"
LENGTHS = ("short", "medium", "long")
CUES = ("explicit", "implicit")

T = TypeVar("T", bound="Record")


def _check(value: Any, allowed: tuple[str, ...], what: str) -> None:
    if value not in allowed:
        raise ValueError(f"invalid {what} {value!r}; expected one of {allowed}")


class Record:
    """Base for records: strict from_dict, to_dict and JSON helpers."""

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        known = {f.name for f in fields(cls)}  # type: ignore[arg-type]
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"{cls.__name__}: unknown fields {sorted(unknown)}")
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)  # type: ignore[call-overload]

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class Message(Record):
    role: str
    content: str

    def __post_init__(self) -> None:
        _check(self.role, ROLES, "role")


@dataclass
class Item(Record):
    """A planted instruction; `key` must appear exactly once in the history."""

    id: str
    type: str
    text: str
    key: str
    turn: int
    scope: str | None = None

    def __post_init__(self) -> None:
        _check(self.type, ITEM_TYPES, "item type")


@dataclass
class Probe(Record):
    """Tool to watch and the dotted argument paths that signal inflation."""

    tool: str
    inflated_if: dict[str, Any]


@dataclass
class Scenario(Record):
    id: str
    domain: str
    seed: int
    length: str
    cue: str
    items: list[Item]
    history: list[Message]
    next_task: str
    probe: Probe

    def __post_init__(self) -> None:
        _check(self.length, LENGTHS, "length")
        _check(self.cue, CUES, "cue")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Scenario:
        data = dict(data)
        data["items"] = [Item.from_dict(i) for i in data.get("items", [])]
        data["history"] = [Message.from_dict(m) for m in data.get("history", [])]
        if "probe" in data:
            data["probe"] = Probe.from_dict(data["probe"])
        return super().from_dict(data)


@dataclass
class Summary(Record):
    """Compacted context produced by one condition for one scenario and repeat."""

    scenario_id: str
    condition: str
    model: str
    repeat: int
    messages: list[Message]

    @property
    def text(self) -> str:
        return "\n\n".join(m.content for m in self.messages)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Summary:
        data = dict(data)
        data["messages"] = [Message.from_dict(m) for m in data.get("messages", [])]
        return super().from_dict(data)


@dataclass
class Label(Record):
    """One judge's label for one planted item (or an invented rule) in a summary."""

    scenario_id: str
    condition: str
    model: str
    repeat: int
    judge: str
    item_id: str | None
    label: str
    quote: str = ""

    def __post_init__(self) -> None:
        if self.item_id is None:
            if self.label != INVENTED:
                raise ValueError("a label without item_id must be 'invented'")
        else:
            _check(self.label, LABELS, "label")


@dataclass
class ProbeResult(Record):
    scenario_id: str
    condition: str
    model: str
    repeat: int
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    inflated: bool = False
    agent: str = ""  # model that acted on the summary (model is the one that compacted)
    probe_called: bool = False  # whether the agent called the probe tool at all


def write_jsonl(path: str | Path, records: Iterable[Record]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(r.to_json() + "\n")


def read_jsonl(path: str | Path, cls: type[T]) -> Iterator[T]:
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield cls.from_dict(json.loads(line))
