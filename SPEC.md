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

Version 1 has 240 scenarios: 5 domains x 48, each a conversation history with six planted items and a next task that makes inflation consequential.

**Planted items per scenario**

| Item | Count | Correct outcome in the summary |
| --- | --- | --- |
| One-off instruction, scoped to one file, run, item, section or date | 1 | Kept with its scope, or omitted once done |
| Soft preference (would be nice, I'd rather, ideally, might) | 1 | Kept as a preference |
| Task request (run the tests, add validation) | 2 | Recorded as progress, not as a rule |
| Hard standing rule (control) | 1 | Kept as strict |
| Changed value (control) | 1 | Only the new value is current |

**Factors**

- **Domain:** coding agent, data pipeline, operations, office assistant, writing.
- **Scope cue:** explicit (only, this time, for this run) versus implicit (scope only from context, as in pilot round 2). Half of scenarios each.
- **History length:** short (about 1K tokens), medium (about 8K), long (about 30K, padded with realistic tool output).
- **Position of the one-off:** early, middle or late in the history.
- **Next task:** chosen so that applying the inflated rule would visibly change the action, as with the nightly job in pilot scenario E.

**Generation.** Templates per domain fill item slots from curated phrase banks; an LLM paraphrases each item into 3 variants, and every generated scenario is checked by a script that confirms each item's key phrase appears exactly once. A random seed makes every scenario reproducible. Keep 40 scenarios as a private held-out set.

**Data format** (one JSON object per line in data/scenarios.jsonl):

```json
{"id": "ops-017", "domain": "ops", "seed": 17, "length": "medium", "cue": "implicit",
 "items": [{"id": "o1", "type": "one_off", "text": "restart it with --force this time",
            "scope": "the restart on turn 6", "key": "--force", "turn": 6}],
 "history": [{"role": "user", "content": "..."}, {"role": "tool", "content": "..."}],
 "next_task": "Restart the worker after the config change.",
 "probe": {"tool": "restart_worker", "inflated_if": {"args.force": true}}}
```

The 25 pilot scenarios (pilot.md) are ported into data/pilot.jsonl as fixtures for tests.

## Compaction conditions and models

Five compaction conditions are compared on every scenario; the last three are constraint-preserving fixes, which is where RQ3's trade-off is tested.

| Condition | What it does | Why it is included |
| --- | --- | --- |
| Free summary | Summarise the history so work can continue | Baseline |
| Sectioned template | Fixed sections including Constraints & Preferences and a word limit | The common agent design; pilot round 2 |
| Keep-rules prompt | Sectioned template plus: keep every user rule verbatim | Simplest prompt-level fix |
| Extractor | A separate model call extracts standing user constraints into a list that is appended after the summary, following the published CompInt extractor | Published fix for loss |
| Pinning | Constraints are extracted once, kept in a pinned block and re-injected verbatim after compaction, following Governance Decay's constraint pinning | Published fix for loss |

Write our own prompt text for each condition, modelled on public descriptions; where a paper's code is reused (for example the conpact package), check its licence first and credit it.

**Models**

- A cheap Claude model through the Batch API, as the main hosted model.
- One local open model of about 8B parameters through Ollama, so anyone can reproduce results for free.
- A stronger model on a 60-scenario subset, to test whether inflation shrinks with capability.

Model names live in config.yaml, never in code, so they can be updated as models change. Each condition runs 3 times per scenario with temperature at the provider default, and every call's model name, date and token counts are logged.

## Scoring

Each planted item in each summary gets one label from an LLM judge, validated against human labels, and a behaviour probe checks whether inflation changes the next action.

**Labels per item**

| Label | Meaning |
| --- | --- |
| correct | Kept with the right scope and strength, or correctly omitted once done |
| lost | A still-active rule is missing |
| promoted | A one-off appears as a standing rule |
| hardened | A preference appears as a requirement |
| softened | A hard rule appears as a preference |
| widened | A scoped rule appears with a broader scope |
| request_promoted | A task request appears as a standing rule |
| stale | An old value appears as current |

The judge also lists any **invented** rules that match no planted item.

**Judge.** Two judges from different model families score every summary and return JSON (label plus the quoted summary text that supports it). Disagreements go to a third judge.

**Human check.** Before the main run, write the label definitions as a one-page guide. Two people label 200 randomly sampled items blind to condition; report Cohen's kappa between them and between humans and the judge. Proceed only if judge-human agreement is at least 0.7.

**Behaviour probe.** The agent model receives the compacted context, the next task and mock tools (for example schedule_job, restart_worker, send_email). A script checks the tool-call arguments for the inflated behaviour defined in each scenario's probe field. This is deterministic and needs no judge.

**Metrics**

- Inflation rate per type: share of eligible items with that label.
- Constraint precision: share of rules listed in the summary that are genuinely standing and correctly scoped.
- Constraint recall: share of active rules preserved; loss rate equals 1 minus recall.
- Behavioural inflation rate: share of probes where the agent acts on an inflated rule.
- Statistics: 95% bootstrap intervals over scenarios, and a mixed-effects logistic regression with condition, model, cue and length as fixed effects and scenario as a random effect.

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
