# Calibrate the router

Router scores are not probabilities until you calibrate them. `ask calibrate` fits one temperature
per question on labelled prompts and prints a block for your config:

```sh
ask calibrate evals/prompts.jsonl --backend hybrid           # prints a block to paste
ask calibrate evals/prompts.jsonl --backend hybrid --write   # or saves it to ~/.config/trivium/calibration.yaml
```

```yaml
calibration:
  hybrid:
    kind: 0.6
    difficulty: 1.35
    tools: 0.25   # flagged: at the grid edge, needs more labelled data
```

`--write` keeps fitted values in their own file, so your hand-edited `targets.yaml` and its comments
stay untouched; the file overrides the config's `calibration` block backend by backend.

Then pick the thresholds with `ask eval --sweep`, which applies one confidence floor to every question
and shows the right-target rate, the fallback rate and the accuracy of the prompts that were not sent
to the fallback.

The shipped config holds semif temperatures fitted on the 72 training prompts of the 100-prompt set
(kind 0.95, difficulty 1.21, tools 2.16). On the held-out 28 they lower the calibration error of the
tools answers from 0.129 to 0.068 and of difficulty from 0.149 to 0.131. It ships **no** confidence
floors: on that set every floor from 0.3 to 0.8 routed fewer prompts right, and none reduced the
prompts sent to a model that was too weak, which is what a fallback is meant to prevent.

Two lessons from the bundled set. First, fit on a few hundred labels, not 36: on this set Laya's
tools answers are right 35 times in 36 yet reported at a median confidence of 0.75, so the fit runs to the edge of
the allowed range. Second, re-choose `min_confidence` after calibrating. Temperatures change the
scale the thresholds are read on: applying semif's fitted temperatures with thresholds tuned on raw
scores sent more prompts to the fallback and lowered the right-target rate from 80.6% to 75.0%.

## Option weights

The router under-picks "moderate" difficulty: short requests like "add a --verbose flag" or "review my
staged changes" come out trivial and go to a model that is too weak. `option_weights` corrects that by
multiplying an option's score before anything else:

```yaml
option_weights:
  difficulty: {moderate: 3, hard: 2}
```

On 119 held-out prompts this raised difficulty accuracy from 79.0% to 85.7% (moderate from 44% to 80%),
right target from 73.9% to 78.2%, and cut the prompts sent to a model that was too weak from 13 to 7.
It ships off because the gain was not statistically significant on that set (paired test p = 0.30,
10 prompts fixed against 5 broken). Details: [evals/results/2026-09-26-difficulty.md](../../evals/results/2026-09-26-difficulty.md).
