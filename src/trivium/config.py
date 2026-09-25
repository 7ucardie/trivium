"""Load and validate targets.yaml."""

from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path

import yaml

USER_CONFIG = Path.home() / ".config" / "trivium" / "targets.yaml"
VENDORS = {"local", "claude", "codex"}
BACKENDS = ["semif", "laya", "hybrid"]
RUNTIMES = ["mlx", "torch", "llamacpp"]


def answers_locally(cfg: dict) -> bool:
    """Whether local targets can be answered: Laya only decides, and so does the llama.cpp runtime."""
    router = cfg["router"]
    return router.get("backend", "semif") != "laya" and router.get("runtime", "mlx") != "llamacpp"


def config_path() -> Path:
    if env := os.environ.get("TRIVIUM_CONFIG"):
        return Path(env).expanduser()
    if USER_CONFIG.exists():
        return USER_CONFIG
    return Path(str(files("trivium") / "targets.yaml"))


def calibration_path() -> Path:
    """Where `ask calibrate --write` keeps fitted temperatures, apart from the hand-edited config."""
    if env := os.environ.get("TRIVIUM_CALIBRATION"):
        return Path(env).expanduser()
    return USER_CONFIG.parent / "calibration.yaml"


def load(path: Path | None = None) -> dict:
    cfg = yaml.safe_load((path or config_path()).read_text())
    written = calibration_path()
    if written.exists():
        # Fitted values override the config's calibration block, backend by backend.
        cfg["calibration"] = {**(cfg.get("calibration") or {}), **(yaml.safe_load(written.read_text()) or {})}
    validate(cfg)
    return cfg


def write_calibration(backend: str, temperatures: dict) -> Path:
    path = calibration_path()
    current = yaml.safe_load(path.read_text()) if path.exists() else {}
    current = current or {}
    current[backend] = {q: round(float(t), 4) for q, t in temperatures.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Written by `ask calibrate --write`. Per backend, per question: p ** (1/T).\n"
                    + yaml.safe_dump(current, sort_keys=False))
    return path


def temperatures(cfg: dict, backend: str) -> dict:
    """Per-question temperatures fitted by `ask calibrate` for this backend; empty means raw."""
    return (cfg.get("calibration") or {}).get(backend) or {}


def validate(cfg: dict) -> None:
    questions, targets = cfg["questions"], cfg["targets"]
    if cfg["router"].get("backend", "semif") not in BACKENDS:
        raise ValueError(f"router.backend must be one of {BACKENDS}")
    if cfg["router"].get("runtime", "mlx") not in RUNTIMES:
        raise ValueError(f"router.runtime must be one of {RUNTIMES}")
    for q in cfg["router"].get("hybrid_laya", []):
        if q not in questions:
            raise ValueError(f"router.hybrid_laya: unknown question {q!r}")
    for backend, temps in (cfg.get("calibration") or {}).items():
        if backend not in BACKENDS:
            raise ValueError(f"calibration: unknown backend {backend!r}")
        for q, t in (temps or {}).items():
            if q not in questions or not (isinstance(t, (int, float)) and t > 0):
                raise ValueError(f"calibration.{backend}.{q}: needs a known question and a positive number")
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
