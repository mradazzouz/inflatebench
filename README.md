# inflatebench

Benchmark for constraint inflation in context compaction: does a compaction summary turn
one-off instructions, soft preferences and task requests into standing or stricter rules,
and does that change what an agent does next? See [SPEC.md](SPEC.md) for the design.

## Installation

Python 3.11 or later.

```sh
git clone https://github.com/mradazzouz/inflatebench
cd inflatebench
pip install -e '.[dev]'         # package, ib command, pytest and the Anthropic SDK
pytest                          # no API keys needed; tests use a fake model
```

`pip install -e .` alone installs the pipeline without the Anthropic SDK (enough for Ollama
and `--fake` runs); add `.[anthropic]` for the hosted provider.

## Quick start

Every stage reads and writes JSONL, so any stage can be rerun on its own. With `--fake`
the whole pipeline runs offline on the 25 pilot scenarios in a few seconds:

```sh
ib generate --n 240 --seed 0                     # 1. data/scenarios.jsonl
ib compact --run-id pilot --scenarios data/pilot.jsonl --fake   # 2. runs/pilot/summaries.jsonl
ib judge   --run-id pilot --fake                 # 3. runs/pilot/labels.jsonl
ib probe   --run-id pilot --fake                 # 4. runs/pilot/probes.jsonl
ib analyze --run-id pilot                        # 5. runs/pilot/report/
```

`ib compact` records the scenarios file in `runs/<run_id>/run.json`, so the later stages
use the same file without `--scenarios`. For a real run, fill in the model names in
`config.yaml` and drop `--fake`:

1. **generate** builds scenarios from the phrase banks (details below).
2. **compact** runs each compaction condition (`free`, `sectioned`, `keep_rules`, `extractor`,
   `pinning`, and the ablations `free_limited` and `sectioned_noconstraints`, see Design notes)
   `repeats` times per scenario. Options: `--model KEY`, `--condition NAME` (repeatable),
   `--limit N`, `--repeats N`, `--dry-run` for a cost estimate.
3. **judge** labels every planted item in every summary with the two judges and the
   tie-break judge set under `judges:` and `tiebreak:` in `config.yaml`; the resolved labels
   are stored under judge `final`. Judges (and human annotators) see each compacted context in
   one neutral format: the summary, any appended constraint list and any pinned block merged
   as plain text under a single header. The summary header is removed and the extractor's and
   pinning's list headers both become `User constraints:`, so an appended list still reads as
   constraints (not as more items of the summary's last section) without saying which fix made it.
   Each item type allows only some labels (`ALLOWED_LABELS` in `judge/rubric.py`: a one-off can
   be correct, promoted or widened; a preference correct, hardened or lost; a request correct or
   request_promoted; a hard rule correct, softened or lost; a changed value correct, stale or
   lost), and the rubric gives an order of precedence when several apply. Each quote must
   appear in that text (ignoring case and whitespace). A judge whose quotes do not, or who gives
   a label the item's type does not allow, is asked once to fix both; quotes still missing are
   flagged (`quote_flagged`) and labels still not allowed are kept but flagged (`type_flagged`).
   The flag rates per judge are printed and stored in `judge.json` and the report; above 10% of
   quotes `ib judge` warns that the judge instructions need work before the main run.
4. **probe** gives the agent model (`agent:` in `config.yaml`, or `--model KEY`) the compacted
   context, the scenario's next task and mock tools for its domain, then checks the
   tool-call arguments against the scenario's `probe.inflated_if`. The check is
   deterministic; no judge is involved. It also runs the **full-history baseline** (condition
   `full`): the same agent, task and tools with the uncompacted history instead of a summary,
   once per scenario, model and repeat. A probe in which the agent refuses the task instead of
   calling the probe tool records how in `refusal`: `provider` when the provider stopped a reply
   as a refusal (Anthropic `refusal`, OpenAI-compatible `content_filter`; cached like any
   answer, while compaction and judge calls still reject an empty reply), `text` when the last
   reply declines in words (a narrow phrase match in `probe/check.py`). Options: `--max-steps N` agent replies per probe,
   `--no-full` to skip the baseline (long histories make it the most expensive part).
5. **analyze** writes inflation rates by type, constraint precision and recall,
   behavioural inflation rates (all with 95% bootstrap intervals that resample one-off
   templates, so the three scenarios built from a template are drawn together),
   mixed-effects regressions (fixed effects for condition, model, cue, length and one-off
   position; random intercepts per template and per scenario), `summary.json` and figures.
   `behaviour.csv` gives the behavioural rate over all probes (`rate`), how often the agent called
   the probe tool at all (`called_rate`), how often it refused the task instead
   (`refusal_rate`; refusals count as not inflated in `rate`), the behavioural rate among probes that called it
   (`rate_when_called`), and the **compaction-induced** rate: each condition's rate minus the
   full-history rate for the same model (`induced`, and `induced_when_called`), with a paired
   bootstrap interval. The behaviour regression uses `full` as its reference condition.
   Flagged labels (quote or type) count in every main table; a robustness check without
   them is written next to them (`inflation_rates_unflagged.csv`,
   `precision_recall_unflagged.csv`, `robustness_unflagged` in `summary.json`). Options: `--judge NAME`,
   `--n-boot N`, `--no-figures`.

Each stage logs its model calls (`calls.jsonl`, `judge_calls.jsonl`, `probe_calls.jsonl`)
with model, date, token counts and cost, and records the models, provider settings, date and
spend of the stage run in `run.json`, `judge.json` and `probe.json`. Human labels for the judge check are collected
with `annotation/index.html`. The items for it (`make_annotation_sample` in `judge/run.py`) are
drawn at random within strata of item type and condition, with an equal share per stratum (with
summaries from several models, the sample is first split equally over the models), so
each item type, and with it each inflation label, gets the same number of items; the sample key
gives each item's stratum and its weight for reweighting to the whole pool. `human_check`
reports, for each pair of annotators and each annotator against the judge, the agreement,
overall kappa and per-label kappa (each label against the rest) in two labelled blocks:
`unweighted_sample` (every sampled item counts once; the 0.7 gate uses its overall kappa) and
`weighted_population` (items weighted by the key's weights, `sample_weights(key_path)`: an
estimate of agreement over all summaries and items).

### The behaviour probe

The agent sees the tools for its scenario's domain (from `inflatebench/generate/tools.py`)
and calls them by writing JSON objects such as
`{"tool": "restart_worker", "args": {"name": "w1", "force": true}}`, so the same protocol
works with every provider. Mock tools reject unknown tools and arguments with an error the
agent can read. A probe counts as inflated when any call to the probe tool matches every
path in `inflated_if`; `probes.jsonl` also records every tool call and whether the probe
tool was called at all.

Each probe's inflated action is a flag or value the agent sets only by carrying the one-off
beyond its occasion (a `--no-verify` commit, a `skip_approval` deploy, the one-off's IP address
in a new firewall rule), never a plausible default for the next task. What the agent still does
anyway shows up in the full-history baseline, and `induced` subtracts it. Hard rules that
would forbid or gate the probe tool (for example "Never deploy on Fridays" with a deploy probe)
are never drawn for that scenario.

## Models

Providers live in `inflatebench/models` and are configured in `config.yaml` (model names and
prices never appear in code):

- `anthropic`: Messages API for single calls and the Message Batches API for runs
  (`pip install -e '.[anthropic]'`, key from `ANTHROPIC_API_KEY`). Prompt-cache breakpoints sit
  on the system prompt and the last two turns, so repeats and conditions sharing a history
  read it from cache.
- `openai_compatible`: any `/v1/chat/completions` endpoint, Ollama by default
  (`base_url: http://localhost:11434/v1`, no key). Set `api_key_env` for hosted endpoints.
- `fake`: canned replies for tests.

### Batch runs

With `batch: true` on an `anthropic` model, `ib compact` and `ib judge` send their calls
through the Message Batches API in two phases. `ib compact` first sends every
condition's first call (the summaries, and pinning's extraction) as one batch, waits for it, then
sends the calls that come after them (the extractor's constraint list, pinning's summary) as a
second batch. `ib judge` first sends both judges' calls, then only the tie-break calls for the
summaries the judges disagree on. A crashed run picks up where it stopped: answered calls come
from the disk cache, and submitted batches are recorded under `paths.cache` and collected
rather than resubmitted.

One window is not covered: a batch is recorded only after the provider has accepted it, so a
crash between the two (after `submit_batch` returns, before the record is written; one HTTP
round trip) leaves a batch the next run does not know about, and that run submits and pays
for the same requests again. To recover the first batch's results instead, find it in the
provider's console (Anthropic lists recent batches) before rerunning. `--no-batch` makes single calls instead. Providers without a batch
API (`openai_compatible`) always make single calls.

### Other hosted providers

`config.yaml` has commented-out entries for OpenAI, Google Gemini (through its
OpenAI-compatible endpoint) and an open-weights model on a hosted provider (Together AI shown;
any `/v1/chat/completions` endpoint works). Each uses `provider: openai_compatible` with its own
`base_url` and key variable:

```yaml
models:
  openai:
    provider: openai_compatible
    name: CHANGE_ME                 # an OpenAI model id
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
  gemini:
    provider: openai_compatible
    name: CHANGE_ME                 # a Gemini model id
    base_url: https://generativelanguage.googleapis.com/v1beta/openai
    api_key_env: GEMINI_API_KEY
  open_hosted:
    provider: openai_compatible
    name: CHANGE_ME                 # e.g. org/model-name
    base_url: https://api.together.xyz/v1
    api_key_env: TOGETHER_API_KEY
```

Uncomment the ones you need, fill in the model ids, export the keys
(`export OPENAI_API_KEY=...`) and use them by key, e.g. `ib compact --model gemini` or as a
judge under `judges:`. Add their prices under `prices:` for cost logging.

Any model entry can carry `params:`, extra request fields sent on every call (part of the cache
key), and `max_tokens`. Reasoning models count hidden reasoning against `max_tokens`, so set it
generously; the OpenAI-compatible provider keeps only the final answer (it ignores
`reasoning_content`, `reasoning` and `thinking` fields, reasoning content parts and a leading
`<think>` block) and raises an error rather than caching an empty reply cut off by the limit.
`config.yaml` has a commented example for Z.ai's `glm-5.3-flash`:

```yaml
  glm:
    provider: openai_compatible
    name: glm-5.3-flash
    base_url: https://api.z.ai/api/paas/v4
    api_key_env: ZAI_API_KEY
    max_tokens: 16384
    params:
      reasoning_effort: low
```

OpenAI's reasoning models take `max_completion_tokens` instead of `max_tokens`; pass it under
`params:` and leave `max_tokens` unset.

Every call is cached on disk under `paths.cache` by a hash of its request, so reruns cost
nothing. A reply that is empty or was cut off by `max_tokens` (stop reason `max_tokens` or
`length`) is never cached or used: the stage stops with an error, so a truncated summary,
verdict or agent turn is never scored. `ib analyze` also stops when the final labels or the
probes do not cover `summaries.jsonl` exactly once (left over from an earlier `ib compact` of
the run id, or from a stage that stopped part way); batches submitted by a crashed run are collected on the next run instead of being
resubmitted. Transient errors (429, 5xx, overload, dropped connections) are retried with
exponential backoff. Each call's model, date, token counts (including prompt-cache reads and
writes) and cost are logged by `UsageLog`.

Estimate a run before paying for it; this makes no API calls:

```sh
ib compact --run-id r1 --dry-run              # main model, all conditions
ib compact --run-id r1 --dry-run --model strong --condition free
```

## Generating scenarios

```sh
pip install -e '.[dev]'
ib generate --n 240 --seed 0          # writes data/scenarios.jsonl
ib generate --pilot                   # ports pilot.md to data/pilot.jsonl
ib generate --heldout                 # the 40 private held-out scenarios, data/heldout.jsonl
ib generate --paraphrase-model KEY    # paraphrase items with a model from config.yaml
```

Without `--paraphrase-model`, items use the curated phrase-bank text verbatim.
The same `--seed` always gives the same scenarios. Each scenario records the one-off's
`position` (early, middle or late in the history) and its `template`.

- **Templates.** Each domain has 16 one-off templates (80 in all): a one-off, the next task
  and the probe. Each is used three times per 240 scenarios, once at each length and position.
  Every domain is one coherent setting (a shop's Flask backend, the shop's data pipelines, a
  booking platform's infrastructure, the office of an online shop, a bakery chain's content),
  so intros and items never mix projects.
- **Cue.** Only the one-off follows the scenario's cue. Hard rules, preferences and changed
  values always use their explicit wording and requests their plain wording, so the
  explicit/implicit factor changes nothing else. An implicit one-off contains no scope or
  temporal word at all (`SCOPE_WORDS`: only, just, now, today, this time, for now, ...);
  `validate` rejects one that does. Its scope comes only from the occasion it names.
- **Reasons that end.** A one-off whose reason is a state that could last (CI is down, the
  on-call lead is on a flight) is followed later by a user turn saying it has ended ("CI is
  back up").
- **Neutral turns.** Each history has 3 to 6 user turns that set no rule and ask for no task
  (questions, thanks, clarifications), each answered by the assistant, so planted items are
  not the only things the user says. `validate` rejects any user turn without a planted item
  that uses a rule or scope marker.

The held-out set uses its own base seed (1000 unless `--seed` is given) and ids prefixed
`heldout-`, so it never repeats a main-set scenario. It holds 8 scenarios per domain from 8
different templates, 20 explicit and 20 implicit cues (4 and 4 per domain), and 13 or 14 of
each length and position. `data/heldout.jsonl` is gitignored; keep it private.

## Design notes

**Paired summaries for the sectioned, extractor and pinning conditions.** Extractor and
pinning both build on the sectioned template: they send the same sectioned prompt over the
same history, under the same cache key, as the sectioned condition. So within a repeat, all
three conditions share one sectioned summary (made once and read from the disk cache), and
differ only in what is added to it: extractor appends its extracted constraint list, and
pinning appends its pinned block of verbatim quotes. The comparison is paired by design.
Differences between these three conditions come from the added constraints, not from
sampling noise between summaries, which is exactly the trade-off RQ3 asks about (do the fixes
trade lost rules for inflated ones). The flip side is that they are not independent samples.
Across repeats the summaries do differ, and the bootstrap resamples scenarios, so intervals
already account for the shared scenarios. Free and keep-rules make their own summary calls.
`ib compact --dry-run` counts the shared summary once per condition, so its estimate is an
upper bound.

**Ablations of the sectioned template.** `sectioned` differs from `free` in three ways at
once: five headings, a "Constraints & Preferences" section and a 250-word limit. Two ablations
separate them: `free_limited` is the free prompt with the same 250-word limit, and
`sectioned_noconstraints` is the sectioned prompt without the Constraints & Preferences
section (four headings, same limit). Free against free_limited isolates the limit; sectioned
against sectioned_noconstraints isolates the section.

## Licence

Code is released under the [MIT licence](LICENSE). The data in `data/` is released under
[CC BY 4.0](data/LICENSE.md).

## Citation

If you use inflatebench or its data, please cite it (also in [CITATION.cff](CITATION.cff)):

```bibtex
@software{mrad2026inflatebench,
  author  = {Mrad, Mohamed Azouz},
  title   = {inflatebench: a benchmark for constraint inflation in context compaction},
  year    = {2026},
  version = {0.0.1},
  url     = {https://github.com/mradazzouz/inflatebench},
  license = {MIT}
}
```
