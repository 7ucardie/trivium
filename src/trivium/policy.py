"""Turn router answers into a target. Pure functions: no model, no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field

# Order used when `--via` has no same-tier target at the requested vendor.
TIERS = ["local", "fast", "mid", "frontier", "max"]


@dataclass
class Decision:
    target: str
    reason: str
    answers: dict = field(default_factory=dict)  # qid -> {"choice", "p", "probabilities"}
    unsure: list = field(default_factory=list)


def summarize(results: dict) -> dict:
    """{qid: {option: p}} -> {qid: {"choice", "p", "probabilities"}}."""
    out = {}
    for qid, probs in results.items():
        choice = max(probs, key=probs.get)
        out[qid] = {"choice": choice, "p": probs[choice], "probabilities": probs}
    return out


def _matches(when: dict, answers: dict) -> bool:
    for qid, want in when.items():
        allowed = want if isinstance(want, list) else [want]
        if answers[qid]["choice"] not in allowed:
            return False
    return True


def decide(cfg: dict, answers: dict) -> Decision:
    floors = cfg.get("min_confidence", {})
    unsure = [q for q, a in answers.items() if a["p"] < floors.get(q, 0.0)]
    if unsure:
        detail = ", ".join(f"{q}={answers[q]['choice']}@{answers[q]['p']:.2f}" for q in unsure)
        return Decision(cfg["fallback"], f"unsure ({detail})", answers, unsure)
    for i, rule in enumerate(cfg["rules"]):
        if _matches(rule["when"], answers):
            return Decision(rule["to"], f"rule {i + 1}: {rule['when']}", answers)
    return Decision(cfg["default"], "no rule matched", answers)


def via(cfg: dict, target: str, vendor: str) -> str:
    """Swap target for the closest-tier target at `vendor` (local never counts as a match)."""
    targets = cfg["targets"]
    if targets[target]["vendor"] == vendor:
        return target
    tier = targets[target]["tier"]
    tier = "fast" if tier == "local" else tier
    rank = TIERS.index(tier)
    candidates = [(n, t) for n, t in targets.items() if t["vendor"] == vendor]
    if not candidates:
        raise ValueError(f"no targets for vendor {vendor!r}")
    # Prefer the exact tier, then the nearest tier above (never quietly downgrade), then below.
    def distance(item):
        r = TIERS.index(item[1]["tier"])
        return (abs(r - rank), r < rank)
    return min(candidates, key=distance)[0]


def resolve_to(cfg: dict, name: str) -> str:
    """`--to` accepts a target name, a vendor, or a model id."""
    targets = cfg["targets"]
    if name in targets:
        return name
    for n, t in targets.items():
        if t["model"] == name:
            return n
    short = {n.split("-", 1)[1]: n for n in targets if "-" in n}
    if name in short:
        return short[name]
    raise ValueError(f"unknown target {name!r}; try one of: {', '.join(targets)}")
