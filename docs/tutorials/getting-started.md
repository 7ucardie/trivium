# Getting started

In this tutorial you install Trivium, look at one routing decision, get one answer from the local
model, open one routed session and rate it. It takes about fifteen minutes, most of it the model
download.

It follows the default setup: macOS on Apple Silicon with about 9 GB of free memory, and the
[Claude Code](https://code.claude.com) and [Codex](https://github.com/openai/codex) CLIs installed
and logged in. For another machine, see [Runtimes and backends](../reference/runtimes-and-backends.md).

## 1. Install

```sh
git clone https://github.com/7ucardie/trivium && cd trivium
uv sync
uv tool install -e .
```

`ask` and `trivium` are now on your PATH. Check which targets you have:

```sh
ask targets
```

It lists every target with its vendor and model, and the config file in use.

## 2. Start the router

In a second terminal:

```sh
ask serve
```

The first run downloads Qwen3.5-4B (about 9 GB). Leave it running: it keeps the model in memory, so
each decision takes about a quarter of a second instead of several seconds.

## 3. Look at a decision

`ask why` shows where a prompt would go and runs nothing:

```text
$ ask why "add retry with exponential backoff to the http client in server.py"
→ codex-sol (gpt-6-sol) · code_change/trivial/workspace · 258 ms · rule 3
  kind       code_change=1.00  quick_answer=0.00  design=0.00  debugging=0.00  review=0.00  writing=0.00
  difficulty trivial=0.78  moderate=0.22  hard=0.00
  tools      workspace=0.99  none=0.01
```

The first line is the target, the three answers, the routing time and the rule that matched. The
lines below are the router's score for every option. Try a few prompts of your own, some inside a
git repository and some outside: the `tools` answer changes with where you are.

## 4. Get a local answer

A trivial question that needs no files is answered by the same model that routed it:

```text
$ ask -p "what does HTTP 409 mean"
→ local (Qwen/Qwen3.5-4B) · quick_answer/trivial/none · 258 ms · rule 1
**HTTP 409 Conflict** is a server response status code indicating ...
```

`-p` is one-shot: print the answer and exit. No hosted model saw this prompt.

## 5. Open a routed session

Go to one of your projects and run `trivium`. Type a prompt and press Enter:

```text
trivium · ~/workspaces/billing-service (billing-service) · semif · /help for keys
› add retry with backoff to the stripe client
  → codex-sol  gpt-6-sol  code_change · moderate · workspace  258 ms
    1 codex-sol 78%   2 claude-sonnet 15%   3 claude-haiku 5%
    enter open Codex · 1-3 pick · p one-shot · e edit · x drop
```

Press Enter to open the chosen tool, or `1`-`3` to pick another target first. The real `codex` or
`claude` CLI opens in this terminal, with your own login and settings. Exit it as usual and you are
back in Trivium.

## 6. Rate it

After the run Trivium asks whether that was the right model. Press `g` if it was, or `b` and name
the target it should have been. Every decision and rating is appended to
`~/.local/state/trivium/decisions.jsonl`.

## Where next

- The same flow in the browser: [Use the web dashboard](../how-to/web-dashboard.md).
- Start the router at every login: `ask service install` (see the [CLI reference](../reference/cli.md#service)).
- Change models or rules: [Configuration](../reference/configuration.md).
- Turn your ratings into numbers: [Measure and improve the router](../how-to/measure-the-router.md).
- Why it is built this way: [How Trivium works](../explanation/how-trivium-works.md).
