"""A small model on top of the router's scores: one logistic regression per question, each reading the
scores of every question. It corrects systematic mistakes of the router. Pure Python, no I/O."""

from __future__ import annotations

import math


def layout(questions: dict) -> dict:
    """{question: [options]} in config order: the order of the features."""
    return {q: list(spec["options"]) for q, spec in questions.items()}


def features(probs: dict, order: dict) -> list[float]:
    return [math.log(max(probs[q][o], 1e-9)) for q, options in order.items() for o in options]


def _softmax(scores: list[float]) -> list[float]:
    top = max(scores)
    exps = [math.exp(s - top) for s in scores]
    total = sum(exps)
    return [e / total for e in exps]


def _fit_one(xs: list[list[float]], labels: list[str], steps: int, l2: float) -> dict:
    classes = sorted(set(labels))
    n, d = len(xs), len(xs[0])
    mean = [sum(x[j] for x in xs) / n for j in range(d)]
    std = [math.sqrt(sum((x[j] - mean[j]) ** 2 for x in xs) / n) or 1.0 for j in range(d)]
    zs = [[(x[j] - mean[j]) / std[j] for j in range(d)] for x in xs]
    weights = [[0.0] * d for _ in classes]
    bias = [0.0] * len(classes)
    truth = [classes.index(label) for label in labels]
    for _ in range(steps):  # plain gradient descent: the loss is convex and the features are standardised
        grad_w = [[l2 / n * w for w in row] for row in weights]
        grad_b = [0.0] * len(classes)
        for z, t in zip(zs, truth):
            p = _softmax([sum(w * v for w, v in zip(row, z)) + b for row, b in zip(weights, bias)])
            for c in range(len(classes)):
                err = (p[c] - (c == t)) / n
                grad_b[c] += err
                row = grad_w[c]
                for j in range(d):
                    row[j] += err * z[j]
        weights = [[w - g for w, g in zip(row, grow)] for row, grow in zip(weights, grad_w)]
        bias = [b - g for b, g in zip(bias, grad_b)]
    # Fold the standardisation into the weights, so applying the model needs only the raw log scores.
    return {c: {"weights": [w / s for w, s in zip(row, std)],
                "bias": b - sum(w * m / s for w, m, s in zip(row, mean, std))}
            for c, row, b in zip(classes, weights, bias)}


def fit(samples: list[tuple[dict, dict]], questions: dict, steps: int = 300, l2: float = 1.0) -> dict:
    """samples: (router scores {q: {option: p}}, labels {q: option}). An option no sample is labelled
    with gets no weights and is never chosen."""
    order = layout(questions)
    xs = [features(probs, order) for probs, _ in samples]
    return {"layout": order, "prompts": len(samples),
            "questions": {q: _fit_one(xs, [labels[q] for _, labels in samples], steps, l2) for q in order}}


def apply(model: dict, probs: dict) -> dict:
    """Router scores -> corrected probabilities, in the same shape."""
    x = features(probs, model["layout"])
    out = {}
    for q, options in model["layout"].items():
        fitted = model["questions"][q]
        known = [o for o in options if o in fitted]
        ps = _softmax([sum(w * v for w, v in zip(fitted[o]["weights"], x)) + fitted[o]["bias"] for o in known])
        out[q] = {**{o: 0.0 for o in options}, **dict(zip(known, ps))}
    return out
