# inflatebench

Benchmark for constraint inflation in context compaction; see SPEC.md.

## Generating scenarios

```sh
pip install -e '.[dev]'
ib generate --n 240 --seed 0          # writes data/scenarios.jsonl
ib generate --pilot                   # ports pilot.md to data/pilot.jsonl
ib generate --paraphrase-model KEY    # paraphrase items with a model from config.yaml
```

Without `--paraphrase-model`, items use the curated phrase-bank text verbatim.
The same `--seed` always gives the same scenarios.
