# Changelog

What changed in Trivium, newest first. Dates are the day the change was pushed to `main`.

## v0.3.0, 2026-11-24

### Removed

- **The `hybrid` backend, on 2026-11-24.**
  - **What it was:** `router.backend: hybrid` let Laya answer the questions listed in
    `router.hybrid_laya` (by default only `tools`) and semif answer the rest.
  - **Why it is gone:** it routed worse than the default. On the 28 held-out prompts of
    `evals/calibration-100.jsonl` it sent 57.1% to the right target against 71.4% for semif, because it
    treats a general question typed inside a repository as if it needed the workspace
    ([measurement](evals/results/2026-09-25-calibration-100.md)). It only looked better on the first 36
    prompts.
  - **Who decided:** the author, on the advice of the assistant that did the measurements.
  - **What you notice:** a config with `router.backend: hybrid` is refused at start with a message that
    says so; `--backend hybrid` is no longer accepted by `ask eval`, `ask calibrate` and `ask correct`.
  - **What to do:** set `router.backend: semif`. A leftover `router.hybrid_laya` line or `hybrid` block
    in `calibration.yaml` is ignored and can be deleted.
  - **Not removed:** the `laya` backend.
  - **Removed files and settings:** `src/trivium/hybrid.py`, the setting `router.hybrid_laya`, the test
    `test_hybrid_splits_questions`.

### Added

- **Guard, 2026-11-24:** every prompt is checked before it reaches the router, the decision log or a
  model. Secrets are redacted and invisible characters removed by default; text that poses as the
  system or the assistant, card numbers and IBANs give a warning. Each kind can be set to `off`,
  `warn`, `redact` or `block` in the new `guard` block. **This changes behaviour without a config
  change:** a prompt that holds a recognised key, token or password is now sent with a placeholder in
  its place.

- **Correction model, 2026-11-24:** `ask correct` fits a logistic regression per question on the
  router's scores and `router.correction: true` applies it. Off by default.
- **`systemone` backend, 2026-11-24:** a local server answers the questions over `POST /v1/systemone`
  (h2o-lightning-4b, Kev). Decides only.
- **Fallback when the router fails, 2026-11-24:** the prompt goes to the `fallback` target and the
  decision says why.
- **Raw scores in the decision log, 2026-11-24:** `ask export` writes them as `probs`.
- **Windows, 2026-11-17:** runs with the `llamacpp` runtime; `ask service` installs a logon task, since
  2026-11-24 without a window.
- **`router.cache`, 2026-11-17:** keep the router's scores on disk for identical prompts. Off by default.

## v0.2.0

See the [release notes](https://github.com/7ucardie/trivium/releases/tag/v0.2.0).
