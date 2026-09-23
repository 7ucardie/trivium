"""Build the router's evidence: the request, front-loaded, plus context stated in words."""

from __future__ import annotations

import subprocess
from pathlib import Path


def repo_name(cwd: str) -> str | None:
    try:
        top = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return Path(top.stdout.strip()).name if top.returncode == 0 else None


def clip(text: str, limit: int) -> str:
    """Keep the head (where intent usually is) and a short tail (where the ask often ends)."""
    text = text.strip()
    if len(text) <= limit:
        return text
    tail = limit // 5
    return f"{text[: limit - tail]}\n[... {len(text) - limit} characters omitted ...]\n{text[-tail:]}"


def build(prompt: str, repo: str | None, limit: int) -> dict:
    where = (
        f"The request was typed inside the code repository '{repo}'."
        if repo else "The request was typed outside any code repository."
    )
    return {"request": clip(prompt, limit), "context": where}
