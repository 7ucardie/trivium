# Status and limits

- Early. It works end to end on the author's machine; interfaces and defaults will change.
- Calibration is fitted on 72 labelled prompts and checked on 28; one held-out prompt is 3.6 points.
  Your own prompts (`ask export`) are the better calibration set.
- Only the `mlx` runtime has been used day to day. `torch` was tested on Apple MPS, not on a CUDA
  GPU; `llamacpp` was tested on an Apple CPU. Both match the MLX routing closely on the bundled set
  (see [Runtimes](runtimes-and-backends.md#runtimes)), but treat them as new.
- `ask service` uses launchd on macOS and a scheduled task on Windows; there is none for Linux.
- Windows was tested on one machine, with the `llamacpp` runtime: routing, the API, one-shot answers and
  opening a console. The terminal app and `--ask` are written for it but were not tried by hand.
- Routing happens once per task, not per turn. Once a session is open you stay in that tool.
- semif's probabilities are not calibrated. Treat `min_confidence` values as starting points.
- Codex refuses one-shot runs outside a trusted git repository. Trivium leaves that check alone.
