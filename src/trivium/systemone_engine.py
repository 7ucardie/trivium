"""A System One server as the router: any model that answers typed questions over
`POST /v1/systemone` (llama-server with h2o-lightning-4b, Kev, Jev). Decides only."""

from __future__ import annotations

import json
import time
import urllib.request


class SystemOneEngine:
    load_seconds = 0.0  # the model lives in the other server

    def __init__(self, router_cfg: dict):
        self.url = router_cfg.get("systemone_url") or ""
        if not self.url.startswith(("http://", "https://")):
            raise ValueError("the systemone backend needs router.systemone_url, "
                             "e.g. http://127.0.0.1:8080/v1/systemone")
        self.timeout = router_cfg.get("systemone_timeout", 120)
        self.metadata = {"source": f"systemone:{self.url}"}

    def route(self, state: dict, questions: dict) -> tuple[dict, dict]:
        body = {"state": state, "questions": {
            qid: {"type": "choice", "instructions": q["question"], "criteria": dict(q["options"])}
            for qid, q in questions.items()}}
        request = urllib.request.Request(self.url, json.dumps(body).encode(), {"Content-Type": "application/json"})
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                answers = json.load(response)["answers"]
        except OSError as error:  # refused, timed out, or an HTTP error status
            raise RuntimeError(f"the System One server at {self.url} did not answer: {error}") from error
        timing = {"total_seconds": time.perf_counter() - started}
        try:
            probs = {qid: {o: float(answers[qid]["probabilities"][o]) for o in q["options"]}
                     for qid, q in questions.items()}
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError(f"the System One server at {self.url} left out an answer or option: {error}") from error
        return probs, timing

    def generate(self, prompt: str, max_tokens: int = 2048):
        raise RuntimeError("a System One server only decides; it cannot answer prompts.")
