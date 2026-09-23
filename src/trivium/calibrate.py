"""Fit one temperature per question so router confidences mean what they say."""

from __future__ import annotations

import math

from .policy import temper

# 0.25 .. ~9.8 in 6% steps. Bounded on purpose: with a few dozen labels a nearly separable
# question drives the fit to an extreme temperature that says more about the sample than the model.
GRID = [round(0.25 * 1.06 ** i, 4) for i in range(64)]


def at_edge(temperature: float) -> bool:
    return temperature in (GRID[0], GRID[-1])


def nll(samples: list[tuple[dict, str]], temperature: float) -> float:
    """Mean negative log-likelihood of the true option after tempering."""
    return -sum(math.log(max(temper(p, temperature)[truth], 1e-12)) for p, truth in samples) / len(samples)


def ece(samples: list[tuple[dict, str]], temperature: float = 1.0, bins: int = 10) -> float:
    """Expected calibration error of the top choice: |confidence - accuracy|, weighted by bin size."""
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for probs, truth in samples:
        tempered = temper(probs, temperature)
        choice = max(tempered, key=tempered.get)
        confidence = tempered[choice]
        buckets[min(int(confidence * bins), bins - 1)].append((confidence, choice == truth))
    total = len(samples)
    return sum(
        len(b) / total * abs(sum(c for c, _ in b) / len(b) - sum(ok for _, ok in b) / len(b))
        for b in buckets if b
    )


def fit(samples: list[tuple[dict, str]]) -> float:
    """The grid temperature with the lowest NLL. A grid is plenty for one scalar and cannot diverge."""
    return min(GRID, key=lambda t: nll(samples, t))
