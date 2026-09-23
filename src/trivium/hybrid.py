"""Ask each question of the router that answers it best: Laya for some, semif for the rest."""

from __future__ import annotations

import time


class HybridEngine:
    def __init__(self, router_cfg: dict, semif=None, laya=None):
        from .engine import Engine
        from .laya_engine import LayaEngine

        self.laya_questions = set(router_cfg.get("hybrid_laya", ["tools"]))
        started = time.perf_counter()
        self.semif = semif or Engine(router_cfg)
        self.laya = laya or LayaEngine(router_cfg)
        self.load_seconds = time.perf_counter() - started
        self.metadata = {"source": f"hybrid:semif+laya({','.join(sorted(self.laya_questions))})"}

    def route(self, state: dict, questions: dict) -> tuple[dict, dict]:
        to_laya = {q: v for q, v in questions.items() if q in self.laya_questions}
        to_semif = {q: v for q, v in questions.items() if q not in self.laya_questions}
        probs, timing = {}, {}
        # semif's shared prefill needs at least one row, Laya is happy with any subset.
        if to_semif:
            p, t = self.semif.route(state, to_semif)
            probs.update(p)
            timing["semif_seconds"] = t.get("total_seconds")
        if to_laya:
            p, t = self.laya.route(state, to_laya)
            probs.update(p)
            timing["laya_seconds"] = t.get("total_seconds")
        return {q: probs[q] for q in questions}, timing

    def generate(self, prompt: str, max_tokens: int = 2048):
        return self.semif.generate(prompt, max_tokens)
