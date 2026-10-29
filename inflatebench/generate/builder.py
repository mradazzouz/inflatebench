"""Assemble scenarios from a domain template, its phrase banks and padding."""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Sequence

from inflatebench.generate.banks import Domain, Phrase, blocks_probe, count_key, cue_ok, item_cue
from inflatebench.generate.domains import DOMAINS
from inflatebench.generate.paraphrase import Paraphraser
from inflatebench.generate.padding import rows_for
from inflatebench.generate.validate import POSITIONS, approx_tokens, position, validate
from inflatebench.schema import CUES, LENGTHS, Item, Message, Probe, Scenario

TARGET_TOKENS = {"short": 1_000, "medium": 8_000, "long": 30_000}
TOKEN_TOLERANCE = 0.3  # accepted relative deviation from the target length
POSITION_TARGET = {"early": 1 / 6, "middle": 1 / 2, "late": 5 / 6}  # share of text before the one-off
MAX_ATTEMPTS = 40
MIN_BLOCK = 150  # leftover padding budget (chars) too small for a block
PER_DOMAIN = 48  # factor design repeats every 48 scenarios
TEMPLATES = 16  # one-off templates (one-off, next task, probe) per domain
NEUTRAL_TURNS = (3, 6)  # neutral user exchanges per scenario, inclusive


class GenerationError(RuntimeError):
    pass


def factors(index: int) -> tuple[str, str, str]:
    """(length, cue, position) for the index-th scenario of a domain.

    Template j = index % 16 is used three times (k = 0, 1, 2) per 48 scenarios, once at each
    length and once at each position, with cues 2:1 one way or the other. Over 48 scenarios
    every length and position gets 16, every cue 24, every length-cue and cue-position cell 8,
    and every length-position cell 4 to 6.
    """
    k, j = divmod(index % PER_DOMAIN, TEMPLATES)
    return LENGTHS[k], CUES[(j + k) % 2], POSITIONS[(k + j // 2) % 3]


def template_id(domain: str, index: int) -> str:
    return f"{domain}-o{index % TEMPLATES:02d}"


def scenario_seed(base_seed: int, index: int) -> int:
    return base_seed * 1000 + index


@dataclass
class _Event:
    messages: list[Message]
    item: Item | None = None  # its user message is messages[0]


def _ev(user: str, ack: str, tool: str | None = None, item: Item | None = None) -> _Event:
    msgs = [Message("user", user), Message("assistant", ack)]
    if tool:
        msgs.append(Message("tool", tool))
    return _Event(msgs, item)


def _order(rng: random.Random, events: dict[str, _Event]) -> list[str]:
    """Shuffle the middle events so the old value comes at least one event before its change."""
    names = list(events)
    while True:
        rng.shuffle(names)
        if names.index("before") + 1 < names.index("change"):
            return names


def _padding(rng: random.Random, domain: Domain, budget: int, keys: list[str], seen: set[str]) -> list[Message]:
    """Padding blocks for `budget` characters. A command already run in the scenario (`seen`)
    prints the same output again, so it is consistent, but a new command is preferred."""
    out: list[Message] = []
    while budget > MIN_BLOCK:
        repeat = None
        for _ in range(10):
            action, output = domain.padders[rng.randrange(len(domain.padders))](rng, rows_for(budget))
            if any(count_key(action, k) or count_key(output, k) for k in keys):
                continue
            if action not in seen:
                break
            repeat = repeat or (action, output)
        else:
            if repeat is None:
                break
            action, output = repeat
        seen.add(action)
        out += [Message("assistant", action), Message("tool", output)]
        budget -= len(action) + len(output)
    return out


def _assemble(domain: Domain, index: int, seed: int, rng: random.Random, para: Paraphraser) -> Scenario:
    length, cue, pos = factors(index)

    def say(p: Phrase, item_type: str) -> str:
        # Only the one-off follows the scenario's cue; every other item uses its fixed variant.
        c = item_cue(item_type, cue)
        return para.pick(rng, p.text(c), p.key, item_type, c)

    one_off = domain.one_offs[index % len(domain.one_offs)]
    # A hard rule that forbids or gates the probe tool would hide the one-off's effect.
    hards = [h for h in domain.hard_rules if not blocks_probe(h, one_off)]
    hard = hards[rng.randrange(len(hards))]
    pref = domain.preferences[rng.randrange(len(domain.preferences))]
    reqs = rng.sample(domain.requests, 2)
    change = domain.changes[rng.randrange(len(domain.changes))]

    def item(id_: str, type_: str, p: Phrase, text: str, scope: str | None = None) -> Item:
        return Item(id=id_, type=type_, text=text, key=p.key, turn=-1, scope=scope)

    hard_text = say(hard, "hard_rule")
    opener = _ev(f"{domain.intros[rng.randrange(len(domain.intros))]} {hard_text}", hard.ack,
                 item=item("h1", "hard_rule", hard, hard_text))
    middle = {
        "before": _ev(change.before, change.before_ack),
        "r1": _ev(t := say(reqs[0], "request"), reqs[0].ack, reqs[0].tool, item("r1", "request", reqs[0], t)),
        "r2": _ev(t := say(reqs[1], "request"), reqs[1].ack, reqs[1].tool, item("r2", "request", reqs[1], t)),
        "pref": _ev(t := say(pref, "preference"), pref.ack, pref.tool, item("p1", "preference", pref, t)),
        "change": _ev(t := say(change, "changed_value"), change.ack, change.tool,
                      item("c1", "changed_value", change, t, scope=f"replaces {change.old}")),
    }
    o_text = say(one_off, "one_off")
    o_event = _ev(o_text, one_off.ack, one_off.tool, item("o1", "one_off", one_off, o_text, one_off.scope))

    events = [opener] + [middle[n] for n in _order(rng, middle)]
    k = {"early": 1, "middle": 3, "late": rng.choice((5, 6))}[pos]
    events.insert(k, o_event)
    if one_off.resolved:
        # The user later says the one-off's reason has ended; always after the one-off.
        events.insert(rng.randint(k + 1, len(events)), _ev(*one_off.resolved))
    n_neutral = rng.randint(*NEUTRAL_TURNS)
    for user, reply in rng.sample(domain.neutral, n_neutral):
        events.insert(rng.randint(1, len(events)), _ev(user, reply))
    k = events.index(o_event)

    # Spread padding so that the share of text before the one-off hits its position target.
    size = lambda ev: sum(len(m.content) for m in ev.messages)
    total = TARGET_TOKENS[length] * 4
    base_before = sum(size(e) for e in events[:k])
    pad_total = max(0, total - sum(size(e) for e in events))
    pad_before = min(pad_total, max(0, int(POSITION_TARGET[pos] * total) - base_before))
    gaps = [0] * len(events)  # gaps[i] is padding after events[i]
    for i in range(k):
        gaps[i] = pad_before // k
    for i in range(k, len(events)):
        gaps[i] = (pad_total - pad_before) // (len(events) - k)

    keys = [ev.item.key for ev in events if ev.item]
    seen: set[str] = set()
    history: list[Message] = []
    items: list[Item] = []
    for ev, gap in zip(events, gaps):
        if ev.item:
            ev.item.turn = len(history)
            items.append(ev.item)
        history += ev.messages
        history += _padding(rng, domain, int(gap * rng.uniform(0.8, 1.2)), keys, seen)

    items.sort(key=lambda i: ["h1", "o1", "p1", "r1", "r2", "c1"].index(i.id))
    o1 = next(i for i in items if i.id == "o1")
    o1.scope = f"{one_off.scope} (turn {o1.turn})"
    return Scenario(
        id=f"{domain.name}-{index:03d}", domain=domain.name, seed=seed, length=length, cue=cue,
        items=items, history=history, next_task=one_off.next_task,
        probe=Probe(tool=one_off.probe_tool, inflated_if=dict(one_off.inflated_if)), position=pos,
        template=template_id(domain.name, index),
    )


def check(s: Scenario, pos: str) -> list[str]:
    """Validation plus the generator's own factor checks (cue, length and position)."""
    errors = validate(s)
    errors += [f"{i.id}: text lacks the {s.cue} cue" for i in s.items if not cue_ok(i.text, i.type, s.cue)]
    tokens = sum(approx_tokens(m.content) for m in s.history)
    target = TARGET_TOKENS[s.length]
    if abs(tokens - target) > TOKEN_TOLERANCE * target:
        errors.append(f"history is {tokens} tokens, target {target}")
    if position(s, "o1") != pos:
        errors.append(f"one-off is {position(s, 'o1')}, wanted {pos}")
    return errors


def build_scenario(domain: str, index: int, base_seed: int = 0, paraphraser: Paraphraser | None = None) -> Scenario:
    """Build the index-th scenario of a domain; the same arguments always give the same scenario."""
    dom = DOMAINS[domain]
    para = paraphraser or Paraphraser()
    seed = scenario_seed(base_seed, index)
    errors: list[str] = []
    for attempt in range(MAX_ATTEMPTS):
        rng = random.Random(f"{domain}:{seed}:{attempt}")
        s = _assemble(dom, index, seed, rng, para)
        errors = check(s, factors(index)[2])
        if not errors:
            return s
    raise GenerationError(f"{domain}-{index:03d}: no valid scenario after {MAX_ATTEMPTS} attempts: {errors}")


def generate(n: int = 240, seed: int = 0, paraphraser: Paraphraser | None = None) -> list[Scenario]:
    """n scenarios spread evenly over the domains, grouped by domain."""
    names = list(DOMAINS)
    para = paraphraser or Paraphraser()
    out = []
    for d, name in enumerate(names):
        count = n // len(names) + (1 if d < n % len(names) else 0)
        if count > 1000:
            raise ValueError("at most 1000 scenarios per domain (seeds are base_seed * 1000 + index)")
        out += [build_scenario(name, i, seed, para) for i in range(count)]
    return out


HELDOUT_SIZE = 40
HELDOUT_SEED = 1000  # base seed of the held-out set, apart from the main set's usual small seeds


# Occurrence k (0, 1, 2) of each held-out template, found by a seeded random search so that the
# set is balanced (see heldout_indices); tests check the balance.
HELDOUT_OCCURRENCE = (0, 2, 1, 1, 1, 2, 2, 1, 2, 0, 1, 2, 2, 1, 0, 2, 1, 0, 0, 1,
                      0, 1, 0, 1, 2, 1, 0, 1, 0, 1, 2, 1, 0, 0, 2, 0, 2, 2, 2, 0)


def heldout_indices() -> list[tuple[str, int]]:
    """(domain, index) for the 40 held-out scenarios: 8 per domain, each from a different one-off
    template (half of them odd, half even), cue 20/20 overall and 4/4 per domain, and lengths
    and positions 13 or 14 each."""
    picks = [(name, (3 * d + 2 * m + (m >= 4)) % TEMPLATES) for d, name in enumerate(DOMAINS) for m in range(8)]
    return [(name, k * TEMPLATES + j) for (name, j), k in zip(picks, HELDOUT_OCCURRENCE)]


# Indices within a domain's 48 scenarios for a model run on a subset (config models.<key>.subset):
# 12 different one-off templates, 4 at each length and each position, 6 at each cue, 2 in every
# cue-length and cue-position cell and at least 1 in every length-position cell.
SUBSET_INDICES = (0, 2, 7, 11, 20, 22, 29, 31, 33, 37, 44, 46)


def balanced_subset(scenarios: Sequence[Scenario], n: int) -> list[Scenario]:
    """n scenarios spread evenly over the domains (the first n % domains get one more), so a
    subset never stands for some domains only, as the first n of the file would.

    Within each domain (in file order, as ib generate writes them) the scenarios at
    SUBSET_INDICES come first, then the rest in order; with 12 per domain the subset is balanced
    over templates, lengths, positions and cues. Returned in file order.
    """
    groups: dict[str, list[int]] = {}
    for k, s in enumerate(scenarios):
        groups.setdefault(s.domain, []).append(k)
    picked: list[int] = []
    for d, members in enumerate(groups.values()):
        count = n // len(groups) + (1 if d < n % len(groups) else 0)
        first = [members[i] for i in SUBSET_INDICES if i < len(members)]
        picked += (first + [k for k in members if k not in first])[:count]
    return [scenarios[k] for k in sorted(picked)]


def generate_heldout(seed: int = HELDOUT_SEED, paraphraser: Paraphraser | None = None) -> list[Scenario]:
    """The private held-out set; ids are prefixed "heldout-" so they never clash with the main set."""
    para = paraphraser or Paraphraser()
    return [replace(s, id=f"heldout-{s.id}")
            for s in (build_scenario(name, i, seed, para) for name, i in heldout_indices())]
