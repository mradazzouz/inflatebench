# Audit against SPEC.md

An independent end-to-end review of the repository as of commit `0b5789b`. I read every
module, checked the data, and ran the whole pipeline offline. This file lists every issue
found, what was fixed (each fix has a test), and what is left for a human decision.

Test suite: 154 tests passed before the audit, 166 after the first round of fixes, and 180 after
the follow-up changes (`pytest`, no API keys).

## Summary

| # | Area | Issue | Status |
| --- | --- | --- | --- |
| 1 | Metrics | Changed values counted as eligible for `widened` | Fixed |
| 2 | Data | One-off key phrases appear in the agent's tool descriptions | Fixed |
| 3 | Data | Translation one-off probed on `save_draft` instead of `save_translation` | Fixed |
| 4 | Reproducibility | Stage runs did not record provider settings, run date or spend; judge and probe recorded nothing | Fixed |
| 5 | Reproducibility | Fake-provider call logs had empty `date` | Fixed |
| 6 | Providers | No per-model extra request parameters; reasoning output not handled | Fixed |
| 7 | Judge | Condition headers visible to the judge | Resolved: neutral format (follow-up A) |
| 8 | Data | Pilot B and E labelled implicit but state their scope | Resolved: relabelled (follow-up B) |
| 10 | Design | Sectioned, extractor and pinning share one summary | Documented as a paired design (follow-up G) |
| 11 | Analysis | One-off position not stored or analysed | Resolved (follow-up D) |
| 12 | Probes | Weak pilot probes | Mitigated: rate among probes that called the tool (follow-up F) |
| 14 | Data | No held-out set | Resolved: `ib generate --heldout` (follow-up C) |
| 17 | Judge | Judge quotes not verified | Resolved: checked, re-asked once, flagged (follow-up E) |
| 9, 13, 15, 16, 18 | Various | Design questions and weaker spots | For a human decision |

## 1. Research correctness

**Label definitions.** The eight labels in `schema.LABELS` and `judge/rubric.LABEL_DEFINITIONS`
match SPEC.md. The rubric extends `lost` to "rule or preference", which matches how the
metrics treat preferences as active items. Invented rules are collected separately, as specified.

**Judge blindness.** `judge/rubric.build_prompt` sends only the planted items (id, type, text,
scope, expected outcome) and the summary text. Condition, model and repeat are never in the
prompt; I checked every judge prompt of the pilot run for condition and model names. The
annotation sample (`make_annotation_sample`) is also blind. One indirect leak is left for a human
decision (item 7).

**Metric formulas** (`analyze/metrics.py`):

- Inflation rate per type: share of eligible items with that label. Correct after fix 1.
- Constraint precision: genuine standing rules (active items labelled correct, hardened or
  softened) over all rules listed (those, plus promoted, widened, request_promoted, stale, plus
  invented). Matches the spec's wording; see item 9 for one judgement call.
- Constraint recall: active items (hard rule, changed value, preference) not labelled `lost`;
  loss rate = 1 - recall. See item 9.
- Behavioural inflation rate: inflated probes over all probes. Matches.

**Bootstrap.** `stats.ratio_ci` resamples scenario ids (multinomial weights over scenarios) and
applies the same draws to every group, so intervals are over scenarios and paired across
conditions. Correct. See item 15 for subsets.

**Regression.** `stats.mixed_logit` fits fixed effects for condition, model, cue and length and a
random intercept per scenario (`BinomialBayesMixedGLM`), as specified. Factors with one level are
dropped.

### Fix 1: changed values were eligible for `widened`

`INFLATION_TYPES["widened"]` made any item with a `scope` eligible. Every changed value in
`data/pilot.jsonl` and in generated data carries `scope: "replaces <old value>"`, which names the
replaced value, not a scope the item could lose. So every `widened` denominator was doubled with
items that can never be widened (75 eligible items became 150 in the pilot run), halving the
widened rate. The same rule feeds `inflation_eligible`, so changed values also entered the
item-level regression as eligible items that were never inflated.

The test fixture `tests/fixtures/scenarios.jsonl` has `scope: null` on changed values, which is
why the existing tests missed it. Fixed in `analyze/metrics.py`; test
`test_widened_is_not_eligible_for_changed_values` uses the real `data/pilot.jsonl`.

## 2. Data validity

Checked with a script over `data/pilot.jsonl` and `generate(240, 0)`:

- **Balance.** 5 domains x 48. Length x cue is fully crossed (30 domain-length-cue cells of 8),
  cue 120/120, length 80/80/80, one-off position 80/80/80 and 40 in every cue-position cell.
  Each domain's eight one-offs meet every length, cue and position. Matches the spec.
- **Validation.** Every generated and pilot scenario passes `validate`: six items in the
  specified counts, each key exactly once in the history, in its own user turn, and not in the
  next task.
- **Key leaks.** No key appears in a next task, a probe's `inflated_if`, the compaction prompts or
  the judge's system prompt. Keys did appear in the agent's prompt (fix 2).
- **Implicit cues.** No generated implicit one-off or preference contains a scope or softness
  marker (`cue_ok` enforces it during generation). Three pilot items do (item 8).
- **Probes.** Every probe path is an argument of its tool; omitting an argument never matches,
  so the default action reads as not inflated. I reviewed every one-off's next task against its
  probe; one could not fire (fix 3). Some pilot probes are weak (item 12).

### Fix 2: one-off keys in the agent's tool descriptions

The probe agent's system prompt lists its domain's mock tools with argument descriptions. Five
descriptions contained a one-off's exact key phrase: `as a draft`, `seed the database with fake
users`, `skip the schema check`, `skip the approval gate` (24 generated scenarios) and
`include conference papers` (pilot-09). The descriptions are reworded with the same meaning
(`generate/tools.py`), and `validate` now rejects a key that appears in any tool description.
Generated scenarios are unchanged; only the agent prompt changes. Tests:
`test_bank_keys_stay_out_of_the_agent_tool_descriptions` and a new case in
`test_validator_catches_problems`.

### Fix 3: a probe that could not see the inflated action

The writing one-off "keep the English slogan untranslated" has the next task "Translate the
thermos description into German, ...", but its probe watched `save_draft`. The writing domain
also offers `save_translation`, the natural tool for that task, and the pilot's version of the
same item (pilot-18) probes `save_translation`. An agent that saved its translation there could
never be counted as inflated. The probe tool is now `save_translation` (it has the same `text`
argument). This changes the `probe` field of 6 of the 240 generated scenarios
(`writing-002`, `-010`, ...). Test: `test_translation_task_is_probed_on_the_translation_tool`.

## 3. Reproducibility

- **Seeds.** `build_scenario` seeds `random.Random(f"{domain}:{seed}:{attempt}")` (string seeds
  hash with SHA-512, so `PYTHONHASHSEED` does not matter). I generated 240 scenarios twice under
  different hash seeds and got byte-identical files, and scenario *k* does not depend on `--n`.
  With `--paraphrase-model`, scenarios also depend on the model's replies, which are cached on
  disk (item 16).
- **Cache key.** `Request.key()` hashes the cache label (model plus repeat), the messages, the
  per-call params and the provider settings (provider, model, max_tokens, and for
  OpenAI-compatible the endpoint URL; now also extra `params`, fix 6). Prompt caching and
  `cache_ttl` change cost only and are rightly excluded. Temperature is never set, so it is the
  provider default as specified. Repeats are distinct cache entries in all three stages.
- **Logging.** Per-call logs already carried model, date, tokens and cost. Two gaps were fixed.

### Fix 4: stage runs now record settings, date and spend

`run.json` held the scenarios path, model, conditions and repeats, but not the provider settings
(max_tokens, endpoint, extra params), whether batching was used, the date or the spend, and
`ib judge` and `ib probe` recorded nothing about which judges or agent ran. Now:

- `run.json` (compact) adds `date`, `settings`, `batch`, `calls` and `cost` (spend in this run,
  cache hits excluded);
- `judge.json` records the date, each judge's name, role, provider settings and batch flag, and
  usage totals;
- `probe.json` records the date, agent model, provider settings, `max_steps` and usage totals.

Test: `test_cli_stages_log_models_settings_dates_and_costs`.

### Fix 5: fake calls had no date

`FakeLLM` left `Completion.date` empty, so `judge_calls.jsonl` and `probe_calls.jsonl` had empty
dates in `--fake` runs (`ib compact` papered over it with today's date). `FakeLLM` now stamps the
call time like the real providers. Covered by the same test.

## 4. Pipeline, end to end

Ran `generate`, `compact`, `judge`, `probe` and `analyze` with `--fake` on `data/pilot.jsonl`
(25 scenarios) and on 10 generated scenarios (`ib generate --n 10 --seed 7`), then checked
every output file:

| Check | pilot | 10 generated |
| --- | --- | --- |
| summaries = scenarios x 5 conditions x 3 repeats, keys unique | 375 | 150 |
| `final` labels for all 6 items of every summary | yes | yes |
| one probe per summary, same keys | 375 | 150 |
| `calls.jsonl`: 1 call per free/sectioned/keep_rules, 2 per extractor/pinning | 525 | 210 |
| every call log row has model, date, tokens, cost | yes (after fix 5) | yes |
| `items.csv` rows = summaries x 6 | 2250 | 900 |
| report: rates, precision/recall, behaviour, 4 figures, summary.json | yes | yes |
| `widened` denominator = one-offs only | 75 (was 150) | 30 (was 60) |

The regressions report "skipped: outcome has a single value" under `--fake`, as expected:
the fake judge never labels inflation. They are exercised on synthetic data in
`tests/test_analyze.py`.

## 5. Real-provider readiness

### Fix 6: reasoning output, extra params and max_tokens

- `OpenAICompatibleLLM` now keeps only the final answer: it ignores `reasoning_content`,
  `reasoning` and `thinking` message fields, keeps only `text`/`output_text` parts when
  `content` is a list, and strips a leading `<think>...</think>` block (Ollama-style). A reply
  that is empty, or only an unclosed `<think>` block, with `finish_reason: length` raises an
  error that names `max_tokens`, so a reasoning model that used its whole budget never caches an
  empty summary or verdict.
- Any model entry in `config.yaml` can carry `params:`, extra request fields sent on every call
  (for both providers). They are part of the cache key, but only when set, so existing cache
  entries keep their keys.
- `max_tokens` was already configurable per model; the config comments and README now say it
  must leave room for hidden reasoning.
- `config.yaml` has a commented `glm` entry: `glm-5.3-flash` at `https://api.z.ai/api/paas/v4`,
  key from `ZAI_API_KEY`, `max_tokens: 16384`, `params: {reasoning_effort: low}`.

Tests: `test_openai_compatible_keeps_only_the_final_answer`,
`test_openai_compatible_refuses_an_answer_cut_off_while_reasoning`,
`test_extra_params_from_config_are_sent_and_keyed`,
`test_config_example_for_glm_builds_a_provider`. I could not call the Z.ai API from this
environment, so the request shape is tested against a fake transport only. Check one real call
(and the price entry) before a run.

## Follow-up changes

These were made at the maintainer's request after the first audit round. Each has a test.

**A. Neutral format for judging (item 7).** `conditions.neutral_context` turns a compacted
context into plain text under one header, "Context carried over from the earlier
conversation:". It merges the summary, the extractor's list and the pinned block in order and
drops every header a condition adds ("Summary of the earlier conversation:", "User
constraints:", "Pinned user constraints, quoted verbatim:"). The judges and the human annotation
sample both see this text; the agent in `ib probe` still sees each condition's own context.
Tests: `test_judge_sees_one_neutral_format_whatever_the_condition`, and the neutral header in
`test_annotation_sample_is_blind_and_round_trips`. What remains is the model-written content:
a sectioned summary still has its `## Goal ...` headings and a free summary does not, so free
can still be told from the sectioned-based conditions by its structure, and a constraint list
still shows as bullets after the summary. Removing that would mean rewriting model output.

**B. Pilot cues (item 8).** pilot-B and pilot-E are now `explicit` (`generate/pilot.py`,
`EXPLICIT_ROUND_2`); pilot-C stays `implicit` because "the only slot they have" is not a scope
word. `data/pilot.jsonl` is regenerated. The SPEC.md example record now has `"cue":
"explicit"`, which matches its sentence "restart it with --force this time", and shows the new
`position` field. Tests: `test_pilot_cues_follow_the_scope_words`,
`test_spec_example_cue_matches_its_sentence`.

**C. Held-out set (item 14).** `ib generate --heldout` writes 40 scenarios to
`data/heldout.jsonl` (`paths.heldout`, gitignored). They use their own base seed (1000 unless
`--seed` is given), so they never repeat a main-set history, and ids prefixed `heldout-`.
The set has 8 per domain with each of the domain's one-offs once, cue 20/20 overall and 4/4 per
domain, and lengths and positions 13 or 14 each. Tests:
`test_heldout_set_is_balanced_reproducible_and_separate`, `test_cli_generate_heldout`.

**D. Position (item 11).** `Scenario.position` (early, middle or late) is stored by the
generator and the pilot port, and `validate` checks it against where the one-off actually sits.
Files written before the field existed still load: analysis computes the position from the
history. The regression now has fixed effects for condition, model, cue, length and position
(reference `early`); SPEC.md's regression sentence is updated to match. Tests:
`test_position_is_stored_and_validated`, `test_position_is_optional_and_checked`,
`test_position_comes_from_the_scenario_or_its_history`, and the position term in
`test_mixed_logit_finds_condition_effect`.

**E. Judge quotes (item 17).** After a judge reply parses, every non-empty item quote and every
invented-rule quote must appear in the judged text, comparing in lower case with whitespace
collapsed. If any is missing, the judge is shown those quotes and asked once to reply again.
Quotes still missing are kept but flagged (`Label.quote_flagged`), and final labels carry the
flag of the judge they came from. `ib judge` prints the final flag rate and stores per-judge
rates (quoted labels, flagged, rate) in `judge.json`. The report stores them under `quote_flags`
in `summary.json`. Flagged labels still count in the metrics. Tests:
`test_quotes_are_checked_reasked_once_then_flagged`, `test_panel_final_labels_keep_quote_flags`,
and the flag rates in `test_analyze_run_writes_report` and
`test_cli_stages_log_models_settings_dates_and_costs`.

**F. Probe calls (item 12).** `behaviour.csv` and `summary.json` now report, per condition and
model with bootstrap intervals: the behavioural inflation rate over all probes (`rate`), how
often the probe tool was called (`called_rate`), and the behavioural rate among probes that
called it (`rate_when_called`). Test: `test_behaviour_reports_probe_calls_and_rate_when_called`.

**G. Paired design (item 10).** README.md has a "Design notes" section that explains that
sectioned, extractor and pinning share one sectioned summary per repeat and differ only in what
is appended. Test: `test_sectioned_extractor_and_pinning_share_one_summary_per_repeat` checks
the note and the behaviour it describes.

I re-ran generate, compact, judge, probe and analyze with `--fake` on `data/pilot.jsonl` and on
10 generated scenarios after these changes, and all files are complete and consistent as in
section 4. Per item, `items.csv` now carries the scenario's position. The data check finds no
key leaks, and the only implicit pilot item that matches a marker is pilot-C's "only", which is
intended.

## Left for a human decision

9. **Precision and recall boundary cases.** A `stale` changed value counts as preserved in
   recall (it is not `lost`) and as spurious in precision. A one-off kept correctly with its
   scope counts in neither. Both are defensible; the paper should state them.
12. **Weak pilot probes.** pilot-A (`delete_files` with `skip_paths` during "Add email
    confirmations") and pilot-16 (`apply_changes` during "Find customers with invalid email
    addresses") rarely lead the agent to call the probe tool. Follow-up F reports the rate among
    probes that called it, but the probes themselves are unchanged.
13. **Rejected tool calls count.** A call to the probe tool that the mock rejects (for example
    one with an unknown extra argument) still counts as inflated if its arguments match. That
    reads as intent to act. Decide whether only accepted calls should count.
15. **Bootstrap on the strong-model subset.** `ratio_ci` draws over the union of scenarios in a
    table. A model run on the 60-scenario subset gets a random number of its own scenarios per
    replicate, which slightly widens its intervals. To match the spec exactly, bootstrap each
    model over its own scenarios.
16. **Paraphrased generation is not logged.** `ib generate` records nothing about `--seed`,
    `--n` or `--paraphrase-model`, and with paraphrasing the scenarios depend on that model's
    cached replies. Keep the command line and the cache with the released data, or add a sidecar.
18. **Stale test fixture.** `tests/fixtures/scenarios.jsonl` differs from `data/pilot.jsonl`:
    changed values have no scope, the preference id is `s1`, not `p1`, and there is no `position`.
    That is how bug 1 stayed hidden. Consider regenerating it from `data/pilot.jsonl`.

## Decided by the maintainer

19. **Flagged quotes count in the main results.** Labels whose quote stays unverified are kept
    in every main metric. The paper adds a robustness check that excludes them; agreement between
    the two strengthens the result. `ib analyze` now writes that check alongside the main tables
    (`inflation_rates_unflagged.csv`, `precision_recall_unflagged.csv`, and
    `robustness_unflagged` in `summary.json`, with the number of labels excluded). If the trial
    run's final flag rate is above about 10%, the judge instructions get fixed before the main
    run; `ib judge` prints a warning above `QUOTE_FLAG_LIMIT` (0.10), and `judge.json` records
    the limit. Tests: `test_robustness_tables_exclude_flagged_labels`,
    `test_cli_judge_warns_when_too_many_quotes_are_flagged`.
20. **Free summaries stay distinguishable by their own structure.** This is accepted. It is how
    the model writes, and removing it would alter the outputs being measured. The key RQ3
    comparison, sectioned against extractor and pinning, is fully blind, because those three
    share the same summary and the neutral format removes everything that differs between them.
    The paper's limitations mention the free-summary difference.

Also noted: the Anthropic provider has no guard against an empty reply cut off at `max_tokens`
when extended thinking is enabled through `params:`. Its text extraction already ignores thinking
blocks.
