# Model comparison round, 2026-11-17

Which model should make the routing decision: Qwen3.5-2B, 4B or 9B through semif, or
h2o-lightning-4b (a Qwen3.5-4B fine-tuned for typed decisions) through its System One API?

## Data

All 255 labelled prompts (`calibration-100.jsonl`, `difficulty-120.jsonl`, `prompts.jsonl`), each
routed once per model on the Windows machine of the [Windows CPU round](2026-11-17-windows-cpu.md),
CPU only, Q4_K_M. Same three questions and the same evidence for every model.

- **Qwen3.5-2B, 4B, 9B:** semif on the `llamacpp` runtime (llama-cpp-python 0.3.35).
- **h2o-lightning-4b:** `llama-server` build 12470 with the native GGUF, `POST /v1/systemone` with
  the questions as `choice` questions. Its stock GGUF does not load in llama-cpp-python 0.3.35, so
  it could not run through semif.

Raw scores per prompt are in [`evals/scores/`](../scores/). No calibration, no option weights.

## Facts of the runs

All times are local time (CET, UTC+1) on Tuesday 2026-11-17. Code: commit `861b0d5` plus the shipped
`targets.yaml` with only `runtime`, `model`, `revision` and `gguf_repo` changed per model.

Machine: Windows Server 2025, Intel Xeon E5-2698 v4 at 2.2 GHz, 24 cores given to the VM, 64 GB, no
GPU. The runs ran one after another, never at the same time.

| Model | Start | End | Prompts | Time per prompt: min / mean / p50 / max | Sum of prompt times |
|---|---|---|---|---|---|
| Qwen3.5-4B | 12:46 | 13:20 | 255 | not recorded | not recorded |
| Qwen3.5-2B | 13:20 | 13:39 | 255 | 2.3 / 4.4 / 4.7 / 7.9 s | 18.9 min |
| h2o-lightning-4b | 13:39 | 14:07 | 255 | 4.0 / 6.6 / 6.7 / 28.9 s | 28.2 min |
| Qwen3.5-9B | 14:08 | 14:51 | 255 | 9.1 / 10.1 / 9.7 / 22.1 s | 43.1 min |

Start and end are the creation time and the last write of the score file. The 4B run was stopped
once by mistake and resumed from the rows it had; its 34 minutes include that. The 9B start includes
loading the model after the 6.2 GB download.

| Model | Weights | Revision | GGUF | Revision |
|---|---|---|---|---|
| Qwen3.5-4B | `Qwen/Qwen3.5-4B` | `851bf6e8` | `bartowski/Qwen_Qwen3.5-4B-GGUF`, `Qwen_Qwen3.5-4B-Q4_K_M.gguf` | `4168f45a` |
| Qwen3.5-2B | `Qwen/Qwen3.5-2B` | `15852e8c` | `bartowski/Qwen_Qwen3.5-2B-GGUF`, `Qwen_Qwen3.5-2B-Q4_K_M.gguf` | `7d266954` |
| Qwen3.5-9B | `Qwen/Qwen3.5-9B` | `c2022362` | `bartowski/Qwen_Qwen3.5-9B-GGUF`, Q4_K_M | `182be2fd` |
| h2o-lightning-4b | `h2oai/h2o-lightning-4b` | `659fc412` | `h2oai/h2o-lightning-4b-gguf`, `h2o-lightning-4b-Q4_K_M.gguf` | `61f8d8b7` |

Software: llama-cpp-python 0.3.35 (prebuilt CPU wheel) for the Qwen models; llama.cpp `llama-server`
build 12470, commit `dde9de82c`, with `-c 8192 -np 1 --no-kv-unified` for h2o-lightning-4b.

Other load on the machine: an idle `ask serve` with the 4B model during all runs, and the idle
`llama-server` with h2o-lightning-4b during the 2B and 9B runs (it holds memory, no CPU).

Score files (SHA-256, first 12 characters), each 255 rows with `key`, `set`, `split`, `prompt`,
`expect`, `probs`, and `ms` except for 4B:

- `qwen3.5-4b-llamacpp-q4.jsonl`: `ebe0860572fd`
- `qwen3.5-2b-llamacpp-q4.jsonl`: `e357c233b507`
- `qwen3.5-9b-llamacpp-q4.jsonl`: `dcddc1fcae9a`
- `h2o-lightning-4b-systemone-q4.jsonl`: `2a467a5cb4a8`

What is measured and what is derived:

- **Measured:** the probabilities per option and the time per prompt in the score files.
- **Derived from the scores:** "right target" (highest score per question, then the rules of
  `targets.yaml`), "too weak" and "too strong" (tier of that target against the tier the labels give).
- **Not measured here:** the time per prompt of 4B. The "about 6 s" below is the p50 of 5,964 ms on
  the 28 held-out prompts in the [Windows CPU round](2026-11-17-windows-cpu.md) of the same day.

## Result, all 255 prompts

| Model | Right target | Kind | Difficulty | Tools | Too weak | Too strong | Time per prompt (p50) |
|---|---|---|---|---|---|---|---|
| Qwen3.5-2B | 39.6% | 71.0% | 41.6% | 71.4% | 14 | 129 | 4.7 s |
| Qwen3.5-4B (shipped) | 71.8% | 89.4% | 77.3% | 81.6% | 33 | 36 | about 6 s (not recorded in this run) |
| Qwen3.5-9B | 74.9% | 89.8% | **81.6%** | **84.7%** | 22 | 37 | 9.7 s |
| h2o-lightning-4b | **75.7%** | **91.0%** | 79.2% | 80.4% | **19** | 40 | 6.7 s |

"Too weak" counts prompts sent to a lower tier than the labels would, "too strong" to a higher one.

## Result, held-out 28 prompts

| Model | Right target | Kind | Difficulty | Tools | Too weak | Too strong |
|---|---|---|---|---|---|---|
| Qwen3.5-2B | 35.7% | 75.0% | 35.7% | 60.7% | 0 | 18 |
| Qwen3.5-4B (shipped) | 67.9% | 85.7% | 82.1% | 82.1% | 2 | 7 |
| Qwen3.5-9B | 60.7% | 89.3% | 67.9% | 85.7% | 4 | 7 |
| h2o-lightning-4b | **71.4%** | **92.9%** | 75.0% | 85.7% | 5 | 3 |

## With the correction model on top

The [correction model](2026-11-17-correction-model.md) (a logistic regression on all 11 scores,
5-fold cross-validation repeated 10 times) on each model's scores, all 255 prompts:

| Model | As is | Per question, all scores | Direct to target | Too weak / too strong (per question, all scores) |
|---|---|---|---|---|
| Qwen3.5-2B | 39.6% | 64.9% | 63.7% | 41.1 / 42.9 |
| Qwen3.5-4B (shipped) | 71.8% | 78.8% | 79.4% | 24.3 / 25.9 |
| Qwen3.5-9B | 74.9% | **81.5%** | 80.3% | 23.6 / 22.6 |
| h2o-lightning-4b | 75.7% | 79.1% | 80.1% | 23.4 / 27.9 |

## Reading

- Qwen3.5-2B is out: it sends half the prompts to a model that is too strong, and the correction
  model does not repair that.
- 4B, 9B and h2o-lightning-4b are close. As is, 9B and h2o-lightning-4b route 3 to 4 points more
  prompts to the right target than 4B (8 to 10 prompts of 255) and send fewer to a model that is too
  weak. On the held-out 28 the order differs, and 9B is the worst of the three there.
- With the correction model on top the three land within 3 points of each other (79% to 82%). The
  correction model gains more than the choice between these three models.
- 9B costs about 4 seconds more per prompt than 4B on this machine; h2o-lightning-4b costs about the
  same as 4B.

## Limits

- 255 prompts written by the author and an agent, not prompts from real use.
- The question wording and the rules were tuned on 136 of these prompts with Qwen3.5-4B. That
  favours 4B a little and may hold 9B and h2o-lightning-4b back.
- Differences of 3 to 4 points on 255 prompts, and of one or two prompts on 28, are within what
  chance can produce. No significance test was planned, so this is descriptive.
- h2o-lightning-4b ran through another server and another llama.cpp build than the Qwen models, so
  the times are not a like-for-like comparison. The 4B time was not recorded in this run.
- One quantisation, one machine, CPU only.

## Next

Not decided. The options: keep 4B and add the correction model, or add a System One backend so that
h2o-lightning-4b (and Kev and Jev, which speak the same API) can make the decision.
