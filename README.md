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
   `pinning`) `repeats` times per scenario. Options: `--model KEY`, `--condition NAME`
   (repeatable), `--limit N`, `--repeats N`, `--dry-run` for a cost estimate.
3. **judge** labels every planted item in every summary with the two judges and the
   tie-break judge set under `judges:` and `tiebreak:` in `config.yaml`; the resolved labels
   are stored under judge `final`.
4. **probe** gives the agent model (`agent:` in `config.yaml`, or `--model KEY`) the compacted
   context, the scenario's next task and mock tools for its domain, then checks the
   tool-call arguments against the scenario's `probe.inflated_if`. The check is
   deterministic; no judge is involved. Options: `--max-steps N` agent replies per probe.
5. **analyze** writes inflation rates by type, constraint precision and recall,
   behavioural inflation rates (all with 95% bootstrap intervals over scenarios),
   mixed-effects regressions, `summary.json` and figures. Options: `--judge NAME`,
   `--n-boot N`, `--no-figures`.

Each stage logs its model calls (`calls.jsonl`, `judge_calls.jsonl`, `probe_calls.jsonl`)
with model, date, token counts and cost, and records the models, provider settings, date and
spend of the stage run in `run.json`, `judge.json` and `probe.json`. Human labels for the judge check are collected
with `annotation/index.html`.

### The behaviour probe

The agent sees the tools for its scenario's domain (from `inflatebench/generate/tools.py`)
and calls them by writing JSON objects such as
`{"tool": "restart_worker", "args": {"name": "w1", "force": true}}`, so the same protocol
works with every provider. Mock tools reject unknown tools and arguments with an error the
agent can read. A probe counts as inflated when any call to the probe tool matches every
path in `inflated_if`; `probes.jsonl` also records every tool call and whether the probe
tool was called at all.

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
rather than resubmitted. `--no-batch` makes single calls instead. Providers without a batch
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
nothing; batches submitted by a crashed run are collected on the next run instead of being
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
ib generate --paraphrase-model KEY    # paraphrase items with a model from config.yaml
```

Without `--paraphrase-model`, items use the curated phrase-bank text verbatim.
The same `--seed` always gives the same scenarios.

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
