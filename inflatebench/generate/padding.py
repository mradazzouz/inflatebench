"""Shared helpers for realistic tool-output padding.

Padding is pure observation (logs, listings, tables, drafts) so it never adds an instruction
of its own. It is also consistent: each domain describes one fixed world (a codebase, a cluster,
a warehouse, an office, a set of drafts) built from a fixed seed, and a block's output depends
only on that world and its own command, which names everything that shapes the output (the
file, the page, the time window, the number of lines). Running the same command twice therefore
prints the same thing, and two commands about the same thing agree. The scenario's rng only
chooses which command to run. Padding shows no problems (failures, warnings, nearly full
disks), no assistant judgement and nothing the user would have to act on.
"""

from __future__ import annotations

import random
from datetime import datetime

FIRST = ("Anna", "Ben", "Chen", "Dana", "Eli", "Fatima", "Gabor", "Hana", "Ivan", "Julia",
         "Kofi", "Lea", "Marek", "Nora", "Omar", "Petra", "Quinn", "Rosa", "Sami", "Teo")
LAST = ("Novak", "Schmidt", "Okafor", "Lindqvist", "Horvath", "Moreau", "Tanaka", "Rossi",
        "Kowalski", "Haddad", "Silva", "Byrne", "Varga", "Nilsen", "Ortiz")
NOUNS = ("order", "invoice", "customer", "booking", "report", "user", "session", "payment",
         "account", "product", "shipment", "ticket", "event", "address", "item")
VERBS = ("load", "parse", "build", "fetch", "update", "render", "validate", "sync", "resolve",
         "format", "compute", "merge", "store", "check", "list")
BASE_TIME = datetime(2026, 10, 19, 8, 0, 0)


def stable(*key: object) -> random.Random:
    """An rng fixed by `key`: the same world entity or command always gets the same draws."""
    return random.Random(":".join(map(str, key)))


def pick(rng: random.Random, seq):
    return seq[rng.randrange(len(seq))]


def name(rng: random.Random) -> str:
    return f"{pick(rng, FIRST)} {pick(rng, LAST)}"


def email(rng: random.Random | None, domain: str = "example.com", person: str | None = None) -> str:
    first, last = (person or name(rng)).lower().split()
    return f"{first}.{last}@{domain}"


def sha(rng: random.Random, n: int = 7) -> str:
    return "".join(pick(rng, "0123456789abcdef") for _ in range(n))


def table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a plain ASCII table like psql or kubectl would print."""
    widths = [max(len(str(c)) for c in col) for col in zip(headers, *rows)]
    line = lambda cells: "  ".join(str(c).ljust(w) for c, w in zip(cells, widths)).rstrip()
    return "\n".join([line(headers)] + [line(r) for r in rows])


def rows_for(budget_chars: int, chars_per_row: int = 70, lo: int = 2, hi: int = 80) -> int:
    return max(lo, min(hi, budget_chars // chars_per_row))
