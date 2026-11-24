# Runtimes and backends

## Runtimes

All three runtimes read the same prompt and answer slots through the vendored semif code, so they make
the same decisions up to arithmetic. On the bundled set, against `mlx`, on an Apple M5 Pro:

| Runtime | Right target | Changed targets | Changed answers | Largest score change | p50 per prompt |
|---|---|---|---|---|---|
| `mlx`, bf16 | 29/36 | | | | 253 ms |
| `torch` on MPS, bf16 | 29/36 | 0/36 | 3/108 | 0.33 | 1,293 ms |
| `llamacpp` on CPU, Q4_K_M | 27/36 | 3/36 | 4/108 | 0.56 | 2,037 ms |

`torch` on an Apple GPU is five times slower than MLX; it exists for CUDA machines. `llamacpp` runs
the 4-bit file on the CPU, which costs two prompts on this set and two seconds a prompt.

## Backends

`router.backend` picks who answers the questions:

- `semif` (default): Qwen3.5-4B answers all three and also answers local prompts.
- `laya`: the Laya encoder answers all three. Faster, decides only, so local targets go to Claude.
- `hybrid`: Laya answers the questions listed in `router.hybrid_laya` (default `[tools]`), semif the
  rest. It looked best on the first 36 prompts, but on the 100-prompt set it routes general questions
  typed inside a repository ("what does ECONNREFUSED mean") as if they needed the workspace, and it
  scores 57.1% against semif's 71.4% on the held-out prompts. Use semif unless your own evaluation
  says otherwise.

- `systemone`: a server you run answers the questions over `POST /v1/systemone`, the API that
  h2o-lightning-4b, Kev and Jev share. Decides only, so local targets go to Claude. See
  [System One backend](#system-one-backend).

`laya` and `hybrid` need `uv sync --extra laya`.

`ask serve` reports which backend it runs. If your config names another one, `ask` loads the
configured backend in-process rather than read one router's scores with another's calibration;
restart `ask serve` to switch it.

Laya reads about 320 tokens of evidence and cuts the end, so on a long prompt it never saw the
repository sentence. Moving that sentence in front of the prompt fixed long prompts but cost 9 of the
36 tools answers on short ones, so Trivium instead keeps the order and shortens the request to
`router.laya_max_request_chars` (300) for Laya, keeping its start and end. On a 60-line pasted log
that moves Laya's "needs the workspace" score from 0.15 both inside and outside a repository to 0.60
inside and 0.08 outside, and leaves the bundled set unchanged (its longest prompt is 147 characters).
The 300 was chosen on two made-up long prompts, so treat it as a starting point.

Laya defaults to its `typed-decisions` checkpoint. In the hybrid it scored 100% on tools against the
English checkpoint's 97.2%, and sent 8.3% of prompts to the fallback instead of 13.9%, because it
reports its answers more confidently. Both differences are one or two prompts on the bundled set.

## Laya backend

[Laya](https://huggingface.co/convaiinnovations/laya) is a 421M-parameter encoder that makes the same
kind of typed decision in about 100 ms for all three questions. Without training on your own prompts it
rates almost every request "moderate", but it is the better judge of whether a request needs your files.
It is available as an optional backend:

```sh
uv sync --extra laya
# targets.yaml: router.backend: laya
```

Laya only decides, so with this backend local targets are routed to Claude instead.

## System One backend

Trivium sends the evidence and the three questions to a server and reads back a probability per option.
Nothing is loaded in Trivium itself, so `router.runtime` and `router.model` are ignored.

```yaml
router:
  backend: systemone
  systemone_url: http://127.0.0.1:8080/v1/systemone
  systemone_timeout: 120   # seconds
```

For [h2o-lightning-4b](https://huggingface.co/h2oai/h2o-lightning-4b), start llama.cpp's `llama-server`
(build 11773 or later) with the model's native GGUF file:

```sh
llama-server -m h2o-lightning-4b-Q4_K_M.gguf -c 8192 -np 1 --host 127.0.0.1 --port 8080
```

The prompt and the repository name are sent to `systemone_url`. With a local address they stay on your
machine; with a hosted service they leave it. Trivium sends no credentials, so a service that needs an
API key is not supported yet.

On the 255 labelled prompts h2o-lightning-4b routed 75.7% to the right target against 71.8% for
Qwen3.5-4B through semif, at about the same time per prompt on a CPU. The difference is within what
chance can produce on this set. Details:
[evals/results/2026-11-17-model-comparison.md](../../evals/results/2026-11-17-model-comparison.md).
