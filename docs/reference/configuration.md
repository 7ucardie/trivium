# Configuration

`ask targets` prints the config file in use. To customise it:

```sh
mkdir -p ~/.config/trivium
cp src/trivium/targets.yaml ~/.config/trivium/targets.yaml   # or point TRIVIUM_CONFIG at any file
```

The file has four parts: `router` (model, pinned revision, quantisation, port), `questions` (wording
and option descriptions), `targets` (vendor, tier, model id, optional effort) and `rules`
(first match wins, plus `default` and `fallback`).

`router.cache: true` keeps the router's scores on disk, in `route-cache` next to the decision log, and
reuses them when the same prompt is typed in the same repository with the same questions and router
settings. It ships off. It only helps for exact repeats, which matters most on the slow `llamacpp`
runtime. Rules, calibration and option weights are applied after the cache, so changing those needs no
clearing; `ask eval` and `ask calibrate` never use it.

`router.correction: true` applies the correction model saved by `ask correct --write`, instead of the
option weights and the temperatures. It ships off; see [Correction model](../how-to/calibrate.md#correction-model).

If the router fails (the model server is down, a System One server does not answer in time), the prompt
goes to the `fallback` target and the decision says "router failed" with the cause. `ask eval`,
`ask calibrate` and `ask correct` stop with the error instead.

## Guard

Before a prompt goes to the router, the decision log or a model, Trivium checks it for four kinds of
content. Each kind has its own action in the `guard` block:

```yaml
guard:
  secrets: redact
  hidden: redact
  injection: warn
  personal: warn
```

| Kind | What it finds | Default |
|---|---|---|
| `secrets` | Private key blocks; AWS, GitHub, Anthropic, OpenAI, Slack, Google and Stripe keys; JWTs; bearer tokens; passwords in URLs; `password=`, `api_key:`, `token=` and similar with a literal value | `redact` |
| `hidden` | Zero-width characters, direction overrides and invisible "tag" characters, which can hide instructions in pasted text | `redact` |
| `injection` | Text that poses as something other than your own words: chat control tokens (`<\|im_start\|>`, `[INST]`), role tags (`<system>`, `<system-reminder>`, `<tool_result>`), role labels at the start of a line (`System prompt:`, `Assistant:`), orders such as "ignore previous instructions" or "do not tell the user", claims such as "message from Anthropic", and base64 blocks of 200 characters or more | `warn` |
| `personal` | Payment card numbers and IBANs with a valid checksum | `warn` |

| Action | What happens |
|---|---|
| `off` | Not checked |
| `warn` | Trivium says what kind it found and goes on with the prompt unchanged |
| `redact` | The finding is replaced by a placeholder such as `[REDACTED:github-token]`; hidden characters are removed |
| `block` | The prompt is refused: nothing is routed, logged or sent. `ask` exits with code 2, the API answers 400 |

Trivium names the kind and the count, never the finding itself, and the decision log holds the prompt
after redaction. A config without a `guard` block gets the defaults above. `ask eval`, `ask calibrate`
and `ask correct` do not use the guard.

What it does not do:

- **It recognises shapes, not meaning.** A secret without a known shape (a password in a sentence, a
  key in a format not listed) passes, and so does an injection in other words than the ones above.
- **It reads the prompt only.** Files that Claude Code or Codex open later are not checked.
- **`injection` warns by default** because the same text is legitimate when you ask about it ("what
  does `<|im_start|>` do"). Set it to `block` if you paste content from sources you do not trust.
- **Redaction can remove what you meant to send.** If the question is about the token itself, set
  `secrets: warn` for that session.

On the 255 bundled prompts, none of which holds a secret, the guard flags none.

Wording is the biggest lever. Questions ask what the text *says*, not what to do, and every option
has a description. Changing the difficulty question from "How demanding is the work?" to "How much
work would a skilled engineer need?" with time-based options moved difficulty accuracy from 67% to
81% on the bundled eval set.
