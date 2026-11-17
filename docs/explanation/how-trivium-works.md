# How Trivium works

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
