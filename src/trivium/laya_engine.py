"""Laya as an alternative router backend: a 421M encoder, one forward pass, no generation."""

from __future__ import annotations

import threading
import time

from .state import clip


class LayaEngine:
    def __init__(self, router_cfg: dict):
        try:
            import laya
        except ImportError as error:
            raise RuntimeError("Install the Laya extra: uv sync --extra laya") from error

        started = time.perf_counter()
        source = router_cfg.get("laya_model", "convaiinnovations/laya")
        if revision := router_cfg.get("laya_revision"):
            # laya.load has no revision argument, so pin the weights by loading a pinned local snapshot.
            from huggingface_hub import snapshot_download

            source = snapshot_download(source, revision=revision)
        self.agent = laya.load(source, subfolder=router_cfg.get("laya_subfolder"))
        self.load_seconds = time.perf_counter() - started
        self.metadata = {"source": f"laya:{router_cfg.get('laya_subfolder') or 'english'}"}
        self.max_request_chars = router_cfg.get("laya_max_request_chars", 300)
        self.lock = threading.Lock()

    def route(self, state: dict, questions: dict) -> tuple[dict, dict]:
        laya_questions = {
            qid: {"type": "choice", "instructions": q["question"], "criteria": dict(q["options"])}
            for qid, q in questions.items()
        }
        # Laya reads about 320 tokens of state and cuts the end, which dropped the repository sentence
        # on long prompts. Moving that sentence first cost 9 of 36 tools answers on short prompts, so
        # keep the order and shorten the request instead (head and tail, where the question usually is).
        if isinstance(state, dict) and "request" in state:
            state = {**state, "request": clip(state["request"], self.max_request_chars)}
        started = time.perf_counter()
        with self.lock:
            result = self.agent.predict(state, laya_questions)
        timing = {"total_seconds": time.perf_counter() - started}
        probs = {qid: {o: float(p) for o, p in a["probabilities"].items()}
                 for qid, a in result["answers"].items()}
        return probs, timing

    def generate(self, prompt: str, max_tokens: int = 2048):
        raise RuntimeError("Laya only decides; it cannot answer prompts. Route local targets elsewhere.")
