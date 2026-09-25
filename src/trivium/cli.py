"""ask: route a prompt to local Qwen, Claude Code or Codex.

  trivium                            the terminal app: type prompts, pick, run and rate in one place

  ask "fix the flaky auth test"      route, then open an interactive session
  ask -p "what does EPERM mean"      one-shot: print the answer and exit
  ask --ask "..."                    show the likeliest targets and let me pick
  ask --to opus "..."                skip the router (still logged as a label)
  ask --via codex "..."              route, then use the Codex model of the same tier
  ask why "..."                      show the decision without running anything
  ask why --json "..."               the decision as JSON, for scripts and editors
  ask serve                          keep the router model warm (recommended)
  ask service install|uninstall|status   run `ask serve` at login with launchd
  ask rate good|bad [--should T]     label the last decision
  ask eval evals/prompts.jsonl       measure router accuracy on labelled prompts
  ask calibrate evals/prompts.jsonl  fit per-question temperatures from labelled prompts
  ask export --out mine.jsonl        turn the decision log into labelled prompts to review
  ask targets                        list targets and the config in use
  ask token                          the API token for connecting another dashboard
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import config, launch, log, policy, server, state
from .server import Remote

BACKENDS = ["semif", "laya", "hybrid"]


def backend_name(cfg: dict, name: str | None = None) -> str:
    return name or cfg["router"].get("backend", "semif")


def load_engine(cfg: dict, name: str):
    if name == "laya":
        from .laya_engine import LayaEngine

        return LayaEngine(cfg["router"])
    if name == "hybrid":
        from .hybrid import HybridEngine

        return HybridEngine(cfg["router"])
    from .engine import Engine

    return Engine(cfg["router"])


def backend(cfg: dict, name: str | None = None):
    """The warm server if it is up and runs the backend asked for, else load in-process."""
    name = backend_name(cfg, name)
    remote = Remote(cfg["router"]["port"])
    if remote.alive():
        if remote.backend == name:
            return remote
        # Never apply one backend's calibration to another backend's scores.
        print(f"trivium: the running server uses the {remote.backend} router, not {name}; "
              f"loading {name} in-process (restart `ask serve` to switch it)", file=sys.stderr)
    else:
        print(f"trivium: loading the {name} router in-process (run `ask serve` to keep it warm)", file=sys.stderr)
    return load_engine(cfg, name)


def raw_route(cfg: dict, engine, prompt: str, repo: str | None) -> tuple[dict, float]:
    evidence = state.build(prompt, repo, cfg["router"]["max_prompt_chars"])
    started = time.perf_counter()
    probs, _ = engine.route(evidence, cfg["questions"])
    return probs, time.perf_counter() - started


def route(cfg: dict, engine, prompt: str, repo: str | None, name: str) -> tuple[policy.Decision, float]:
    probs, elapsed = raw_route(cfg, engine, prompt, repo)
    answers = policy.summarize(probs, config.temperatures(cfg, name))
    return policy.decide(cfg, answers), elapsed


def describe(cfg: dict, decision: policy.Decision, elapsed: float | None, verbose: bool) -> str:
    target = cfg["targets"][decision.target]
    labels = "/".join(a["choice"] for a in decision.answers.values())
    timing = f" · {elapsed * 1000:.0f} ms" if elapsed is not None else ""
    line = f"→ {decision.target} ({target['model']}) · {labels or 'manual'}{timing} · {decision.reason}"
    if verbose:
        for qid, a in decision.answers.items():
            ranked = sorted(a["probabilities"].items(), key=lambda kv: -kv[1])
            line += f"\n  {qid:<11}" + "  ".join(f"{o}={p:.2f}" for o, p in ranked)
    return line


def pick(cfg: dict, decision: policy.Decision, tty=None) -> str | None:
    """Show the likeliest targets and read a choice from the terminal. None keeps the decision."""
    options = policy.alternatives(cfg, decision.answers)[:3]
    if tty is None:
        try:
            tty = open("/dev/tty", "r+")
        except OSError:
            return None  # no terminal (a pipe or a script): keep the router's decision
    with tty:
        tty.write("trivium: pick a target\n")
        for i, (name, p) in enumerate(options, 1):
            tty.write(f"  {i}) {name:<16} {cfg['targets'][name]['model']:<20} {p:5.0%}\n")
        tty.write(f"  Enter keeps {decision.target}: ")
        tty.flush()
        answer = tty.readline().strip()
    if answer.isdigit() and 1 <= int(answer) <= len(options):
        return options[int(answer) - 1][0]
    return None


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ask", description="Route a prompt to the right model.")
    parser.add_argument("prompt", nargs="*")
    parser.add_argument("-p", "--print", dest="one_shot", action="store_true", help="one-shot, non-interactive")
    parser.add_argument("--ask", action="store_true", help="show the likeliest targets and let me pick")
    parser.add_argument("--to", help="skip routing: target name, short name (opus, sol) or model id")
    parser.add_argument("--via", choices=["claude", "codex"], help="keep the routed tier, use this vendor")
    parser.add_argument("--no-local", action="store_true", help="never answer with the local model")
    parser.add_argument("--dry", action="store_true", help="decide and print, but do not run")
    parser.add_argument("--json", action="store_true", help="print the decision as JSON on stdout, do not run")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    args.dry = args.dry or args.json

    prompt = " ".join(args.prompt).strip()
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
    if not prompt:
        parser.error("no prompt given")

    cfg = config.load()
    name = backend_name(cfg)
    cwd = os.getcwd()
    repo = state.repo_name(cwd)
    engine, elapsed, picked = None, None, None

    if args.to:
        decision = policy.Decision(policy.resolve_to(cfg, args.to), "manual --to")
    else:
        engine = backend(cfg)
        decision, elapsed = route(cfg, engine, prompt, repo, name)
    routed = decision.target
    ask_now = args.ask or (decision.unsure and cfg["router"].get("ask_when_unsure", False))
    if ask_now and decision.answers and not args.dry:
        print(describe(cfg, decision, elapsed, True), file=sys.stderr)
        picked = pick(cfg, decision)
        if picked:
            decision.target, decision.reason = picked, "picked with --ask"
    if args.via:
        decision.target = policy.via(cfg, decision.target, args.via)
    # Laya and the llama.cpp runtime only decide, so there is nothing local to answer with.
    no_local = args.no_local or not config.answers_locally(cfg)
    if no_local and cfg["targets"][decision.target]["vendor"] == "local":
        decision.target = policy.via(cfg, decision.target, "claude")

    if args.json:
        target = cfg["targets"][decision.target]
        print(json.dumps({
            "target": decision.target, "vendor": target["vendor"], "model": target["model"],
            "effort": target.get("effort"), "reason": decision.reason, "unsure": decision.unsure,
            "routed": routed, "backend": name, "route_ms": elapsed and round(elapsed * 1000, 1),
            "answers": decision.answers,
            "alternatives": policy.alternatives(cfg, decision.answers) if decision.answers else [],
            "command": None if target["vendor"] == "local" else launch.argv(target, prompt, one_shot=args.one_shot),
        }, indent=2))
    else:
        print(describe(cfg, decision, elapsed, args.verbose or args.dry), file=sys.stderr)
    log.append({
        "type": "decision", "prompt": prompt, "cwd": cwd, "repo": repo, "backend": name,
        "answers": decision.answers, "routed": routed, "target": decision.target,
        "reason": decision.reason, "via": args.via, "manual": bool(args.to or picked),
        "one_shot": args.one_shot, "route_ms": elapsed and round(elapsed * 1000, 1),
    })
    if args.dry:
        return 0

    target = cfg["targets"][decision.target]
    if target["vendor"] == "local" or args.one_shot:
        # One-shot answers stream through the CLIs' JSON events, so a model that thinks for a while
        # shows what it is doing instead of printing nothing until it is done.
        from . import repl, session

        router = session.Router(cfg=cfg, engine=engine)
        got = repl.print_events(router.one_shot(decision.target, prompt, cwd))
        return 0 if got else 1
    cmd = launch.argv(target, prompt, one_shot=False)
    try:
        os.execvp(cmd[0], cmd)
    except FileNotFoundError:
        print(f"trivium: `{cmd[0]}` is not on PATH", file=sys.stderr)
        return 127


def cmd_serve(argv: list[str]) -> int:
    from .server import serve

    cfg = config.load()
    name = backend_name(cfg)
    port = cfg["router"]["port"]
    # Check the port before spending seconds on loading a model that could not be served.
    running = Remote(port)
    if running.alive():
        print(f"trivium: a server is already running on port {port} "
              f"(backend {running.backend}, {running.metadata['source']}).\n"
              f"  Stop it first: `ask service uninstall` if it runs as a service, otherwise "
              f"`kill $(lsof -tiTCP:{port} -sTCP:LISTEN)`.", file=sys.stderr)
        return 1
    if not server.port_free(port):
        print(f"trivium: port {port} is in use by another program; set router.port to a free port.",
              file=sys.stderr)
        return 1
    engine = load_engine(cfg, name)
    # Warm up: the first call at a new shape compiles kernels.
    engine.route(state.build("warm up", None, 100), cfg["questions"])
    serve(engine, cfg["router"]["port"], name)
    return 0


def cmd_service(argv: list[str]) -> int:
    from . import service

    parser = argparse.ArgumentParser(prog="ask service")
    parser.add_argument("action", choices=["install", "uninstall", "status"])
    action = parser.parse_args(argv).action
    return {"install": service.install, "uninstall": service.uninstall, "status": service.status}[action]()


def cmd_rate(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ask rate")
    parser.add_argument("verdict", choices=["good", "bad"])
    parser.add_argument("--should", help="the target it should have gone to")
    parser.add_argument("--note")
    args = parser.parse_args(argv)
    last = log.last_decision()
    if not last:
        print("trivium: nothing to rate yet", file=sys.stderr)
        return 1
    should = policy.resolve_to(config.load(), args.should) if args.should else None
    log.append({"type": "feedback", "decision": last["id"], "verdict": args.verdict,
                "should": should, "note": args.note})
    print(f"trivium: rated {last['target']} as {args.verdict}" + (f", should be {should}" if should else ""),
          file=sys.stderr)
    return 0


def _labelled(path: str, split: str | None = None) -> list[dict]:
    """Labelled prompts; with split, only rows whose "split" field matches (e.g. train or test)."""
    rows = [json.loads(line) for line in open(path) if line.strip()]
    if split:
        rows = [r for r in rows if r.get("split") == split]
        if not rows:
            raise SystemExit(f"trivium: no rows with split={split!r} in {path}")
    return rows


def cmd_eval(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ask eval")
    parser.add_argument("file")
    parser.add_argument("--show-misses", action="store_true")
    parser.add_argument("--sweep", action="store_true",
                        help="also show right target and fallback rate for a range of confidence floors")
    parser.add_argument("--backend", choices=BACKENDS, help="router to evaluate (default: config)")
    parser.add_argument("--split", help="only rows with this split field, e.g. test")
    args = parser.parse_args(argv)
    cfg = config.load()
    name = backend_name(cfg, args.backend)
    engine = backend(cfg, name)
    rows = _labelled(args.file, args.split)
    temps = config.temperatures(cfg, name)
    scored = []  # route every prompt once; thresholds are applied afterwards
    for row in rows:
        probs, elapsed = raw_route(cfg, engine, row["prompt"], row.get("repo"))
        expected = policy.decide(cfg, {q: {"choice": c, "p": 1.0} for q, c in row["expect"].items()}).target
        scored.append((row, policy.summarize(probs, temps), expected, elapsed))
    hits = {q: 0 for q in cfg["questions"]}
    targets_hit, unsure, misses = 0, 0, []
    for row, answers, expected, _ in scored:
        decision = policy.decide(cfg, answers)
        unsure += bool(decision.unsure)
        targets_hit += decision.target == expected
        wrong = {}
        for q, want in row["expect"].items():
            got = answers[q]["choice"]
            hits[q] += got == want
            if got != want:
                wrong[q] = f"{got}@{answers[q]['p']:.2f} (want {want})"
        if wrong or decision.target != expected:
            misses.append((row["prompt"], decision.target, expected, wrong))
    n = len(rows)
    times = sorted(t for *_, t in scored)
    print(f"{n} prompts{f' ({args.split})' if args.split else ''} · router {engine.metadata['source']}"
          + (" · calibrated" if temps else ""))
    for q, h in hits.items():
        print(f"  {q:<11} {h / n:6.1%}")
    print(f"  {'target':<11} {targets_hit / n:6.1%}   (same target as the labels would route to)")
    print(f"  {'unsure':<11} {unsure / n:6.1%}   (sent to fallback {cfg['fallback']})")
    print(f"  latency     p50 {times[n // 2] * 1000:.0f} ms · p90 {times[int(n * 0.9)] * 1000:.0f} ms")
    if args.sweep:
        print(f"\n  one floor for every question (your config: {cfg.get('min_confidence', {})})")
        print(f"  {'floor':>5}  {'right target':>12}  {'fallback':>8}  {'right when routed':>17}")
        for floor, right, fell, precise in sweep(cfg, scored):
            print(f"  {floor:5.2f}  {right:12.1%}  {fell:8.1%}  {precise:17.1%}")
    if args.show_misses:
        for prompt, got, want, wrong in misses:
            print(f"\n- {prompt[:90]!r}\n  routed {got}, labels say {want}  {wrong or ''}")
    return 0


FLOORS = [0.0, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.8, 0.9]


def sweep(cfg: dict, scored: list) -> list[tuple[float, float, float, float]]:
    """(floor, right target, fallback rate, right target among prompts that were not sent to fallback)."""
    out = []
    for floor in FLOORS:
        at_floor = {**cfg, "min_confidence": {q: floor for q in cfg["questions"]}}
        right = fell = routed_right = 0
        for _, answers, expected, _ in scored:
            decision = policy.decide(at_floor, answers)
            right += decision.target == expected
            if decision.unsure:
                fell += 1
            else:
                routed_right += decision.target == expected
        n = len(scored)
        out.append((floor, right / n, fell / n, routed_right / (n - fell) if n > fell else 0.0))
    return out


def cmd_calibrate(argv: list[str]) -> int:
    from . import calibrate

    parser = argparse.ArgumentParser(prog="ask calibrate")
    parser.add_argument("file", help="labelled prompts, same format as ask eval")
    parser.add_argument("--backend", choices=BACKENDS, help="router to calibrate (default: config)")
    parser.add_argument("--write", action="store_true",
                        help=f"save the temperatures to {config.calibration_path()} instead of printing a block")
    parser.add_argument("--split", help="only rows with this split field, e.g. train")
    args = parser.parse_args(argv)
    cfg = config.load()
    name = backend_name(cfg, args.backend)
    engine = backend(cfg, name)
    rows = _labelled(args.file, args.split)
    samples: dict[str, list] = {q: [] for q in cfg["questions"]}
    for row in rows:
        probs, _ = raw_route(cfg, engine, row["prompt"], row.get("repo"))
        for q, truth in row["expect"].items():
            samples[q].append((probs[q], truth))
    print(f"{len(rows)} prompts · router {engine.metadata['source']}")
    print(f"  {'question':<11} {'T':>6}  {'NLL before':>10} {'after':>6}  {'ECE before':>10} {'after':>6}")
    fitted = {}
    for q, s in samples.items():
        t = calibrate.fit(s)
        fitted[q] = t
        edge = "  (at the grid edge: needs more labelled data)" if calibrate.at_edge(t) else ""
        print(f"  {q:<11} {t:6.2f}  {calibrate.nll(s, 1.0):10.3f} {calibrate.nll(s, t):6.3f}"
              f"  {calibrate.ece(s, 1.0):10.3f} {calibrate.ece(s, t):6.3f}{edge}")
    if args.write:
        path = config.write_calibration(name, fitted)
        print(f"\nSaved to {path}; it overrides calibration.{name} in {config.config_path()}.")
        print("Re-check your min_confidence values with `ask eval --sweep`: they are read on the new scale.")
    else:
        print(f"\nAdd to your targets.yaml ({config.config_path()}), or re-run with --write:\n\ncalibration:\n  {name}:")
        for q, t in fitted.items():
            print(f"    {q}: {t}")
    if len(rows) < 200:
        print(f"\nOnly {len(rows)} labelled prompts: treat these temperatures as a rough start, "
              "and re-fit once you have a few hundred.", file=sys.stderr)
    return 0


def cmd_export(argv: list[str]) -> int:
    from . import export

    parser = argparse.ArgumentParser(prog="ask export", description="Decision log -> labelled prompts.")
    parser.add_argument("--out", required=True, help="JSONL file for ask eval / ask calibrate")
    parser.add_argument("--only-rated", action="store_true", help="only decisions rated or picked with --ask")
    parser.add_argument("--since", help="only decisions on or after this day (YYYY-MM-DD, UTC)")
    args = parser.parse_args(argv)
    cfg = config.load()
    if not log.LOG.exists():
        print(f"trivium: no decision log at {log.LOG}", file=sys.stderr)
        return 1
    records = [json.loads(line) for line in log.LOG.read_text().splitlines() if line.strip()]
    since = export.since_timestamp(args.since) if args.since else None
    rows, skipped = export.rows_from_log(records, cfg, args.only_rated, since)
    export.write(rows, args.out)
    review = sum(r["needs_review"] for r in rows)
    kinds = {k: sum(r["label"] == k for r in rows) for k in ("confirmed-target", "inferred-from-feedback", "router")}
    print(f"trivium: wrote {len(rows)} prompts to {args.out} ({review} need review)", file=sys.stderr)
    print("  labels: " + ", ".join(f"{k} {v}" for k, v in kinds.items()), file=sys.stderr)
    if any(skipped.values()):
        print("  skipped: " + ", ".join(f"{k} {v}" for k, v in skipped.items() if v), file=sys.stderr)
    print("  check the rows with needs_review before using the file for ask eval or ask calibrate",
          file=sys.stderr)
    return 0


def cmd_token(argv: list[str]) -> int:
    """Print the API token, for connecting another dashboard or script to `ask serve`."""
    from . import security

    print(security.token())
    print(f"(stored in {security.token_path()}; send it as {security.TOKEN_HEADER})", file=sys.stderr)
    return 0


def cmd_targets(argv: list[str]) -> int:
    cfg = config.load()
    print(f"config: {config.config_path()} · backend: {backend_name(cfg)} · "
          f"runtime: {cfg['router'].get('runtime', 'mlx')}")
    for name, t in cfg["targets"].items():
        effort = f" effort={t['effort']}" if t.get("effort") else ""
        print(f"  {name:<16} {t['vendor']:<7} {t['tier']:<9} {t['model']}{effort}")
    return 0


COMMANDS = {
    "why": lambda a: run(["--dry", *a]),
    "serve": cmd_serve,
    "service": cmd_service,
    "rate": cmd_rate,
    "eval": cmd_eval,
    "calibrate": cmd_calibrate,
    "export": cmd_export,
    "targets": cmd_targets,
    "token": cmd_token,
}


def main() -> None:
    argv = sys.argv[1:]
    if not argv and sys.stdin.isatty():
        # `trivium` or `ask` on its own opens the terminal app.
        from . import repl

        sys.exit(repl.main())
    if argv and argv[0] in COMMANDS:
        sys.exit(COMMANDS[argv[0]](argv[1:]))
    sys.exit(run(argv))
