# Correction model round, 2026-11-17

Does a small model on top of the router's scores pick the right target more often than taking the
highest score per question? An experiment only: nothing in Trivium uses it yet.

## Data

All 255 labelled prompts: `calibration-100.jsonl` (100), `difficulty-120.jsonl` (119) and
`prompts.jsonl` (36). Each was routed once with Qwen3.5-4B on the `llamacpp` runtime (Q4_K_M, the
Windows machine of the [Windows CPU round](2026-11-17-windows-cpu.md)). The raw scores, before
calibration, are in [`evals/scores/qwen3.5-4b-llamacpp-q4.jsonl`](../scores/qwen3.5-4b-llamacpp-q4.jsonl):
one row per prompt with the 11 probabilities and the labels.

Facts: the scores were collected on Tuesday 2026-11-17 between 12:46 and 13:20 local time (CET), at
commit `861b0d5`, with `Qwen/Qwen3.5-4B` at `851bf6e8` and `bartowski/Qwen_Qwen3.5-4B-GGUF` at
`4168f45a`. The analysis ran the same day with scikit-learn's `LogisticRegression(C=1.0)` and
`RepeatedStratifiedKFold(n_splits=5, n_repeats=10, random_state=0)`, so it gives the same numbers
when repeated. The probabilities are measured; every percentage below is computed from them. The
[model comparison](2026-11-17-model-comparison.md) has the machine and the other models.

## Method

[`evals/correction_experiment.py`](../correction_experiment.py) compares five ways to get from the
scores to a target:

- **Router as shipped:** the highest score per question, then the rules.
- **Router + option weights:** the same with `difficulty: {moderate: 3, hard: 2}`.
- **Per question, own scores:** a logistic regression per question on that question's own log scores,
  then the rules. This generalises temperatures and option weights.
- **Per question, all scores:** a logistic regression per question on all 11 log scores, then the rules.
- **Direct to target:** one logistic regression from all 11 log scores to the target.

The three fitted models are scored on prompts they did not see: 5-fold cross-validation, stratified
on difficulty, repeated 10 times. "Too weak" counts prompts sent to a lower tier than the labels
would, "too strong" to a higher one. The last column fits on the other 227 prompts and tests on the
28 held-out prompts of `calibration-100.jsonl`.

```sh
uv run --no-project --with pyyaml --with scikit-learn --with numpy \
  python evals/correction_experiment.py evals/scores/qwen3.5-4b-llamacpp-q4.jsonl   # with PYTHONPATH=src
```

## Result

| Variant | Right target, all 255 | Range over 10 repeats | Too weak | Too strong | Held-out 28 |
|---|---|---|---|---|---|
| Router as shipped | 71.8% | | 33 | 36 | 67.9% |
| Router + option weights | 75.7% | | 20 | 39 | 71.4% |
| Per question, own scores | 76.9% | 75.7% to 78.4% | 20.8 | 34.9 | 75.0% |
| Per question, all scores | 78.8% | 77.6% to 80.4% | 24.3 | 25.9 | **85.7%** |
| Direct to target | **79.4%** | 77.6% to 80.4% | 22.2 | 27.6 | 82.1% |

For the fitted models "too weak" and "too strong" are means over the 10 repeats.

A model on all 11 scores routes about 7 points more prompts to the right target than the shipped
router, with fewer prompts sent to a model that is too weak and fewer to one that is too strong. Using
all scores beats correcting each question on its own: the scores of one question carry information
about another. It costs no extra time per prompt.

## Limits

- 255 prompts written by the author and an agent, not prompts from real use. The gain on a user's own
  prompts can differ.
- The shipped router and the option weights are not fitted here, but their wording and weights were
  chosen on 136 of these prompts, so their numbers are a little flattering. The fitted models have no
  such advantage: every prompt is scored out of fold.
- 85.7% on the held-out prompts is 24 of 28, four prompts more than the shipped router. It points the
  same way; it is not a measurement of the gain.
- No significance test was planned before the run, so this is descriptive.
- One model, one runtime, one quantisation.

## Next

Build it only after the same comparison on prompts from real use (`ask export`), and after the model
comparison of this round (Qwen3.5-2B and 9B, h2o-lightning-4b) shows which router the correction
should sit on.
