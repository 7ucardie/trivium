"""Build the command line for a Claude Code or Codex target."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

WINDOWS = os.name == "nt"


def resolve(cmd: list[str]) -> list[str]:
    """Windows only: make the command startable. CreateProcess finds only .exe files, and npm installs
    CLIs such as codex as .cmd shims. Run the shim's node script directly instead of the shim: a prompt
    passed through cmd.exe could inject commands."""
    if not WINDOWS:
        return cmd
    found = shutil.which(cmd[0])
    if not found:
        return cmd
    if found.lower().endswith(".exe"):
        return [found, *cmd[1:]]
    script = re.search(r'"%dp0%\\(node_modules\\[^"]+\.js)"', Path(found).read_text(errors="ignore"))
    node = shutil.which("node")
    if script and node:
        return [node, str(Path(found).parent / script.group(1)), *cmd[1:]]
    return cmd  # an unknown kind of shim: let the caller report it as not startable


def argv(target: dict, prompt: str, *, one_shot: bool, stream: bool = False) -> list[str]:
    """stream=True (one-shot only) asks for the CLIs' JSON event streams; see stream.py."""
    from .stream import claude_flags

    vendor, model, effort = target["vendor"], target["model"], target.get("effort")
    if vendor == "claude":
        cmd = ["claude", "--model", model]
        if effort:
            cmd += ["--effort", effort]
        if one_shot:
            cmd.append("-p")
            if stream:
                cmd += claude_flags()
        return cmd + [prompt]
    if vendor == "codex":
        cmd = ["codex", "exec"] if one_shot else ["codex"]
        if one_shot and stream:
            cmd.append("--json")
        cmd += ["-m", model]
        if effort:
            cmd += ["-c", f'model_reasoning_effort="{effort}"']
        return cmd + [prompt]
    raise ValueError(f"{vendor} targets are not launched as a CLI")
