"""ask: route a prompt to local Qwen, Claude Code or Codex.

  ask "fix the flaky auth test"      route, then open an interactive session
  ask -p "what does EPERM mean"      one-shot: print the answer and exit
  ask --to opus "..."                skip the router (still logged as a label)
  ask --via codex "..."              route, then use the Codex model of the same tier
  ask why "..."                      show the decision without running anything
  ask serve                          keep the router model warm (recommended)
  ask rate good|bad [--should T]     label the last decision
  ask eval evals/prompts.jsonl       measure router accuracy on labelled prompts
  ask targets                        list targets and the config in use
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import config, launch, log, policy, state
from .server import Remote

SUBCOMMANDS = {"why", "serve", "rate", "eval", "targets"}


def load_engine(cfg: dict, name: str):
    if name == "laya":
        from .laya_engine import LayaEngine

        return LayaEngine(cfg["router"])
    from .engine import Engine

    return Engine(cfg["router"])


def backend(cfg: dict, name: str | None = None):
    """The warm server if it is up and no specific backend was asked for, else load in-process."""
    name = name or cfg["router"].get("backend", "semif")
    if name == cfg["router"].get("backend", "semif"):
        remote = Remote(cfg["router"]["port"])
        if remote.alive():
            return remote
    print(f"trivium: loading the {name} router in-process (run `ask serve` to keep it warm)", file=sys.stderr)
    return load_engine(cfg, name)


def route(cfg: dict, engine, prompt: str, repo: str | None) -> tuple[policy.Decision, float]:
    evidence = state.build(prompt, repo, cfg["router"]["max_prompt_chars"])
    started = time.perf_counter()
    probs, _ = engine.route(evidence, cfg["questions"])
    elapsed = time.perf_counter() - started
    return policy.decide(cfg, policy.summarize(probs)), elapsed


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


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ask", description="Route a prompt to the right model.")
    parser.add_argument("prompt", nargs="*")
    parser.add_argument("-p", "--print", dest="one_shot", action="store_true", help="one-shot, non-interactive")
    parser.add_argument("--to", help="skip routing: target name, short name (opus, sol) or model id")
    parser.add_argument("--via", choices=["claude", "codex"], help="keep the routed tier, use this vendor")
    parser.add_argument("--no-local", action="store_true", help="never answer with the local model")
    parser.add_argument("--dry", action="store_true", help="decide and print, but do not run")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    prompt = " ".join(args.prompt).strip()
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
    if not prompt:
        parser.error("no prompt given")

    cfg = config.load()
    cwd = os.getcwd()
    repo = state.repo_name(cwd)
    engine, elapsed = None, None

    if args.to:
        decision = policy.Decision(policy.resolve_to(cfg, args.to), "manual --to")
    else:
        engine = backend(cfg)
        decision, elapsed = route(cfg, engine, prompt, repo)
    routed = decision.target
    if args.via:
        decision.target = policy.via(cfg, decision.target, args.via)
    # Laya only decides, so with that backend there is nothing local to answer with.
    no_local = args.no_local or cfg["router"].get("backend", "semif") == "laya"
    if no_local and cfg["targets"][decision.target]["vendor"] == "local":
        decision.target = policy.via(cfg, decision.target, "claude")

    print(describe(cfg, decision, elapsed, args.verbose or args.dry), file=sys.stderr)
    log.append({
        "type": "decision", "prompt": prompt, "cwd": cwd, "repo": repo,
        "answers": decision.answers, "routed": routed, "target": decision.target,
        "reason": decision.reason, "via": args.via, "manual": bool(args.to),
        "one_shot": args.one_shot, "route_ms": elapsed and round(elapsed * 1000, 1),
    })
    if args.dry:
        return 0

    target = cfg["targets"][decision.target]
    if target["vendor"] == "local":
        engine = engine or backend(cfg)
        for text in engine.generate(prompt):
            sys.stdout.write(text)
            sys.stdout.flush()
        sys.stdout.write("\n")
        return 0
    cmd = launch.argv(target, prompt, one_shot=args.one_shot)
    try:
        os.execvp(cmd[0], cmd)
    except FileNotFoundError:
        print(f"trivium: `{cmd[0]}` is not on PATH", file=sys.stderr)
        return 127


def cmd_serve(argv: list[str]) -> int:
    from .server import serve

    cfg = config.load()
    engine = load_engine(cfg, cfg["router"].get("backend", "semif"))
    # Warm up: the first call at a new shape compiles kernels.
    engine.route(state.build("warm up", None, 100), cfg["questions"])
    serve(engine, cfg["router"]["port"])
    return 0


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


def cmd_eval(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ask eval")
    parser.add_argument("file")
    parser.add_argument("--show-misses", action="store_true")
    parser.add_argument("--backend", choices=["semif", "laya"], help="router to evaluate (default: config)")
    args = parser.parse_args(argv)
    cfg = config.load()
    engine = backend(cfg, args.backend)
    rows = [json.loads(line) for line in open(args.file) if line.strip()]
    hits = {q: 0 for q in cfg["questions"]}
    targets_hit, unsure, times, misses = 0, 0, [], []
    for row in rows:
        decision, elapsed = route(cfg, engine, row["prompt"], row.get("repo"))
        times.append(elapsed)
        expected = policy.decide(cfg, {q: {"choice": c, "p": 1.0} for q, c in row["expect"].items()})
        unsure += bool(decision.unsure)
        targets_hit += decision.target == expected.target
        wrong = {}
        for q, want in row["expect"].items():
            got = decision.answers[q]["choice"]
            hits[q] += got == want
            if got != want:
                wrong[q] = f"{got}@{decision.answers[q]['p']:.2f} (want {want})"
        if wrong or decision.target != expected.target:
            misses.append((row["prompt"], decision.target, expected.target, wrong))
    n = len(rows)
    print(f"{n} prompts · router {engine.metadata['source'] if hasattr(engine, 'metadata') else cfg['router']['model']}")
    for q, h in hits.items():
        print(f"  {q:<11} {h / n:6.1%}")
    print(f"  {'target':<11} {targets_hit / n:6.1%}   (same target as the labels would route to)")
    print(f"  {'unsure':<11} {unsure / n:6.1%}   (sent to fallback {cfg['fallback']})")
    times.sort()
    print(f"  latency     p50 {times[n // 2] * 1000:.0f} ms · p90 {times[int(n * 0.9)] * 1000:.0f} ms")
    if args.show_misses:
        for prompt, got, want, wrong in misses:
            print(f"\n- {prompt[:90]!r}\n  routed {got}, labels say {want}  {wrong or ''}")
    return 0


def cmd_targets(argv: list[str]) -> int:
    cfg = config.load()
    print(f"config: {config.config_path()}")
    for name, t in cfg["targets"].items():
        effort = f" effort={t['effort']}" if t.get("effort") else ""
        print(f"  {name:<16} {t['vendor']:<7} {t['tier']:<9} {t['model']}{effort}")
    return 0


def main() -> None:
    argv = sys.argv[1:]
    commands = {"why": lambda a: run(["--dry", *a]), "serve": cmd_serve, "rate": cmd_rate,
                "eval": cmd_eval, "targets": cmd_targets}
    if argv and argv[0] in SUBCOMMANDS:
        sys.exit(commands[argv[0]](argv[1:]))
    sys.exit(run(argv))
