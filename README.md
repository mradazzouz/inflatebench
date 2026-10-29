# inflatebench

Benchmark for constraint inflation in context compaction. See SPEC.md.

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
