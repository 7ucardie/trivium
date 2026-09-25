"""The router as a service: decide, choose, run and rate. Shared by the terminal app and the dashboard.

The one-shot `ask` command keeps its own flow in cli.py; this module is for front ends that stay open
and talk about one decision at a time by its id.
"""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
import time
from pathlib import Path

from . import cli, config, launch, log, policy, state, status, stream

LAUNCH_DIR = log.LOG.parent / "launch"


class Router:
    def __init__(self, cfg: dict | None = None, engine=None):
        self.cfg = cfg or config.load()
        self.name = cli.backend_name(self.cfg)
        self._engine = engine

    @property
    def engine(self):
        if self._engine is None:
            self._engine = cli.backend(self.cfg)
        return self._engine

    def local_ok(self) -> bool:
        return config.answers_locally(self.cfg)

    def target_info(self, name: str) -> dict:
        t = self.cfg["targets"][name]
        return {"name": name, "vendor": t["vendor"], "model": t["model"], "tier": t["tier"],
                "effort": t.get("effort")}

    def decide(self, prompt: str, cwd: str) -> dict:
        """Route a prompt, log the decision, and return it with the likeliest alternatives."""
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("empty prompt")
        cwd = str(Path(cwd).expanduser().resolve())
        if not Path(cwd).is_dir():
            raise ValueError(f"not a directory: {cwd}")
        repo = state.repo_name(cwd)
        decision, elapsed = cli.route(self.cfg, self.engine, prompt, repo, self.name)
        routed = decision.target
        if not self.local_ok() and self.cfg["targets"][decision.target]["vendor"] == "local":
            decision.target = policy.via(self.cfg, decision.target, "claude")
        alternatives = []
        for name, p in policy.alternatives(self.cfg, decision.answers):
            if not self.local_ok() and self.cfg["targets"][name]["vendor"] == "local":
                name = policy.via(self.cfg, name, "claude")
            if name not in [a["name"] for a in alternatives]:
                alternatives.append({**self.target_info(name), "p": round(p, 4)})
        decision_id = log.append({
            "type": "decision", "prompt": prompt, "cwd": cwd, "repo": repo, "backend": self.name,
            "answers": decision.answers, "routed": routed, "target": decision.target,
            "reason": decision.reason, "via": None, "manual": False, "one_shot": False,
            "route_ms": round(elapsed * 1000, 1),
        })
        return {
            "id": decision_id, "prompt": prompt, "cwd": cwd, "repo": repo, "routed": routed,
            "target": self.target_info(decision.target), "reason": decision.reason,
            "unsure": decision.unsure, "answers": decision.answers,
            "alternatives": alternatives[:4], "route_ms": round(elapsed * 1000, 1),
        }

    def pick(self, decision_id: str, target: str) -> dict:
        """Record that a different target than the router's was chosen for this decision."""
        name = policy.resolve_to(self.cfg, target)
        log.append({"type": "pick", "decision": decision_id, "target": name})
        return self.target_info(name)

    def rate(self, decision_id: str, verdict: str, should: str | None = None) -> None:
        if verdict not in ("good", "bad"):
            raise ValueError("verdict must be good or bad")
        should = policy.resolve_to(self.cfg, should) if should else None
        log.append({"type": "feedback", "decision": decision_id, "verdict": verdict, "should": should})

    def command(self, target: str, prompt: str, one_shot: bool) -> list[str] | None:
        """The CLI command for a target, or None for the local model."""
        info = self.cfg["targets"][target]
        return None if info["vendor"] == "local" else launch.argv(info, prompt, one_shot=one_shot)

    def one_shot(self, target: str, prompt: str, cwd: str):
        """Yield (kind, text) events for a one-shot answer: "text", "status" or "error" (see stream.py)."""
        info = self.cfg["targets"][target]
        if info["vendor"] == "local":
            yield "status", "answering with the local model"
            for chunk in self.engine.generate(prompt):
                yield "text", chunk
            return
        cmd = launch.argv(info, prompt, one_shot=True, stream=True)
        parse = stream.claude_events if info["vendor"] == "claude" else stream.codex_events
        yield "status", f"starting {cmd[0]} ({info['model']})"
        errored = False
        try:
            with subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, bufsize=1) as proc:
                for kind, text in parse(proc.stdout):
                    errored = errored or kind == "error"
                    yield kind, text
                code = proc.wait()
        except FileNotFoundError:
            yield "error", f"`{cmd[0]}` is not on PATH"
            return
        if code and not errored:
            yield "error", f"{cmd[0]} exited with code {code}"

    def open_in_terminal(self, target: str, prompt: str, cwd: str) -> Path:
        """Open a new terminal window running the interactive CLI for this target in cwd (macOS)."""
        cmd = self.command(target, prompt, one_shot=False)
        if cmd is None:
            raise ValueError("the local model has no interactive session; use a one-shot answer")
        script = launch_script(cmd, cwd)
        app = self.cfg["router"].get("terminal_app", "Terminal")
        subprocess.run(["open", "-a", app, str(script)], check=True)
        return script


def launch_script(cmd: list[str], cwd: str) -> Path:
    """A .command file that cds into the project and runs the CLI; every argument is shell-quoted."""
    LAUNCH_DIR.mkdir(parents=True, exist_ok=True)
    path = LAUNCH_DIR / f"{int(time.time() * 1000)}.command"
    path.write_text(
        "#!/bin/bash\n"
        f"cd {shlex.quote(cwd)} || exit 1\n"
        f"rm -f {shlex.quote(str(path))}\n"  # one use only; the command line holds the prompt
        f"exec {shlex.join(cmd)}\n"
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def recent_projects(limit: int = 12) -> list[str]:
    """Directories from the config's `projects` list, then the most recent ones in the log."""
    cfg = config.load()
    seen: list[str] = []
    for p in cfg.get("projects") or []:
        p = str(Path(p).expanduser())
        if Path(p).is_dir() and p not in seen:
            seen.append(p)
    for d in status.recent_decisions(log.LOG, 200):
        cwd = d.get("cwd")
        if cwd and cwd not in seen and Path(cwd).is_dir() and not cwd.startswith(("/tmp", "/private/")):
            seen.append(cwd)
    home = os.path.expanduser("~")
    if home not in seen:
        seen.append(home)
    return seen[:limit]
