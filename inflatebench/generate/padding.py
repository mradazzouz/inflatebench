"""Shared helpers for realistic tool-output padding.

Padding is pure observation (logs, listings, tables, drafts) so it never adds
an instruction of its own. Every helper draws only from the rng it is given.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

FIRST = ("Anna", "Ben", "Chen", "Dana", "Eli", "Fatima", "Gabor", "Hana", "Ivan", "Julia",
         "Kofi", "Lea", "Marek", "Nora", "Omar", "Petra", "Quinn", "Rosa", "Sami", "Teo")
LAST = ("Novak", "Schmidt", "Okafor", "Lindqvist", "Horvath", "Moreau", "Tanaka", "Rossi",
        "Kowalski", "Haddad", "Silva", "Byrne", "Varga", "Nilsen", "Ortiz")
NOUNS = ("order", "invoice", "customer", "booking", "report", "user", "session", "payment",
         "account", "product", "shipment", "ticket", "event", "address", "item")
VERBS = ("load", "parse", "build", "fetch", "update", "render", "validate", "sync", "resolve",
         "format", "compute", "merge", "store", "check", "list")
BASE_TIME = datetime(2026, 10, 19, 8, 0, 0)


def pick(rng: random.Random, seq):
    return seq[rng.randrange(len(seq))]


def name(rng: random.Random) -> str:
    return f"{pick(rng, FIRST)} {pick(rng, LAST)}"


def email(rng: random.Random, domain: str = "example.com", person: str | None = None) -> str:
    first, last = (person or name(rng)).lower().split()
    return f"{first}.{last}@{domain}"


def sha(rng: random.Random, n: int = 7) -> str:
    return "".join(pick(rng, "0123456789abcdef") for _ in range(n))


def ident(rng: random.Random) -> str:
    return f"{pick(rng, VERBS)}_{pick(rng, NOUNS)}"


def clock(rng: random.Random, start: datetime | None = None, span_min: int = 600) -> datetime:
    return (start or BASE_TIME) + timedelta(seconds=rng.randrange(span_min * 60))


def times(rng: random.Random, n: int, step_s: int = 40) -> list[datetime]:
    t = clock(rng)
    out = []
    for _ in range(n):
        t += timedelta(seconds=rng.randrange(1, step_s))
        out.append(t)
    return out


def table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a plain ASCII table like psql or kubectl would print."""
    widths = [max(len(str(c)) for c in col) for col in zip(headers, *rows)]
    line = lambda cells: "  ".join(str(c).ljust(w) for c, w in zip(cells, widths)).rstrip()
    return "\n".join([line(headers)] + [line(r) for r in rows])


def rows_for(budget_chars: int, chars_per_row: int = 70, lo: int = 2, hi: int = 80) -> int:
    return max(lo, min(hi, budget_chars // chars_per_row))
