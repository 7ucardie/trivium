"""Laya as an alternative router backend: a 421M encoder, one forward pass, no generation."""

from __future__ import annotations

import threading
import time


class LayaEngine:
    def __init__(self, router_cfg: dict):
        try:
            import laya
        except ImportError as error:
            raise RuntimeError("Install the Laya extra: uv sync --extra laya") from error

        started = time.perf_counter()
        self.agent = laya.load(router_cfg.get("laya_model", "convaiinnovations/laya"),
                               subfolder=router_cfg.get("laya_subfolder"))
        self.load_seconds = time.perf_counter() - started
        self.metadata = {"source": f"laya:{router_cfg.get('laya_subfolder') or 'english'}"}
        self.lock = threading.Lock()

    def route(self, state: dict, questions: dict) -> tuple[dict, dict]:
        laya_questions = {
            qid: {"type": "choice", "instructions": q["question"], "criteria": dict(q["options"])}
            for qid, q in questions.items()
        }
        started = time.perf_counter()
        with self.lock:
            result = self.agent.predict(state, laya_questions)
        timing = {"total_seconds": time.perf_counter() - started}
        probs = {qid: {o: float(p) for o, p in a["probabilities"].items()}
                 for qid, a in result["answers"].items()}
        return probs, timing

    def generate(self, prompt: str, max_tokens: int = 2048):
        raise RuntimeError("Laya only decides; it cannot answer prompts. Route local targets elsewhere.")
