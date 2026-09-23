# Trivium

[![test](https://github.com/7ucardie/trivium/actions/workflows/test.yml/badge.svg)](https://github.com/7ucardie/trivium/actions/workflows/test.yml)

A local System-1 router that sends each prompt to the right model: a local Qwen, Claude Code, or Codex.

*Trivium* is Latin for the place where three roads meet. You type one command; a small model on your
own machine reads the prompt in about a quarter of a second, and the prompt goes down one of three
roads: answered locally, opened in Claude Code, or opened in Codex, on the model tier the task needs.

```text
$ ask why "add retry with exponential backoff to the http client in server.py"
→ codex-sol (gpt-6-sol) · code_change/trivial/workspace · 258 ms · rule 3
  kind       code_change=1.00  quick_answer=0.00  design=0.00  debugging=0.00  review=0.00  writing=0.00
  difficulty trivial=0.78  moderate=0.22  hard=0.00
  tools      workspace=0.99  none=0.01

$ ask -p "what does HTTP 409 mean"
→ local (Qwen/Qwen3.5-4B) · quick_answer/trivial/none · 258 ms · rule 1
**HTTP 409 Conflict** is a server response status code indicating ...
```

## Why

Claude Code and Codex both choose their model when they start, so the cheapest moment to pick a model
is before either one runs. Picking by hand is friction, so in practice everything goes to the biggest
model. Trivium makes that choice for you, in front of both tools:

- **Across vendors.** Routing inside Claude Code can't reach GPT, and routing inside Codex can't
  reach Opus. A wrapper can reach both, plus a local model.
- **Before any tokens are spent.** The decision is one forward pass of a local model. No hosted call
  reads your prompt until the chosen tool does.
- **With your existing setup.** Trivium launches the real `claude` and `codex` CLIs, so your logins,
  subscriptions, settings, skills and MCP servers work as they already do.

## How it works

```text
prompt ─▶ evidence ─▶ router ─────────────▶ rules ─▶ local Qwen      (answers in-process)
          (prompt +    3 typed questions,           claude --model …  (Claude Code)
          "inside      one forward pass,            codex -m …        (Codex)
          repo X")     probability per option  └──▶ decisions.jsonl  (every decision logged)
```

1. **Evidence.** The prompt (head and tail if long) plus one plain sentence saying whether you are
   inside a git repository. The router reads sentences better than facts it has to infer.
2. **Three questions.** `kind` (quick answer, code change, debugging, review, design, writing),
   `difficulty` (trivial, moderate, hard) and `tools` (none, workspace). The router returns a
   probability per option, using [semif](https://github.com/theoleecj/semif) to read Qwen3.5-4B's
   option logits directly: no text is generated, so there is nothing to parse or hallucinate.
3. **Rules.** A first-match-wins table in `targets.yaml` maps the answers to a target. If any answer
   is less confident than its threshold, the prompt goes to a safe fallback instead.
4. **Launch.** `claude --model <id>` or `codex -m <id>`, interactive by default or one-shot with
   `-p`. Trivial questions are answered by the same Qwen that routed them, so one model in memory
   does both jobs.

### Default routing

| The router says | Goes to |
|---|---|
| trivial quick answer or short writing, no files | local Qwen3.5-4B |
| other trivial work without files | Claude Haiku 4.5 |
| code change, trivial or moderate | Codex gpt-6-sol |
| code change, hard | Codex gpt-6-astra |
| design, hard | Claude Fable 5.1 |
| anything else hard | Claude Opus 5.5 |
| everything else, or the router is unsure | Claude Sonnet 5 |

Every model name, rule, question and threshold lives in `targets.yaml`. A new model is a config edit.

## Requirements

- macOS on Apple Silicon (the router runs on MLX). About 9 GB of free memory for Qwen3.5-4B in bf16,
  or less with `bits: 8`.
- [uv](https://docs.astral.sh/uv/) and Python 3.10–3.13.
- The [Claude Code](https://code.claude.com) and/or [Codex](https://github.com/openai/codex) CLIs,
  logged in, for the targets you want to use.

## Install

```sh
git clone https://github.com/7ucardie/trivium && cd trivium
uv sync                    # MLX, semif (which also pins torch and transformers)
uv tool install -e .       # puts `ask` (and `trivium`) on your PATH
ask serve                  # keep the router warm; the first run downloads Qwen3.5-4B (~9 GB)
```

`ask` works without `ask serve`, but then it loads the model for every prompt, which takes several
seconds. To start the server at every login instead of by hand:

```sh
ask service install        # a launchd agent that runs `ask serve`; logs to ~/Library/Logs/trivium.log
ask service status
ask service uninstall
```

## Usage

```sh
ask "fix the flaky test in tests/test_auth.py"   # route, then open an interactive session
ask -p "regex for a semver string"               # one-shot: print the answer and exit
ask why "plan the billing architecture"          # show the decision and probabilities only
ask --ask "refactor the auth module"             # show the likeliest targets and pick one
ask --to opus "..."                              # skip the router: target, short name or model id
ask --via codex "..."                            # keep the routed tier, use the other vendor
ask --no-local "..."                             # never answer with the local model
ask targets                                      # list targets and the config file in use
```

`--ask` shows the three likeliest targets with their probability, computed by routing the top
two answers of every question through the rules, and lets you pick one or keep the router's choice.
Set `router.ask_when_unsure: true` to get that prompt automatically whenever the router is unsure,
instead of the fallback.

`--via` keeps the strength and swaps the vendor: a route to Claude Opus becomes Codex gpt-6-astra, and a
route to Codex gpt-6-sol becomes Claude Sonnet.

## Configuration

`ask targets` prints the config file in use. To customise it:

```sh
mkdir -p ~/.config/trivium
cp src/trivium/targets.yaml ~/.config/trivium/targets.yaml   # or point TRIVIUM_CONFIG at any file
```

The file has four parts: `router` (model, pinned revision, quantisation, port), `questions` (wording
and option descriptions), `targets` (vendor, tier, model id, optional effort) and `rules`
(first match wins, plus `default` and `fallback`).

Wording is the biggest lever. Questions ask what the text *says*, not what to do, and every option
has a description. Changing the difficulty question from "How demanding is the work?" to "How much
work would a skilled engineer need?" with time-based options moved difficulty accuracy from 67% to
81% on the bundled eval set.

## Measuring and improving the router

```sh
ask eval evals/prompts.jsonl --show-misses       # accuracy per question and per target
ask eval evals/prompts.jsonl --backend laya      # same prompts, Laya instead of semif
ask rate bad --should opus                       # label the last real decision
```

Every decision is appended to `~/.local/state/trivium/decisions.jsonl` with the full probabilities,
and `ask rate` appends labels. That log is the data for tuning thresholds and wording, and for
training a router later.

`evals/prompts.jsonl` holds 36 prompts I wrote and labelled by hand. Same prompts, same questions,
same rules, confidence thresholds off, on an Apple M5 Pro (full write-up in
[`evals/results/2026-09-23.md`](evals/results/2026-09-23.md)):

| Router | Kind | Difficulty | Tools | Right target | Latency p50 |
|---|---|---|---|---|---|
| semif + Qwen3.5-4B, MLX bf16 (default) | **94.4%** | **80.6%** | 80.6% | **80.6%** | 241 ms |
| Laya 0.3.7, English checkpoint | 69.4% | 47.2% | 97.2% | 38.9% | **98 ms** |
| Laya 0.3.7, typed-decisions checkpoint | 80.6% | 47.2% | **100%** | 47.2% | 99 ms |
| Hybrid: Laya for tools, semif for the rest | **94.4%** | **80.6%** | 97.2% | **83.3%** | 263 ms |

"Right target" means the router's answers lead to the same target as the hand labels would. These are
small-sample numbers, and the questions were tuned on the same set with semif, which favours semif.
Replace the file with your own prompts before trusting any threshold.

### Backends

`router.backend` picks who answers the questions:

- `semif` (default): Qwen3.5-4B answers all three and also answers local prompts.
- `laya`: the Laya encoder answers all three. Faster, decides only, so local targets go to Claude.
- `hybrid`: Laya answers the questions listed in `router.hybrid_laya` (default `[tools]`), semif the
  rest. The best result on the bundled set, at the cost of a second model in memory.

`laya` and `hybrid` need `uv sync --extra laya`.

### Calibration

Router scores are not probabilities until you calibrate them. `ask calibrate` fits one temperature
per question on labelled prompts and prints a block for your config:

```sh
ask calibrate evals/prompts.jsonl --backend hybrid
```

```yaml
calibration:
  hybrid:
    kind: 0.6
    difficulty: 1.35
    tools: 0.25   # flagged: at the grid edge, needs more labelled data
```

Two lessons from the bundled set. First, fit on a few hundred labels, not 36: on this set Laya's
tools answers are right 35 times in 36 yet reported at a median confidence of 0.75, so the fit runs to the edge of
the allowed range. Second, re-choose `min_confidence` after calibrating. Temperatures change the
scale the thresholds are read on: applying semif's fitted temperatures with thresholds tuned on raw
scores sent more prompts to the fallback and lowered the right-target rate from 80.6% to 75.0%.

### Laya backend

[Laya](https://huggingface.co/convaiinnovations/laya) is a 421M-parameter encoder that makes the same
kind of typed decision in about 100 ms for all three questions. Without training on your own prompts it
rates almost every request "moderate", but it is the better judge of whether a request needs your files.
It is available as an optional backend:

```sh
uv sync --extra laya
# targets.yaml: router.backend: laya
```

Laya only decides, so with this backend local targets are routed to Claude instead.

## Status and limits

- Early. It works end to end on the author's machine; interfaces and defaults will change.
- Calibration and thresholds are fitted on 36 hand-written prompts; nothing ships pre-calibrated.
- Apple Silicon only for the default backend. semif also has PyTorch (CUDA) and llama.cpp backends
  that Trivium does not wire up yet.
- Routing happens once per task, not per turn. Once a session is open you stay in that tool.
- semif's probabilities are not calibrated. Treat `min_confidence` values as starting points.
- Codex refuses one-shot runs outside a trusted git repository. Trivium leaves that check alone.

## Credits and licenses

Trivium is released under the [MIT License](LICENSE). It builds on:

- [semif](https://github.com/theoleecj/semif) (MIT) for option-logit scoring
- [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) (Apache 2.0), downloaded at run time, not
  redistributed
- [MLX](https://github.com/ml-explore/mlx) and [mlx-lm](https://github.com/ml-explore/mlx-lm) (MIT)
- [Laya](https://huggingface.co/convaiinnovations/laya) (Apache 2.0), optional

Claude, Claude Code, Codex and the model names are trademarks of their owners. Trivium is an
independent project and is not affiliated with Anthropic or OpenAI.
