# Measure and improve the router

```sh
ask eval evals/prompts.jsonl --show-misses       # accuracy per question and per target
ask eval evals/prompts.jsonl --backend laya      # same prompts, Laya instead of semif
ask eval evals/prompts.jsonl --sweep             # right target vs fallback rate per confidence floor
ask rate bad --should opus                       # label the last real decision
ask export --out mine.jsonl --only-rated         # decision log -> labelled prompts to review
```

Every decision is appended to `~/.local/state/trivium/decisions.jsonl` with the full probabilities,
and `ask rate` appends labels. That log is the data for tuning thresholds and wording, and for
training a router later.

`ask export` turns the log into the same format as `evals/prompts.jsonl`. Feedback only names the
target a prompt should have gone to, while `ask eval` and `ask calibrate` need an answer per question,
so every row is pre-filled and labelled with where its answers came from:

- `confirmed-target`: rated good; the router's answers led to the right target.
- `inferred-from-feedback`: rated bad with `--should`, or re-routed with `--ask`; the answers are the
  most likely combination, under the router's own scores, that leads to the target you chose.
- `router`: unrated; the router's answers as they were.

Rows with `needs_review: true` need a human to check the per-question answers before the file is used
for evaluation or calibration. Decisions made with `--to` never ran the router and are skipped.

Trivium ships two labelled sets. `evals/calibration-100.jsonl` is the main one: 100 prompts across
every kind, difficulty and tools answer, including general questions typed inside a repository, long
pasted logs and Dutch prompts. Two labellers answered them independently (agreement 100% on kind, 90%
on difficulty, 97% on tools) and the 12 disagreements were settled in the file. It is split 72 / 28 so
that calibration is fitted on one part and checked on the other
([write-up](../../evals/results/2026-09-25-calibration-100.md)). With the shipped config, semif routes to the
right target on 77.8% of the training prompts, **71.4% of the held-out prompts** and 80.6% of the older
set below; kind, difficulty and tools score 89.3%, 82.1% and 78.6% on the held-out prompts.

```sh
ask eval evals/calibration-100.jsonl --split test     # the held-out 28
ask calibrate evals/calibration-100.jsonl --split train
```

`evals/difficulty-120.jsonl` is a third set of 119 prompts written around the difficulty boundaries,
used to test fixes for the router's main weakness: it calls short moderate requests trivial. Rewording
the question made things worse; weighting the options helped (see [Option weights](calibrate.md#option-weights)).

`evals/prompts.jsonl` holds 36 prompts I wrote and labelled by hand earlier. Same prompts, same questions,
same rules, confidence thresholds off, on an Apple M5 Pro (full write-up in
[`evals/results/2026-09-23.md`](../../evals/results/2026-09-23.md)):

| Router | Kind | Difficulty | Tools | Right target | Latency p50 |
|---|---|---|---|---|---|
| semif + Qwen3.5-4B, MLX bf16 (default) | **94.4%** | **80.6%** | 80.6% | **80.6%** | 241 ms |
| Laya 0.3.7, English checkpoint | 69.4% | 47.2% | 97.2% | 38.9% | **98 ms** |
| Laya 0.3.7, typed-decisions checkpoint | 80.6% | 47.2% | **100%** | 47.2% | 99 ms |
| Hybrid: Laya English for tools, semif for the rest | **94.4%** | **80.6%** | 97.2% | **83.3%** | 263 ms |
| Hybrid: Laya typed-decisions for tools | **94.4%** | **80.6%** | **100%** | **83.3%** | 247 ms |

"Right target" means the router's answers lead to the same target as the hand labels would. The
question wording was tuned on this set with semif, which favours semif. The two hybrid rows are
history: on the larger set the hybrid did worse than semif and it was removed on 2026-11-24 (see
[Backends](../reference/runtimes-and-backends.md#backends)).
