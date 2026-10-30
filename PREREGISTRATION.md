# Preregistration: Constraint Inflation in Context Compaction

- **Date:** 2026-10-29
- **Author:** Mohamed Azouz Mrad
- **Frozen against:** SPEC.md and code at `main` commit `e750a7c`, plus PR #14 (balanced strong-model subset; human-check sample split over models). Function and file names below refer to that code.

**Status.** No real-model results exist yet. The only model outputs so far are from the 30-summary pilot (ChatGPT and Gemini; `pilot.md`) and its 25 scenarios ported into `data/pilot.jsonl`. These are exploratory: they motivated the hypotheses and serve as test fixtures. They are excluded from every confirmatory analysis.

## 1. Confirmatory hypotheses

"Combined inflation" is the primary outcome (section 2). Each hypothesis has a direction. All comparisons pool the confirmatory models (section 3.4), with model as a fixed effect.

| | Hypothesis | Direction |
| --- | --- | --- |
| H1 | `sectioned` has a higher combined inflation rate than `free`. | sectioned > free |
| H2 | The Constraints & Preferences section drives H1: (a) `sectioned` > `sectioned_noconstraints` in combined inflation, and (b) `free_limited` does not differ meaningfully from `free`. | (a) greater; (b) equivalent |
| H3 | Each of `extractor` and `pinning`, relative to `sectioned`, (a) has lower loss and (b) has higher combined inflation. | (a) loss lower; (b) inflation higher |
| H4 | Implicit scope cues give more promotion of one-offs than explicit cues. | implicit > explicit |
| H5 | Compaction-induced behavioural inflation (the condition's behavioural rate minus the `full` rate) is greater than zero for `sectioned`, `extractor` and `pinning`. | > 0 for each |
| H6 | Controls: the softening rate of hard rules and the stale rate of changed values each stay below 5%. | < 0.05 |

## 2. Outcomes

All outcomes are computed from the final panel labels (judge `final`) by `inflatebench/analyze/metrics.py`. Every rate is a ratio of sums over all items (or probes) in a cell, not a mean of per-scenario rates.

**Eligibility** (`INFLATION_TYPES`, `CONTROL_TYPES`):

| Type | Eligible items |
| --- | --- |
| promoted | one-offs |
| widened | one-offs, and any scoped item that is not a changed value |
| hardened | preferences |
| request_promoted | task requests |
| softened | hard rules |
| stale | changed values |
| lost | active items: hard rules, changed values, preferences (`ACTIVE`) |

**Primary outcome: combined inflation rate.** The numerator counts items eligible for at least one inflation type (promoted, widened, hardened, request_promoted) and labelled with a type they are eligible for (`any_inflation`). The denominator counts items eligible for at least one inflation type (`inflation_eligible`). Each item counts at most once.

**Secondary outcomes.**

- **Rate of each type:** items with that label over eligible items (`type_counts`). This covers the four inflation types, plus softened and stale (the controls) and lost.
- **Constraint precision** (`precision_counts`): genuine standing rules over all listed rules. Genuine standing rules are active items labelled correct, hardened or softened (`GENUINE`). All listed rules are those genuine rules, plus items labelled promoted, widened, request_promoted or stale (`SPURIOUS`), plus invented rules.
- **Constraint recall** (`recall_counts`): active items not labelled lost over active items. The **loss rate** is 1 − recall.
- **Behavioural inflation rate** (`behaviour_counts`): probes where a call to the probe tool matches the scenario's `probe.inflated_if` (`probe/check.py`), over all probes. The secondary versions are `called_counts` and `behaviour_when_called_counts`.
- **Compaction-induced behavioural inflation:** a condition's behavioural rate minus the `full` rate for the same model (`diff_ci` with baseline `full`, reported as `induced` in `behaviour.csv`).
- **Refusal rate** (`refusal_counts`): probes where the agent refused the task and never called the probe tool. This counts provider refusals and refusals in text (`probe/check.refusal`). Refusals count as not inflated.
- **Invented rules per summary** (`invented_frame`).

## 3. Design

### 3.1 Scenarios

- **Main set:** 240 scenarios from `ib generate` (base seed 0): 5 domains (coding, pipeline, ops, office, writing) with 48 scenarios each.
- **Templates:** each domain has 16 one-off templates (80 in total). A template fixes the one-off, the next task and the probe.
- **Template use:** each template is used 3 times, once at each length (about 1K, 8K and 30K tokens) and once at each position (early, middle, late). Cue (explicit or implicit) is split 24/24 per domain (`builder.factors`).
- **Planted items:** each scenario has 6: one one-off, one soft preference, two task requests, one hard rule and one changed value. There are also 3 to 6 neutral user turns.
- **Validation:** every scenario passes `generate/validate.py`. The validator checks that each key phrase appears exactly once, that implicit one-offs contain no `SCOPE_WORDS`, and that no rule markers appear outside planted items.
- **Held-out set:** 40 scenarios from `ib generate --heldout` (seed 1000, 8 per domain, each from a different template). The set stays private and is not used in any confirmatory analysis. Any later run on it is labelled exploratory.

### 3.2 Conditions

The study has seven compaction conditions (`config.yaml`): `free`, `sectioned`, `keep_rules`, `extractor`, `pinning`, `free_limited` and `sectioned_noconstraints`. The prompts are in `inflatebench/conditions/prompts/`. Within a repeat, `extractor` and `pinning` reuse the `sectioned` summary from the cache, so their comparison with `sectioned` is paired. `keep_rules` is included in all descriptive results but is not part of a confirmatory hypothesis.

### 3.3 Full-history probe baseline

Condition `full`: the agent acts on the uncompacted history. It gets the same task, tools and system prompt as the compacted conditions (`probe/run.probe_full`). It runs once per scenario, model and repeat.

### 3.4 Models and repeats

- **`main`:** a cheap Claude model run through the Batch API. **Confirmatory.**
- **`local`:** an open model of about 8B parameters through Ollama (`llama3.1:8b`). **Confirmatory.**
- **`strong`:** a stronger model on a 60-scenario subset, `subset: 60` (`generate.balanced_subset`). The subset has 12 scenarios per domain from 12 different templates. Each domain's 12 include 4 at each length, 4 at each position and 6 at each cue, and every length × position cell is covered. The strong model is **exploratory only**: it sees a quarter of the scenarios, so it is not in the confirmatory tests.
- **Model ids:** the exact ids for `main`, `strong`, the judges and the tie-break are filled into `config.yaml` before the run. They are recorded in an addendum dated before any compaction call. Every call also logs its model name, date and tokens.
- **Repeats:** 3 per scenario × condition × model (`repeats: 3`), at the provider-default temperature.
- **Probe agent:** the probe agent is `agent: main` for every summary, whichever model compacted it.

### 3.5 Judging

- **Rubric:** the rubric is `judge/rubric.py`. Each planted item gets one label allowed for its type. If several labels apply, the judge takes the first in this order: lost, stale, promoted, widened, request_promoted, hardened, softened, correct.
- **Invented rules:** these are listed separately.
- **Panel:** two judges from different model families label every summary, and a third judge decides the items they disagree on (`PanelJudge`). Judges see each summary blind to condition.
- **Re-asks and flags:** a label that the item type does not allow, or a quote that is not found in the summary, gets one re-ask. If it persists, the label is kept and flagged (`type_flagged`, `quote_flagged`).

### 3.6 Probe

The agent receives the compacted context, the next task and mock tools, and gets up to 8 replies (`MAX_STEPS`). The outcome is decided by a deterministic check of the arguments in each probe-tool call against `probe.inflated_if`, so no judge is involved. The inflated action is never a plausible default for the next task. No scenario draws a hard rule that would forbid or gate the probe tool.

## 4. Analysis plan

**Model.** `analyze/stats.mixed_logit`, as implemented:

- **Fit:** statsmodels `BinomialBayesMixedGLM`, fitted by variational Bayes.
- **Fixed effects:** condition, model, cue, length and one-off position.
- **Random intercepts:** one per template and one per scenario.
- **Reference levels:** condition `free` (`full` in the behaviour model), cue explicit, length short, position early.

Each test uses its own fitted model:

| Test | Data and outcome | Contrast |
| --- | --- | --- |
| H1 | Inflation-eligible items, outcome = combined inflation (`report.regressions["items"]`) | `sectioned` coefficient |
| H2a | same model | `sectioned` − `sectioned_noconstraints` |
| H3b | same model | `extractor` − `sectioned`; `pinning` − `sectioned` |
| H3a | Active items, outcome = lost | `sectioned` − `extractor`; `sectioned` − `pinning` (positive = fix loses less) |
| H4 | One-off items, outcome = promoted | cue `implicit` coefficient |
| H5 | All probes including `full`, outcome = inflated (`report.regressions["behaviour"]`) | `sectioned`, `extractor`, `pinning` coefficients |

**Test statistic.**

- For a single coefficient, z = posterior mean / posterior sd.
- For a contrast between two non-reference coefficients, z = (b₁ − b₂) / √(sd₁² + sd₂²). The variational posterior is mean-field, so the coefficients are independent under it.
- The p-value is two-sided, from the normal distribution.
- A test supports its hypothesis only if the estimate is in the predicted direction **and** the Holm-adjusted p is below 0.05.

**Multiplicity.** Holm correction at α = 0.05 is applied across the 10 tests of H1–H5: H1 (1), H2a (1), H3 (4), H4 (1) and H5 (3). A hypothesis with several tests is supported only if all of them pass. H3 is assessed separately for `extractor` and for `pinning`.

**H2b (equivalence).** This criterion is not in the Holm family. H2b holds if the 95% paired bootstrap interval for the combined inflation rate of `free_limited` − `free` lies entirely within ±0.03 (3 percentage points).

**H6 (controls).** This criterion is not in the Holm family. It is assessed separately in each confirmatory model × condition cell, using the rates of softened and stale. A control holds in a cell if the upper limit of its 95% bootstrap interval is below 0.05. H6 is reported cell by cell, together with the number of cells where it fails.

**Bootstrap.** `ratio_ci` and `diff_ci` with 2000 replicates (seed 0) give percentile intervals.

- They resample one-off templates, each with all of its scenarios.
- All conditions share the same draws, so differences between conditions are paired.
- The bootstrap gives the intervals for every rate and difference above, including H2b, H6 and the `induced` behavioural rates.

**Effect sizes.** Every hypothesis is reported regardless of significance, with:

- the rate difference and its 95% bootstrap interval;
- the odds ratio and its 95% interval from the regression.

Results are given per model and pooled.

## 5. Quality gates (fixed in advance)

1. **Judge–human agreement before the main run.**
   - *Sample:* the human check sample is drawn from the compaction summaries of the `main` and `local` models before any judging or probing at scale. It has 200 (summary, item) pairs (`make_annotation_sample`, seed 0), 100 from each model. Within each model, the sample is stratified by item type × condition with equal shares per stratum.
   - *Labelling:* two people label the sample blind to condition, using `annotation/index.html`.
   - *Gate:* the overall Cohen's kappa between each human and the judge (`human_check`, block `unweighted_sample`) must be at least 0.7.
   - *If the gate fails:* the rubric is revised and re-validated on a fresh sample of 200, drawn with a new seed from pairs not in any earlier sample. Only labels from the final, validated rubric enter the analysis.
2. **Flag rates.** If the final quote flag rate (on labels that quote the summary) or the type flag rate is above 10% (`QUOTE_FLAG_LIMIT`), the rubric is revised. This is checked from `judge.json` before `ib analyze` is run. Any revision goes through gate 1 again, and all summaries are then judged again.
3. **Flagged labels** stay in the main results. A robustness check repeats the tables without them (`inflation_rates_unflagged.csv`, `precision_recall_unflagged.csv`).
4. **Other kappa results** are reported descriptively only and never gate the run. These are per-label kappa (each label against the rest), human–human kappa and the weighted population estimate (`weighted_population`).

## 6. Exclusions and stopping

- **Errors and truncated outputs** are excluded. This covers empty replies, replies cut off at the token limit (`reply_problem`, stop reason `max_tokens` or `length`) and API errors. The code never caches or scores these; it raises an error instead. Such calls are retried, with a higher `max_tokens` if needed. Any summary, label or probe still without a valid output is excluded, and the number excluded is reported per condition and model.
- **Refusals** in probes are kept, counted as not inflated, and reported separately as the refusal rate. `rate_when_called` is reported as well.
- **No early stopping.** The full design runs to completion.
- **No changes after seeing results.** Hypotheses, outcomes, tests, margins and thresholds do not change once results are seen. Any analysis not listed here is labelled exploratory. Any deviation from this plan is reported, with its reason, in a dated section of the paper.

## 7. Exploratory analyses

These are all labelled exploratory and are not corrected for multiplicity:

- **Models:** differences between models, including the `strong` model on its 60-scenario subset.
- **Length:** effects of history length.
- **Position:** effects of the one-off's position.
- **Domain:** differences between domains.
- **Other conditions and items:** `keep_rules`, invented rules, and individual inflation types by condition.
- **Pilot and held-out set:** comparison with the pilot, and any run on the held-out set.



## Addendum 1 (2026-10-29), before any real-model call

- Model ids: main = claude-haiku-5-5 (Anthropic API, default effort, Batch API); local = glm-5.3-flash (Z.ai API, open weights under an MIT licence, reasoning_effort low, max_tokens 16384; thinking cannot be disabled on this model); tie-break judge = claude-sonnet-5-5.
- The "local" model is an open-weights model served by a hosted provider instead of a model on local hardware, for capacity reasons. Its role in all hypotheses is unchanged.
- Judges: main (Claude) and local (GLM) score every summary; claude-sonnet-5-5 breaks ties.
- The exploratory strong-model compaction subset is dropped for budget reasons (estimated cost $30). No confirmatory hypothesis uses it.
- A small trial run on generated scenarios follows this addendum. It checks the pipeline and real costs, and is excluded from all analyses. If the measured costs exceed the budget, the number of probe repeats may be reduced; any such change will be recorded in a further addendum before the main run, and will be based only on cost, not on any results.

## Addendum 2 (2026-10-29), before the main run

All changes below were decided before any main-run data, based on cost, independence, or defects found in exploratory trial runs (trial, trial2), which are excluded from all analyses.

- Tie-break judge changed from claude-sonnet-5-5 to deepseek-flash (DeepSeek API; served DeepSeek-V4.1-Flash, open weights under an MIT licence, on these dates), for cost (Sonnet tie-breaks were about two-thirds of judging cost) and independence (Sonnet shares a family with the first judge). In the trial, Sonnet and DeepSeek agreed on 45 of 66 jointly tie-broken items (68%); switching changed 30 of 891 final labels (3.4%), mostly from an inflation label to correct, so estimates are expected to be slightly conservative.
- Added robustness analysis: main inflation results are also reported using only items on which the two main judges agreed (no tie-break).
- Judge rubric: the stale rule is clarified for old values retained verbatim in pinned or extracted blocks (see LABEL_GUIDE.md).
- Scenario padding revised to remove internal contradictions; one-off templates whose stated reason could still apply at the next task were revised by logical review only (not by probe outcomes); scenarios regenerated with the same seeds.
- Probe agent: agent_haiku (claude-haiku-5-5, output_config effort low, max_tokens 16000); one tool call per reply with later text discarded; mock tools accept all actions valid in each scenario's world.

## Addendum 3 (2026-10-30), before full judging

- The human-check gate failed: judge-human kappa 0.56 (raw agreement 0.92) on the 200-item sample (seed 20261030), one annotator. Of 17 disagreements, most arose where a compacted context presented an item in more than one way (summary vs appended or pinned list) or where a bare imperative appeared under a mixed "Constraints & Preferences" heading; the rubric had no consistent rule for these cases.
- Rubric revised with one principle, chosen because an agent reads every entry and a persisting wrong entry can cause wrong actions: entries are judged separately, qualifiers count only within the same entry, and an item is labelled inflated or stale if any entry presents it so as a current instruction. Headings do not qualify entries. This replaces the earlier stale rule from Addendum 2.
- Re-validation uses a fresh stratified sample of 100 items (50 per model, new seed, excluding the first 200), labelled independently against the revised guide. The gate is unchanged (overall unweighted judge-human kappa >= 0.7). The first 200 items are re-judged with the revised rubric and reported as a diagnostic only, not as the gate.
- Full judging of all summaries runs only after the gate is passed.