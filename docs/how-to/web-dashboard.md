# Use the web dashboard

While `ask serve` runs, http://127.0.0.1:8765/ is a dashboard with the same flow: pick a project, type
a prompt, see the decision with every answer's probabilities, click another target if you disagree,
then **Open in Claude Code / Codex** (a new Terminal window in that project) or **One-shot answer
here** (streamed into the page). Rate the result with one click; recent decisions sit underneath.
The simpler read-only page is still at `/status`.

To drive Trivium from another dashboard, see the [JSON API](../reference/api.md).
