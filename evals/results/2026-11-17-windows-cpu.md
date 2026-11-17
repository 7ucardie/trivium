# Windows CPU round, 2026-11-17

Trivium ran on Windows for the first time, on the `llamacpp` runtime. A decision took 6 to 10 seconds,
so this round tested two ways to make it faster: a smaller model and fewer threads.

## Setup

- Machine: Windows Server 2025, Intel Xeon E5-2698 v4 at 2.2 GHz, 24 cores given to the VM, 64 GB, no GPU.
- Runtime: `llamacpp`, llama-cpp-python 0.3.35 from the prebuilt CPU wheel, Q4_K_M GGUF files.
- Config: the shipped `targets.yaml` with `runtime: llamacpp`, including the temperatures fitted for
  Qwen3.5-4B. No confidence floors, no option weights, cache off.
- An idle `ask serve` with the 4B model was running on the same machine during all runs.

## Smaller model

`ask eval evals/calibration-100.jsonl --split test`, the 28 held-out prompts.

| Model | Right target | Kind | Difficulty | Tools | Latency p50 | p90 |
|---|---|---|---|---|---|---|
| Qwen3.5-4B (shipped) | **67.9%** | **85.7%** | **82.1%** | **82.1%** | 5,964 ms | 8,928 ms |
| Qwen3.5-2B | 35.7% | 75.0% | 35.7% | 60.7% | **2,569 ms** | **2,874 ms** |

Pinned revisions: `Qwen/Qwen3.5-2B` at 15852e8, `bartowski/Qwen_Qwen3.5-2B-GGUF` at 7d26695.

The 2B model is 2.3 times as fast and routes half as many prompts to the right target. It loses most
on difficulty, the question that decides between a light and a heavy model. Not adopted.

Limits: the question wording and the temperatures were tuned on 4B, so 2B was tested on another
model's settings. Temperatures do not change which option scores highest, so they do not explain the
gap; wording tuned for 2B might close part of it. 28 prompts means one prompt is 3.6 points.

On the same split the `mlx` runtime in bf16 scored 71.4% right target on an Apple M5 Pro
([calibration write-up](2026-09-25-calibration-100.md)); the 4-bit file on this CPU scores 67.9%,
one prompt less.

## Threads

Qwen3.5-4B, the first 10 of the held-out prompts, `router.llama_threads` set per run. The decisions
were the same in every run (7 of 10 right).

| Threads | Latency p50 | p90 |
|---|---|---|
| 24 (default, all cores) | 6,223 ms | 9,862 ms |
| 16 | 6,272 ms | 6,699 ms |
| 12 | 7,976 ms | 8,421 ms |
| 8 | 11,090 ms | 11,574 ms |
| 6 | 14,647 ms | 15,098 ms |
| 4 | 21,114 ms | 21,525 ms |

Fewer threads are slower. 16 and 24 threads have the same median; 16 had a lower p90, but that is one
run of 10 prompts next to an idle server, so the default stays.

## Outcome

Keep Qwen3.5-4B and the default thread count. The only speed-up adopted in this round is the optional
disk cache (`router.cache`), which reuses the scores of an identical prompt: a repeat went from 9.4 s
to 11 ms. A new prompt still takes about 6 seconds on this machine.

Phi-3.5 Mini was also tried and left out of the comparison: the vendored semif code refuses it at load
("The GGUF vocabulary disagrees with the reference tokenizer"), so there are no scores for it.
