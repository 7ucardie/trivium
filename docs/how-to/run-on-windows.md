# Run Trivium on Windows

Trivium runs on Windows with the `llamacpp` runtime on the CPU, or with `torch` on a CUDA GPU. This
guide uses `llamacpp`. It decides only: prompts the rules send to the local model go to Claude
instead. Expect seconds per decision, not a quarter of a second: about 6 to 10 seconds on a 24-core
Xeon from 2016.
A smaller model or fewer threads did not help: see the
[Windows CPU round](../../evals/results/2026-11-17-windows-cpu.md). `router.cache: true` makes exact
repeats instant.

## 1. Install with a prebuilt llama.cpp

`uv sync --extra llamacpp` builds llama.cpp from source, which fails with MinGW. Install the prebuilt
CPU wheel instead:

```sh
git clone https://github.com/7ucardie/trivium && cd trivium
uv tool install -e . --with "llama-cpp-python==0.3.35" --with "numpy>=2" --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
```

## 2. Choose the runtime

Copy the config and set the runtime:

```powershell
mkdir $HOME\.config\trivium
copy src\trivium\targets.yaml $HOME\.config\trivium\targets.yaml
# in that file, under router:   runtime: llamacpp
```

## 3. Start the router

```sh
ask serve                  # the first run downloads a 2.9 GB model file
ask service install        # or: a task that starts `ask serve` at every logon
```

`ask service install` creates the scheduled task `Trivium`, which needs an administrator prompt. It
runs in a minimised window and logs to `%LOCALAPPDATA%\trivium\trivium.log`.

## What differs from macOS

- **Open in Claude Code / Codex** opens a new console window instead of Terminal.
- **Codex from npm** is a `.cmd` file. Trivium starts its node script directly, so a prompt never
  passes through `cmd.exe`.
- **No local answers** with `llamacpp`, so the `local` target never appears.
- **Prompt editing** in the terminal app has no pre-filled text: Python on Windows has no readline.
