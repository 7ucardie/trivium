# CLI

```sh
ask "fix the flaky test in tests/test_auth.py"   # route, then open an interactive session
ask -p "regex for a semver string"               # one-shot: print the answer and exit
ask why "plan the billing architecture"          # show the decision and probabilities only
ask why --json "plan the billing architecture"   # the same as JSON, for scripts and editors
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

## Service

`ask` works without `ask serve`, but then it loads the model for every prompt, which takes several
seconds. To start the server at every login instead of by hand:

```sh
ask service install        # macOS: a launchd agent, logs to ~/Library/Logs/trivium.log
                           # Windows: a logon task, logs to %LOCALAPPDATA%	rivium	rivium.log
ask service status
ask service uninstall
```
