"""The local model: semif option-logit routing and plain generation, sharing one Qwen in memory.

Three runtimes read the same prompt and answer slots through the vendored semif code:
  mlx       Apple Silicon (default)
  torch     CUDA GPUs, or Apple GPUs through MPS; needs the `torch` extra
  llamacpp  CPU, from a local GGUF file; decides only, needs the `llamacpp` extra
"""

from __future__ import annotations

import threading
import time

RUNTIMES = ["mlx", "torch", "llamacpp"]


class Engine:
    def __init__(self, router_cfg: dict):
        self.runtime = router_cfg.get("runtime", "mlx")
        started = time.perf_counter()
        source, revision = router_cfg["model"], router_cfg["revision"]
        if self.runtime == "mlx":
            from ._semif import mlx_backend as scorer

            self.model, self.tokenizer, self.metadata = scorer.load_model(
                source, revision, bits=router_cfg.get("bits"))
        elif self.runtime == "torch":
            from ._semif import core
            from ._semif import shared as scorer

            self.model, self.tokenizer, self.metadata = core.load_causal_model(
                source, revision, device=router_cfg.get("device", "auto"),
                dtype=router_cfg.get("dtype", "bfloat16"))
        elif self.runtime == "llamacpp":
            from ._semif import llamacpp_backend as scorer

            self.model, self.tokenizer, self.metadata = scorer.load_model(
                source, revision, gguf_path(router_cfg), threads=router_cfg.get("llama_threads"))
        else:
            raise ValueError(f"router.runtime must be one of {RUNTIMES}")
        self._scorer = scorer
        self.can_generate = self.runtime != "llamacpp"
        self.load_seconds = time.perf_counter() - started
        # One forward pass at a time: neither MLX, a single GPU nor the llama.cpp context is thread-safe.
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
            results, timing = self._scorer.score_shared(self.model, self.tokenizer, rows, self.metadata)
        probs = {r["id"]: dict(zip(r["option_ids"], r["probabilities"])) for r in results}
        return probs, timing

    def generate(self, prompt: str, max_tokens: int = 2048):
        """Yield text chunks from the same Qwen, thinking disabled."""
        if self.runtime == "llamacpp":
            raise RuntimeError("the llamacpp runtime only decides; local targets are routed to Claude")
        messages = [{"role": "user", "content": prompt}]
        text = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        if self.runtime == "torch":
            yield from self._generate_torch(text, max_tokens)
            return
        from mlx_lm import stream_generate
        from mlx_lm.sample_utils import make_sampler

        sampler = make_sampler(temp=0.7, top_p=0.8, top_k=20)
        with self.lock:
            for chunk in stream_generate(self.model, self.tokenizer, text, max_tokens=max_tokens, sampler=sampler):
                yield chunk.text

    def _generate_torch(self, text: str, max_tokens: int):
        from transformers import TextIteratorStreamer

        inputs = self.tokenizer(text, return_tensors="pt").to(self.model.device)
        streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True)
        kwargs = dict(**inputs, max_new_tokens=max_tokens, do_sample=True, temperature=0.7, top_p=0.8,
                      top_k=20, streamer=streamer)
        with self.lock:
            worker = threading.Thread(target=self.model.generate, kwargs=kwargs, daemon=True)
            worker.start()
            yield from streamer
            worker.join()


def gguf_path(router_cfg: dict) -> str:
    """A local GGUF file, or one downloaded from a pinned Hugging Face revision."""
    if path := router_cfg.get("gguf"):
        return path
    spec = router_cfg.get("gguf_repo")
    if not spec:
        raise ValueError("the llamacpp runtime needs router.gguf (a local file) or router.gguf_repo")
    from huggingface_hub import hf_hub_download

    return hf_hub_download(spec["repo"], spec["file"], revision=spec["revision"])
