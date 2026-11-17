# JSON API

The dashboard is a client of a small JSON API on the same server, so another dashboard can use the API
directly:

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/status` | | model, backend, runtime, uptime, counters, routing latencies |
| GET | `/api/decisions?limit=25` | | recent decisions with picks and ratings |
| GET | `/api/projects` | | folders for a project picker |
| GET | `/api/targets` | | every target with vendor, model and tier |
| POST | `/api/decide` | `{prompt, cwd}` | the decision: `id`, `target`, `answers`, `alternatives` |
| POST | `/api/pick` | `{id, target}` | records choosing another target |
| POST | `/api/run` | `{id, target?, mode}` | `mode: "oneshot"` streams text; `"terminal"` opens a window |
| POST | `/api/rate` | `{id, verdict, should?}` | records `good` or `bad` |

Every `/api` call needs the header `X-Trivium-Token` with the value from `ask token`, and POST bodies
must be `application/json`. The server only answers on 127.0.0.1 or localhost, and refuses browser
requests from other sites unless their origin is listed in `router.allowed_origins`. That matters,
because `/api/run` starts `claude` and `codex`: keep the token private, and only list origins you
control. The dashboard page itself cannot be framed by another site.
