"""Build the command line for a Claude Code or Codex target."""

from __future__ import annotations


def argv(target: dict, prompt: str, *, one_shot: bool) -> list[str]:
    vendor, model, effort = target["vendor"], target["model"], target.get("effort")
    if vendor == "claude":
        cmd = ["claude", "--model", model]
        if effort:
            cmd += ["--effort", effort]
        if one_shot:
            cmd.append("-p")
        return cmd + [prompt]
    if vendor == "codex":
        cmd = ["codex", "exec"] if one_shot else ["codex"]
        cmd += ["-m", model]
        if effort:
            cmd += ["-c", f'model_reasoning_effort="{effort}"']
        return cmd + [prompt]
    raise ValueError(f"{vendor} targets are not launched as a CLI")
