"""Load and validate targets.yaml."""

from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path

import yaml

USER_CONFIG = Path.home() / ".config" / "trivium" / "targets.yaml"
VENDORS = {"local", "claude", "codex"}


def config_path() -> Path:
    if env := os.environ.get("TRIVIUM_CONFIG"):
        return Path(env).expanduser()
    if USER_CONFIG.exists():
        return USER_CONFIG
    return Path(str(files("trivium") / "targets.yaml"))


def load(path: Path | None = None) -> dict:
    cfg = yaml.safe_load((path or config_path()).read_text())
    validate(cfg)
    return cfg


def validate(cfg: dict) -> None:
    questions, targets = cfg["questions"], cfg["targets"]
    for qid, q in questions.items():
        if not 2 <= len(q["options"]) <= 16:
            raise ValueError(f"question {qid}: needs 2-16 options (semif limit)")
    for name, t in targets.items():
        if t.get("vendor") not in VENDORS:
            raise ValueError(f"target {name}: vendor must be one of {sorted(VENDORS)}")
        if not t.get("model") or not t.get("tier"):
            raise ValueError(f"target {name}: needs model and tier")
    for key in ("default", "fallback"):
        if cfg[key] not in targets:
            raise ValueError(f"{key}: unknown target {cfg[key]!r}")
    for i, rule in enumerate(cfg["rules"]):
        if rule["to"] not in targets:
            raise ValueError(f"rule {i}: unknown target {rule['to']!r}")
        for qid, want in rule["when"].items():
            if qid not in questions:
                raise ValueError(f"rule {i}: unknown question {qid!r}")
            for option in want if isinstance(want, list) else [want]:
                if option not in questions[qid]["options"]:
                    raise ValueError(f"rule {i}: {qid} has no option {option!r}")
    for qid in cfg.get("min_confidence", {}):
        if qid not in questions:
            raise ValueError(f"min_confidence: unknown question {qid!r}")
