# Use the terminal app

Run `trivium` (or `ask` with no arguments) in a project folder. It stays open like the claude and codex
CLIs: type a prompt, see where it would go, and act on it with one key.

```text
trivium · ~/workspaces/billing-service (billing-service) · semif · /help for keys
› add retry with backoff to the stripe client
  → codex-sol  gpt-6-sol  code_change · moderate · workspace  258 ms
    1 codex-sol 78%   2 claude-sonnet 15%   3 claude-haiku 5%
    enter open Codex · 1-3 pick · p one-shot · e edit · x drop
```

Enter opens the chosen tool right there, and you come back to trivium when you exit it. After each run
it asks whether that was the right model (`g`, or `b` and what it should have been), which is what
`ask export` later turns into tuning data. `/cd DIR` switches project; history is kept between runs.
