"""The terminal app: `trivium` (or `ask` with no arguments) stays open like the claude and codex CLIs.

Type a prompt, see where it would go, press Enter to open that tool here, and come back when the
session ends. Claude Code and Codex stay the harness; this only decides and hands off.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import log, session

MAIN_TARGETS = ["local", "claude-haiku", "claude-sonnet", "claude-opus", "claude-fable",
                "codex-luna", "codex-sol", "codex-astra"]

HELP = """  Type a prompt and press Enter to route it. Then:
    Enter   open the chosen tool here (or answer locally)
    1-4     choose another target        p   one-shot answer, printed here
    e       edit the prompt              x   drop it
  Commands: /cd DIR   /help   /quit (or Ctrl-D)
"""


def _color(code: str, text: str) -> str:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def dim(t: str) -> str: return _color("2", t)
def bold(t: str) -> str: return _color("1", t)
def accent(t: str) -> str: return _color("36;1", t)
def warn(t: str) -> str: return _color("33", t)


def read_key() -> str:
    """One keypress without Enter. Returns '\\n' for Enter and 'esc' for Escape."""
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return {"\r": "\n", "\x1b": "esc", "\x04": "x"}.get(ch, ch)


def read_line(prompt: str, prefill: str = "") -> str:
    try:
        import readline

        readline.set_startup_hook(lambda: readline.insert_text(prefill))
        try:
            return input(prompt)
        finally:
            readline.set_startup_hook(None)
    except ImportError:
        return input(prompt)


def run_interactive(cmd: list[str], cwd: str) -> int:
    """Run claude or codex in this terminal and wait; the TTY is inherited, so it behaves as usual."""
    try:
        return subprocess.run(cmd, cwd=cwd).returncode
    except FileNotFoundError:
        print(warn(f"  `{cmd[0]}` is not on PATH"))
        return 127
    except KeyboardInterrupt:
        return 130


def print_events(events, write=None) -> bool:
    """Print (kind, text) events: answer text as it arrives, status on one updating line, errors in
    colour. Returns whether any answer text arrived."""
    import time

    write = write or sys.stdout.write
    tty = sys.stdout.isatty()
    started, got_text, status_shown = time.monotonic(), False, False
    for kind, text in events:
        if kind == "status":
            if got_text:
                continue
            line = dim(f"  … {text} ({time.monotonic() - started:.0f}s)")
            write(("\r\033[K" if tty and status_shown else ("" if not status_shown else "\n")) + line)
            status_shown = True
        elif kind == "text":
            if not got_text and status_shown:
                write("\r\033[K" if tty else "\n")
            got_text = True
            write(text)
        elif kind == "error":
            write(("\n" if got_text or status_shown else "") + warn(f"  {text}") + "\n")
        sys.stdout.flush()
    if status_shown and not got_text:
        write("\n")
    if got_text:
        write("\n")
    return got_text


class App:
    def __init__(self, router: session.Router, cwd: str, key=read_key, line=read_line, run=run_interactive,
                 out=print):
        self.router, self.cwd = router, str(Path(cwd).resolve())
        self.key, self.line, self.run, self.out = key, line, run, out

    # --- screen -------------------------------------------------------------------------------------

    def banner(self) -> None:
        repo = session.state.repo_name(self.cwd)
        where = f"{self.cwd}" + (f" ({repo})" if repo else "")
        self.out(bold("trivium") + dim(f" · {where} · {self.router.name} · /help for keys"))

    def show(self, d: dict, current: str) -> None:
        answers = " · ".join(a["choice"] for a in d["answers"].values())
        t = self.router.target_info(current)
        note = warn(" unsure: " + ", ".join(d["unsure"])) if d["unsure"] else ""
        self.out(f"  → {accent(current)}  {t['model']}  {dim(answers)}  {dim(str(round(d['route_ms'])) + ' ms')}{note}")
        choices = "   ".join(
            (accent if a["name"] == current else str)(f"{i} {a['name']} {a['p']:.0%}")
            for i, a in enumerate(d["alternatives"], 1)
        )
        self.out(f"    {choices}")
        action = "answer locally" if t["vendor"] == "local" else f"open {'Claude Code' if t['vendor'] == 'claude' else 'Codex'}"
        self.out(dim(f"    enter {action} · 1-{len(d['alternatives'])} pick · p one-shot · e edit · x drop"))

    # --- flow ---------------------------------------------------------------------------------------

    def loop(self) -> int:
        self.banner()
        prefill = ""
        while True:
            try:
                text = self.line("› ", prefill).strip()
            except (EOFError, KeyboardInterrupt):
                self.out("")
                return 0
            prefill = ""
            if not text:
                continue
            if text.startswith("/"):
                if self.command(text) == "quit":
                    return 0
                continue
            try:
                d = self.router.decide(text, self.cwd)
            except (ValueError, RuntimeError) as error:
                self.out(warn(f"  {error}"))
                continue
            prefill = self.act(d)

    def command(self, text: str) -> str | None:
        name, _, arg = text.partition(" ")
        if name in ("/quit", "/exit", "/q"):
            return "quit"
        if name == "/help":
            self.out(HELP)
        elif name == "/cd":
            target = Path(arg.strip() or "~").expanduser()
            target = target if target.is_absolute() else Path(self.cwd) / target
            if target.is_dir():
                self.cwd = str(target.resolve())
                self.banner()
            else:
                self.out(warn(f"  not a directory: {target}"))
        else:
            self.out(warn(f"  unknown command {name}; /help lists them"))
        return None

    def act(self, d: dict) -> str:
        """Handle the keys after a decision. Returns text to prefill the next prompt with (for `e`)."""
        current = d["target"]["name"]
        self.show(d, current)
        while True:
            k = self.key()
            if k.isdigit() and 1 <= int(k) <= len(d["alternatives"]):
                chosen = d["alternatives"][int(k) - 1]["name"]
                if chosen != current:
                    current = chosen
                    if chosen != d["target"]["name"]:
                        self.router.pick(d["id"], chosen)
                self.show(d, current)
            elif k == "e":
                return d["prompt"]
            elif k in ("x", "esc", "q"):
                self.out(dim("  dropped"))
                return ""
            elif k in ("\n", "p"):
                self.execute(d, current, one_shot=(k == "p"))
                self.ask_rating(d)
                return ""

    def execute(self, d: dict, target: str, one_shot: bool) -> None:
        cmd = self.router.command(target, d["prompt"], one_shot=False)
        if cmd is None or one_shot:
            print_events(self.router.one_shot(target, d["prompt"], self.cwd))
            return
        self.out(dim(f"  $ {' '.join(cmd[:3])} …  (exit it to come back to trivium)"))
        code = self.run(cmd, self.cwd)
        self.out(dim(f"  back in trivium ({cmd[0]} exited {code})"))

    def ask_rating(self, d: dict) -> None:
        self.out(dim("  was that the right model?  g good · b bad · enter skip"))
        k = self.key()
        if k == "g":
            self.router.rate(d["id"], "good")
            self.out(dim("  rated good"))
        elif k == "b":
            options = [t for t in MAIN_TARGETS if t in self.router.cfg["targets"]
                       and (t != "local" or self.router.local_ok())]
            self.out(dim("  which should it have been?  ") + "  ".join(f"{i} {t}" for i, t in enumerate(options, 1))
                     + dim("  enter: not sure"))
            k2 = self.key()
            should = options[int(k2) - 1] if k2.isdigit() and 1 <= int(k2) <= len(options) else None
            self.router.rate(d["id"], "bad", should)
            self.out(dim(f"  rated bad" + (f", should be {should}" if should else "")))


def main(cwd: str | None = None) -> int:
    router = session.Router()
    app = App(router, cwd or os.getcwd())
    history = log.LOG.parent / "history"
    try:
        import readline

        history.parent.mkdir(parents=True, exist_ok=True)
        if history.exists():
            readline.read_history_file(history)
        readline.set_history_length(1000)
    except (ImportError, OSError):
        readline = None
    try:
        # Load the router before the first prompt so the first decision is not the slow one.
        router.engine
        return app.loop()
    finally:
        if readline:
            try:
                readline.write_history_file(history)
            except OSError:
                pass
