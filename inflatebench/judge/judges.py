"""LLM judge and the two-judges-plus-tie-break panel."""

from __future__ import annotations

import json
from typing import Any

from inflatebench.conditions import neutral_context
from inflatebench.judge.parse import JudgeError, Verdict, disallowed, parse_verdict, same_rule, unquoted
from inflatebench.judge.rubric import ALLOWED_LABELS, build_prompt
from inflatebench.models import LLM
from inflatebench.schema import INVENTED, Label, Message, Scenario, Summary

FINAL = "final"


def _meta(summary: Summary | str) -> tuple[str, dict[str, Any]]:
    """The text to judge (a Summary in the neutral format, so the condition stays hidden)."""
    if isinstance(summary, Summary):
        return neutral_context(summary.messages), {"condition": summary.condition, "model": summary.model,
                              "repeat": summary.repeat}
    return summary, {"condition": "", "model": "", "repeat": 0}


def verdict_labels(verdict: Verdict, scenario: Scenario, judge: str,
                   meta: dict[str, Any]) -> list[Label]:
    labels = [Label(scenario_id=scenario.id, judge=judge, item_id=item.id,
                    label=verdict.items[item.id][0], quote=verdict.items[item.id][1],
                    quote_flagged=item.id in verdict.flagged_items,
                    type_flagged=item.id in verdict.flagged_types, **meta)
              for item in scenario.items]
    labels += [Label(scenario_id=scenario.id, judge=judge, item_id=None, label=INVENTED,
                     quote=q, quote_flagged=q in verdict.flagged_invented, **meta)
               for q in verdict.invented]
    return labels


class LLMJudge:
    """Scores one summary with the rubric prompt; retries when the reply is malformed."""

    def __init__(self, name: str, llm: LLM, retries: int = 2, **params: Any) -> None:
        self.name = name
        self.llm = llm
        self.retries = retries
        self.params = params

    def verdict(self, scenario: Scenario, summary: str) -> Verdict:
        """Parse the judge's reply, retrying malformed ones. Quotes missing from the summary,
        and labels the item's type does not allow, get one re-ask together; any still wrong
        after it are flagged on the verdict (and kept as given)."""
        messages = build_prompt(scenario, summary)
        error: JudgeError | None = None
        failures, reasked = 0, False
        while failures <= self.retries:
            reply = self.llm.complete(messages, **self.params).text
            try:
                verdict = parse_verdict(reply, scenario)
            except JudgeError as e:
                error, failures = e, failures + 1
                # Show the judge its broken reply and the error, so the retry is a new request
                # (an identical request would be served from the disk cache).
                messages = messages + [
                    Message("assistant", reply),
                    Message("user", f"That reply was invalid: {e}. Reply again with JSON only."),
                ]
                continue
            items, invented = unquoted(verdict, summary)
            off_type = disallowed(verdict, scenario)
            if (items or invented or off_type) and not reasked:
                reasked = True
                problems = []
                if items or invented:
                    missing = [verdict.items[i][1] for i in sorted(items)] + sorted(invented)
                    problems.append("These quotes are not in the summary: "
                                    + "; ".join(json.dumps(q, ensure_ascii=False) for q in missing)
                                    + '. Copy every quote verbatim from the summary, or use "" when '
                                    "a label rests on absence.")
                if off_type:
                    types = {i.id: i.type for i in scenario.items}
                    problems.append("These labels are not allowed for the item's type: " + "; ".join(
                        f"{i} ({types[i]}) is {verdict.items[i][0]!r}, allowed: "
                        + ", ".join(ALLOWED_LABELS[types[i]]) for i in sorted(off_type)) + ".")
                messages = messages + [
                    Message("assistant", reply),
                    Message("user", " ".join(problems) + " Reply again with the full JSON only."),
                ]
                continue
            verdict.flagged_items, verdict.flagged_invented = items, invented
            verdict.flagged_types = off_type
            return verdict
        raise JudgeError(f"{self.name} failed on {scenario.id}: {error}")

    def label(self, scenario: Scenario, summary: Summary | str) -> list[Label]:
        text, meta = _meta(summary)
        return verdict_labels(self.verdict(scenario, text), scenario, self.name, meta)

    def prefetch(self, scenario: Scenario, summary: str) -> None:
        """Queue this judge's first call when its LLM batches calls (models.Deferred)."""
        want = getattr(self.llm, "want", None)
        if want is not None:
            want(build_prompt(scenario, summary), **self.params)


class PanelJudge:
    """Two judges score every summary; a third decides the items they disagree on.

    `label` returns every judge's labels plus the resolved ones under judge="final".
    Invented rules are final when both judges list them; a rule only one judge lists
    is kept if the tie-break judge lists it too.
    """

    def __init__(self, first: LLMJudge, second: LLMJudge, tiebreak: LLMJudge) -> None:
        names = [first.name, second.name, tiebreak.name]
        if len(set(names + [FINAL])) != 4:
            raise ValueError(f"judge names must be distinct and not {FINAL!r}: {names}")
        self.first, self.second, self.tiebreak = first, second, tiebreak
        self.name = FINAL

    @property
    def judges(self) -> tuple[LLMJudge, LLMJudge, LLMJudge]:
        return self.first, self.second, self.tiebreak

    def label(self, scenario: Scenario, summary: Summary | str) -> list[Label]:
        text, meta = _meta(summary)
        # With batched judges, both scores go out in the first phase, the tie-break in the next.
        self.second.prefetch(scenario, text)
        a = self.first.verdict(scenario, text)
        b = self.second.verdict(scenario, text)
        disputed = [i.id for i in scenario.items if a.items[i.id][0] != b.items[i.id][0]]
        agreed_inv = [q for q in a.invented if any(same_rule(q, r) for r in b.invented)]
        open_inv = ([q for q in a.invented if q not in agreed_inv]
                    + [r for r in b.invented if not any(same_rule(r, q) for q in a.invented)])

        c = self.tiebreak.verdict(scenario, text) if disputed or open_inv else None
        items, flagged, flagged_types = {}, set(), set()
        for item in scenario.items:
            source = c if item.id in disputed else a
            items[item.id] = source.items[item.id]
            if item.id in source.flagged_items:
                flagged.add(item.id)
            if item.id in source.flagged_types:
                flagged_types.add(item.id)
        invented = agreed_inv
        if c is not None:
            invented = invented + [q for q in open_inv if any(same_rule(q, r) for r in c.invented)]
        final = Verdict(items=items, invented=invented, flagged_items=flagged,
                        flagged_invented={q for q in invented
                                          if q in a.flagged_invented | b.flagged_invented},
                        flagged_types=flagged_types)

        out = verdict_labels(a, scenario, self.first.name, meta)
        out += verdict_labels(b, scenario, self.second.name, meta)
        if c is not None:
            # Record the tie-break judge's labels only where it was asked to decide.
            out += [lab for lab in verdict_labels(c, scenario, self.tiebreak.name, meta)
                    if lab.item_id in disputed or lab.item_id is None]
        out += verdict_labels(final, scenario, FINAL, meta)
        return out
