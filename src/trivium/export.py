"""Turn the decision log into labelled prompts for `ask eval` and `ask calibrate`.

Feedback only says which target a prompt should have gone to, while eval and calibration need an
answer per question. So each row is pre-filled: with the router's own answers, or, when the feedback
names another target, with the most likely answers that route there. Rows marked `needs_review`
still need a human to check the labels.
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone

from .policy import decide


def labels_for_target(cfg: dict, answers: dict, target: str) -> dict | None:
    """The most probable combination of answers, under the router's scores, that routes to target."""
    questions = list(answers)
    options = [list(answers[q]["probabilities"].items()) for q in questions]
    best, best_p = None, -1.0
    no_floor = {**cfg, "min_confidence": {}}
    for combo in itertools.product(*options):
        joint = 1.0
        for _, p in combo:
            joint *= p
        if joint <= best_p:
            continue
        labels = {q: option for q, (option, _) in zip(questions, combo)}
        if decide(no_floor, {q: {"choice": o, "p": 1.0} for q, o in labels.items()}).target == target:
            best, best_p = labels, joint
    return best


def rows_from_log(records: list[dict], cfg: dict, only_rated: bool = False,
                  since: float | None = None) -> tuple[list[dict], dict]:
    feedback = {r["decision"]: r for r in records if r.get("type") == "feedback"}
    # The terminal app and the dashboard log a separate "pick" when another target is chosen.
    picks = {r["decision"]: r["target"] for r in records if r.get("type") == "pick"}
    rows: dict[tuple, dict] = {}
    skipped = {"no router answers": 0, "unrated": 0, "before --since": 0, "unknown questions": 0}
    for r in records:
        if r.get("type") != "decision":
            continue
        if since and r.get("ts", 0) < since:
            skipped["before --since"] += 1
            continue
        answers = r.get("answers") or {}
        if not answers:
            skipped["no router answers"] += 1  # `--to` decisions never ran the router
            continue
        if set(answers) != set(cfg["questions"]):
            skipped["unknown questions"] += 1  # logged under an older question set
            continue
        fb = feedback.get(r["id"])
        picked = r.get("reason") == "picked with --ask" or r["id"] in picks
        if r["id"] in picks:
            r = {**r, "target": picks[r["id"]]}
        if only_rated and not fb and not picked:
            skipped["unrated"] += 1
            continue
        router_labels = {q: a["choice"] for q, a in answers.items()}
        should = (fb or {}).get("should") or (r["target"] if picked else None)
        if fb and fb.get("verdict") == "good" and not should:
            label, expect = "confirmed-target", router_labels
        elif should and should != r.get("routed"):
            inferred = labels_for_target(cfg, answers, should)
            label, expect = ("inferred-from-feedback", inferred) if inferred else ("router", router_labels)
        else:
            label, expect = "router", router_labels
        rows[(r["prompt"], r.get("repo"))] = {
            "prompt": r["prompt"],
            "repo": r.get("repo"),
            "expect": expect,
            "label": label,
            "needs_review": label != "confirmed-target",
            "source": {"decision": r["id"], "routed": r.get("routed"), "target": r.get("target"),
                       "verdict": (fb or {}).get("verdict"), "should": should},
        }
    return list(rows.values()), skipped


def since_timestamp(day: str) -> float:
    return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()


def write(rows: list[dict], path: str) -> None:
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
