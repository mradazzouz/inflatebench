"""Judge: rubric prompt, JSON parsing, multi-judge agreement."""

from __future__ import annotations

from typing import Protocol

from inflatebench.schema import Label, Scenario


class Judge(Protocol):
    def label(self, scenario: Scenario, summary: str) -> list[Label]: ...
