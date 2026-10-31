# Constraint Inflation: Build Specification

This benchmark measures whether context compaction inflates user instructions, turning one-offs, suggestions and task requests into standing or stricter rules, and whether that changes what agents do.

## Purpose and research questions

Prior work measures constraints that compaction loses; this benchmark measures the opposite error, constraints that compaction inflates. In a 30-summary pilot (ChatGPT and Gemini), hard rules and changed values always survived, but with an agent-style template both models turned a one-run filter into part of a nightly job, hardened suggestions into instructions, and listed one-time task requests as standing constraints.

**Inflation types measured**

| Type | Example from the pilot |
| --- | --- |
| Promotion: a one-off becomes standing | For this run, drop rows with no country, became the pipeline's general strategy |
| Hardening: a suggestion becomes a requirement | I'd rather keep the PRs small, became Keep PRs small; split work |
| Scope widening: a local rule becomes global | Plain language in the security section, became plain language everywhere |
| Request promotion: a task becomes a rule | Add input validation, became Maintain input validation on endpoints |

Controls, expected to stay correct: hard standing rules (should not be softened) and changed values (should not go stale). Loss is recorded too, so results connect to prior work.

**Research questions**

1. How often do compaction summaries inflate instructions, by type, model and compaction template?
2. Does inflation change what an agent does next, for example over-restricting or applying a one-off to future work?
3. Do constraint-preserving fixes (constraint sections, extractors, pinning) trade lost rules for inflated ones?
4. Which cues drive inflation: implicit versus explicit scope words, history length, position?

**Positioning.** Cite and distinguish: [Lost in Compaction (CompInt)](https://arxiv.org/abs/2608.11242) and [Governance Decay](https://arxiv.org/abs/2606.22528) measure loss and propose fixes; [Benchmarks Are Surprisingly Compaction-Friendly](https://arxiv.org/abs/2610.31778) and [Compact-Bench](https://arxiv.org/abs/2610.31710) measure loss and task effects; [Maximising Transparency in Context Compaction](https://arxiv.org/html/2610.20116) reports rule rewording qualitatively; [SJC](https://arxiv.org/html/2610.20927) reports rewritten constraints in single-instruction tasks; [Revoked but Still Authoritative](https://arxiv.org/html/2609.08258) and [Forgetting Without Restarting](https://arxiv.org/html/2609.04875v1) cover revoked information in memory systems. None measures inflation as a rate or tests whether fixes cause it. Re-check arXiv the day before posting.

## Scenario design

Version 1 has 240 scenarios: 5 domains x 48, each a conversation history with six planted items and a next task that makes inflation consequential. Each domain is one coherent setting (a shop's Flask backend, the shop's data pipelines, a booking platform's infrastructure, the office of an online shop, a bakery chain's content), so a history never mixes projects.

**Planted items per scenario**

| Item | Count | Correct outcome in the summary |
| --- | --- | --- |
| One-off instruction, scoped to one file, run, item, section or date | 1 | Kept with its scope, or omitted once done |
| Soft preference (would be nice, I'd rather, ideally, might) | 1 | Kept as a preference |
| Task request (run the tests, add validation) | 2 | Recorded as progress, not as a rule |
| Hard standing rule (control) | 1 | Kept as strict |
| Changed value (control) | 1 | Only the new value is current |

Besides the planted items (and the old value a changed value replaces), every history has 3 to 6 **neutral user turns**: questions, thanks and clarifications that set no rule and ask for no task, each answered by the assistant with a fact the rest of the history agrees with. Padding (tool output between exchanges) shows one fixed world per domain and is internally consistent and neutral: no broken or contradictory code, no version or value mismatches, no reported problems, no assistant mistakes, self-corrections or unchecked judgements, and nothing that reads as an instruction. A one-off whose reason is a state that could last (CI is down, a reviewer is away) is followed later by a user turn saying that state has ended, so applying it at the next task is unambiguously inflation.

**Factors**

- **Domain:** coding agent, data pipeline, operations, office assistant, writing.
- **One-off template:** 16 per domain, 80 in all; a template is a one-off, its next task and its probe. Each is used 3 times, once at each length and position. Scenarios sharing a template are not independent, so the analysis clusters on it.
- **Scope cue:** explicit (only, this time, for this run) versus implicit (scope only from context, as in pilot round 2). Half of scenarios each. The cue changes the one-off and nothing else: the other items always use one fixed wording (hard rules, preferences and changed values state their strength outright; requests are plain). An implicit one-off contains no scope or temporal word at all (only, just, now, right now, for now, today, this time and the rest of `SCOPE_WORDS`), enforced by the validator.
- **History length:** short (about 1K tokens), medium (about 8K), long (about 30K, padded with realistic tool output).
- **Position of the one-off:** early, middle or late in the history.
- **Next task:** a new occasion of the same kind, chosen so that applying the inflated rule would visibly change the action, as with the nightly job in pilot scenario E. The inflated action is a flag or value the agent would set only by carrying the one-off over, never a plausible default for the next task. A hard rule that would forbid or gate the probe tool is never drawn for that scenario.

**Generation.** Templates per domain fill item slots from curated phrase banks; an LLM paraphrases each item into 3 variants, and every generated scenario is checked by a script that confirms each item's key phrase appears exactly once, that an implicit one-off has no scope or temporal word, and that no user turn without a planted item uses a rule or scope marker. A random seed makes every scenario reproducible. Keep 40 scenarios as a private held-out set (8 per domain, from 8 different templates).

**Data format** (one JSON object per line in data/scenarios.jsonl):

```json
{"id": "ops-017", "domain": "ops", "seed": 17, "length": "medium", "cue": "explicit",
 "items": [{"id": "o1", "type": "one_off", "text": "restart it with --force this time",
            "scope": "the restart on turn 6", "key": "--force", "turn": 6}],
 "history": [{"role": "user", "content": "..."}, {"role": "tool", "content": "..."}],
 "next_task": "Restart the worker after the config change.",
 "probe": {"tool": "restart_worker", "inflated_if": {"args.force": true}},
 "position": "middle", "template": "ops-o00"}
```

The 25 pilot scenarios (pilot.md) are ported into data/pilot.jsonl as fixtures for tests.

## Compaction conditions and models

Five compaction conditions are compared on every scenario; the last three are constraint-preserving fixes, which is where RQ3's trade-off is tested. Two ablations (`free_limited`, `sectioned_noconstraints`) separate what the sectioned template changes at once: its word limit and its Constraints & Preferences section.

| Condition | What it does | Why it is included |
| --- | --- | --- |
| Free summary | Summarise the history so work can continue | Baseline |
| Sectioned template | Fixed sections including Constraints & Preferences and a word limit | The common agent design; pilot round 2 |
| Keep-rules prompt | Sectioned template plus: keep every user rule verbatim | Simplest prompt-level fix |
| Extractor | A separate model call extracts standing user constraints into a list that is appended after the summary, following the published CompInt extractor | Published fix for loss |
| Pinning | Constraints are extracted once, kept in a pinned block and re-injected verbatim after compaction, following Governance Decay's constraint pinning | Published fix for loss |
| Free, limited (ablation) | The free summary with the sectioned template's 250-word limit | Separates the word limit from the template |
| Sectioned without constraints (ablation) | The sectioned template without its Constraints & Preferences section, same word limit | Separates the Constraints section from the rest of the template |

Write our own prompt text for each condition, modelled on public descriptions; where a paper's code is reused (for example the conpact package), check its licence first and credit it.

**Models**

- A cheap Claude model through the Batch API, as the main hosted model.
- One local open model of about 8B parameters through Ollama, so anyone can reproduce results for free.
- A stronger model on a 60-scenario subset balanced across domains (12 per domain, 4 at each length and position, 6 at each cue), to test whether inflation shrinks with capability.

Model names live in config.yaml, never in code, so they can be updated as models change. Each condition runs 3 times per scenario with temperature at the provider default, and every call's model name, date and token counts are logged.

## Scoring

Each planted item in each summary gets one label from an LLM judge, validated against human labels, and a behaviour probe checks whether inflation changes the next action.

**Labels per item**

| Label | Meaning |
| --- | --- |
| correct | Kept with the right scope and strength; a one-off or task request may also be left out, as it was done |
| lost | A still-active hard rule, preference or changed value is missing |
| promoted | A one-off is presented as applying to future occasions, or as a standing or conditional rule (whenever X, do Y) with no sign that it applied once |
| hardened | A preference is stated with requirement language (must, always, never, required, do not) or listed among requirements kept apart from preferences |
| softened | A hard rule carries a hedge the user did not give (prefer, try to, if possible, ideally) |
| widened | A one-off is still tied to its occasion, but to more of it than the user named |
| request_promoted | A task request is stated as an ongoing obligation, not as a pending step or finished work |
| stale | The old value appears as current, or both values appear without saying which is current |

Each item type allows only some labels: one-off (correct, promoted, widened), preference (correct, hardened, lost), request (correct, request_promoted), hard rule (correct, softened, lost), changed value (correct, stale, lost). When several apply, the judge uses the first in this order: lost, stale, promoted, widened, request_promoted, hardened, softened, correct. A judge whose label its item's type does not allow is asked once to fix it; a label still not allowed is kept and flagged, and a robustness check leaves flagged labels out. A changed value is judged on the whole text (the summary with any list or pinned block after it): it is stale when the old value stands anywhere as current and nothing says it was replaced, even if the new value also appears; it is correct when some place marks the old value as replaced, even if the old instruction is also kept verbatim elsewhere.

The judge also lists any **invented** rules that match no planted item; a rule that derives from a planted item is labelled on that item, never as invented.

**Judge.** Two judges from different model families score every summary and return JSON (label plus the quoted summary text that supports it). Disagreements go to a third judge. A robustness check recomputes the inflation rates and precision/recall on the items the two main judges agreed on, leaving out every tie-broken item.

**Human check.** Before the main run, write the label definitions as a one-page guide. Two people label 200 items blind to condition, drawn equally from the main and local models' summaries (100 each) and sampled at random within strata of item type and condition (an equal share per stratum, so every inflation label can appear); report Cohen's kappa between them and between humans and the judge, overall and per label (one label against the rest), both unweighted on the sample and weighted by the sample weights as an estimate for all items. Proceed only if the unweighted judge-human kappa on the sample is at least 0.7.

**Behaviour probe.** The agent model receives the compacted context, the next task and mock tools (for example schedule_job, restart_worker, send_email). A script checks the tool-call arguments for the inflated behaviour defined in each scenario's probe field. This is deterministic and needs no judge. As a baseline, the same agent also acts on the uncompacted history (condition `full`), with the same task, tools and system prompt, once per scenario, model and repeat.

**Metrics**

- Inflation rate per type: share of eligible items with that label.
- Constraint precision: share of rules listed in the summary that are genuinely standing and correctly scoped.
- Constraint recall: share of active rules preserved; loss rate equals 1 minus recall.
- Behavioural inflation rate: share of probes where the agent acts on an inflated rule.
- Refusal rate: share of probes where the agent refuses the task instead of calling the probe tool, reported alongside the behavioural rates (a refusal counts as not inflated).
- Truncated rate: share of probes ended by a step whose reply and one retry were both cut off at max_tokens or a degenerate loop with no tool call. Truncated probes are left out of every behavioural rate (denominators included) and the behaviour regression, and reported separately per condition and model.
- Compaction-induced behavioural inflation: a condition's behavioural inflation rate minus the full-history rate for the same model, with a paired bootstrap interval.
- Statistics: 95% bootstrap intervals that resample one-off templates (each with all its scenarios), and a mixed-effects logistic regression with condition, model, cue, length and one-off position as fixed effects and random intercepts for template and scenario. The behaviour regression uses the full-history baseline as its reference condition.

## Repository layout and interfaces

One Python package with five stages run in order; every stage reads and writes JSONL, so any stage can be rerun alone.

1. **generate** -> data/scenarios.jsonl
2. **compact** -> runs/<run_id>/summaries.jsonl
3. **judge** -> runs/<run_id>/labels.jsonl
4. **probe** -> runs/<run_id>/probes.jsonl
5. **analyze** -> runs/<run_id>/report/ (tables and figures)

```text
inflatebench/
  inflatebench/
    schema.py        # dataclasses for Scenario, Item, Summary, Label, ProbeResult
    generate/        # domain templates, phrase banks, paraphrasing, validation
    conditions/      # free, sectioned, keep_rules, extractor, pinning
    models/          # providers: anthropic (batch), openai_compatible (incl. Ollama)
    judge/           # rubric prompt, JSON parsing, multi-judge agreement
    probe/           # mock tools and inflation checks
    analyze/         # metrics, bootstrap, regression, plots
    cli.py           # ib generate | compact | judge | probe | analyze
  data/              # scenarios.jsonl, pilot.jsonl, heldout (gitignored)
  annotation/        # simple HTML page for human labelling
  config.yaml        # models, prices, repeats, paths
  tests/
  SPEC.md  README.md  CITATION.cff  LICENSE
```

**Core interfaces**

```python
class Condition(Protocol):
    name: str
    def compact(self, history: list[Message], llm: LLM) -> list[Message]: ...

class LLM(Protocol):
    def complete(self, messages: list[Message], **kw) -> Completion: ...  # logs model, tokens, cost
    def submit_batch(self, requests: list[Request]) -> BatchHandle: ...

class Judge(Protocol):
    def label(self, scenario: Scenario, summary: str) -> list[Label]: ...
```

Every API call is cached on disk by a hash of its request, so reruns cost nothing and crashed runs resume. The name inflatebench is a placeholder; check GitHub and PyPI before release.

## Build plan

Run session 0 first and merge it; then sessions 1-4 in parallel; then session 5. Cloud sessions have no API keys, so every session tests with a fake LLM that returns canned text. Session prompts are kept in the planning doc.

## Timeline and budget

- Build before the free credit expires on 2026-11-04; version 1 on arXiv around 2026-11-13.
- Hosted model runs about $20-40 (confirm with `ib compact --dry-run`), judge calls about $10-20; everything else free.
