"""The local model: semif option-logit routing and plain generation, sharing one Qwen in memory."""

from __future__ import annotations

import threading
import time


class Engine:
    def __init__(self, router_cfg: dict):
        from semif_phase1 import mlx_backend

        self._semif = mlx_backend
        started = time.perf_counter()
        self.model, self.tokenizer, self.metadata = mlx_backend.load_model(
            router_cfg["model"], router_cfg["revision"], bits=router_cfg.get("bits"),
        )
        self.load_seconds = time.perf_counter() - started
        # MLX is not safe to drive from several threads at once.
        self.lock = threading.Lock()

    def route(self, state: dict, questions: dict) -> tuple[dict, dict]:
        """Score every question against one shared state prefix. Returns ({qid: {option: p}}, timing)."""
        rows = [
            {
                "id": qid,
                "state": state,
                "question": q["question"],
                "options": [{"id": oid, "description": desc} for oid, desc in q["options"].items()],
            }
            for qid, q in questions.items()
        ]
        with self.lock:
            results, timing = self._semif.score_shared(self.model, self.tokenizer, rows, self.metadata)
        probs = {r["id"]: dict(zip(r["option_ids"], r["probabilities"])) for r in results}
        return probs, timing

    def generate(self, prompt: str, max_tokens: int = 2048):
        """Yield text chunks from the same Qwen, thinking disabled."""
        from mlx_lm import stream_generate
        from mlx_lm.sample_utils import make_sampler

        text = self.tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=False, add_generation_prompt=True, enable_thinking=False,
        )
        sampler = make_sampler(temp=0.7, top_p=0.8, top_k=20)
        with self.lock:
            for chunk in stream_generate(self.model, self.tokenizer, text, max_tokens=max_tokens, sampler=sampler):
                yield chunk.text
